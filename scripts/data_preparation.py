import csv
import hashlib
import importlib.metadata
import json
import shutil
from pathlib import Path

import duckdb
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
SOURCE = Path.home() / "Downloads"
DATA = ROOT / "data" / "processed"
REPORTS = ROOT / "reports"
CURRENCIES = {
    "Paris": "EUR", "Rome": "EUR", "New York": "USD", "Sydney": "AUD",
    "Rio de Janeiro": "BRL", "Istanbul": "TRY", "Mexico City": "MXN",
    "Bangkok": "THB", "Cape Town": "ZAR", "Hong Kong": "HKD",
}


def quote(value):
    return "'" + str(value).replace("\\", "/").replace("'", "''") + "'"


def main():
    DATA.mkdir(parents=True, exist_ok=True)
    REPORTS.mkdir(parents=True, exist_ok=True)
    db = duckdb.connect()
    db.execute("SET threads=4")
    for table, filename in [("raw_listings", "Listings.csv"), ("raw_reviews", "Reviews.csv")]:
        staging = DATA / ("staging_" + filename)
        with (SOURCE / filename).open(encoding="latin-1", newline="") as src:
            with staging.open("w", encoding="utf-8", newline="") as dst:
                shutil.copyfileobj(src, dst, length=1024 * 1024)
        db.execute(f"CREATE TABLE {table} AS SELECT * FROM read_csv({quote(staging)}, "
                   "header=true, all_varchar=true, strict_mode=true)")
        staging.unlink()

    def rows(sql):
        cursor = db.execute(sql)
        names = [item[0] for item in cursor.description]
        return [dict(zip(names, row)) for row in cursor.fetchall()]

    def scalar(sql):
        return db.execute(sql).fetchone()[0]

    profile = {}
    for table in ["raw_listings", "raw_reviews"]:
        columns = [row[1] for row in db.execute(f"PRAGMA table_info('{table}')").fetchall()]
        profile[table] = {
            "row_count": scalar(f"SELECT count(*) FROM {table}"),
            "missingness": {
                column: scalar(f'SELECT count(*) FROM {table} WHERE "{column}" IS NULL OR trim("{column}")=\'\'')
                for column in columns
            },
        }
    profile["listing_duplicate_ids"] = scalar(
        "SELECT count(*)-count(DISTINCT listing_id) FROM raw_listings")
    profile["review_id_repeated_rows"] = scalar(
        "SELECT count(*)-count(DISTINCT review_id) FROM raw_reviews")
    profile["review_composite_duplicate_rows"] = scalar(
        "SELECT count(*) FROM raw_reviews") - scalar(
        "SELECT count(*) FROM (SELECT DISTINCT listing_id,review_id,date,reviewer_id FROM raw_reviews)")
    profile["review_listing_review_key_duplicate_rows"] = scalar(
        "SELECT count(*) FROM raw_reviews") - scalar(
        "SELECT count(*) FROM (SELECT DISTINCT listing_id,review_id FROM raw_reviews)")
    profile["invalid_review_numeric_ids"] = rows(
        "SELECT count(*) FILTER(WHERE try_cast(listing_id AS BIGINT) IS NULL) listing_id,"
        "count(*) FILTER(WHERE try_cast(review_id AS BIGINT) IS NULL) review_id,"
        "count(*) FILTER(WHERE try_cast(reviewer_id AS BIGINT) IS NULL) reviewer_id FROM raw_reviews")
    profile["review_id_multi_listing_examples"] = rows(
        "SELECT review_id,count(*) AS rows,count(DISTINCT listing_id) AS listings "
        "FROM raw_reviews GROUP BY review_id HAVING count(DISTINCT listing_id)>1 "
        "ORDER BY rows DESC,review_id LIMIT 10")
    profile["review_orphans"] = scalar(
        "SELECT count(*) FROM raw_reviews r ANTI JOIN raw_listings l USING(listing_id)")
    profile["invalid_review_dates"] = scalar(
        "SELECT count(*) FROM raw_reviews WHERE try_cast(date AS DATE) IS NULL")
    if profile["listing_duplicate_ids"] or profile["review_orphans"] or profile["invalid_review_dates"]:
        raise ValueError(f"Unresolved keys or dates: {profile}")
    db.execute("CREATE TABLE reviews AS SELECT DISTINCT try_cast(listing_id AS BIGINT) listing_id,"
               "try_cast(review_id AS BIGINT) review_id,try_cast(date AS DATE) date,"
               "try_cast(reviewer_id AS BIGINT) reviewer_id FROM raw_reviews")
    db.execute("CREATE TABLE activity AS SELECT listing_id,cast(date_trunc('month',date) AS DATE) "
               "month_start,count(*)::BIGINT review_count FROM reviews GROUP BY 1,2")
    db.execute("CREATE TABLE review_totals AS SELECT listing_id,count(*)::BIGINT review_count,"
               "min(date) first_review_date,max(date) last_review_date FROM reviews GROUP BY 1")
    excluded = {"name", "host_location", "amenities", "latitude", "longitude"}
    integers = {"listing_id", "host_id", "host_total_listings_count", "accommodates",
                "minimum_nights", "maximum_nights"}
    numeric = {"host_response_rate", "host_acceptance_rate", "bedrooms", "price"}
    booleans = {"host_is_superhost", "host_has_profile_pic", "host_identity_verified", "instant_bookable"}
    fields = [r[1] for r in db.execute("PRAGMA table_info('raw_listings')").fetchall()]
    expressions = []
    for field in fields:
        if field in excluded:
            continue
        if field in integers:
            expression = f'try_cast("{field}" AS BIGINT)'
        elif field in numeric or field.startswith("review_scores_"):
            expression = f'try_cast("{field}" AS DOUBLE)'
        elif field == "host_since":
            expression = 'try_cast("host_since" AS DATE)'
        elif field in booleans:
            expression = f"""CASE lower("{field}") WHEN 't' THEN 'true' WHEN 'f' THEN 'false'
                WHEN 'true' THEN 'true' WHEN 'false' THEN 'false' END"""
        else:
            expression = f'nullif(trim("{field}"),\'\')'
        expressions.append(f'{expression} AS "{field}"')
    db.execute("CREATE TABLE typed AS SELECT " + ",".join(expressions) + " FROM raw_listings")
    profile["type_failures"] = {}
    for field in integers | numeric | {"host_since"} | {f for f in fields if f.startswith("review_scores_")}:
        profile["type_failures"][field] = scalar(
            f'SELECT count(*) FROM raw_listings r JOIN typed t ON r.listing_id=cast(t.listing_id AS VARCHAR) '
            f'WHERE r."{field}" IS NOT NULL AND t."{field}" IS NULL')
    profile["invalid_boolean_values"] = {
        field: scalar(f"""SELECT count(*) FROM raw_listings WHERE "{field}" IS NOT NULL
                         AND lower("{field}") NOT IN ('t','f','true','false')""")
        for field in booleans
    }
    profile["invalid_rates"] = rows(
        "SELECT count(*) FILTER(WHERE host_response_rate NOT BETWEEN 0 AND 1) response_rate,"
        "count(*) FILTER(WHERE host_acceptance_rate NOT BETWEEN 0 AND 1) acceptance_rate FROM typed")
    db.execute("CREATE TABLE currencies(city VARCHAR,currency_code VARCHAR)")
    db.executemany("INSERT INTO currencies VALUES (?,?)", list(CURRENCIES.items()))
    db.execute("""CREATE TABLE price_thresholds AS SELECT city,
        quantile_cont(price,0.25) q1,quantile_cont(price,0.5) median,
        quantile_cont(price,0.75) q3,quantile_cont(price,0.99) p99,
        max(price) maximum FROM typed WHERE price>0 GROUP BY city""")
    db.execute("""CREATE TABLE listings AS SELECT t.*,c.currency_code,
        coalesce(r.review_count,0)::BIGINT review_count,r.first_review_date,r.last_review_date,
        CASE WHEN t.price>0 THEN t.price END price_valid,
        CASE WHEN t.price<=0 OR t.price IS NULL THEN NULL WHEN t.price<=p.q1 THEN 'Q1'
             WHEN t.price<=p.median THEN 'Q2' WHEN t.price<=p.q3 THEN 'Q3' ELSE 'Q4' END price_band,
        CASE WHEN accommodates IS NULL OR accommodates<=0 THEN 'Unknown'
             WHEN accommodates<=2 THEN '1-2 guests' WHEN accommodates<=4 THEN '3-4 guests'
             WHEN accommodates<=6 THEN '5-6 guests' ELSE '7+ guests' END capacity_band
        FROM typed t LEFT JOIN review_totals r USING(listing_id)
        LEFT JOIN currencies c USING(city) LEFT JOIN price_thresholds p USING(city)""")
    for table, filename in [("listings", "listings.csv"), ("activity", "review_activity.csv"),
                            ("currencies", "cities.csv")]:
        order = "listing_id,month_start" if table == "activity" else ("city" if table == "currencies" else "listing_id")
        db.execute(f"COPY (SELECT * FROM {table} ORDER BY {order}) TO {quote(DATA / filename)} (HEADER, DELIMITER ',')")
    summary = {
        "source_profile": profile,
        "clean_review_count": scalar("SELECT count(*) FROM reviews"),
        "activity_rows": scalar("SELECT count(*) FROM activity"),
        "listing_count": scalar("SELECT count(*) FROM listings"),
        "host_count": scalar("SELECT count(DISTINCT host_id) FROM listings"),
        "review_date_range": rows("SELECT min(date) first_date,max(date) last_date FROM reviews")[0],
        "city_breakdown": rows("""SELECT city,currency_code,count(*) listings,sum(review_count) reviews,
            count(*) FILTER(WHERE review_scores_rating IS NOT NULL) rated_listings,
            avg(review_scores_rating) mean_rating_100,
            count(*) FILTER(WHERE price<=0) nonpositive_prices,
            count(*) FILTER(WHERE district IS NULL) missing_district,
            count(*) FILTER(WHERE host_is_superhost='true') superhost_listings
            FROM listings GROUP BY 1,2 ORDER BY listings DESC"""),
        "city_price_quantiles": rows("""SELECT p.*,count(*) FILTER(WHERE l.price>p.p99) above_p99,
            count(*) FILTER(WHERE l.price>p.q3+1.5*(p.q3-p.q1)) above_upper_iqr_fence
            FROM price_thresholds p JOIN listings l USING(city) GROUP BY ALL ORDER BY city"""),
        "room_breakdown": rows("""SELECT city,room_type,count(*) listings,median(price_valid) median_price,
            avg(review_scores_rating) mean_rating_100,sum(review_count) reviews
            FROM listings GROUP BY 1,2 ORDER BY city,listings DESC"""),
        "property_breakdown": rows("""SELECT city,property_type,count(*) listings,
            median(price_valid) median_price FROM listings GROUP BY 1,2 ORDER BY city,listings DESC"""),
        "host_stats_listing_weighted": rows("""SELECT host_is_superhost,count(*) listings,
            count(review_scores_rating) rated_listings,avg(review_scores_rating) mean_rating_100,
            avg(host_response_rate) mean_response_rate,count(host_response_rate) observed_response_rates,
            avg(host_acceptance_rate) mean_acceptance_rate,count(host_acceptance_rate) observed_acceptance_rates,
            avg(review_count) mean_lifetime_reviews FROM listings GROUP BY 1 ORDER BY 1"""),
        "score_comparisons": rows("""SELECT city,price_band,count(*) listings,
            count(review_scores_rating) rated_listings,avg(review_scores_rating) mean_rating_100,
            avg(review_scores_value) mean_value_10 FROM listings WHERE price_band IS NOT NULL
            GROUP BY 1,2 ORDER BY 1,2"""),
        "review_top_listings": rows("""SELECT listing_id,city,room_type,review_count,review_scores_rating
            FROM listings ORDER BY review_count DESC,listing_id LIMIT 20"""),
        "monthly_trends": rows("""SELECT month_start,sum(review_count)::BIGINT review_count
            FROM activity GROUP BY 1 ORDER BY 1"""),
        "city_monthly_trends": rows("""SELECT l.city,a.month_start,sum(a.review_count)::BIGINT review_count
            FROM activity a JOIN listings l USING(listing_id) GROUP BY 1,2 ORDER BY 1,2"""),
        "schema": rows("DESCRIBE listings"),
    }
    frame = db.execute("SELECT city,price_valid,review_scores_rating,review_count FROM listings").df()
    summary["within_city_spearman"] = []
    for city, group in frame.groupby("city"):
        paired = group[["price_valid", "review_scores_rating"]].dropna()
        corr = paired.rank().corr().iloc[0, 1]
        summary["within_city_spearman"].append(
            {"city": city, "pairs": len(paired), "price_rating_rho": float(corr)})
    summary["date_quality"] = rows("""SELECT
        count(*) FILTER(WHERE host_since IS NULL) missing_host_since,
        min(host_since) earliest_host_since,max(host_since) latest_host_since,
        count(*) FILTER(WHERE minimum_nights>maximum_nights) inverted_stay_limits,
        count(*) FILTER(WHERE bedrooms IS NULL) missing_bedrooms,
        count(*) FILTER(WHERE price<=0) nonpositive_prices,
        count(*) FILTER(WHERE review_scores_rating NOT BETWEEN 0 AND 100) out_of_range_rating
        FROM listings""")[0]
    summary["score_ranges"] = {
        field: rows(f'SELECT min("{field}") minimum,max("{field}") maximum,'
                    f'count(*) FILTER(WHERE "{field}" NOT BETWEEN 0 AND '
                    f'{100 if field == "review_scores_rating" else 10}) out_of_range FROM listings')[0]
        for field in fields if field.startswith("review_scores_")
    }
    manifest = {}
    for filename in ["Listings.csv", "Reviews.csv", "Listings_data_dictionary.csv", "Reviews_data_dictionary.csv"]:
        source = SOURCE / filename
        manifest[filename] = {"path": str(source), "bytes": source.stat().st_size,
                              "sha256": hashlib.file_digest(source.open("rb"), "sha256").hexdigest()}
    summary["source_manifest"] = manifest
    (REPORTS / "analysis_summary.json").write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")
    packages = ["duckdb", "pandas", "matplotlib", "pillow", "python-docx", "reportlab", "pywinauto"]
    versions = []
    for package in packages:
        try:
            marker = '; sys_platform == "win32"' if package == "pywinauto" else ""
            versions.append(f"{package}=={importlib.metadata.version(package)}{marker}")
        except importlib.metadata.PackageNotFoundError:
            pass
    (ROOT / "requirements.txt").write_text("\n".join(versions) + "\n", encoding="utf-8")
    print(json.dumps({key: summary[key] for key in ["listing_count", "clean_review_count", "activity_rows",
                                                  "host_count", "review_date_range"]}, default=str, indent=2))


if __name__ == "__main__":
    main()

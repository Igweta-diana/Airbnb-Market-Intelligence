# AnalystLab Africa Week 1 – Airbnb Market Intelligence

**Track A: Data Analytics**

## Project overview

This project analyses Airbnb listings and reviews across ten cities. The aim is to understand listing distribution, pricing, host performance and review activity, and use the findings to support market decisions.

The project uses Python, DuckDB and Power BI. No Excel is required.

## 1. Running the project

Run the following commands from the project folder using Python 3.12:

```powershell
python -m pip install -r requirements.txt
python scripts\prepare_data.py
```

The scripts use the original CSV files in the Downloads folder. The original files are not modified.

## 2. Data used

The analysis uses four source files:

- Listings.csv
- Reviews.csv
- Listings_data_dictionary.csv
- Reviews_data_dictionary.csv

The dataset contains 279,712 listings and 5,373,143 reviews across ten cities.

## 3. Project outputs

The project folder contains:

- **Processed data:** cleaned listings, review activity and city information.
- **Reports containing&#x20;**&#x65;xecutive summary, data quality assessment, KPI definitions and validation results.
- **Power BI dashboard:** four pages covering market overview, pricing and property, host performance and review activity.
- **Screenshots:** dashboard pages and selected filtered views.
- **Scripts:** Python and SQL scripts used to prepare and validate the data.

The final dashboard is saved as:

`powerbi\Airbnb_Market_Intelligence.pbix`

It contains embedded data and can be opened in Power BI Desktop.

## 4. Dashboard structure

The dashboard has four pages:

1. **Market Overview** – listing distribution and market trends.
2. **Pricing & Property** – local prices and property types.
3. **Host Performance** – host status and listing scores.
4. **Review Activity & Listing Scores** – review trends and ratings.

Each page has city, room type and property type filters. The review-month filter is available on the fourth page.

## 5. Validation

The project has undergone three separate levels of testing:

- **Source data:** 29 of 29 checks passed.
- **Power BI model:** 377 of 377 checks passed.
- **Dashboard interface:** 51 of 51 checks passed.

The release checklist recorded 15 passed items and one item not tested. The outstanding test is refreshing the dashboard after moving the project folder to another location.

## 6. Opening and refreshing the dashboard

Open the PBIX file in Power BI Desktop. The embedded data allows you to view the dashboard without reconnecting to the original CSV files.

If the project folder is moved, update the `DataFolder` parameter to the new `data\processed` folder before refreshing. This relocation test has not yet been completed.

## 8. Limitations

The data covers review dates from November 2008 to March 2021 and should not be treated as a picture of the current Airbnb market.

The analysis does not measure bookings, occupancy, revenue or profit because the required data is not available. Prices are analysed within each city's local currency and are not converted. District information is only available for New York.

Missing ratings and other fields are retained and reported rather than treated as zero. Extreme prices are also retained for further review.

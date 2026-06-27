{{ config(materialized='table') }}

SELECT DISTINCT
    date_id,
    date, day, year, month, quarter, month_name, day_name,
    day_of_week, day_of_year, week_of_year, is_weekend,
    is_holyday, holyday_name, is_workday, is_leap_year,
    is_month_start, is_month_end, is_quarter_start, is_quarter_end,
    is_year_start, is_year_end, is_week_start, is_week_end,
    season, is_winter, is_spring, is_summer, is_autumn
FROM 
    {{ source('raw_data', 'STG_ALL_SELLERS_PRODUCTS') }}
QUALIFY ROW_NUMBER() OVER(PARTITION BY time_id ORDER BY time_id) = 1
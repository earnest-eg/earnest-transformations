{{ config(materialized='table') }}

SELECT DISTINCT
    time_id,
    time_12, time_24, hour_12, hour_24, minute, second,
    meridiem, is_am, is_pm, TIMESTAMP_TIMEZONE,part_of_day, is_morning,
    is_afternoon, is_evening, is_night, is_noon,
    is_midnight, is_midday
FROM 
    {{ source('raw_data', 'STG_ALL_SELLERS_PRODUCTS') }}
QUALIFY ROW_NUMBER() OVER(PARTITION BY time_id ORDER BY time_id) = 1
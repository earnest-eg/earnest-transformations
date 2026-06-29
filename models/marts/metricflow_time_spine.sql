{{ config(
    materialized='table',
    meta={
        'time_spine': {
            'standard_granularity_column': 'date_day'
        }
    }
) }}

SELECT
    DATE_TRUNC('day', date) AS date_day
FROM {{ ref('dim_date') }}
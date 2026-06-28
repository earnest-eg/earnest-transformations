{{ config(materialized='table') }}

WITH days AS (
    SELECT
        DATEADD(day, SEQ4(), '2024-01-01'::DATE) AS date_day
    FROM TABLE(GENERATOR(rowcount => 3650))
)

SELECT CAST(date_day AS DATE) AS date_day
FROM days
SELECT
    date_id,
    is_winter,
    is_spring,
    is_summer,
    is_autumn
FROM {{ ref('dim_date') }}
WHERE (
    CASE WHEN UPPER(CAST(is_winter AS VARCHAR)) IN ('TRUE', '1') THEN 1 ELSE 0 END +
    CASE WHEN UPPER(CAST(is_spring AS VARCHAR)) IN ('TRUE', '1') THEN 1 ELSE 0 END +
    CASE WHEN UPPER(CAST(is_summer AS VARCHAR)) IN ('TRUE', '1') THEN 1 ELSE 0 END +
    CASE WHEN UPPER(CAST(is_autumn AS VARCHAR)) IN ('TRUE', '1') THEN 1 ELSE 0 END
) != 1

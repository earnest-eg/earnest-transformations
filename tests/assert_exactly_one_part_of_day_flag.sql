SELECT
    time_id,
    is_morning,
    is_afternoon,
    is_evening,
    is_night
FROM {{ ref('dim_time') }}
WHERE (
    CASE WHEN UPPER(CAST(is_morning   AS VARCHAR)) IN ('TRUE', '1') THEN 1 ELSE 0 END +
    CASE WHEN UPPER(CAST(is_afternoon AS VARCHAR)) IN ('TRUE', '1') THEN 1 ELSE 0 END +
    CASE WHEN UPPER(CAST(is_evening   AS VARCHAR)) IN ('TRUE', '1') THEN 1 ELSE 0 END +
    CASE WHEN UPPER(CAST(is_night     AS VARCHAR)) IN ('TRUE', '1') THEN 1 ELSE 0 END
) != 1

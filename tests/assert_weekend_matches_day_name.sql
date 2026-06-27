SELECT
    date_id,
    day_name,
    is_weekend
FROM {{ ref('dim_date') }}
WHERE
    (UPPER(CAST(is_weekend AS VARCHAR)) IN ('TRUE', '1') AND day_name NOT IN ('Friday', 'Saturday'))
    OR
    (UPPER(CAST(is_weekend AS VARCHAR)) IN ('FALSE', '0') AND day_name IN ('Friday', 'Saturday'))
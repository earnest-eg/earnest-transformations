SELECT
    time_id,
    meridiem,
    is_am,
    is_pm
FROM {{ ref('dim_time') }}
WHERE
    (UPPER(CAST(is_am AS VARCHAR)) IN ('TRUE', '1') AND UPPER(CAST(is_pm AS VARCHAR)) IN ('TRUE', '1'))
    OR
    (UPPER(CAST(is_am AS VARCHAR)) IN ('FALSE', '0') AND UPPER(CAST(is_pm AS VARCHAR)) IN ('FALSE', '0'))
    OR
    (meridiem = 'AM' AND UPPER(CAST(is_am AS VARCHAR)) NOT IN ('TRUE', '1'))
    OR
    (meridiem = 'PM' AND UPPER(CAST(is_pm AS VARCHAR)) NOT IN ('TRUE', '1'))

SELECT
    date_id,
    month,
    quarter
FROM {{ ref('dim_date') }}
WHERE
    (quarter = 1 AND month NOT IN (1, 2, 3))
    OR (quarter = 2 AND month NOT IN (4, 5, 6))
    OR (quarter = 3 AND month NOT IN (7, 8, 9))
    OR (quarter = 4 AND month NOT IN (10, 11, 12))

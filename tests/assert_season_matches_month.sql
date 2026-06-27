SELECT
    date_id,
    month,
    season
FROM {{ ref('dim_date') }}
WHERE
    (season = 'Winter' AND month NOT IN (12, 1, 2))
    OR (season = 'Spring' AND month NOT IN (3, 4, 5))
    OR (season = 'Summer' AND month NOT IN (6, 7, 8))
    OR (season = 'Autumn' AND month NOT IN (9, 10, 11))

SELECT
    f.fact_id,
    f.time_id
FROM {{ ref('fact_product') }} f
LEFT JOIN {{ ref('dim_time') }} t
    ON f.time_id = t.time_id
WHERE t.time_id IS NULL

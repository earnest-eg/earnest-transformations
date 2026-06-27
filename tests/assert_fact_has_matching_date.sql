SELECT
    f.fact_id,
    f.date_id
FROM {{ ref('fact_product') }} f
LEFT JOIN {{ ref('dim_date') }} d
    ON f.date_id = d.date_id
WHERE d.date_id IS NULL

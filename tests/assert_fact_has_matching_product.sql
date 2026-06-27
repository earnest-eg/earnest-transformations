SELECT
    f.fact_id,
    f.product_sk
FROM {{ ref('fact_product') }} f
LEFT JOIN {{ ref('dim_product') }} p
    ON f.product_sk = p.product_sk
WHERE p.product_sk IS NULL

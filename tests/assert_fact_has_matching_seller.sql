SELECT
    f.fact_id,
    f.seller_sk
FROM {{ ref('fact_product') }} f
LEFT JOIN {{ ref('dim_seller') }} s
    ON f.seller_sk = s.seller_sk
WHERE s.seller_sk IS NULL

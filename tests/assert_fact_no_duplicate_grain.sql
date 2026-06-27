SELECT
    product_sk,
    date_id,
    time_id,
    COUNT(*) AS row_count
FROM {{ ref('fact_product') }}
GROUP BY product_sk, date_id, time_id
HAVING COUNT(*) > 1

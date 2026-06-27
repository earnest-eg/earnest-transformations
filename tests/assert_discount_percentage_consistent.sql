SELECT
    fact_id,
    product_old_price,
    product_current_price,
    product_discount_percentage,
    CASE
        WHEN product_old_price > 0
        THEN ABS(product_discount_percentage
                 - ((product_old_price - product_current_price) / product_old_price * 100))
        ELSE 0
    END AS pct_diff
FROM {{ ref('fact_product') }}
WHERE product_has_discount = 1
  AND product_old_price > 0
  AND ABS(product_discount_percentage
          - ((product_old_price - product_current_price) / product_old_price * 100)) > 0.5

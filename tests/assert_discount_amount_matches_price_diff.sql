SELECT
    fact_id,
    product_old_price,
    product_current_price,
    product_discount_amount,
    ABS(product_discount_amount - (product_old_price - product_current_price)) AS diff
FROM {{ ref('fact_product') }}
WHERE product_has_discount = 1
  AND ABS(product_discount_amount - (product_old_price - product_current_price)) > 0.01

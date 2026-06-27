SELECT
    fact_id,
    product_has_discount,
    product_discount_amount,
    product_discount_percentage,
    product_current_price,
    product_old_price
FROM {{ ref('fact_product') }}
WHERE product_has_discount = 1
  AND (product_discount_amount <= 0 OR product_discount_percentage <= 0)

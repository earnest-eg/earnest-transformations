SELECT
    product_sk,
    product_name,
    product_has_image_url,
    product_image_url
FROM {{ ref('dim_product') }}
WHERE
    (product_has_image_url = 1 AND LOWER(product_image_url) = 'missing_url')
    OR
    (product_has_image_url = 0 AND LOWER(product_image_url) != 'missing_url')

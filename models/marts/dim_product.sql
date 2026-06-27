{{ config(materialized='table') }}

SELECT
    md5(product_url) AS product_sk,
    product_name,
    product_brand,
    product_category,
    product_subcategory,
    product_url,
    product_has_image_url,
    product_image_url,
    product_has_ram,
    product_has_storage,
    product_ram,
    product_storage
FROM {{ source('raw_data', 'STG_ALL_SELLERS_PRODUCTS') }}

QUALIFY ROW_NUMBER() OVER(
    PARTITION BY product_url 
    ORDER BY date_id DESC, time_id DESC
) = 1
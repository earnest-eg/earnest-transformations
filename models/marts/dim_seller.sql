{{ config(materialized='table') }}

SELECT DISTINCT
    md5(product_seller) AS seller_sk,
    product_seller,
    product_is_talabat_seller
FROM 
    {{ source('raw_data', 'STG_ALL_SELLERS_PRODUCTS') }}

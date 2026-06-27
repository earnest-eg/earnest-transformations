{{ config(materialized='table') }}

SELECT
    md5(concat(product_url, cast(date_id as varchar), cast(time_id as varchar), product_seller)) AS fact_id,
    md5(product_url) AS product_sk, 
    md5(product_seller) AS seller_sk,
    date_id, 
    time_id, 
    
    product_current_price,
    product_old_price,
    product_discount_amount,
    product_discount_percentage,
    product_has_discount,
    product_availability,
    product_count,
    product_weight,
    product_measuring_unit,
    
FROM 
    {{ source('raw_data', 'STG_ALL_SELLERS_PRODUCTS') }}


QUALIFY ROW_NUMBER() OVER(
    PARTITION BY product_url, date_id, time_id 
    ORDER BY date_id DESC
) = 1
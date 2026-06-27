WITH source_count AS (
    SELECT COUNT(*) AS cnt
    FROM (
        SELECT
            product_url, date_id, time_id
        FROM {{ source('raw_data', 'STG_ALL_SELLERS_PRODUCTS') }}
        QUALIFY ROW_NUMBER() OVER(
            PARTITION BY product_url, date_id, time_id
            ORDER BY date_id DESC
        ) = 1
    )
),

fact_count AS (
    SELECT COUNT(*) AS cnt
    FROM {{ ref('fact_product') }}
)

SELECT
    s.cnt AS source_rows,
    f.cnt AS fact_rows
FROM source_count s
CROSS JOIN fact_count f
WHERE s.cnt != f.cnt

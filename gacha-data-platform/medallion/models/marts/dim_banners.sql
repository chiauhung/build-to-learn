{{ config(materialized='table', schema='gold') }}

-- Sourced from dbt seed: seeds/banners.csv
with banners as (
    select * from {{ ref('banners') }}
),

final as (
    select
        banner_id,
        name,
        type,
        version,
        rate_up_ssr_id,
        start_date,
        end_date
    from banners
)

select * from final

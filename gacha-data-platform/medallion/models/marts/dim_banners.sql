{{ config(materialized='table', schema='gold') }}

with stg as (
    select * from {{ ref('stg_banners') }}
)

select
    id              as banner_id,
    name,
    type,
    version,
    rate_up_ssr_id,
    start_date,
    end_date
from stg

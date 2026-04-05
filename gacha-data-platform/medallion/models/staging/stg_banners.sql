{{ config(materialized='table', schema='silver') }}

with source as (
    select *
    from {{ source('bronze', 'banners') }}
    where event in ('insert', 'update')
),

parsed as (
    select
        json_extract_string(data, '$.id')                                       as id,
        json_extract_string(data, '$.name')                                     as name,
        json_extract_string(data, '$.type')                                     as type,
        json_extract_string(data, '$.version')                                  as version,
        json_extract_string(data, '$.rate_up_ssr_id')                           as rate_up_ssr_id,
        date '1970-01-01' + cast(json_extract_string(data, '$.start_date') as integer) as start_date,
        date '1970-01-01' + cast(json_extract_string(data, '$.end_date') as integer)   as end_date,
        ingested_at,
        row_number() over (
            partition by json_extract_string(data, '$.id')
            order by ingested_at desc
        ) as rn
    from source
),

deduped as (
    select
        id,
        name,
        type,
        version,
        rate_up_ssr_id,
        start_date,
        end_date
    from parsed
    where rn = 1
)

select * from deduped

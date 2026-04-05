{{ config(materialized='table', schema='silver') }}

with source as (
    select *
    from {{ source('bronze', 'players') }}
    where event in ('insert', 'update')
),

parsed as (
    select
        json_extract_string(data, '$.id')                                           as id,
        json_extract_string(data, '$.username')                                     as username,
        json_extract_string(data, '$.region')                                       as region,
        cast(json_extract_string(data, '$.crystal_balance') as integer)             as crystal_balance,
        cast(json_extract_string(data, '$.registered_at') as timestamp)             as registered_at,
        cast(json_extract_string(data, '$.updated_at') as timestamp)                as updated_at,
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
        username,
        region,
        crystal_balance,
        registered_at,
        updated_at
    from parsed
    where rn = 1
)

select * from deduped

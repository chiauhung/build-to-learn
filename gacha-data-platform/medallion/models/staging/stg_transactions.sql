{{ config(materialized='table', schema='silver') }}

with source as (
    select *
    from {{ source('bronze', 'transactions') }}
    where event in ('insert', 'update')
),

parsed as (
    select
        json_extract_string(data, '$.id')                                           as id,
        json_extract_string(data, '$.player_id')                                    as player_id,
        json_extract_string(data, '$.package_id')                                   as package_id,
        cast(json_extract_string(data, '$.crystals_added') as integer)              as crystals_added,
        cast(json_extract_string(data, '$.amount_usd') as double)                   as amount_usd,
        json_extract_string(data, '$.payment_method')                               as payment_method,
        json_extract_string(data, '$.payment_status')                               as payment_status,
        case
            when json_extract_string(data, '$.is_first_buy') = 'true' then true
            else false
        end                                                                          as is_first_buy,
        cast(json_extract_string(data, '$.transacted_at') as timestamp)             as transacted_at,
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
        player_id,
        package_id,
        crystals_added,
        amount_usd,
        payment_method,
        payment_status,
        is_first_buy,
        transacted_at
    from parsed
    where rn = 1
)

select * from deduped

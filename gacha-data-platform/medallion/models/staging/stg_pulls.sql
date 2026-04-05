{{ config(materialized='table', schema='silver') }}

with source as (
    select *
    from {{ source('bronze', 'pulls') }}
    where event in ('insert', 'update')
),

parsed as (
    select
        json_extract_string(data, '$.id')                                       as id,
        json_extract_string(data, '$.player_id')                                as player_id,
        json_extract_string(data, '$.banner_id')                                as banner_id,
        json_extract_string(data, '$.character_id')                             as character_id,
        json_extract_string(data, '$.rarity')                                   as rarity,
        cast(json_extract_string(data, '$.pity_count') as integer)              as pity_count,
        case
            when json_extract_string(data, '$.is_guaranteed') = 'true' then true
            else false
        end                                                                      as is_guaranteed,
        cast(json_extract_string(data, '$.pull_number') as integer)             as pull_number,
        json_extract_string(data, '$.batch_id')                                 as batch_id,
        cast(json_extract_string(data, '$.crystals_spent') as integer)          as crystals_spent,
        cast(json_extract_string(data, '$.pulled_at') as timestamp)             as pulled_at,
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
        banner_id,
        character_id,
        rarity,
        pity_count,
        is_guaranteed,
        pull_number,
        batch_id,
        crystals_spent,
        pulled_at
    from parsed
    where rn = 1
)

select * from deduped

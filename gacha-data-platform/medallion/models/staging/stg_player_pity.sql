{{ config(materialized='table', schema='silver') }}

-- Grain: one row per (player_id, banner_type) combination
-- Synthetic id: player_id:banner_type (matches source Postgres composite key pattern)

with source as (
    select *
    from {{ source('bronze', 'player_pity') }}
    where event in ('insert', 'update')
),

parsed as (
    select
        json_extract_string(data, '$.player_id') || ':' || json_extract_string(data, '$.banner_type') as id,
        json_extract_string(data, '$.player_id')                                    as player_id,
        json_extract_string(data, '$.banner_type')                                  as banner_type,
        cast(json_extract_string(data, '$.pity_count') as integer)                  as pity_count,
        case
            when json_extract_string(data, '$.guaranteed_next') = 'true' then true
            else false
        end                                                                          as guaranteed_next,
        cast(json_extract_string(data, '$.updated_at') as timestamp)                as updated_at,
        ingested_at,
        row_number() over (
            partition by
                json_extract_string(data, '$.player_id'),
                json_extract_string(data, '$.banner_type')
            order by ingested_at desc
        ) as rn
    from source
),

deduped as (
    select
        id,
        player_id,
        banner_type,
        pity_count,
        guaranteed_next,
        updated_at
    from parsed
    where rn = 1
)

select * from deduped

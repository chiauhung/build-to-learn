{{ config(materialized='table', schema='silver') }}

-- Grain: one row per (player_id, character_id) combination
-- Synthetic id: player_id:character_id

with source as (
    select *
    from {{ source('bronze', 'player_inventory') }}
    where event in ('insert', 'update')
),

parsed as (
    select
        json_extract_string(data, '$.player_id') || ':' || json_extract_string(data, '$.character_id') as id,
        json_extract_string(data, '$.player_id')                                    as player_id,
        json_extract_string(data, '$.character_id')                                 as character_id,
        cast(json_extract_string(data, '$.constellation') as integer)               as constellation,
        cast(json_extract_string(data, '$.obtained_at') as timestamp)               as obtained_at,
        cast(json_extract_string(data, '$.updated_at') as timestamp)                as updated_at,
        ingested_at,
        row_number() over (
            partition by
                json_extract_string(data, '$.player_id'),
                json_extract_string(data, '$.character_id')
            order by ingested_at desc
        ) as rn
    from source
),

deduped as (
    select
        id,
        player_id,
        character_id,
        constellation,
        obtained_at,
        updated_at
    from parsed
    where rn = 1
)

select * from deduped

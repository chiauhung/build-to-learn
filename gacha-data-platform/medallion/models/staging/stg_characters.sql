{{ config(materialized='table', schema='silver') }}

with source as (
    select *
    from {{ source('bronze', 'characters') }}
    where event in ('insert', 'update')
),

parsed as (
    select
        json_extract_string(data, '$.id')                                       as id,
        json_extract_string(data, '$.name')                                     as name,
        json_extract_string(data, '$.rarity')                                   as rarity,
        json_extract_string(data, '$.archetype')                                as archetype,
        json_extract_string(data, '$.element')                                  as element,
        json_extract_string(data, '$.faction')                                  as faction,
        json_extract_string(data, '$.banner_debut')                             as banner_debut,
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
        rarity,
        archetype,
        element,
        faction,
        banner_debut
    from parsed
    where rn = 1
)

select * from deduped

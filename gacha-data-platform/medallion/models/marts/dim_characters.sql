{{ config(materialized='table', schema='gold') }}

-- Sourced from dbt seed: seeds/characters.csv
with characters as (
    select * from {{ ref('characters') }}
),

final as (
    select
        character_id,
        name,
        rarity,
        archetype,
        element,
        banner_debut
    from characters
)

select * from final

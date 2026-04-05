{{ config(materialized='table', schema='gold') }}

with stg as (
    select * from {{ ref('stg_characters') }}
)

select
    id          as character_id,
    name,
    rarity,
    archetype,
    element,
    banner_debut
from stg

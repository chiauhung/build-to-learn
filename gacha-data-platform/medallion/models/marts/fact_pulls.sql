{{ config(materialized='table', schema='gold') }}

with pulls as (
    select * from {{ ref('stg_pulls') }}
),

players as (
    select id, region from {{ ref('stg_players') }}
),

final as (
    select
        p.id            as pull_id,
        p.player_id,
        pl.region       as player_region,
        p.banner_id,
        p.character_id,
        p.rarity,
        p.pity_count,
        p.is_guaranteed,
        p.crystals_spent,
        p.pulled_at
    from pulls p
    left join players pl
        on p.player_id = pl.id
)

select * from final

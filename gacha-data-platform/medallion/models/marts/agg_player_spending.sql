{{ config(materialized='table', schema='gold') }}

with pulls as (
    select * from {{ ref('fact_pulls') }}
),

transactions as (
    select * from {{ ref('fact_transactions') }}
    where payment_status = 'success'
),

pull_stats as (
    select
        player_id,
        count(*)                                                        as total_pulls,
        sum(crystals_spent)                                             as total_crystals_spent,
        count(case when rarity = 'SSR' then 1 end)                      as ssr_count,
        count(case when rarity = 'SR' then 1 end)                       as sr_count,
        count(case when rarity = 'R' then 1 end)                        as r_count,
        count(distinct character_id)                                    as unique_characters
    from pulls
    group by player_id
),

ssr_pity as (
    -- For each SSR pull, find how many pulls it took since the last SSR (or start)
    -- Approximation: average pity_count at SSR pulls as proxy for pulls-to-SSR
    select
        player_id,
        avg(pity_count)                                                 as avg_pity_to_ssr
    from pulls
    where rarity = 'SSR'
    group by player_id
),

spend_stats as (
    select
        player_id,
        sum(amount_usd)                                                 as total_usd_spent
    from transactions
    group by player_id
),

final as (
    select
        ps.player_id,
        ps.total_pulls,
        ps.total_crystals_spent,
        coalesce(ss.total_usd_spent, 0)                                 as total_usd_spent,
        ps.ssr_count,
        ps.sr_count,
        ps.r_count,
        ps.unique_characters,
        sp.avg_pity_to_ssr
    from pull_stats ps
    left join spend_stats ss
        on ps.player_id = ss.player_id
    left join ssr_pity sp
        on ps.player_id = sp.player_id
)

select * from final

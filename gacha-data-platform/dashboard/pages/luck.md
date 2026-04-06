---
title: Luck Analysis
---

## Luckiest Players (Lowest Avg Pity to SSR)

```sql luckiest
select
    a.player_id,
    p.username,
    p.region,
    a.total_pulls,
    a.ssr_count,
    round(a.avg_pity_to_ssr, 1) as avg_pity,
    round(a.ssr_count * 100.0 / a.total_pulls, 2) as ssr_rate
from gacha.agg_player_spending a
join gacha.stg_players p on a.player_id = p.id
where a.ssr_count > 0
order by a.avg_pity_to_ssr asc
limit 20
```

<DataTable data={luckiest} />

## Unluckiest Players (Highest Avg Pity to SSR)

```sql unluckiest
select
    a.player_id,
    p.username,
    p.region,
    a.total_pulls,
    a.ssr_count,
    round(a.avg_pity_to_ssr, 1) as avg_pity,
    round(a.ssr_count * 100.0 / a.total_pulls, 2) as ssr_rate
from gacha.agg_player_spending a
join gacha.stg_players p on a.player_id = p.id
where a.ssr_count > 0
order by a.avg_pity_to_ssr desc
limit 20
```

<DataTable data={unluckiest} />

## Pity Distribution (When SSR Landed)

```sql pity_histogram
select
    case
        when pity_count between 1 and 10 then '1-10 (early)'
        when pity_count between 11 and 30 then '11-30'
        when pity_count between 31 and 50 then '31-50'
        when pity_count between 51 and 73 then '51-73'
        when pity_count between 74 and 89 then '74-89 (soft pity)'
        when pity_count >= 90 then '90 (hard pity)'
    end as pity_range,
    count(*) as ssr_pulls
from gacha.fact_pulls
where rarity = 'SSR'
group by pity_range
order by min(pity_count)
```

<BarChart data={pity_histogram} x=pity_range y=ssr_pulls title="SSR Pulls by Pity Count" />

## High Pity Club (SSR at 75+ Pity)

```sql high_pity_players
select
    fp.player_id,
    p.username,
    fp.pity_count,
    c.name as character_name
from gacha.fact_pulls fp
join gacha.stg_players p on fp.player_id = p.id
join gacha.dim_characters c on fp.character_id = c.character_id
where fp.rarity = 'SSR' and fp.pity_count >= 75
order by fp.pity_count desc
limit 20
```

{#if high_pity_players.length > 0}
<DataTable data={high_pity_players} />
{:else}
*No players hit 75+ pity in this dataset. Try `make seed` (1000 players) for more data.*
{/if}

## 50/50 Win Rate

```sql fifty_fifty
select
    case when is_guaranteed then 'Won 50/50' else 'Lost 50/50 (guaranteed)' end as outcome,
    count(*) as ssr_pulls
from gacha.fact_pulls
where rarity = 'SSR'
group by outcome
```

<BarChart data={fifty_fifty} x=outcome y=ssr_pulls />

---

[Home](/) | [Spending & Whales](/spending) | [Characters](/characters)

---
title: Husbando Chronicles — Analytics
---

```sql overview
select
    count(distinct player_id) as total_players,
    count(*) as total_pulls,
    count(case when rarity = 'SSR' then 1 end) as total_ssr,
    round(count(case when rarity = 'SSR' then 1 end) * 100.0 / count(*), 2) as ssr_rate,
    sum(crystals_spent) as total_crystals_spent
from gacha.fact_pulls
```

```sql total_spent
select coalesce(sum(amount_usd), 0) as total_revenue_usd
from gacha.fact_transactions
where payment_status = 'success'
```

<BigValue data={overview} value=total_players title="Players" />
<BigValue data={overview} value=total_pulls title="Total Pulls" />
<BigValue data={overview} value=total_ssr title="SSR Pulled" />
<BigValue data={overview} value=ssr_rate title="SSR Rate %" />
<BigValue data={total_spent} value=total_revenue_usd title="Revenue (USD)" fmt="$#,##0.00" />

## Pulls by Rarity

```sql rarity_dist
select
    rarity,
    count(*) as pulls
from gacha.fact_pulls
group by rarity
order by
    case rarity when 'SSR' then 1 when 'SR' then 2 when 'R' then 3 end
```

<BarChart data={rarity_dist} x=rarity y=pulls />

## Pulls by Region

```sql region_pulls
select
    player_region as region,
    count(*) as pulls,
    count(case when rarity = 'SSR' then 1 end) as ssr_pulls,
    round(count(case when rarity = 'SSR' then 1 end) * 100.0 / count(*), 2) as ssr_rate
from gacha.fact_pulls
group by player_region
order by pulls desc
```

<DataTable data={region_pulls} />

## Revenue by Payment Method

```sql payment_methods
select
    payment_method,
    count(*) as transactions,
    round(sum(amount_usd), 2) as total_usd
from gacha.fact_transactions
where payment_status = 'success'
group by payment_method
order by total_usd desc
```

<BarChart data={payment_methods} x=payment_method y=total_usd />

---

[Luck Analysis](/luck) | [Spending & Whales](/spending) | [Characters](/characters)

---
title: Spending & Whales
---

## Whale Leaderboard

```sql whales
select
    a.player_id,
    p.username,
    p.region,
    a.total_pulls,
    a.ssr_count,
    a.total_crystals_spent,
    round(a.total_usd_spent, 2) as total_usd_spent
from gacha.agg_player_spending a
join gacha.stg_players p on a.player_id = p.id
order by a.total_usd_spent desc
limit 20
```

<DataTable data={whales} />

## Spender Tiers

```sql spender_tiers
select
    case
        when total_usd_spent = 0 then 'F2P'
        when total_usd_spent < 50 then 'Minnow (<$50)'
        when total_usd_spent < 200 then 'Dolphin ($50-200)'
        else 'Whale ($200+)'
    end as tier,
    count(*) as players,
    round(sum(total_usd_spent), 2) as total_revenue,
    round(avg(total_pulls), 0) as avg_pulls
from gacha.agg_player_spending
group by tier
order by
    case tier
        when 'F2P' then 1
        when 'Minnow (<$50)' then 2
        when 'Dolphin ($50-200)' then 3
        when 'Whale ($200+)' then 4
    end
```

<DataTable data={spender_tiers} />

<BarChart data={spender_tiers} x=tier y=total_revenue title="Revenue by Spender Tier" />

## Transaction Status Breakdown

```sql tx_status
select
    payment_status,
    count(*) as transactions,
    round(sum(amount_usd), 2) as total_usd
from gacha.fact_transactions
group by payment_status
order by transactions desc
```

<BarChart data={tx_status} x=payment_status y=transactions title="Transactions by Status" />

## Top-Up Package Popularity

```sql packages
select
    package_id,
    count(*) as purchases,
    round(sum(amount_usd), 2) as total_revenue,
    round(avg(amount_usd), 2) as avg_price
from gacha.fact_transactions
where payment_status = 'success'
group by package_id
order by total_revenue desc
```

<DataTable data={packages} />

## Revenue by Region

```sql revenue_region
select
    p.region,
    count(distinct t.player_id) as paying_players,
    round(sum(t.amount_usd), 2) as total_revenue,
    round(avg(t.amount_usd), 2) as avg_transaction
from gacha.fact_transactions t
join gacha.stg_players p on t.player_id = p.id
where t.payment_status = 'success'
group by p.region
order by total_revenue desc
```

<BarChart data={revenue_region} x=region y=total_revenue title="Revenue by Region" />

---

[Home](/) | [Luck Analysis](/luck) | [Characters](/characters)

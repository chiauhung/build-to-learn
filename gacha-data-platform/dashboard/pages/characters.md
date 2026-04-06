---
title: Character Analytics
---

## Most Pulled Characters

```sql most_pulled
select
    c.character_id,
    c.name,
    c.rarity,
    c.archetype,
    c.element,
    count(*) as times_pulled,
    count(distinct fp.player_id) as unique_owners
from gacha.fact_pulls fp
join gacha.dim_characters c on fp.character_id = c.character_id
group by c.character_id, c.name, c.rarity, c.archetype, c.element
order by times_pulled desc
```

<DataTable data={most_pulled} />

## SSR Pull Rate by Character

```sql ssr_characters
select
    c.name,
    c.archetype,
    c.element,
    count(*) as times_pulled,
    count(distinct fp.player_id) as unique_owners
from gacha.fact_pulls fp
join gacha.dim_characters c on fp.character_id = c.character_id
where c.rarity = 'SSR'
group by c.name, c.archetype, c.element
order by times_pulled desc
```

<BarChart data={ssr_characters} x=name y=times_pulled title="SSR Characters — Times Pulled" />

## Collection Completeness

```sql collection
select
    case
        when unique_characters >= 21 then 'Complete (21/21)'
        when unique_characters >= 15 then '15-20'
        when unique_characters >= 10 then '10-14'
        when unique_characters >= 5 then '5-9'
        else '1-4'
    end as collection_range,
    count(*) as players
from gacha.agg_player_spending
group by collection_range
order by
    case collection_range
        when '1-4' then 1
        when '5-9' then 2
        when '10-14' then 3
        when '15-20' then 4
        when 'Complete (21/21)' then 5
    end
```

<BarChart data={collection} x=collection_range y=players title="Player Collection Completeness" />

## Banner Performance

```sql banners
select
    b.banner_id,
    b.name,
    b.type,
    count(*) as total_pulls,
    count(case when fp.rarity = 'SSR' then 1 end) as ssr_pulls,
    count(distinct fp.player_id) as players_pulled,
    round(count(case when fp.rarity = 'SSR' then 1 end) * 100.0 / count(*), 2) as ssr_rate
from gacha.fact_pulls fp
join gacha.dim_banners b on fp.banner_id = b.banner_id
group by b.banner_id, b.name, b.type
order by total_pulls desc
```

<DataTable data={banners} />

---

[Home](/) | [Luck Analysis](/luck) | [Spending & Whales](/spending)

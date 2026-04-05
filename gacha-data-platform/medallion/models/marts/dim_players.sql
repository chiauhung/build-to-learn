{{ config(materialized='table', schema='gold') }}

with players as (
    select * from {{ ref('stg_players') }}
),

final as (
    select
        id              as player_id,
        username,
        region,
        crystal_balance,
        registered_at
    from players
)

select * from final

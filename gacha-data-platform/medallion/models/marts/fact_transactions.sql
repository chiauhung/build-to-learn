{{ config(materialized='table', schema='gold') }}

with transactions as (
    select * from {{ ref('stg_transactions') }}
),

final as (
    select
        id              as transaction_id,
        player_id,
        package_id,
        crystals_added,
        amount_usd,
        payment_method,
        payment_status,
        is_first_buy,
        transacted_at
    from transactions
)

select * from final

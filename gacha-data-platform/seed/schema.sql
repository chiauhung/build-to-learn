-- ============================================
-- Husbando Chronicles — Source Database (PostgreSQL)
-- This is the OLTP source that CDC streams from.
-- ============================================

-- ----- SEED / DIMENSION TABLES -----

CREATE TABLE characters (
    id          VARCHAR(10) PRIMARY KEY,       -- e.g. 'ssr-001'
    name        VARCHAR(100) NOT NULL,
    rarity      VARCHAR(3) NOT NULL,           -- SSR, SR, R
    archetype   VARCHAR(50) NOT NULL,
    element     VARCHAR(20) NOT NULL,
    faction     VARCHAR(50),                   -- NULL in v1.0, added in v2.0 (schema evolution)
    banner_debut VARCHAR(5) NOT NULL,          -- e.g. '1.0', '1.1'
    description TEXT,
    portrait    VARCHAR(100),                  -- e.g. 'portraits/ssr-001.webp'
    created_at  TIMESTAMPTZ DEFAULT NOW(),
    updated_at  TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE banners (
    id              VARCHAR(30) PRIMARY KEY,   -- e.g. 'banner-limited-001'
    name            VARCHAR(100) NOT NULL,
    type            VARCHAR(20) NOT NULL,      -- permanent, limited
    version         VARCHAR(5) NOT NULL,
    rate_up_ssr_id  VARCHAR(10) REFERENCES characters(id),
    start_date      DATE,
    end_date        DATE,
    is_active       BOOLEAN DEFAULT TRUE,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE topup_packages (
    id              VARCHAR(10) PRIMARY KEY,   -- e.g. 'pkg-01'
    name            VARCHAR(50) NOT NULL,
    crystals        INT NOT NULL,
    price_usd       NUMERIC(6,2) NOT NULL,
    first_time_bonus INT DEFAULT 0,
    daily_crystals  INT,                       -- for monthly pass
    duration_days   INT,                       -- for monthly pass
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

-- ----- PLAYER TABLES -----

CREATE TABLE players (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    username        VARCHAR(50) UNIQUE NOT NULL,
    region          VARCHAR(10) NOT NULL,       -- APAC, EU, NA
    crystal_balance INT DEFAULT 0,
    registered_at   TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);

-- ----- FACT: GACHA PULLS -----

CREATE TABLE pulls (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    player_id       UUID NOT NULL REFERENCES players(id),
    banner_id       VARCHAR(30) NOT NULL REFERENCES banners(id),
    character_id    VARCHAR(10) NOT NULL REFERENCES characters(id),
    rarity          VARCHAR(3) NOT NULL,       -- denormalized for query speed
    pity_count      INT NOT NULL,              -- how many pulls since last SSR
    is_guaranteed   BOOLEAN DEFAULT FALSE,     -- won or lost the 50/50
    pull_number     INT NOT NULL,              -- 1-10 within a multi-pull, 1 for single
    batch_id        UUID,                      -- groups a 10-pull together
    crystals_spent  INT NOT NULL,
    pulled_at       TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_pulls_player ON pulls(player_id);
CREATE INDEX idx_pulls_banner ON pulls(banner_id);
CREATE INDEX idx_pulls_pulled_at ON pulls(pulled_at);

-- ----- FACT: TOP-UP TRANSACTIONS -----

CREATE TABLE transactions (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    player_id       UUID NOT NULL REFERENCES players(id),
    package_id      VARCHAR(10) NOT NULL REFERENCES topup_packages(id),
    crystals_added  INT NOT NULL,              -- includes first-time bonus if applicable
    amount_usd      NUMERIC(6,2) NOT NULL,
    payment_method  VARCHAR(20) NOT NULL,      -- credit_card, google_pay, apple_pay
    payment_status  VARCHAR(20) NOT NULL,      -- success, failed, refunded, pending
    is_first_buy    BOOLEAN DEFAULT FALSE,     -- first-time bonus flag
    transacted_at   TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_transactions_player ON transactions(player_id);
CREATE INDEX idx_transactions_status ON transactions(payment_status);
CREATE INDEX idx_transactions_transacted_at ON transactions(transacted_at);

-- ----- STATEFUL: PLAYER PITY TRACKING -----

CREATE TABLE player_pity (
    player_id       UUID NOT NULL REFERENCES players(id),
    banner_type     VARCHAR(20) NOT NULL,      -- permanent, limited
    pity_count      INT DEFAULT 0,             -- resets on SSR pull
    guaranteed_next BOOLEAN DEFAULT FALSE,     -- lost 50/50 last time
    updated_at      TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (player_id, banner_type)
);

-- ----- STATEFUL: PLAYER INVENTORY -----

CREATE TABLE player_inventory (
    player_id       UUID NOT NULL REFERENCES players(id),
    character_id    VARCHAR(10) NOT NULL REFERENCES characters(id),
    constellation   INT DEFAULT 0,             -- 0 = first copy, max 6 (dupes)
    obtained_at     TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (player_id, character_id)
);

-- Kimball Practice: Retail Sales
-- PostgreSQL Schema for Chapter 3
--
-- Grain: One row per product per POS transaction, per store, per date.

-- ============================================
-- STAGING SCHEMA (The Mess)
-- ============================================
-- Raw data lands here first, duplicates and all

CREATE SCHEMA IF NOT EXISTS staging;

-- Raw POS events - exactly as received from PubSub
-- Duplicates, out-of-order, all the mess
CREATE TABLE staging.raw_pos_events (
    id                  BIGSERIAL PRIMARY KEY,
    received_at         TIMESTAMPTZ DEFAULT NOW(),
    message_id          TEXT,                       -- PubSub message ID
    raw_payload         JSONB NOT NULL,             -- Original JSON blob
    transaction_id      TEXT,                       -- Extracted for indexing
    event_timestamp     TIMESTAMPTZ,                -- Extracted event time
    processed           BOOLEAN DEFAULT FALSE
);

CREATE INDEX idx_raw_pos_txn_id ON staging.raw_pos_events(transaction_id);
CREATE INDEX idx_raw_pos_processed ON staging.raw_pos_events(processed);

-- Raw product updates - CSV rows as received
CREATE TABLE staging.raw_product_updates (
    id                  BIGSERIAL PRIMARY KEY,
    received_at         TIMESTAMPTZ DEFAULT NOW(),
    source_file         TEXT,                       -- Which CSV file
    row_number          INT,
    sku                 TEXT,
    description         TEXT,
    brand               TEXT,
    subcategory         TEXT,
    category            TEXT,
    dept_num            TEXT,                       -- Keep as text (might be messy)
    dept_name           TEXT,
    pkg_type            TEXT,
    pkg_size            TEXT,
    weight              TEXT,                       -- Keep as text (might be messy)
    weight_uom          TEXT,
    source_updated_at   TEXT,                       -- Keep as text (date format varies)
    processed           BOOLEAN DEFAULT FALSE
);

CREATE INDEX idx_raw_product_sku ON staging.raw_product_updates(sku);


-- ============================================
-- STAR SCHEMA (The Clean)
-- ============================================

CREATE SCHEMA IF NOT EXISTS dw;

-- --------------------------------------------
-- DIMENSION: Date
-- --------------------------------------------
-- Pre-populated calendar table
CREATE TABLE dw.dim_date (
    date_key            INT PRIMARY KEY,            -- YYYYMMDD format
    full_date           DATE NOT NULL UNIQUE,
    day_of_week         SMALLINT,                   -- 1=Monday, 7=Sunday
    day_name            TEXT,                       -- 'Monday', 'Tuesday', etc.
    day_of_month        SMALLINT,
    day_of_year         SMALLINT,
    week_of_year        SMALLINT,
    month_number        SMALLINT,
    month_name          TEXT,
    quarter             SMALLINT,
    year                SMALLINT,
    is_weekend          BOOLEAN,
    is_holiday          BOOLEAN DEFAULT FALSE,
    fiscal_year         SMALLINT,
    fiscal_quarter      SMALLINT
);

-- --------------------------------------------
-- DIMENSION: Product (SCD Type 2)
-- --------------------------------------------
CREATE TABLE dw.dim_product (
    product_key         SERIAL PRIMARY KEY,         -- Surrogate key
    sku                 TEXT NOT NULL,              -- Natural key
    description         TEXT,
    brand               TEXT,
    subcategory         TEXT,
    category            TEXT,
    department_number   INT,
    department_name     TEXT,
    package_type        TEXT,
    package_size        TEXT,
    weight              NUMERIC(10,2),
    weight_uom          TEXT,
    -- SCD Type 2 columns
    effective_from      DATE NOT NULL,
    effective_to        DATE,                       -- NULL = current
    is_current          BOOLEAN DEFAULT TRUE,
    row_hash            TEXT                        -- For change detection
);

CREATE INDEX idx_dim_product_sku ON dw.dim_product(sku);
CREATE INDEX idx_dim_product_current ON dw.dim_product(sku, is_current) WHERE is_current = TRUE;

-- --------------------------------------------
-- DIMENSION: Store
-- --------------------------------------------
CREATE TABLE dw.dim_store (
    store_key           SERIAL PRIMARY KEY,         -- Surrogate key
    store_number        TEXT NOT NULL UNIQUE,       -- Natural key
    store_name          TEXT,
    street_address      TEXT,
    city                TEXT,
    state               TEXT,
    zip_code            TEXT,
    district            TEXT,
    region              TEXT,
    store_manager       TEXT,
    selling_sqft        INT,
    total_sqft          INT,
    first_open_date     DATE,
    last_remodel_date   DATE
);

-- --------------------------------------------
-- DIMENSION: Promotion
-- --------------------------------------------
CREATE TABLE dw.dim_promotion (
    promotion_key       SERIAL PRIMARY KEY,         -- Surrogate key
    promotion_code      TEXT,                       -- Natural key (nullable for "No Promotion")
    promotion_name      TEXT,
    price_reduction_type TEXT,
    promotion_media     TEXT,
    ad_type             TEXT,
    display_type        TEXT,
    coupon_type         TEXT,
    promotion_cost      NUMERIC(12,2),
    start_date          DATE,
    end_date            DATE
);

-- Insert default "No Promotion" row
INSERT INTO dw.dim_promotion (promotion_key, promotion_code, promotion_name)
VALUES (0, NULL, 'No Promotion');

-- --------------------------------------------
-- DIMENSION: Cashier (SCD Type 2)
-- --------------------------------------------
CREATE TABLE dw.dim_cashier (
    cashier_key         SERIAL PRIMARY KEY,         -- Surrogate key
    employee_id         TEXT NOT NULL,              -- Natural key
    employee_name       TEXT,
    hire_date           DATE,
    store_number        TEXT,                       -- Store assignment at this version
    position            TEXT,
    -- SCD Type 2 columns
    effective_from      DATE NOT NULL,
    effective_to        DATE,
    is_current          BOOLEAN DEFAULT TRUE
);

CREATE INDEX idx_dim_cashier_emp ON dw.dim_cashier(employee_id);

-- --------------------------------------------
-- DIMENSION: Payment Method
-- --------------------------------------------
CREATE TABLE dw.dim_payment_method (
    payment_method_key  SERIAL PRIMARY KEY,
    payment_method_code TEXT NOT NULL UNIQUE,
    payment_method_name TEXT,
    card_type           TEXT                        -- VISA, MC, AMEX, etc. (nullable for cash)
);

-- Insert common payment methods
INSERT INTO dw.dim_payment_method (payment_method_code, payment_method_name, card_type) VALUES
    ('CASH', 'Cash', NULL),
    ('CREDIT', 'Credit Card', NULL),
    ('DEBIT', 'Debit Card', NULL),
    ('MOBILE', 'Mobile Payment', NULL);

-- --------------------------------------------
-- FACT: Retail Sales
-- --------------------------------------------
-- Grain: One row per product per transaction
CREATE TABLE dw.fact_retail_sales (
    -- Keys
    date_key                    INT NOT NULL REFERENCES dw.dim_date(date_key),
    product_key                 INT NOT NULL REFERENCES dw.dim_product(product_key),
    store_key                   INT NOT NULL REFERENCES dw.dim_store(store_key),
    promotion_key               INT NOT NULL REFERENCES dw.dim_promotion(promotion_key),
    cashier_key                 INT NOT NULL REFERENCES dw.dim_cashier(cashier_key),
    payment_method_key          INT NOT NULL REFERENCES dw.dim_payment_method(payment_method_key),

    -- Degenerate dimension
    pos_transaction_number      TEXT NOT NULL,

    -- Measures
    sales_quantity              INT NOT NULL,
    regular_unit_price          NUMERIC(10,2),
    discount_unit_price         NUMERIC(10,2),
    net_unit_price              NUMERIC(10,2),
    extended_discount_amount    NUMERIC(12,2),
    extended_sales_amount       NUMERIC(12,2),
    extended_cost_amount        NUMERIC(12,2),
    extended_gross_profit       NUMERIC(12,2),

    -- Metadata
    loaded_at                   TIMESTAMPTZ DEFAULT NOW(),

    PRIMARY KEY (date_key, product_key, store_key, pos_transaction_number)
);

CREATE INDEX idx_fact_sales_date ON dw.fact_retail_sales(date_key);
CREATE INDEX idx_fact_sales_product ON dw.fact_retail_sales(product_key);
CREATE INDEX idx_fact_sales_store ON dw.fact_retail_sales(store_key);


-- ============================================
-- HELPER: Populate Date Dimension
-- ============================================
-- Generate dates for 2024-2025

INSERT INTO dw.dim_date (
    date_key, full_date, day_of_week, day_name, day_of_month, day_of_year,
    week_of_year, month_number, month_name, quarter, year, is_weekend,
    fiscal_year, fiscal_quarter
)
SELECT
    TO_CHAR(d, 'YYYYMMDD')::INT AS date_key,
    d AS full_date,
    EXTRACT(ISODOW FROM d)::SMALLINT AS day_of_week,
    TO_CHAR(d, 'Day') AS day_name,
    EXTRACT(DAY FROM d)::SMALLINT AS day_of_month,
    EXTRACT(DOY FROM d)::SMALLINT AS day_of_year,
    EXTRACT(WEEK FROM d)::SMALLINT AS week_of_year,
    EXTRACT(MONTH FROM d)::SMALLINT AS month_number,
    TO_CHAR(d, 'Month') AS month_name,
    EXTRACT(QUARTER FROM d)::SMALLINT AS quarter,
    EXTRACT(YEAR FROM d)::SMALLINT AS year,
    EXTRACT(ISODOW FROM d) IN (6, 7) AS is_weekend,
    -- Fiscal year starts in February (example)
    CASE WHEN EXTRACT(MONTH FROM d) >= 2
         THEN EXTRACT(YEAR FROM d)::SMALLINT
         ELSE (EXTRACT(YEAR FROM d) - 1)::SMALLINT
    END AS fiscal_year,
    CASE
        WHEN EXTRACT(MONTH FROM d) IN (2,3,4) THEN 1
        WHEN EXTRACT(MONTH FROM d) IN (5,6,7) THEN 2
        WHEN EXTRACT(MONTH FROM d) IN (8,9,10) THEN 3
        ELSE 4
    END::SMALLINT AS fiscal_quarter
FROM generate_series('2024-01-01'::DATE, '2025-12-31'::DATE, '1 day'::INTERVAL) AS d;


-- ============================================
-- VERIFICATION QUERIES
-- ============================================
-- Run these after init to verify setup

-- Check staging tables exist
-- SELECT COUNT(*) FROM staging.raw_pos_events;
-- SELECT COUNT(*) FROM staging.raw_product_updates;

-- Check dimension tables
-- SELECT COUNT(*) FROM dw.dim_date;          -- Should be 731 (2 years)
-- SELECT * FROM dw.dim_promotion;            -- Should have "No Promotion" row
-- SELECT * FROM dw.dim_payment_method;       -- Should have 4 rows

COMMENT ON SCHEMA staging IS 'Raw data landing zone - contains duplicates and messy data';
COMMENT ON SCHEMA dw IS 'Clean dimensional model following Kimball methodology';
COMMENT ON TABLE dw.fact_retail_sales IS 'Grain: One row per product per POS transaction';

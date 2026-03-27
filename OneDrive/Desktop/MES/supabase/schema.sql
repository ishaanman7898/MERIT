-- MERIT Database Schema
-- Run this in your Supabase SQL Editor to set up all required tables and views.
--
-- IMPORTANT: After running this SQL, go to Storage in your Supabase dashboard and:
--   1. Create a new bucket named "product-images"
--   2. Set it to PUBLIC access
--   (The app will try to auto-create this bucket, but if permissions prevent it,
--    create it manually from the dashboard.)

-- ============================================================
-- PRODUCTS TABLE
-- Master product catalog with pricing and images.
-- ============================================================
CREATE TABLE IF NOT EXISTS products (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name TEXT NOT NULL,
    category TEXT,
    status TEXT DEFAULT 'Active',
    sku TEXT UNIQUE NOT NULL,
    price FLOAT DEFAULT 0.0,
    image_url TEXT DEFAULT 'N/A',
    secondary_image_url TEXT DEFAULT 'N/A',
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- ============================================================
-- INVENTORY TABLE
-- Tracks stock levels per SKU with invoice metadata.
-- ============================================================
CREATE TABLE IF NOT EXISTS inventory (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    sku TEXT UNIQUE NOT NULL REFERENCES products(sku) ON DELETE CASCADE,
    item_name TEXT,
    stock_bought INT DEFAULT 0,
    stock_left INT DEFAULT 0,
    status TEXT DEFAULT 'Out of stock',
    last_updated_from_invoice TEXT,
    invoice_date TEXT,
    due_date TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- ============================================================
-- INVENTORY SUMMARY VIEW
-- Joins products + inventory for a unified read-only dashboard.
-- ============================================================
CREATE OR REPLACE VIEW inventory_summary AS
SELECT
    i.sku,
    p.name,
    p.category,
    p.price,
    i.stock_bought,
    i.stock_left,
    i.status,
    ROUND((p.price * i.stock_left)::NUMERIC, 2) AS estimated_value
FROM inventory i
JOIN products p ON p.sku = i.sku;

-- ============================================================
-- EMAIL CAMPAIGNS TABLE
-- Tracks bulk email campaigns and open metrics.
-- ============================================================
CREATE TABLE IF NOT EXISTS email_campaigns (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    subject TEXT,
    body_html TEXT,
    recipients_json JSONB,
    sent_at TIMESTAMPTZ DEFAULT NOW(),
    open_count INT DEFAULT 0,
    status TEXT DEFAULT 'draft'
);

-- ============================================================
-- ORDERS TABLE
-- Records individual order emails sent through MERIT.
-- ============================================================
CREATE TABLE IF NOT EXISTS orders (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    recipient_name TEXT,
    recipient_email TEXT,
    order_number TEXT,
    products_json JSONB,
    order_total FLOAT DEFAULT 0.0,
    sent_at TIMESTAMPTZ DEFAULT NOW(),
    status TEXT DEFAULT 'sent'
);

-- ============================================================
-- CONFIG TABLE
-- Key-value store for app-level settings.
-- ============================================================
CREATE TABLE IF NOT EXISTS config (
    key TEXT UNIQUE NOT NULL,
    value TEXT
);

-- ============================================================
-- INDEXES
-- ============================================================
CREATE INDEX IF NOT EXISTS idx_products_sku ON products(sku);
CREATE INDEX IF NOT EXISTS idx_inventory_sku ON inventory(sku);
CREATE INDEX IF NOT EXISTS idx_orders_order_number ON orders(order_number);

-- ============================================================
-- AUTO-UPDATE TRIGGER for inventory.updated_at
-- ============================================================
CREATE OR REPLACE FUNCTION update_inventory_timestamp()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_inventory_updated_at ON inventory;
CREATE TRIGGER trg_inventory_updated_at
    BEFORE UPDATE ON inventory
    FOR EACH ROW
    EXECUTE FUNCTION update_inventory_timestamp();

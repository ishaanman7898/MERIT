# Inventory System Guide

This guide covers how the inventory system works inside MERIT and how to manage it correctly.


## Core Metrics

MERIT tracks two independent metrics for every product.

### `stock_left` — Current Available Stock

The live quantity of units available for sale or distribution.

**Where to manage:** Inventory → Adjust Stock

**How it works:**
- Decreases by 1 unit per item whenever an order confirmation email is sent through Mass Email.
- Can be manually adjusted using the stepper to add or remove stock without affecting past orders.
- Controls the status badges shown on your storefront (Low Stock, Out of Stock, Backordered).

### `original_stock` — Lifetime Total Purchased

The cumulative total of all inventory quantities your firm has ever purchased.

**Where to manage:** Inventory → Original Stock

**How it works:**
- Automatically increases when you add stock in the Adjust Stock tab.
- Does not decrease when you sell products or send emails.
- Can be manually overridden if a mistake was made or a past purchase was missed.


## Managing Wholesale Marketplace Purchases

When your firm buys inventory through the VEI Wholesale Marketplace, quantities do not automatically sync to MERIT. After every purchase:

1. Navigate to **Inventory → Adjust Stock**.
2. Add the quantity purchased for each product.
3. Click **Apply**.

This increases both `stock_left` (so you can sell the items) and `original_stock` (so your lifetime total stays accurate).


## Database Synchronization

MERIT writes inventory changes to all configured databases simultaneously.

| Database | Role |
|---|---|
| **Turso** | Primary cloud database. All reads prefer Turso when connected. |
| **Supabase** | Secondary cloud database. Used as fallback when Turso is unavailable. |
| **SQLite** | Local cache on the server. Always available; used for initial setup and offline fallback. |

When you adjust inventory, MERIT writes the update to every connected database at the same time. If you need to access this data for an external website, use the **API Endpoints** page inside the app for pre-built SQL and JavaScript code.


## Outbound Order Tracking

Every order confirmation email processed through Mass Email generates a log entry in the `outbound_logs` table.

Each log entry includes:
- Recipient name and email address
- Order number
- Product list
- Full cost breakdown (subtotal, tax, shipping)

View these logs in **Inventory → Outbound Information**.

The Financials module uses this table to calculate total revenue and break down sales by month.


## Reset Inventory

The **Reset Inventory** tab provides two destructive operations for end-of-year or firm handover scenarios:

| Action | What it does |
|---|---|
| **Zero Out Stock** | Sets `stock_left` to 0 for all products. Preserves product records and `original_stock`. |
| **Delete All Products** | Permanently removes all products and inventory records from all databases. |

Both actions require confirmation and propagate to Turso, Supabase, and SQLite simultaneously.

# MERIT Inventory System Guide

This guide covers how the inventory system works inside MERIT and how to manage it correctly.

## Core Metrics

MERIT tracks two independent metrics for every product in your system.

### 1. `stock_left` — Current Available Stock

This is the live quantity of units available for sale or distribution.

**Where to manage:** The Adjust Stock tab in the app.

**How it works:**
- Decreases by 1 unit per item whenever an order confirmation email is sent through the Mass Email system.
- Can be manually adjusted using the stepper to add or remove stock without affecting past orders.
- Controls the status badges shown on your storefront (Low Stock, Out of Stock, Backordered).

### 2. `original_stock` — Lifetime Total Purchased

This is the cumulative total of all inventory quantities your firm has ever purchased.

**Where to manage:** The Original Stock tab in the app.

**How it works:**
- Automatically increases when you add stock in the Adjust Stock tab.
- Does not decrease when you sell products or send emails.
- Can be manually overridden if a mistake was made or a past purchase was missed.


## Managing Wholesale Marketplace Purchases

When your firm buys inventory through the VEI Wholesale Marketplace, quantities do not automatically sync to MERIT. After every Wholesale purchase, you need to update MERIT manually.

1. Navigate to **Inventory → Adjust Stock**.
2. Add the quantity you purchased for each product using the input field.
3. Click Apply.

This single action increases both your `stock_left` (so you can sell the items) and your `original_stock` (so your lifetime total stays accurate).


## Database Synchronization

MERIT uses a dual database approach to keep your data reliable and available.

**SQLite (Local Database)** handles all immediate reads and writes. This data lives alongside the app and makes operations fast.

**Supabase (Cloud PostgreSQL)** acts as the primary persistent storage layer. This is the source of truth for all your data.

Whenever you adjust inventory, MERIT writes the update to both SQLite and Supabase at the same time. If you need to access this data for an external website, use your Supabase credentials.


## Outbound Order Tracking

Every order confirmation email processed through the Mass Email queue generates a log entry in the `outbound_logs` database table.

This log includes the recipient name, email address, order number, product list, and full cost breakdown. You can view these logs in the **Inventory → Outbound Information** tab.

The Financials module uses this table to calculate total revenue and break down sales by month based on the cost stored in each log entry.

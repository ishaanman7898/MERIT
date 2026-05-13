# MERIT Inventory System Guide

This guide covers the functionality and architecture of the inventory system in MERIT.

## Core Metrics

MERIT tracks two independent metrics for every product in your system:

### 1. `stock_left` (Current Available Stock)
- **Definition:** The live, real-time quantity of units available for sale or distribution.
- **Where to manage:** **Adjust Stock** tab in the app.
- **How it behaves:**
  - Automatically decreases by 1 unit per item whenever an order confirmation email is sent via the *Mass Email* system.
  - Can be manually adjusted using the ± stepper to add (+5) or remove (-2) stock without affecting past orders.
  - Controls the Status badges (e.g. "Low stock", "Out of stock", "Backordered").

### 2. `original_stock` (Lifetime Total Purchased)
- **Definition:** The cumulative sum of all inventory quantities ever purchased by your firm.
- **Where to manage:** **Original Stock** tab in the app.
- **How it behaves:**
  - Automatically **increases** when you add stock using the *Adjust Stock* tab (positive delta).
  - Does **not** decrease when you sell products or send emails.
  - Can be manually overridden if a mistake occurs or a past purchase was missed.

## Managing Wholesale Marketplace Purchases

When your firm buys inventory through the VEI Wholesale Marketplace, the quantities do **not** automatically sync to MERIT. 

**After every Wholesale purchase, you must:**
1. Navigate to **Inventory → Adjust Stock**.
2. Add the quantity you purchased for each product using the `±` input.
3. Click Apply. 

*This single action automatically increases your `stock_left` (so you can sell the items) and your `original_stock` (so your lifetime total remains accurate).*

## Database Synchronization

MERIT uses a dual-database approach to ensure high availability:
- **SQLite (Local Database):** Handles all immediate reads and writes. This data lives alongside the app.
- **Supabase (Cloud PostgreSQL):** Acts as the primary persistent storage layer. 

Whenever you adjust inventory, MERIT writes the update to **both** SQLite and Supabase simultaneously via the `adjust_inventory_sqlite` and `adjust_inventory_supabase` functions. If you need to access this data for an external website, use your Supabase credentials.

## Outbound Order Tracking

Every order confirmation email processed through the *Mass Email* queue generates a log entry in the `outbound_logs` database table.
- This includes the recipient name, email, order number, products list, and cost breakdown.
- These logs are visible in the **Inventory → Outbound Information** tab.
- This table also powers the **Financials** module, which calculates total revenue and aggregates sales data by month based on the total cost stored in the log entries.

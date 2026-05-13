# MERIT — Mass Email and Inventory Tool

MERIT is the definitive productivity tool for Virtual Enterprise International (VEI) firms. Automate order confirmations, manage a professional product catalog, track live inventory, and analyze revenue — all from a single dashboard. No coding required, though a basic understanding of database concepts helps during setup.

[Getting Started](#getting-started) • [Pages Overview](#pages-overview) • [Inventory System](#inventory-system) • [API Endpoints](#api-endpoints) • [FAQ](#frequently-asked-questions)

---

## Key Features

- **Bulk Email Sending**: Send personalized order confirmation emails to hundreds of customers in seconds using CSV upload, manual entry, or Excel import directly from VEI Checkout.
- **Automatic Inventory Sync**: Stock levels deduct automatically when order emails are sent — no manual updates needed.
- **Financials Dashboard**: Track total revenue, per-product revenue, monthly trends, cost breakdowns (subtotal, tax, shipping), and a full outbound email log.
- **Product Catalog**: Full CRUD for products with multiple images, descriptions, buy button URLs, and category tags.
- **Image Hosting**: Built-in integration with FreeImage.host and Imghippo. Supports multiple images per product, all stored and served from a CDN.
- **App Security**: Password-protected login gate prevents unauthorized access to your dashboard.
- **Cloud Persistence**: Supabase integration keeps your data synchronized and safe across restarts.
- **Excel Import**: Import orders directly from VEI Checkout Excel exports — quantities ("Product x 8") are parsed automatically.
- **API Endpoints**: Auto-generated code and prompts to connect your storefront (Bolt.new, Lovable, Cursor, v0) to your live product database.
- **Email Templates**: Customize HTML order emails and mass campaign templates, saved permanently to your database.

---

## Hardware Recommendations

MERIT runs on **Streamlit**, which often has performance and storage issues on school-issued Chromebooks. For the best experience, use a **personal laptop** or your **school-provided VE laptop**. Once setup is complete, the app works from any browser — including phones and tablets.

---

## Getting Started

> [!IMPORTANT]
> Use your official VEI Firm Email for all account registrations to ensure access remains consistent for future firm members.

### 1. Fork and Deploy to Streamlit Cloud

#### Fork the repository
1. Go to the MERIT GitHub repository page.
2. Click **Fork** in the top-right corner.
3. Under "Owner", select your personal GitHub account or your firm's organization.
4. Click **Create fork**.

#### Deploy on Streamlit Cloud
1. Go to [share.streamlit.io](https://share.streamlit.io) and sign in with the same GitHub account.
2. Click **Create app**.
3. Under "Repository", select your forked MERIT repository.
4. Set **Main file path** to `app.py`.
5. Click **Deploy**. Streamlit will build and launch your app in about a minute.
6. Once live, you will get a public URL (e.g. `https://yourname-merit-app-xxxxx.streamlit.app`). Share this with your firm.

> [!NOTE]
> **Open your deployed app and go to Get Started — complete every step inside the app.** The steps below are quick-reference summaries. The in-app guide includes detailed screenshots and instructions for first-time setup.

---

### 2. Connect Your Database (Supabase)

Supabase is the cloud database for MERIT. It stores products, inventory, email templates, and outbound logs securely so data survives app restarts.

1. Create a free project at [supabase.com](https://supabase.com) using your VEI email.
2. Click the green **Connect** button → find the **Session Pooler** connection string.
3. Copy the string (looks like `postgresql://postgres.xxxx:[YOUR-PASSWORD]@aws-0-us-east-1.pooler.supabase.com:5432/postgres`).
4. In MERIT → **Settings → Database Connection**, paste the string and your database password.
5. Click **Setup Tables** to create all required tables automatically.

---

### 3. Get Your Supabase Anon Key

The **anon key** lets your public storefront website safely read products from Supabase without exposing your database password. It is also pre-filled into all code examples on the API Endpoints page.

1. In your Supabase project, click the **gear icon (⚙)** → **Project Settings → API**.
2. Under **Project API keys**, copy the **anon / public** key (starts with `eyJ…`).
3. In MERIT → **Settings → Supabase Anon Key**, paste the key.

This key is safe to embed in public website code when Row Level Security (RLS) is enabled. Never use your database password or connection string in website code.

---

### 4. Enable Image Hosting

Product images must be hosted online to appear in emails and on your storefront.

1. Obtain a free API key from [freeimage.host](https://freeimage.host) (recommended) or [imghippo.com](https://imghippo.com).
2. Paste the key into **MERIT → Settings → Image Hosting**.
3. MERIT automatically uploads and compresses images when you add or edit products. Multiple images per product are supported.

---

### 5. Configure Gmail SMTP

MERIT sends emails through your firm's Gmail account. An App Password is required for secure authentication.

1. Open your Google Account → **Security** → enable **2-Step Verification**.
2. Search for **App Passwords** → create one named `MERIT Email`.
3. Copy the 16-character code and paste it into **MERIT → Settings → Email**.
4. Also enter your VEI Gmail address (e.g. `yourfirm@veinternational.org`).

---

### 6. Set App Login Password

Protect your dashboard from unauthorized changes.

1. In **MERIT → Settings**, navigate to **App Login Password**.
2. Enter a secure password your firm will use to log in.
3. This password is required every time the app is opened (after the final setup step).

---

### 7. Save Your Settings (The Final Step)

Streamlit Cloud restarts your app periodically and wipes saved files. To keep all settings permanently:

1. After completing steps 2–6 inside the app, go to **Settings → Secrets TOML**.
2. Copy the entire generated TOML code block.
3. In Streamlit Cloud: click **Manage app** (bottom-right) → **⋮** → **Settings** → **Secrets**.
4. Paste the TOML block and click **Save**. Your credentials are now permanent.

After the app reboots, the **Get Started** page disappears from the sidebar — setup is complete.

---

## Pages Overview

| Page | What it does |
|---|---|
| **Get Started** | Step-by-step guided setup (disappears after secrets are saved) |
| **Mass Email** | Upload CSV orders, send bulk emails, manage order templates and campaigns |
| **Products** | Add, edit, delete products; multiple images, descriptions, buy button URLs |
| **Inventory** | Overview, Financials, Adjust Stock, Original Stock, and Documentation |
| **Settings** | All credentials — Supabase, Gmail, image hosting, anon key, login password |
| **API Endpoints** | Pre-built code for connecting your website to the live product database |

---

## Inventory System

MERIT tracks two numbers per product:

| Field | Meaning |
|---|---|
| **Original Stock** | Running lifetime total of all units ever purchased |
| **Current Stock** | Units available right now — decreases automatically as emails are sent |

### Original Stock Tab (Primary Restocking)

Use this tab whenever you receive new inventory from the VEI Wholesale Marketplace:

- **Positive value**: units received (e.g. +50 → Original Stock +50, Current Stock +50)
- **Negative value**: units removed due to damage or loss (e.g. −5 → both decrease by 5)
- Both Original Stock and Current Stock are updated simultaneously

### Adjust Stock Tab (Manual Corrections)

Use this tab only for manual corrections to Current Stock (does not affect Original Stock):
- Fix a counting error
- Write off damaged goods already received
- Reconcile after a physical count

### Current Stock Auto-Deduction

Every time order emails are sent from Mass Email, MERIT deducts the ordered quantity from Current Stock automatically. Products with `stock_left ≤ 0` are blocked from the next send session to prevent overselling.

### Financials Tab

The Financials tab provides complete revenue reporting:
- Total revenue, orders, average order value, unique customers
- Monthly revenue chart and table
- Per-product revenue breakdown (price × units sold)
- Full outbound email log with timestamps and cost breakdown

---

## API Endpoints

Connect your storefront (Bolt.new, Lovable, Cursor, v0) directly to your Supabase database for real-time updates.

### Key Tables

| Table | Purpose |
|---|---|
| `inventory` | Live stock levels, prices, images, and status for your storefront catalog |
| `products` | Full catalog with descriptions, buy button URLs, and active/inactive flag |
| `outbound_logs` | Audit trail of all sent emails including subtotal, tax, and shipping data |

### Quick Start

On the **API Endpoints** page inside MERIT, you will find:
- **AI Prompts**: Copy-paste prompts for Bolt.new, Lovable, Cursor, and v0 — paste them into the AI chat and your storefront is built automatically, pre-connected to your database
- **Live Preview**: Test your REST endpoints directly in the app
- **REST Endpoints**: Individual URLs for each table with curl examples and filter operators
- **Code Snippets**: JavaScript and TypeScript examples for common operations
- **Schema & Security SQL**: Row Level Security policies to run in Supabase

### Important Storefront Rules

1. Always filter `stock_left > 0` — never show out-of-stock products without a badge
2. Take only the **first** URL from `image_url` when multiple images are stored (split on comma)
3. Filter `active = true` from the `products` table — inactive products should not appear in the store
4. Use `sku` as the URL slug for product detail pages

> [!TIP]
> Save your Supabase Anon Key in MERIT Settings — it will be pre-filled into every code example and AI prompt on the API Endpoints page.

---

## Privacy and Security

MERIT is designed with data privacy as a core principle:

- **Direct Connection**: Data travels directly from your app to Gmail and Supabase — no MERIT intermediary server.
- **Ownership**: All credentials are stored in your own Streamlit Secrets or local config. Anthropic and MERIT have no access to your keys.
- **Auditability**: The entire source code is open for review.
- **Anon Key Safety**: The Supabase anon key is safe for public use with Row Level Security (RLS) enabled. Never put your database password or connection string in website code.

---

## Frequently Asked Questions

**Q: Is coding knowledge required?**  
A: No coding is required. Setup involves copy-paste operations for credentials and API keys. The API Endpoints page generates all website integration code for you.

**Q: Can multiple users access the system?**  
A: Yes. Once Supabase is connected, all firm members can manage inventory and send emails simultaneously from any browser.

**Q: What if Streamlit is inaccessible at school?**  
A: Some school networks block Streamlit. Use your personal laptop or phone for setup. Once your Secrets TOML is saved, the app works from any browser or device going forward.

**Q: Can I run MERIT on my phone?**  
A: Yes. Setup works fine from a phone or tablet browser. Open your Streamlit URL, fill in credentials, and save the Secrets TOML before ending your session.

**Q: What happens when the app restarts?**  
A: If you have completed Step 7 (Secrets TOML), all credentials are restored automatically. Product data and inventory are stored in Supabase and are never lost. If you skipped Step 7, credentials will be wiped and you will need to re-enter them.

**Q: How does Excel import work?**  
A: Export your orders from VEI Checkout as an Excel file and upload it in **Mass Email → Excel Import**. MERIT reads Name, Email, Order Number, and Items columns. Quantities written as "Product x 8" are parsed automatically — 8 units of that product are deducted from inventory when the emails are sent.

**Q: How do I get the Supabase anon key?**  
A: Supabase Dashboard → gear icon → Project Settings → API → copy the **anon / public** key. Paste it into MERIT Settings. It will then appear pre-filled on the API Endpoints page and in all AI prompts.

---

Built for VEI Firms worldwide.

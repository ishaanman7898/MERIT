# MERIT — Mass Email & Inventory Tool for VEI Firms

MERIT is a self-hosted Streamlit app built specifically for **Virtual Enterprise International (VEI)** firms. It lets you send personalised order-confirmation emails in bulk, manage a product catalog with images, and track live inventory — all from one browser tab, with no code required after setup.

Every write syncs across every database you've configured simultaneously (SQLite always, plus Supabase and/or Neon if connected), so your firm's data is never in just one place.

---

## Table of Contents

1. [Quick Start](#1-quick-start)
   - [Streamlit Cloud (recommended)](#recommended-deploy-on-streamlit-cloud-no-install-required)
   - [Run locally](#alternative-run-locally)
2. [Required Credentials](#2-required-credentials)
   - [Gmail App Password](#21-gmail-app-password-required)
   - [Imghippo API Key](#22-imghippo-api-key-required-for-product-images)
   - [Supabase](#23-supabase-optional-strongly-recommended)
   - [Neon](#24-neon-optional-alternative-to-supabase)
3. [First-Run Setup Checklist](#3-first-run-setup-checklist)
4. [Email Sender — Full Guide](#4-email-sender--full-guide)
5. [Products — Full Guide](#5-products--full-guide)
6. [Inventory — Full Guide](#6-inventory--full-guide)
7. [HTML Email Templates](#7-html-email-templates)
8. [Database Architecture](#8-database-architecture)
9. [Troubleshooting](#9-troubleshooting)

---

## 1. Quick Start

### Recommended: Deploy on Streamlit Cloud (no install required)

This is the fastest path — your app is live in under 2 minutes, nothing to install.

1. **Fork this repo**
   - Sign in to GitHub with the account you want to use
   - Click **Fork** at the top-right of this page
   - This creates your own private copy under your GitHub account

2. **Create a Streamlit account**
   - Go to [share.streamlit.io](https://share.streamlit.io) and click **Sign up**
   - Sign in with the **exact same GitHub account** you used to fork — this is required so Streamlit can see your repos

3. **Deploy the app**
   - Click **Create app** in your Streamlit dashboard
   - Select **"Deploy from GitHub"**
   - Select your forked repository from the list
   - Set the following fields exactly:
     - **Branch:** `master`
     - **Main file path:** `app.py`
     - **App URL:** type your VEI firm name (e.g. `acme-merit`) — this becomes your public URL at `acme-merit.streamlit.app`
   - Click **Deploy** — the app will be live in about 60 seconds

4. **Configure credentials inside the app**
   - Once the app loads, go to **Settings** in the left sidebar
   - Fill in your Gmail SMTP credentials, Imghippo API key, and optionally Supabase/Neon database details
   - Click **Save Settings** — credentials are stored in `config.json` and persist across every session
   - See [Required Credentials](#2-required-credentials) for step-by-step guides on getting each key

> **Critical for Streamlit Cloud users:** Streamlit Cloud resets its local filesystem every time the app restarts or redeploys. This means the local SQLite file (`data.db`) is wiped on every restart. Connect a free Supabase project (see [section 2.3](#23-supabase-optional-strongly-recommended)) so your products and inventory survive restarts. Gmail and Imghippo credentials are stored in `config.json` which also resets — you will need to re-enter them after each restart unless you use Streamlit Secrets (advanced).

---

### Alternative: Run locally

Clone your fork:

```bash
git clone https://github.com/YOUR_USERNAME/MERIT.git
cd MERIT
```

Install dependencies (Python 3.10+ required):

```bash
pip install -r requirements.txt
```

Or in a virtual environment (recommended to avoid package conflicts):

```bash
python -m venv venv

# Windows
venv\Scripts\activate

# macOS / Linux
source venv/bin/activate

pip install -r requirements.txt
```

Copy the config template:

```bash
cp config.template.json config.json
```

`config.json` stores all your credentials and is in `.gitignore` — it is never committed to git.

Run the app:

```bash
streamlit run app.py
```

Open [http://localhost:8501](http://localhost:8501) in your browser, then go to **Settings** to fill in your credentials.

---

## 2. Required Credentials

### 2.1 Gmail App Password (required)

MERIT sends emails through Gmail SMTP. You need a **Gmail App Password** — this is different from your regular Gmail password and is specifically designed for apps like this.

**Why App Passwords exist:** Google blocks direct password sign-in for apps when 2-Step Verification is enabled. App Passwords are 16-character one-time tokens scoped to a single application. You can revoke them at any time from your Google account without changing your actual password.

**Steps:**

1. Open [myaccount.google.com](https://myaccount.google.com) and sign in to the Gmail account you want to send from
2. Click **Security** in the left sidebar
3. Under *How you sign in to Google*, confirm **2-Step Verification** shows **On**
   - If it is off, click it and follow the prompts to enable it — App Passwords are only available with 2-Step Verification active
4. In the Google search bar at the top of the page, type **App passwords** and click the result (you may need to re-enter your password)
5. Under *App name*, type `MERIT` (or any label), then click **Create**
6. Google displays a 16-character password in a yellow box — **copy it immediately**, it will never be shown again
7. In MERIT: go to **Settings → Gmail SMTP** and enter:
   - **Gmail Address** — the full address you signed into (e.g. `you@gmail.com`)
   - **App Password** — paste the 16-character password with no spaces

**Common mistakes:**
- Using your regular Gmail password instead of an App Password → authentication will fail
- Leaving spaces in the App Password when pasting → remove all spaces, it should be exactly 16 characters
- 2-Step Verification is off → App Passwords won't appear in your Google account at all

**Where it's saved:** `config.json` → `smtp_email` and `smtp_password`

---

### 2.2 Imghippo API Key (required for product images)

Imghippo is a free image hosting service. When you upload a product image in MERIT, it is sent to Imghippo and stored there. The returned public URL is saved with the product and embedded in order confirmation emails so customers can see what they ordered.

**Free tier:** 500 MB storage, no credit card required, no expiry.

**Steps:**

1. Go to [imghippo.com](https://imghippo.com) and click **Sign Up**
2. Enter your email and verify it
3. Log in, then navigate to **Settings → API Keys** in your dashboard
4. Click **Generate API Key** and copy the key that appears
5. In MERIT: go to **Settings → Image Hosting** and paste the key into the **Imghippo API Key** field
6. Click **Test Key** — you should see a green success message
7. Click **Save Settings**

**What happens without it:** The app still works and sends emails, but product images will not appear in the emails and image upload buttons will show a warning.

**Where it's saved:** `config.json` → `imghippo_api_key`

---

### 2.3 Supabase (optional, strongly recommended)

Supabase is a free cloud Postgres database service. Connecting it means your products, inventory, and stock levels are stored safely in the cloud — accessible from any machine, any browser, and safe from restarts on Streamlit Cloud.

**Free tier:** 500 MB database, 2 projects, no credit card required.

**Steps:**

1. Go to [supabase.com](https://supabase.com) and click **Start your project** → sign in with GitHub or email
2. Click **New project** — give it a name, pick a region close to you, set a database password, and click **Create new project** (takes about 2 minutes)
3. Once your project is ready, go to **Project Settings → API** in the left sidebar
4. Copy the following three values:

   | Field | Where to find it | Used for |
   |---|---|---|
   | **Project URL** | Top of the API settings page | Connecting to your database |
   | **Anon / public key** | Under *Project API keys* — the `anon` row | Read access |
   | **Service role key** | Under *Project API keys* — the `service_role` row | Write/admin access |

   > **Keep the service role key secret.** It bypasses Row Level Security and has full database access. Never share it or commit it to git.

5. For the **Personal Access Token** (allows MERIT to create tables automatically):
   - Go to [supabase.com/dashboard/account/tokens](https://supabase.com/dashboard/account/tokens)
   - Click **Generate new token**, give it a name (e.g. `MERIT`), and copy it — it starts with `sbp_`
   - Paste it into **Settings → Supabase → Personal Access Token** in MERIT

6. In MERIT: go to **Settings → Database Connections → Supabase** and fill in all four fields (URL, anon key, service role key, personal access token)
7. Click **Save Settings**, then click **Setup Tables** — this runs the SQL to create the `inventory` and `products` tables in your Supabase project

**After this:** all product and inventory writes will sync to Supabase automatically. If you restart the app or redeploy on Streamlit Cloud, your data is safe.

**Where it's saved:** `config.json` → `supabase_url`, `supabase_key`, `supabase_service_role_key`, `supabase_pat`

---

### 2.4 Neon (optional, alternative to Supabase)

Neon is a serverless Postgres database. It works the same way as Supabase in MERIT — use it instead of or alongside Supabase.

**Free tier:** 0.5 GB storage, 1 project, no credit card required.

**Steps:**

1. Go to [neon.tech](https://neon.tech) and click **Sign Up**
2. Create a new project and choose a region close to you
3. Go to your project **Dashboard → Connection Details**
4. In the connection string dropdown, select the **psql** or **postgresql** format
5. Copy the full connection string — it looks like:

   ```
   postgresql://neondb_owner:PASSWORD@ep-xxxx.us-east-2.aws.neon.tech/neondb?sslmode=require
   ```

   > **Common mistake:** Do NOT use the REST/HTTP URL (starts with `https://ep-…`). MERIT uses `psycopg2` which requires the `postgresql://` format.

6. In MERIT: go to **Settings → Database Connections → Neon** and paste the string
7. Click **Test Connection** to verify it connects, then click **Setup Tables**

**Where it's saved:** `config.json` → `neon_connection_string`

---

## 3. First-Run Setup Checklist

Use this after deploying or after a fresh local install:

- [ ] Open the app and go to **Settings** in the left sidebar
- [ ] Fill in **From Name** — your VEI firm name. This appears in emails and as the browser tab title
- [ ] Fill in **Default Subject Line** — e.g. `Your order #{{order_number}} is confirmed`
- [ ] Under **Gmail SMTP**: enter your Gmail address and 16-character App Password
- [ ] Under **Image Hosting**: enter your Imghippo API Key and click **Test Key**
- [ ] *(Recommended)* Under **Database Connections → Supabase**: enter all four Supabase fields, click **Save Settings**, then **Setup Tables**
- [ ] Click **Save Settings**
- [ ] Go to **Products** → add your product catalog (name, SKU, price, category, image)
- [ ] Go to **Inventory** → add those same products with their starting stock levels
- [ ] Go to **Email Sender** → add orders to the queue and send your first batch

---

## 4. Email Sender — Full Guide

The Email Sender is the core of MERIT. You build a queue of customer orders, each with a name, email address, order number, and list of products, then send all of them in one click.

### Adding orders to the queue

There are three ways to add orders:

**Single entry** — fill in the form fields (Name, Email, Order #, Products) and click **Add to Queue**. Products can be entered as a comma-separated list, pipe-separated (`|`), semicolon-separated (`;`), or one per line.

**Bulk data table** — an editable table lets you type or paste multiple orders at once. Click **Add All to Queue** when done.

**CSV / TSV import** — upload a `.csv` or `.tsv` file. Required columns are `name`, `email`, `order_number`, and `products`. Extra columns are ignored.

### Product name matching and warnings

As you type product names, MERIT checks them against your product catalog (loaded from Supabase/Neon/SQLite). If a product name doesn't match anything in your catalog:
- A warning appears listing the unmatched names
- These products will still appear in the email as text, but no product image will be included

Matching is fuzzy — partial matches and substring matches work (e.g. typing `T-Shirt` will match a catalog entry of `Blue T-Shirt`).

### Sending emails

Click **Send All Emails** to start the batch send. MERIT:

1. Connects to Gmail SMTP using your credentials
2. Builds a personalised HTML email for each order (using your saved template)
3. Sends each email and shows a live status log as it goes
4. Shows a final summary (sent / failed count)

### Automatic inventory deduction

After every successful send, MERIT automatically subtracts 1 unit of stock for each matched product in each sent order. This happens across all configured databases (SQLite, Supabase, Neon) simultaneously.

- If a product is ordered once, stock goes down by 1
- If the same product appears in 3 different orders, stock goes down by 3
- Stock can go negative — negative stock is shown as **Backordered**
- Failed emails (SMTP errors) do not trigger deductions

### Inventory Impact chart

After the send completes, an **Inventory Impact** section appears below the results table showing:
- A table with each affected product: SKU, units deducted, stock before, stock after
- A grouped bar chart comparing before and after stock for every affected product

This is useful for a quick visual of how the send changed your stock levels. Click **Clear Log** to dismiss it.

---

## 5. Products — Full Guide

The Products page manages your product catalog — the source of truth for names, SKUs, prices, categories, and images used in emails.

### Adding a single product

Fill in the **Add Product** form: SKU (unique identifier), Product Name, Category, Price, and an optional image. Click **Add Product** — the product is saved to all configured databases and the image is uploaded to Imghippo.

### Bulk adding products

Switch to the **Bulk Add** tab. A table of empty rows appears — fill in as many as you need. Each row has its own image uploader so you can attach images per product without having to go back and edit later. Click **Add Row** to add more rows. Click **Add All Products** to save everything at once.

### Bulk editing

The **Bulk Edit** tab shows all your products in an editable data table. Click any cell to edit the value. Click **Save All Changes** to write the entire table back to all databases.

**Replacing images in bulk edit:** Below the table, expand **Replace product images**. Each product is listed with its current image thumbnail and a file uploader. Upload a new image next to any product and click **Upload** — the new image is sent to Imghippo, the URL is updated, and the catalog refreshes immediately.

### Editing a single product

The **Edit Product** tab lets you select one product from a dropdown and edit all its fields in a form. Includes a **Replace Image** section below the form (outside the form since Streamlit doesn't allow file uploaders inside forms).

### Deleting products

The **Bulk Delete** tab lists all products as checkboxes. Select the ones you want to remove and click **Delete Selected** — they are permanently removed from all configured databases simultaneously.

---

## 6. Inventory — Full Guide

The Inventory page tracks live stock levels for every product.

### Overview dashboard

At the top of the page (above the tabs), four metrics give you an instant snapshot:

| Metric | What it shows |
|---|---|
| **Products** | Total number of distinct products in inventory |
| **Total Stock Units** | Sum of all stock across every product |
| **Low Stock** | Number of products with 1–10 units remaining |
| **Out of Stock** | Number of products at exactly 0 units |

Below the metrics, a bar chart shows stock level per product sorted from highest to lowest. Products at zero or in negative (Backordered) are visible at the bottom.

### Stock status levels

| Status | Condition |
|---|---|
| **In stock** | 11 or more units |
| **Low stock** | 1–10 units |
| **Out of stock** | Exactly 0 |
| **Backordered** | Negative (stock went below zero — e.g. from bulk deductions) |

Stock is allowed to go negative. This represents orders that have been confirmed but inventory hasn't been restocked yet.

### Adjust Stock tab

The Adjust Stock tab lists every product as a card row showing:
- Product thumbnail image
- Product name, SKU, category, and image URL link
- Current stock number (white, large) with a colour-coded status badge
- A **± input** to enter a delta (positive to add stock, negative to remove)
- An **Apply** button per row, plus an **Apply All Changes** button at the top

Entering `+5` adds 5 units. Entering `-3` removes 3. The change is applied to all configured databases immediately.

### Add Products tab

Add new products to inventory with initial stock. Each row has fields for SKU, Name, Category, Price, Stock, and an individual image uploader. Use **Add Row** to add more rows. Click **Add All** to save.

### Bulk Edit tab

An editable data table showing all inventory fields. Edit any cell, then click **Save All Changes** to sync to all databases.

**Replacing images in bulk edit:** Below the Save button, expand **Replace product images**. Each product has its current image shown and an individual file uploader to replace it.

### Edit Product tab

Select a product from the dropdown to edit all its fields in a form. A **Replace Image** section sits below the form (outside the form block) for uploading a new image.

### Delete Products tab

Select one or more products from a multi-select list and click **Delete** to permanently remove them from all databases.

---

## 7. HTML Email Templates

MERIT lets you fully customise the HTML of every order confirmation email.

### How it works

Go to **Email Sender → Email Template** tab. You can:
- Edit the HTML directly in the text editor
- Generate a template using the built-in AI prompt (see below)
- Preview a live render of the template with sample order data
- Reset to the built-in default at any time

The template is saved to `config.json` under `email_html_template` and is used automatically for every future send.

### Available template variables

Use these placeholders anywhere in your HTML — MERIT substitutes real values before sending:

| Variable | What it becomes |
|---|---|
| `{{name}}` | Customer's full name |
| `{{order_number}}` | Order number |
| `{{from_name}}` | Your VEI firm name (from Settings → From Name) |
| `{{items_html}}` | A pre-built HTML block of table rows — one per product — with product image, name, and SKU |

**Example:**

```html
<!DOCTYPE html>
<html>
<body style="font-family:sans-serif;background:#f9f9f9;padding:20px;">
  <h2>Hi {{name}}, your order is confirmed!</h2>
  <p>Order number: <strong>#{{order_number}}</strong></p>
  <table cellpadding="8" cellspacing="0" style="width:100%;border-collapse:collapse;">
    {{items_html}}
  </table>
  <p style="margin-top:24px;">Thanks for your order — {{from_name}}</p>
</body>
</html>
```

### Generate a template with AI

In the **Email Template** tab, expand **AI prompt — copy this into ChatGPT / Claude**. Copy the full prompt text, replace the design brief placeholder at the bottom with your own brief (e.g. `"dark theme, VEI firm color #1a1a2e, modern sans-serif"`), then paste it into ChatGPT or Claude. Copy the returned HTML into the template editor and click **Save Template**.

### Requirements for custom templates

- Must be a complete HTML document (starting with `<!DOCTYPE html>`, ending with `</html>`)
- Use inline CSS only — no `<link>` stylesheets or `<script>` tags (most email clients strip them)
- Use table-based layouts for maximum compatibility across Gmail, Outlook, Apple Mail, etc.
- Must include `{{items_html}}` wrapped inside a `<table>` element
- Maximum recommended content width: 600 px

---

## 8. Database Architecture

MERIT writes to all configured databases simultaneously on every create, update, and delete operation. This means your firm's data is always consistent across every configured source.

| Database | Type | When active |
|---|---|---|
| SQLite (`data.db`) | Local file | Always — zero-config, built-in fallback |
| Supabase | Cloud Postgres | When URL and keys are configured in Settings |
| Neon | Serverless Postgres | When connection string is configured in Settings |
| `config.json` `products` array | JSON file | Always — keeps a local copy for fast access |

**Read priority (highest to lowest):** Supabase → Neon → SQLite → `config.json`

The app always reads from the highest-priority source that is configured and available. If Supabase is connected, all reads come from Supabase. If only SQLite is available, reads come from SQLite.

**Important:** `config.json` and `data.db` are both in `.gitignore` and are never committed to your repository. They are local to the machine or container running the app.

---

## 9. Troubleshooting

**"SMTP Authentication Error" when sending**
- You must use a **Gmail App Password**, not your regular Gmail password
- App Passwords are exactly 16 characters with no spaces — check for accidental spaces when pasting
- Confirm that 2-Step Verification is enabled on the Google account — without it, App Passwords don't exist

**"Supabase credentials not configured"**
- Go to Settings → Database Connections → Supabase and make sure the Project URL and at least one key (anon or service role) are filled in, then click Save Settings

**"relation 'inventory' does not exist" or similar Postgres error**
- Your Supabase or Neon project doesn't have the required tables yet
- Go to Settings → Database Connections and click **Setup Tables** after entering your credentials

**Stock not deducting after send**
- Check that your product names in the email queue match (or partially match) the product names in your catalog
- If a product has no match, a warning is shown in the queue view — exact or partial name match is required
- Go to Inventory and confirm the products exist there with the correct SKUs

**Images not appearing in emails**
- Confirm your Imghippo API key is set in Settings → Image Hosting and the Test Key button shows success
- Products must have images uploaded to Imghippo — a local file path won't work in emails
- If a product shows `N/A` as its image URL, upload an image from the Products → Catalog or Bulk Edit page

**Data disappears after restarting on Streamlit Cloud**
- This is expected — Streamlit Cloud resets the local filesystem on every restart
- Connect Supabase (free tier) so your inventory and products are stored in the cloud

**App shows "MERIT" instead of your firm name in the browser tab**
- Go to Settings, fill in **From Name** with your VEI firm name, and click **Save Settings** — the tab title updates on the next page load

**Products page or Inventory page is slow to load**
- The first load after a restart hits the database — subsequent loads within the same session use a 30-second in-memory cache
- If you have a large catalog (100+ products), Supabase or Neon will be significantly faster than SQLite for reads

**Negative stock / Backordered status appearing unexpectedly**
- This is intentional — stock is allowed to go below zero to represent overselling or pre-orders
- Adjust stock manually from the Inventory → Adjust Stock tab to correct it

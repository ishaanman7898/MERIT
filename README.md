# MERIT — Mass Email & Inventory Tool

Send personalised order-confirmation emails in bulk, manage your product catalog, and track inventory — all from a single Streamlit app. Connects to Gmail SMTP for sending, Imghippo for image hosting, and optionally Supabase or Neon for cloud database storage.

---

## Table of Contents

1. [Quick Start (Fork & Run)](#1-quick-start-fork--run)
2. [Required Credentials](#2-required-credentials)
   - [Gmail App Password](#21-gmail-app-password-required)
   - [Imghippo API Key](#22-imghippo-api-key-required-for-product-images)
   - [Supabase](#23-supabase-optional-recommended)
   - [Neon](#24-neon-optional-alternative-to-supabase)
3. [First-Run Setup Checklist](#3-first-run-setup-checklist)
4. [HTML Email Templates](#4-html-email-templates)
5. [Features Overview](#5-features-overview)
6. [Database Architecture](#6-database-architecture)
7. [Troubleshooting](#7-troubleshooting)

---

## 1. Quick Start (Fork & Run)

### Fork the repo

1. Click **Fork** at the top-right of this page
2. Clone your fork locally:

```bash
git clone https://github.com/YOUR_USERNAME/MERIT.git
cd MERIT
```

### Install dependencies

Python 3.10 or newer is required.

```bash
pip install -r requirements.txt
```

Or in a virtual environment (recommended):

```bash
python -m venv venv
# Windows
venv\Scripts\activate
# macOS / Linux
source venv/bin/activate

pip install -r requirements.txt
```

### Set up your config

Copy the template — this is where all your credentials live:

```bash
cp config.template.json config.json
```

`config.json` is already in `.gitignore` so your credentials are never committed.

### Run the app

```bash
streamlit run app.py
```

Open [http://localhost:8501](http://localhost:8501) in your browser.

Go to **Settings** and fill in your credentials (see below). Everything saves to `config.json` automatically and persists across restarts.

---

## 2. Required Credentials

### 2.1 Gmail App Password (required)

MERIT sends emails through Gmail SMTP. You need an **App Password** — not your regular Gmail password.

**Why:** Google requires App Passwords when 2-Step Verification is enabled. They are 16-character passwords scoped to a single app and can be revoked at any time.

**Steps:**

1. Open [myaccount.google.com](https://myaccount.google.com) and sign in to the Gmail account you want to send from
2. Click **Security** in the left sidebar
3. Under *How you sign in to Google*, confirm **2-Step Verification** is **On**
   - If it is off, click it and follow the prompts to enable it first
4. In the search bar at the top, type **App passwords** and click the result
5. Under *App name*, type `MERIT` (or any label you like), then click **Create**
6. Google shows a 16-character password — copy it now (it will not be shown again)
7. In the MERIT app: go to **Settings → Gmail SMTP** and paste:
   - **Gmail Address** — the full Gmail address (e.g. `you@gmail.com`)
   - **App Password** — the 16-character password

**Where it's saved:** `config.json` → `smtp_email` and `smtp_password`

---

### 2.2 Imghippo API Key (required for product images)

Imghippo is a free image hosting service. Product images you upload are stored here and linked in emails.

**Free tier:** 500 MB storage, no credit card required.

**Steps:**

1. Go to [imghippo.com](https://imghippo.com) and click **Sign Up**
2. Enter your email and verify it
3. Log in, then go to **Settings → API Keys** in the dashboard
4. Click **Generate API Key** → copy the key
5. In MERIT: go to **Settings → Image Hosting** and paste the key
6. Click **Test Key** to confirm it works, then **Save Settings**

**Where it's saved:** `config.json` → `imghippo_api_key`

---

### 2.3 Supabase (optional, recommended)

Supabase gives you a cloud Postgres database so your products and inventory are accessible from any machine. Without it, data is stored only in a local SQLite file (`data.db`).

**Free tier:** 500 MB database, 2 projects, no credit card required.

**Steps:**

1. Go to [supabase.com](https://supabase.com) and click **Start your project**
2. Sign in with GitHub or email
3. Click **New project** → give it a name → pick a region close to you → set a strong database password → click **Create new project** (takes ~2 minutes)
4. Once ready, go to **Project Settings → API** in the left sidebar and copy:

   | Field | Where to find it | Config key |
   |---|---|---|
   | **Project URL** | Top of the API settings page | `supabase_url` |
   | **Anon key** | Under *Project API keys* — the `anon` / `public` row | `supabase_key` |
   | **Service role key** | Under *Project API keys* — the `service_role` row | `supabase_service_role_key` |

   > Keep the **service role key** secret — it bypasses Row Level Security and has full database access.

5. For the **Personal Access Token** (needed to auto-create tables from within the app):
   - Go to [supabase.com/dashboard/account/tokens](https://supabase.com/dashboard/account/tokens)
   - Click **Generate new token** → give it a name → copy it (starts with `sbp_…`)
   - Paste it into **Settings → Supabase → Personal Access Token**

6. In MERIT: go to **Settings → Database Connections → Supabase** and fill in all four fields
7. Click **Save Settings**, then **Setup Tables** — this creates the `inventory` and `products` tables automatically

**Where it's saved:** `config.json` → `supabase_url`, `supabase_key`, `supabase_service_role_key`, `supabase_pat`

---

### 2.4 Neon (optional, alternative to Supabase)

Neon is a serverless Postgres service. Use it instead of (or alongside) Supabase.

**Free tier:** 0.5 GB storage, 1 project.

**Steps:**

1. Go to [neon.tech](https://neon.tech) and click **Sign Up**
2. Create a new project (pick a region close to you)
3. Go to your project **Dashboard → Connection Details**
4. In the dropdown, select **psql** or **postgresql** to get the connection string format
5. Copy the connection string — it looks like:

   ```
   postgresql://neondb_owner:PASSWORD@ep-xxxx.us-east-2.aws.neon.tech/neondb?sslmode=require
   ```

   > **Common mistake:** Do NOT paste the REST/HTTP URL (`https://ep-…`). MERIT uses `psycopg2` which requires the `postgresql://` connection string.

6. In MERIT: go to **Settings → Database Connections → Neon** and paste the string
7. Click **Test Connection** to verify, then **Setup Tables**

**Where it's saved:** `config.json` → `neon_connection_string`

---

## 3. First-Run Setup Checklist

After cloning and running `streamlit run app.py`:

- [ ] Open **Settings**
- [ ] Fill in **From Name** (your store/brand name) — this becomes the browser tab title
- [ ] Fill in **Default Subject Line**
- [ ] Add your **Gmail address** and **App Password** under Gmail SMTP
- [ ] Add your **Imghippo API Key** under Image Hosting
- [ ] *(Optional)* Connect Supabase or Neon under Database Connections → click **Setup Tables**
- [ ] Click **Save Settings**
- [ ] Go to **Products** → add your product catalog (with images)
- [ ] Go to **Email Sender** → build a queue and send your first email

---

## 4. HTML Email Templates

MERIT lets you fully customise the HTML layout of your order confirmation emails.

### How it works

Go to **Email Sender → Email Template**. You can:
- Edit the HTML directly in the text editor
- Use the AI prompt to generate a custom template
- Preview what a sample email looks like before saving
- Reset to the built-in default at any time

The template is saved to `config.json` (`email_html_template`) and used automatically for all future sends.

### Available variables

Use these placeholders anywhere in your HTML — MERIT replaces them with real order data before sending:

| Variable | What it inserts |
|---|---|
| `{{name}}` | Customer's name |
| `{{order_number}}` | Order number |
| `{{from_name}}` | Your store / company name (from Settings) |
| `{{items_html}}` | Pre-built HTML table rows listing every ordered product, with product images when available |

**Example usage:**

```html
<p>Hi {{name}}, your order <strong>#{{order_number}}</strong> is confirmed.</p>
<table cellpadding="0" cellspacing="0" style="width:100%;">
  {{items_html}}
</table>
<p>Thanks, {{from_name}}</p>
```

### Generate a template with AI

In the **Email Template** tab, expand **AI prompt — copy this into ChatGPT / Claude** and copy the prompt. Replace the design brief at the bottom (e.g. `"clean and minimal, brand color #4F46E5"`), paste into your AI of choice, then copy the returned HTML back into the template editor and click **Save Template**.

### Requirements for custom templates

- Must be a complete HTML document (`<!DOCTYPE html>` through `</html>`)
- Inline styles only — no `<link>` stylesheets, no JavaScript (most email clients block them)
- Table-based layout for maximum email client compatibility
- Must include `{{items_html}}` wrapped in a `<table>` element
- Recommended max content width: 600 px

---

## 5. Features Overview

### Email Sender
- Add orders one at a time, in bulk via a data table, or by importing a CSV/TSV
- Custom HTML email templates with live preview
- Sends via Gmail SMTP with a progress bar and per-email status log

### Products
- Add single or bulk products with images
- Bulk edit and bulk delete
- Images uploaded to Imghippo automatically
- Catalog view with per-product edit and image replacement

### Inventory
- Real-time stock tracking (adjust by delta or set absolute value)
- Bulk add products with initial stock
- Bulk edit all fields including stock
- Delete products across all databases simultaneously

### Settings
- All credentials stored locally in `config.json` (gitignored)
- Test buttons for SMTP and Imghippo connections
- One-click database table setup for Supabase and Neon

---

## 6. Database Architecture

MERIT writes to all configured databases simultaneously so data is always in sync.

| Database | Type | When used |
|---|---|---|
| SQLite (`data.db`) | Local file | Always — built-in fallback, no setup needed |
| Supabase | Cloud Postgres | When configured in Settings |
| Neon | Serverless Postgres | When configured in Settings |
| `config.json` `products` array | JSON file | Always — keeps a config-level copy |

**Read priority:** Supabase → Neon → SQLite → config.json

Both `config.json` and `data.db` are in `.gitignore` and are never committed.

---

## 7. Troubleshooting

**"SMTP Authentication Error" when sending**
- Make sure you are using a **Gmail App Password**, not your regular Gmail password
- App Passwords are 16 characters with no spaces — remove any spaces before saving
- Confirm 2-Step Verification is enabled on your Google account

**"Supabase credentials not configured"**
- Go to Settings → Supabase and make sure Project URL and at least one key are filled in, then Save Settings

**"relation 'inventory' does not exist"**
- Click **Setup Tables** in Settings → Database Connections after entering your credentials

**Images not appearing in emails**
- Confirm your Imghippo API key is set and the Test Key button shows success
- Products need to have images uploaded before they appear in order emails

**Data not persisting between sessions**
- Make sure `config.json` exists (copy from `config.template.json`) and the app has write permission to the folder
- If running on a cloud platform (Streamlit Cloud, Heroku, etc.), use Supabase or Neon for persistent storage — local files reset on restart

**App shows "MERIT" instead of your store name**
- Go to Settings, fill in **From Name**, and click **Save Settings**

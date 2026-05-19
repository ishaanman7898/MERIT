# MERIT

**Mass Email and Inventory Tool for VEI Firms**

MERIT is the productivity platform built for Virtual Enterprise International firms. Send personalized order confirmation emails to hundreds of customers in seconds, manage a professional product catalog, and track live inventory — all from one dashboard. No coding required.

[Get Started](#getting-started) · [Pages Overview](#pages-overview) · [API Endpoints](#api-endpoints)


## What MERIT Does

**Bulk Email Sending** — Deliver personalized order confirmation emails to your entire customer list in one click.

**Inventory Sync** — Stock levels deduct automatically each time an order email goes out, so your numbers are always accurate.

**Image Hosting** — Built-in integration with Freeimage.host and Imghippo. Upload multiple images per product and MERIT handles the rest.

**Financials** — Revenue overview, monthly breakdowns, a full ledger, and per-product sales reporting.

**Secure Access** — Individual user accounts with role-based access control. Admins manage who sees what.

**Cloud Storage** — Turso (primary) and Supabase (optional) keep your data synchronized and accessible from any device.

**Excel Import** — Drop in a VEI Checkout Excel export and eliminate manual data entry entirely.


## Hardware Recommendations

MERIT runs on Streamlit, which can have performance issues on school-issued Chromebooks. For the smoothest experience, use a personal laptop or a school-provided VE laptop.


## Getting Started

> [!IMPORTANT]
> Use your official VEI Firm Email for all account registrations — Supabase, Turso, Gmail SMTP, and Image Hosting — so that access carries over to future firm members.

> [!NOTE]
> After deploying, open your app and go to **Get Started** inside the app. It walks through every step interactively with status indicators. The sections below are a complete reference copy of that same guide.

### 0. Fork and Deploy to Streamlit Cloud

Start here. You need a running app before you can configure anything.

**Create your repository from this template**

1. Go to the MERIT GitHub repository page.
2. Click **Use this Template** in the top right corner.
3. Under Owner, select your firm's GitHub account.
4. Name the repository (e.g. `MERIT-Nova`) and create it. It must be public.
5. You now have your own copy of MERIT.

**Deploy on Streamlit Cloud**

1. Go to [share.streamlit.io](https://share.streamlit.io) and sign in with the same GitHub account.
2. Click **Create app**.
3. Under Repository, select your forked MERIT repository.
4. Set the Main file path to `app.py`.
5. Click **Deploy**. Streamlit will build and launch your app in about a minute.
6. Once live you will receive a public URL (e.g. `https://yourname-merit-app-xxxxx.streamlit.app`). Share this with your firm.


### Step 1 — Create Your Admin Account (Do This First)

Create at least one **Admin** user so you can sign in after setup is complete.

After setup is done (secrets saved and app reboots), go to **Settings → Team** to invite additional team members. They receive a shareable link and set their own password — no credential sharing needed.

**Roles** control which pages each person can see. Three built-in roles cover most firms:

| Role | Access |
|---|---|
| **Admin** | All pages including Settings |
| **Staff** | Mass Email, Products, Inventory, Financials |
| **Viewer** | Read-only access to Products and Inventory |

You can also create custom roles with exactly the page permissions your firm needs.

**To create your first user:**

1. Open your deployed app — the **Get Started** page appears automatically.
2. Under Step 1, fill in Full Name, Email, Role, and Password.
3. Click **Create User**.


### Step 2 — Connect a Cloud Database

MERIT needs a cloud database so your products, inventory, users, and financials persist even when the app restarts. Connect **Turso** (recommended) or **Supabase** — or both for redundancy. Both are free for VEI firms.

#### Option A — Turso (Recommended)

Turso is a fast, distributed SQLite database — simple to set up and free for VEI firms.

**1. Sign in to Turso**

Go to [turso.tech](https://turso.tech) and sign in with your VE email.

**2. Create your database**

1. On the **Databases** page, click **Create database**.
2. **Name** — enter your organization name (e.g. `bluepeak-ventures`).
3. Leave the **Group** as the default.
4. Click **Create database**.

**3. Copy your Database URL**

On the database page, look in the **Connect** section and copy the `libsql://` link.
It looks like: `libsql://[your-org-name]-[username].turso.io`

Paste it into **Settings → Database → Turso → Database URL**.

**4. Get your Auth Token**

Right below the `libsql://` URL on your database page you will see a **Create a token** link — click it.

- **Expiration:** 1 year
- **Authorization:** Read & Write

Click **Create** and copy the long string that appears (starts with `eyJ…`).

Paste it into **Settings → Database → Turso → Auth Token**.

> [!WARNING]
> This is a database-specific token. Do NOT use the Platform API token from the sidebar avatar menu — that token only manages Turso itself and will be rejected with a 401 error.

**5. Set up tables**

In MERIT go to **Settings → Database** and click **Setup Turso Tables**.
This creates all MERIT tables in your Turso database and syncs your users and roles from Step 1.

#### Option B — Supabase

Supabase is a PostgreSQL-based cloud database. It works well for larger firms or those already using Supabase.

**1. Sign up at Supabase**

Go to [supabase.com](https://supabase.com) → **Sign Up** with your VE email.

**2. Create a new project**

| Field | What to enter |
|---|---|
| **Organization** | Your VE email (pre-selected) |
| **Project name** | Your VEI firm name (e.g. `BluePeak Ventures`) |
| **Database password** | Create your own — do NOT use Generate. Write it down. |
| **Region** | Closest to your location |

Click **Create new project** and wait about 60 seconds.

**3. Get your connection string**

1. Click the green **Connect** button at the top right.
2. Select the **Session Pooler** tab.
3. Copy the connection string:
   `postgresql://postgres.xxxxxxxxxxxx:[YOUR-PASSWORD]@aws-0-us-east-1.pooler.supabase.com:5432/postgres`
4. Go to **Settings → Database** and paste it, then click **Setup Tables**.

**4. Get your Anon Key (for API Endpoints)**

1. Supabase Dashboard → gear icon → **Project Settings** → **API**.
2. Under **Legacy API keys** → copy the **anon / public** key (starts with `eyJ…`).
3. Paste it into **Settings → Database → Supabase Anon Key**.


### Step 3 — Set Up Image Hosting

Product images must be hosted online to appear in emails and on your storefront. Pick one free service and use your official VE email when signing up.

**Option A — Freeimage.host (recommended)**
1. Go to [freeimage.host](https://freeimage.host) and sign in.
2. Click the top-left menu → **API** → copy your API key.
3. Paste it into **Settings → Image Hosting**.

**Option B — Imghippo**
1. Go to [imghippo.com](https://imghippo.com) → create a free account.
2. Go to Settings → API Keys → copy the API Version 1 key.
3. Paste it into **Settings → Image Hosting**.


### Step 4 — Configure Gmail SMTP

MERIT sends order emails via your official VE Gmail account. An App Password is required for secure authentication.

1. Go to [myaccount.google.com](https://myaccount.google.com) → **Security** → enable **2-Step Verification**.
2. Search for **App passwords** → create one named `MERIT Email`.
3. Copy the 16-character password Google shows you.
4. In **Settings → Email**, paste your VE Gmail address and the App Password.


### Step 5 — Set Sender Identity

Controls who the email appears to come from.

1. In **Settings → Email**, fill in **Sender Identity**:
   - **From Name** — Your VEI firm name (e.g. `Acme VEI`).
   - **Default Subject Line** — e.g. `Your order from Acme VEI`.


### Step 6 — Save Secrets TOML (Final Step)

Streamlit Cloud forgets everything on reboot. Saving a Secrets TOML makes all your credentials permanent.

1. Go to **Settings → Secrets TOML** and copy the generated code block.
2. In Streamlit Cloud, click **Manage app** (bottom-right) → **⋮** → **Settings** → **Secrets**.
3. Paste the code and click **Save**.
4. The app reboots and **Get Started disappears from the sidebar** — setup is complete.


## Pages Overview

| Page | What it does |
|---|---|
| **Get Started** | Interactive setup wizard — walks through all six steps with live status indicators |
| **Mass Email** | Upload CSV orders, send bulk emails, manage templates and campaigns |
| **Products** | Add, edit, and delete products with images and descriptions |
| **Inventory** | Stock overview, adjust stock, original stock tracking, and outbound logs |
| **Financials** | Revenue overview, ledger, order history, and product revenue breakdowns |
| **Settings** | All credentials — Turso, Supabase, email, image hosting, and team management |
| **API Endpoints** | Pre-built SQL and JavaScript code to connect your website to the live database |


## Database Architecture

MERIT uses a three-layer database approach.

| Layer | Role |
|---|---|
| **Turso** (primary cloud) | Recommended. Distributed SQLite — fast, free, and no extra packages required. All reads and writes hit Turso when connected. |
| **Supabase** (secondary cloud) | Optional PostgreSQL backup. Also provides the Anon Key for storefront API access. |
| **SQLite** (local cache) | Always present. Used for initial setup before cloud credentials are saved, and as an offline fallback. |

When both Turso and Supabase are connected, MERIT writes to all three simultaneously so your data is always consistent. See [docs/database.md](docs/database.md) for technical details.


## API Endpoints

Connect your storefront website (Bolt.new, Lovable, Cursor, etc.) directly to your MERIT database for real-time product and inventory data.

| Table | Purpose |
|---|---|
| `inventory` | Live stock levels and product details for your storefront catalog |
| `products` | Clean catalog listing for external integration and display |
| `outbound_logs` | Audit trail of sent emails including subtotal, tax, and shipping data |

> [!TIP]
> Use the **API Endpoints** page inside the app to access pre-generated SQL and JavaScript code for fast integration.


## Privacy and Security

**Direct Connection** — Data travels directly from your application to Gmail, Turso, and Supabase. Nothing passes through a third party.

**Full Ownership** — All credentials are stored exclusively in your Streamlit Secrets or local configuration files. We never see them.

**Open Source** — The full source code is available for review so your firm can verify exactly what MERIT does with your data.


## Frequently Asked Questions

**Do I need to know how to code?**
No coding is required. Setup involves copying and pasting configuration keys from one service into another.

**Which database should I use — Turso or Supabase?**
Start with Turso. It is simpler to set up, requires no extra Python packages, and is free for VEI firms. Add Supabase later if you need the Anon Key for storefront API access or want a PostgreSQL backup.

**Can multiple people use MERIT at the same time?**
Yes. Once Turso or Supabase is connected, all firm members can manage inventory and send emails simultaneously using their own accounts.

**What if Streamlit is blocked at school?**
Some school networks block Streamlit. Use a personal device to complete the initial setup. Once your Secrets TOML is saved, the app is accessible from any browser on any network.

**Can I set up MERIT on my phone?**
Yes. The setup steps work from a phone or tablet browser. Open your Streamlit app URL, fill in your credentials, and copy the Secrets TOML before the session ends.

**What happens if Streamlit restarts?**
Streamlit Cloud restarts periodically and clears local files. Your Secrets TOML preserves all credentials, and Turso/Supabase preserve all your data. The app resumes exactly where it left off.


---

Built for VEI Firms worldwide.

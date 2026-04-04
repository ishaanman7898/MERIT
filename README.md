# MERIT — Mass Email & Inventory Tool for VEI Firms

MERIT is a browser-based app built specifically for **Virtual Enterprise International (VEI)** firms. It lets you send personalised order-confirmation emails in bulk, manage a product catalog with images, and track live inventory — all from one tab, with no coding required after setup.

---

## Try the app

MERIT runs on two platforms. Test both links below and use whichever one opens on your school or work network — some networks block one but not the other.

| Platform | Link | When to use |
|---|---|---|
| **Streamlit** (recommended) | [Open Streamlit app](https://ishaanman7898-merit-merit-app-bfhyad.streamlit.app) | Try this first — full-featured version |
| **Gradio** (fallback) | Deploy your own — see [Section 3b](#3b-deploy-the-gradio-fallback-app) | Use this if Streamlit is blocked on your network |

> **Which one should I use?** Try the Streamlit link first. If it loads, use that — it has every feature. If your school or work network blocks it, follow Section 3b to set up the Gradio version.

---

## Table of Contents

1. [What is MERIT and who is it for?](#1-what-is-merit-and-who-is-it-for)
2. [The big picture — what accounts you need](#2-the-big-picture--what-accounts-you-need)
3. [Deploy the app (one-time setup)](#3-deploy-the-app-one-time-setup)
   - [3b. Deploy the Gradio fallback app](#3b-deploy-the-gradio-fallback-app)
4. [Settings — step by step](#4-settings--step-by-step)
   - [4.1 Sender Identity](#41-sender-identity)
   - [4.2 Gmail App Password](#42-gmail-app-password)
   - [4.3 Image Hosting — Freeimage.host](#43-image-hosting--freeimagehostcreate-account--get-key)
   - [4.4 Image Hosting — Imghippo (alternative)](#44-image-hosting--imghippo-alternative)
   - [4.5 Supabase cloud database](#45-supabase-cloud-database)
   - [4.6 Neon cloud database (alternative)](#46-neon-cloud-database-alternative)
5. [Using Email Sender](#5-using-email-sender)
6. [Using Products](#6-using-products)
7. [Using Inventory](#7-using-inventory)
   - [7.1 Overview dashboard](#71-overview-dashboard)
   - [7.2 Adjusting stock](#72-adjusting-stock)
   - [7.3 Outbound Information — email tracking](#73-outbound-information--email-tracking)
8. [How databases work (offline fallback + sync)](#8-how-databases-work-offline-fallback--sync)
9. [API Endpoints — connect your website](#9-api-endpoints--connect-your-website)
   - [9.1 What it does](#91-what-it-does)
   - [9.2 Quick start (Bolt.new / Lovable / Cursor)](#92-quick-start-boltnew--lovable--cursor)
   - [9.3 REST API reference](#93-rest-api-reference)
   - [9.4 Row Level Security (public read)](#94-row-level-security-public-read)
   - [9.5 Real-time subscriptions](#95-real-time-subscriptions)
10. [Error messages explained](#10-error-messages-explained)
11. [Frequently asked questions](#11-frequently-asked-questions)
12. [Excel Import — VEI Checkout](#12-excel-import--vei-checkout)

---

## 1. What is MERIT and who is it for?

**MERIT** stands for Mass Email & Inventory Tool. It is made for VEI student firms that need to:

- Send a batch of order confirmation emails to multiple customers at once (instead of manually writing each one)
- Keep track of which products they sell, complete with photos and prices
- Track how many of each item they have left in stock

You run MERIT from a web browser — no coding, no spreadsheets, no manually writing emails one by one.

---

## 2. The big picture — what accounts you need

> **CRITICAL SETUP INSTRUCTION:**
> This tool is strictly for your VEI firm. **Everything must be done with your VEI account (or firm email) provided by your teacher, facilitator, or administrator.** 
> **DO NOT** use your personal emails, personal GitHub accounts, or personal Google accounts for any of these steps. This ensures your data stays with the firm and passes to the next class correctly.

Before using MERIT, you need to set up operations accounts. Remember: every single account below must be registered with your **VEI firm email**.

| What | Why | Cost | Used with which email? |
|---|---|---|---|
| **Gmail account** | MERIT sends firm emails through Gmail | Free | VEI Firm Email ONLY |
| **Freeimage.host account** | Stores your product photos online | Free | VEI Firm Email ONLY |
| **Supabase account** (recommended) | Database to save your products in the cloud | Free | VEI Firm Email ONLY |
| **GitHub account** | Used to fork the code & deploy to Streamlit | Free | VEI Firm Email ONLY |
| **Streamlit account** | Hosts the app in your browser | Free | VEI Firm Email ONLY |

> **VEI Firm Tip:** Your firm should have a shared Gmail address assigned to your department (like `acme-vei@gmail.com`). Use that address to sign up for all other services. You will also need to generate a Gmail App Password from that account (the teacher cannot bypass this for you).

---

## 3. Deploy the app (one-time setup)

This section gets the app running on the internet so everyone in your firm can access it. Because you are using VEI accounts, please follow these steps precisely so the accounts link correctly.

### Step 1 — Create a VEI GitHub account & Link it

You need a GitHub account to hold the code before Streamlit can host it.
1. Go to [github.com/signup](https://github.com/signup).
2. Enter your **VEI firm email address** (e.g., your assigned `@school.edu` or firm email). **Do not use a personal email.**
3. Create a strong password (save it in your firm's password manager if you have one).
4. Enter a username related to your firm (e.g., `AcmeFirmVEI`).
5. Complete the verification puzzle and click **Create account**.
6. Check your VEI firm email inbox and paste the launch code GitHub sent you to verify everything.

### Step 2 — Fork this repository with your VEI account

"Forking" means taking a copy of the MERIT code and putting it into your new VEI GitHub account.
1. Make sure you are signed into [github.com](https://github.com) with the VEI account you just made.
2. Go to the original MERIT repository page.
3. In the top-right corner of the page, click the **Fork** button.
4. On the "Create a new fork" screen, ensure the "Owner" is your VEI account. Leave everything else as it is.
5. Click the green **Create fork** button. 
6. Wait a few seconds. You now have a complete copy of MERIT physically linked to your VEI firm's account!

### Step 3 — Create a Streamlit account and deploy

1. Keep your VEI GitHub account logged in on a tab.
2. Go to [share.streamlit.io/signup](https://share.streamlit.io/signup).
3. Click **Continue with GitHub**. (Because you are using the VEI GitHub account, Streamlit will automatically link the two! This is why using the VEI account across the board is so important).
4. Authorize Streamlit if it asks for permission.
5. On your Streamlit dashboard, click **Create app**.
6. Select **"Deploy a public app from GitHub"**.
7. In the **Repository** dropdown, find your forked MERIT repo (e.g., `AcmeFirmVEI/MERIT`).
8. Check that these fields match exactly:
   - **Branch:** `master` (or `main`)
   - **Main file path:** `app.py`
   - **App URL:** Type your firm name with no spaces (like `acme-merit-firm`) — this will create your live web link: `https://acme-merit-firm.streamlit.app`.
9. Click **Deploy**. Wait about 60 seconds.

### Step 4 — Open the app and go to Settings

Once the loading finishes, your app will be live on the internet! 
You will see a **Privacy Agreement** screen first. Read it and click **I Agree — Continue to MERIT**.

Then click **Settings** in the left sidebar and follow section 4 below.

---

## 3b. Deploy the Gradio fallback app

Use this if Streamlit is blocked on your network. Gradio runs on Hugging Face Spaces (free).

### Option A — Hugging Face Spaces (recommended, runs in your browser)

1. Go to [huggingface.co](https://huggingface.co) → click **Sign Up** (free account)
2. Click your profile picture → **New Space**
3. Fill in the form:
   - **Space name:** `merit-gradio` (or anything you like)
   - **SDK:** choose **Gradio**
   - **Visibility:** Private (recommended — keeps your config private)
4. Click **Create Space**
5. On the **Files** tab, upload these two files from your forked MERIT repo:
   - `gradio_app.py` → rename to `app.py` when uploading
   - `requirements_gradio.txt` → rename to `requirements.txt` when uploading
6. Hugging Face will build and launch the app automatically (takes about 60 seconds)
7. Your Gradio app URL will be: `https://huggingface.co/spaces/YOUR-USERNAME/merit-gradio`

### Option B — Run locally (no account needed)

If you just want to run it on your own laptop:

```bash
pip install gradio psycopg2-binary pandas Pillow
python gradio_app.py
```

Then open [http://localhost:7860](http://localhost:7860) in your browser.

### What the Gradio app includes

| Feature | Available |
|---|---|
| Email Campaigns (broadcast emails to a contact list) | Yes |
| Live product catalog from Supabase | Yes |
| Settings (SMTP, Supabase, image hosting) | Yes |
| Order queue with individual order emails | Streamlit only |
| Inventory management | Streamlit only |
| API Endpoints / AI Prompts | Streamlit only |

---

## 4. Settings — step by step

> **Important:** After filling in any section of Settings, always scroll to the bottom of the page and click **Save Settings**. Nothing is saved until you click that button.

---

### 4.1 Sender Identity

These two fields appear at the very top of Settings:

- **From Name** — Type your VEI firm's name exactly as you want it to appear in every email (e.g. `Acme VEI Firm`). This also appears as the browser tab title for the app.
- **Default Subject Line** — The subject line every customer will see in their inbox (e.g. `Your order #{{order_number}} is confirmed`). You can use `{{order_number}}` and it will be replaced with the actual order number automatically.

---

### 4.2 Gmail App Password

**What this is for:** MERIT sends emails through your Gmail account. Gmail does not allow apps to log in with your regular password for security reasons, so you need to create a special one-time password called an **App Password**.

**An App Password is NOT your Gmail password.** It is a separate 16-character code that only works for one app. You can delete it at any time without changing your real password.

**Step-by-step:**

1. Open a new tab and go to [myaccount.google.com](https://myaccount.google.com)
2. Make sure you are signed into the Gmail account your firm will send emails from
3. Click **Security** in the left sidebar
4. Look for **"How you sign in to Google"** — find **2-Step Verification** and make sure it says **On**
   - If it says Off, click it and follow the steps to turn it on. This is required before App Passwords will appear.
5. In the search bar at the top of the Google account page, type `App passwords` and click the result
   - You may need to sign in again with your password at this step
6. Under **App name**, type `MERIT` (just a label so you remember what it is for)
7. Click **Create**
8. Google shows you a 16-character password in a yellow/grey box — **copy it immediately**. This password is only shown once. It looks like: `abcd efgh ijkl mnop`
9. Go back to MERIT → **Settings → Gmail SMTP**
10. In **Gmail Address**, type the full Gmail address you signed into
11. In **App Password**, paste the 16-character code. Remove any spaces if there are any — it should be exactly 16 letters with no spaces.
12. Scroll to the bottom and click **Save Settings**
13. Click **Test Connection** (or send a test email) to confirm it works

> **VEI Firm:** If your teacher gave you a firm Gmail address like `acmevei@gmail.com`, use that address here. But you still need to sign into that Gmail account yourself and create an App Password. The teacher cannot create an App Password for you remotely.

---

### 4.3 Image Hosting — Freeimage.host (create account + get key)

**What this is for:** When you upload a product photo, MERIT needs to store it online so it can appear in customer emails. Freeimage.host does this for free with no credit card.

**Step-by-step:**

1. Open [freeimage.host](https://freeimage.host) in a new tab
2. Click **Sign up** in the top-right corner
3. Enter an email address and password, then click **Sign up**
4. Check your email and click the verification link
5. Log back into [freeimage.host](https://freeimage.host)
6. Click the **menu icon (☰)** in the **top-left corner** of the page — it looks like three horizontal lines
7. Click **API** in the menu that appears
8. You will see a page titled "API version 1" with your **API Key** shown (it is a long string of letters and numbers like `your_freeimage_host_api_key_here`)
9. Copy that key
10. Go to MERIT → **Settings → Image Hosting → Freeimage.host** tab
11. Paste it into the **Freeimage.host API Key** field
12. Click **Test Key** — you should see a green message saying the key works
13. Scroll down and click **Save Settings**

---

### 4.4 Image Hosting — Imghippo (alternative)

If you prefer Imghippo instead of Freeimage.host, use this guide. You only need **one** image hosting service.

1. Sign up at [https://www.imghippo.com/](https://www.imghippo.com/)
2. Navigate to API Keys at [https://www.imghippo.com/settings?tab=api-keys](https://www.imghippo.com/settings?tab=api-keys)
3. Complete the API access form (5 steps):
   - **Step 1 – Primary Use Case:** Select Website/Web Application
   - **Step 2 – Expected Usage Volume:** Select Less than 1,000
   - **Step 3 – Main Feature Needed:** Select Image upload and sharing
   - **Step 4 – Business Email:** Skip (optional)
   - **Step 5 – Acceptable Use Confirmation:** Select Yes, I agree
4. Copy the generated API key
5. Go to MERIT → **Settings → Image Hosting → Imghippo** tab
6. Paste the API key into the Streamlit app when prompted and test
7. Click the **Save Settings** button at the end of the settings page when making everything work.
8. If the key does not work, then retry the steps or try with a different account.

---

### 4.5 Supabase cloud database

**What this is for:** Supabase is a free online database. Without it, your products and inventory are only saved on the computer running the app. If the app restarts (which Streamlit Cloud does regularly), all your data would be wiped. Supabase keeps everything safe in the cloud.

**This is strongly recommended** — without it, you will need to re-enter your products every time the app restarts on Streamlit Cloud.

**Step-by-step:**

1. Open [supabase.com](https://supabase.com) in a new tab
2. Click **Start your project** (top right)
3. Click **Sign up** — you can sign in with your GitHub account (convenient) or create a new email account
4. Once signed in, click **New project** on your Supabase dashboard
5. Fill in the form:
   - **Name:** anything you like (e.g. `merit-db`)
   - **Database Password:** choose a strong password — **write this down somewhere safe**
   - **Region:** pick whichever is closest to you (e.g. US East, EU West)
   - Leave everything else as default
6. Click **Create new project** — this takes about 1–2 minutes to set up
7. Once the project is ready, look at the left sidebar and click **Project Settings** (the gear icon)
8. Click **API** in the left sidebar under Project Settings
9. You will see a page with your credentials. You need to copy three things:

   **Project URL** (at the top):
   - Looks like: `https://abcdefghijklmnop.supabase.co`
   - Copy it and paste into MERIT → Settings → Database Connections → Supabase → **Project URL**

   **Anon key** (under "Project API keys"):
   - The row labelled `anon` or `public`
   - A very long string starting with `eyJ…`
   - Copy it and paste into MERIT → **Anon Key**

   **Service role key** (under "Project API keys"):
   - The row labelled `service_role`
   - Also a long string starting with `eyJ…`
   - Copy it and paste into MERIT → **Service Role Key**
   - Keep this one private — it has full admin access to your database

10. Now get your **Personal Access Token** (this lets MERIT create your database tables automatically):
    - Open a new tab and go to [supabase.com/dashboard/account/tokens](https://supabase.com/dashboard/account/tokens)
    - Click **Generate new token**
    - Give it a name like `MERIT`
    - Copy the token that appears — it starts with `sbp_…`
    - Paste it into MERIT → Settings → Supabase → **Personal Access Token**

11. Click **Save Settings** in MERIT
12. Click **Test Connection** — green means it is working
13. Click **Setup Tables** — this creates the database tables MERIT needs. You should see "Tables created successfully."

Your data is now safe in the cloud. Every time you add a product or adjust inventory, it saves to Supabase automatically.

---

### 4.6 Neon cloud database (alternative)

Neon is another free online database, similar to Supabase. You only need **one** database service — use this if you prefer Neon or if Supabase is not working for you.

**Step-by-step:**

1. Open [neon.tech](https://neon.tech) in a new tab
2. Click **Sign Up** — you can use your GitHub account or email
3. Once signed in, you will see the Neon Console
4. Click **Create a project**
5. Give the project a name (e.g. `merit`) and choose a region, then click **Create project**
6. On your project's **Dashboard**, click the **Connect** button
7. A panel appears showing your connection string. Click **Copy** next to the connection string
   - It looks like: `postgresql://neondb_owner:PASSWORD@ep-xxxx.us-east-2.aws.neon.tech/neondb?sslmode=require`
   - Make sure the dropdown is set to **psql** or **postgresql** format, not the REST format
8. Go to MERIT → **Settings → Database Connections → Neon**
9. Paste the connection string into the **PostgreSQL Connection String** field
10. Click **Test Connection** — green means it works
11. Click **Setup Tables** — this creates the database tables automatically
12. Click **Save Settings**

---

### 4.7 Auto-save

**Settings are saved automatically** the moment you leave any field (press Tab, click elsewhere, or press Enter).  
You do not need to click any button. The **Save & Sync to Cloud** button at the bottom of Settings is only needed when you want to force-push all existing products up to Supabase or Neon in one go.

You can close and reopen the app at any time — all your credentials will still be there.

---

## 5. Using Email Sender

The Email Sender is the main feature of MERIT. You build a list of customer orders and send all their confirmation emails in one click.

### Adding orders

**Single order:** Fill in the form on the left — customer Name, Email, Order Number, and the Products they ordered. Products can be typed as a list separated by commas, semicolons, or one per line. Click **Add to Queue**.

**Multiple orders at once (bulk entry):** Click the **Bulk Entry** tab. A table appears where you can type multiple orders. Fill in as many rows as you need, then click **Add All to Queue**.

**From a file (CSV/TSV):** If you have a spreadsheet of orders, export it as a `.csv` file. The file needs columns named `name`, `email`, `order_number`, and `products`. Upload it using the file uploader.

### Sending emails

Once your queue has orders in it, click **Send All Emails**. MERIT will:

1. Connect to Gmail using your credentials
2. Build a personalised email for each order
3. Send each one and show a live log of what is happening
4. Show you how many were sent and how many failed

### Automatic stock deduction

After every successful email send, MERIT automatically reduces stock by 1 for each product in that order. So if you send 5 orders all containing "Blue T-Shirt", the Blue T-Shirt stock goes down by 5.

---

## 6. Using Products

The Products page manages your product catalog — names, SKUs, prices, categories, and photos.

### Adding products

Fill in the **Add Product** form: give each product a unique **SKU** (a short code like `SHIRT-001`), a name, category, price, and optionally upload a photo. Click **Add Product**.

### Bulk adding

Use the **Bulk Add** tab to add many products at once. Fill in the table rows and click **Add All Products**.

### Editing products

Use **Bulk Edit** to edit many products in a spreadsheet-style table. Or use **Edit Product** to select and edit one product at a time.

### Deleting products

Use **Bulk Delete** to select which products to remove and click **Delete Selected**.

---

## 7. Using Inventory

The Inventory page tracks how many units of each product you have.

### Overview dashboard

At the top you see four numbers at a glance: total products, total units in stock, low stock count, and out-of-stock count. A bar chart shows stock per product.

### Adjusting stock

In the **Adjust Stock** tab, each product has a **±** box. Enter a positive number to add stock (e.g. `+10` received a shipment of 10), or a negative number to remove it (e.g. `-3` sold 3). Click **Apply** per row, or **Apply All Changes** to do all at once.

### Stock status colours

| Colour | What it means |
|---|---|
| Green — **In stock** | 11 or more units available |
| Yellow — **Low stock** | 1 to 10 units left — order more soon |
| Red — **Out of stock** | 0 units — nothing left |
| Purple — **Backordered** | Negative number — more have been sold than exist (a VEI scenario where you confirm orders ahead of restocking) |

---

### 7.3 Outbound Information — email tracking

All sent emails are logged in the **Outbound Information** tab within the Inventory page. This provides a detailed audit trail of:
- **Recipient Details:** Name and email of the customer.
- **Order Number:** The unique transaction ID.
- **Ordered Products:** A list of items included in the order.
- **Price Breakdown:** Detailed tracking of Subtotal, Tax, Shipping, and Total Cost.
- **Inventory Impact:** Every successfully sent email automatically deducts the respective items from your live inventory.

---

## 8. Excel Import — VEI Checkout

MERIT supports importing order data directly from the **VEI Checkout** system's Excel export.

### 8.1 Format Requirements
The Excel file (`.xlsx`) must contain two specific sheets:
1.  **Sales transactions**: Contains customer info (name, email), order number, subtotal, tax, and shipping.
2.  **Sales transaction items**: Contains the line items (product names) linked by `Transaction no`.

### 8.2 Steps to Import
1.  Navigate to **Email Sender** → **Excel Import**.
2.  Upload your `.xlsx` file.
3.  Click **Import Excel**.
4.  MERIT will automatically link the products to the customers, calculate the totals, and add them to your sending queue.

---

## 9. How databases work (offline fallback + sync)

MERIT always writes your data to every database you have configured at the same time. This means your data is backed up in multiple places.

**If a cloud database (Supabase or Neon) goes offline:**
- MERIT will still save everything to the local SQLite database on the machine running the app
- You will not lose any data — writes to SQLite never fail as long as the app is running
- Any cloud write failures are shown as warnings, not errors that block you from continuing

**When the cloud comes back online:**
- Go to **Settings → Database Connections**
- Click **Sync Local → Cloud**
- MERIT reads every row from local SQLite and pushes it to your cloud databases
- You will see a confirmation of how many rows were synced

**Read order (which database MERIT reads from first):**
1. Supabase (if configured and reachable)
2. Neon (if configured and reachable)
3. Local SQLite (always available)

---

## 9b. API Endpoints — connect your website

> **This page is inside MERIT under the "API Endpoints" navigation item.**
> It only becomes available after you connect Supabase in Settings.

### 9b.1 What it does

Every product you add, edit, or delete in MERIT is immediately written to your Supabase database.  
Any website — built on Bolt.new, Lovable, Cursor, v0, or written by hand — can connect to the same Supabase project and display your live product catalog without any manual exporting or copy-pasting.

**Two tables are kept in sync:**

| Table | Columns | Best used for |
|---|---|---|
| `inventory` | sku, item_name, category, price, stock_left, status, image_url | Storefront product listing with stock levels |
| `products` | sku, name, category, price, image_url, active | Clean catalog, no stock data |

### 9b.2 Quick start (Bolt.new / Lovable / Cursor)

1. Start a new project on your vibe-coding platform and choose **Supabase** as the backend.
2. When asked for connection details, enter:
   - **SUPABASE_URL** → your Supabase project URL (shown in MERIT → API Endpoints)
   - **SUPABASE_ANON_KEY** → your anon / publishable key (Settings → Database → Anon Key)
3. Tell the AI assistant to use the `inventory` table and filter with `stock_left > 0` for in-stock items.
4. Run the **Row Level Security SQL** (shown in MERIT → API Endpoints → Row Level Security SQL tab) so visitors can read products without the ability to write anything.
5. Enable **Replication** for the `inventory` table in Supabase Dashboard → Database → Replication for live updates.

### 9b.3 REST API reference

All calls need two headers:
```
apikey: <your-anon-key>
Authorization: Bearer <your-anon-key>
```

| Method | Endpoint | Description |
|---|---|---|
| GET | `/rest/v1/inventory?select=*` | All products |
| GET | `/rest/v1/inventory?select=*&stock_left=gte.1&order=item_name` | In-stock only, A→Z |
| GET | `/rest/v1/inventory?category=eq.Apparel&select=*` | Filter by category |
| GET | `/rest/v1/inventory?sku=eq.SKU001&select=*` | Single product by SKU |
| GET | `/rest/v1/products?select=*&active=eq.true&order=name` | Clean catalog, active only |

### 9b.4 Row Level Security (public read)

Run this SQL in your Supabase Dashboard → SQL Editor before going live:

```sql
ALTER TABLE inventory ENABLE ROW LEVEL SECURITY;
ALTER TABLE products  ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Public can read inventory"
  ON inventory FOR SELECT USING (true);

CREATE POLICY "Public can read products"
  ON products FOR SELECT USING (true);
```

This allows anyone with the anon key to read products, but **only MERIT** (using the service role key) can write.

### 9b.5 Real-time subscriptions

Enable replication in Supabase Dashboard → Database → Replication → toggle the `inventory` table, then use this in your website:

```javascript
import { createClient } from '@supabase/supabase-js'

const supabase = createClient(SUPABASE_URL, SUPABASE_ANON_KEY)

supabase
  .channel('merit-sync')
  .on('postgres_changes', { event: '*', schema: 'public', table: 'inventory' }, () => {
    refreshProducts()   // re-fetch your product list
  })
  .subscribe()
```

Every time you add, edit, or delete a product in MERIT, your website refreshes automatically.

---

## 10. Error messages explained

This section explains every error or warning you might see in plain English.

---

### Email errors

**"SMTP Authentication Error" or "Username and Password not accepted"**

What happened: Gmail rejected your login credentials.

What to do:
- Make sure you entered a **Gmail App Password**, not your regular Gmail password
- The App Password should be exactly 16 characters with no spaces
- Make sure 2-Step Verification is turned on for that Google account
- Try generating a new App Password — old ones sometimes stop working

---

**"Connection refused" or "timed out" when sending email**

What happened: MERIT could not reach Gmail's servers.

What to do:
- Check your internet connection
- If you are on a school or work network, the network may be blocking outgoing email connections (port 587). Try using a personal hotspot or home internet.

---

**"Daily sending limit reached"**

What happened: Gmail has a daily limit of roughly 500 emails per day for regular accounts.

What to do:
- Wait 24 hours and try again
- If you regularly send more than 500 emails per day, consider Google Workspace (paid)

---

### Image hosting errors

**"Freeimage.host key works!" / "Imghippo key works!"**

This is not an error — this is a success message. Your API key is correct.

---

**"Error: Bad request" or status code errors on image test**

What happened: The API key may be typed incorrectly.

What to do:
- Go back to freeimage.host (or imghippo.com), open the API page, and copy the key again carefully
- Make sure there are no spaces before or after the key when you paste it
- Click **Save Settings** after updating the key

---

**"Image skipped — add an image hosting key in Settings first"**

What happened: You tried to upload a product photo but have not added an image hosting API key yet.

What to do:
- Go to Settings → Image Hosting, follow the guide in section 4.3, and save your key

---

**"Image upload failed: ..."**

What happened: The image was uploaded but the hosting service returned an error.

What to do:
- Check that the image file is a standard JPEG, PNG, or WebP
- Try a smaller image (under 5 MB)
- Check your internet connection
- Try clicking the upload button again — sometimes it is a temporary server issue

---

### Database errors

**"Connected. Tables not created yet — click Setup Tables below."**

This is not a real error. It means your database connection works but the tables MERIT needs do not exist yet.

What to do: Click **Setup Tables** right below the test result.

---

**"relation 'inventory' does not exist"**

What happened: You are connected to the database but have not created the tables.

What to do: Go to Settings → Database Connections → Supabase (or Neon) → click **Setup Tables**.

---

**"Connection failed: could not connect to server"**

What happened: MERIT could not reach your Neon database.

What to do:
- Check that the connection string starts with `postgresql://` — NOT `https://`
- Make sure you copied the full string including the password and database name at the end
- Check your internet connection
- Log into your Neon dashboard and confirm the project is not paused (free tier projects pause after inactivity — click Resume)

---

**"Could not parse project ref from URL" (Supabase Setup Tables)**

What happened: The Project URL you entered does not look like a Supabase URL.

What to do:
- The URL should look exactly like `https://abcdefghijk.supabase.co`
- Make sure you copied it from **Project Settings → API → Project URL** in Supabase, not from the browser address bar while browsing Supabase

---

**"401 Unauthorized" (Supabase)**

What happened: The API key you entered is wrong or expired.

What to do:
- Go to Supabase → Project Settings → API and copy the service role key again
- Make sure you are copying the **service_role** key for writes, not just the anon key
- Click Save Settings after updating

---

**"Supabase skipped (pip install supabase)"**

What happened: The Python library for Supabase is not installed in this environment.

What to do:
- If you are on Streamlit Cloud, this should install automatically from `requirements.txt`. Trigger a reboot by going to your Streamlit dashboard and clicking **Reboot app**.
- If running locally, run `pip install supabase` in your terminal.

---

**"Run: pip install psycopg2-binary" (Neon Test Connection)**

What happened: The library needed to connect to Neon is not installed. (MERIT now installs it automatically when you click Test Connection, but if you see this it means the auto-install failed.)

What to do:
- If running locally, open your terminal and run: `pip install psycopg2-binary`
- Then click **Test Connection** again

---

### General app errors

**"No image hosting configured. Add an API key in Settings → Image Hosting."**

What happened: You tried to upload a product image but neither Freeimage.host nor Imghippo API keys have been saved yet.

What to do: Follow section 4.3 or 4.4 to add an image hosting key and click **Save Settings**.

---

**"Data disappears after the app restarts on Streamlit Cloud"**

This is expected behaviour — Streamlit Cloud resets its local storage every time the app restarts.

What to do: Connect Supabase (section 4.5). Once connected, all your products and inventory are stored in the cloud and survive any number of restarts.

---

**"App shows MERIT instead of our firm name"**

What to do: Go to Settings → Sender Identity → fill in **From Name** with your firm's name → click **Save Settings**. The browser tab title and sidebar header update on the next page load.

---

**"Stock not going down after sending emails"**

What happened: The product names in your email queue do not match the names in your product catalog.

What to do:
- Go to Products and note the exact names in your catalog
- When adding orders to the email queue, spell product names the same way they appear in the catalog (partial matches work, but they need to overlap)
- A warning appears in the queue view if any product could not be matched

---

**"Negative stock / Backordered showing for a product"**

This is intentional. MERIT allows stock to go below zero to represent situations where you have confirmed more orders than you have stock for.

What to do: Go to Inventory → Adjust Stock → enter a positive number in the ± box to add stock back up to the correct level.

---

**"Synced 0 rows to cloud" after clicking Sync Local → Cloud**

What happened: Your local SQLite database had no rows to sync, or the cloud databases were still unreachable.

What to do:
- Make sure your internet connection is working
- Click Test Connection in the Supabase or Neon tab to confirm the cloud is reachable before syncing
- If the local database genuinely has no data (e.g. you just deployed fresh), this is normal — nothing to sync yet

---

## 11. Privacy & data — how your credentials are stored

When you first open MERIT you will see a one-time **Privacy Agreement** screen. Here is the full picture of what happens to your data.

### Where your credentials go

| Credential | Where it is stored |
|---|---|
| Gmail App Password | Streamlit Secrets (your own Streamlit project, encrypted) and/or `config.json` locally |
| Supabase connection string | Same as above |
| Image hosting API keys | Same as above |
| Product & inventory data | Your own Supabase database — you own and control it |
| Customer names & emails | Only in emails you send via Gmail. Logs stored in your own Supabase `outbound_logs` table |

### What MERIT does NOT do

- MERIT does **not** send your API keys, passwords, or credentials to any third party
- MERIT does **not** have a central backend server — there is no "MERIT cloud" that receives your data
- MERIT does **not** collect analytics, usage data, or telemetry of any kind
- The only outgoing network connections MERIT makes are:
  - **Gmail SMTP** (port 587) — to send the emails you initiate
  - **Supabase / Neon** — to read and write your own database
  - **Freeimage.host / Imghippo** — to upload product images you choose to upload

### Streamlit Secrets

When you paste the Secrets TOML into your Streamlit project settings, your credentials are stored in **Streamlit's encrypted secrets store** — tied to your Streamlit account, not shared with anyone. Streamlit is SOC 2 compliant. See [Streamlit's privacy policy](https://streamlit.io/privacy-policy) for details.

### config.json

This file is written to disk in the app container while it runs. It is listed in `.gitignore` and is never committed to GitHub. On Streamlit Cloud the container resets periodically, wiping this file — which is why Streamlit Secrets is the recommended way to persist credentials.

---

## 12. Frequently asked questions


**Do I need to know how to code?**

No. MERIT is designed for VEI students with no programming experience. All setup is done through the Settings page in the browser.

---

**Can multiple students in the firm use it at the same time?**

Yes, if you connect Supabase. Everyone accesses the same cloud database, so changes one person makes are visible to everyone within about 30 seconds.

---

**Can I use a school Gmail account (e.g. @school.edu)?**

Maybe. School accounts controlled by Google Workspace sometimes block App Passwords. If the App Passwords option does not appear in your account security settings, ask your school IT department. The safest choice is a personal Gmail account or a Gmail account created specifically for your VEI firm.

---

**What happens if I forget to click Save Settings?**

Settings are now **auto-saved** the moment you leave any field (tab out, click elsewhere, press Enter). You no longer need to click "Save & Sync to Cloud" for credentials to persist — that button only force-saves and triggers a cloud product sync.

---

**I clicked Test Key and it says success, but images are not appearing in emails.**

Two possible causes:
1. You tested the key but forgot to click **Save Settings** afterwards — the key was not actually saved.
2. The products in your catalog have `N/A` as their image URL — they were added before you had an image hosting key. Go to Products → Edit Product (or Bulk Edit → Replace product images) and re-upload images for those products.

---

**Can I use both Supabase and Neon at the same time?**

Yes. MERIT writes to every configured database simultaneously. Both will contain the same data. Reads prefer Supabase first, then Neon, then SQLite.

---

**The app is slow to load products or inventory.**

The first load after any restart hits the database directly. Subsequent loads within 30 seconds use an in-memory cache and are instant. If you are on a free Supabase or Neon tier, the database may take a second to "wake up" after a period of inactivity.

---

**I accidentally deleted a product — can I get it back?**

Not automatically. MERIT does not keep a recycle bin. If you have Supabase connected, you can log into your Supabase dashboard → Table Editor → find the row in the `inventory` or `products` table and restore it manually. This is another reason to use Supabase — it provides a visual table editor as a manual backup.

---

**Where are my credentials stored?**

All settings are saved in a file called `config.json` in the same folder as `app.py`. This file is listed in `.gitignore` — it is never uploaded to GitHub. On Streamlit Cloud, this file only exists while the app is running; it is wiped when the app restarts, which is why Supabase is recommended for data, and you should re-enter credentials after each cloud restart (or use Streamlit Secrets for production).

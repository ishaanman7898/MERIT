# MERIT

**Mass Email and Inventory Tool for VEI Firms**

MERIT is the productivity platform built for Virtual Enterprise International firms. Send personalized order confirmation emails to hundreds of customers in seconds, manage a professional product catalog, and track live inventory all from one dashboard. No coding required.

[Get Started](#getting-started) · [API Reference](#api-endpoints)


## What MERIT Does

**Bulk Email Sending** — Deliver personalized order confirmation emails to your entire customer list in one click.

**Inventory Sync** — Stock levels deduct automatically each time an order email goes out, so your numbers are always accurate.

**Image Hosting** — Built-in integration with FreeImage and Imghippo. Upload multiple images per product and MERIT handles the rest.

**Secure Access** — Protect your dashboard with individual user accounts and role-based access control.

**Cloud Storage** — Supabase integration keeps your data secure, synchronized, and accessible from any device.

**Excel Import** — Drop in a VEI Checkout Excel export and eliminate manual data entry entirely.


## Hardware Recommendations

MERIT runs on Streamlit, which can have performance issues on school issued Chromebooks. For the smoothest setup experience, use a personal laptop or a school provided VE laptop.


## Getting Started

> [!IMPORTANT]
> Use your official VEI Firm Email for all account registrations so that access carries over to future firm members.

### 1. Fork and Deploy to Streamlit Cloud

Start here. You need a running app before you can configure anything.

**Create your repository from this template**

1. Go to the MERIT GitHub repository page.
2. Click **Use this Template** in the top right corner.
3. Under Owner, select your firm's GitHub account.
4. Name the repository (e.g. MERIT Nova) and create it. It must be public.
5. You now have your own copy of MERIT.

**Deploy on Streamlit Cloud**

1. Go to [share.streamlit.io](https://share.streamlit.io) and sign in with the same GitHub account you used to fork.
2. Click **Create app**.
3. Under Repository, select your forked MERIT repository.
4. Set the Main file path to `app.py`.
5. Click **Deploy**. Streamlit will build and launch your app in about a minute.
6. Once live, you will receive a public URL (e.g. `https://yourname-merit-app-xxxxx.streamlit.app`). Share this with your firm.

> [!NOTE]
> Open your deployed app and go to Get Started, then complete every step inside the app. The steps below are quick reference summaries. If this is your first time setting up MERIT, follow the in-app guide — it walks you through everything with full detail and context.


### 2. Connect Your Database (Supabase)

Supabase is the central database for MERIT. It stores your products and inventory securely in the cloud.

1. Create a project at Supabase.com.
2. Copy your Connection String from the Connect button (found in the Session Pooler tab).
3. Paste the string into the MERIT Settings page under the Database section.


### 3. Enable Image Hosting

Product images must be hosted online to appear in emails and on your storefront.

1. Obtain a free API key from freeimage.host or imghippo.com.
2. Paste the key into MERIT Settings under Image Hosting.
3. MERIT will automatically upload and link photos when new products are added. Multiple images per product are supported and all images are stored.


### 4. Configure Gmail SMTP

MERIT sends emails through your firm's Gmail account. An App Password is required for secure authentication.

1. Open your Google Account Security settings.
2. Enable 2 Step Verification.
3. Search for App Passwords and create one named MERIT.
4. Copy the 16 character code and paste it into the MERIT Settings page under Email.


### 5. Set Up User Accounts

Protect your dashboard and give each firm member their own login.

1. In MERIT Settings, navigate to the Users section.
2. Add firm members by email and assign each a role.
3. Each member will receive an invite link to set their own password.


### 6. Save Your Settings

Streamlit Cloud restarts periodically and wipes saved files. To keep your settings permanent:

1. After completing the setup steps in the MERIT app, go to **Settings → Secrets TOML** and copy the generated block.
2. In Streamlit Cloud, open your app, click **Manage app** in the bottom right, then go to **Settings → Secrets**.
3. Paste the TOML block and click **Save**. Your credentials and configuration are now safe across restarts.


## API Endpoints

Connect your storefront website (Bolt.new, Lovable, Cursor, etc.) directly to your MERIT database for real time updates.

| Table | Purpose |
| :--- | :--- |
| inventory | Live stock levels and product details for your storefront catalog. |
| products | Clean catalog listing for external integration and display. |
| outbound_logs | Audit trail of sent emails including subtotal, tax, and shipping data. |

> [!TIP]
> Use the API Endpoints page inside the app to access pregenerated SQL and JavaScript code for fast integration.


## Privacy and Security

MERIT is built with data privacy as a core principle.

**Direct Connection** — Data travels directly from your application to Gmail and Supabase. Nothing passes through a third party.

**Full Ownership** — All credentials are stored exclusively in your Streamlit Secrets or local configuration files. We never see them.

**Open Source** — The full source code is available for review so your firm can verify exactly what MERIT does with your data.


## Frequently Asked Questions

**Do I need to know how to code?**
No coding is required. Setup involves copying and pasting configuration keys from one service into another. If you can follow instructions, you can set up MERIT.

**Can multiple people use MERIT at the same time?**
Yes. Once Supabase is connected, all firm members can manage inventory and send emails simultaneously using their own accounts.

**What if Streamlit is blocked at school?**
Some school networks block Streamlit. You may need to use a personal device to complete the initial setup. Once your Secrets TOML is saved, your firm can access the app from any browser on any network.

**Can I set up MERIT on my phone?**
Yes. The setup steps work fine from a phone or tablet browser. Open your Streamlit app URL, fill in your credentials, and copy the Secrets TOML before the session ends.


Built for VEI Firms worldwide.

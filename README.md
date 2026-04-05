# MERIT — Mass Email and Inventory Tool

MERIT is the definitive productivity tool for Virtual Enterprise International (VEI) firms. Automate order confirmations, manage a professional product catalog, and track live inventory from a single dashboard. No coding or complex spreadsheets required.

[Documentation](#getting-started) • [API Reference](#api-endpoints)

---

## Key Features

- **Bulk Emailing**: Send personalized confirmation emails to hundreds of customers in seconds.
- **Inventory Sync**: Stock levels deduct automatically when order emails are sent.
- **Image Hosting**: Built-in integration with FreeImage and Imghippo. Supports multiple images per product — all stored, first image used in emails.
- **Cloud Powered**: Supabase integration ensures your data is secure and synchronized.
- **Excel Import**: Support for VEI Checkout Excel exports to eliminate manual data entry.

---

## Getting Started

> [!IMPORTANT]
> Use your official VEI Firm Email for all account registrations to ensure access remains consistent for future firm members.

### 1. Fork and Deploy to Streamlit Cloud
Start here — you need a running app before you can configure anything.

#### Fork the repository
1. Go to the MERIT GitHub repository page.
2. Click **Fork** in the top-right corner.
3. Under "Owner", select your personal GitHub account (or your firm's organization).
4. Click **Create fork**. You now have your own copy of MERIT.

#### Deploy on Streamlit Cloud
1. Go to [share.streamlit.io](https://share.streamlit.io) and sign in with the same GitHub account you used to fork.
2. Click **Create app**.
3. Under "Repository", select your forked MERIT repository.
4. Set **Main file path** to `app.py`.
5. Click **Deploy**. Streamlit will build and launch your app in about a minute.
6. Once live, you will get a public URL (e.g. `https://yourname-merit-app-xxxxx.streamlit.app`). Share this with your firm.

---

### 2. Connect Your Database (Supabase)
Supabase acts as the central database for MERIT. It stores your products and inventory securely in the cloud.

1. Create a project at Supabase.com.
2. Copy your Connection String from the Connect button (found in the Session Pooler tab).
3. Paste the string into the MERIT Settings page under the Database section.

---

### 3. Enable Image Hosting
Product images must be hosted online to appear in emails and on your storefront.

1. Obtain a free API key from freeimage.host or imghippo.com.
2. Paste the key into MERIT Settings under Image Hosting.
3. MERIT will automatically upload and link photos whenever new products are added. Multiple images per product are supported — all images are stored and the first one is used in emails.

---

### 4. Configure Gmail SMTP
MERIT sends emails through your firm's Gmail account. An App Password is required for secure authentication.

1. Access your Google Account Security settings.
2. Enable 2-Step Verification.
3. Search for App Passwords and create one named MERIT.
4. Copy the 16-character code and paste it into the MERIT Settings page under Email.

---

### 5. Save Your Settings (Prevents Settings Loss on Restart)
Streamlit Cloud restarts your app periodically and wipes any saved files. To keep your settings:

1. After completing steps 2-4 in the MERIT app, go to **Settings → Secrets TOML** and copy the generated block.
2. In Streamlit Cloud, open your app → click **Manage app** (bottom-right) → **Settings** → **Secrets**.
3. Paste the TOML block and click **Save**. Your credentials are now safe across restarts.

---

## API Endpoints

Connect your storefront website (Bolt.new, Lovable, Cursor, etc.) directly to your MERIT database for real-time updates.

| Table | Purpose |
| :--- | :--- |
| inventory | Real-time stock levels and product details for your storefront catalog. |
| products | Clean catalog listing for external integration and display. |
| outbound_logs | Audit trail of sent emails including subtotal, tax, and shipping data. |

> [!TIP]
> Utilize the API Endpoints page within the application to access pre-generated SQL and JavaScript code for quick integration.

---

## Privacy and Security

MERIT is designed with data privacy as a core principle:
- **Direct Connection**: Data is transmitted directly from your application to Gmail and Supabase.
- **Ownership**: All credentials are stored exclusively in your Streamlit Secrets or local configuration files.
- **Auditability**: The source code is open for review to ensure data integrity.

---

## Frequently Asked Questions

**Q: Is coding knowledge required?**  
A: No coding is required. The setup involves standard copy and paste operations for configuration keys.

**Q: Can multiple users access the system?**  
A: Yes. Once Supabase is connected, all firm members can manage inventory and send emails simultaneously.

**Q: What if Streamlit is inaccessible at school?**  
A: Some school networks block Streamlit. You may need to use your personal laptop or even your phone to run the app and set it up — but once everything is configured and your Secrets TOML is saved, your firm can use the app from any browser and device. The one-time setup effort is worth it: MERIT saves hours of manual email and inventory work every week.

**Q: Can I run MERIT on my phone?**  
A: Yes. The setup steps work fine from a phone or tablet browser. Just open your Streamlit app URL, fill in your credentials, and copy the Secrets TOML before the session ends.

---

Built for VEI Firms worldwide.

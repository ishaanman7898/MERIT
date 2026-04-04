# 💎 MERIT — Mass Email & Inventory Tool

**MERIT** is the ultimate power-tool for **Virtual Enterprise International (VEI)** firms. Automate your order confirmations, manage a professional product catalog, and track live inventory—all from a single, beautiful dashboard. No coding, no spreadsheets, just results.

[🚀 Launch Streamlit App](https://ishaanman7898-merit-merit-app-bfhyad.streamlit.app) • [📖 Documentation](#-getting-started) • [🛠️ API Reference](#-api-endpoints)

---

## ✨ Key Features

- **📧 Bulk Emailing:** Send personalized confirmation emails to 100+ customers in seconds.
- **📦 Inventory Sync:** Stock levels deduct automatically when you send an order email.
- **🖼️ Image Hosting:** Built-in integration with FreeImage and Imghippo for product photos.
- **☁️ Cloud Powered:** Full Supabase and Neon integration to keep your data safe and synced.
- **📊 Excel Import:** Direct support for VEI Checkout Excel exports. No manual entry needed.

---

## 🏁 Getting Started

Setting up MERIT takes less than 5 minutes. Follow these four steps to get your firm online.

### 1️⃣ Connect Your Database (Supabase)
Supabase is the "brain" of MERIT. It stores your products and inventory in the cloud so they never disappear.

> [!IMPORTANT]
> Use your **VEI Firm Email** for all accounts to ensure continuity for next year's firm members!

**Step GIF Placeholder**


1. Create a project at [Supabase.com](https://supabase.com).
2. Copy your **Connection String** from the "Connect" button (use the **Session Pooler** tab).
3. Paste it into MERIT **Settings → Database**.

---

### 2️⃣ Enable Image Hosting
To show product photos in your emails and on your storefront website, you need a place to host them.

**Step GIF Placeholder**


1. Get a free API key from [freeimage.host](https://freeimage.host) or [imghippo.com](https://imghippo.com).
2. Paste the key into MERIT **Settings → Image Hosting**.
3. MERIT will now automatically upload and link photos when you add products.

---

### 3️⃣ Configure your Gmail Sender
MERIT sends emails through your firm's Gmail account. You need an **App Password** to make this secure.

**Step GIF Placeholder**


1. Go to your Google Account Security settings.
2. Enable **2-Step Verification**.
3. Search for **"App Passwords"** and create one named `MERIT`.
4. Copy the 16-character code and paste it into MERIT **Settings → Email**.

---

### 4️⃣ Deploy to Streamlit Cloud
Host your app on the web so your whole firm can use it.

**Step GIF Placeholder**


1. **Fork** this repository to your firm's GitHub account.
2. Sign in to [Streamlit Cloud](https://share.streamlit.io) with GitHub.
3. Click "Create App" and select your forked MERIT repo.
4. Click **Deploy**—your firm is now live!

---

## 🛠️ API Endpoints

Connect your storefront website (Bolt.new, Lovable, Cursor, etc.) directly to your MERIT database.

| Table | Purpose |
| :--- | :--- |
| `inventory` | Real-time stock levels and product details for your storefront. |
| `products` | Clean catalog listing for external integrations. |
| `outbound_logs` | Audit trail of every email sent (Subtotal, Tax, Shipping). |

> [!TIP]
> Use the **API Endpoints** page inside the app to get ready-made SQL and JavaScript code to connect your website in seconds.

---

## 🔒 Privacy & Security

MERIT is designed with privacy as the top priority:
- **No Middleman:** Data goes directly from your browser to Gmail/Supabase.
- **You Own the Keys:** All credentials are stored in *your* Streamlit Secrets or *your* local config.
- **Open Source:** Check the code yourself—we never see your data.

---

## ❓ FAQ

**Q: Do I need to be a coder?**  
A: Zero coding required. If you can copy-paste a password, you can set up MERIT.

**Q: Can multiple people use it?**  
A: Yes! Once Supabase is connected, everyone in your firm can manage inventory at the same time.

**Q: What if Streamlit is blocked at school?**  
A: We've got you covered. See the [Gradio Fallback Guide](https://github.com/ishaanman7898/MERIT#3b-deploy-the-gradio-fallback-app) in the full manual.

---

<p align="center">
  Built with ❤️ for VEI Firms everywhere.
</p>

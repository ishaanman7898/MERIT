```
 __  __ _____ ____  ___ _____
|  \/  | ____|  _ \|_ _|_   _|
| |\/| |  _| | |_) || |  | |
| |  | | |___|  _ < | |  | |
|_|  |_|_____|_| \_\___| |_|
```

# MERIT — Mass Email & Real-time Inventory Tracker

> Bulk email campaigns + real-time inventory tracking for VEI firms.

[![Streamlit](https://img.shields.io/badge/Streamlit-FF4B4B?style=flat&logo=streamlit&logoColor=white)](https://streamlit.io)
[![Supabase](https://img.shields.io/badge/Supabase-3ECF8E?style=flat&logo=supabase&logoColor=white)](https://supabase.com)
[![Python](https://img.shields.io/badge/Python-3776AB?style=flat&logo=python&logoColor=white)](https://python.org)
[![License: MIT](https://img.shields.io/badge/License-MIT-gold.svg)](LICENSE)

---

## Features

- **Dashboard** — Metric cards for total products, inventory value, emails sent, and stock alerts
- **Inventory Management** — Quick stock adjustments (stock left & bought), summary view, full editable table
- **PDF Invoice Parser** — Upload a PDF invoice and auto-update stock_bought with pdfplumber
- **Product Images** — Upload product images directly, auto-compressed and stored in Supabase Storage
- **Email Sender** — Order queue with data entry table, CSV import, regex product parser, SMTP sending
- **Branded Emails** — 100% inline-CSS HTML templates with firm logo, itemized order table, product image attachments
- **Dual Image Attachments** — Supports primary + secondary product images per SKU
- **Product Merger** — Merge VE Store Manager Orders + Products CSV sheets into a consolidated report
- **First-Run Setup Wizard** — Streamlit form that writes all credentials to secrets.toml
- **GitHub Pages Setup Guide** — Interactive 6-step wizard deployed automatically on fork

## Quick Start

1. **Fork** this repository on GitHub
2. **GitHub Pages** will automatically deploy at `https://YOUR_USERNAME.github.io/merit/`
3. **Follow the setup guide** — create a Supabase project, paste the schema, deploy to Streamlit Cloud
4. **First run** — fill in credentials in the setup wizard, restart, and you're live

## Tech Stack

| Component | Technology |
|-----------|-----------|
| Frontend | Streamlit |
| Database | Supabase (PostgreSQL) |
| Email | Gmail SMTP with STARTTLS |
| PDF Parsing | pdfplumber |
| CI/CD | GitHub Actions → GitHub Pages |
| Language | Python 3.11+ |

## Project Structure

```
merit/
├── .github/workflows/setup.yml    # Auto-deploys setup wizard to GitHub Pages
├── docs/index.html                # Interactive setup guide (GitHub Pages)
├── app/
│   ├── main.py                    # App entry point with sidebar navigation
│   ├── setup_wizard.py            # First-run credential setup
│   ├── supabase_client.py         # Authenticated Supabase client
│   ├── dashboard.py               # Metric cards and charts
│   ├── inventory_management.py    # 4-tab inventory UI + PDF parser
│   ├── email_sender.py            # Order queue, CSV import, SMTP sending
│   ├── email_templates.py         # Inline-CSS HTML email templates
│   └── product_merger.py          # Shopify CSV merger
├── supabase/schema.sql            # Database schema (tables + views)
├── requirements.txt               # Pinned Python dependencies
└── README.md
```

## Screenshots

> _Coming soon — screenshots of dashboard, inventory management, email sender, and setup wizard._

## Local Development

```bash
# Clone your fork
git clone https://github.com/YOUR_USERNAME/merit.git
cd merit

# Install dependencies
pip install -r requirements.txt

# Create secrets file
mkdir -p .streamlit
# Fill in .streamlit/secrets.toml (the app will guide you on first run)

# Run
streamlit run app/main.py
```

## License

MIT

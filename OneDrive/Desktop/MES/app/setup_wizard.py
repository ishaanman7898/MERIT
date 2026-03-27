# setup_wizard.py
# First-run setup screen shown when secrets.toml is missing or incomplete.
# Collects Supabase, SMTP, and branding credentials, then writes them to disk.
# Also provides an initial product image upload flow.

import os
import io

import streamlit as st
import requests
from PIL import Image

from app.supabase_client import get_authed_supabase


def _preview_email_header(firm_name: str, logo_url: str, accent_color: str, gold_color: str):
    """Render a live preview of the branded email header."""
    logo_html = ""
    if logo_url:
        logo_html = (
            f'<img src="{logo_url}" alt="{firm_name}" '
            f'style="max-height:60px;margin-bottom:8px;" '
            f'onerror="this.style.display=\'none\'">'
        )

    st.markdown("#### Email Header Preview")
    st.markdown(
        f"""
        <div style="background-color:{accent_color};padding:24px;text-align:center;
                    border-radius:8px 8px 0 0;max-width:600px;margin:auto;">
            {logo_html}
            <div style="color:{gold_color};font-size:20px;font-weight:bold;">
                {firm_name or 'Your Firm Name'}
            </div>
        </div>
        <div style="background:#ffffff;padding:20px;max-width:600px;margin:auto;
                    border:1px solid #ddd;border-top:none;border-radius:0 0 8px 8px;">
            <p style="color:#333;">Hi <b>Customer</b>,</p>
            <p style="color:#555;">Thank you for your order! Here are the details...</p>
        </div>
        """,
        unsafe_allow_html=True,
    )


def show_setup_wizard():
    """Display the first-run setup form and write secrets.toml on submit."""
    st.set_page_config(page_title="MERIT — Setup", page_icon="⚙️", layout="centered")

    st.markdown("# ⚙️ MERIT — First-Run Setup")
    st.markdown(
        "Welcome! Fill in the fields below to configure your MERIT instance. "
        "All values are saved to `.streamlit/secrets.toml` and never leave your server."
    )
    st.divider()

    with st.form("setup_form"):
        st.markdown("### 1. Supabase Credentials")
        supabase_url = st.text_input(
            "Supabase Project URL",
            placeholder="https://xyzcompany.supabase.co",
        )
        supabase_key = st.text_input(
            "Supabase Anon Key",
            type="password",
            placeholder="eyJhbGciOiJIUzI1NiIs...",
        )

        st.markdown("### 2. Gmail SMTP Credentials")
        smtp_email = st.text_input(
            "Sender Email (Gmail)",
            placeholder="yourfirm@gmail.com",
        )
        smtp_password = st.text_input(
            "App Password",
            type="password",
            placeholder="xxxx xxxx xxxx xxxx",
            help="Generate at https://myaccount.google.com/apppasswords",
        )

        st.markdown("### 3. Branding")
        firm_name = st.text_input("Firm Name", placeholder="VE International")
        logo_url = st.text_input(
            "Logo URL (optional)",
            placeholder="https://example.com/logo.png",
            help="Used in email headers. Falls back to firm name text if broken.",
        )
        col1, col2 = st.columns(2)
        with col1:
            accent_color = st.color_picker("Primary / Navy Color", value="#1B2A4A")
        with col2:
            gold_color = st.color_picker("Accent / Gold Color", value="#C9A84C")

        submitted = st.form_submit_button("Save & Configure", type="primary", use_container_width=True)

    # Live preview outside the form so it updates on interaction
    _preview_email_header(firm_name, logo_url, accent_color, gold_color)

    if submitted:
        missing = []
        if not supabase_url:
            missing.append("Supabase URL")
        if not supabase_key:
            missing.append("Supabase Key")
        if not smtp_email:
            missing.append("SMTP Email")
        if not smtp_password:
            missing.append("SMTP Password")
        if not firm_name:
            missing.append("Firm Name")

        if missing:
            st.error(f"Missing required fields: {', '.join(missing)}")
            return

        # Validate logo URL if provided
        if logo_url:
            try:
                resp = requests.head(logo_url, timeout=5)
                if resp.status_code >= 400:
                    st.warning("Logo URL returned an error — emails will fall back to firm name text.")
            except Exception:
                st.warning("Could not reach logo URL — emails will fall back to firm name text.")

        secrets_content = (
            f'SUPABASE_URL = "{supabase_url}"\n'
            f'SUPABASE_KEY = "{supabase_key}"\n'
            f'SMTP_SENDER_EMAIL = "{smtp_email}"\n'
            f'SMTP_APP_PASSWORD = "{smtp_password}"\n'
            f'FIRM_NAME = "{firm_name}"\n'
            f'LOGO_URL = "{logo_url}"\n'
            f'ACCENT_COLOR = "{accent_color}"\n'
            f'GOLD_COLOR = "{gold_color}"\n'
        )

        secrets_dir = os.path.join(os.getcwd(), ".streamlit")
        os.makedirs(secrets_dir, exist_ok=True)
        secrets_path = os.path.join(secrets_dir, "secrets.toml")

        with open(secrets_path, "w", encoding="utf-8") as f:
            f.write(secrets_content)

        st.success("Configuration saved to `.streamlit/secrets.toml`!")
        st.balloons()
        st.divider()

        # Product image upload prompt
        st.markdown("### 4. Upload Product Images (optional)")
        st.markdown(
            "You can upload product images now. They'll be compressed and stored in "
            "Supabase Storage, then attached to order confirmation emails.\n\n"
            "**You can also do this later** from the **Product Images** page in the sidebar."
        )

        st.info(
            "**Before uploading images**, make sure:\n"
            "1. You've run `schema.sql` in your Supabase SQL Editor\n"
            "2. You've added your products to the `products` table\n"
            "3. Restart the app first, then go to **Product Images** in the sidebar"
        )

        st.divider()
        st.info("Please restart the Streamlit app for changes to take effect: **stop and re-run `streamlit run app/main.py`**")

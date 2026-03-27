# main.py
# Entry point for the MERIT Streamlit application.
# Checks for required secrets, shows the setup wizard if missing,
# and provides sidebar navigation to all modules.

import streamlit as st


def _secrets_present() -> bool:
    """Check that all required secrets are configured."""
    required = ["SUPABASE_URL", "SUPABASE_KEY", "SMTP_SENDER_EMAIL", "SMTP_APP_PASSWORD"]
    for key in required:
        if not st.secrets.get(key):
            return False
    return True


def main():
    if not _secrets_present():
        from app.setup_wizard import show_setup_wizard
        show_setup_wizard()
        return

    st.set_page_config(
        page_title="MERIT",
        page_icon="📦",
        layout="wide",
        initial_sidebar_state="expanded",
    )

    # Sidebar navigation
    firm_name = st.secrets.get("FIRM_NAME", "MERIT")
    st.sidebar.title(firm_name)
    st.sidebar.caption("Mass Email & Real-time Inventory Tracker")

    page = st.sidebar.radio(
        "Navigate",
        [
            "Dashboard",
            "Inventory Management",
            "Product Images",
            "Email Sender",
            "Product Merger",
            "Settings",
        ],
        label_visibility="collapsed",
    )

    if page == "Dashboard":
        from app.dashboard import show_dashboard
        show_dashboard()

    elif page == "Inventory Management":
        from app.inventory_management import show_inventory_management
        show_inventory_management()

    elif page == "Product Images":
        from app.image_manager import show_product_image_manager, show_bulk_image_upload
        show_product_image_manager()
        st.divider()
        show_bulk_image_upload()

    elif page == "Email Sender":
        from app.email_sender import show_email_sender
        show_email_sender()

    elif page == "Product Merger":
        from app.product_merger import show_product_merger
        show_product_merger()

    elif page == "Settings":
        _show_settings()


def _show_settings():
    """Settings page to update branding and re-run setup."""
    st.header("Settings")

    st.markdown("Current configuration is stored in `.streamlit/secrets.toml`.")

    st.subheader("Branding")
    current_firm = st.secrets.get("FIRM_NAME", "")
    current_logo = st.secrets.get("LOGO_URL", "")
    current_accent = st.secrets.get("ACCENT_COLOR", "#1B2A4A")
    current_gold = st.secrets.get("GOLD_COLOR", "#C9A84C")

    st.text_input("Firm Name", value=current_firm, disabled=True)
    st.text_input("Logo URL", value=current_logo, disabled=True)

    col1, col2 = st.columns(2)
    with col1:
        st.color_picker("Primary Color", value=current_accent, disabled=True)
    with col2:
        st.color_picker("Accent Color", value=current_gold, disabled=True)

    st.info(
        "To update settings, edit `.streamlit/secrets.toml` directly or "
        "delete it and restart the app to re-run the setup wizard."
    )

    st.divider()
    st.subheader("Connection Status")

    try:
        from app.supabase_client import get_authed_supabase
        sb = get_authed_supabase()
        sb.table("products").select("id").limit(1).execute()
        st.success("Supabase: Connected")
    except Exception as e:
        st.error(f"Supabase: Connection failed — {e}")

    import smtplib
    try:
        server = smtplib.SMTP("smtp.gmail.com", 587, timeout=10)
        server.starttls()
        server.login(st.secrets["SMTP_SENDER_EMAIL"], st.secrets["SMTP_APP_PASSWORD"])
        server.quit()
        st.success("Gmail SMTP: Connected")
    except Exception as e:
        st.error(f"Gmail SMTP: Connection failed — {e}")


if __name__ == "__main__":
    main()

# dashboard.py
# Dashboard page showing key metrics: total products, inventory value,
# emails sent, and low/out-of-stock count.

import streamlit as st
import pandas as pd
from app.supabase_client import get_authed_supabase


def show_dashboard():
    """Render the dashboard with metric cards."""
    st.header("Dashboard")

    sb = get_authed_supabase()

    # Load data
    products_resp = sb.table("products").select("id", count="exact").execute()
    total_products = products_resp.count if products_resp.count is not None else 0

    inv_resp = sb.table("inventory_summary").select("*").execute()
    inv_df = pd.DataFrame(inv_resp.data)

    orders_resp = sb.table("orders").select("id", count="exact").execute()
    total_emails = orders_resp.count if orders_resp.count is not None else 0

    # Calculate metrics
    total_value = 0.0
    low_stock_count = 0

    if not inv_df.empty:
        if "estimated_value" in inv_df.columns:
            total_value = pd.to_numeric(inv_df["estimated_value"], errors="coerce").fillna(0).sum()
        if "status" in inv_df.columns:
            low_stock_count = inv_df[
                inv_df["status"].isin(["Low stock", "Out of stock", "Backordered"])
            ].shape[0]

    # Display metrics
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Total Products", f"{total_products:,}")
    col2.metric("Inventory Value", f"${total_value:,.2f}")
    col3.metric("Emails Sent", f"{total_emails:,}")
    col4.metric("Low / Out of Stock", f"{low_stock_count:,}")

    # Quick inventory overview
    if not inv_df.empty:
        st.divider()
        st.subheader("Inventory Status Breakdown")

        if "status" in inv_df.columns:
            status_counts = inv_df["status"].value_counts()
            st.bar_chart(status_counts)

        st.subheader("Top Products by Value")
        if "estimated_value" in inv_df.columns and "name" in inv_df.columns:
            top = inv_df.nlargest(10, "estimated_value")[["name", "sku", "estimated_value"]]
            st.dataframe(top, use_container_width=True, hide_index=True)

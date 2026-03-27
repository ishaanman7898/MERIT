# email_sender.py
# Order-based email sending with SMTP, product image attachments,
# CSV importing, regex-based product parsing, and inventory subtraction.

import re
import os
import time
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.image import MIMEImage

import streamlit as st
import pandas as pd
import requests

from app.supabase_client import get_authed_supabase
from app.email_templates import generate_items_html, get_fulfillment_email_html


# ---------------------------------------------------------------------------
# Image helpers
# ---------------------------------------------------------------------------

def get_image_urls_from_supabase(sku: str, supabase) -> list[str]:
    """Query the products table for image_url and secondary_image_url.

    Returns a list of 1 or 2 valid URLs (skips None and 'N/A').
    Works with both external URLs and Supabase Storage public URLs.
    """
    resp = supabase.table("products").select("image_url, secondary_image_url").eq("sku", sku).execute()
    if not resp.data:
        return []
    row = resp.data[0]
    urls = []
    for key in ("image_url", "secondary_image_url"):
        val = row.get(key)
        if val and str(val).strip() not in ("", "N/A"):
            urls.append(str(val).strip())
    return urls


# In-memory cache for image downloads during a single send batch.
# Avoids re-downloading the same product image for every unit in a multi-qty order.
_image_cache: dict[str, bytes | None] = {}


def fetch_image_from_url(url: str) -> bytes | None:
    """Download image bytes from a URL with per-session caching. Returns None on failure."""
    if url in _image_cache:
        return _image_cache[url]
    try:
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        _image_cache[url] = resp.content
        return resp.content
    except Exception:
        _image_cache[url] = None
        return None


def clear_image_cache():
    """Clear the in-memory image download cache after a send batch."""
    _image_cache.clear()


# ---------------------------------------------------------------------------
# Product loading
# ---------------------------------------------------------------------------

@st.cache_data(ttl=600)
def load_products_from_supabase() -> pd.DataFrame:
    """Load master product list with images. Same normalization as load_master()."""
    sb = get_authed_supabase()
    resp = sb.table("products").select("*").execute()
    df = pd.DataFrame(resp.data)
    if df.empty:
        return df

    rename_map = {
        "category": "Category",
        "name": "Product name",
        "status": "Product Status",
        "sku": "SKU#",
        "price": "Final Price",
        "image_url": "image_url",
        "secondary_image_url": "secondary_image_url",
    }
    df = df.rename(columns=rename_map)

    if "Product name" in df.columns:
        df["Product name"] = df["Product name"].apply(
            lambda v: re.sub(r"(\S)x(\S)", r"\1 x \2", str(v)) if pd.notna(v) else v
        )

    if "Final Price" in df.columns:
        df["Final Price"] = (
            df["Final Price"]
            .astype(str)
            .str.replace("$", "", regex=False)
            .str.replace(",", "", regex=False)
        )
        df["Final Price"] = pd.to_numeric(df["Final Price"], errors="coerce").fillna(0.0)

    df = df.dropna(subset=["SKU#", "Product name"])
    df = df[df["SKU#"].astype(str).str.strip() != ""]
    df = df[df["Product name"].astype(str).str.strip() != ""]

    return df


# ---------------------------------------------------------------------------
# Inventory subtraction
# ---------------------------------------------------------------------------

def subtract_inventory_from_order_supabase(
    cart: dict[str, int],
    sku_to_name: dict[str, str],
) -> tuple[bool, str, list[dict]]:
    """Subtract ordered quantities from inventory.

    Args:
        cart: {sku: qty} dict
        sku_to_name: {sku: product_name} lookup

    Returns:
        (success, message, stock_info_list)
        stock_info_list entries: {Product, Before, Change, After}
    """
    sb = get_authed_supabase()
    inv_resp = sb.table("inventory").select("*").execute()
    inv_df = pd.DataFrame(inv_resp.data)
    stock_info = []

    if inv_df.empty:
        return False, "Inventory table is empty.", []

    for sku, qty in cart.items():
        name = sku_to_name.get(sku, sku)
        # Look up by SKU first
        match = inv_df[inv_df["sku"] == sku]
        # Fallback to item_name match
        if match.empty:
            match = inv_df[inv_df["item_name"].str.lower() == name.lower()]

        if match.empty:
            stock_info.append({"Product": name, "Before": "N/A", "Change": -qty, "After": "N/A (not found)"})
            continue

        row = match.iloc[0]
        before = int(row["stock_left"])
        after = before - qty

        from app.inventory_management import _inventory_status_from_stock_left
        new_status = _inventory_status_from_stock_left(after)

        sb.table("inventory").update({
            "stock_left": after,
            "status": new_status,
        }).eq("sku", row["sku"]).execute()

        stock_info.append({"Product": name, "Before": before, "Change": -qty, "After": after})

    st.cache_data.clear()
    return True, "Inventory updated successfully.", stock_info


# ---------------------------------------------------------------------------
# Product string parser
# ---------------------------------------------------------------------------

def parse_product_string(
    prods: str,
    name_to_sku: dict[str, str],
    master_df: pd.DataFrame,
) -> dict[str, int]:
    """Parse a freeform product string into a {sku: qty} cart.

    Handles qty suffixes: "x2", "×3", "* 2", " x 2".
    Sorts product names by length descending to avoid partial matches.
    Case-insensitive matching.
    """
    if not prods or not isinstance(prods, str):
        return {}

    cart: dict[str, int] = {}
    remaining = prods.strip()

    # Sort names longest-first to prevent partial matches
    sorted_names = sorted(name_to_sku.keys(), key=len, reverse=True)

    for name in sorted_names:
        sku = name_to_sku[name]
        escaped = re.escape(name)
        # Pattern: product name optionally followed by qty marker
        pattern = (
            rf"(?i){escaped}"
            r"(?:\s*[x×\*]\s*(\d+))?"
        )
        match = re.search(pattern, remaining)
        if match:
            qty = int(match.group(1)) if match.group(1) else 1
            cart[sku] = cart.get(sku, 0) + qty
            # Remove matched portion to avoid double-counting
            remaining = remaining[:match.start()] + remaining[match.end():]

    return cart


# ---------------------------------------------------------------------------
# CSV column auto-detect
# ---------------------------------------------------------------------------

def _auto_detect_csv_columns(df: pd.DataFrame) -> dict[str, str | None]:
    """Map CSV columns to expected fields by keyword matching.

    Returns {field_name: csv_column_name_or_None}.
    """
    mapping: dict[str, str | None] = {
        "email": None,
        "name": None,
        "order_number": None,
        "products": None,
        "total": None,
    }
    for col in df.columns:
        lower = col.lower()
        if "email" in lower and mapping["email"] is None:
            mapping["email"] = col
        elif ("name" in lower or "first" in lower) and mapping["name"] is None:
            mapping["name"] = col
        elif ("order" in lower and "#" in lower) or "transaction" in lower:
            if mapping["order_number"] is None:
                mapping["order_number"] = col
        elif "product" in lower and mapping["products"] is None:
            mapping["products"] = col
        elif "total" in lower and mapping["total"] is None:
            mapping["total"] = col
    return mapping


# ---------------------------------------------------------------------------
# Main UI
# ---------------------------------------------------------------------------

def show_email_sender():
    """Render the email sender interface with data entry, CSV import, queue, and send."""
    st.header("Email Sender")

    master = load_products_from_supabase()
    if master.empty:
        st.warning("No products found. Add products to Supabase first.")
        return

    name_to_sku = dict(zip(master["Product name"], master["SKU#"]))
    sku_to_name = dict(zip(master["SKU#"], master["Product name"]))
    sku_to_price = dict(zip(master["SKU#"], master["Final Price"]))

    # Initialize session state
    if "order_entry_data" not in st.session_state:
        st.session_state["order_entry_data"] = pd.DataFrame({
            "First Name": [""] * 10,
            "Email": [""] * 10,
            "Order #": [""] * 10,
            "Order Total": [""] * 10,
            "Products": [""] * 10,
        })
    if "orders" not in st.session_state:
        st.session_state["orders"] = []

    # ------------------------------------------------------------------
    # Data entry table
    # ------------------------------------------------------------------
    st.subheader("Order Entry")
    edited_df = st.data_editor(
        st.session_state["order_entry_data"],
        key="order_editor",
        use_container_width=True,
        num_rows="dynamic",
        hide_index=True,
    )

    # ------------------------------------------------------------------
    # CSV Importer
    # ------------------------------------------------------------------
    with st.expander("Import from CSV"):
        csv_file = st.file_uploader("Upload a CSV file", type=["csv"], key="csv_import")
        if csv_file is not None:
            if st.button("Apply CSV Data to Table"):
                try:
                    csv_df = pd.read_csv(csv_file)
                except Exception as e:
                    st.error(f"Failed to read CSV: {e}")
                    csv_df = None

                if csv_df is not None and not csv_df.empty:
                    col_map = _auto_detect_csv_columns(csv_df)
                    rows = []
                    for _, row in csv_df.iterrows():
                        # Name: take first word if full name column
                        raw_name = str(row.get(col_map["name"], "")) if col_map["name"] else ""
                        first_name = raw_name.split()[0] if raw_name.strip() else ""

                        rows.append({
                            "First Name": first_name,
                            "Email": str(row.get(col_map["email"], "")) if col_map["email"] else "",
                            "Order #": str(row.get(col_map["order_number"], "")) if col_map["order_number"] else "",
                            "Order Total": str(row.get(col_map["total"], "")) if col_map["total"] else "",
                            "Products": str(row.get(col_map["products"], "")) if col_map["products"] else "",
                        })

                    st.session_state["order_entry_data"] = pd.DataFrame(rows)
                    st.rerun()

    # ------------------------------------------------------------------
    # Controls
    # ------------------------------------------------------------------
    col_l, col_c, col_r = st.columns([1, 2, 1])
    with col_c:
        subtract_inventory = st.checkbox("Subtract from Inventory?", value=False)

    btn_cols = st.columns([1, 1])
    with btn_cols[0]:
        if st.button("Clear Table"):
            st.session_state["order_entry_data"] = pd.DataFrame({
                "First Name": [""] * 10,
                "Email": [""] * 10,
                "Order #": [""] * 10,
                "Order Total": [""] * 10,
                "Products": [""] * 10,
            })
            st.rerun()

    with btn_cols[1]:
        if st.button("Add All to Queue", type="primary"):
            added = 0
            for _, row in edited_df.iterrows():
                first_name = str(row.get("First Name", "")).strip()
                email = str(row.get("Email", "")).strip()
                if not first_name or not email:
                    continue

                products_str = str(row.get("Products", ""))
                cart = parse_product_string(products_str, name_to_sku, master)
                if not cart:
                    continue

                order_total = str(row.get("Order Total", "0"))
                order_number = str(row.get("Order #", ""))

                st.session_state["orders"].append({
                    "first_name": first_name,
                    "email": email,
                    "order_number": order_number,
                    "order_total": order_total,
                    "cart": cart,
                    "products_str": products_str,
                })
                added += 1

            if added:
                st.success(f"Added {added} order(s) to queue.")
            else:
                st.warning("No valid orders found. Each row needs a name, email, and at least one recognized product.")

    # ------------------------------------------------------------------
    # Order queue display
    # ------------------------------------------------------------------
    st.divider()
    orders = st.session_state["orders"]
    st.subheader(f"Queue — {len(orders)} order(s)")

    for idx in range(len(orders) - 1, -1, -1):
        order = orders[idx]
        items_str = ", ".join(
            f"{sku_to_name.get(sku, sku)} x{qty}" for sku, qty in order["cart"].items()
        )
        col_info, col_del = st.columns([5, 1])
        with col_info:
            st.markdown(
                f"**#{order['order_number']}** — {order['first_name']} — ${order['order_total']}"
            )
            st.caption(items_str)
        with col_del:
            if st.button("Delete", key=f"del_order_{idx}"):
                st.session_state["orders"].pop(idx)
                st.rerun()

    # ------------------------------------------------------------------
    # Send button
    # ------------------------------------------------------------------
    if orders:
        st.divider()
        if st.button("SEND ALL EMAILS", type="primary", use_container_width=True):
            sender_email = st.secrets["SMTP_SENDER_EMAIL"]
            sender_password = st.secrets["SMTP_APP_PASSWORD"]
            firm_name = st.secrets.get("FIRM_NAME", "MERIT")
            logo_url = st.secrets.get("LOGO_URL", "")
            sb = get_authed_supabase()

            all_stock_info: list[dict] = []
            progress = st.progress(0, text="Sending emails...")

            try:
                server = smtplib.SMTP("smtp.gmail.com", 587)
                server.starttls()
                server.login(sender_email, sender_password)
            except Exception as e:
                st.error(f"SMTP connection failed: {e}")
                return

            total = len(orders)
            for i, order in enumerate(orders):
                progress.progress((i + 1) / total, text=f"Sending {i + 1}/{total}...")

                # Build items list for the template
                items_list = []
                for sku, qty in order["cart"].items():
                    name = sku_to_name.get(sku, sku)
                    price = sku_to_price.get(sku, 0.0)
                    items_list.append({"name": name, "price": price, "qty": qty})

                items_html = generate_items_html(items_list)
                html_body = get_fulfillment_email_html(
                    first_name=order["first_name"],
                    order_number=order["order_number"],
                    items_rows_html=items_html,
                    order_total=order["order_total"],
                )

                # Build the email
                msg = MIMEMultipart("related")
                msg["From"] = f"{firm_name} <{sender_email}>"
                msg["To"] = order["email"]
                msg["Subject"] = f"Thank you for your order #{order['order_number']} \u2013 {firm_name}"

                msg.attach(MIMEText(html_body, "html"))

                # Attach product images
                for sku, qty in order["cart"].items():
                    product_name = sku_to_name.get(sku, sku)
                    image_urls = get_image_urls_from_supabase(sku, sb)

                    for unit_idx in range(qty):
                        for img_idx, url in enumerate(image_urls):
                            img_data = fetch_image_from_url(url)
                            if img_data:
                                if len(image_urls) > 1:
                                    filename = f"{product_name}_{img_idx + 1}.jpg"
                                else:
                                    filename = f"{product_name}.jpg"
                                img_part = MIMEImage(img_data, _subtype="jpeg")
                                img_part.add_header(
                                    "Content-Disposition", "attachment", filename=filename
                                )
                                msg.attach(img_part)

                # Attach logo
                logo_attached = False
                if logo_url:
                    logo_data = fetch_image_from_url(logo_url)
                    if logo_data:
                        logo_part = MIMEImage(logo_data, _subtype="png")
                        logo_part.add_header("Content-ID", "<logo>")
                        logo_part.add_header(
                            "Content-Disposition", "inline", filename="logo.png"
                        )
                        msg.attach(logo_part)
                        logo_attached = True

                if not logo_attached:
                    # Fallback: try local logo.png
                    local_logo = os.path.join(os.getcwd(), "logo.png")
                    if os.path.exists(local_logo):
                        with open(local_logo, "rb") as f:
                            logo_data = f.read()
                        logo_part = MIMEImage(logo_data, _subtype="png")
                        logo_part.add_header("Content-ID", "<logo>")
                        logo_part.add_header(
                            "Content-Disposition", "inline", filename="logo.png"
                        )
                        msg.attach(logo_part)

                # Subtract inventory if enabled
                if subtract_inventory:
                    success, message, stock_info = subtract_inventory_from_order_supabase(
                        order["cart"], sku_to_name
                    )
                    all_stock_info.extend(stock_info)

                # Log order to Supabase
                sb.table("orders").insert({
                    "recipient_name": order["first_name"],
                    "recipient_email": order["email"],
                    "order_number": order["order_number"],
                    "products_json": order["cart"],
                    "order_total": float(
                        str(order["order_total"]).replace("$", "").replace(",", "") or 0
                    ),
                    "status": "sent",
                }).execute()

                # Send
                try:
                    server.send_message(msg)
                except Exception as e:
                    st.error(f"Failed to send to {order['email']}: {e}")

                time.sleep(0.5)

            server.quit()
            clear_image_cache()
            st.session_state["orders"] = []
            progress.empty()
            st.success(f"All {total} email(s) sent successfully!")

            # Show inventory impact
            if all_stock_info:
                st.divider()
                st.subheader("Inventory Impact")
                impact_df = pd.DataFrame(all_stock_info)

                # Group by product
                if not impact_df.empty:
                    grouped = (
                        impact_df[impact_df["Before"] != "N/A"]
                        .groupby("Product")
                        .agg({"Before": "first", "Change": "sum", "After": "last"})
                        .reset_index()
                    )
                    st.dataframe(grouped, use_container_width=True, hide_index=True)

                    if "Change" in grouped.columns:
                        chart_data = grouped.set_index("Product")["Change"]
                        st.bar_chart(chart_data)

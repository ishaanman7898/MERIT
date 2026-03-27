# inventory_management.py
# Full inventory management module with 4-tab UI:
#   Tab 1: Quick Adjust (Stock Left)
#   Tab 2: Quick Adjust (Stock Bought)
#   Tab 3: Inventory Summary view
#   Tab 4: Full Inventory Table + PDF Invoice Parser

import re
import io
import streamlit as st
import pandas as pd
import pdfplumber
from app.supabase_client import get_authed_supabase


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

@st.cache_data(ttl=600)
def load_master() -> pd.DataFrame:
    """Load the master products table from Supabase.

    Renames columns to: Category, Product name, Product Status, SKU#, Final Price.
    Normalizes bundle names, cleans price fields, drops empty rows.
    """
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

    # Normalize product names — spaces around 'x' in bundle names
    if "Product name" in df.columns:
        df["Product name"] = df["Product name"].apply(
            lambda v: re.sub(r"(\S)x(\S)", r"\1 x \2", str(v)) if pd.notna(v) else v
        )

    # Clean price field
    if "Final Price" in df.columns:
        df["Final Price"] = (
            df["Final Price"]
            .astype(str)
            .str.replace("$", "", regex=False)
            .str.replace(",", "", regex=False)
        )
        df["Final Price"] = pd.to_numeric(df["Final Price"], errors="coerce").fillna(0.0)

    # Drop rows with empty SKU or name
    df = df.dropna(subset=["SKU#", "Product name"])
    df = df[df["SKU#"].astype(str).str.strip() != ""]
    df = df[df["Product name"].astype(str).str.strip() != ""]

    return df


@st.cache_data(ttl=600)
def load_inventory() -> pd.DataFrame:
    """Load raw inventory table from Supabase."""
    sb = get_authed_supabase()
    resp = sb.table("inventory").select("*").execute()
    return pd.DataFrame(resp.data)


@st.cache_data(ttl=600)
def load_inventory_summary() -> pd.DataFrame:
    """Load the inventory_summary view from Supabase."""
    sb = get_authed_supabase()
    resp = sb.table("inventory_summary").select("*").execute()
    return pd.DataFrame(resp.data)


# ---------------------------------------------------------------------------
# Status logic
# ---------------------------------------------------------------------------

def _inventory_status_from_stock_left(stock_left: int) -> str:
    if stock_left < 0:
        return "Backordered"
    if stock_left == 0:
        return "Out of stock"
    if stock_left <= 10:
        return "Low stock"
    return "In stock"


# ---------------------------------------------------------------------------
# Inventory update helpers
# ---------------------------------------------------------------------------

def update_inventory_delta(sku: str, delta: int):
    """Adjust stock_left by delta, recalculate status, and persist."""
    sb = get_authed_supabase()
    resp = sb.table("inventory").select("stock_left").eq("sku", sku).execute()
    if not resp.data:
        st.error(f"SKU {sku} not found in inventory.")
        return
    current = int(resp.data[0]["stock_left"])
    new_val = current + delta
    new_status = _inventory_status_from_stock_left(new_val)
    sb.table("inventory").update({
        "stock_left": new_val,
        "status": new_status,
    }).eq("sku", sku).execute()
    st.cache_data.clear()


def update_stock_bought_delta(sku: str, delta: int):
    """Adjust stock_bought by delta and persist."""
    sb = get_authed_supabase()
    resp = sb.table("inventory").select("stock_bought").eq("sku", sku).execute()
    if not resp.data:
        st.error(f"SKU {sku} not found in inventory.")
        return
    current = int(resp.data[0]["stock_bought"])
    new_val = max(0, current + delta)
    sb.table("inventory").update({
        "stock_bought": new_val,
    }).eq("sku", sku).execute()
    st.cache_data.clear()


# ---------------------------------------------------------------------------
# PDF Invoice Parser
# ---------------------------------------------------------------------------

def pdf_to_csv_converter(pdf_file) -> tuple[str | None, pd.DataFrame | None]:
    """Parse a VE Wholesale Marketplace invoice PDF into structured data.

    Returns (header_text, line_items_df) or (None, None) on failure.
    """
    try:
        with pdfplumber.open(pdf_file) as pdf:
            full_text = "\n".join(page.extract_text() or "" for page in pdf.pages)
    except Exception as e:
        st.error(f"Failed to read PDF: {e}")
        return None, None

    if not full_text.strip():
        st.error("PDF appears to be empty or image-based (no extractable text).")
        return None, None

    # Extract header metadata
    invoice_number = ""
    invoice_date = ""
    discount_date = ""
    due_date = ""
    invoice_total = ""
    order_placed_by = ""
    po_number = ""

    for line in full_text.split("\n"):
        line_clean = line.strip()
        if re.match(r"(?i)invoice\s*#?\s*:?\s*\d", line_clean):
            invoice_number = re.sub(r"(?i)invoice\s*#?\s*:?\s*", "", line_clean).strip()
        elif re.match(r"(?i)invoice\s+date", line_clean):
            invoice_date = re.sub(r"(?i)invoice\s+date\s*:?\s*", "", line_clean).strip()
        elif re.match(r"(?i)discount\s+date", line_clean):
            discount_date = re.sub(r"(?i)discount\s+date\s*:?\s*", "", line_clean).strip()
        elif re.match(r"(?i)due\s+date", line_clean):
            due_date = re.sub(r"(?i)due\s+date\s*:?\s*", "", line_clean).strip()
        elif re.match(r"(?i)(invoice\s+)?total", line_clean):
            match = re.search(r"[\$]?[\d,]+\.?\d*", line_clean)
            if match:
                invoice_total = match.group()
        elif re.match(r"(?i)order\s+placed\s+by", line_clean):
            order_placed_by = re.sub(r"(?i)order\s+placed\s+by\s*:?\s*", "", line_clean).strip()
        elif re.match(r"(?i)po\s*#?\s*:?\s*\w", line_clean):
            po_number = re.sub(r"(?i)po\s*#?\s*:?\s*", "", line_clean).strip()

    header_lines = [
        f"Invoice Number: {invoice_number}",
        f"Invoice Date: {invoice_date}",
        f"Discount Date: {discount_date}",
        f"Due Date: {due_date}",
        f"Invoice Total: {invoice_total}",
        f"Order Placed By: {order_placed_by}",
        f"PO Number: {po_number}",
    ]
    header_text = "\n".join(header_lines)

    # Extract line items — look for rows with SKU-like patterns
    items = []
    # Pattern: item name, SKU (alphanumeric), unit price ($X.XX), quantity (int), amount ($X.XX)
    line_pattern = re.compile(
        r"^(.+?)\s+"                          # Item name
        r"([A-Z0-9][\w-]{2,})\s+"             # SKU
        r"\$?([\d,]+\.?\d*)\s+"               # Unit price
        r"(\d+)\s+"                            # Quantity
        r"\$?([\d,]+\.?\d*)\s*$"              # Amount
    )

    for line in full_text.split("\n"):
        line_clean = line.strip()
        m = line_pattern.match(line_clean)
        if m:
            items.append({
                "Item": m.group(1).strip(),
                "SKU#": m.group(2).strip(),
                "Unit price": m.group(3).strip(),
                "Quantity": int(m.group(4)),
                "Amount": m.group(5).strip(),
            })

    # Fallback: try extracting tables with pdfplumber
    if not items:
        try:
            with pdfplumber.open(pdf_file) as pdf:
                for page in pdf.pages:
                    tables = page.extract_tables()
                    for table in tables:
                        for row in table:
                            if row and len(row) >= 5:
                                # Skip header rows
                                if any(
                                    h in str(row[0]).lower()
                                    for h in ["item", "product", "description"]
                                ):
                                    continue
                                try:
                                    qty = int(str(row[3]).strip())
                                    items.append({
                                        "Item": str(row[0]).strip(),
                                        "SKU#": str(row[1]).strip(),
                                        "Unit price": str(row[2]).strip(),
                                        "Quantity": qty,
                                        "Amount": str(row[4]).strip(),
                                    })
                                except (ValueError, IndexError):
                                    continue
        except Exception:
            pass

    if not items:
        st.warning("Could not extract line items from this PDF. The format may not match the expected invoice layout.")
        return header_text, pd.DataFrame()

    return header_text, pd.DataFrame(items)


# ---------------------------------------------------------------------------
# Main UI
# ---------------------------------------------------------------------------

def show_inventory_management():
    """Render the 4-tab inventory management interface."""
    st.header("Inventory Management")

    master = load_master()
    inventory = load_inventory()

    if master.empty:
        st.warning("No products found. Add products to your Supabase `products` table first.")
        return

    tab1, tab2, tab3, tab4 = st.tabs([
        "Quick Adjust (Stock Left)",
        "Quick Adjust (Stock Bought)",
        "Inventory Summary",
        "Full Inventory Table",
    ])

    # ------------------------------------------------------------------
    # Tab 1: Quick Adjust (Stock Left)
    # ------------------------------------------------------------------
    with tab1:
        st.subheader("Adjust Stock Left")
        search_q = st.text_input("Search by name or SKU", key="search_left")

        display_inv = inventory.copy()
        if search_q:
            mask = (
                display_inv["item_name"].str.contains(search_q, case=False, na=False)
                | display_inv["sku"].str.contains(search_q, case=False, na=False)
            )
            display_inv = display_inv[mask]

        if len(display_inv) > 60:
            st.warning("Showing first 60 items. Use the search bar to filter.")
            display_inv = display_inv.head(60)

        if display_inv.empty:
            st.info("No matching inventory items.")
        else:
            for _, row in display_inv.iterrows():
                sku = row["sku"]
                name = row.get("item_name", sku)
                current = int(row.get("stock_left", 0))

                cols = st.columns([4, 2, 1, 1, 1])
                cols[0].markdown(f"**{name}** `{sku}`")
                cols[1].markdown(f"Stock: **{current}**")

                amount_key = f"adj_left_{sku}"
                amount = cols[2].number_input(
                    "Amt", min_value=1, value=1, key=amount_key, label_visibility="collapsed"
                )
                if cols[3].button("➖", key=f"minus_left_{sku}"):
                    update_inventory_delta(sku, -amount)
                    st.rerun()
                if cols[4].button("➕", key=f"plus_left_{sku}"):
                    update_inventory_delta(sku, amount)
                    st.rerun()

    # ------------------------------------------------------------------
    # Tab 2: Quick Adjust (Stock Bought)
    # ------------------------------------------------------------------
    with tab2:
        st.subheader("Adjust Stock Bought")
        search_q2 = st.text_input("Search by name or SKU", key="search_bought")

        display_inv2 = inventory.copy()
        if search_q2:
            mask = (
                display_inv2["item_name"].str.contains(search_q2, case=False, na=False)
                | display_inv2["sku"].str.contains(search_q2, case=False, na=False)
            )
            display_inv2 = display_inv2[mask]

        if len(display_inv2) > 60:
            st.warning("Showing first 60 items. Use the search bar to filter.")
            display_inv2 = display_inv2.head(60)

        if display_inv2.empty:
            st.info("No matching inventory items.")
        else:
            for _, row in display_inv2.iterrows():
                sku = row["sku"]
                name = row.get("item_name", sku)
                current = int(row.get("stock_bought", 0))

                cols = st.columns([4, 2, 1, 1, 1])
                cols[0].markdown(f"**{name}** `{sku}`")
                cols[1].markdown(f"Bought: **{current}**")

                amount_key = f"adj_bought_{sku}"
                amount = cols[2].number_input(
                    "Amt", min_value=1, value=1, key=amount_key, label_visibility="collapsed"
                )
                if cols[3].button("➖", key=f"minus_bought_{sku}"):
                    update_stock_bought_delta(sku, -amount)
                    st.rerun()
                if cols[4].button("➕", key=f"plus_bought_{sku}"):
                    update_stock_bought_delta(sku, amount)
                    st.rerun()

    # ------------------------------------------------------------------
    # Tab 3: Inventory Summary
    # ------------------------------------------------------------------
    with tab3:
        st.subheader("Inventory Summary")
        summary = load_inventory_summary()
        if summary.empty:
            st.info("No inventory data available.")
        else:
            st.dataframe(summary, use_container_width=True, hide_index=True)
            total_value = summary["estimated_value"].sum() if "estimated_value" in summary.columns else 0
            st.metric("Total Estimated Inventory Value", f"${total_value:,.2f}")

    # ------------------------------------------------------------------
    # Tab 4: Full Inventory Table + PDF Invoice Parser
    # ------------------------------------------------------------------
    with tab4:
        st.subheader("Full Inventory Table")

        # Missing-image warning
        if not master.empty and "image_url" in master.columns:
            missing_imgs = master[
                (master["image_url"].isna())
                | (master["image_url"].astype(str).str.strip().isin(["", "N/A"]))
            ]
            if not missing_imgs.empty:
                with st.expander(f"⚠️ {len(missing_imgs)} product(s) missing images"):
                    for _, row in missing_imgs.iterrows():
                        st.write(f"- **{row.get('Product name', 'Unknown')}** (`{row.get('SKU#', 'N/A')}`)")

        # Editable inventory table
        if inventory.empty:
            st.info("No inventory records. Import from an invoice or add products to Supabase first.")
        else:
            disabled_cols = [c for c in ["id", "created_at", "updated_at"] if c in inventory.columns]
            edited_df = st.data_editor(
                inventory,
                key="inv_editor",
                use_container_width=True,
                hide_index=True,
                disabled=disabled_cols,
            )

            if st.button("Save Bulk Changes", type="primary"):
                sb = get_authed_supabase()
                save_count = 0
                for _, row in edited_df.iterrows():
                    record = row.to_dict()
                    # Recalculate status from stock_left
                    stock_left = int(record.get("stock_left", 0))
                    record["status"] = _inventory_status_from_stock_left(stock_left)
                    # Remove auto-generated fields
                    for key in ["id", "created_at", "updated_at"]:
                        record.pop(key, None)
                    sb.table("inventory").upsert(record, on_conflict="sku").execute()
                    save_count += 1
                st.cache_data.clear()
                st.success(f"Saved {save_count} inventory records.")
                st.rerun()

        # PDF Invoice Importer
        st.divider()
        st.subheader("Import from Invoice (PDF)")
        pdf_file = st.file_uploader("Upload a PDF invoice", type=["pdf"], key="pdf_invoice")

        if pdf_file is not None:
            header_text, items_df = pdf_to_csv_converter(pdf_file)

            if header_text:
                with st.expander("Invoice Header"):
                    st.text(header_text)

            if items_df is not None and not items_df.empty:
                st.dataframe(items_df, use_container_width=True, hide_index=True)

                # Download as CSV
                csv_buffer = io.StringIO()
                if header_text:
                    csv_buffer.write(header_text + "\n\n")
                items_df.to_csv(csv_buffer, index=False)
                st.download_button(
                    "Download as CSV",
                    csv_buffer.getvalue(),
                    file_name="parsed_invoice.csv",
                    mime="text/csv",
                )

                # Apply to inventory
                if st.button("Apply Invoice to Inventory (update stock_bought)", type="primary"):
                    sb = get_authed_supabase()
                    applied = 0
                    for _, item_row in items_df.iterrows():
                        sku = str(item_row.get("SKU#", "")).strip()
                        qty = int(item_row.get("Quantity", 0))
                        if not sku or qty <= 0:
                            continue
                        # Check if SKU exists
                        existing = sb.table("inventory").select("stock_bought").eq("sku", sku).execute()
                        if existing.data:
                            current_bought = int(existing.data[0]["stock_bought"])
                            sb.table("inventory").update({
                                "stock_bought": current_bought + qty,
                                "last_updated_from_invoice": header_text.split("\n")[0] if header_text else "",
                                "invoice_date": next(
                                    (l.split(":")[1].strip() for l in (header_text or "").split("\n") if "Invoice Date" in l),
                                    "",
                                ),
                                "due_date": next(
                                    (l.split(":")[1].strip() for l in (header_text or "").split("\n") if "Due Date" in l),
                                    "",
                                ),
                            }).eq("sku", sku).execute()
                            applied += 1
                        else:
                            st.warning(f"SKU `{sku}` not found in inventory — skipped.")
                    st.cache_data.clear()
                    if applied:
                        st.success(f"Updated stock_bought for {applied} item(s).")
                        st.rerun()

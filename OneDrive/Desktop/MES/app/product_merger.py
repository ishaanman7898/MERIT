# product_merger.py
# Merges VE Store Manager export sheets into a single consolidated order report.
# Sheet 1 (Orders) + Sheet 2 (Products sold) → merged output with aggregated products.

import streamlit as st
import pandas as pd


# ---------------------------------------------------------------------------
# Required columns from VE Store Manager exports
# ---------------------------------------------------------------------------

# Sheet 1 — Orders (the first sheet of the Excel downloaded from VE Store Manager)
ORDERS_REQUIRED = [
    "Transaction no",
    "Date",
    "Billing name",
    "Billing company",
    "Billing city",
    "Billing state/province",
    "Customer email",
    "Subtotal",
    "Discount",
    "Shipping",
    "Tax",
    "Total",
]

# Sheet 2 — Products sold per order (the second sheet of the same Excel)
PRODUCTS_REQUIRED = [
    "Transaction no",
    "Item name",
    "Quantity",
]


def _validate_columns(df: pd.DataFrame, required: list[str]) -> list[str]:
    """Return list of missing required columns."""
    return [col for col in required if col not in df.columns]


def show_product_merger():
    """Render the Product Merger interface with VE Store Manager instructions."""
    st.header("Product Merger")

    # ---------------------------------------------------------------------------
    # Instructions for downloading from VE Store Manager
    # ---------------------------------------------------------------------------
    with st.expander("How to get your CSV files from VE Store Manager", expanded=False):
        st.markdown("""
**Step 1:** Log in to your VE Store Manager and download your sales report.
This gives you an Excel file (`.xlsx`) with two sheets.

**Step 2:** Open the Excel file in **Google Drive** (upload it, then open with Google Sheets).

**Step 3:** Download each sheet as a separate CSV:
- **Sheet 1 (Orders)** → `File → Download → Comma Separated Values (.csv)`
  - Contains: Transaction no, Date, Billing name, Company, City, State, Email, Subtotal, Discount, Shipping, Tax, Total
- Switch to **Sheet 2 (Products)** → `File → Download → Comma Separated Values (.csv)`
  - Contains: Transaction no, Item name, Item number, Price, Quantity, Amount

**Step 4:** Upload both CSV files below.
        """)

    st.markdown("Upload the **Orders CSV** (Sheet 1) and the **Products CSV** (Sheet 2) from your VE Store Manager export.")

    col1, col2 = st.columns(2)
    with col1:
        orders_file = st.file_uploader(
            "Sheet 1 — Orders CSV",
            type=["csv"],
            key="merger_orders",
            help="The first sheet: Transaction no, Date, Billing name, etc.",
        )
    with col2:
        products_file = st.file_uploader(
            "Sheet 2 — Products CSV",
            type=["csv"],
            key="merger_products",
            help="The second sheet: Transaction no, Item name, Item number, Price, Quantity, Amount",
        )

    if orders_file is None or products_file is None:
        st.info("Upload both CSV files to proceed.")
        return

    try:
        orders_df = pd.read_csv(orders_file)
        products_df = pd.read_csv(products_file)
    except Exception as e:
        st.error(f"Failed to read CSV file(s): {e}")
        return

    # ---------------------------------------------------------------------------
    # Validate required columns
    # ---------------------------------------------------------------------------
    missing_orders = _validate_columns(orders_df, ORDERS_REQUIRED)
    missing_products = _validate_columns(products_df, PRODUCTS_REQUIRED)

    if missing_orders:
        st.error(
            f"**Orders CSV (Sheet 1)** is missing columns: {', '.join(missing_orders)}\n\n"
            "Expected columns from VE Store Manager Sheet 1: Transaction no, Date, "
            "Billing name, Billing company, Billing address, Billing city, "
            "Billing state/province, Billing zip/postcode, Billing country, "
            "Shipping name, Shipping company, Shipping address, Shipping city, "
            "Shipping state/province, Shipping zip/postcode, Shipping country, "
            "Customer email, Subtotal, Promotional code, Discount, Shipping, Tax, Total"
        )
        return
    if missing_products:
        st.error(
            f"**Products CSV (Sheet 2)** is missing columns: {', '.join(missing_products)}\n\n"
            "Expected columns from VE Store Manager Sheet 2: Transaction no, "
            "Item name, Item number, Price, Quantity, Amount"
        )
        return

    # ---------------------------------------------------------------------------
    # Aggregate products per transaction
    # Group by Transaction no, format each item as "Item Name xQty"
    # ---------------------------------------------------------------------------
    products_df["Quantity"] = pd.to_numeric(products_df["Quantity"], errors="coerce").fillna(1).astype(int)

    aggregated = (
        products_df
        .groupby("Transaction no")
        .apply(
            lambda g: ", ".join(
                f"{row['Item name']} x{row['Quantity']}" for _, row in g.iterrows()
            ),
            include_groups=False,
        )
        .reset_index()
        .rename(columns={0: "Product(s) Ordered & Quantity"})
    )

    # ---------------------------------------------------------------------------
    # Deduplicate orders by Transaction no (keep first occurrence)
    # ---------------------------------------------------------------------------
    orders_deduped = orders_df.drop_duplicates(subset=["Transaction no"], keep="first")

    # ---------------------------------------------------------------------------
    # Merge orders + aggregated products on Transaction no (left join)
    # ---------------------------------------------------------------------------
    merged = orders_deduped.merge(aggregated, on="Transaction no", how="left")

    # ---------------------------------------------------------------------------
    # Build output with exact columns
    # ---------------------------------------------------------------------------
    output = pd.DataFrame()
    output["Transaction No."] = merged["Transaction no"]
    output["Purchase Date"] = merged["Date"]
    output["Customer Name"] = merged["Billing name"]
    output["Company"] = merged["Billing company"]
    output["City"] = merged["Billing city"]
    output["State"] = merged["Billing state/province"]
    output["Customer E-Mail"] = merged["Customer email"]
    output["Product(s) Ordered & Quantity"] = merged["Product(s) Ordered & Quantity"].fillna("")
    output["Order Subtotal"] = merged["Subtotal"]
    output["Discount Applied"] = merged["Discount"]
    output["Shipping"] = merged["Shipping"]
    output["Tax"] = merged["Tax"]
    output["Order Total"] = merged["Total"]

    # ---------------------------------------------------------------------------
    # Display results
    # ---------------------------------------------------------------------------
    st.success(f"Merged **{len(output)}** order(s) successfully.")
    st.dataframe(output, use_container_width=True, hide_index=True)

    csv_data = output.to_csv(index=False)
    st.download_button(
        "Download merged_orders.csv",
        csv_data,
        file_name="merged_orders.csv",
        mime="text/csv",
        type="primary",
    )

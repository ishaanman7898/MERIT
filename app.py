"""
Mass Email Sender
Open-source · Gmail SMTP · ImgBB image hosting · Supabase / Neon database
"""

import base64
import csv
import io
import json
import re
import smtplib
import time
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

import pandas as pd
import streamlit as st
import sqlite3

_SQLITE_DB = Path(__file__).parent / "data.db"

def _get_sqlite_conn():
    conn = sqlite3.connect(str(_SQLITE_DB), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def _init_sqlite():
    conn = _get_sqlite_conn()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS products (
            sku       TEXT PRIMARY KEY,
            item_name TEXT NOT NULL,
            category  TEXT NOT NULL DEFAULT '',
            price     REAL NOT NULL DEFAULT 0.0,
            image_url TEXT NOT NULL DEFAULT 'N/A',
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS inventory (
            sku        TEXT PRIMARY KEY,
            item_name  TEXT NOT NULL,
            category   TEXT NOT NULL DEFAULT '',
            price      REAL NOT NULL DEFAULT 0.0,
            stock_left INTEGER NOT NULL DEFAULT 0,
            status     TEXT NOT NULL DEFAULT 'In stock',
            image_url  TEXT NOT NULL DEFAULT 'N/A',
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
    """)
    conn.commit()
    conn.close()

_init_sqlite()

# ─────────────────────────────────────────────
# Config persistence
# ─────────────────────────────────────────────

CONFIG_FILE = Path(__file__).parent / "config.json"

# Default SQL run when a user clicks "Setup Tables".
# Shown in an editable text area so users can add their own tables/indexes.
SETUP_SQL = """\
-- ── Inventory table (stock tracking) ─────────────────────────────────────
CREATE TABLE IF NOT EXISTS inventory (
    id         BIGSERIAL      PRIMARY KEY,
    sku        TEXT           NOT NULL,
    item_name  TEXT           NOT NULL,
    category   TEXT           NOT NULL DEFAULT '',
    price      NUMERIC(10,2)  NOT NULL DEFAULT 0.00,
    stock_left INTEGER        NOT NULL DEFAULT 0,
    status     TEXT           NOT NULL DEFAULT 'In stock',
    image_url  TEXT           NOT NULL DEFAULT 'N/A',
    created_at TIMESTAMPTZ    NOT NULL DEFAULT NOW(),
    CONSTRAINT inventory_sku_unique UNIQUE (sku)
);

-- ── Products table (catalog / storefront) ─────────────────────────────────
CREATE TABLE IF NOT EXISTS products (
    id          BIGSERIAL      PRIMARY KEY,
    sku         TEXT           NOT NULL,
    name        TEXT           NOT NULL,
    category    TEXT           NOT NULL DEFAULT '',
    price       NUMERIC(10,2)  NOT NULL DEFAULT 0.00,
    description TEXT           NOT NULL DEFAULT '',
    image_url   TEXT           NOT NULL DEFAULT 'N/A',
    active      BOOLEAN        NOT NULL DEFAULT TRUE,
    created_at  TIMESTAMPTZ    NOT NULL DEFAULT NOW(),
    CONSTRAINT products_sku_unique UNIQUE (sku)
);

-- Add your own tables below this line ──────────────────────────────────────
"""


def load_config() -> dict:
    try:
        if CONFIG_FILE.exists():
            return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}


def save_config(data: dict):
    CONFIG_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")


# ─────────────────────────────────────────────
# Image helpers
# ─────────────────────────────────────────────

def upload_to_imghippo(
    image_bytes: bytes, api_key: str, name: str = "product"
) -> str:
    """Compress image with Pillow then upload to Imghippo via multipart/form-data.
    Returns data.view_url (direct CDN link) on success."""
    import requests  # type: ignore

    # ── Compress with Pillow if available ──────────────────────────
    try:
        from PIL import Image  # type: ignore
        img = Image.open(io.BytesIO(image_bytes))
        if img.mode not in ("RGB", "L"):
            img = img.convert("RGB")
        if max(img.size) > 1200:
            img.thumbnail((1200, 1200), Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=82, optimize=True)
        upload_bytes = buf.getvalue()
        fname = f"{name}.jpg"
    except ImportError:
        upload_bytes = image_bytes
        fname = f"{name}.jpg"

    resp = requests.post(
        "https://api.imghippo.com/v1/upload",
        data={"api_key": api_key, "title": name},
        files={"file": (fname, io.BytesIO(upload_bytes), "image/jpeg")},
        timeout=30,
    )

    body = resp.json()
    if resp.status_code == 200 and body.get("success"):
        return body["data"]["view_url"]

    raise RuntimeError(body.get("message") or f"HTTP {resp.status_code}: {resp.text[:120]}")


# ─────────────────────────────────────────────
# Database helpers
# ─────────────────────────────────────────────

def _get_db_conn(cfg: dict):
    """Return a psycopg2 connection to Neon, or None."""
    try:
        import psycopg2  # type: ignore
        if cfg.get("neon_connection_string"):
            return psycopg2.connect(cfg["neon_connection_string"], connect_timeout=10)
    except Exception:
        pass
    return None


def _has_any_db(cfg: dict) -> bool:
    return True  # SQLite is always available; Neon/Supabase are optional extras


def save_product_to_db(product: dict, cfg: dict) -> tuple[bool, str]:
    """Upsert one product into ALL configured databases. Always saves to SQLite."""
    row = {
        "sku":        product["sku"],
        "item_name":  product["item_name"],
        "category":   product.get("category", ""),
        "price":      product.get("price", 0.0),
        "stock_left": 0,   # always start at 0 inventory
        "status":     "In stock",
        "image_url":  product.get("image_url", "N/A"),
    }
    results = []

    # ── SQLite (always) ────────────────────────────────────────────
    try:
        conn = _get_sqlite_conn()
        conn.execute("""
            INSERT INTO inventory (sku, item_name, category, price, stock_left, status, image_url)
            VALUES (:sku, :item_name, :category, :price, :stock_left, :status, :image_url)
            ON CONFLICT(sku) DO UPDATE SET
                item_name=excluded.item_name, category=excluded.category,
                price=excluded.price, image_url=excluded.image_url
        """, row)
        conn.execute("""
            INSERT INTO products (sku, item_name, category, price, image_url)
            VALUES (:sku, :item_name, :category, :price, :image_url)
            ON CONFLICT(sku) DO UPDATE SET
                item_name=excluded.item_name, category=excluded.category,
                price=excluded.price, image_url=excluded.image_url
        """, row)
        conn.commit()
        conn.close()
        results.append("SQLite")
    except Exception as exc:
        results.append(f"SQLite failed: {exc}")

    # ── Neon (psycopg2) ────────────────────────────────────────────
    conn_pg = _get_db_conn(cfg)
    if conn_pg is not None:
        try:
            with conn_pg:
                with conn_pg.cursor() as cur:
                    cur.execute("""
                        INSERT INTO inventory (sku,item_name,category,price,stock_left,status,image_url)
                        VALUES (%s,%s,%s,%s,%s,%s,%s)
                        ON CONFLICT(sku) DO UPDATE SET
                            item_name=EXCLUDED.item_name, category=EXCLUDED.category,
                            price=EXCLUDED.price, image_url=EXCLUDED.image_url
                    """, (row["sku"],row["item_name"],row["category"],row["price"],0,"In stock",row["image_url"]))
            conn_pg.close()
            results.append("Neon")
        except Exception as exc:
            results.append(f"Neon failed: {exc}")

    # ── Supabase ────────────────────────────────────────────────────
    sb_url = cfg.get("supabase_url","").strip()
    sb_key = (cfg.get("supabase_service_role_key") or cfg.get("supabase_key","")).strip()
    if sb_url and sb_key:
        try:
            from supabase import create_client  # type: ignore
            client = create_client(sb_url, sb_key)
            # Update existing record (preserves stock_left) or insert new one
            _detail = {
                "item_name": row["item_name"],
                "category":  row["category"],
                "price":     row["price"],
                "image_url": row["image_url"],
            }
            _res = client.table("inventory").update(_detail).eq("sku", row["sku"]).execute()
            if not getattr(_res, "data", None):
                # No existing row — insert fresh with stock = 0
                client.table("inventory").insert(row).execute()
            results.append("Supabase")
        except ImportError:
            results.append("Supabase skipped (pip install supabase)")
        except Exception as exc:
            results.append(f"Supabase failed: {exc}")

    ok = any("failed" not in r for r in results)
    return ok, " · ".join(results)


def load_products() -> list[dict]:
    """Return the locally-cached product list from config.json."""
    return st.session_state.cfg.get("products", [])


def load_inventory_from_sqlite() -> pd.DataFrame:
    """Load inventory table from SQLite."""
    try:
        conn = _get_sqlite_conn()
        df = pd.read_sql("SELECT * FROM inventory ORDER BY item_name", conn)
        conn.close()
        return df
    except Exception:
        return pd.DataFrame()

def adjust_inventory_sqlite(sku: str, delta: int, note: str = "") -> tuple[bool, str]:
    """Add or subtract stock in SQLite. delta can be negative."""
    try:
        conn = _get_sqlite_conn()
        row = conn.execute("SELECT stock_left FROM inventory WHERE sku=?", (sku,)).fetchone()
        if row is None:
            conn.close()
            return False, "SKU not found"
        new_stock = max(0, row["stock_left"] + delta)
        if new_stock < 0:
            status = "Backordered"
        elif new_stock == 0:
            status = "Out of stock"
        elif new_stock <= 10:
            status = "Low stock"
        else:
            status = "In stock"
        conn.execute("UPDATE inventory SET stock_left=?, status=? WHERE sku=?", (new_stock, status, sku))
        conn.commit()
        conn.close()
        return True, f"Stock → {new_stock} ({status})"
    except Exception as exc:
        return False, str(exc)

def adjust_inventory_neon(sku: str, delta: int, cfg: dict) -> tuple[bool, str]:
    conn = _get_db_conn(cfg)
    if conn is None:
        return False, "Neon not configured"
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute("SELECT stock_left FROM inventory WHERE sku=%s", (sku,))
                row = cur.fetchone()
                if row is None:
                    return False, "SKU not found in Neon"
                new_stock = max(0, row[0] + delta)
                status = "Out of stock" if new_stock == 0 else ("Low stock" if new_stock <= 10 else "In stock")
                cur.execute("UPDATE inventory SET stock_left=%s, status=%s WHERE sku=%s", (new_stock, status, sku))
        conn.close()
        return True, f"Neon stock → {new_stock}"
    except Exception as exc:
        return False, str(exc)

def adjust_inventory_supabase(sku: str, delta: int, cfg: dict) -> tuple[bool, str]:
    sb_url = cfg.get("supabase_url","").strip()
    sb_key = (cfg.get("supabase_service_role_key") or cfg.get("supabase_key","")).strip()
    if not (sb_url and sb_key):
        return False, "Supabase not configured"
    try:
        from supabase import create_client  # type: ignore
        client = create_client(sb_url, sb_key)
        res = client.table("inventory").select("stock_left").eq("sku", sku).execute()
        if not res.data:
            return False, "SKU not found in Supabase"
        current = res.data[0]["stock_left"] or 0
        new_stock = max(0, current + delta)
        status = "Out of stock" if new_stock == 0 else ("Low stock" if new_stock <= 10 else "In stock")
        client.table("inventory").update({"stock_left": new_stock, "status": status}).eq("sku", sku).execute()
        return True, f"Supabase stock → {new_stock}"
    except Exception as exc:
        return False, str(exc)


def delete_product_from_db(sku: str, cfg: dict) -> tuple[bool, str]:
    """Delete a product from ALL configured databases (SQLite, Neon, Supabase)."""
    results = []

    # ── SQLite (always) ──────────────────────────────────────────────
    try:
        conn = _get_sqlite_conn()
        conn.execute("DELETE FROM inventory WHERE sku=?", (sku,))
        conn.execute("DELETE FROM products WHERE sku=?", (sku,))
        conn.commit()
        conn.close()
        results.append("SQLite")
    except Exception as exc:
        results.append(f"SQLite failed: {exc}")

    # ── Neon ─────────────────────────────────────────────────────────
    conn_pg = _get_db_conn(cfg)
    if conn_pg is not None:
        try:
            with conn_pg:
                with conn_pg.cursor() as cur:
                    cur.execute("DELETE FROM inventory WHERE sku=%s", (sku,))
                    try:
                        cur.execute("DELETE FROM products WHERE sku=%s", (sku,))
                    except Exception:
                        pass
            conn_pg.close()
            results.append("Neon")
        except Exception as exc:
            results.append(f"Neon failed: {exc}")

    # ── Supabase ─────────────────────────────────────────────────────
    sb_url = cfg.get("supabase_url", "").strip()
    sb_key = (cfg.get("supabase_service_role_key") or cfg.get("supabase_key", "")).strip()
    if sb_url and sb_key:
        try:
            from supabase import create_client  # type: ignore
            client = create_client(sb_url, sb_key)
            client.table("inventory").delete().eq("sku", sku).execute()
            try:
                client.table("products").delete().eq("sku", sku).execute()
            except Exception:
                pass
            results.append("Supabase")
        except Exception as exc:
            results.append(f"Supabase failed: {exc}")

    ok = any("failed" not in r for r in results)
    return ok, " · ".join(results) if results else "No databases written"


def set_stock_all_dbs(sku: str, stock: int, cfg: dict) -> tuple[bool, str]:
    """Set stock to an absolute value across all configured databases."""
    status = "Out of stock" if stock == 0 else ("Low stock" if stock <= 10 else "In stock")
    results = []

    # SQLite
    try:
        conn = _get_sqlite_conn()
        conn.execute("UPDATE inventory SET stock_left=?, status=? WHERE sku=?", (stock, status, sku))
        conn.commit()
        conn.close()
        results.append("SQLite")
    except Exception as exc:
        results.append(f"SQLite failed: {exc}")

    # Neon
    conn_pg = _get_db_conn(cfg)
    if conn_pg is not None:
        try:
            with conn_pg:
                with conn_pg.cursor() as cur:
                    cur.execute(
                        "UPDATE inventory SET stock_left=%s, status=%s WHERE sku=%s",
                        (stock, status, sku),
                    )
            conn_pg.close()
            results.append("Neon")
        except Exception as exc:
            results.append(f"Neon failed: {exc}")

    # Supabase
    sb_url = cfg.get("supabase_url", "").strip()
    sb_key = (cfg.get("supabase_service_role_key") or cfg.get("supabase_key", "")).strip()
    if sb_url and sb_key:
        try:
            from supabase import create_client  # type: ignore
            client = create_client(sb_url, sb_key)
            client.table("inventory").update({"stock_left": stock, "status": status}).eq("sku", sku).execute()
            results.append("Supabase")
        except Exception as exc:
            results.append(f"Supabase failed: {exc}")

    ok = any("failed" not in r for r in results)
    return ok, " · ".join(results) if results else "No databases written"


def load_inventory_preferring_cloud(cfg: dict) -> pd.DataFrame:
    """Load inventory preferring Supabase > Neon > SQLite."""
    # ── Try Supabase ─────────────────────────────────────────────────
    sb_url = cfg.get("supabase_url", "").strip()
    sb_key = (cfg.get("supabase_service_role_key") or cfg.get("supabase_key", "")).strip()
    if sb_url and sb_key:
        try:
            from supabase import create_client  # type: ignore
            client = create_client(sb_url, sb_key)
            res = client.table("inventory").select("*").order("item_name").execute()
            if res.data:
                return pd.DataFrame(res.data)
        except Exception:
            pass

    # ── Try Neon ─────────────────────────────────────────────────────
    conn_pg = _get_db_conn(cfg)
    if conn_pg is not None:
        try:
            df = pd.read_sql("SELECT * FROM inventory ORDER BY item_name", conn_pg)
            conn_pg.close()
            if not df.empty:
                return df
        except Exception:
            pass

    # ── Fall back to SQLite ───────────────────────────────────────────
    return load_inventory_from_sqlite()


def load_products_for_catalog(cfg: dict) -> list[dict]:
    """Load product list preferring Supabase > Neon > SQLite > config.json."""
    # ── Try Supabase inventory ────────────────────────────────────────
    sb_url = cfg.get("supabase_url", "").strip()
    sb_key = (cfg.get("supabase_service_role_key") or cfg.get("supabase_key", "")).strip()
    if sb_url and sb_key:
        try:
            from supabase import create_client  # type: ignore
            client = create_client(sb_url, sb_key)
            res = client.table("inventory").select("*").order("item_name").execute()
            if res.data:
                return res.data
        except Exception:
            pass

    # ── Try Neon ─────────────────────────────────────────────────────
    conn_pg = _get_db_conn(cfg)
    if conn_pg is not None:
        try:
            df = pd.read_sql("SELECT * FROM inventory ORDER BY item_name", conn_pg)
            conn_pg.close()
            if not df.empty:
                return df.to_dict("records")
        except Exception:
            pass

    # ── Try SQLite ───────────────────────────────────────────────────
    df = load_inventory_from_sqlite()
    if not df.empty:
        return df.to_dict("records")

    # ── Fall back to config.json ──────────────────────────────────────
    return cfg.get("products", [])


# ─────────────────────────────────────────────
# Page setup
# ─────────────────────────────────────────────

st.set_page_config(page_title="Mass Email Sender", layout="wide")

if "cfg" not in st.session_state:
    st.session_state.cfg = load_config()

if "queue" not in st.session_state:
    st.session_state.queue = []

if "send_log" not in st.session_state:
    st.session_state.send_log = []

# ─────────────────────────────────────────────
# Sidebar navigation
# ─────────────────────────────────────────────

with st.sidebar:
    st.title("Mass Email Sender")
    page = st.radio(
        "page",
        ["Email Sender", "Products", "Inventory", "Settings"],
        label_visibility="collapsed",
    )
    st.divider()
    cfg = st.session_state.cfg
    if cfg.get("from_name"):
        st.caption(f"Sending as: {cfg['from_name']}")
    if cfg.get("smtp_email"):
        st.caption(f"From: {cfg['smtp_email']}")
    products_count = len(cfg.get("products", []))
    if products_count:
        st.caption(f"Products: {products_count}")

cfg = st.session_state.cfg

# ─────────────────────────────────────────────
# Shared helpers
# ─────────────────────────────────────────────

def split_products(raw: str) -> list[str]:
    if not raw or str(raw).strip() in ("", "nan", "None", "null"):
        return []
    text = str(raw).strip()
    for sep in ["|", ";", "\n"]:
        if sep in text:
            return [p.strip() for p in text.split(sep) if p.strip()]
    parts = [p.strip() for p in text.split(",") if p.strip()]
    return parts if len(parts) > 1 else [text]


def validate_email(e: str) -> bool:
    return bool(e and "@" in e and "." in e.split("@")[-1])


def add_to_queue(name: str, email: str, order_number: str, products: str) -> bool:
    if not name.strip():
        st.error("Name is required.")
        return False
    if not validate_email(email.strip()):
        st.error(f"Invalid email: '{email}'")
        return False
    st.session_state.queue.append({
        "name":         name.strip(),
        "email":        email.strip(),
        "order_number": order_number.strip() or "N/A",
        "products":     products.strip(),
    })
    return True


# ─────────────────────────────────────────────
# Email builder
# ─────────────────────────────────────────────

def _build_items_html(prods: list[str], products_lookup: dict[str, str] | None) -> str:
    """Build email-safe HTML rows for the items list.
    Uses product images (from ImgBB URLs) when available."""
    if not prods:
        prods = ["N/A"]
    rows = []
    for p in prods:
        img_url = None
        if products_lookup:
            img_url = products_lookup.get(p)
            if not img_url:
                p_lower = p.lower()
                for k, v in products_lookup.items():
                    if p_lower in k.lower() or k.lower() in p_lower:
                        img_url = v
                        break
        if img_url:
            rows.append(
                f'<tr><td style="padding:4px 0;">'
                f'<table cellpadding="0" cellspacing="0" style="background:#f9fafb;'
                f'border-radius:8px;margin-bottom:2px;width:100%;">'
                f'<tr>'
                f'<td style="width:76px;padding:8px;">'
                f'<img src="{img_url}" alt="" width="60" height="60" '
                f'style="width:60px;height:60px;object-fit:cover;'
                f'border-radius:6px;display:block;">'
                f'</td>'
                f'<td style="padding:8px 12px;font-size:14px;'
                f'color:#111;font-weight:500;">{p}</td>'
                f'</tr></table></td></tr>'
            )
        else:
            rows.append(
                f'<tr><td style="padding:3px 0;font-size:14px;color:#333;">• {p}</td></tr>'
            )
    return "".join(rows)


def build_html(
    order: dict,
    from_name: str,
    products_lookup: dict[str, str] | None = None,
) -> str:
    name      = order.get("name", "Customer")
    order_num = order.get("order_number", "N/A")
    prods     = split_products(order.get("products", ""))
    items     = _build_items_html(prods, products_lookup)
    return f"""<!DOCTYPE html>
<html>
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:0;background:#f5f5f5;font-family:Arial,Helvetica,sans-serif;">
  <table width="100%" cellpadding="0" cellspacing="0">
    <tr><td align="center" style="padding:32px 16px;">
      <table width="560" cellpadding="0" cellspacing="0"
             style="background:#fff;border-radius:10px;overflow:hidden;
                    box-shadow:0 2px 12px rgba(0,0,0,.08);max-width:100%;">
        <tr>
          <td style="background:#18181b;padding:28px 36px;">
            <p style="margin:0;font-size:20px;font-weight:700;color:#fff;">{from_name}</p>
          </td>
        </tr>
        <tr>
          <td style="padding:32px 36px;">
            <p style="margin:0 0 12px;font-size:16px;color:#111;">Hi {name},</p>
            <p style="margin:0 0 24px;font-size:14px;color:#555;line-height:1.6;">
              Thank you for your order. Here is a summary of what you ordered.
            </p>
            <table cellpadding="0" cellspacing="0"
                   style="background:#f4f4f5;border-radius:8px;margin-bottom:24px;">
              <tr>
                <td style="padding:14px 20px;">
                  <p style="margin:0 0 4px;font-size:11px;color:#888;
                             text-transform:uppercase;letter-spacing:.6px;font-weight:600;">
                    Order Number
                  </p>
                  <p style="margin:0;font-size:22px;font-weight:700;color:#18181b;">
                    #{order_num}
                  </p>
                </td>
              </tr>
            </table>
            <p style="margin:0 0 12px;font-size:11px;color:#888;
                       text-transform:uppercase;letter-spacing:.6px;font-weight:600;">
              Items Ordered
            </p>
            <table cellpadding="0" cellspacing="0" style="width:100%;margin-bottom:28px;">
              {items}
            </table>
            <p style="margin:0;font-size:13px;color:#888;line-height:1.6;">
              Questions? Just reply to this email and we will be happy to help.
            </p>
          </td>
        </tr>
        <tr>
          <td style="background:#fafafa;padding:16px 36px;border-top:1px solid #ebebeb;">
            <p style="margin:0;font-size:12px;color:#bbb;">Sent by {from_name}</p>
          </td>
        </tr>
      </table>
    </td></tr>
  </table>
</body>
</html>"""


def build_text(order: dict, from_name: str) -> str:
    name      = order.get("name", "Customer")
    order_num = order.get("order_number", "N/A")
    prods     = split_products(order.get("products", ""))
    lines     = "\n".join(f"  - {p}" for p in prods) if prods else "  - N/A"
    return (
        f"Hi {name},\n\n"
        f"Thank you for your order.\n\n"
        f"Order Number: #{order_num}\n\n"
        f"Items Ordered:\n{lines}\n\n"
        f"Questions? Reply to this email.\n\n"
        f"{from_name}"
    )


# ─────────────────────────────────────────────
# CSV parsing
# ─────────────────────────────────────────────

_ALIASES = {
    "name":         ["name", "full_name", "customer_name", "customer", "first_name"],
    "email":        ["email", "email_address", "e_mail", "mail"],
    "order_number": ["order_number", "order_no", "order_id", "order",
                     "orderid", "ordernumber", "transaction_no", "transaction"],
    "products":     ["products", "items", "product_list", "product",
                     "item", "description", "ordered_items"],
}


def _norm(h: str) -> str:
    return h.strip().lower().replace(" ", "_").replace("-", "_").replace("#", "").replace(".", "_")


def _map_headers(headers: list[str]) -> dict[str, str]:
    out = {}
    for raw in headers:
        n = _norm(raw)
        for canonical, aliases in _ALIASES.items():
            if n in aliases:
                out[raw] = canonical
                break
    return out


def parse_csv_text(text: str) -> tuple[list[dict], list[str]]:
    warns = []
    text = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    if not text:
        return [], ["Input is empty."]
    try:
        dialect = csv.Sniffer().sniff(text[:2048], delimiters=",\t|;")
        delim = dialect.delimiter
    except csv.Error:
        delim = ","
    reader  = csv.DictReader(io.StringIO(text), delimiter=delim)
    headers = reader.fieldnames or []
    if not headers:
        return [], ["No headers found. Make sure row 1 is a header row."]
    hmap = _map_headers(headers)
    if "email" not in hmap.values():
        return [], [f"No email column found. Detected headers: {headers}"]
    rows = []
    for i, row in enumerate(reader, start=2):
        mapped = {c: (row.get(r) or "").strip() for r, c in hmap.items()}
        email  = mapped.get("email", "")
        if not validate_email(email):
            warns.append(f"Row {i}: skipped — bad email '{email}'")
            continue
        rows.append({
            "name":         mapped.get("name", "Customer"),
            "email":        email,
            "order_number": mapped.get("order_number", "N/A"),
            "products":     mapped.get("products", ""),
        })
    if not rows:
        warns.append("No valid rows found.")
    return rows, warns


# ═════════════════════════════════════════════
# PRODUCTS PAGE
# ═════════════════════════════════════════════

if page == "Products":
    cfg = st.session_state.cfg
    st.title("Products")

    # ── Status banners ──────────────────────────
    if not cfg.get("imghippo_api_key"):
        st.warning(
            "No Imghippo API key set. Go to **Settings → Image Hosting** to add one. "
            "Get a free key at [imghippo.com](https://imghippo.com)."
        )
    _has_cloud_db = cfg.get("neon_connection_string") or (cfg.get("supabase_url") and (cfg.get("supabase_service_role_key") or cfg.get("supabase_key")))
    if not _has_cloud_db:
        st.info("Saving to **SQLite** (local). Connect Supabase or Neon in Settings for cloud backup.")

    products = load_products_for_catalog(cfg)

    tab_single, tab_bulk, tab_catalog = st.tabs(["Add Single", "Bulk Add", "Catalog"])

    # ══ SINGLE ADD ══════════════════════════════
    with tab_single:
        col_left, col_right = st.columns([3, 2])
        with col_left:
            p_sku      = st.text_input("SKU *",          placeholder="SKU-001",      key="p_sku")
            p_name     = st.text_input("Product Name *", placeholder="Blue T-Shirt", key="p_name")
            p_category = st.text_input("Category",       placeholder="Clothing",     key="p_category")
            p_price    = st.number_input("Price ($)", min_value=0.0, step=0.01, format="%.2f", key="p_price")
        with col_right:
            p_image = st.file_uploader(
                "Product Image",
                type=["jpg", "jpeg", "png", "webp"],
                key="p_image",
                help="Compressed and uploaded to Imghippo automatically.",
            )
            if p_image:
                st.image(p_image, use_container_width=True)

        _add_clicked = st.button("Add Product", type="primary", use_container_width=True, key="btn_add_product")

        if _add_clicked:
            if not p_sku.strip():
                st.error("SKU is required.")
            elif not p_name.strip():
                st.error("Product Name is required.")
            else:
                image_url = "N/A"
                if p_image:
                    if not cfg.get("imghippo_api_key"):
                        st.warning("Image skipped — add an Imghippo API key in Settings first.")
                    else:
                        with st.spinner("Uploading image to Imghippo..."):
                            try:
                                image_url = upload_to_imghippo(
                                    p_image.read(), cfg["imghippo_api_key"], name=p_name.strip()
                                )
                            except Exception as _img_err:
                                st.error(f"Image upload failed: {_img_err}")

                product = {
                    "sku":        p_sku.strip().upper(),
                    "item_name":  p_name.strip(),
                    "category":   p_category.strip() or "General",
                    "price":      round(float(p_price), 2),
                    "stock_left": 0,
                    "status":     "In stock",
                    "image_url":  image_url,
                }
                updated = [p for p in products if p["sku"] != product["sku"]]
                updated.append(product)
                cfg["products"] = updated
                save_config(cfg)
                st.session_state.cfg = cfg

                ok, saved_to = save_product_to_db(product, cfg)
                st.success(f"**{product['item_name']}** added · Saved to: {saved_to}")
                st.rerun()

    # ══ BULK ADD ════════════════════════════════
    with tab_bulk:
        st.caption("Fill in the table below — SKU and Product Name are required. Leave image blank; add images later via the Catalog tab.")
        _bulk_template = pd.DataFrame({
            "SKU":      [""] * 8,
            "Name":     [""] * 8,
            "Category": [""] * 8,
            "Price":    [0.0] * 8,
        })
        _bulk_edited = st.data_editor(
            _bulk_template,
            num_rows="dynamic",
            use_container_width=True,
            key="bulk_editor",
            column_config={
                "Price": st.column_config.NumberColumn("Price ($)", min_value=0.0, format="$%.2f"),
            },
        )
        _bc1, _bc2 = st.columns(2)
        with _bc1:
            _bulk_csv = st.file_uploader("Or import CSV (columns: SKU, Name, Category, Price)", type=["csv"], key="bulk_csv")
        with _bc2:
            st.markdown("<div style='margin-top:28px'></div>", unsafe_allow_html=True)
            if st.button("Add All to Products", type="primary", use_container_width=True, key="btn_bulk_add"):
                rows_to_add = _bulk_edited[
                    _bulk_edited["SKU"].astype(str).str.strip().ne("") &
                    _bulk_edited["Name"].astype(str).str.strip().ne("")
                ]
                if _bulk_csv:
                    _csv_df = pd.read_csv(_bulk_csv)
                    _csv_df.columns = _csv_df.columns.str.strip()
                    _col_map = {}
                    for _c in _csv_df.columns:
                        _cl = _c.lower()
                        if "sku" in _cl: _col_map[_c] = "SKU"
                        elif "name" in _cl or "product" in _cl: _col_map[_c] = "Name"
                        elif "cat" in _cl: _col_map[_c] = "Category"
                        elif "price" in _cl: _col_map[_c] = "Price"
                    _csv_df = _csv_df.rename(columns=_col_map)
                    for _need in ["SKU","Name"]:
                        if _need not in _csv_df.columns: _csv_df[_need] = ""
                    if "Category" not in _csv_df.columns: _csv_df["Category"] = "General"
                    if "Price" not in _csv_df.columns: _csv_df["Price"] = 0.0
                    rows_to_add = pd.concat([rows_to_add, _csv_df[["SKU","Name","Category","Price"]]], ignore_index=True)

                added = 0
                for _, _row in rows_to_add.iterrows():
                    _sku = str(_row["SKU"]).strip().upper()
                    _name = str(_row["Name"]).strip()
                    if not _sku or not _name: continue
                    try: _price = round(float(_row["Price"]), 2)
                    except: _price = 0.0
                    _product = {"sku": _sku, "item_name": _name, "category": str(_row.get("Category","General")).strip() or "General", "price": _price, "stock_left": 0, "status": "In stock", "image_url": "N/A"}
                    _existing = [p for p in st.session_state.cfg.get("products",[]) if p["sku"] != _sku]
                    _existing.append(_product)
                    st.session_state.cfg["products"] = _existing
                    save_product_to_db(_product, cfg)
                    added += 1
                save_config(st.session_state.cfg)
                st.success(f"Added {added} products.")
                st.rerun()

    # ══ CATALOG ═════════════════════════════════
    with tab_catalog:
        if not products:
            st.info("No products yet. Use Add Single or Bulk Add above.")
        else:
            # Sync button
            _has_cloud = _has_cloud_db
            if _has_cloud:
                if st.button("Sync All to Cloud Databases", use_container_width=True, key="btn_sync_all"):
                    _ok_n, _fail_n = 0, 0
                    for prod in products:
                        _ok, _ = save_product_to_db(prod, cfg)
                        if _ok: _ok_n += 1
                        else: _fail_n += 1
                    st.success(f"Synced {_ok_n} products." if not _fail_n else f"{_ok_n} synced, {_fail_n} failed.")

            st.caption(f"{len(products)} product{'s' if len(products) != 1 else ''}")
            for i, prod in enumerate(products):
                img_url = prod.get("image_url", "N/A")
                has_img = bool(img_url and img_url not in ("N/A", ""))
                col_img, col_info, col_del = st.columns([1, 6, 1])
                with col_img:
                    if has_img:
                        st.image(img_url, width=80)
                    else:
                        st.markdown("<div style='width:80px;height:80px;background:#f4f4f5;border-radius:8px;display:flex;align-items:center;justify-content:center;color:#bbb;font-size:11px;'>No image</div>", unsafe_allow_html=True)
                with col_info:
                    img_badge = "<span style='font-size:11px;background:#d1fae5;color:#065f46;padding:2px 8px;border-radius:12px;margin-left:6px;'>image</span>" if has_img else "<span style='font-size:11px;background:#fee2e2;color:#991b1b;padding:2px 8px;border-radius:12px;margin-left:6px;'>no image</span>"
                    st.markdown(f"**{prod['item_name']}** <code style='font-size:11px;background:#f4f4f5;padding:2px 8px;border-radius:12px;color:#555;'>{prod['sku']}</code>{img_badge}", unsafe_allow_html=True)
                    st.caption(f"{prod.get('category','General')}  ·  ${prod.get('price',0):.2f}  ·  Stock: {prod.get('stock_left',0)}")
                    # Image upload for existing product
                    _up = st.file_uploader("Replace image", type=["jpg","jpeg","png","webp"], key=f"reup_{prod['sku']}_{i}", label_visibility="collapsed")
                    if _up and cfg.get("imghippo_api_key"):
                        if st.button("Upload image", key=f"upbtn_{prod['sku']}_{i}"):
                            with st.spinner("Uploading..."):
                                try:
                                    _new_url = upload_to_imghippo(_up.read(), cfg["imghippo_api_key"], name=prod["item_name"])
                                    prod["image_url"] = _new_url
                                    # Sync new image URL to ALL databases
                                    save_product_to_db(prod, cfg)
                                    _cfg_prods = [dict(p) for p in cfg.get("products", [])]
                                    for _cp in _cfg_prods:
                                        if _cp.get("sku") == prod["sku"]:
                                            _cp["image_url"] = _new_url
                                    cfg["products"] = _cfg_prods
                                    save_config(cfg)
                                    st.session_state.cfg = cfg
                                    st.success("Image updated across all databases.")
                                    st.rerun()
                                except Exception as _e:
                                    st.error(f"Upload failed: {_e}")
                with col_del:
                    st.markdown("<div style='margin-top:16px;'></div>", unsafe_allow_html=True)
                    if st.button("Delete", key=f"del_prod_{i}", use_container_width=True):
                        _del_sku = prod["sku"]
                        # Remove from ALL databases
                        _, _del_msg = delete_product_from_db(_del_sku, cfg)
                        # Remove from config.json
                        cfg["products"] = [p for p in cfg.get("products", []) if p.get("sku") != _del_sku]
                        save_config(cfg)
                        st.session_state.cfg = cfg
                        st.toast(f"Deleted {_del_sku} from: {_del_msg}")
                        st.rerun()
                # ── Edit form (inline expander) ──────────────────
                with st.expander(f"Edit {prod.get('item_name', prod['sku'])}"):
                    with st.form(key=f"edit_prod_{prod['sku']}_{i}"):
                        _e_c1, _e_c2 = st.columns(2)
                        with _e_c1:
                            _e_name  = st.text_input("Product Name *", value=str(prod.get("item_name", "")))
                            _e_cat   = st.text_input("Category",       value=str(prod.get("category", "")))
                        with _e_c2:
                            _e_price = st.number_input("Price ($)", value=float(prod.get("price", 0.0)), min_value=0.0, step=0.01, format="%.2f")
                            _e_img   = st.text_input("Image URL",   value=str(prod.get("image_url", "N/A")))
                        if st.form_submit_button("Save Changes", type="primary"):
                            _upd = {
                                "sku":       prod["sku"],
                                "item_name": _e_name.strip() or prod.get("item_name", ""),
                                "category":  _e_cat.strip() or prod.get("category", "General"),
                                "price":     round(_e_price, 2),
                                "image_url": _e_img.strip() or "N/A",
                                "stock_left": prod.get("stock_left", 0),
                                "status":    prod.get("status", "In stock"),
                            }
                            _ok, _msg = save_product_to_db(_upd, cfg)
                            # Update config.json product list
                            _cfg_prods = cfg.get("products", [])
                            cfg["products"] = [_upd if p.get("sku") == _upd["sku"] else p for p in _cfg_prods]
                            if not any(p.get("sku") == _upd["sku"] for p in _cfg_prods):
                                cfg["products"].append(_upd)
                            save_config(cfg)
                            st.session_state.cfg = cfg
                            st.success(f"Updated across: {_msg}")
                            st.rerun()
                st.divider()


# ═════════════════════════════════════════════
# INVENTORY PAGE
# ═════════════════════════════════════════════

elif page == "Inventory":
    cfg = st.session_state.cfg
    st.title("Inventory")
    st.caption("All changes sync across every configured database simultaneously.")

    # Load from best available source: Supabase > Neon > SQLite
    inv_df = load_inventory_preferring_cloud(cfg)

    # ── DB source / sync badges ───────────────────────────────────────
    _sb_url = cfg.get("supabase_url", "").strip()
    _sb_key = (cfg.get("supabase_service_role_key") or cfg.get("supabase_key", "")).strip()
    _has_supabase = bool(_sb_url and _sb_key)
    _has_neon = bool(cfg.get("neon_connection_string"))

    _source_label = "Supabase" if _has_supabase else ("Neon" if _has_neon else "SQLite (local)")
    _sync_targets = ["SQLite"]
    if _has_neon:   _sync_targets.append("Neon")
    if _has_supabase: _sync_targets.append("Supabase")
    st.caption(f"Reading from: **{_source_label}** · Writing to: **{' + '.join(_sync_targets)}**")

    if inv_df.empty:
        st.info("No products in inventory yet. Add products on the **Products** page first.")
    else:
        inv_tab_adjust, inv_tab_edit, inv_tab_delete = st.tabs(["Adjust Stock", "Edit Product", "Delete Product"])

        # ══ ADJUST STOCK ════════════════════════════════
        with inv_tab_adjust:
            st.subheader("Bulk Adjust")
            st.caption("Enter a delta (+ adds stock, − removes stock) then click Apply.")

            display_cols = ["sku", "item_name", "category", "stock_left", "status"]
            show_cols = [c for c in display_cols if c in inv_df.columns]
            edit_df = inv_df[show_cols].copy()
            edit_df["delta"] = 0
            edited = st.data_editor(
                edit_df,
                column_config={
                    "sku":        st.column_config.TextColumn("SKU",           disabled=True),
                    "item_name":  st.column_config.TextColumn("Product",       disabled=True),
                    "category":   st.column_config.TextColumn("Category",      disabled=True),
                    "stock_left": st.column_config.NumberColumn("Stock",        disabled=True),
                    "status":     st.column_config.TextColumn("Status",        disabled=True),
                    "delta":      st.column_config.NumberColumn("Adjust By",   help="+10 adds, -5 removes"),
                },
                use_container_width=True,
                key="inv_editor",
            )

            if st.button("Apply Adjustments", type="primary", use_container_width=True):
                changes = edited[edited["delta"] != 0]
                if changes.empty:
                    st.warning("No changes — set a non-zero delta first.")
                else:
                    for _, _row in changes.iterrows():
                        _sku   = _row["sku"]
                        _delta = int(_row["delta"])
                        _msgs  = []
                        _, _m = adjust_inventory_sqlite(_sku, _delta)
                        _msgs.append(_m)
                        if _has_neon:
                            _, _m2 = adjust_inventory_neon(_sku, _delta, cfg)
                            _msgs.append(_m2)
                        if _has_supabase:
                            _, _m3 = adjust_inventory_supabase(_sku, _delta, cfg)
                            _msgs.append(_m3)
                        st.toast(f"{_row.get('item_name', _sku)}: {' · '.join(_msgs)}")
                    st.success(f"Applied {len(changes)} adjustment(s) across {' + '.join(_sync_targets)}.")
                    st.rerun()

            st.divider()
            st.subheader("Quick Adjust")
            _qa_options  = inv_df["sku"].tolist()
            _qa_name_map = dict(zip(inv_df["sku"], inv_df["item_name"])) if "item_name" in inv_df.columns else {}
            _qa_c1, _qa_c2, _qa_c3 = st.columns([3, 1, 1])
            with _qa_c1:
                _qa_sku = st.selectbox("Product", _qa_options,
                    format_func=lambda s: f"{_qa_name_map.get(s, s)} ({s})", key="qa_sku")
            with _qa_c2:
                _qa_delta = st.number_input("Adjust By", step=1, value=0, key="qa_delta")
            with _qa_c3:
                st.markdown("<div style='margin-top:28px'></div>", unsafe_allow_html=True)
                if st.button("Apply", type="primary", use_container_width=True, key="qa_apply"):
                    if _qa_delta == 0:
                        st.warning("Delta is 0 — nothing to do.")
                    else:
                        _, _qm = adjust_inventory_sqlite(_qa_sku, int(_qa_delta))
                        if _has_neon:     adjust_inventory_neon(_qa_sku, int(_qa_delta), cfg)
                        if _has_supabase: adjust_inventory_supabase(_qa_sku, int(_qa_delta), cfg)
                        st.success(f"{_qa_name_map.get(_qa_sku, _qa_sku)}: {_qm}")
                        st.rerun()

            st.divider()
            st.subheader("Current Inventory")
            st.dataframe(load_inventory_preferring_cloud(cfg), use_container_width=True)

        # ══ EDIT PRODUCT ════════════════════════════════
        with inv_tab_edit:
            st.subheader("Edit Product Details")
            st.caption("Changes are saved to all configured databases.")
            _edit_options  = inv_df["sku"].tolist()
            _edit_name_map = dict(zip(inv_df["sku"], inv_df["item_name"])) if "item_name" in inv_df.columns else {}
            _edit_sku_sel = st.selectbox(
                "Select product",
                _edit_options,
                format_func=lambda s: f"{_edit_name_map.get(s, s)} ({s})",
                key="edit_inv_sku",
            )
            if _edit_sku_sel:
                _edit_row = inv_df[inv_df["sku"] == _edit_sku_sel].iloc[0].to_dict()
                with st.form(key="edit_inv_form"):
                    _ec1, _ec2 = st.columns(2)
                    with _ec1:
                        _en = st.text_input("Product Name *", value=str(_edit_row.get("item_name", "")))
                        _ec = st.text_input("Category",       value=str(_edit_row.get("category", "")))
                    with _ec2:
                        _ep = st.number_input("Price ($)", value=float(_edit_row.get("price", 0.0)), min_value=0.0, step=0.01, format="%.2f")
                        _es = st.number_input("Set Stock To", value=int(_edit_row.get("stock_left", 0)), min_value=0, step=1,
                                              help="Sets stock to this exact value across all databases")
                    _ei = st.text_input("Image URL", value=str(_edit_row.get("image_url", "N/A")))
                    if st.form_submit_button("Save All Changes", type="primary"):
                        _upd_prod = {
                            "sku":        _edit_sku_sel,
                            "item_name":  _en.strip() or _edit_row.get("item_name", ""),
                            "category":   _ec.strip() or _edit_row.get("category", "General"),
                            "price":      round(_ep, 2),
                            "stock_left": _es,
                            "image_url":  _ei.strip() or "N/A",
                            "status":     "Out of stock" if _es == 0 else ("Low stock" if _es <= 10 else "In stock"),
                        }
                        # Sync name/category/price/image to all DBs
                        _ok, _msg = save_product_to_db(_upd_prod, cfg)
                        # Sync stock separately (save_product_to_db preserves existing stock on update)
                        set_stock_all_dbs(_edit_sku_sel, _es, cfg)
                        # Update config.json
                        _cfg_prods = cfg.get("products", [])
                        cfg["products"] = [_upd_prod if p.get("sku") == _edit_sku_sel else p for p in _cfg_prods]
                        if not any(p.get("sku") == _edit_sku_sel for p in _cfg_prods):
                            cfg["products"].append(_upd_prod)
                        save_config(cfg)
                        st.session_state.cfg = cfg
                        st.success(f"Updated across: {_msg}")
                        st.rerun()

        # ══ DELETE PRODUCT ══════════════════════════════
        with inv_tab_delete:
            st.subheader("Delete Product")
            st.caption("Permanently removes the product from ALL configured databases.")
            _del_options  = inv_df["sku"].tolist()
            _del_name_map = dict(zip(inv_df["sku"], inv_df["item_name"])) if "item_name" in inv_df.columns else {}
            _del_sku_sel = st.selectbox(
                "Select product to delete",
                _del_options,
                format_func=lambda s: f"{_del_name_map.get(s, s)} ({s})",
                key="del_inv_sku",
            )
            st.warning(f"This will permanently delete **{_del_name_map.get(_del_sku_sel, _del_sku_sel)}** from: {' + '.join(_sync_targets)}")
            _del_confirm = st.checkbox("I understand this cannot be undone", key="del_inv_confirm")
            if st.button("Delete Product", type="primary", key="del_inv_btn", disabled=not _del_confirm):
                _, _del_msg = delete_product_from_db(_del_sku_sel, cfg)
                cfg["products"] = [p for p in cfg.get("products", []) if p.get("sku") != _del_sku_sel]
                save_config(cfg)
                st.session_state.cfg = cfg
                st.success(f"Deleted from: {_del_msg}")
                st.rerun()


# ═════════════════════════════════════════════
# SETTINGS PAGE
# ═════════════════════════════════════════════

elif page == "Settings":
    st.title("Settings")
    st.caption("Settings are saved to config.json in the app folder and load automatically on every visit.")

    with st.expander("Getting Started — how to set everything up", expanded=False):
        st.markdown("""
### 1. Gmail SMTP (required for sending emails)
1. Go to [myaccount.google.com](https://myaccount.google.com) → **Security**
2. Enable **2-Step Verification** (required)
3. Search for **App passwords** → create one named `Email Sender`
4. Copy the 16-character password and paste it below under **Gmail SMTP**

---

### 2. Imghippo — free image hosting (required for product images in emails)
1. Go to [imghippo.com](https://imghippo.com) → **Sign Up** (free, no credit card, 500 MB storage)
2. Verify your email address
3. Go to **Settings → API Keys** → click **Generate API Key**
4. Copy the key and paste it below under **Image Hosting**

---

### 3. Supabase — cloud Postgres (optional, recommended)
1. Go to [supabase.com](https://supabase.com) → **Start your project** (free tier)
2. Create a new project → choose a region close to you → set a strong DB password
3. Once created, go to **Settings → API** in your project dashboard:
   - Copy **Project URL** → `https://xxxx.supabase.co`
   - Copy **Anon key** (starts with `eyJ…`)
   - Copy **Service role key** (starts with `eyJ…`) — keep this secret
4. For the **Personal Access Token** (needed for Setup Tables):
   - Go to [supabase.com/dashboard/account/tokens](https://supabase.com/dashboard/account/tokens)
   - Click **Generate new token** → copy it (starts with `sbp_…`)
5. Fill all four fields below and click **Save Settings**
6. Click **Setup Tables** — it will create the `inventory` and `products` tables automatically

---

### 4. Neon — serverless Postgres (optional, alternative to Supabase)
1. Go to [neon.tech](https://neon.tech) → **Sign Up** (free tier)
2. Create a new project
3. Go to **Dashboard → Connection Details**
4. Select **psql** from the dropdown → copy the connection string
   - It looks like: `postgresql://user:pass@ep-xxxx.us-east-2.aws.neon.tech/neondb?sslmode=require`
5. Paste it below under **Neon**
6. Click **Setup Tables** to create the schema

---

### SQLite (built-in — no setup needed)
Products and inventory are **always** saved to `data.db` in the app folder automatically. No account or keys required. Use Supabase/Neon if you want cloud backup or multi-device access.
        """)

    # ── Sender Identity ─────────────────────────
    st.subheader("Sender Identity")
    col1, col2 = st.columns(2)
    with col1:
        inp_from_name = st.text_input(
            "From Name",
            value=cfg.get("from_name", ""),
            placeholder="Acme Store",
            help="Displayed as the sender name in the recipient's inbox",
        )
    with col2:
        inp_subject = st.text_input(
            "Default Subject Line",
            value=cfg.get("subject", "Your Order Confirmation"),
            placeholder="Your Order Confirmation",
            help="Use {order_number} to insert the order number",
        )

    # ── Gmail SMTP ──────────────────────────────
    st.divider()
    st.subheader("Gmail SMTP")

    with st.expander("How to get a Gmail App Password", expanded=False):
        st.markdown("""
**You need a Gmail App Password — not your regular Gmail password.**

1. Open [myaccount.google.com](https://myaccount.google.com) and sign in.
2. Click **Security** in the left sidebar.
3. Under *How you sign in to Google*, confirm **2-Step Verification** is **On**.
4. Search for **App passwords** and click the result.
5. Under *App name*, type `Email Sender`, then click **Create**.
6. Copy the **16-character password** shown and paste it below.
        """)

    col3, col4 = st.columns(2)
    with col3:
        inp_smtp_email = st.text_input(
            "Gmail Address",
            value=cfg.get("smtp_email", ""),
            placeholder="yourname@gmail.com",
            help="The Gmail account emails will be sent from",
        )
    with col4:
        inp_smtp_pass = st.text_input(
            "App Password",
            value=cfg.get("smtp_password", ""),
            type="password",
            placeholder="xxxx xxxx xxxx xxxx",
            help="The 16-character app password from your Google account",
        )

    # ── Image Hosting (Imghippo) ─────────────────
    st.divider()
    st.subheader("Image Hosting")
    st.caption("Imghippo is a free image hosting service (500 MB free storage). Product images are uploaded here automatically.")

    with st.expander("How to get an Imghippo API key", expanded=False):
        st.markdown("""
1. Go to [imghippo.com](https://imghippo.com) and click **Sign Up** (free, no credit card)
2. Verify your email address
3. Go to **Settings → API Keys** in your dashboard
4. Click **Generate API Key** → copy it
5. Paste it in the field below and click **Save Settings**
        """)

    _ib_l, _ib_r = st.columns([3, 1])
    with _ib_l:
        inp_imgbb_key = st.text_input(
            "Imghippo API Key",
            value=cfg.get("imghippo_api_key", ""),
            type="password",
            placeholder="your_imghippo_api_key",
            help="imghippo.com → Settings → API Keys → Generate",
            key="inp_imgbb_key",
        )
    with _ib_r:
        st.markdown("<div style='margin-top:28px;'></div>", unsafe_allow_html=True)
        if st.button("Test Key", use_container_width=True, key="btn_test_imgbb", disabled=not inp_imgbb_key):
            try:
                import requests  # type: ignore
                _test_path = Path(__file__).parent / "TESTPRODUCT.png"
                if _test_path.exists():
                    _raw = _test_path.read_bytes()
                else:
                    # Minimal valid JPEG bytes as fallback
                    import base64 as _b64
                    _raw = _b64.b64decode("/9j/4AAQSkZJRgABAQEASABIAAD/2wBDAAgGBgcGBQgHBwcJCQgKDBQNDAsLDBkSEw8UHRofHh0aHBwgJC4nICIsIxwcKDcpLDAxNDQ0Hyc5PTgyPC4zNDL/2wBDAQkJCQwLDBgNDRgyIRwhMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjL/wAARCAABAAEDASIAAhEBAxEB/8QAFAABAAAAAAAAAAAAAAAAAAAACf/EABQQAQAAAAAAAAAAAAAAAAAAAAD/xAAUAQEAAAAAAAAAAAAAAAAAAAAA/8QAFBEBAAAAAAAAAAAAAAAAAAAAAP/aAAwDAQACEQMRAD8AJQAB/9k=")
                _resp = requests.post(
                    "https://api.imghippo.com/v1/upload",
                    data={"api_key": inp_imgbb_key.strip(), "title": "api_test"},
                    files={"file": ("test.jpg", io.BytesIO(_raw), "image/jpeg")},
                    timeout=20,
                )
                _body = _resp.json() if _resp.content else {}
                if _resp.status_code == 200 and _body.get("success"):
                    st.success("Imghippo key works!")
                elif _resp.status_code == 401:
                    st.error("Invalid API key — check for typos.")
                elif _resp.status_code == 429:
                    st.warning("Rate limited — wait a minute and try again.")
                else:
                    st.error(f"Error {_resp.status_code}: {_body.get('message', _resp.text[:150])}")
            except Exception as exc:
                st.error(f"Test failed: {exc}")

    # ── Database Connections ────────────────────
    st.divider()
    st.subheader("Database Connections")
    st.caption(
        "Connect Supabase or Neon to persist products and inventory. "
        "Click **Setup Tables** to create the schema automatically."
    )

    db_tab_sb, db_tab_neon = st.tabs(["Supabase", "Neon"])

    with db_tab_sb:
        inp_sb_url = st.text_input(
            "Project URL",
            value=cfg.get("supabase_url", ""),
            placeholder="https://xxxxxxxxxxxx.supabase.co",
            help="Supabase Dashboard → Settings → API → Project URL",
            key="inp_sb_url",
        )
        inp_sb_pat = st.text_input(
            "Personal Access Token",
            value=cfg.get("supabase_pat", ""),
            type="password",
            placeholder="sbp_xxxxxxxxxxxxxxxxxxxx",
            help="supabase.com/dashboard/account/tokens → Generate new token. Required to auto-run SQL via the Management API.",
            key="inp_sb_pat",
        )

        col_sb1, col_sb2 = st.columns(2)
        with col_sb1:
            inp_sb_anon = st.text_input(
                "Anon Key",
                value=cfg.get("supabase_key", ""),
                type="password",
                placeholder="eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
                help="Supabase Dashboard → Settings → API → Anon key (legacy JWT starting with eyJ…)",
                key="inp_sb_anon",
            )
        with col_sb2:
            inp_sb_publishable = st.text_input(
                "Publishable Key",
                value=cfg.get("supabase_publishable_key", ""),
                type="password",
                placeholder="sb_publishable_...",
                help="Supabase Dashboard → Settings → API → Publishable key (starts with sb_publishable_…)",
                key="inp_sb_publishable",
            )

        inp_sb_service = st.text_input(
            "Service Role Key",
            value=cfg.get("supabase_service_role_key", ""),
            type="password",
            placeholder="eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9... (role: service_role)",
            help="Supabase Dashboard → Settings → API → Service role key. Used by the backend for full read/write access (bypasses RLS). Keep this secret.",
            key="inp_sb_service",
        )

        # Use service_role key for testing if provided, otherwise anon
        _test_key = inp_sb_service.strip() or inp_sb_anon.strip()
        col_sb_test, col_sb_setup = st.columns(2)
        with col_sb_test:
            if st.button(
                "Test Connection",
                use_container_width=True,
                key="btn_test_sb",
                disabled=not (inp_sb_url and _test_key),
            ):
                try:
                    from supabase import create_client  # type: ignore
                    client = create_client(inp_sb_url.strip(), _test_key)
                    client.table("inventory").select("id").limit(1).execute()
                    st.success("Connected to Supabase successfully.")
                except ImportError:
                    st.error("Run: pip install supabase")
                except Exception as exc:
                    if "PGRST205" in str(exc) or "does not exist" in str(exc).lower() or "relation" in str(exc).lower():
                        st.success("Connected. Tables not created yet — click **Setup Tables** below.")
                    else:
                        st.error(f"Connection failed: {exc}")

        with col_sb_setup:
            if st.button(
                "Setup Tables",
                type="primary",
                use_container_width=True,
                key="btn_setup_sb",
                disabled=not (inp_sb_url and inp_sb_pat.strip()),
            ):
                import re as _re
                import requests as _req
                _project_ref = _re.search(r"https://([^.]+)\.supabase\.co", inp_sb_url.strip())
                if not _project_ref:
                    st.error("Could not parse project ref from URL.")
                else:
                    _ref = _project_ref.group(1)
                    # Split on semicolons, skip blank/comment-only chunks
                    _statements = [
                        s.strip() for s in SETUP_SQL.split(";")
                        if s.strip() and not all(l.startswith("--") for l in s.strip().splitlines() if l.strip())
                    ]
                    _ok, _fail = 0, []
                    for _stmt in _statements:
                        _r = _req.post(
                            f"https://api.supabase.com/v1/projects/{_ref}/database/query",
                            headers={
                                "Authorization": f"Bearer {inp_sb_pat.strip()}",
                                "Content-Type": "application/json",
                            },
                            json={"query": _stmt},
                            timeout=20,
                        )
                        if _r.status_code in (200, 201):
                            _ok += 1
                        else:
                            _fail.append(f"{_stmt[:60]}… → {_r.text[:120]}")
                    if not _fail:
                        st.success(f"Tables created successfully.")
                    else:
                        st.warning(f"{_ok} OK, {len(_fail)} failed:")
                        for _f in _fail:
                            st.caption(_f)

    with db_tab_neon:
        with st.expander("Where do I find the Neon connection string?", expanded=False):
            st.markdown("""
1. Open your **Neon Console** and select your project.
2. Click **Dashboard** (or **Connection Details**) in the left sidebar.
3. Under **Connection string**, make sure the dropdown says **psql** or **postgresql**.
4. Copy the string — it looks like:
   `postgresql://neondb_owner:[password]@ep-xxxx.us-east-2.aws.neon.tech/neondb?sslmode=require`

**Common mistake:** Do NOT paste the REST API URL (`https://ep-…apirest…`).
That is Neon's HTTP API — psycopg2 requires the `postgresql://` connection string.
            """)

        inp_neon = st.text_input(
            "PostgreSQL Connection String",
            value=cfg.get("neon_connection_string", ""),
            type="password",
            placeholder="postgresql://neondb_owner:[password]@ep-xxxx.us-east-2.aws.neon.tech/neondb?sslmode=require",
            help="Neon Console → Dashboard → Connection string (must start with postgresql:// or postgres://)",
            key="inp_neon",
        )

        # Warn immediately if they pasted the REST URL instead
        _neon_val = inp_neon.strip()
        if _neon_val.startswith("https://") or _neon_val.startswith("http://"):
            st.error(
                "That looks like the **REST API URL**, not the PostgreSQL connection string. "
                "Expand the guide above to find the correct `postgresql://` string."
            )

        _neon_is_valid_dsn = bool(
            _neon_val and (
                _neon_val.startswith("postgresql://") or _neon_val.startswith("postgres://")
            )
        )

        with st.expander("SQL that will be executed (editable)", expanded=False):
            neon_sql = st.text_area(
                "Schema SQL",
                value=SETUP_SQL,
                height=320,
                key="neon_sql_editor",
                help="Edit this SQL to add your own tables, indexes, or constraints before running.",
                label_visibility="collapsed",
            )
        st.caption("You can add your own CREATE TABLE statements before clicking Setup.")

        col_neon_test, col_neon_setup = st.columns(2)
        with col_neon_test:
            if st.button(
                "Test Connection",
                use_container_width=True,
                key="btn_test_neon",
                disabled=not _neon_is_valid_dsn,
            ):
                try:
                    import psycopg2  # type: ignore
                    with psycopg2.connect(_neon_val, connect_timeout=10) as conn:
                        pass
                    st.success("Connected to Neon successfully.")
                except ImportError:
                    st.error("Run: pip install psycopg2-binary")
                except Exception as exc:
                    st.error(f"Connection failed: {exc}")

        with col_neon_setup:
            if st.button(
                "Setup Tables",
                type="primary",
                use_container_width=True,
                key="btn_setup_neon",
                disabled=not _neon_is_valid_dsn,
            ):
                try:
                    import psycopg2  # type: ignore
                    _run_sql = st.session_state.get("neon_sql_editor", SETUP_SQL)
                    with psycopg2.connect(_neon_val, connect_timeout=10) as conn:
                        with conn.cursor() as cur:
                            cur.execute(_run_sql)
                        conn.commit()
                    st.success("Tables created successfully (or already exist).")
                except ImportError:
                    st.error("Run: pip install psycopg2-binary")
                except Exception as exc:
                    st.error(f"Setup failed: {exc}")

    # ── Save + Test SMTP ────────────────────────
    st.divider()
    save_col, test_col = st.columns([1, 1])

    with save_col:
        if st.button("Save Settings", type="primary", use_container_width=True):
            # Preserve products list when saving settings
            existing_products = cfg.get("products", [])
            new_cfg = {
                "from_name":                inp_from_name.strip(),
                "subject":                  inp_subject.strip(),
                "smtp_email":               inp_smtp_email.strip(),
                "smtp_password":            re.sub(r"\s+", "", inp_smtp_pass.strip()),
                "imghippo_api_key":         inp_imgbb_key.strip(),
                "supabase_url":             inp_sb_url.strip(),
                "supabase_pat":             inp_sb_pat.strip(),
                "supabase_key":             inp_sb_anon.strip(),
                "supabase_publishable_key": inp_sb_publishable.strip(),
                "supabase_service_role_key": inp_sb_service.strip(),
                "supabase_db_password":     cfg.get("supabase_db_password", ""),
                "neon_connection_string":   inp_neon.strip(),
                "products":                 existing_products,
            }
            save_config(new_cfg)
            st.session_state.cfg = new_cfg
            cfg = new_cfg
            st.success("Settings saved.")

    with test_col:
        can_test = bool(cfg.get("smtp_email") and cfg.get("smtp_password"))
        if st.button("Test SMTP Connection", use_container_width=True, disabled=not can_test):
            try:
                server = smtplib.SMTP("smtp.gmail.com", 587, timeout=10)
                server.starttls()
                server.login(cfg["smtp_email"], cfg["smtp_password"])
                server.quit()
                st.success("SMTP connection successful.")
            except Exception as exc:
                st.error(f"Connection failed: {exc}")


# ═════════════════════════════════════════════
# EMAIL SENDER PAGE
# ═════════════════════════════════════════════

elif page == "Email Sender":

    cfg = st.session_state.cfg
    missing_cfg = [k for k in ("from_name", "smtp_email", "smtp_password") if not cfg.get(k)]
    if missing_cfg:
        st.warning("Go to **Settings** and fill in your SMTP credentials before sending.")

    st.title("Email Sender")
    st.caption("Build a queue of orders and send personalised confirmation emails in bulk.")

    # ── Entry tabs ──────────────────────────────

    tab_single, tab_bulk, tab_csv = st.tabs(["Single Entry", "Bulk Entry", "CSV Import"])

    # ─ Single ───────────────────────────────────
    with tab_single:
        st.markdown("#### Add one order")
        c1, c2, c3 = st.columns(3)
        with c1:
            s_name  = st.text_input("Name",    key="s_name",  placeholder="Jane Smith")
            s_email = st.text_input("Email",   key="s_email", placeholder="jane@example.com")
        with c2:
            s_order = st.text_input("Order #", key="s_order", placeholder="ORD-1001")
        with c3:
            s_prods = st.text_area(
                "Products", key="s_prods", height=108,
                placeholder="Blue T-Shirt\nBlack Jeans\nRunning Shoes",
                help="One product per line, or separate with | or ;",
            )

        if st.button("Add to Queue", key="single_add", type="primary"):
            if add_to_queue(s_name, s_email, s_order, s_prods):
                st.success(f"Added {s_name} to the queue.")
                st.rerun()

    # ─ Bulk ─────────────────────────────────────
    with tab_bulk:
        st.markdown("#### Enter multiple orders")
        st.caption("Type directly in the table. Use the + icon to add rows. Separate multiple products with |")

        _BULK_BASE = pd.DataFrame({
            "Name":     pd.Series([], dtype=str),
            "Email":    pd.Series([], dtype=str),
            "Order #":  pd.Series([], dtype=str),
            "Products": pd.Series([], dtype=str),
        })

        edited = st.data_editor(
            _BULK_BASE,
            num_rows="dynamic",
            use_container_width=True,
            key="bulk_editor",
            column_config={
                "Name":     st.column_config.TextColumn(width="medium"),
                "Email":    st.column_config.TextColumn(width="large"),
                "Order #":  st.column_config.TextColumn(width="small"),
                "Products": st.column_config.TextColumn(
                    width="large",
                    help="Separate multiple products with |",
                ),
            },
        )

        col_add, col_clear = st.columns(2)
        with col_add:
            if st.button("Add All to Queue", type="primary", use_container_width=True, key="bulk_add"):
                added = 0
                for _, row in edited.iterrows():
                    nm = str(row.get("Name",     "")).strip()
                    em = str(row.get("Email",    "")).strip()
                    on = str(row.get("Order #",  "")).strip()
                    pr = str(row.get("Products", "")).strip()
                    if not nm or nm == "nan" or not em or em == "nan":
                        continue
                    if add_to_queue(nm, em, on, pr):
                        added += 1
                if added:
                    st.success(f"Added {added} order(s) to the queue.")
                    if "bulk_editor" in st.session_state:
                        del st.session_state["bulk_editor"]
                    st.rerun()
                else:
                    st.warning("No valid rows found. Make sure Name and Email are filled in.")

        with col_clear:
            if st.button("Clear Table", use_container_width=True, key="bulk_clear"):
                if "bulk_editor" in st.session_state:
                    del st.session_state["bulk_editor"]
                st.rerun()

    # ─ CSV ──────────────────────────────────────
    with tab_csv:
        st.markdown("#### Import from a CSV or TSV file")
        st.caption(
            "Required column: **email**. "
            "Optional: **name**, **order_number**, **products**. "
            "Column names are flexible — most variations are recognised automatically."
        )

        uploaded = st.file_uploader(
            "Choose a CSV or TSV file",
            type=["csv", "tsv", "txt"],
            key="csv_upload",
        )

        with st.expander("Or paste raw text instead"):
            pasted = st.text_area(
                "Paste CSV / TSV text",
                height=160,
                key="csv_paste",
                placeholder=(
                    "name,email,order_number,products\n"
                    "Jane Smith,jane@example.com,ORD-1001,Blue T-Shirt | Black Jeans\n"
                    "John Doe,john@example.com,ORD-1002,Running Shoes"
                ),
            )

        if st.button("Import", type="primary", key="csv_import"):
            raw = ""
            if uploaded:
                raw = uploaded.read().decode("utf-8", errors="replace")
            elif pasted and pasted.strip():
                raw = pasted.strip()
            else:
                st.warning("Upload a file or paste text first.")
                st.stop()

            rows, warns = parse_csv_text(raw)
            for w in warns:
                st.warning(w)
            if rows:
                st.session_state.queue.extend(rows)
                st.success(f"Imported {len(rows)} orders into the queue.")
                st.rerun()

    # ── Queue ───────────────────────────────────

    st.divider()
    queue = st.session_state.queue

    # Build product image lookup for the queue preview and email sending
    _products_lookup: dict[str, str] = {
        p["item_name"]: p["image_url"]
        for p in load_products()
        if p.get("image_url") and p["image_url"] not in ("N/A", "")
    }

    if not queue:
        st.info("Queue is empty. Add orders using the tabs above.")

    else:
        header_col, action_col = st.columns([6, 1])
        with header_col:
            st.subheader(f"Queue  —  {len(queue)} order{'s' if len(queue) != 1 else ''}")
        with action_col:
            if st.button("Clear All", key="clear_queue"):
                st.session_state.queue = []
                st.rerun()

        for i, order in enumerate(queue):
            prods    = split_products(order.get("products", ""))
            prod_str = "  |  ".join(prods) if prods else "—"
            row_l, row_r = st.columns([9, 1])
            with row_l:
                st.markdown(
                    f"**#{order['order_number']}**  —  {order['name']}  "
                    f"<span style='color:#888;font-size:13px;'>{order['email']}</span>  \n"
                    f"<small style='color:#aaa;'>{prod_str}</small>",
                    unsafe_allow_html=True,
                )
            with row_r:
                if st.button("Delete", key=f"del_{i}", use_container_width=True):
                    st.session_state.queue.pop(i)
                    st.rerun()

        # Show image match summary
        if _products_lookup:
            matched = set()
            for order in queue:
                for p in split_products(order.get("products", "")):
                    p_l = p.lower()
                    for k in _products_lookup:
                        if p_l in k.lower() or k.lower() in p_l:
                            matched.add(k)
                            break
            if matched:
                st.caption(f"Images found for: {', '.join(sorted(matched))}")

        st.divider()

        ready = not missing_cfg
        if not ready:
            st.warning("Complete your settings before sending.")

        if st.button(
            "Send All Emails",
            type="primary",
            use_container_width=True,
            disabled=not ready,
            key="send_all",
        ):
            total         = len(queue)
            subject_tmpl  = cfg.get("subject", "Your Order Confirmation")
            from_name     = cfg["from_name"]
            smtp_email    = cfg["smtp_email"]
            smtp_password = cfg["smtp_password"]

            prog   = st.progress(0, text="Connecting to Gmail...")
            log_ph = st.empty()
            results, sent_n, failed_n = [], 0, 0

            try:
                server = smtplib.SMTP("smtp.gmail.com", 587, timeout=15)
                server.starttls()
                server.login(smtp_email, smtp_password)
            except Exception as exc:
                st.error(f"Could not connect to Gmail SMTP: {exc}")
                st.stop()

            for idx, order in enumerate(queue):
                prog.progress(
                    idx / total,
                    text=f"Sending {idx + 1} of {total}  —  {order['email']}",
                )

                subject = subject_tmpl.replace("{order_number}", order.get("order_number", ""))

                msg = MIMEMultipart("alternative")
                msg["From"]    = f"{from_name} <{smtp_email}>"
                msg["To"]      = order["email"]
                msg["Subject"] = subject
                msg.attach(MIMEText(build_text(order, from_name), "plain"))
                # Pass image lookup so product images appear in the email
                msg.attach(MIMEText(build_html(order, from_name, _products_lookup), "html"))

                try:
                    server.send_message(msg)
                    status = "Sent"
                    sent_n += 1
                except Exception as exc:
                    status = f"Failed: {str(exc)[:80]}"
                    failed_n += 1

                results.append({
                    "#":       idx + 1,
                    "Name":    order["name"],
                    "Email":   order["email"],
                    "Order #": order["order_number"],
                    "Status":  status,
                })
                log_ph.dataframe(
                    pd.DataFrame(results),
                    use_container_width=True,
                    hide_index=True,
                )
                time.sleep(0.25)

            server.quit()
            prog.progress(1.0, text="Done")

            if failed_n == 0:
                st.success(f"All {sent_n} emails sent successfully.")
            else:
                st.warning(f"{sent_n} sent, {failed_n} failed. See the results table above.")

            st.session_state.send_log = results
            st.session_state.queue    = []
            time.sleep(1)
            st.rerun()

    # ── Last send log ────────────────────────────

    if st.session_state.send_log and not st.session_state.queue:
        st.divider()
        st.subheader("Last Send Results")
        st.dataframe(
            pd.DataFrame(st.session_state.send_log),
            use_container_width=True,
            hide_index=True,
        )
        if st.button("Clear Log", key="clear_log"):
            st.session_state.send_log = []
            st.rerun()

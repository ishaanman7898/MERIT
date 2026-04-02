"""
MERIT — Mass Email & Inventory Tool for Virtual Enterprise (VEI) firms
Gmail SMTP · Freeimage.host / Imghippo image hosting · Supabase / Neon database
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

# ─────────────────────────────────────────────
# Custom CSS for UI enhancements
# ─────────────────────────────────────────────

st.markdown("""
<style>
/* Make toasts stay visible longer / slower fade out */
[data-testid="stToast"] {
    animation: toast-fade-in 0.5s, toast-fade-out 0.5s 5.5s forwards !important;
    width: auto !important;
    max-width: 400px !important;
}
@keyframes toast-fade-in { from { opacity: 0; transform: translateY(20px); } to { opacity: 1; transform: translateY(0); } }
@keyframes toast-fade-out { from { opacity: 1; } to { opacity: 0; } }

/* Fix all buttons - avoid blue text/outlines */
.stButton > button {
    transition: all 0.2s ease !important;
    outline: none !important;
    box-shadow: none !important;
}

/* Primary buttons (Main actions) */
.stButton > button[kind="primary"] {
    background-color: #dc2626 !important; /* Red-600 */
    border-color: #dc2626 !important;
    color: #ffffff !important;
}
.stButton > button[kind="primary"]:hover {
    background-color: #ef4444 !important; /* Red-500 */
    border-color: #ef4444 !important;
    color: #ffffff !important;
    transform: translateY(-1.5px);
    box-shadow: 0 6px 15px rgba(220, 38, 38, 0.3) !important;
}
.stButton > button[kind="primary"]:focus:not(:active) {
    background-color: #dc2626 !important;
    border-color: #dc2626 !important;
    color: #ffffff !important;
    box-shadow: none !important;
}

/* Secondary / Default buttons */
.stButton > button[kind="secondary"] {
    border-color: #e4e4e7 !important;
    color: #3f3f46 !important;
}
.stButton > button[kind="secondary"]:hover {
    border-color: #dc2626 !important;
    color: #dc2626 !important;
    transform: translateY(-1.5px);
    box-shadow: 0 4px 12px rgba(0, 0, 0, 0.05) !important;
}
.stButton > button[kind="secondary"]:focus:not(:active) {
    border-color: #e4e4e7 !important;
    color: #3f3f46 !important;
    box-shadow: none !important;
}
.stButton > button:active {
    transform: translateY(0px) !important;
}
</style>
""", unsafe_allow_html=True)

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
        CREATE TABLE IF NOT EXISTS outbound_logs (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            recipient_name TEXT NOT NULL,
            recipient_email TEXT NOT NULL,
            order_number   TEXT NOT NULL,
            products_list  TEXT NOT NULL,
            subtotal       REAL NOT NULL DEFAULT 0.0,
            tax            REAL NOT NULL DEFAULT 0.0,
            shipping       REAL NOT NULL DEFAULT 0.0,
            total_cost     REAL NOT NULL DEFAULT 0.0,
            timestamp      TEXT NOT NULL DEFAULT (datetime('now'))
        );
    """)
    conn.commit()

    # Migration for existing outbound_logs (add subtotal, tax, shipping)
    try:
        cur = conn.cursor()
        cur.execute("PRAGMA table_info(outbound_logs)")
        cols = [r[1] for r in cur.fetchall()]
        if "subtotal" not in cols:
            conn.execute("ALTER TABLE outbound_logs ADD COLUMN subtotal REAL NOT NULL DEFAULT 0.0")
            conn.execute("ALTER TABLE outbound_logs ADD COLUMN tax REAL NOT NULL DEFAULT 0.0")
            conn.execute("ALTER TABLE outbound_logs ADD COLUMN shipping REAL NOT NULL DEFAULT 0.0")
            conn.commit()
    except Exception: pass

    conn.close()

_init_sqlite()


def _clear_data_caches():
    """Clear both the @st.cache_data function cache and the per-session state caches."""
    st.cache_data.clear()
    st.session_state.pop("_products_cache", None)
    st.session_state.pop("_inv_cache", None)


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

-- ── Outbound logs (email history) ─────────────────────────────────────────
CREATE TABLE IF NOT EXISTS outbound_logs (
    id              BIGSERIAL      PRIMARY KEY,
    recipient_name  TEXT           NOT NULL,
    recipient_email TEXT           NOT NULL,
    order_number    TEXT           NOT NULL,
    products_list   TEXT           NOT NULL,
    subtotal        NUMERIC(10,2)  NOT NULL DEFAULT 0.00,
    tax             NUMERIC(10,2)  NOT NULL DEFAULT 0.00,
    shipping        NUMERIC(10,2)  NOT NULL DEFAULT 0.00,
    total_cost      NUMERIC(10,2)  NOT NULL DEFAULT 0.00,
    created_at      TIMESTAMPTZ    NOT NULL DEFAULT NOW()
);

-- Migrations for existing users
DO $$ 
BEGIN 
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='outbound_logs' AND column_name='subtotal') THEN
    ALTER TABLE outbound_logs ADD COLUMN subtotal NUMERIC(10,2) NOT NULL DEFAULT 0.00;
    ALTER TABLE outbound_logs ADD COLUMN tax NUMERIC(10,2) NOT NULL DEFAULT 0.00;
    ALTER TABLE outbound_logs ADD COLUMN shipping NUMERIC(10,2) NOT NULL DEFAULT 0.00;
  END IF;
END $$;

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


def upload_to_freeimage(
    image_bytes: bytes, api_key: str, name: str = "product"
) -> str:
    """Compress image with Pillow then upload to Freeimage.host via multipart/form-data.
    Returns the direct display URL on success."""
    import requests  # type: ignore

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
        "https://freeimage.host/api/1/upload",
        data={"key": api_key, "action": "upload", "format": "json"},
        files={"source": (fname, io.BytesIO(upload_bytes), "image/jpeg")},
        timeout=30,
    )

    body = resp.json()
    if resp.status_code == 200 and body.get("status_code") == 200:
        return body["image"]["display_url"]

    raise RuntimeError(body.get("status_txt") or f"HTTP {resp.status_code}: {resp.text[:120]}")


def _has_image_host(cfg: dict) -> bool:
    """Return True if any image hosting API key is configured."""
    return bool(cfg.get("freeimage_api_key") or cfg.get("imghippo_api_key"))


def upload_image(image_bytes: bytes, cfg: dict, name: str = "product") -> str:
    """Upload using Freeimage.host if configured, otherwise Imghippo."""
    if cfg.get("freeimage_api_key"):
        return upload_to_freeimage(image_bytes, cfg["freeimage_api_key"], name=name)
    if cfg.get("imghippo_api_key"):
        return upload_to_imghippo(image_bytes, cfg["imghippo_api_key"], name=name)
    raise RuntimeError("No image hosting configured. Add an API key in Settings → Image Hosting.")


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
    _stock = int(product.get("stock_left", 0))
    _status = str(product.get("status") or (
        "Backordered" if _stock < 0 else ("Out of stock" if _stock == 0 else ("Low stock" if _stock <= 10 else "In stock"))
    ))
    row = {
        "sku":        product["sku"],
        "item_name":  product["item_name"],
        "category":   product.get("category", ""),
        "price":      product.get("price", 0.0),
        "stock_left": _stock,
        "status":     _status,
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
                    """, (row["sku"],row["item_name"],row["category"],row["price"],row["stock_left"],row["status"],row["image_url"]))
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
        new_stock = row["stock_left"] + delta
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
                new_stock = row[0] + delta
                status = "Backordered" if new_stock < 0 else ("Out of stock" if new_stock == 0 else ("Low stock" if new_stock <= 10 else "In stock"))
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
        new_stock = current + delta
        status = "Backordered" if new_stock < 0 else ("Out of stock" if new_stock == 0 else ("Low stock" if new_stock <= 10 else "In stock"))
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
    status = "Backordered" if stock < 0 else ("Out of stock" if stock == 0 else ("Low stock" if stock <= 10 else "In stock"))
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


def sync_sqlite_to_cloud(cfg: dict) -> tuple[int, list[str]]:
    """Read every row from SQLite and upsert to all configured cloud databases.
    Returns (rows_synced, error_list). Call this to push local data to cloud after reconnecting."""
    errors: list[str] = []
    synced = 0

    # Read all rows from SQLite
    try:
        conn = _get_sqlite_conn()
        rows = conn.execute("SELECT * FROM inventory").fetchall()
        conn.close()
        records = [dict(r) for r in rows]
    except Exception as exc:
        return 0, [f"Could not read SQLite: {exc}"]

    if not records:
        return 0, []

    # ── Neon ──────────────────────────────────────────────────────────
    conn_pg = _get_db_conn(cfg)
    if conn_pg is not None:
        try:
            with conn_pg:
                with conn_pg.cursor() as cur:
                    for rec in records:
                        cur.execute("""
                            INSERT INTO inventory (sku, item_name, category, price, stock_left, status, image_url)
                            VALUES (%s,%s,%s,%s,%s,%s,%s)
                            ON CONFLICT(sku) DO UPDATE SET
                                item_name=EXCLUDED.item_name, category=EXCLUDED.category,
                                price=EXCLUDED.price, stock_left=EXCLUDED.stock_left,
                                status=EXCLUDED.status, image_url=EXCLUDED.image_url
                        """, (rec.get("sku"), rec.get("item_name"), rec.get("category"),
                              rec.get("price"), rec.get("stock_left"), rec.get("status"),
                              rec.get("image_url")))
            conn_pg.close()
            synced = len(records)
        except Exception as exc:
            errors.append(f"Neon sync failed: {exc}")

    # ── Supabase ──────────────────────────────────────────────────────
    sb_url = cfg.get("supabase_url", "").strip()
    sb_key = (cfg.get("supabase_service_role_key") or cfg.get("supabase_key", "")).strip()
    if sb_url and sb_key:
        try:
            from supabase import create_client  # type: ignore
            client = create_client(sb_url, sb_key)
            for rec in records:
                row = {
                    "sku": rec.get("sku"), "item_name": rec.get("item_name"),
                    "category": rec.get("category"), "price": rec.get("price"),
                    "stock_left": rec.get("stock_left"), "status": rec.get("status"),
                    "image_url": rec.get("image_url"),
                }
                existing = client.table("inventory").select("sku").eq("sku", row["sku"]).execute()
                if getattr(existing, "data", None):
                    client.table("inventory").update(row).eq("sku", row["sku"]).execute()
                else:
                    client.table("inventory").insert(row).execute()
            synced = max(synced, len(records))
        except Exception as exc:
            errors.append(f"Supabase sync failed: {exc}")

    return synced, errors


@st.cache_data(ttl=30, show_spinner=False)
def _fetch_inventory_supabase(sb_url: str, sb_key: str) -> list | None:
    try:
        from supabase import create_client  # type: ignore
        client = create_client(sb_url, sb_key)
        res = client.table("inventory").select("*").order("item_name").execute()
        if res.data:
            return res.data
    except Exception:
        pass
    return None


@st.cache_data(ttl=30, show_spinner=False)
def _fetch_inventory_neon(conn_str: str) -> list | None:
    try:
        import psycopg2  # type: ignore
        conn = psycopg2.connect(conn_str, connect_timeout=10)
        df = pd.read_sql("SELECT * FROM inventory ORDER BY item_name", conn)
        conn.close()
        if not df.empty:
            return df.to_dict("records")
    except Exception:
        pass
    return None


@st.cache_data(ttl=30, show_spinner=False)
def _fetch_inventory_sqlite_cached() -> list | None:
    df = load_inventory_from_sqlite()
    if not df.empty:
        return df.to_dict("records")
    return None


def load_inventory_preferring_cloud(cfg: dict) -> pd.DataFrame:
    """Load inventory preferring Supabase > Neon > SQLite (results cached 30 s)."""
    sb_url = cfg.get("supabase_url", "").strip()
    sb_key = (cfg.get("supabase_service_role_key") or cfg.get("supabase_key", "")).strip()
    if sb_url and sb_key:
        rows = _fetch_inventory_supabase(sb_url, sb_key)
        if rows:
            return pd.DataFrame(rows)

    conn_str = cfg.get("neon_connection_string", "").strip()
    if conn_str:
        rows = _fetch_inventory_neon(conn_str)
        if rows:
            return pd.DataFrame(rows)

    rows = _fetch_inventory_sqlite_cached()
    if rows:
        return pd.DataFrame(rows)
    return load_inventory_from_sqlite()


def load_products_for_catalog(cfg: dict) -> list[dict]:
    """Load product list preferring Supabase > Neon > SQLite > config.json (cached 30 s)."""
    sb_url = cfg.get("supabase_url", "").strip()
    sb_key = (cfg.get("supabase_service_role_key") or cfg.get("supabase_key", "")).strip()
    if sb_url and sb_key:
        rows = _fetch_inventory_supabase(sb_url, sb_key)
        if rows:
            return rows

    conn_str = cfg.get("neon_connection_string", "").strip()
    if conn_str:
        rows = _fetch_inventory_neon(conn_str)
        if rows:
            return rows

    rows = _fetch_inventory_sqlite_cached()
    if rows:
        return rows

    return cfg.get("products", [])


def save_outbound_log(log: dict, cfg: dict):
    """Save an email record to all configured databases."""
    row = {
        "name": log.get("name", "Customer"),
        "email": log.get("email", ""),
        "order": log.get("order_number", "N/A"),
        "prods": log.get("products", ""),
        "sub": float(log.get("subtotal", 0.0) or 0.0),
        "tax": float(log.get("tax", 0.0) or 0.0),
        "ship": float(log.get("shipping", 0.0) or 0.0),
        "cost": float(log.get("total_cost", 0.0) or 0.0)
    }
    # SQLite
    try:
        conn = _get_sqlite_conn()
        conn.execute("""
            INSERT INTO outbound_logs (recipient_name, recipient_email, order_number, products_list, subtotal, tax, shipping, total_cost)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (row["name"], row["email"], row["order"], row["prods"], row["sub"], row["tax"], row["ship"], row["cost"]))
        conn.commit()
        conn.close()
    except Exception: pass

    # Neon
    conn_pg = _get_db_conn(cfg)
    if conn_pg:
        try:
            with conn_pg:
                with conn_pg.cursor() as cur:
                    cur.execute("""
                        INSERT INTO outbound_logs (recipient_name, recipient_email, order_number, products_list, subtotal, tax, shipping, total_cost)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    """, (row["name"], row["email"], row["order"], row["prods"], row["sub"], row["tax"], row["ship"], row["cost"]))
            conn_pg.close()
        except Exception: pass

    # Supabase
    sb_url = cfg.get("supabase_url","").strip()
    sb_key = (cfg.get("supabase_service_role_key") or cfg.get("supabase_key","")).strip()
    if sb_url and sb_key:
        try:
            from supabase import create_client
            client = create_client(sb_url, sb_key)
            client.table("outbound_logs").insert({
                "recipient_name": row["name"],
                "recipient_email": row["email"],
                "order_number": row["order"],
                "products_list": row["prods"],
                "subtotal": row["sub"],
                "tax": row["tax"],
                "shipping": row["ship"],
                "total_cost": row["cost"]
            }).execute()
        except Exception: pass


def load_outbound_logs(cfg: dict) -> pd.DataFrame:
    """Load outbound logs from cloud (preferring Supabase > Neon) or local SQLite."""
    sb_url = cfg.get("supabase_url","").strip()
    sb_key = (cfg.get("supabase_service_role_key") or cfg.get("supabase_key","")).strip()
    if sb_url and sb_key:
        try:
            from supabase import create_client
            client = create_client(sb_url, sb_key)
            res = client.table("outbound_logs").select("*").order("created_at", desc=True).limit(500).execute()
            if res.data:
                df = pd.DataFrame(res.data)
                # Rename columns to match local if needed
                df = df.rename(columns={"created_at": "timestamp"})
                return df
        except Exception: pass

    conn_str = cfg.get("neon_connection_string", "").strip()
    if conn_str:
        try:
            import psycopg2
            conn = psycopg2.connect(conn_str, connect_timeout=10)
            df = pd.read_sql("SELECT * FROM outbound_logs ORDER BY created_at DESC LIMIT 500", conn)
            conn.close()
            df = df.rename(columns={"created_at": "timestamp"})
            return df
        except Exception: pass

    try:
        conn = _get_sqlite_conn()
        df = pd.read_sql("SELECT * FROM outbound_logs ORDER BY timestamp DESC LIMIT 500", conn)
        conn.close()
        return df
    except Exception:
        return pd.DataFrame()


# ─────────────────────────────────────────────
# Page setup
# ─────────────────────────────────────────────

_early_cfg = load_config()
_title_co = _early_cfg.get("from_name", "").strip()
_app_title = f"{_title_co} - MERIT" if _title_co else "MERIT"
st.set_page_config(page_title=_app_title, layout="wide")

if "cfg" not in st.session_state:
    st.session_state.cfg = _early_cfg

if "queue" not in st.session_state:
    st.session_state.queue = []

if "send_log" not in st.session_state:
    st.session_state.send_log = []

# ─────────────────────────────────────────────
# Shared helpers
# ─────────────────────────────────────────────

def split_products(raw: str) -> list[str]:
    if not raw or str(raw).strip() in ("", "nan", "None", "null"):
        return []
    text = str(raw).strip()
    # Support multiple separators: |, ;, \n, and comma (if not part of a single item name usually)
    # We use a prioritized split. 
    for sep in ["|", ";", "\n"]:
        if sep in text:
            return [p.strip() for p in text.split(sep) if p.strip()]
    
    if "," in text:
        return [p.strip() for p in text.split(",") if p.strip()]
    
    # Space split is only done if multiple words exist AND none match the catalog (fuzzy)
    # But usually it's safer to not auto-split by space.
    return [text]


def validate_email(e: str) -> bool:
    return bool(e and "@" in e and "." in e.split("@")[-1])


def add_to_queue(name: str, email: str, order_number: str, products: str, 
                 sub: float = 0.0, tax: float = 0.0, ship: float = 0.0, total: float = 0.0,
                 discount: float = 0.0) -> bool:
    if not name.strip():
        st.error("Name is required.")
        return False
    if not validate_email(email.strip()):
        st.error(f"Invalid email: '{email}'")
        return False
    st.session_state.queue.append({
        "name":          name.strip(),
        "email":         email.strip(),
        "order_number":  order_number.strip() or "N/A",
        "products":      products.strip(),
        "subtotal":      round(float(sub), 2),
        "tax":           round(float(tax), 2),
        "shipping":      round(float(ship), 2),
        "discount":      round(float(discount), 2),
        "total_cost":    round(float(total), 2)
    })
    return True

# ─────────────────────────────────────────────
# Sidebar navigation
# ─────────────────────────────────────────────

with st.sidebar:
    _sb_co = st.session_state.cfg.get("from_name", "").strip()
    st.title(f"{_sb_co} · MERIT" if _sb_co else "MERIT")
    page = st.radio(
        "page",
        ["Email Sender", "Products", "Inventory", "Settings"],
        label_visibility="collapsed",
    )
    st.divider()
    cfg = st.session_state.cfg
    if cfg.get("from_name"):
        st.caption(f"Sending as: **{cfg['from_name']}**")
    if cfg.get("smtp_email"):
        st.caption(f"From: {cfg['smtp_email']}")
    products_count = len(cfg.get("products", []))
    if products_count:
        st.caption(f"Catalog Products: {products_count}")
    
    # ── Queue Status Indicator in Sidebar ─────
    _queue_count = len(st.session_state.queue)
    if _queue_count:
        st.divider()
        st.subheader(f"Queue: {_queue_count}")
        # Check if queue has any unmatched products
        _cat_names = [p["item_name"].lower().strip() for p in (load_products_for_catalog(cfg))]
        _has_err = False
        for _ord in st.session_state.queue:
            for _p in split_products(_ord.get("products", "")):
                _pl = _p.lower().strip()
                if not any(_pl in cn or cn in _pl for cn in _cat_names):
                    _has_err = True
                    break
            if _has_err: break
        if _has_err:
            st.error("⚠️ Queue has unmatched items. Fix them in **Email Sender** before sending.")
        else:
            st.success("✅ Queue is ready.")


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


_DEFAULT_EMAIL_TEMPLATE = """\
<!DOCTYPE html>
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
            <p style="margin:0;font-size:20px;font-weight:700;color:#fff;">{{from_name}}</p>
          </td>
        </tr>
        <tr>
          <td style="padding:32px 36px;">
            <p style="margin:0 0 12px;font-size:16px;color:#111;">Hi {{name}},</p>
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
                    #{{order_number}}
                  </p>
                </td>
              </tr>
            </table>
            <p style="margin:0 0 12px;font-size:11px;color:#888;
                       text-transform:uppercase;letter-spacing:.6px;font-weight:600;">
              Items Ordered
            </p>
            <table cellpadding="0" cellspacing="0" style="width:100%;margin-bottom:28px;">
              {{items_html}}
            </table>
            <table cellpadding="0" cellspacing="0" style="width:100%;border-top:2px solid #f4f4f5;padding-top:16px;margin-bottom:8px;">
              <tr>
                <td style="font-size:13px;color:#666;">Subtotal</td>
                <td align="right" style="font-size:13px;color:#111;">${{subtotal}}</td>
              </tr>
              <tr>
                <td style="font-size:13px;color:#666;padding-top:4px;">Discount</td>
                <td align="right" style="font-size:13px;color:#dc2626;padding-top:4px;">-${{discount}}</td>
              </tr>
              <tr>
                <td style="font-size:13px;color:#666;padding-top:4px;">Tax</td>
                <td align="right" style="font-size:13px;color:#111;padding-top:4px;">${{tax}}</td>
              </tr>
              <tr>
                <td style="font-size:13px;color:#666;padding-top:4px;">Shipping</td>
                <td align="right" style="font-size:13px;color:#111;padding-top:4px;">${{shipping}}</td>
              </tr>
              <tr>
                <td style="font-size:14px;color:#888;font-weight:600;text-transform:uppercase;padding-top:12px;">Total Amount</td>
                <td align="right" style="font-size:20px;font-weight:700;color:#18181b;padding-top:12px;">${{total_cost}}</td>
              </tr>
            </table>
            <p style="margin:0;font-size:13px;color:#888;line-height:1.6;">
              Questions? Just reply to this email and we will be happy to help.
            </p>
          </td>
        </tr>
        <tr>
          <td style="background:#fafafa;padding:16px 36px;border-top:1px solid #ebebeb;">
            <p style="margin:0;font-size:12px;color:#bbb;">Sent by {{from_name}}</p>
          </td>
        </tr>
      </table>
    </td></tr>
  </table>
</body>
</html>"""


def build_html(
    order: dict,
    from_name: str,
    products_lookup: dict[str, str] | None = None,
    template: str | None = None,
) -> str:
    name      = order.get("name", "Customer")
    order_num = order.get("order_number", "N/A")
    prods     = split_products(order.get("products", ""))
    sub       = f"{float(order.get('subtotal', 0.0)):.2f}"
    tax       = f"{float(order.get('tax', 0.0)):.2f}"
    ship      = f"{float(order.get('shipping', 0.0)):.2f}"
    disc      = f"{float(order.get('discount', 0.0)):.2f}"
    cost      = f"{float(order.get('total_cost', 0.0)):.2f}"
    items     = _build_items_html(prods, products_lookup)
    tpl = (template.strip() if template and template.strip() else _DEFAULT_EMAIL_TEMPLATE)
    return (
        tpl
        .replace("{{name}}", name)
        .replace("{{order_number}}", order_num)
        .replace("{{from_name}}", from_name)
        .replace("{{items_html}}", items)
        .replace("{{subtotal}}", sub)
        .replace("{{tax}}", tax)
        .replace("{{shipping}}", ship)
        .replace("{{discount}}", disc)
        .replace("{{total_cost}}", cost)
    )


def build_text(order: dict, from_name: str) -> str:
    name      = order.get("name", "Customer")
    order_num = order.get("order_number", "N/A")
    prods     = split_products(order.get("products", ""))
    sub       = f"{float(order.get('subtotal', 0.0)):.2f}"
    tax       = f"{float(order.get('tax', 0.0)):.2f}"
    ship      = f"{float(order.get('shipping', 0.0)):.2f}"
    cost      = f"{float(order.get('total_cost', 0.0)):.2f}"
    lines     = "\n".join(f"  - {p}" for p in prods) if prods else "  - N/A"
    return (
        f"Hi {name},\n\n"
        f"Thank you for your order.\n\n"
        f"Order Number: #{order_num}\n"
        f"Subtotal: ${sub}\n"
        f"Discount: -${disc}\n"
        f"Tax: ${tax}\n"
        f"Shipping: ${ship}\n"
        f"Total Amount: ${cost}\n\n"
        f"Items Ordered:\n{lines}\n\n"
        f"Questions? Reply to this email.\n\n"
        f"{from_name}"
    )


# ─────────────────────────────────────────────
# CSV parsing
# ─────────────────────────────────────────────

_ALIASES = {
    "name":         ["name", "full_name", "customer_name", "customer", "first_name", "billing_name"],
    "email":        ["email", "email_address", "e_mail", "mail", "customer_email"],
    "order_number": ["order_number", "order_no", "order_id", "order",
                     "orderid", "ordernumber", "transaction_no", "transaction"],
    "products":     ["products", "items", "product_list", "product",
                     "item", "description", "ordered_items"],
    "subtotal":     ["subtotal", "sub_total", "price_subtotal", "sub_total_amount"],
    "tax":          ["tax", "tax_amount", "taxes", "vat"],
    "shipping":     ["shipping", "shipping_cost", "freight", "delivery"],
    "discount":     ["discount", "discount_amount", "off", "promo_discount"],
    "total_cost":   ["total_cost", "total", "cost", "total_price", "amount", "price", "order_total"],
}


def _norm(h: str) -> str:
    return h.strip().lower().replace(" ", "_").replace("-", "_").replace("#", "").replace(".", "_").replace("/", "_").replace("(", "").replace(")", "")


def parse_excel_file(file_bytes) -> tuple[list[dict], list[str]]:
    import pandas as pd
    try:
        import openpyxl
    except ImportError:
        import subprocess, sys
        subprocess.check_call([sys.executable, "-m", "pip", "install", "openpyxl"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    
    warns = []
    try:
        xl = pd.ExcelFile(io.BytesIO(file_bytes))
        sheets = xl.sheet_names
        # Map sheets (some might have slight name variations)
        tx_sheet = next((s for s in sheets if "transaction" in s.lower() and "item" not in s.lower()), None)
        item_sheet = next((s for s in sheets if "transaction" in s.lower() and "item" in s.lower()), None)
        
        if not tx_sheet or not item_sheet:
            return [], [f"Excel file missing required sheets. Found: {sheets}"]
        
        df_tx = pd.read_excel(xl, sheet_name=tx_sheet)
        df_items = pd.read_excel(xl, sheet_name=item_sheet)
        
        # Link products to transactions
        tx_items = {}
        # Normalize columns for the items sheet
        df_items.columns = [_norm(c) for c in df_items.columns]
        for _, obj in df_items.iterrows():
            t_no = str(obj.get('transaction_no', '')).strip()
            item = str(obj.get('item_name', '')).strip()
            qty  = obj.get('quantity', 1)
            
            if t_no:
                if t_no not in tx_items: tx_items[t_no] = []
                try:
                    q_val = int(float(qty or 1))
                    if q_val > 1:
                        tx_items[t_no].append(f"{item} x {q_val}")
                    else:
                        tx_items[t_no].append(item)
                except:
                    tx_items[t_no].append(item)
        
        rows = []
        # Normalize columns for the transactions sheet
        df_tx.columns = [_norm(c) for c in df_tx.columns]
        for _, tx in df_tx.iterrows():
            t_no  = str(tx.get('transaction_no', '')).strip()
            email = str(tx.get('customer_email', '')).strip()
            name  = str(tx.get('billing_name', '')).strip() or str(tx.get('shipping_name', 'Customer')).strip()
            
            if not t_no or not email or not validate_email(email):
                continue
            
            # Combine items
            items_list = " | ".join(tx_items.get(t_no, ["N/A"]))
            
            rows.append({
                "name":          name,
                "email":         email,
                "order_number":  t_no,
                "products":      items_list,
                "subtotal":      round(float(tx.get('subtotal', 0.0) or 0.0), 2),
                "discount":      round(float(tx.get('discount', 0.0) or 0.0), 2),
                "tax":           round(float(tx.get('tax', 0.0) or 0.0), 2),
                "shipping":      round(float(tx.get('shipping', 0.0) or 0.0), 2),
                "total_cost":    round(float(tx.get('total', 0.0) or 0.0), 2),
            })
        return rows, warns
    except Exception as e:
        return [], [f"Error reading Excel: {e}"]


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
    if "products" not in hmap.values():
        return [], [f"No products column found (items ordered). Detected headers: {headers}"]
    
    rows = []
    required_keys = ["name", "email", "order_number", "products", "subtotal", "tax", "shipping", "discount", "total_cost"]
    for i, row in enumerate(reader, start=2):
        mapped = {c: (row.get(r) or "").strip() for r, c in hmap.items()}
        email  = mapped.get("email", "")
        if not email or not validate_email(email):
            warns.append(f"Row {i}: skipped — invalid or missing email")
            continue
        
        # Validation for required fields
        is_missing = False
        for rk in required_keys:
            if not mapped.get(rk):
                warns.append(f"Row {i}: skipped — missing required field '{rk}'")
                is_missing = True
                break
        if is_missing: continue

        rows.append({
            "name":          mapped.get("name", ""),
            "email":         email,
            "order_number":  mapped.get("order_number", ""),
            "products":      mapped.get("products", ""),
            "subtotal":      float(mapped.get("subtotal", 0.0) or 0.0),
            "discount":      float(mapped.get("discount", 0.0) or 0.0),
            "tax":           float(mapped.get("tax", 0.0) or 0.0),
            "shipping":      float(mapped.get("shipping", 0.0) or 0.0),
            "total_cost":    float(mapped.get("total_cost", 0.0) or 0.0),
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
    if not _has_image_host(cfg):
        st.warning(
            "No image hosting key set. Go to **Settings → Image Hosting** to add one. "
            "Free options: [freeimage.host](https://freeimage.host) or [imghippo.com](https://imghippo.com)."
        )
    _has_cloud_db = cfg.get("neon_connection_string") or (cfg.get("supabase_url") and (cfg.get("supabase_service_role_key") or cfg.get("supabase_key")))
    if not _has_cloud_db:
        st.info("Saving to **SQLite** (local). Connect Supabase or Neon in Settings for cloud backup.")

    if "_products_cache" not in st.session_state:
        with st.spinner("Loading products…"):
            st.session_state["_products_cache"] = load_products_for_catalog(cfg)
    products = st.session_state["_products_cache"]

    # Compute sync targets for display in this page
    _p_has_sb = bool(cfg.get("supabase_url","").strip() and (cfg.get("supabase_service_role_key") or cfg.get("supabase_key","")).strip())
    _p_has_neon = bool(cfg.get("neon_connection_string"))
    _p_sync = ["SQLite"] + (["Neon"] if _p_has_neon else []) + (["Supabase"] if _p_has_sb else [])
    _p_sync_str = " + ".join(_p_sync)

    tab_catalog, tab_add, tab_edit, tab_delete = st.tabs(
        ["Catalog", "Add Products", "Edit Products", "Delete Products"]
    )

    # ══ CATALOG ═════════════════════════════════
    with tab_catalog:
        if not products:
            st.info("No products yet. Go to the **Add Products** tab to get started.")
        else:
            if _p_has_sb or _p_has_neon:
                if st.button("Sync All to Cloud Databases", width="stretch", key="btn_sync_all"):
                    with st.spinner("Syncing all products to cloud..."):
                        _ok_n, _fail_n = 0, 0
                        for prod in products:
                            _ok, _ = save_product_to_db(prod, cfg)
                            if _ok: _ok_n += 1
                            else: _fail_n += 1
                        if _ok_n: st.toast("Sync complete.", icon="🌥️")
                        st.success(f"Synced {_ok_n} products." if not _fail_n else f"{_ok_n} synced, {_fail_n} failed.")

            st.caption(f"Showing {len(products)} product{'s' if len(products) != 1 else ''}. Syncing to: **{_p_sync_str}**")
            
            for i, prod in enumerate(products):
                _sku = prod.get("sku", "N/A")
                _name = prod.get("item_name", "Unknown")
                _img = prod.get("image_url", "N/A")
                has_img = bool(_img and _img not in ("N/A", ""))

                _c_img, _c_txt, _c_act = st.columns([1, 5, 2], vertical_alignment="center")
                with _c_img:
                    if has_img:
                        st.image(_img, width=80)
                    else:
                        st.markdown("<div style='width:80px;height:80px;background:#f4f4f5;border-radius:8px;display:flex;align-items:center;justify-content:center;color:#bbb;font-size:11px;'>No image</div>", unsafe_allow_html=True)
                with _c_txt:
                    st.markdown(f"**{_name}**")
                    st.caption(f"`{_sku}`  ·  {prod.get('category','General')}  ·  ${prod.get('price',0):.2f}  ·  Stock: {prod.get('stock_left',0)}")
                
                with _c_act:
                    with st.popover("Replace Image", width="stretch"):
                        st.markdown("##### Upload New Image")
                        _new_file = st.file_uploader("img", type=["jpg","jpeg","png","webp"], key=f"cat_repl_{_sku}_{i}", label_visibility="collapsed")
                        if _new_file and _has_image_host(cfg):
                            if st.button("Upload & Save", key=f"cat_repl_btn_{_sku}_{i}", type="primary", width="stretch"):
                                with st.spinner("Uploading..."):
                                    try:
                                        _new_url = upload_image(_new_file.read(), cfg, name=_name)
                                        prod["image_url"] = _new_url
                                        save_product_to_db(prod, cfg)
                                        _cfg_prods = [dict(p) for p in cfg.get("products", [])]
                                        for _cpc in _cfg_prods:
                                            if _cpc.get("sku") == _sku:
                                                _cpc["image_url"] = _new_url
                                        cfg["products"] = _cfg_prods
                                        save_config(cfg)
                                        st.session_state.cfg = cfg
                                        st.toast("Image updated.", icon="✅")
                                        _clear_data_caches()
                                        time.sleep(0.5)
                                        st.rerun()
                                    except Exception as _e:
                                        st.error(f"Upload failed: {_e}")
                        elif _new_file:
                            st.warning("Configure image hosting in Settings first.")
                st.divider()

    # ══ ADD PRODUCTS ════════════════════════════
    with tab_add:
        st.subheader("Add Products")
        st.caption(f"Add products individually or in bulk. Syncing to: **{_p_sync_str}**")
        
        _add_single_exp = st.expander("Add Single Product", expanded=True)
        with _add_single_exp:
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
                    st.image(p_image, width="stretch")

            if st.button("Add Product", type="primary", width="stretch", key="btn_add_product"):
                if not p_sku.strip():
                    st.error("SKU is required.")
                elif not p_name.strip():
                    st.error("Product Name is required.")
                else:
                    image_url = "N/A"
                    if p_image:
                        if not _has_image_host(cfg):
                            st.warning("Image skipped — add an image hosting key in Settings first.")
                        else:
                            with st.spinner("Processing image and adding product..."):
                                try:
                                    image_url = upload_image(p_image.read(), cfg, name=p_name.strip())
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
                    ok, saved_to = save_product_to_db(product, cfg)
                    if not ok:
                        st.toast("Something went wrong. Please try again.", icon="❌")
                    _cp = cfg.get("products", [])
                    cfg["products"] = [p for p in _cp if p.get("sku") != product["sku"]]
                    cfg["products"].append(product)
                    save_config(cfg)
                    st.session_state.cfg = cfg
                    st.toast("Product added successfully.", icon="✅")
                    st.success(f"**{product['item_name']}** added · Synced to: {saved_to}")
                    _clear_data_caches()
                    time.sleep(0.5)
                    st.rerun()

        _add_bulk_exp = st.expander("Add Bulk Products", expanded=False)
        with _add_bulk_exp:
            st.caption("Enter multiple products in the table below or upload a CSV.")
            if "pb_ids" not in st.session_state:
                st.session_state.pb_ids   = list(range(4))
                st.session_state.pb_next  = 4
            _PB_COLS = [1.5, 2.5, 1.5, 1.2, 2.8, 0.45]
            _pbh = st.columns(_PB_COLS)
            for _lbl, _col in zip(["SKU *", "Name *", "Category", "Price ($)", "Image", ""], _pbh):
                _col.caption(_lbl)
            for _rid in list(st.session_state.pb_ids):
                _pc = st.columns(_PB_COLS)
                with _pc[0]: st.text_input("sku", key=f"pb_sku_{_rid}", placeholder="SKU-001", label_visibility="collapsed")
                with _pc[1]: st.text_input("name", key=f"pb_name_{_rid}", placeholder="Blue T-Shirt", label_visibility="collapsed")
                with _pc[2]: st.text_input("cat", key=f"pb_cat_{_rid}", placeholder="General", label_visibility="collapsed")
                with _pc[3]: st.number_input("price", key=f"pb_price_{_rid}", min_value=0.0, step=0.01, format="%.2f", label_visibility="collapsed")
                with _pc[4]: st.file_uploader("img", key=f"pb_img_{_rid}", type=["jpg","jpeg","png","webp"], label_visibility="collapsed")
                with _pc[5]:
                    if st.button("×", key=f"pb_del_{_rid}", width="stretch"):
                        st.session_state.pb_ids.remove(_rid)
                        st.rerun()
            _idx_c1, _idx_c2 = st.columns([1, 3])
            with _idx_c1:
                if st.button("+ Add Row", width="stretch", key="pb_add_row"):
                    st.session_state.pb_ids.append(st.session_state.pb_next)
                    st.session_state.pb_next += 1
                    st.rerun()
            with _idx_c2:
                _bulk_csv = st.file_uploader("Import CSV (SKU, Name, Category, Price)", type=["csv"], key="bulk_csv")

            if st.button("Add All to Products", type="primary", width="stretch", key="btn_bulk_add"):
                with st.spinner("Processing products..."):
                    _pb_rows = []
                    for _rid in st.session_state.pb_ids:
                        _bsku = str(st.session_state.get(f"pb_sku_{_rid}", "")).strip().upper()
                        _bname = str(st.session_state.get(f"pb_name_{_rid}", "")).strip()
                        if _bsku and _bname:
                            _pb_rows.append({
                                "sku": _bsku, "name": _bname,
                                "cat": str(st.session_state.get(f"pb_cat_{_rid}", "")).strip() or "General",
                                "price": round(float(st.session_state.get(f"pb_price_{_rid}", 0.0)), 2),
                                "img": st.session_state.get(f"pb_img_{_rid}")
                            })
                    if _bulk_csv:
                        _df = pd.read_csv(_bulk_csv)
                        _df.columns = _df.columns.str.strip()
                        _cmap = {c: "SKU" if "sku" in c.lower() else "Name" if "name" in c.lower() or "prod" in c.lower() else "Category" if "cat" in c.lower() else "Price" if "price" in c.lower() else c for c in _df.columns}
                        _df = _df.rename(columns=_cmap)
                        for _, _r in _df.iterrows():
                            if str(_r.get("SKU","")).strip() and str(_r.get("Name","")).strip():
                                _pb_rows.append({"sku": str(_r["SKU"]).strip().upper(), "name": str(_r["Name"]).strip(), "cat": str(_r.get("Category","General")).strip() or "General", "price": round(float(_r.get("Price",0)), 2), "img": None})
                    
                    added, uploaded = 0, 0
                    for _r in _pb_rows:
                        _url = "N/A"
                        if _r["img"] and _has_image_host(cfg):
                            try:
                                _r["img"].seek(0)
                                _url = upload_image(_r["img"].read(), cfg, name=_r["name"])
                                uploaded += 1
                            except: pass
                        _p = {"sku": _r["sku"], "item_name": _r["name"], "category": _r["cat"], "price": _r["price"], "stock_left": 0, "status": "In stock", "image_url": _url}
                        save_product_to_db(_p, cfg)
                        _cp = cfg.get("products", [])
                        cfg["products"] = [x for x in _cp if x.get("sku") != _r["sku"]]
                        cfg["products"].append(_p)
                        added += 1
                    save_config(cfg)
                    st.session_state.cfg = cfg
                    st.session_state.pb_ids, st.session_state.pb_next = list(range(4)), 4
                    st.toast(f"Added {added} products.", icon="✅")
                    st.success(f"Successfully added {added} products.")
                    _clear_data_caches()
                    time.sleep(0.5)
                    st.rerun()

    # ══ EDIT PRODUCTS ════════════════════════════
    with tab_edit:
        st.subheader("Edit Products")
        if not products:
            st.info("No products yet.")
        else:
            _edit_sku = st.selectbox(
                "Select a product to edit",
                options=[p["sku"] for p in products if p.get("sku")],
                format_func=lambda s: f"{next((p['item_name'] for p in products if p['sku'] == s), s)} ({s})",
                key="prod_edit_select"
            )
            _eprod = next((p for p in products if p["sku"] == _edit_sku), None)
            if _eprod:
                with st.form(key=f"edit_form_{_edit_sku}"):
                    _e_c1, _e_c2 = st.columns(2)
                    with _e_c1:
                        _e_name  = st.text_input("Product Name *", value=str(_eprod.get("item_name", "")))
                        _e_cat   = st.text_input("Category",       value=str(_eprod.get("category", "")))
                    with _e_c2:
                        _e_price = st.number_input("Price ($)", value=float(_eprod.get("price", 0.0)), min_value=0.0, step=0.01, format="%.2f")
                        _e_img   = st.text_input("Image URL",   value=str(_eprod.get("image_url", "N/A")))
                    if st.form_submit_button("Save Changes", type="primary", width="stretch"):
                        with st.spinner("Saving..."):
                            _upd = {
                                "sku": _edit_sku, "item_name": _e_name.strip() or _eprod.get("item_name", ""),
                                "category": _e_cat.strip() or _eprod.get("category", "General"),
                                "price": round(_e_price, 2), "image_url": _e_img.strip() or "N/A",
                                "stock_left": _eprod.get("stock_left", 0), "status": _eprod.get("status", "In stock")
                            }
                            _ok, _msg = save_product_to_db(_upd, cfg)
                            if not _ok: st.toast("Error saving to database.", icon="❌")
                            _cp = cfg.get("products", [])
                            cfg["products"] = [_upd if p.get("sku") == _edit_sku else p for p in _cp]
                            if not any(p.get("sku") == _edit_sku for p in _cp): cfg["products"].append(_upd)
                            save_config(cfg)
                            st.session_state.cfg = cfg
                            st.toast("Product updated.", icon="✅")
                            _clear_data_caches()
                            time.sleep(0.5)
                            st.rerun()

    # ══ DELETE PRODUCTS ══════════════════════════
    with tab_delete:
        st.subheader("Delete Products")
        if not products:
            st.info("No products yet.")
        else:
            st.caption(f"Permanently remove products from: **{_p_sync_str}**")
            _bd_map = {p["sku"]: f"{p.get('item_name', p['sku'])} ({p['sku']})" for p in products if p.get("sku")}
            _bd_selected = st.multiselect("Select products to delete", options=list(_bd_map.keys()), format_func=lambda s: _bd_map[s])
            if _bd_selected:
                st.warning(f"**{len(_bd_selected)} product(s)** will be deleted.")
                _bd_confirm = st.checkbox("Confirm permanent deletion", key="p_del_confirm")
                if st.button("Delete Selected", type="primary", key="btn_p_del", disabled=not _bd_confirm, width="stretch"):
                    with st.spinner("Deleting..."):
                        for _sku in _bd_selected:
                            delete_product_from_db(_sku, cfg)
                        cfg["products"] = [p for p in cfg.get("products", []) if p.get("sku") not in _bd_selected]
                        save_config(cfg)
                        st.session_state.cfg = cfg
                        st.toast(f"Deleted {len(_bd_selected)} items.", icon="✅")
                        _clear_data_caches()
                        time.sleep(0.5)
                        st.rerun()



# ═════════════════════════════════════════════
# INVENTORY PAGE
# ═════════════════════════════════════════════

elif page == "Inventory":
    cfg = st.session_state.cfg
    st.title("Inventory")
    st.caption("Manage stock overview, adjustments, and outbound logs in one place.")

    tab_overview, tab_adjust, tab_outbound = st.tabs(
        ["Overview", "Adjust Stock", "Outbound Information"]
    )

    # Load shared data
    if "_inv_cache" not in st.session_state:
        with st.spinner("Loading inventory…"):
            st.session_state["_inv_cache"] = load_inventory_preferring_cloud(cfg)
    inv_df = st.session_state["_inv_cache"]

    # ── OVERVIEW ────────────────────────────────
    with tab_overview:
        if inv_df.empty:
            st.info("No products found. Add products in the **Products** page first.")
        else:
            # ── Metrics ─────────────────────────────
            _ov_stock = inv_df["stock_left"].fillna(0).astype(int)
            _ov_c1, _ov_c2, _ov_c3, _ov_c4 = st.columns(4)
            _ov_c1.metric("Total Products",    len(inv_df))
            _ov_c2.metric("Total Stock Units", int(_ov_stock.sum()))
            _ov_c3.metric("Low Stock Items",   int(((_ov_stock > 0) & (_ov_stock <= 10)).sum()))
            _ov_c4.metric("Out of Stock",      int((_ov_stock == 0).sum()))

            st.divider()

            # ── Stock Chart ──────────────────────────
            if "item_name" in inv_df.columns:
                _ov_chart = (
                    inv_df[["item_name", "stock_left"]]
                    .copy()
                    .rename(columns={"item_name": "Product", "stock_left": "Stock Level"})
                    .sort_values("Stock Level", ascending=False)
                    .set_index("Product")
                )
                st.bar_chart(_ov_chart["Stock Level"], color="#4F46E5")

            st.divider()
            st.info("To modify stock levels, use the **Adjust Stock** tab above. To add or edit product details, go to the **Products** page.")

    # ── ADJUST STOCK ────────────────────────────
    with tab_adjust:
        if inv_df.empty:
            st.info("No products found. Add products in the **Products** page first.")
        else:
            _has_supabase = bool(cfg.get("supabase_url","").strip() and (cfg.get("supabase_service_role_key") or cfg.get("supabase_key","")).strip())
            _has_neon = bool(cfg.get("neon_connection_string"))
            _sync_targets = ["SQLite"]
            if _has_neon:   _sync_targets.append("Neon")
            if _has_supabase: _sync_targets.append("Supabase")

            st.caption(
                f"Set a ± amount for each product, then click **Apply** next to it or **Apply All** at the top. "
                f"Synced to: **{' + '.join(_sync_targets)}**"
            )

            # ── Apply All Changes ───────────────────
            if st.button("Apply All Changes", type="primary", width="stretch", key="btn_adj_all"):
                with st.spinner("Applying adjustments..."):
                    _adj_applied = 0
                    for _, _arow in inv_df.iterrows():
                        _asku   = str(_arow["sku"])
                        _adelta = int(st.session_state.get(f"adj_{_asku}", 0))
                        if _adelta == 0:
                            continue
                        adjust_inventory_sqlite(_asku, _adelta)
                        if _has_neon:     adjust_inventory_neon(_asku, _adelta, cfg)
                        if _has_supabase: adjust_inventory_supabase(_asku, _adelta, cfg)
                        _adj_applied += 1
                    if _adj_applied:
                        st.toast("Stock updated successfully.", icon="✅")
                        st.success(f"Applied {_adj_applied} adjustment(s) · {' + '.join(_sync_targets)}")
                        _clear_data_caches()
                        time.sleep(0.5)
                        st.rerun()
                    else:
                        st.warning("All deltas are 0 — set a non-zero amount first.")

            st.divider()

            # ── Per-product rows ────────────────────
            _img_col_exists = "image_url" in inv_df.columns
            for _, _pr in inv_df.iterrows():
                _psku   = str(_pr.get("sku", ""))
                _pname  = str(_pr.get("item_name", _psku))
                _pstock = int(_pr.get("stock_left", 0))
                _pstat  = str(_pr.get("status", ""))
                _pcat   = str(_pr.get("category", ""))
                _pimg   = str(_pr.get("image_url", "")) if _img_col_exists else ""

                _stat_color = (
                    "#7c3aed" if "Backordered" in _pstat
                    else "#dc2626" if "Out" in _pstat
                    else "#f59e0b" if "Low" in _pstat
                    else "#16a34a"
                )

                _rc1, _rc2, _rc3, _rc4, _rc5 = st.columns([1, 4, 2, 2, 1.5], vertical_alignment="center")

                with _rc1:
                    if _pimg and _pimg not in ("N/A", "", "nan"):
                        st.image(_pimg, width=56)
                    else:
                        st.markdown("<div style='width:56px;height:56px;background:#f4f4f5;border-radius:8px;display:flex;align-items:center;justify-content:center;color:#bbb;font-size:10px;'>No img</div>", unsafe_allow_html=True)

                with _rc2:
                    st.markdown(f"**{_pname}**")
                    st.caption(f"{_psku}  ·  {_pcat}")

                with _rc3:
                    st.markdown(
                        f"<div style='display:flex; align-items:center;'>"
                        f"<span style='font-size:24px;font-weight:700;color:#ffffff;line-height:1;'>{_pstock}</span>"
                        f"<span style='font-size:10px;margin-left:8px;color:{_stat_color};white-space:nowrap;'>{_pstat}</span>"
                        f"</div>",
                        unsafe_allow_html=True,
                    )

                with _rc4:
                    _delta_val = st.number_input("±", step=1, value=0, key=f"adj_{_psku}", label_visibility="collapsed")

                with _rc5:
                    if st.button("Apply", key=f"btn_adj_{_psku}", width="stretch"):
                        with st.spinner("Updating..."):
                            if _delta_val == 0:
                                st.toast(f"{_pname}: delta is 0, nothing changed.")
                            else:
                                ok, _am = adjust_inventory_sqlite(_psku, int(_delta_val))
                                if not ok:
                                    st.toast("Something went wrong. Please try again.", icon="❌")
                                if _has_neon:     adjust_inventory_neon(_psku, int(_delta_val), cfg)
                                if _has_supabase: adjust_inventory_supabase(_psku, int(_delta_val), cfg)
                                st.toast(f"Stock updated: {_pname}", icon="✅")
                                _clear_data_caches()
                                time.sleep(0.5)
                                st.rerun()
                st.divider()

    # ── OUTBOUND INFORMATION ────────────────────
    with tab_outbound:
        st.subheader("Sent History")
        st.caption("View a history of all emails sent and their impact on inventory.")
        logs = load_outbound_logs(cfg)

        if logs.empty:
            st.info("No outbound emails found. Start sending emails from the **Email Sender** page.")
        else:
            # Format the table for display
            display_df = logs.copy()
            if "recipient_name" in display_df.columns:
                display_df = display_df.rename(columns={
                    "recipient_name": "Name",
                    "recipient_email": "Email",
                    "order_number": "Order #",
                    "products_list": "Products",
                    "subtotal": "Sub ($)",
                    "tax": "Tax ($)",
                    "shipping": "Ship ($)",
                    "total_cost": "Total ($)",
                    "timestamp": "Sent At"
                })
            
            cols = ["Sent At", "Name", "Email", "Order #", "Products", "Sub ($)", "Tax ($)", "Ship ($)", "Total ($)"]
            display_df = display_df[[c for c in cols if c in display_df.columns]]
            
            st.dataframe(
                display_df,
                width="stretch",
                hide_index=True,
                column_config={
                    "Cost ($)": st.column_config.NumberColumn(format="$%.2f"),
                    "Sent At": st.column_config.DatetimeColumn(format="MMM DD, YYYY, HH:mm"),
                    "Products": st.column_config.TextColumn(width="large")
                }
            )

            if st.button("Clear View Cache", width="stretch"):
                _clear_data_caches()
                st.rerun()


# ═════════════════════════════════════════════
# SETTINGS PAGE
# ═════════════════════════════════════════════

elif page == "Settings":
    st.title("Settings")
    st.caption("Settings are saved to config.json in the app folder and load automatically on every visit.")

    # ── One-time toast reminder ──────────────────
    if "_settings_toast_shown" not in st.session_state:
        st.toast("Tip: after testing your keys, scroll to the bottom and click **Save Settings**!", icon="💾")
        st.session_state["_settings_toast_shown"] = True

    # ── VEI account note ─────────────────────────
    st.info(
        "**VEI Firms:** You must use your VEI account for all settings below. "
        "Click **Getting Started** (below) to set everything up step by step. "
        "Your firm coordinator may have already set up a shared Gmail account and firm name — ask them for the details. "
        "All other keys (image hosting, database) are personal free accounts you create yourself."
    )

    with st.expander("Getting Started — how to set everything up", expanded=False):
        st.markdown("""
### 1. Gmail SMTP (required for sending emails)
1. Go to [myaccount.google.com](https://myaccount.google.com) → **Security**
2. Enable **2-Step Verification** (required)
3. Search for **App passwords** → create one named `Email Sender`
4. Copy the 16-character password and paste it below under **Gmail SMTP**

---

### 2. Image Hosting — free (required for product images in emails)
Choose **one** of these free services:

**Freeimage.host** (recommended):
1. Go to [freeimage.host](https://freeimage.host) → **Sign up**
2. Log in → click the **menu icon (☰)** in the top-left → click **API**
3. Copy your API key and paste it below under **Image Hosting → Freeimage.host**

**Imghippo** (alternative):
1. Sign up at [https://www.imghippo.com/](https://www.imghippo.com/)
2. Navigate to API Keys at [https://www.imghippo.com/settings?tab=api-keys](https://www.imghippo.com/settings?tab=api-keys)
3. Complete the API access form (5 steps):
   - **Step 1:** Select Website/Web Application
   - **Step 2:** Select Less than 1,000
   - **Step 3:** Select Image upload and sharing
   - **Step 4:** Skip (optional)
   - **Step 5:** Select Yes, I agree
4. Copy the generated API key and paste it below under **Image Hosting → Imghippo**
5. Test the key, click **Save Settings**, and retry if it fails.

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
            placeholder="Acme VEI Firm",
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

    st.markdown("<div style='margin-bottom:10px;'></div>", unsafe_allow_html=True)
    can_test = bool(inp_smtp_email.strip() and inp_smtp_pass.strip())
    if st.button("Test SMTP Connection", width="stretch", disabled=not can_test):
        with st.spinner("Testing connection to Gmail SMTP..."):
            try:
                server = smtplib.SMTP("smtp.gmail.com", 587, timeout=10)
                server.starttls()
                server.login(inp_smtp_email.strip(), re.sub(r"\s+", "", inp_smtp_pass.strip()))
                server.quit()
                st.toast("SMTP connection success!", icon="📧")
                st.success("SMTP connection successful.")
            except Exception as exc:
                st.error(f"Connection failed: {exc}")

    # ── Image Hosting ─────────────────────────────
    st.divider()
    st.subheader("Image Hosting")
    st.caption("Choose one free image hosting service. Product images are uploaded automatically.")

    _img_tab_fi, _img_tab_ih = st.tabs(["Freeimage.host", "Imghippo"])

    with _img_tab_fi:
        with st.expander("How to get a Freeimage.host API key", expanded=False):
            st.markdown("""
1. Go to [freeimage.host](https://freeimage.host) and click **Sign up** (free, no credit card)
2. Verify your email, then log in
3. Click the **menu icon** (☰) in the top-left corner
4. Click **API** in the menu
5. Your API key is shown on that page — copy it
6. Paste it in the field below and click **Save Settings**
            """)

        _fi_l, _fi_r = st.columns([3, 1])
        with _fi_l:
            inp_freeimage_key = st.text_input(
                "Freeimage.host API Key",
                value=cfg.get("freeimage_api_key", ""),
                type="password",
                placeholder="your_api_key_here",
                help="freeimage.host → Menu → API → copy your key",
                key="inp_freeimage_key",
            )
        with _fi_r:
            st.markdown("<div style='margin-top:28px;'></div>", unsafe_allow_html=True)
            if st.button("Test Key", width="stretch", key="btn_test_fi", disabled=not inp_freeimage_key):
                with st.spinner("Testing Freeimage.host API..."):
                    try:
                        import requests  # type: ignore
                        _test_path = Path(__file__).parent / "TESTPRODUCT.png"
                        if _test_path.exists():
                            _fi_raw = _test_path.read_bytes()
                        else:
                            import base64 as _b64
                            _fi_raw = _b64.b64decode("/9j/4AAQSkZJRgABAQEASABIAAD/2wBDAAgGBgcGBQgHBwcJCQgKDBQNDAsLDBkSEw8UHRofHh0aHBwgJC4nICIsIxwcKDcpLDAxNDQ0Hyc5PTgyPC4zNDL/2wBDAQkJCQwLDBgNDRgyIRwhMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjL/wAARCAABAAEDASIAAhEBAxEB/8QAFAABAAAAAAAAAAAAAAAAAAAACf/EABQQAQAAAAAAAAAAAAAAAAAAAAD/xAAUAQEAAAAAAAAAAAAAAAAAAAAA/8QAFBEBAAAAAAAAAAAAAAAAAAAAAP/aAAwDAQACEQMRAD8AJQAB/9k=")
                        _fi_resp = requests.post(
                            "https://freeimage.host/api/1/upload",
                            data={"key": inp_freeimage_key.strip(), "action": "upload", "format": "json"},
                            files={"source": ("test.jpg", io.BytesIO(_fi_raw), "image/jpeg")},
                            timeout=20,
                        )
                        _fi_body = _fi_resp.json() if _fi_resp.content else {}
                        if _fi_resp.status_code == 200 and _fi_body.get("status_code") == 200:
                            st.toast("Freeimage.host key verified!", icon="🖼️")
                            st.success("Freeimage.host key works!")
                        else:
                            st.error(f"Error: {_fi_body.get('status_txt', _fi_resp.text[:150])}")
                    except Exception as exc:
                        st.error(f"Test failed: {exc}")

    with _img_tab_ih:
        with st.expander("How to get an Imghippo API key", expanded=False):
            st.markdown("""
1. Sign up at [https://www.imghippo.com/](https://www.imghippo.com/)
2. Navigate to API Keys at [https://www.imghippo.com/settings?tab=api-keys](https://www.imghippo.com/settings?tab=api-keys)
3. Complete the API access form (5 steps):
   - **Step 1:** Select Website/Web Application
   - **Step 2:** Select Less than 1,000
   - **Step 3:** Select Image upload and sharing
   - **Step 4:** Skip (optional)
   - **Step 5:** Select Yes, I agree
4. Copy the generated API key, paste it in the field below, and click **Test Key**
5. If it works, click **Save Settings**. If it fails, retry steps or try a different account.
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
            if st.button("Test Key", width="stretch", key="btn_test_imgbb", disabled=not inp_imgbb_key):
                with st.spinner("Testing Imghippo API..."):
                    try:
                        import requests  # type: ignore
                        _test_path = Path(__file__).parent / "TESTPRODUCT.png"
                        if _test_path.exists():
                            _raw = _test_path.read_bytes()
                        else:
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
                            st.toast("Imghippo key verified!", icon="🖼️")
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
        "Click **Setup Tables** to create the schema automatically. "
        "If a cloud database goes offline, all writes fall back to local SQLite automatically. "
        "Use **Sync Local → Cloud** below to push your local data back up once the cloud is reachable again."
    )

    # ── Offline fallback + sync notice ──────────
    _cfg_now = st.session_state.cfg
    _cloud_configured = bool(
        _cfg_now.get("neon_connection_string") or
        (_cfg_now.get("supabase_url") and (_cfg_now.get("supabase_service_role_key") or _cfg_now.get("supabase_key")))
    )
    if _cloud_configured:
        _sync_col1, _sync_col2 = st.columns([3, 1])
        with _sync_col1:
            st.info(
                "**Cloud database configured.** Writes go to both your cloud database and local SQLite simultaneously. "
                "If your cloud database is temporarily unreachable, writes continue to local SQLite automatically. "
                "Use **Sync Local → Cloud** to push any locally-saved data up to the cloud."
            )
        with _sync_col2:
            st.markdown("<div style='margin-top:14px;'></div>", unsafe_allow_html=True)
            if st.button("Sync Local → Cloud", width="stretch", key="btn_sync_sqlite"):
                with st.spinner("Syncing local SQLite data to cloud…"):
                    _synced, _sync_errs = sync_sqlite_to_cloud(st.session_state.cfg)
                if _sync_errs:
                    st.warning(f"Synced {_synced} rows with issues: " + "; ".join(_sync_errs))
                else:
                    st.success(f"Synced {_synced} rows to cloud successfully.")

    db_tab_sb, db_tab_neon = st.tabs(["Supabase", "Neon"])

    with db_tab_sb:
        with st.expander("Where do I find my Supabase credentials?", expanded=False):
            st.markdown("""
1. Open [supabase.com](https://supabase.com) and select your project.
2. Go to **Settings → API** in the left sidebar.
3. Copy the **Project URL** (e.g. `https://xxxx.supabase.co`) → paste into **Project URL** below.
4. Copy the **Anon key** (starts with `eyJ…`) → paste into **Anon Key**.
5. Copy the **Service role key** (starts with `eyJ…`) → paste into **Service Role Key**. Keep this secret!
6. For **Personal Access Token**: go to **supabase.com → Account → Access Tokens** → click **Generate new token** → paste into **Personal Access Token**.
            """)

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
                width="stretch",
                key="btn_test_sb",
                disabled=not (inp_sb_url and _test_key),
            ):
                with st.spinner("Connecting to Supabase..."):
                    try:
                        from supabase import create_client  # type: ignore
                        client = create_client(inp_sb_url.strip(), _test_key)
                        client.table("inventory").select("id").limit(1).execute()
                        st.toast("Supabase connection success!", icon="☁️")
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
                width="stretch",
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
                            st.toast("Supabase tables ready!", icon="📦")
                            st.success(f"Tables created successfully.")
                        else:
                            st.warning(f"{_ok} OK, {len(_fail)} failed:")
                            for _f in _fail:
                                st.caption(_f)

    with db_tab_neon:
        with st.expander("Where do I find the Neon connection string?", expanded=False):
            st.markdown("""
1. Open your **Neon Console** and select your project.
2. Click **Dashboard** in the left sidebar.
3. Click the **Connect** button in your dashboard, then press **Copy** next to the connection string and paste it in the field below — you're done!
4. Under **Connection string**, make sure the dropdown says **psql** or **postgresql**.
5. Copy the string — it looks like:
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
                width="stretch",
                key="btn_test_neon",
                disabled=not _neon_is_valid_dsn,
            ):
                try:
                    import psycopg2  # type: ignore
                except ImportError:
                    import subprocess, sys
                    with st.spinner("Installing psycopg2-binary…"):
                        subprocess.check_call(
                            [sys.executable, "-m", "pip", "install", "psycopg2-binary"],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                        )
                    import psycopg2  # type: ignore
                try:
                    with psycopg2.connect(_neon_val, connect_timeout=10) as conn:
                        pass
                    st.success("Connected to Neon successfully.")
                except Exception as exc:
                    st.error(f"Connection failed: {exc}")

        with col_neon_setup:
            if st.button(
                "Setup Tables",
                type="primary",
                width="stretch",
                key="btn_setup_neon",
                disabled=not _neon_is_valid_dsn,
            ):
                with st.spinner("Setting up Neon tables..."):
                    try:
                        import psycopg2  # type: ignore
                    except ImportError:
                        import subprocess, sys
                        with st.spinner("Installing psycopg2-binary…"):
                            subprocess.check_call(
                                [sys.executable, "-m", "pip", "install", "psycopg2-binary"],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                            )
                        import psycopg2  # type: ignore
                    try:
                        _run_sql = st.session_state.get("neon_sql_editor", SETUP_SQL)
                        with psycopg2.connect(_neon_val, connect_timeout=10) as conn:
                            with conn.cursor() as cur:
                                cur.execute(_run_sql)
                            conn.commit()
                        st.toast("Neon tables ready!", icon="📦")
                        st.success("Tables created successfully (or already exist).")
                    except Exception as exc:
                        st.error(f"Setup failed: {exc}")

    # ── Save Settings ───────────────────────────
    st.divider()

    if st.button("Save Settings", type="primary", width="stretch"):
        # Preserve products list and email template when saving settings
        existing_products = cfg.get("products", [])
        new_cfg = {
            "from_name":                inp_from_name.strip(),
            "subject":                  inp_subject.strip(),
            "smtp_email":               inp_smtp_email.strip(),
            "smtp_password":            re.sub(r"\s+", "", inp_smtp_pass.strip()),
            "freeimage_api_key":         inp_freeimage_key.strip(),
            "imghippo_api_key":         inp_imgbb_key.strip(),
            "supabase_url":             inp_sb_url.strip(),
            "supabase_pat":             inp_sb_pat.strip(),
            "supabase_key":             inp_sb_anon.strip(),
            "supabase_publishable_key": inp_sb_publishable.strip(),
            "supabase_service_role_key": inp_sb_service.strip(),
            "supabase_db_password":     cfg.get("supabase_db_password", ""),
            "neon_connection_string":   inp_neon.strip(),
            "email_html_template":      cfg.get("email_html_template", ""),
            "products":                 existing_products,
        }
        save_config(new_cfg)
        st.session_state.cfg = new_cfg
        cfg = new_cfg
        st.success("Settings saved.")




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

    # Build catalog lookup once — used for image-match warnings and inventory deduction
    # Load from cloud/SQLite so deductions work even when cfg["products"] is stale
    _catalog_products = load_products_for_catalog(cfg)
    _catalog_name_lower: set[str] = {
        str(p.get("item_name", "")).lower().strip()
        for p in _catalog_products if p.get("item_name")
    }
    _name_to_sku: dict[str, str] = {
        str(p.get("item_name", "")).lower().strip(): str(p.get("sku", ""))
        for p in _catalog_products if p.get("sku") and p.get("item_name")
    }

    def _unmatched_products(raw_products: str) -> list[str]:
        """Return product names that have no fuzzy match in the catalog."""
        if not _catalog_name_lower:
            return []
        unmatched = []
        for pname in split_products(raw_products):
            pl = pname.lower()
            if not any(pl in cn or cn in pl for cn in _catalog_name_lower):
                unmatched.append(pname)
        return unmatched

    # ── Entry tabs ──────────────────────────────

    tab_single, tab_bulk, tab_csv, tab_excel, tab_template = st.tabs(
        ["Single Entry", "Bulk Entry", "CSV Import", "Excel Import", "Email Template"]
    )

    # ─ Single ───────────────────────────────────
    with tab_single:
        st.markdown("#### Add one order")
        c1, c2, c3 = st.columns(3)
        with c1:
            s_name  = st.text_input("Name *",    key="s_name",  placeholder="Jane Smith")
            s_email = st.text_input("Email *",   key="s_email", placeholder="jane@example.com")
        with c2:
            s_order = st.text_input("Order # *", key="s_order", placeholder="ORD-1001")
            s_sub   = st.number_input("Subtotal ($)", key="s_sub", min_value=0.0, step=0.01, format="%.2f")
            s_tax   = st.number_input("Tax ($)",      key="s_tax", min_value=0.0, step=0.01, format="%.2f")
        with c3:
            s_disc  = st.number_input("Discount ($)", key="s_disc", min_value=0.0, step=0.01, format="%.2f")
            s_ship  = st.number_input("Shipping ($)", key="s_ship", min_value=0.0, step=0.01, format="%.2f")
            s_cost  = st.number_input("Total Cost ($) *", key="s_cost", min_value=0.0, step=0.01, format="%.2f")
            if s_cost == 0 and s_sub > 0:
                st.caption(f"Suggested Total: ${s_sub + s_tax + s_ship - s_disc:.2f}")

        s_prods = st.text_area(
            "Products *", key="s_prods", height=108,
            placeholder="Blue T-Shirt\nBlack Jeans\nRunning Shoes",
            help="One product per line, or separate with | or ;",
        )

        if s_prods and _catalog_name_lower:
            _s_unmatched = _unmatched_products(s_prods)
            if _s_unmatched:
                st.warning(
                    f"No catalog match for: **{', '.join(_s_unmatched)}** — "
                    "product image(s) won't appear in the email. "
                    "Check spelling or add the product in the Products page."
                )

        if st.button("Add to Queue", key="single_add", type="primary"):
            if not s_name.strip() or not s_email.strip() or not s_order.strip() or not s_prods.strip() or s_cost <= 0:
                st.error("All fields marked with * are required.")
            else:
                with st.spinner("Adding to queue..."):
                    if add_to_queue(s_name, s_email, s_order, s_prods, s_sub, s_tax, s_ship, s_cost, s_disc):
                        st.toast(f"Added {s_name} to queue.", icon="👤")
                        st.success(f"Added {s_name} to the queue.")
                        time.sleep(0.5)
                        st.rerun()

    # ─ Bulk ─────────────────────────────────────
    with tab_bulk:
        st.markdown("#### Enter multiple orders")
        st.caption("Type directly in the table. Use the + icon to add rows. Separate multiple products with |")

        _BULK_BASE = pd.DataFrame({
            "Name":       pd.Series([], dtype=str),
            "Email":      pd.Series([], dtype=str),
            "Order #":    pd.Series([], dtype=str),
            "Products":   pd.Series([], dtype=str),
            "Subtotal":   pd.Series([], dtype=float),
            "Discount":   pd.Series([], dtype=float),
            "Tax":        pd.Series([], dtype=float),
            "Shipping":   pd.Series([], dtype=float),
            "Total Cost": pd.Series([], dtype=float),
        })

        edited = st.data_editor(
            _BULK_BASE,
            num_rows="dynamic",
            width="stretch",
            key="bulk_editor",
            column_config={
                "Name":     st.column_config.TextColumn(width="medium"),
                "Email":    st.column_config.TextColumn(width="large"),
                "Order #":  st.column_config.TextColumn(width="small"),
                "Products": st.column_config.TextColumn(
                    width="large",
                    help="Separate multiple products with |",
                ),
                "Total Cost": st.column_config.NumberColumn(width="small", format="$%.2f"),
            },
        )

        # Warn about unmatched products across all rows
        if _catalog_name_lower:
            _bulk_all_prods: list[str] = []
            for _, _brow in edited.iterrows():
                _bpr = str(_brow.get("Products", "")).strip()
                if _bpr and _bpr not in ("nan", ""):
                    _bulk_all_prods.extend(split_products(_bpr))
            _bulk_unmatched = sorted({
                p for p in _bulk_all_prods
                if p and not any(p.lower() in cn or cn in p.lower() for cn in _catalog_name_lower)
            })
            if _bulk_unmatched:
                st.warning(
                    f"No catalog match for: **{', '.join(_bulk_unmatched)}** — "
                    "product image(s) won't appear in emails. "
                    "Check spelling or add them in the Products page."
                )

        col_add, col_clear = st.columns(2)
        with col_add:
            if st.button("Add All to Queue", type="primary", width="stretch", key="bulk_add"):
                added = 0
                for _, row in edited.iterrows():
                    nm = str(row.get("Name",     "")).strip()
                    em = str(row.get("Email",    "")).strip()
                    on = str(row.get("Order #",  "")).strip()
                    pr = str(row.get("Products", "")).strip()
                    sb = float(row.get("Subtotal", 0.0) or 0.0)
                    ds = float(row.get("Discount", 0.0) or 0.0)
                    tx = float(row.get("Tax", 0.0) or 0.0)
                    sh = float(row.get("Shipping", 0.0) or 0.0)
                    co = float(row.get("Total Cost", 0.0) or 0.0)
                    
                    if not nm or nm == "nan" or not em or em == "nan" or not pr or pr == "nan" or co <= 0:
                        continue
                    if add_to_queue(nm, em, on, pr, sb, tx, sh, co, ds):
                        added += 1
                if added:
                    st.toast(f"Added {added} orders to queue.", icon="📋")
                    st.success(f"Added {added} order(s) to the queue.")
                    if "bulk_editor" in st.session_state:
                        del st.session_state["bulk_editor"]
                    time.sleep(0.5)
                    st.rerun()
                else:
                    st.warning("No valid rows found. Make sure Name and Email are filled in.")

        with col_clear:
            if st.button("Clear Table", width="stretch", key="bulk_clear"):
                if "bulk_editor" in st.session_state:
                    del st.session_state["bulk_editor"]
                st.rerun()

    # ─ Excel ────────────────────────────────────
    with tab_excel:
        st.markdown("#### Import from VEI Checkout Excel File")
        st.caption(
            "Upload an `.xlsx` file from the VEI Checkout system. "
            "It must contain 'Sales transactions' and 'Sales transaction items' sheets."
        )

        xl_file = st.file_uploader("Choose an Excel file", type=["xlsx"], key="excel_upload")

        if st.button("Import Excel", type="primary", key="btn_xl_import"):
            if not xl_file:
                st.warning("Upload an Excel file first.")
            else:
                with st.spinner("Linking transactions and products..."):
                    rows, warns = parse_excel_file(xl_file.read())
                    for w in warns:
                        st.warning(w)
                    if rows:
                        st.session_state.queue.extend(rows)
                        st.toast(f"Imported {len(rows)} orders.", icon="📊")
                        st.success(f"Imported {len(rows)} orders from Excel.")
                        time.sleep(0.5)
                        st.rerun()
                    else:
                        st.error("No valid orders found in the Excel file.")
    # ─ CSV ──────────────────────────────────────
    with tab_csv:
        st.markdown("#### Import from a CSV or TSV file")
        st.caption(
            "Required columns: **Name**, **Email**, **Order #**, **Products**, **Subtotal**, **Tax**, **Shipping**, **Total**. "
            "Column names are flexible — most variations are recognised automatically."
        )

        uploaded = st.file_uploader(
            "Choose a CSV or TSV file",
            type=["csv", "tsv", "txt"],
            key="csv_upload",
        )

        if st.button("Import", type="primary", key="csv_import"):
            if not uploaded:
                st.warning("Upload a file first.")
                st.stop()

            raw = uploaded.read().decode("utf-8", errors="replace")
            rows, warns = parse_csv_text(raw)
            for w in warns:
                st.warning(w)
            if rows:
                with st.spinner("Importing orders..."):
                    st.session_state.queue.extend(rows)
                    st.toast(f"Imported {len(rows)} orders.", icon="📥")
                    st.success(f"Imported {len(rows)} orders into the queue.")
                    time.sleep(0.5)
                    st.rerun()

    # ─ Email Template ───────────────────────────
    with tab_template:
        st.markdown("#### Customize your email layout")
        st.caption(
            "Write or paste HTML below. Use the variables listed to inject order data. "
            "Saved to config.json — persists across restarts."
        )

        _tpl_vars_md = """
| Variable | What it inserts |
|---|---|
| `{{name}}` | Customer's name |
| `{{order_number}}` | Order number |
| `{{from_name}}` | Your VEI firm name |
| `{{items_html}}` | Ready-made HTML rows for each ordered product (with images when available) |
| `{{subtotal}}` | Subtotal amount ($) |
| `{{tax}}` | Tax amount ($) |
| `{{discount}}` | Discount amount ($) |
| `{{shipping}}` | Shipping amount ($) |
| `{{total_cost}}` | Total order cost ($) |
"""
        with st.expander("Available template variables", expanded=True):
            st.markdown(_tpl_vars_md)

        _ai_prompt = """\
You are building an HTML email template for an order confirmation email.
Use ONLY these variables (double curly braces, exactly as shown):
  {{name}}         — customer's name
  {{order_number}} — order number
  {{from_name}}    — VEI firm name
  {{items_html}}   — pre-built HTML <tr> rows listing the ordered products (with product images when available). Wrap this inside a <table cellpadding="0" cellspacing="0" style="width:100%;">…</table>.
  {{subtotal}}     — subtotal amount ($)
  {{discount}}     — discount amount ($)
  {{tax}}          — tax amount ($)
  {{shipping}}     — shipping amount ($)
  {{total_cost}}   — total order cost ($)

Requirements:
- Return a COMPLETE HTML document (<!DOCTYPE html> … </html>)
- Email-safe: inline styles only, no external CSS or JS, table-based layout
- Mobile-friendly: max content width 600 px, readable on small screens
- Must include all variables where appropriate

Example default HTML template for inspiration:
--------------------------------------------
""" + _DEFAULT_EMAIL_TEMPLATE + """
--------------------------------------------

Design brief: [describe your style here — e.g. "clean and minimal, brand color #4F46E5, sans-serif font, white background, dark header bar, soft rounded corners"]
"""
        with st.expander("AI prompt — copy this into any AI (ChatGPT, Claude, or any LLM) to generate a template"):
            st.code(_ai_prompt, language=None)
            st.caption("Replace the design brief at the bottom, paste into your AI, then copy the returned HTML back here.")

        _current_tpl = cfg.get("email_html_template", "").strip()
        _editor_val  = _current_tpl if _current_tpl else _DEFAULT_EMAIL_TEMPLATE

        _tpl_input = st.text_area(
            "HTML template",
            value=_editor_val,
            height=380,
            key="email_tpl_editor",
            label_visibility="collapsed",
            help="Use {{name}}, {{order_number}}, {{from_name}}, {{items_html}}, {{subtotal}}, {{discount}}, {{tax}}, {{shipping}}, {{total_cost}} as placeholders.",
        )

        _tpl_c1, _tpl_c2, _tpl_c3 = st.columns(3)
        with _tpl_c1:
            if st.button("Save Template", type="primary", width="stretch", key="btn_save_tpl"):
                with st.spinner("Saving template..."):
                    cfg["email_html_template"] = _tpl_input.strip()
                    save_config(cfg)
                    st.session_state.cfg = cfg
                    st.toast("Template saved.", icon="💾")
                    st.success("Template saved.")
        with _tpl_c2:
            if st.button("Reset to Default", width="stretch", key="btn_reset_tpl"):
                cfg["email_html_template"] = ""
                save_config(cfg)
                st.session_state.cfg = cfg
                st.session_state.pop("_tpl_preview_html", None)
                st.success("Reset to built-in template.")
                st.rerun()
        with _tpl_c3:
            if st.button("Preview", width="stretch", key="btn_preview_tpl"):
                _preview_order = {
                    "name": "Jane Smith",
                    "order_number": "ORD-1001",
                    "products": "Blue T-Shirt | Black Jeans",
                }
                st.session_state["_tpl_preview_html"] = build_html(
                    _preview_order,
                    cfg.get("from_name") or "Your VEI Firm",
                    template=_tpl_input.strip() or None,
                )

        # Render preview full-width below the buttons (persists across reruns)
        if "_tpl_preview_html" in st.session_state:
            st.markdown("---")
            st.markdown("**Email preview** — sample order: Jane Smith · ORD-1001 · Blue T-Shirt, Black Jeans")
            st.components.v1.html(st.session_state["_tpl_preview_html"], height=800, scrolling=True)

    # ── Queue ───────────────────────────────────

    st.divider()
    queue = st.session_state.queue

    # Build product image lookup for the queue preview and email sending
    _products_lookup: dict[str, str] = {
        p["item_name"]: p["image_url"]
        for p in _catalog_products
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
                with st.spinner("Clearing queue..."):
                    st.session_state.queue = []
                    st.toast("Queue cleared.", icon="🧹")
                    time.sleep(0.5)
                    st.rerun()

        _cat_names = [p["item_name"] for p in _catalog_products]
        _cat_names_lower = [n.lower().strip() for n in _cat_names]

        for i, order in enumerate(queue):
            prods    = split_products(order.get("products", ""))
            
            # Find unmatched
            unmatched = []
            for p in prods:
                pl = p.lower().strip()
                if not any(pl in cn or cn in pl for cn in _cat_names_lower):
                    unmatched.append(p)
            
            prod_str = " | ".join(prods) if prods else "—"
            row_l, row_r = st.columns([9, 1], vertical_alignment="center")
            with row_l:
                _color = "#ef4444" if unmatched else "#ffffff"
                st.markdown(
                    f"**#{order['order_number']}**  —  {order['name']}  "
                    f"<span style='color:#888;font-size:13px;'>{order['email']}</span>  \n"
                    f"<small style='color:{_color};'>{prod_str}</small>",
                    unsafe_allow_html=True,
                )
                if unmatched:
                    st.caption(f"⚠️ Unmatched: {', '.join(unmatched)}")
            with row_r:
                if st.button("Delete", key=f"del_{i}", width="stretch"):
                    with st.spinner("Deleting..."):
                        st.session_state.queue.pop(i)
                        st.toast("Order removed.", icon="🗑️")
                        time.sleep(0.5)
                        st.rerun()
            st.divider()

        st.divider()

        ready = not missing_cfg
        if not ready:
            st.warning("Complete your settings before sending.")

        if st.button(
            "Send All Emails",
            type="primary",
            width="stretch",
            disabled=not ready,
            key="send_all",
        ):
            total         = len(queue)
            subject_tmpl  = cfg.get("subject", "Your Order Confirmation")
            from_name     = cfg["from_name"]
            smtp_email    = cfg["smtp_email"]
            smtp_password = cfg["smtp_password"]

            # Capture pre-send inventory snapshot for impact chart
            _presend_inv_df = load_inventory_preferring_cloud(cfg)
            _presend_stock: dict[str, int] = {}
            if not _presend_inv_df.empty and "sku" in _presend_inv_df.columns and "stock_left" in _presend_inv_df.columns:
                for _, _ps_row in _presend_inv_df.iterrows():
                    _presend_stock[str(_ps_row["sku"])] = int(_ps_row.get("stock_left", 0))

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
                msg.attach(MIMEText(
                    build_html(order, from_name, _products_lookup, cfg.get("email_html_template")),
                    "html",
                ))

                try:
                    server.send_message(msg)
                    status = "Sent"
                    sent_n += 1
                    # Log the successfully sent email to the database
                    save_outbound_log(order, cfg)
                except Exception as exc:
                    status = f"Failed: {str(exc)[:80]}"
                    failed_n += 1

                results.append({
                    "#":idx + 1,
                    "Name":order["name"],
                    "Email":order["email"],
                    "Order #":order["order_number"],
                    "Status":status,
                })
                # Update session state for the persistent log
                st.session_state.send_log = results
                log_ph.dataframe(
                    pd.DataFrame(results),
                    width="stretch",
                    hide_index=True,
                )
                time.sleep(0.25)

            server.quit()
            prog.progress(1.0, text="Done")

            # ── Deduct inventory for every successfully sent order ──────
            _has_sb_send  = bool(cfg.get("supabase_url","").strip() and (cfg.get("supabase_service_role_key") or cfg.get("supabase_key","")).strip())
            _has_neon_send = bool(cfg.get("neon_connection_string","").strip())
            _deductions: dict[str, int] = {}
            for _si, _sorder in enumerate(queue):
                if results[_si]["Status"] == "Sent":
                    for _spname in split_products(_sorder.get("products", "")):
                        _spl = _spname.lower().strip()
                        _matched_sku = _name_to_sku.get(_spl)
                        if _matched_sku:
                            _deductions[_matched_sku] = _deductions.get(_matched_sku, 0) + 1
            if _deductions:
                for _dsku, _dqty in _deductions.items():
                    adjust_inventory_sqlite(_dsku, -_dqty)
                    if _has_neon_send:  adjust_inventory_neon(_dsku, -_dqty, cfg)
                    if _has_sb_send:    adjust_inventory_supabase(_dsku, -_dqty, cfg)
                _clear_data_caches()

            # Persist deduction data for impact chart (survives st.rerun)
            st.session_state["_last_deductions"]   = _deductions
            st.session_state["_presend_stock"]     = _presend_stock
            st.session_state["_sku_name_map_send"] = {
                str(p.get("sku", "")): str(p.get("item_name", ""))
                for p in _catalog_products if p.get("sku")
            }

            if failed_n == 0:
                _inv_note = f" · Deducted stock for {sum(_deductions.values())} item(s)" if _deductions else ""
                st.success(f"All {sent_n} emails sent successfully.{_inv_note}")
            else:
                st.warning(f"{sent_n} sent, {failed_n} failed. See the results table above.")

            st.session_state.queue    = []
            st.toast("All emails sent!", icon="🚀")
            time.sleep(1)
            st.rerun()

    # ── Last send log ────────────────────────────

    if st.session_state.send_log and not st.session_state.queue:
        st.divider()
        st.subheader("Last Send Results")
        st.dataframe(
            pd.DataFrame(st.session_state.send_log),
            width="stretch",
            hide_index=True,
        )

        # ── Inventory Impact Chart ────────────────────────────────────
        _ld = st.session_state.get("_last_deductions", {})
        if _ld:
            st.divider()
            st.subheader("Inventory Impact")
            _ps  = st.session_state.get("_presend_stock", {})
            _snm = st.session_state.get("_sku_name_map_send", {})
            _impact_rows = []
            for _d_sku, _d_qty in _ld.items():
                _d_name   = _snm.get(_d_sku, _d_sku)
                _d_before = _ps.get(_d_sku, 0)
                _d_after  = _d_before - _d_qty
                _impact_rows.append({
                    "Product":   _d_name,
                    "SKU":       _d_sku,
                    "Deducted":  _d_qty,
                    "Before":    _d_before,
                    "After":     _d_after,
                })
            _impact_df = pd.DataFrame(_impact_rows)
            st.dataframe(_impact_df, use_container_width=True, hide_index=True)
            _chart_df = _impact_df.set_index("Product")[["Before", "After"]]
            st.bar_chart(_chart_df)

        if st.button("Clear Log", key="clear_log"):
            st.session_state.send_log = []
            for _k in ("_last_deductions", "_presend_stock", "_sku_name_map_send"):
                st.session_state.pop(_k, None)
            st.rerun()

"""
MERIT — Mass Email & Inventory Tool for Virtual Enterprise (VEI) firms
Gmail SMTP · Freeimage.host / Imghippo image hosting · Supabase database
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
    background-color: #3f3f46 !important; /* Zinc-700 */
    border-color: #3f3f46 !important;
    color: #ffffff !important;
}
.stButton > button[kind="secondary"]:hover {
    background-color: #52525b !important; /* Zinc-600 */
    border-color: #52525b !important;
    color: #ffffff !important;
    transform: translateY(-1.5px);
    box-shadow: 0 4px 12px rgba(0, 0, 0, 0.1) !important;
}
.stButton > button[kind="secondary"]:focus:not(:active) {
    background-color: #3f3f46 !important;
    border-color: #3f3f46 !important;
    color: #ffffff !important;
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
            original_stock INTEGER NOT NULL DEFAULT 0,
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
    status         TEXT           NOT NULL DEFAULT 'In stock',
    image_url      TEXT           NOT NULL DEFAULT 'N/A',
    original_stock INTEGER        NOT NULL DEFAULT 0,
    created_at     TIMESTAMPTZ    NOT NULL DEFAULT NOW(),
    CONSTRAINT inventory_sku_unique UNIQUE (sku)
);

-- Migrations for existing users (Original Stock)
DO $$ 
BEGIN 
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='inventory' AND column_name='original_stock') THEN
    ALTER TABLE inventory ADD COLUMN original_stock INTEGER NOT NULL DEFAULT 0;
  END IF;
END $$;

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


_SECRETS_CREDENTIAL_KEYS = [
    "supabase_connection_string",
    "supabase_db_password",
    "smtp_email",
    "smtp_password",
    "from_name",
    "subject",
    "freeimage_api_key",
    "imghippo_api_key",
    "privacy_acknowledged",
]


def load_config() -> dict:
    """Load config from config.json, then overlay credentials from st.secrets[merit].

    st.secrets persists across Streamlit Cloud reboots; config.json is used for
    local dev and for non-credential data (products list, email template).
    """
    cfg: dict = {}
    # 1. Load local config.json (products, email template, and local dev credentials)
    try:
        if CONFIG_FILE.exists():
            cfg = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except Exception:
        pass
    # 2. Overlay credentials from st.secrets (Streamlit Cloud — survives reboots)
    #    Secrets take precedence so that pasting a new TOML always wins.
    try:
        if hasattr(st, "secrets") and "merit" in st.secrets:
            for _k in _SECRETS_CREDENTIAL_KEYS:
                _v = st.secrets["merit"].get(_k, "")
                if _v:
                    cfg[_k] = str(_v)
    except Exception:
        pass
    return cfg


def save_config(data: dict):
    _tmp = CONFIG_FILE.with_suffix(".tmp")
    _tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    _tmp.replace(CONFIG_FILE)


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

def _psycopg2_connect(conn_str: str, connect_timeout: int = 10):
    """Connect via psycopg2, falling back to IPv4 if IPv6 fails.

    Streamlit Cloud (and many school networks) cannot route IPv6 even when DNS
    returns an AAAA record first. We detect the error and retry by resolving the
    host to its IPv4 address, then reconnecting using libpq keyword=value format
    so that both `host` (for SSL verification) and `hostaddr` (the actual IP to
    dial) are set correctly. Appending hostaddr as a URL query parameter does NOT
    work reliably — psycopg2 only honours it in the keyword=value DSN form.
    """
    import psycopg2  # type: ignore

    try:
        return psycopg2.connect(conn_str, connect_timeout=connect_timeout)
    except Exception as _e:
        _msg = str(_e)
        if "assign requested address" not in _msg and "Network is unreachable" not in _msg:
            raise
        # IPv6 unreachable — resolve to IPv4 and reconnect via keyword DSN
        try:
            import socket
            from urllib.parse import urlparse
            _p    = urlparse(conn_str)
            _host = _p.hostname or ""
            _ipv4 = socket.getaddrinfo(_host, None, socket.AF_INET)[0][4][0]
            _dsn  = (
                f"host={_host} "
                f"hostaddr={_ipv4} "
                f"port={_p.port or 5432} "
                f"dbname={(_p.path or '/postgres').lstrip('/')} "
                f"user={_p.username or 'postgres'} "
                f"password={_p.password or ''} "
                f"sslmode=require"
            )
            return psycopg2.connect(_dsn, connect_timeout=connect_timeout)
        except Exception:
            pass
        raise



def _get_effective_supabase_conn_str(cfg: dict) -> str:
    """Return the Supabase connection string with the stored password substituted in."""
    conn_str = cfg.get("supabase_connection_string", "").strip()
    password  = cfg.get("supabase_db_password", "").strip()
    if not conn_str:
        return ""
    if "[YOUR-PASSWORD]" in conn_str and password:
        return conn_str.replace("[YOUR-PASSWORD]", password)
    return conn_str


def _get_supabase_conn(cfg: dict):
    """Open a psycopg2 connection to Supabase. Returns None if not configured."""
    conn_str = _get_effective_supabase_conn_str(cfg)
    if not conn_str:
        return None
    try:
        return _psycopg2_connect(conn_str)
    except Exception:
        return None


def _has_supabase(cfg: dict) -> bool:
    """True if a working Supabase connection string is present."""
    return bool(_get_effective_supabase_conn_str(cfg))


def _get_supabase_project_url(cfg: dict) -> str:
    """Derive the Supabase project URL from the connection string (for API Endpoints)."""
    import re as _re
    conn_str = _get_effective_supabase_conn_str(cfg)
    if conn_str:
        m = _re.search(r'@db\.([^.]+)\.supabase\.co', conn_str)
        if m:
            return f"https://{m.group(1)}.supabase.co"
    return cfg.get("supabase_url", "").strip()   # fallback: old-style config


def _has_any_db(cfg: dict) -> bool:
    return True  # SQLite is always available; Supabase is optional


def save_product_to_db(product: dict, cfg: dict) -> tuple[bool, str]:
    """Upsert one product into ALL configured databases. Always saves to SQLite."""
    _stock = int(product.get("stock_left", 0))
    _orig  = int(product.get("original_stock") if product.get("original_stock") is not None else _stock)
    _status = str(product.get("status") or (
        "Backordered" if _stock < 0 else ("Out of stock" if _stock == 0 else ("Low stock" if _stock <= 10 else "In stock"))
    ))
    row = {
        "sku":        product["sku"],
        "item_name":  product["item_name"],
        "category":   product.get("category", ""),
        "price":      product.get("price", 0.0),
        "stock_left": _stock,
        "original_stock": _orig,
        "status":     _status,
        "image_url":  product.get("image_url", "N/A"),
    }
    results = []

    # ── SQLite (always) ────────────────────────────────────────────
    try:
        conn = _get_sqlite_conn()
        conn.execute("""
            INSERT INTO inventory (sku, item_name, category, price, stock_left, original_stock, status, image_url)
            VALUES (:sku, :item_name, :category, :price, :stock_left, :original_stock, :status, :image_url)
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

    # ── Supabase (psycopg2 direct connection) ───────────────────────
    conn_sb = _get_supabase_conn(cfg)
    if conn_sb is not None:
        try:
            with conn_sb:
                with conn_sb.cursor() as cur:
                    # inventory table — stock tracking + all catalog fields
                    cur.execute("""
                        INSERT INTO inventory (sku,item_name,category,price,stock_left,original_stock,status,image_url)
                        VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                        ON CONFLICT(sku) DO UPDATE SET
                            item_name=EXCLUDED.item_name, category=EXCLUDED.category,
                            price=EXCLUDED.price, image_url=EXCLUDED.image_url
                    """, (row["sku"],row["item_name"],row["category"],row["price"],
                          row["stock_left"],row["original_stock"],row["status"],row["image_url"]))
                    # products table — clean catalog for external websites
                    cur.execute("""
                        INSERT INTO products (sku,name,category,price,image_url,active)
                        VALUES (%s,%s,%s,%s,%s,true)
                        ON CONFLICT(sku) DO UPDATE SET
                            name=EXCLUDED.name, category=EXCLUDED.category,
                            price=EXCLUDED.price, image_url=EXCLUDED.image_url, active=true
                    """, (row["sku"],row["item_name"],row["category"],row["price"],row["image_url"]))
            conn_sb.close()
            results.append("Supabase")
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

def set_original_stock_all_dbs(sku: str, stock: int, cfg: dict) -> tuple[bool, str]:
    """Set the original purchased stock level across all databases."""
    results = []
    # SQLite
    try:
        conn = _get_sqlite_conn()
        conn.execute("UPDATE inventory SET original_stock=? WHERE sku=?", (stock, sku))
        conn.commit()
        conn.close()
        results.append("SQLite")
    except Exception as exc: results.append(f"SQLite failed: {exc}")

    # Supabase
    conn_sb = _get_supabase_conn(cfg)
    if conn_sb is not None:
        try:
            with conn_sb:
                with conn_sb.cursor() as cur:
                    cur.execute("UPDATE inventory SET original_stock=%s WHERE sku=%s", (stock, sku))
            conn_sb.close()
            results.append("Supabase")
        except Exception as exc: results.append(f"Supabase failed: {exc}")

    return any("failed" not in r for r in results), " · ".join(results)


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
        if delta > 0:
            conn.execute("UPDATE inventory SET original_stock = original_stock + ? WHERE sku=?", (delta, sku))
        conn.commit()
        conn.close()
        return True, f"Stock → {new_stock} ({status})"
    except Exception as exc:
        return False, str(exc)

def adjust_inventory_supabase(sku: str, delta: int, cfg: dict) -> tuple[bool, str]:
    conn = _get_supabase_conn(cfg)
    if conn is None:
        return False, "Supabase not configured"
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute("SELECT stock_left FROM inventory WHERE sku=%s", (sku,))
                row = cur.fetchone()
                if row is None:
                    return False, "SKU not found in Supabase"
                new_stock = row[0] + delta
                status = "Backordered" if new_stock < 0 else ("Out of stock" if new_stock == 0 else ("Low stock" if new_stock <= 10 else "In stock"))
                cur.execute("UPDATE inventory SET stock_left=%s, status=%s WHERE sku=%s", (new_stock, status, sku))
                if delta > 0:
                    cur.execute("UPDATE inventory SET original_stock = original_stock + %s WHERE sku=%s", (delta, sku))
        conn.close()
        return True, f"Supabase stock → {new_stock}"
    except Exception as exc:
        return False, str(exc)


def delete_product_from_db(sku: str, cfg: dict) -> tuple[bool, str]:
    """Delete a product from ALL configured databases (SQLite, Supabase)."""
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

    # ── Supabase ─────────────────────────────────────────────────────
    conn_sb = _get_supabase_conn(cfg)
    if conn_sb is not None:
        try:
            with conn_sb:
                with conn_sb.cursor() as cur:
                    cur.execute("DELETE FROM inventory WHERE sku=%s", (sku,))
                    try:
                        cur.execute("DELETE FROM products WHERE sku=%s", (sku,))
                    except Exception:
                        pass
            conn_sb.close()
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

    # Supabase
    conn_sb = _get_supabase_conn(cfg)
    if conn_sb is not None:
        try:
            with conn_sb:
                with conn_sb.cursor() as cur:
                    cur.execute("UPDATE inventory SET stock_left=%s, status=%s WHERE sku=%s", (stock, status, sku))
            conn_sb.close()
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

    # ── Supabase ──────────────────────────────────────────────────────
    conn_sb = _get_supabase_conn(cfg)
    if conn_sb is not None:
        try:
            with conn_sb:
                with conn_sb.cursor() as cur:
                    for rec in records:
                        cur.execute("""
                            INSERT INTO inventory (sku,item_name,category,price,stock_left,status,image_url)
                            VALUES (%s,%s,%s,%s,%s,%s,%s)
                            ON CONFLICT(sku) DO UPDATE SET
                                item_name=EXCLUDED.item_name, category=EXCLUDED.category,
                                price=EXCLUDED.price, stock_left=EXCLUDED.stock_left,
                                status=EXCLUDED.status, image_url=EXCLUDED.image_url
                        """, (rec.get("sku"), rec.get("item_name"), rec.get("category"),
                              rec.get("price"), rec.get("stock_left"), rec.get("status"),
                              rec.get("image_url")))
            conn_sb.close()
            synced = max(synced, len(records))
        except Exception as exc:
            errors.append(f"Supabase sync failed: {exc}")

    return synced, errors


@st.cache_data(ttl=30, show_spinner=False)
def _fetch_inventory_supabase(conn_str: str) -> list | None:
    try:
        conn = _psycopg2_connect(conn_str)
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
    """Load inventory preferring Supabase > SQLite (results cached 30 s)."""
    _sb_cs = _get_effective_supabase_conn_str(cfg)
    if _sb_cs:
        rows = _fetch_inventory_supabase(_sb_cs)
        if rows:
            return pd.DataFrame(rows)

    rows = _fetch_inventory_sqlite_cached()
    if rows:
        return pd.DataFrame(rows)
    return load_inventory_from_sqlite()


def load_products_for_catalog(cfg: dict) -> list[dict]:
    """Load product list preferring Supabase > SQLite > config.json (cached 30 s)."""
    _sb_cs = _get_effective_supabase_conn_str(cfg)
    if _sb_cs:
        rows = _fetch_inventory_supabase(_sb_cs)
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

    # Supabase
    conn_sb = _get_supabase_conn(cfg)
    if conn_sb is not None:
        try:
            with conn_sb:
                with conn_sb.cursor() as cur:
                    cur.execute("""
                        INSERT INTO outbound_logs
                            (recipient_name,recipient_email,order_number,products_list,subtotal,tax,shipping,total_cost)
                        VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                    """, (row["name"],row["email"],row["order"],row["prods"],
                          row["sub"],row["tax"],row["ship"],row["cost"]))
            conn_sb.close()
        except Exception: pass


def load_outbound_logs(cfg: dict) -> pd.DataFrame:
    """Load outbound logs from Supabase or local SQLite."""
    _sb_cs = _get_effective_supabase_conn_str(cfg)
    if _sb_cs:
        try:
            conn = _psycopg2_connect(_sb_cs)
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
# Privacy agreement gate (one-time, persists via TOML)
# ─────────────────────────────────────────────

if not st.session_state.cfg.get("privacy_acknowledged"):
    st.title("Privacy & Data Agreement")
    st.markdown("""
Before using MERIT, please read and accept the following:

---

### How MERIT stores your data

MERIT is a self-hosted app that **you** deploy on your own Streamlit Cloud account.
When you enter credentials (Gmail App Password, Supabase connection string, image hosting API keys, etc.),
here is exactly where they go:

| Where your data is stored | Details |
|---|---|
| **Streamlit Secrets** | When you paste the Secrets TOML, your credentials are stored in **your** Streamlit project's encrypted secrets store — owned by you, on Streamlit's servers |
| **config.json** | A local file in your deployed app container. It exists only while the container is running and is wiped on restart (which is why Streamlit Secrets is recommended) |
| **Supabase** | Your product and inventory data lives in **your** Supabase project — you own that database |

### What MERIT does NOT do

- MERIT does **not** transmit your API keys, passwords, or credentials to any third party
- MERIT does **not** have a central server — there is no "MERIT cloud" that receives your data
- MERIT does **not** log, collect, or share your email addresses, customer data, or order information
- The only outgoing connections MERIT makes are: Gmail SMTP (to send emails you initiate), Supabase (your own database), and image hosting services (Freeimage.host or Imghippo, to upload product images)

### In plain English

Your credentials are stored on **Streamlit's servers** (in your own account's encrypted secrets) and in **your own Supabase database**. They are used only to run this app for you. No one else — including the MERIT developer — can see them.

---

By clicking **I Agree**, you confirm that you have read and understood the above.
    """)
    st.divider()
    if st.button("I Agree — Continue to MERIT", type="primary"):
        st.session_state.cfg["privacy_acknowledged"] = "1"
        save_config(st.session_state.cfg)
        st.rerun()
    st.stop()

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

    # Hide "Get Started" once the user has pasted their secrets TOML
    _secrets_active = False
    try:
        _secrets_active = hasattr(st, "secrets") and "merit" in st.secrets
    except Exception:
        pass
    _nav_pages = (
        ["Email Sender", "Products", "Inventory", "Settings", "API Endpoints"]
        if _secrets_active
        else ["Get Started", "Email Sender", "Products", "Inventory", "Settings", "API Endpoints"]
    )
    # Ensure current value is valid after hiding Get Started
    if "sidebar_page" not in st.session_state or st.session_state["sidebar_page"] not in _nav_pages:
        st.session_state["sidebar_page"] = _nav_pages[0]
    page = st.radio(
        "page",
        _nav_pages,
        key="sidebar_page",
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


_DEFAULT_CAMPAIGN_TEMPLATE = """\
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
              Write your campaign message here. You can use HTML to style it however you like.
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
    disc      = f"{float(order.get('discount', 0.0)):.2f}"
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


_ALIASES = {
    "name":         ["name", "customer_name", "billing_name", "shipping_name", "customer"],
    "email":        ["email", "customer_email", "e-mail"],
    "order_number": ["order_number", "order_no", "transaction_no", "transaction_id", "id"],
    "products":     ["products", "items", "item", "description", "ordered_items", "item_name"],
    "subtotal":     ["subtotal", "sub_total", "price_subtotal", "sub_total_amount"],
    "tax":          ["tax", "tax_amount", "taxes", "vat"],
    "shipping":     ["shipping", "shipping_cost", "freight", "delivery"],
    "discount":     ["discount", "discount_amount", "off", "promo_discount"],
    "total_cost":   ["total_cost", "total", "cost", "total_price", "amount", "price", "order_total"],
}


def _parse_money(val: any) -> float:
    """Cleans currency strings and converts to float."""
    if val is None or val == "": return 0.0
    s = str(val).replace("$", "").replace(",", "").replace("-", "").strip()
    try: return round(float(s), 2)
    except: return 0.0


def _norm(h: str) -> str:
    return h.strip().lower().replace(" ", "_").replace("-", "_").replace("#", "").replace(".", "_").replace("/", "_").replace("(", "").replace(")", "")


def parse_excel_file(file_bytes) -> tuple[list[dict], list[str]]:
    import pandas as pd
    try:
        import openpyxl # type: ignore
    except ImportError:
        return [], ["Excel engine 'openpyxl' missing. Please ensure it is in requirements.txt."]
    
    warns = []
    try:
        xl = pd.ExcelFile(io.BytesIO(file_bytes))
        sheets = xl.sheet_names
        tx_sheet = next((s for s in sheets if "transaction" in s.lower() and "item" not in s.lower()), None)
        item_sheet = next((s for s in sheets if "transaction" in s.lower() and "item" in s.lower()), None)
        
        if not tx_sheet or not item_sheet:
            return [], [f"Excel file missing required sheets. Found: {sheets}"]
        
        df_tx = pd.read_excel(xl, sheet_name=tx_sheet)
        df_items = pd.read_excel(xl, sheet_name=item_sheet)
        
        tx_items = {}
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
        df_tx.columns = [_norm(c) for c in df_tx.columns]
        for _, tx in df_tx.iterrows():
            t_no  = str(tx.get('transaction_no', '')).strip()
            email = str(tx.get('customer_email', '')).strip()
            name  = str(tx.get('billing_name', '')).strip() or str(tx.get('shipping_name', 'Customer')).strip()
            
            if not t_no or not email or not validate_email(email):
                continue
            
            items_list = " | ".join(tx_items.get(t_no, ["N/A"]))
            
            rows.append({
                "name":          name,
                "email":         email,
                "order_number":  t_no,
                "products":      items_list,
                "subtotal":      _parse_money(tx.get('subtotal', 0.0)),
                "discount":      _parse_money(tx.get('discount', 0.0)),
                "tax":           _parse_money(tx.get('tax', 0.0)),
                "shipping":      _parse_money(tx.get('shipping', 0.0)),
                "total_cost":    _parse_money(tx.get('total', 0.0)),
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
            "subtotal":      _parse_money(mapped.get("subtotal")),
            "discount":      _parse_money(mapped.get("discount")),
            "tax":           _parse_money(mapped.get("tax")),
            "shipping":      _parse_money(mapped.get("shipping")),
            "total_cost":    _parse_money(mapped.get("total_cost")),
        })
    if not rows:
        warns.append("No valid rows found.")
    return rows, warns


def parse_multi_csv(tx_text: str, items_text: str) -> tuple[list[dict], list[str]]:
    """Links transactions and items from two separate CSV strings."""
    warns = []
    try:
        t_text = tx_text.replace("\r\n", "\n").replace("\r", "\n").strip()
        t_reader = csv.DictReader(io.StringIO(t_text))
        t_headers = t_reader.fieldnames or []
        t_hmap = _map_headers(t_headers)
        
        i_text = items_text.replace("\r\n", "\n").replace("\r", "\n").strip()
        i_reader = list(csv.DictReader(io.StringIO(i_text)))
        i_headers = (csv.DictReader(io.StringIO(i_text))).fieldnames or []
        i_hmap = _map_headers(i_headers)
        
        tx_items = {}
        for row in i_reader:
            # Map headers for this specific row using items hmap
            m_item = {t: (row.get(r) or "").strip() for r, t in i_hmap.items()}
            t_no = m_item.get("order_number") or str(row.get('Transaction no') or '').strip()
            item = m_item.get("products") or str(row.get('Item name') or '').strip()
            
            _qty_raw = row.get('Quantity') or row.get('quantity') or 1
            try: _q = int(float(_qty_raw))
            except: _q = 1
            
            if t_no and item:
                if t_no not in tx_items: tx_items[t_no] = []
                tx_items[t_no].append(f"{item} x {_q}" if _q > 1 else item)
        
        rows = []
        for i, row in enumerate(t_reader, start=2):
            m = {t: (row.get(r) or "").strip() for r, t in t_hmap.items()}
            email = m.get("email")
            t_no  = m.get("order_number") or str(row.get('Transaction no') or '').strip()
            name  = m.get("name", "Customer")
            if not email or not validate_email(email) or not t_no: continue
            
            items_list = " | ".join(tx_items.get(t_no, ["N/A"]))
            rows.append({
                "name":          name,
                "email":         email,
                "order_number":  t_no,
                "products":      items_list,
                "subtotal":      _parse_money(m.get("subtotal")),
                "discount":      _parse_money(m.get("discount")),
                "tax":           _parse_money(m.get("tax")),
                "shipping":      _parse_money(m.get("shipping")),
                "total_cost":    _parse_money(m.get("total_cost")),
            })
        return rows, warns
    except Exception as e:
        return [], [f"Error linking multi-CSV: {e}"]


# ═════════════════════════════════════════════
# GET STARTED PAGE
# ═════════════════════════════════════════════

if page == "Get Started":
    cfg = st.session_state.cfg
    _gs_has_sb = _has_supabase(cfg)
    _gs_has_img = _has_image_host(cfg)
    _gs_has_smtp = bool(cfg.get("smtp_email") and cfg.get("smtp_password"))
    _gs_has_identity = bool(cfg.get("from_name") and cfg.get("subject"))
    _gs_has_secrets = False
    try:
        _gs_has_secrets = hasattr(st, "secrets") and "merit" in st.secrets
    except Exception:
        pass

    st.title("Get Started with MERIT")
    st.caption("MERIT is a product catalog + email order system. Follow the steps below to get fully set up.")

    # ── Step status indicators ────────────────────────────────────────
    _step1_ok = _gs_has_sb
    _step2_ok = _gs_has_img
    _step3_ok = _gs_has_smtp
    _step4_ok = _gs_has_identity
    _step5_ok = _gs_has_secrets

    st.markdown("### Setup Checklist")
    col1, col2, col3, col4, col5 = st.columns(5)
    with col1:
        if _step1_ok:
            st.success("Step 1 — Supabase Connected")
        else:
            st.error("Step 1 — Connect Supabase (required)")
    with col2:
        if _step2_ok:
            st.success("Step 2 — Image Hosting Ready")
        else:
            st.warning("Step 2 — Add Image Hosting Key")
    with col3:
        if _step3_ok:
            st.success("Step 3 — Email Configured")
        else:
            st.warning("Step 3 — Configure Email")
    with col4:
        if _step4_ok:
            st.success("Step 4 — Sender Identity Set")
        else:
            st.warning("Step 4 — Set Sender Identity")
    with col5:
        if _step5_ok:
            st.success("Step 5 — Secrets Saved (persists reboots)")
        else:
            st.warning("Step 5 — Save Secrets TOML (prevents settings loss)")

    st.divider()

    # ── Step 1: Supabase ──────────────────────────────────────────────
    with st.expander("Step 1 — Connect Supabase (REQUIRED)", expanded=not _step1_ok):
        st.markdown("""
Supabase is **required** for MERIT to work properly. It stores your products and inventory in the cloud
so that your data survives app reboots, and powers the **API Endpoints** page so your website auto-updates.

**Without Supabase:** products are only stored in a local SQLite file that gets wiped every time Streamlit restarts.

---

#### 1. Create your Supabase account
Go to [supabase.com](https://supabase.com) and sign up for a free account.

#### 2. Create a new project
Once logged in, click **New Project**. Fill in the form:

| Field | What to enter |
|---|---|
| **Organization** | Your personal org (already selected by default) |
| **Project name** | `merit` (or anything you like — it's just a label) |
| **Database password** | Choose a strong password — **write this down**, you'll need it later |
| **Region** | Pick the region closest to you (e.g. `East US`, `West EU`) |
| **Pricing plan** | **Free** — the free tier is more than enough for MERIT |

Click **Create new project** and wait ~60 seconds for it to provision.

#### 3. Get your connection string
Once the project dashboard loads:
1. Click the **Connect** button in the top-right corner of your project dashboard
2. In the dialog that opens, click the **Direct connection** tab
3. Copy the connection string — it looks like:
   `postgresql://postgres:[YOUR-PASSWORD]@db.xxxxxxxxxxxx.supabase.co:5432/postgres`

> **Tip:** Leave everything else at default. You do not need to change any Supabase project settings.

#### 4. Connect MERIT to Supabase
In MERIT, go to **Settings → Database** (left sidebar) and paste:
- The connection string into **Connection String**
- Your database password into **Database Password**

Then click **Setup Tables** — MERIT will create all required tables automatically.

Once connected, the Step 1 indicator above turns green.
        """)

    # ── Step 2: Image Hosting ─────────────────────────────────────────
    with st.expander("Step 2 — Set Up Image Hosting", expanded=not _step2_ok and _step1_ok):
        st.markdown("""
Product images need to be hosted online so they show up in emails and on your website.
MERIT supports two **free** image hosting services — pick one:

---

#### Option A — Freeimage.host (recommended)
1. Go to [freeimage.host](https://freeimage.host) → click **API** (top menu) → sign up or log in
2. After logging in, go back to the **API** page and copy your **API key**
3. In MERIT → **Settings → Image Hosting**, paste the key into **Freeimage.host API Key**

#### Option B — Imghippo
1. Go to [imghippo.com](https://imghippo.com) → sign up for a free account
2. After signing up, go directly to your API keys page: [imghippo.com/settings?tab=api-keys](https://www.imghippo.com/settings?tab=api-keys)
3. Complete the API access form (5 quick steps):
   - **Step 1:** Select *Website/Web Application*
   - **Step 2:** Select *Less than 1,000*
   - **Step 3:** Select *Image upload and sharing*
   - **Step 4:** Skip (optional)
   - **Step 5:** Select *Yes, I agree*
4. Copy the generated **API Version 1** key
5. In MERIT → **Settings → Image Hosting**, paste the key into **Imghippo API Key**

---

You only need **one** of the two keys. Once a key is saved, MERIT automatically uploads and
compresses product images whenever you add or edit a product.

Once a key is saved, the Step 2 indicator above turns green.
        """)

    # ── Step 3: Email ────────────────────────────────────────────────
    with st.expander("Step 3 — Configure Gmail SMTP", expanded=not _step3_ok and _step2_ok):
        st.markdown("""
MERIT sends order emails via your **VEI Google (Gmail) account**. To do this safely,
Google requires you to generate a special **App Password** instead of using your normal password.

#### How to set up:
1. Go to [myaccount.google.com](https://myaccount.google.com) and sign in
2. Click **Security** in the left sidebar
3. Under *How you sign in to Google*, confirm **2-Step Verification** is **On** — turn it on if not
4. Search for **App passwords** at the top of the page and click the result
5. Under *App name*, type `MERIT Email` then click **Create**
6. Google shows a **16-character password** (e.g. `abcd efgh ijkl mnop`) — copy it now
7. In MERIT → **Settings → Email**, fill in:
   - **Gmail Address**: your Gmail address (e.g. `yourname@gmail.com`)
   - **App Password**: the 16-character password — spaces are fine, MERIT strips them automatically

Fields auto-save as you type. Once both fields are filled, the Step 3 indicator above turns green.
        """)

    # ── Step 4: Sender Identity ───────────────────────────────────────
    with st.expander("Step 4 — Set Sender Identity", expanded=not _step4_ok and _step3_ok):
        st.markdown("""
Sender Identity controls **who the email appears to come from** in the recipient's inbox.
This is separate from the Gmail credentials — it's the display name and subject line your customers see.

#### How to set up:
1. In MERIT → **Settings → Email**, scroll to the **Sender Identity** section and fill in:
   - **From Name**: your VEI firm name exactly as it appears in VEI (e.g. `Acme VEI`)
   - **Default Subject Line**: `Your order is here` (or customise as you like)
     - You can use `{order_number}` in the subject to insert the customer's order number automatically
2. Fields auto-save as you type — no save button needed

> **Tip:** Ask your firm coordinator for the exact firm name if you're unsure.

Once both fields are filled, the Step 4 indicator above turns green.
        """)

    # ── Step 5: Streamlit Secrets ────────────────────────────────────
    with st.expander("Step 5 — Save Secrets TOML (prevents settings loss on reboot)", expanded=not _step5_ok and _step4_ok):
        st.markdown("""
**Why is this needed?**
Streamlit Cloud restarts your app container periodically. When it does, any files written to disk
(including `config.json`) are wiped. Your settings disappear.

**The fix:** Streamlit has a built-in **Secrets** store that persists across reboots. You paste
your credentials there once, and MERIT reads from it automatically on every startup.

#### How to save your secrets:
1. Go to **Settings → Secrets TOML** in MERIT and copy the generated TOML block
2. Click **Manage app** in the bottom-right corner of your Streamlit app
3. Click the **⋮ three-dot menu** → **Settings** → **Secrets**
4. Paste the TOML → click **Save**
5. Streamlit reboots the app — your settings persist forever

Once saved, the Step 5 indicator above turns green and **Get Started disappears from the sidebar**.
        """)

    st.divider()

    # ── Quick reference ───────────────────────────────────────────────
    st.subheader("What each page does")
    st.markdown("""
| Page | What it does |
|---|---|
| **Email Sender** | Upload a CSV of orders, match them to products, send bulk emails |
| **Products** | Add, edit, and delete products (syncs to Supabase automatically) |
| **Inventory** | View live stock levels, adjust stock manually |
| **Settings** | Configure email, Supabase, image hosting, and get your secrets TOML |
| **API Endpoints** | REST API docs + ready-to-paste code for your website (Bolt, Lovable, etc.) |
    """)

# ═════════════════════════════════════════════
# PRODUCTS PAGE
# ═════════════════════════════════════════════

elif page == "Products":
    cfg = st.session_state.cfg
    st.title("Products")

    # ── Status banners ──────────────────────────
    if not _has_image_host(cfg):
        st.warning(
            "No image hosting key set. Go to **Settings → Image Hosting** to add one. "
            "Free options: [freeimage.host](https://freeimage.host) or [imghippo.com](https://imghippo.com)."
        )
    _has_cloud_db = _has_supabase(cfg)
    if not _has_cloud_db:
        st.warning(
            "⚠️ **Supabase not configured.** Products are only saved locally to `data.db` on this machine. "
            "If this computer is lost or the app is redeployed, all product and inventory data will be gone. "
            "Go to **Settings → Database** to connect Supabase. "
            "Supabase also powers the **API Endpoints** page so your website auto-updates when you change products here."
        )

    if "_products_cache" not in st.session_state:
        with st.spinner("Loading products…"):
            st.session_state["_products_cache"] = load_products_for_catalog(cfg)
    products = st.session_state["_products_cache"]

    # Compute sync targets for display in this page
    _p_has_sb = _has_supabase(cfg)
    _p_sync = ["SQLite"] + (["Supabase"] if _p_has_sb else [])
    _p_sync_str = " + ".join(_p_sync)

    tab_catalog, tab_add, tab_edit, tab_delete = st.tabs(
        ["Catalog", "Add Products", "Edit Products", "Delete Products"]
    )

    # ══ CATALOG ═════════════════════════════════
    with tab_catalog:
        if not products:
            st.info("No products yet. Go to the **Add Products** tab to get started.")
        else:
            if _p_has_sb:
                st.caption(f"Syncing to: **{_p_sync_str}**")
            
            st.caption(f"Showing {len(products)} product{'s' if len(products) != 1 else ''}.")
            
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
                        _e_file  = st.file_uploader("Replace image", type=["jpg", "png", "webp", "jpeg"], key=f"e_file_{_edit_sku}")
                    
                    if st.form_submit_button("Save Changes", type="primary", width="stretch"):
                        with st.spinner("Saving..."):
                            _final_url = _eprod.get("image_url", "N/A")
                            if _e_file and _has_image_host(cfg):
                                try:
                                    _final_url = upload_image(_e_file.read(), cfg, name=_e_name.strip())
                                except: pass
                            
                            _upd = {
                                "sku": _edit_sku, "item_name": _e_name.strip() or _eprod.get("item_name", ""),
                                "category": _e_cat.strip() or _eprod.get("category", "General"),
                                "price": round(_e_price, 2), "image_url": _final_url,
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
    
    # ── Migration for Original Stock (SQLite local) ─────────────────
    try:
        _conn_mig = _get_sqlite_conn()
        _cur_mig = _conn_mig.cursor()
        _cur_mig.execute("PRAGMA table_info(inventory)")
        _cols = [r[1] for r in _cur_mig.fetchall()]
        if "original_stock" not in _cols:
            _conn_mig.execute("ALTER TABLE inventory ADD COLUMN original_stock INTEGER NOT NULL DEFAULT 0")
            _conn_mig.commit()
        _conn_mig.close()
    except: pass

    st.title("Inventory")
    st.caption("Manage stock overview, adjustments, and outbound logs in one place.")

    tab_overview, tab_adjust, tab_original, tab_outbound = st.tabs(
        ["Overview", "Adjust Stock", "Original Stock", "Outbound Information"]
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
            _has_sb_inv = _has_supabase(cfg)
            _sync_targets = ["SQLite"]
            if _has_sb_inv:  _sync_targets.append("Supabase")

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
                        if _has_sb_inv: adjust_inventory_supabase(_asku, _adelta, cfg)
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
                                if _has_sb_inv: adjust_inventory_supabase(_psku, int(_delta_val), cfg)
                                st.toast(f"Stock updated: {_pname}", icon="✅")
                                _clear_data_caches()
                                time.sleep(0.5)
                                st.rerun()
            st.divider()

    # ── ORIGINAL STOCK ──────────────────────────
    with tab_original:
        if inv_df.empty:
            st.info("No products found. Add products in the **Products** page first.")
        else:
            st.markdown("#### Purchased Inventory (Lifetime Total)")
            st.caption(
                "This reflects the **total quantity** of items you have ever acquired for your firm. "
                "The `Adjust Stock` tab automatically increases this number when you ADD stock. "
                "You can manually correct these values here if needed."
            )
            
            for _, _pr in inv_df.iterrows():
                _osku   = str(_pr.get("sku", ""))
                _oname  = str(_pr.get("item_name", _osku))
                _ostock = int(_pr.get("original_stock", 0))
                _oimg   = str(_pr.get("image_url", ""))
                
                _oc1, _oc2, _oc3, _oc4, _oc5 = st.columns([1, 4, 2, 2, 1.5], vertical_alignment="center")
                with _oc1:
                    if _oimg and _oimg not in ("N/A", "", "nan"): st.image(_oimg, width=56)
                    else: st.markdown("<div style='width:56px;height:56px;background:#f4f4f5;border-radius:8px;display:flex;align-items:center;justify-content:center;color:#bbb;font-size:10px;'>No img</div>", unsafe_allow_html=True)
                
                with _oc2:
                    st.markdown(f"**{_oname}**")
                    st.caption(f"{_osku}")
                
                with _oc3:
                    st.markdown(
                        f"<div style='font-size:24px;font-weight:700;color:#818cf8;'>{_ostock}</div>"
                        f"<div style='font-size:10px;color:#94a3b8;'>Lifetime Total</div>",
                        unsafe_allow_html=True
                    )
                
                with _oc4:
                    # Input for absolute override
                    _new_total = st.number_input("New Total", min_value=0, value=_ostock, key=f"orig_val_{_osku}", label_visibility="collapsed")
                
                with _oc5:
                    if st.button("Set", key=f"btn_orig_{_osku}", width="stretch"):
                        with st.spinner("Setting..."):
                            ok, _msg = set_original_stock_all_dbs(_osku, int(_new_total), cfg)
                            if ok:
                                st.toast(f"Original stock updated: {_oname}", icon="📌")
                                _clear_data_caches()
                                time.sleep(0.5)
                                st.rerun()
                            else:
                                st.error(f"Failed to update some databases: {_msg}")
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
    st.caption("Credentials are auto-saved the moment you leave any field — no need to click a button.")

    # ── Auto-save key map: session-state key → config.json key ──────
    _SETTINGS_KEY_MAP = {
        "_cfg_from_name":       "from_name",
        "_cfg_subject":         "subject",
        "_cfg_smtp_email":      "smtp_email",
        "_cfg_smtp_pass":       "smtp_password",
        "inp_freeimage_key":    "freeimage_api_key",
        "inp_imgbb_key":        "imghippo_api_key",
        "inp_sb_pass":          "supabase_db_password",
        "inp_sb_conn":          "supabase_connection_string",
    }

    # Initialise session state keys from cfg (once per session)
    for _ss_k, _cfg_k in _SETTINGS_KEY_MAP.items():
        if _ss_k not in st.session_state:
            st.session_state[_ss_k] = cfg.get(_cfg_k, "")

    def _auto_save_settings():
        _new = {**st.session_state.cfg}
        for _ss_k, _cfg_k in _SETTINGS_KEY_MAP.items():
            _new[_cfg_k] = st.session_state.get(_ss_k, "")
        # Gmail app passwords are pasted with spaces — strip them before saving
        _new["smtp_password"] = re.sub(r"\s+", "", _new.get("smtp_password", ""))
        try:
            save_config(_new)
            st.session_state.cfg = _new
        except Exception as _e:
            st.error(f"Auto-save failed: {_e}")

    # ── VEI account note ─────────────────────────
    st.info(
        "**VEI Firms:** You must use your VEI account for all settings below. "
        "Your firm coordinator may have already set up a shared Gmail account and firm name — ask them for the details. "
        "All other keys (image hosting, database) are personal free accounts you create yourself."
    )

    # ── Sender Identity ─────────────────────────
    st.subheader("Sender Identity")
    col1, col2 = st.columns(2)
    with col1:
        inp_from_name = st.text_input(
            "From Name",
            placeholder="Your VEI Firm Name",
            help="Displayed as the sender name in the recipient's inbox",
            key="_cfg_from_name",
            on_change=_auto_save_settings,
        )
    with col2:
        inp_subject = st.text_input(
            "Default Subject Line",
            placeholder="Your order is here",
            help="Use {order_number} to insert the order number",
            key="_cfg_subject",
            on_change=_auto_save_settings,
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
            placeholder="yourname@gmail.com",
            help="The Gmail account emails will be sent from",
            key="_cfg_smtp_email",
            on_change=_auto_save_settings,
        )
    with col4:
        inp_smtp_pass = st.text_input(
            "App Password",
            type="password",
            placeholder="xxxx xxxx xxxx xxxx",
            help="The 16-character app password from your Google account",
            key="_cfg_smtp_pass",
            on_change=_auto_save_settings,
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
                type="password",
                placeholder="your_api_key_here",
                help="freeimage.host → Menu → API → copy your key",
                key="inp_freeimage_key",
                on_change=_auto_save_settings,
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
                type="password",
                placeholder="your_imghippo_api_key",
                help="imghippo.com → Settings → API Keys → Generate",
                key="inp_imgbb_key",
                on_change=_auto_save_settings,
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
        "Connect Supabase to persist products and inventory. "
        "Click **Setup Tables** to create the schema automatically. "
        "If the cloud database goes offline, all writes fall back to local SQLite automatically."
    )

    _cfg_now = st.session_state.cfg
    if _has_supabase(_cfg_now):
        st.info(
            "**Cloud database configured.** Writes go to both Supabase and local SQLite simultaneously. "
            "If Supabase is temporarily unreachable, writes continue to local SQLite automatically."
        )

    st.markdown("#### Connect Supabase (required for API Endpoints & cloud sync)")
    st.caption("New to Supabase? See the **Get Started** page for a full walkthrough.")

    inp_sb_conn = st.text_input(
        "Connection String",
        placeholder="postgresql://postgres:[YOUR-PASSWORD]@db.xxxxxxxxxxxx.supabase.co:5432/postgres",
        help="From Supabase Dashboard → Connect button (top right) → Direct connection tab. Leave [YOUR-PASSWORD] as-is.",
        key="inp_sb_conn",
        on_change=_auto_save_settings,
    )
    inp_sb_pass = st.text_input(
        "Database Password",
        type="password",
        placeholder="Your Supabase database password",
        help="The password you set when creating your Supabase project. Used to replace [YOUR-PASSWORD] in the connection string.",
        key="inp_sb_pass",
        on_change=_auto_save_settings,
    )

    # Show resolved connection status
    _sb_conn_val = inp_sb_conn.strip()
    _sb_pass_val = inp_sb_pass.strip()
    _sb_effective = ""
    if _sb_conn_val:
        if "[YOUR-PASSWORD]" in _sb_conn_val and _sb_pass_val:
            _sb_effective = _sb_conn_val.replace("[YOUR-PASSWORD]", _sb_pass_val)
        elif "[YOUR-PASSWORD]" not in _sb_conn_val:
            _sb_effective = _sb_conn_val

    if _sb_conn_val and "[YOUR-PASSWORD]" in _sb_conn_val and not _sb_pass_val:
        st.warning("Enter your **Database Password** above to complete the connection string.")
    elif _sb_effective:
        st.caption("Connection string is ready. Click **Test Connection** to verify.")

    col_sb_test, col_sb_setup = st.columns(2)
    with col_sb_test:
        if st.button(
            "Test Connection",
            width="stretch",
            key="btn_test_sb",
            disabled=not _sb_effective,
        ):
            with st.spinner("Connecting to Supabase..."):
                try:
                    _conn = _psycopg2_connect(_sb_effective)
                    _conn.close()
                    st.toast("Supabase connection success!", icon="☁️")
                    st.success("Connected to Supabase successfully.")
                except Exception as exc:
                    st.error(f"Connection failed: {exc}")

    with col_sb_setup:
        if st.button(
            "Setup Tables",
            type="primary",
            width="stretch",
            key="btn_setup_sb",
            disabled=not _sb_effective,
        ):
            with st.spinner("Creating tables in Supabase..."):
                try:
                    _conn = _psycopg2_connect(_sb_effective, connect_timeout=15)
                    _cur = _conn.cursor()
                    _statements = [
                        s.strip() for s in SETUP_SQL.split(";")
                        if s.strip() and not all(l.startswith("--") for l in s.strip().splitlines() if l.strip())
                    ]
                    _ok, _fail = 0, []
                    for _stmt in _statements:
                        try:
                            _cur.execute(_stmt)
                            _ok += 1
                        except Exception as _se:
                            _fail.append(f"{_stmt[:60]}… → {str(_se)[:100]}")
                    _conn.commit()
                    _cur.close()
                    _conn.close()
                    if not _fail:
                        st.toast("Supabase tables ready!", icon="📦")
                        st.success("Tables created successfully. You can now use the API Endpoints page.")
                    else:
                        st.warning(f"{_ok} OK, {len(_fail)} failed:")
                        for _f in _fail:
                            st.caption(_f)
                except Exception as exc:
                    st.error(f"Setup failed: {exc}")

    # ── Save Settings ──
    st.divider()
    st.caption("All fields above are auto-saved as you type. Use this button to force-save.")

    if st.button("Save Settings", type="primary", width="stretch"):
        # Save config first
        new_cfg = {
            "from_name":                inp_from_name.strip(),
            "subject":                  inp_subject.strip(),
            "smtp_email":               inp_smtp_email.strip(),
            "smtp_password":            re.sub(r"\s+", "", inp_smtp_pass.strip()),
            "freeimage_api_key":        inp_freeimage_key.strip(),
            "imghippo_api_key":         inp_imgbb_key.strip(),
            "supabase_connection_string": inp_sb_conn.strip(),
            "supabase_db_password":     inp_sb_pass.strip(),
            "email_html_template":      cfg.get("email_html_template", ""),
            "products":                 cfg.get("products", []),
        }
        save_config(new_cfg)
        st.session_state.cfg = new_cfg

        st.success("Settings saved!")
        time.sleep(0.5)
        st.rerun()

    # ── Secrets TOML ─────────────────────────────────────────────────
    st.divider()
    st.subheader("Secrets TOML — Prevent Settings Loss on Reboot")
    st.markdown("""
Streamlit Cloud wipes the local filesystem on every reboot, so `config.json` disappears.
**Fix this in one step:** generate the TOML below, copy it, and paste it into Streamlit's built-in secrets store.
MERIT reads from `st.secrets` automatically on startup — your settings will survive reboots forever.

**How to paste it:**
1. Click **Manage app** in the bottom-right corner of your Streamlit app
2. Click the **⋮ three-dot menu** → **Settings** → **Secrets**
3. Paste the TOML below into the editor → click **Save**
4. Streamlit reboots the app with your secrets loaded

*If running locally:* save the TOML to `.streamlit/secrets.toml` in the project folder.
    """)

    _toml_cfg = st.session_state.cfg
    def _toml_escape(v: str) -> str:
        return v.replace("\\", "\\\\").replace('"', '\\"')

    _toml_lines = ["[merit]"]
    for _tk in _SECRETS_CREDENTIAL_KEYS:
        _tv = _toml_cfg.get(_tk, "")
        _toml_lines.append(f'{_tk} = "{_toml_escape(str(_tv))}"')
    _toml_content = "\n".join(_toml_lines)

    st.code(_toml_content, language="toml")

    _has_toml_data = any(_toml_cfg.get(k) for k in _SECRETS_CREDENTIAL_KEYS)
    if not _has_toml_data:
        st.info("Fill in your Supabase and email settings above, then come back here to generate your TOML.")

    _gs_secrets_active = False
    try:
        _gs_secrets_active = hasattr(st, "secrets") and "merit" in st.secrets
    except Exception:
        pass

    if _gs_secrets_active:
        st.success("Secrets are active — MERIT is reading credentials from `st.secrets`. Settings will persist across reboots.")
    else:
        st.warning(
            "Secrets not detected yet. After pasting the TOML into Streamlit secrets and saving, "
            "Streamlit will reboot and this message will change to a green confirmation."
        )


# ═════════════════════════════════════════════
# API ENDPOINTS PAGE
# ═════════════════════════════════════════════

elif page == "API Endpoints":
    cfg = st.session_state.cfg

    _api_sb_url    = _get_supabase_project_url(cfg)
    _api_rest_base = f"{_api_sb_url}/rest/v1" if _api_sb_url else ""
    _sb_url_ph     = _api_sb_url or "YOUR_SUPABASE_URL"

    st.title("Connect Your Website")
    st.caption(
        "Every product you add or edit in MERIT automatically updates in your Supabase database. "
        "This page gives you everything you need to connect that database to a website built on "
        "Bolt.new, Lovable, Cursor, v0, or any other platform."
    )

    if not _has_supabase(cfg):
        st.warning(
            "**Supabase is not connected yet.** "
            "Go to **Get Started → Step 1** or **Settings → Database** and paste your "
            "Supabase connection string, then click **Setup Tables**."
        )
        st.stop()

    # ── Key values banner ────────────────────────────────────────────
    _kv1, _kv2 = st.columns(2)
    with _kv1:
        st.markdown("**Your Supabase URL** — paste this into your website builder")
        st.code(_sb_url_ph, language="text")
    with _kv2:
        st.markdown("**Your anon key** — where to get it")
        st.info("Supabase Dashboard → Project Settings (gear icon) → API → copy the **anon / public** key (starts with `eyJ…`)")

    st.caption(
        "The anon key is safe to put in your website code when Row Level Security is on. "
        "Never put your database password or connection string in a website."
    )

    st.divider()

    # ── Tabs ─────────────────────────────────────────────────────────
    _tab_ai, _tab_live, _tab_api, _tab_code, _tab_schema = st.tabs(
        ["AI Prompts", "Live Preview", "REST Endpoints", "Code Snippets", "Schema & Security SQL"]
    )

    # ── AI Prompts ────────────────────────────────────────────────────
    with _tab_ai:
        _sb_url_ai = _api_sb_url or "YOUR_SUPABASE_URL"
        st.markdown("### Copy-paste prompts for AI website builders")
        st.caption(
            "Pick the tab matching your platform, copy the prompt, paste it into the AI chat, "
            "replace YOUR_SUPABASE_ANON_KEY with your real anon key, and the AI will build your storefront."
        )

        _ai_master, _ai_bolt, _ai_lovable, _ai_cursor, _ai_schema_tab = st.tabs(
            ["Master Context Block", "Bolt.new", "Lovable", "Cursor / v0 / General", "Full Schema SQL"]
        )

        # ── shared schema text used across all prompts ──────────────────
        _schema_block = f"""\
=== MERIT DATABASE SCHEMA (Supabase / PostgreSQL) ===

Supabase project URL : {_sb_url_ai}
Supabase anon key    : YOUR_SUPABASE_ANON_KEY   ← replace this

--- TABLE: inventory  (use for storefront — has live stock) ---
Column          Type              Notes
-----------     ----------------  -----------------------------------------
id              BIGSERIAL PK      auto-increment, do not reference in queries
sku             TEXT NOT NULL     unique product code, use as the URL slug
item_name       TEXT NOT NULL     product display name
category        TEXT              product category (use for filters)
price           NUMERIC(10,2)     retail price in USD
stock_left      INTEGER           units currently in stock
status          TEXT              'In stock' | 'Low stock' | 'Out of stock' | 'Backordered'
image_url       TEXT              full public HTTPS URL — use directly in <img src="">
original_stock  INTEGER           initial stock set when product was added
created_at      TIMESTAMPTZ       when the row was created

STOREFRONT QUERY RULE:
  Show only products where stock_left > 0
  (status reflects the same thing but stock_left > 0 is the canonical filter)

--- TABLE: products  (clean catalog, no stock data) ---
Column          Type              Notes
-----------     ----------------  -----------------------------------------
id              BIGSERIAL PK
sku             TEXT NOT NULL     matches inventory.sku
name            TEXT NOT NULL     product display name
category        TEXT
price           NUMERIC(10,2)
description     TEXT              product description (may be empty)
image_url       TEXT              full public HTTPS URL
active          BOOLEAN           true = visible, false = hidden
created_at      TIMESTAMPTZ

USE CASE: Use products table when you want a clean catalog without stock numbers.
Filter: active = true

--- TABLE: outbound_logs  (order history — read-only from website) ---
Column            Type              Notes
-----------       ----------------  -----------------------------------------
id                BIGSERIAL PK
recipient_name    TEXT
recipient_email   TEXT
order_number      TEXT
products_list     TEXT              comma-separated product names
subtotal          NUMERIC(10,2)
tax               NUMERIC(10,2)
shipping          NUMERIC(10,2)
total_cost        NUMERIC(10,2)
created_at        TIMESTAMPTZ

=== IMAGE RULES ===
- image_url is ALWAYS a full public HTTPS URL (hosted on Freeimage.host or Imghippo)
- Use it directly in <img src={{product.image_url}}>
- If image_url is 'N/A', null, or empty string → show a grey placeholder div
- NEVER try to proxy or re-upload images — they are already hosted

=== RLS (ROW LEVEL SECURITY) ===
The following policies must be in place so anonymous visitors can read but not write.
Run this SQL in Supabase Dashboard → SQL Editor → New Query:

  ALTER TABLE inventory ENABLE ROW LEVEL SECURITY;
  ALTER TABLE products  ENABLE ROW LEVEL SECURITY;
  ALTER TABLE outbound_logs ENABLE ROW LEVEL SECURITY;

  CREATE POLICY "Public read inventory"
    ON inventory FOR SELECT USING (true);

  CREATE POLICY "Public read products"
    ON products FOR SELECT USING (true);

MERIT writes to the database using the direct PostgreSQL connection string (bypasses RLS).
The anon key used by the website is read-only — it cannot INSERT, UPDATE, or DELETE.

=== SUPABASE REALTIME ===
To enable live updates when MERIT changes a product:
1. Supabase Dashboard → Database → Replication
2. Toggle ON for: inventory, products
3. Subscribe in your JS code using supabase.channel(...)

=== ENV VARIABLES ===
For Bolt.new / Lovable / Vite projects use:
  VITE_SUPABASE_URL      = {_sb_url_ai}
  VITE_SUPABASE_ANON_KEY = YOUR_SUPABASE_ANON_KEY

For Next.js projects use:
  NEXT_PUBLIC_SUPABASE_URL      = {_sb_url_ai}
  NEXT_PUBLIC_SUPABASE_ANON_KEY = YOUR_SUPABASE_ANON_KEY"""

        # ── Master Context Block ────────────────────────────────────────
        with _ai_master:
            st.markdown(
                "**Paste this entire block at the start of any AI conversation** "
                "(Bolt.new, Lovable, Cursor, ChatGPT, Claude, v0 — anything). "
                "It gives the AI full schema, RLS policies, image rules, and env var names so it can build "
                "the entire storefront without asking follow-up questions."
            )
            _master_prompt = f"""\
{_schema_block}

=== WHAT TO BUILD ===
Build a modern product storefront website that reads from the Supabase database described above.

Requirements:
1. Product grid — responsive 3-column layout (1 col mobile, 2 col tablet, 3 col desktop)
   - Each card: product image, name (item_name), price, stock status badge, "Add to Cart" button
   - Only show products where stock_left > 0
   - Grey placeholder when image_url is 'N/A' or empty

2. Category filter — horizontal pill buttons at the top, "All" selected by default
   - Fetch distinct categories from the inventory table
   - Clicking a category filters the grid instantly (client-side)

3. Product detail page — route: /products/[sku]
   - Large image left, details right
   - Show: name, price, category, description (from products table), stock status
   - "Out of Stock" badge when stock_left = 0, grey out the Add to Cart button

4. Cart — localStorage, no login required
   - Slide-in drawer, quantity +/-, remove button, subtotal
   - Cart icon in header with item count badge

5. Realtime — subscribe to inventory table changes
   - When MERIT updates a product, the grid refreshes automatically without page reload

6. RLS — run the RLS SQL above in Supabase before going live"""
            st.code(_master_prompt, language="text")

        # ── Bolt.new ────────────────────────────────────────────────────
        with _ai_bolt:
            st.markdown("""
**How to use in Bolt.new:**
1. Open [bolt.new](https://bolt.new) → start a new project
2. When Bolt asks you to connect a database → click **Supabase** → **Connect to existing project**
3. Paste your Supabase URL and anon key
4. Then paste the prompt below into the chat
            """)
            _bolt_prompt = f"""\
I already have a Supabase database set up and connected. Do NOT create new tables.

{_schema_block}

Build a VEI (Virtual Enterprise International) firm product storefront using the schema above.

Tech stack: React + Vite + Tailwind CSS + @supabase/supabase-js

Pages to build:
1. / (Home) — product grid
   - Fetch from inventory where stock_left > 0
   - Responsive grid: 1 col (mobile) → 2 col (tablet) → 3 col (desktop)
   - Product card: <img src={{item.image_url}} /> with grey fallback, item_name, price formatted as $X.XX,
     stock status badge (green = In stock, yellow = Low stock, red = Out of stock), Add to Cart button
   - Category filter pills at top (fetch distinct categories, All selected by default)
   - Sort toggle: A-Z / Price Low-High / Price High-Low

2. /products/:sku — product detail
   - Pull single product where sku = route param
   - Large image + details panel with description from products table
   - Add to Cart button disabled + greyed when stock_left = 0
   - Breadcrumb: Home → [category] → [item_name]

3. Cart (slide-in drawer, not a page)
   - State in localStorage key "merit_cart"
   - Each item: {{ sku, item_name, price, image_url, quantity }}
   - +/- quantity buttons, remove button, item subtotal, grand total
   - "Checkout" button → opens a modal form (Name, Email, notes) → shows order confirmation on submit

Supabase Realtime:
- Subscribe to postgres_changes on inventory table
- On any change event → refetch the product list so the page stays live

Use the exact env var names: VITE_SUPABASE_URL and VITE_SUPABASE_ANON_KEY"""
            st.code(_bolt_prompt, language="text")

        # ── Lovable ─────────────────────────────────────────────────────
        with _ai_lovable:
            st.markdown("""
**How to use in Lovable:**
1. Open [lovable.dev](https://lovable.dev) → create a new project
2. In the Supabase integration panel → paste your URL and anon key
3. Tell Lovable **"do not create new tables — I already have tables"**, then paste the prompt below
            """)
            _lovable_prompt = f"""\
I have an existing Supabase database. DO NOT run any CREATE TABLE or ALTER TABLE statements.
My tables already exist. Only read from them using SELECT queries through the Supabase client.

{_schema_block}

Build a product storefront for my VEI firm with the following pages and features.

Design: clean, minimal, white background, dark navy header, rounded product cards with subtle shadows.

--- PAGE: / (Product Catalog) ---
- Fetch all rows from inventory where stock_left > 0, ordered by item_name ASC
- Display in a responsive product grid
- Each card shows:
    • Product image from image_url (if image_url = 'N/A' or empty → show grey box with "No image" text)
    • item_name as card title
    • price formatted as "$X.XX"
    • A coloured badge for status: "In stock" → green, "Low stock" → amber, "Out of stock" → red
    • "Add to Cart" button (disabled and greyed when stock_left = 0)
- Horizontal category filter at top (distinct values from inventory.category)
- Search bar that filters item_name in real-time (client-side)

--- PAGE: /product/:sku ---
- Fetch single product from inventory where sku = URL param
- Two-column layout: image left (large), details right
- Show: item_name, price, category, stock_left (e.g. "12 in stock"), status badge, description (from products table if available)
- Add to Cart button
- Back link to catalog

--- COMPONENT: Cart Drawer ---
- Triggered by cart icon in navbar (shows count badge)
- Slide in from right
- Line items: image thumbnail, name, $price × quantity, remove button
- Order total at bottom
- "Request Order" button → opens a modal with: Name, Email, Message fields → on submit show thank-you confirmation

--- REALTIME ---
Connect to Supabase Realtime on the inventory table. On INSERT, UPDATE, or DELETE events re-fetch the catalog so changes from MERIT appear instantly on the site.

--- ENV VARS needed ---
VITE_SUPABASE_URL      = {_sb_url_ai}
VITE_SUPABASE_ANON_KEY = YOUR_SUPABASE_ANON_KEY"""
            st.code(_lovable_prompt, language="text")

        # ── Cursor / v0 / General ───────────────────────────────────────
        with _ai_cursor:
            st.markdown("""
**Works with Cursor, v0.dev, Claude, ChatGPT, or any AI assistant.**
Paste the prompt below into the AI chat after opening your project.
For **v0.dev** just paste it directly into the v0 prompt bar.
            """)
            _cursor_prompt = f"""\
I need to build a product storefront that reads from my Supabase database.
Use the schema and rules below exactly — do not invent column names or table structures.

{_schema_block}

=== IMPLEMENTATION INSTRUCTIONS ===

Step 1 — Supabase client setup
  import {{ createClient }} from '@supabase/supabase-js'
  const supabase = createClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL,   // or VITE_SUPABASE_URL for Vite
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY
  )

Step 2 — Fetch in-stock products
  const {{ data: products }} = await supabase
    .from('inventory')
    .select('sku, item_name, category, price, stock_left, status, image_url')
    .gt('stock_left', 0)
    .order('item_name')

Step 3 — Fetch a single product by SKU
  const {{ data }} = await supabase
    .from('inventory')
    .select('*')
    .eq('sku', sku)
    .single()

Step 4 — Fetch distinct categories for the filter bar
  const {{ data: cats }} = await supabase
    .from('inventory')
    .select('category')
  const categories = [...new Set(cats.map(r => r.category).filter(Boolean))]

Step 5 — Product image rendering
  // image_url is a full HTTPS URL from Freeimage.host or Imghippo
  // Always provide a fallback:
  <img
    src={{product.image_url !== 'N/A' ? product.image_url : '/placeholder.png'}}
    alt={{product.item_name}}
    onError={{(e) => {{ e.target.src = '/placeholder.png' }}}}
  />

Step 6 — Subscribe to Realtime (live updates from MERIT)
  const channel = supabase
    .channel('merit-inventory')
    .on('postgres_changes', {{ event: '*', schema: 'public', table: 'inventory' }},
      () => fetchProducts()  // re-fetch on any change
    )
    .subscribe()
  // Cleanup: supabase.removeChannel(channel)

Step 7 — Run RLS SQL in Supabase SQL Editor before deploying:
  ALTER TABLE inventory ENABLE ROW LEVEL SECURITY;
  ALTER TABLE products  ENABLE ROW LEVEL SECURITY;
  CREATE POLICY "Public read inventory" ON inventory FOR SELECT USING (true);
  CREATE POLICY "Public read products"  ON products  FOR SELECT USING (true);

=== BUILD THE FOLLOWING ===
- Responsive product grid (3 cols desktop, 1 col mobile) from the inventory table
- Category filter pills
- Product detail page routed by SKU
- Cart stored in localStorage (sku, item_name, price, image_url, quantity)
- Simple checkout modal (Name, Email, Message) with confirmation on submit
- Realtime subscription so the page auto-updates when I change products in MERIT"""
            st.code(_cursor_prompt, language="text")

        # ── Full Schema SQL ─────────────────────────────────────────────
        with _ai_schema_tab:
            st.markdown(
                "**Paste this SQL into Supabase Dashboard → SQL Editor → New Query and click Run.** "
                "This creates all tables MERIT needs AND adds the public-read RLS policies your website requires. "
                "If tables already exist the `IF NOT EXISTS` clauses make it safe to re-run."
            )
            _full_schema_sql = SETUP_SQL.rstrip() + """

-- ── Row Level Security (required for website access) ─────────────────────────
-- Run this after creating the tables.
-- This lets any visitor with the anon key READ products.
-- MERIT writes using the direct connection string which bypasses RLS entirely.

ALTER TABLE inventory     ENABLE ROW LEVEL SECURITY;
ALTER TABLE products      ENABLE ROW LEVEL SECURITY;
ALTER TABLE outbound_logs ENABLE ROW LEVEL SECURITY;

-- Drop policies first in case you are re-running this script
DROP POLICY IF EXISTS "Public read inventory"     ON inventory;
DROP POLICY IF EXISTS "Public read products"      ON products;
DROP POLICY IF EXISTS "Public read outbound_logs" ON outbound_logs;

CREATE POLICY "Public read inventory"
  ON inventory FOR SELECT USING (true);

CREATE POLICY "Public read products"
  ON products FOR SELECT USING (true);

-- outbound_logs: uncomment the line below if you want the website to show order history
-- CREATE POLICY "Public read outbound_logs" ON outbound_logs FOR SELECT USING (true);

-- ── Verify everything ─────────────────────────────────────────────────────────
SELECT
  t.tablename,
  t.rowsecurity,
  COUNT(p.policyname) AS policies
FROM pg_tables t
LEFT JOIN pg_policies p ON p.tablename = t.tablename
WHERE t.schemaname = 'public'
  AND t.tablename IN ('inventory', 'products', 'outbound_logs')
GROUP BY t.tablename, t.rowsecurity
ORDER BY t.tablename;
-- Expected result: 3 rows, rowsecurity = true, inventory and products have 1 policy each"""
            st.code(_full_schema_sql, language="sql")

    # ── Live Preview ─────────────────────────────────────────────────
    with _tab_live:
        st.markdown("### Live snapshot from your Supabase database")
        st.caption("This is exactly the data your website will see when it reads from Supabase.")

        _live_conn_str = _get_effective_supabase_conn_str(cfg)

        # Validate format before attempting connection
        if not _live_conn_str.startswith("postgresql://"):
            st.error(
                "**Connection string format is incorrect.** "
                "It must start with `postgresql://`. "
                "Go to **Settings → Database** and paste the full connection string from Supabase."
            )
        else:
            if st.button("Load / Refresh Data", key="btn_api_refresh", type="primary"):
                st.cache_data.clear()
                st.rerun()

            try:
                _live_conn = _psycopg2_connect(_live_conn_str)

                _preview_inv, _preview_prod = st.columns(2)
                with _preview_inv:
                    st.markdown("**Your products** (inventory table)")
                    try:
                        _inv_df = pd.read_sql(
                            "SELECT sku, item_name AS name, category, price, stock_left, status "
                            "FROM inventory ORDER BY item_name LIMIT 50",
                            _live_conn,
                        )
                        if not _inv_df.empty:
                            st.dataframe(_inv_df, use_container_width=True, hide_index=True)
                            st.caption(f"{len(_inv_df)} products shown (max 50)")
                        else:
                            st.info("No products yet. Add some in the **Products** page.")
                    except Exception as _e:
                        st.error(f"Could not read products: {_e}")

                with _preview_prod:
                    st.markdown("**Category breakdown**")
                    try:
                        _cat_df = pd.read_sql(
                            "SELECT category, COUNT(*) AS products, SUM(stock_left) AS total_stock "
                            "FROM inventory GROUP BY category ORDER BY products DESC",
                            _live_conn,
                        )
                        if not _cat_df.empty:
                            st.dataframe(_cat_df, use_container_width=True, hide_index=True)
                        else:
                            st.info("No categories yet.")
                    except Exception as _e:
                        st.error(f"Could not read categories: {_e}")

                _live_conn.close()
            except Exception as _live_err:
                _err_msg = str(_live_err)
                if "password" in _err_msg.lower() or "authentication" in _err_msg.lower():
                    st.error(
                        "**Wrong database password.** "
                        "Go to **Settings → Database** and check that the Database Password field matches "
                        "the password you set when creating your Supabase project."
                    )
                elif "could not connect" in _err_msg.lower() or "timeout" in _err_msg.lower():
                    st.error(
                        "**Could not reach Supabase.** Check your internet connection and try again. "
                        "If you are on a school network, try a personal hotspot."
                    )
                else:
                    st.error(f"**Connection failed.** {_err_msg}")

    # ── REST Endpoints ────────────────────────────────────────────────
    with _tab_api:
        st.markdown("### REST API Endpoints")
        st.caption(
            "These are the URLs your website can call to read products. "
            "You normally don't need to use these manually — the AI Prompts tab generates code that calls them for you. "
            "But they are here if you want to test or inspect them."
        )
        st.markdown(f"**Base URL:** `{_api_rest_base}`")
        st.markdown("**Required headers on every request:**")
        st.code(
            f"apikey: YOUR_SUPABASE_ANON_KEY\nAuthorization: Bearer YOUR_SUPABASE_ANON_KEY",
            language="http",
        )
        st.divider()

        st.markdown("#### Products + live stock (`inventory` table)")
        _inv_rows = [
            ("GET", f"{_api_rest_base}/inventory?select=*",                                  "All products (all columns)"),
            ("GET", f"{_api_rest_base}/inventory?select=*&stock_left=gte.1&order=item_name", "In-stock only, A to Z"),
            ("GET", f"{_api_rest_base}/inventory?select=*&category=eq.Apparel",              "Filter by category"),
            ("GET", f"{_api_rest_base}/inventory?sku=eq.SKU001&select=*",                    "One product by SKU"),
        ]
        st.dataframe(
            pd.DataFrame(_inv_rows, columns=["Method", "URL", "What it returns"]),
            use_container_width=True, hide_index=True,
        )

        st.markdown("#### Clean catalog (no stock numbers) — `products` table")
        _prod_rows = [
            ("GET", f"{_api_rest_base}/products?select=*&active=eq.true",                   "All active products"),
            ("GET", f"{_api_rest_base}/products?select=*&active=eq.true&order=name",        "Active, A to Z"),
            ("GET", f"{_api_rest_base}/products?category=eq.Apparel&active=eq.true&select=*", "Filter by category"),
        ]
        st.dataframe(
            pd.DataFrame(_prod_rows, columns=["Method", "URL", "What it returns"]),
            use_container_width=True, hide_index=True,
        )

    # ── Code Snippets ─────────────────────────────────────────────────
    with _tab_code:
        st.markdown("### Ready-to-paste code snippets")
        st.caption(
            "Copy the snippet that matches your project. "
            "Replace `YOUR_SUPABASE_ANON_KEY` with your actual anon key from Supabase Dashboard → Project Settings → API."
        )

        _ex_js, _ex_ts, _ex_react, _ex_rt = st.tabs(
            ["JavaScript", "TypeScript / Next.js", "React Hook", "Real-time (live updates)"]
        )

        with _ex_js:
            st.markdown("Works in any plain HTML/JS project or Bolt.new:")
            st.code(f"""\
// Step 1 — install:  npm install @supabase/supabase-js
import {{ createClient }} from '@supabase/supabase-js'

const supabase = createClient(
  '{_sb_url_ph}',
  'YOUR_SUPABASE_ANON_KEY'
)

// Fetch all in-stock products
async function getProducts() {{
  const {{ data, error }} = await supabase
    .from('inventory')
    .select('*')
    .gt('stock_left', 0)       // only show products that have stock
    .order('item_name')         // alphabetical order

  if (error) throw error
  return data  // each item has: sku, item_name, price, image_url, stock_left, category
}}

// Fetch by category (for filter buttons)
async function getByCategory(category) {{
  const {{ data }} = await supabase
    .from('inventory')
    .select('*')
    .eq('category', category)
    .gt('stock_left', 0)

  return data
}}
""", language="javascript")

        with _ex_ts:
            st.markdown("For Next.js or any TypeScript project:")
            st.code(f"""\
// lib/supabase.ts
import {{ createClient }} from '@supabase/supabase-js'
export const supabase = createClient(
  process.env.NEXT_PUBLIC_SUPABASE_URL!,
  process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!
)

// .env.local  (create this file in your project root)
NEXT_PUBLIC_SUPABASE_URL={_sb_url_ph}
NEXT_PUBLIC_SUPABASE_ANON_KEY=YOUR_SUPABASE_ANON_KEY

// types.ts
export interface Product {{
  sku: string
  item_name: string
  category: string
  price: number
  stock_left: number
  status: string          // 'In stock' | 'Low stock' | 'Out of stock' | 'Backordered'
  image_url: string       // full HTTPS URL — use directly in <img src>
}}

// lib/products.ts
import {{ supabase }} from './supabase'
import type {{ Product }} from './types'

export async function getProducts(): Promise<Product[]> {{
  const {{ data, error }} = await supabase
    .from('inventory')
    .select('*')
    .gt('stock_left', 0)
    .order('item_name')

  if (error) throw error
  return data as Product[]
}}
""", language="typescript")

        with _ex_react:
            st.markdown("A React hook that auto-refreshes when MERIT updates a product:")
            st.code(f"""\
// hooks/useProducts.ts
import {{ useEffect, useState }} from 'react'
import {{ supabase }} from '../lib/supabase'

export function useProducts(category?: string) {{
  const [products, setProducts] = useState([])
  const [loading, setLoading]   = useState(true)

  async function fetchProducts() {{
    let q = supabase
      .from('inventory')
      .select('*')
      .gt('stock_left', 0)
      .order('item_name')

    if (category) q = q.eq('category', category)

    const {{ data }} = await q
    setProducts(data ?? [])
    setLoading(false)
  }}

  useEffect(() => {{
    fetchProducts()

    // Subscribe so the page updates automatically when you change products in MERIT
    const channel = supabase
      .channel('merit-live')
      .on('postgres_changes', {{ event: '*', schema: 'public', table: 'inventory' }},
        () => fetchProducts()
      )
      .subscribe()

    return () => {{ supabase.removeChannel(channel) }}
  }}, [category])

  return {{ products, loading }}
}}

// Usage:
// const {{ products, loading }} = useProducts()          — all products
// const {{ products }} = useProducts('Apparel')          — filtered by category
""", language="typescript")

        with _ex_rt:
            st.markdown(
                "To make your site update **live** when you change something in MERIT, "
                "first enable Replication in Supabase Dashboard → Database → Replication → toggle `inventory` ON, "
                "then use this code:"
            )
            st.code(f"""\
import {{ createClient }} from '@supabase/supabase-js'

const supabase = createClient('{_sb_url_ph}', 'YOUR_SUPABASE_ANON_KEY')

// This runs every time MERIT adds, edits, or deletes a product
supabase
  .channel('merit-sync')
  .on('postgres_changes',
    {{ event: '*', schema: 'public', table: 'inventory' }},
    (payload) => {{
      console.log('MERIT changed a product:', payload.eventType)
      loadProducts()  // call your own function to re-fetch and re-render
    }}
  )
  .subscribe()
""", language="javascript")

    # ── Schema & Security SQL ─────────────────────────────────────────
    with _tab_schema:
        st.markdown("### Schema & Security SQL")
        st.markdown(
            "If you ever need to re-create the tables, or you need to grant your website read access, "
            "run the SQL below in **Supabase Dashboard → SQL Editor → New Query → Run**."
        )

        _schema_rls_intro, _schema_rls_sql = st.tabs(
            ["What does this SQL do?", "Copy the SQL"]
        )

        with _schema_rls_intro:
            st.markdown("""
**The SQL in the next tab does three things:**

1. **Creates the tables** MERIT needs (`inventory`, `products`, `outbound_logs`).
   The `IF NOT EXISTS` means it is safe to run even if the tables already exist — it won't overwrite anything.

2. **Enables Row Level Security (RLS)** — this is a Supabase feature that locks down your database
   so that random people on the internet cannot add, change, or delete your products even if they
   find your anon key. Think of it as a read-only lock.

3. **Adds a read policy** — this tells Supabase that anyone with the anon key is allowed to
   *read* (but not write) your products. This is what lets your website show the catalog.

**When to run it:**
- Once, right after creating your Supabase project and before going live with your website.
  MERIT's "Setup Tables" button in Settings creates the tables for you, but does not add the
  RLS policies — so you still need to run the Security section of this SQL.
            """)

        with _schema_rls_sql:
            _full_schema_sql_tab = SETUP_SQL.rstrip() + """

-- ════════════════════════════════════════════════════════════════════════
-- ROW LEVEL SECURITY — run this so your website can read products
-- ════════════════════════════════════════════════════════════════════════

ALTER TABLE inventory     ENABLE ROW LEVEL SECURITY;
ALTER TABLE products      ENABLE ROW LEVEL SECURITY;
ALTER TABLE outbound_logs ENABLE ROW LEVEL SECURITY;

-- Remove old policies first (safe to re-run)
DROP POLICY IF EXISTS "Public read inventory"     ON inventory;
DROP POLICY IF EXISTS "Public read products"      ON products;
DROP POLICY IF EXISTS "Public read outbound_logs" ON outbound_logs;

-- Allow any visitor to read products (they cannot write — RLS blocks that)
CREATE POLICY "Public read inventory"
  ON inventory FOR SELECT USING (true);

CREATE POLICY "Public read products"
  ON products FOR SELECT USING (true);

-- Uncomment the line below if you want your website to show order history too:
-- CREATE POLICY "Public read outbound_logs" ON outbound_logs FOR SELECT USING (true);

-- ════════════════════════════════════════════════════════════════════════
-- VERIFY: run this separately to confirm everything is set up correctly
-- Expected: 3 rows, rowsecurity = true, inventory and products show 1 policy
-- ════════════════════════════════════════════════════════════════════════
SELECT t.tablename, t.rowsecurity, COUNT(p.policyname) AS policies
FROM pg_tables t
LEFT JOIN pg_policies p ON p.tablename = t.tablename
WHERE t.schemaname = 'public'
  AND t.tablename IN ('inventory', 'products', 'outbound_logs')
GROUP BY t.tablename, t.rowsecurity
ORDER BY t.tablename;"""
            st.code(_full_schema_sql_tab, language="sql")


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

    tab_single, tab_bulk, tab_csv, tab_excel, tab_template, tab_campaign = st.tabs(
        ["Single Entry", "Bulk Entry", "CSV Import", "Excel Import", "Email Template", "Email Campaigns"]
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
                "Email":    st.column_config.TextColumn(width="medium"),
                "Order #":  st.column_config.TextColumn(width="small"),
                "Products": st.column_config.TextColumn(
                    width="medium",
                    help="Separate multiple products with |",
                ),
                "Subtotal": st.column_config.NumberColumn(width="small", format="$%.2f"),
                "Discount": st.column_config.NumberColumn(width="small", format="$%.2f"),
                "Tax":      st.column_config.NumberColumn(width="small", format="$%.2f"),
                "Shipping": st.column_config.NumberColumn(width="small", format="$%.2f"),
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
                    # Skip if any of the key fields are missing or zero (optional ones like tax/disc/ship can be 0)
                    if not on or on == "nan":
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
        st.markdown("#### Import from CSV files")
        st.caption("Provide both the Transactions and Items CSV files exported from VEI Checkout.")

        c_up1, c_up2 = st.columns(2)
        with c_up1:
            tx_csv = st.file_uploader("1. Sales Transactions CSV", type=["csv"], key="tx_csv_sep")
        with c_up2:
            items_csv = st.file_uploader("2. Sales Transaction Items CSV", type=["csv"], key="items_csv_sep")

        if st.button("Link and Import CSVs", type="primary", key="btn_csv_duo"):
            if not tx_csv or not items_csv:
                st.warning("Upload both CSV files.")
            else:
                with st.spinner("Linking data..."):
                    try:
                        t_raw = tx_csv.read().decode("utf-8", errors="replace")
                        i_raw = items_csv.read().decode("utf-8", errors="replace")
                        rows, warns = parse_multi_csv(t_raw, i_raw)
                        for w in warns: st.warning(w)
                        if rows:
                            st.session_state.queue.extend(rows)
                            st.toast(f"Imported {len(rows)} orders.", icon="📥")
                            st.success(f"Imported {len(rows)} linked orders into the queue.")
                            time.sleep(0.5)
                            st.rerun()
                        else:
                            st.error("No valid linked orders found.")
                    except Exception as e:
                        st.error(f"Error reading CSVs: {e}")

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

    # ── Email Campaigns ──────────────────────────
    with tab_campaign:
        st.markdown("#### Send a broadcast email to a list of contacts")
        st.caption(
            "Paste your contacts below, write a subject and HTML body, then send to everyone at once. "
            "Uses the same Gmail credentials as the order sender. "
            "Available variables: `{{name}}` and `{{from_name}}`."
        )

        _camp_cfg = st.session_state.cfg
        _camp_from = _camp_cfg.get("from_name", "")
        _camp_smtp_email = _camp_cfg.get("smtp_email", "").strip()
        _camp_smtp_pass  = (_camp_cfg.get("smtp_password", "") or "").replace(" ", "")

        if not _camp_smtp_email or not _camp_smtp_pass:
            st.warning("Configure your Gmail credentials in **Settings → Email** before sending campaigns.")

        _camp_col1, _camp_col2 = st.columns([1, 1])

        with _camp_col1:
            st.markdown("**Contacts**")
            st.caption("One per line. Format: `Name, email@example.com` or just `email@example.com`")
            _camp_contacts_raw = st.text_area(
                "Contacts",
                height=220,
                key="camp_contacts",
                label_visibility="collapsed",
                placeholder="Jane Smith, jane@example.com\nJohn Doe, john@example.com\nanother@example.com",
            )

            _camp_subject = st.text_input(
                "Subject Line",
                key="camp_subject",
                placeholder="Important update from your VEI firm",
            )

        with _camp_col2:
            st.markdown("**HTML Template**")
            st.caption("Use `{{name}}` for recipient name and `{{from_name}}` for your firm name.")
            _camp_tpl_raw = st.text_area(
                "Campaign HTML",
                value=_DEFAULT_CAMPAIGN_TEMPLATE,
                height=220,
                key="camp_html",
                label_visibility="collapsed",
            )

        _camp_prev_col, _camp_send_col = st.columns(2)
        with _camp_prev_col:
            if st.button("Preview Email", width="stretch", key="btn_camp_preview"):
                _camp_preview_html = (
                    _camp_tpl_raw
                    .replace("{{name}}", "Jane Smith")
                    .replace("{{from_name}}", _camp_from or "Your VEI Firm")
                )
                st.session_state["_camp_preview_html"] = _camp_preview_html

        if "_camp_preview_html" in st.session_state:
            with st.expander("Email Preview", expanded=True):
                st.components.v1.html(st.session_state["_camp_preview_html"], height=500, scrolling=True)

        # Parse contacts
        def _parse_campaign_contacts(raw: str) -> list[dict]:
            contacts = []
            for line in raw.strip().splitlines():
                line = line.strip()
                if not line:
                    continue
                if "," in line:
                    parts = line.split(",", 1)
                    name  = parts[0].strip()
                    email = parts[1].strip()
                else:
                    name  = line.split("@")[0].strip()
                    email = line.strip()
                if "@" in email:
                    contacts.append({"name": name, "email": email})
            return contacts

        _camp_contacts_parsed = _parse_campaign_contacts(_camp_contacts_raw or "")
        if _camp_contacts_parsed:
            st.caption(f"{len(_camp_contacts_parsed)} contact{'s' if len(_camp_contacts_parsed) != 1 else ''} ready to send.")

        with _camp_send_col:
            _camp_send_disabled = not (
                _camp_contacts_parsed and _camp_subject.strip()
                and _camp_smtp_email and _camp_smtp_pass
            )
            if st.button(
                f"Send to {len(_camp_contacts_parsed)} Contact{'s' if len(_camp_contacts_parsed) != 1 else ''}",
                type="primary",
                width="stretch",
                key="btn_camp_send",
                disabled=_camp_send_disabled,
            ):
                _camp_prog   = st.progress(0, text="Connecting to Gmail...")
                _camp_log_ph = st.empty()
                _camp_results = []
                _camp_sent = 0
                _camp_failed = 0

                try:
                    _camp_server = smtplib.SMTP("smtp.gmail.com", 587, timeout=15)
                    _camp_server.starttls()
                    _camp_server.login(_camp_smtp_email, _camp_smtp_pass)
                except Exception as _camp_exc:
                    st.error(f"Could not connect to Gmail: {_camp_exc}")
                    st.stop()

                for _ci, _contact in enumerate(_camp_contacts_parsed):
                    _camp_prog.progress(
                        _ci / len(_camp_contacts_parsed),
                        text=f"Sending {_ci + 1} of {len(_camp_contacts_parsed)}  —  {_contact['email']}",
                    )
                    _camp_html_rendered = (
                        _camp_tpl_raw
                        .replace("{{name}}", _contact["name"])
                        .replace("{{from_name}}", _camp_from or "")
                    )
                    _camp_text_rendered = (
                        f"Hi {_contact['name']},\n\n"
                        + "Please view this email in an HTML-capable email client.\n\n"
                        + (_camp_from or "")
                    )
                    _camp_msg = MIMEMultipart("alternative")
                    _camp_msg["From"]    = f"{_camp_from} <{_camp_smtp_email}>"
                    _camp_msg["To"]      = _contact["email"]
                    _camp_msg["Subject"] = _camp_subject.strip()
                    _camp_msg.attach(MIMEText(_camp_text_rendered, "plain"))
                    _camp_msg.attach(MIMEText(_camp_html_rendered, "html"))

                    try:
                        _camp_server.send_message(_camp_msg)
                        _camp_results.append({"#": _ci + 1, "Name": _contact["name"], "Email": _contact["email"], "Status": "Sent"})
                        _camp_sent += 1
                    except Exception as _camp_err:
                        _camp_results.append({"#": _ci + 1, "Name": _contact["name"], "Email": _contact["email"], "Status": f"Failed: {str(_camp_err)[:60]}"})
                        _camp_failed += 1

                    _camp_log_ph.dataframe(pd.DataFrame(_camp_results), use_container_width=True, hide_index=True)
                    time.sleep(0.2)

                _camp_server.quit()
                _camp_prog.progress(1.0, text="Done")
                st.success(f"Campaign complete — {_camp_sent} sent, {_camp_failed} failed.")

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
        header_col, action_col = st.columns([10, 2])
        with header_col:
            st.subheader(f"Queue  —  {len(queue)} order{'s' if len(queue) != 1 else ''}")
        with action_col:
            st.markdown("<div style='margin-top:10px;'></div>", unsafe_allow_html=True)
            if st.button("Clear All", key="clear_queue", width="stretch"):
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
            _has_sb_send  = _has_supabase(cfg)
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

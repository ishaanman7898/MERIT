"""
MERIT — Mass Email & Inventory Tool for Virtual Enterprise (VEI) firms
Gmail SMTP · Freeimage.host / Imghippo image hosting · Supabase / Turso database
"""

import base64
import csv
import hashlib
import io
import json
import os as _os
import re
import smtplib
import time
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.image import MIMEImage
from datetime import datetime
import urllib.request as _urllib_request
from pathlib import Path
import warnings

# Suppress Pandas warnings about non-SQLAlchemy connectable (sqlite3 / psycopg2)
warnings.filterwarnings("ignore", ".*SQLAlchemy.*")
warnings.filterwarnings("ignore", ".*DBAPI2.*")

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


def _sqlite_read_sql(conn, sql: str, params=()) -> "pd.DataFrame":
    """Execute SQL on a sqlite3 connection and return a DataFrame without using pd.read_sql."""
    cur = conn.execute(sql, params)
    cols = [d[0] for d in cur.description] if cur.description else []
    return pd.DataFrame([dict(zip(cols, row)) for row in cur.fetchall()], columns=cols if cols else None)

def _init_sqlite():
    conn = _get_sqlite_conn()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS products (
            sku            TEXT PRIMARY KEY,
            item_name      TEXT NOT NULL,
            category       TEXT NOT NULL DEFAULT '',
            price          REAL NOT NULL DEFAULT 0.0,
            description    TEXT NOT NULL DEFAULT '',
            buy_button_url TEXT NOT NULL DEFAULT '',
            image_url      TEXT NOT NULL DEFAULT 'N/A',
            active         INTEGER NOT NULL DEFAULT 1,
            created_at     TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS inventory (
            sku        TEXT PRIMARY KEY,
            item_name  TEXT NOT NULL,
            category   TEXT NOT NULL DEFAULT '',
            price      REAL NOT NULL DEFAULT 0.0,
            unit_cost  REAL NOT NULL DEFAULT 0.0,
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
        CREATE TABLE IF NOT EXISTS email_templates (
            template_key TEXT PRIMARY KEY,
            html_content TEXT NOT NULL DEFAULT '',
            updated_at   TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS users (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            email         TEXT NOT NULL UNIQUE,
            full_name     TEXT NOT NULL DEFAULT '',
            role          TEXT NOT NULL DEFAULT 'staff',
            password_hash TEXT NOT NULL DEFAULT '',
            invite_token  TEXT,
            created_at    TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS roles (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            role_name  TEXT NOT NULL UNIQUE,
            pages      TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS financials (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            entry_date      TEXT    NOT NULL DEFAULT (date('now')),
            category        TEXT    NOT NULL DEFAULT 'Expense',
            description     TEXT    NOT NULL DEFAULT '',
            amount          REAL    NOT NULL DEFAULT 0.0,
            notes           TEXT    NOT NULL DEFAULT '',
            payment_method  TEXT    NOT NULL DEFAULT '',
            tags            TEXT    NOT NULL DEFAULT '',
            is_recurring    INTEGER NOT NULL DEFAULT 0,
            recur_frequency TEXT    NOT NULL DEFAULT '',
            created_at      TEXT    NOT NULL DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS fin_budgets (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            category      TEXT    NOT NULL,
            period        TEXT    NOT NULL DEFAULT 'monthly',
            budget_amount REAL    NOT NULL DEFAULT 0.0,
            notes         TEXT    NOT NULL DEFAULT '',
            created_at    TEXT    NOT NULL DEFAULT (datetime('now')),
            UNIQUE(category, period)
        );
    """)
    conn.commit()
    # Migrate existing financials table — add columns if missing
    try:
        _fin_cols = [r[1] for r in conn.execute("PRAGMA table_info(financials)").fetchall()]
        for _fc_name, _fc_def in [
            ("payment_method",  "TEXT NOT NULL DEFAULT ''"),
            ("tags",            "TEXT NOT NULL DEFAULT ''"),
            ("is_recurring",    "INTEGER NOT NULL DEFAULT 0"),
            ("recur_frequency", "TEXT NOT NULL DEFAULT ''"),
        ]:
            if _fc_name not in _fin_cols:
                conn.execute(f"ALTER TABLE financials ADD COLUMN {_fc_name} {_fc_def}")
        conn.commit()
    except Exception:
        pass
    # Seed default roles if the table is empty
    try:
        _rc = conn.execute("SELECT COUNT(*) FROM roles").fetchone()[0]
        if _rc == 0:
            conn.executemany(
                "INSERT OR IGNORE INTO roles (role_name, pages) VALUES (?, ?)",
                [
                    ("admin",  "Mass Email,Products,Inventory,Financials,Settings,API Endpoints"),
                    ("staff",  "Mass Email,Products,Inventory,Financials"),
                    ("viewer", "Inventory,Financials"),
                ]
            )
            conn.commit()
    except Exception: pass

    # Migration: add Financials to default role pages if missing
    try:
        _default_pages = {
            "admin":  "Mass Email,Products,Inventory,Financials,Settings,API Endpoints",
            "staff":  "Mass Email,Products,Inventory,Financials",
            "viewer": "Inventory,Financials",
        }
        for _rn, _rp in _default_pages.items():
            _row = conn.execute("SELECT pages FROM roles WHERE role_name=?", (_rn,)).fetchone()
            if _row and "Financials" not in str(_row[0]):
                conn.execute("UPDATE roles SET pages=? WHERE role_name=?", (_rp, _rn))
        conn.commit()
    except Exception: pass

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

    # Migration for existing products table (add description, buy_button_url, active)
    try:
        cur = conn.cursor()
        cur.execute("PRAGMA table_info(products)")
        _prod_cols = [r[1] for r in cur.fetchall()]
        if "description" not in _prod_cols:
            conn.execute("ALTER TABLE products ADD COLUMN description TEXT NOT NULL DEFAULT ''")
        if "buy_button_url" not in _prod_cols:
            conn.execute("ALTER TABLE products ADD COLUMN buy_button_url TEXT NOT NULL DEFAULT ''")
        if "active" not in _prod_cols:
            conn.execute("ALTER TABLE products ADD COLUMN active INTEGER NOT NULL DEFAULT 1")
        conn.commit()
    except Exception: pass

    # Migration for users table (add invite_token)
    try:
        cur = conn.cursor()
        cur.execute("PRAGMA table_info(users)")
        _user_cols = [r[1] for r in cur.fetchall()]
        if "invite_token" not in _user_cols:
            conn.execute("ALTER TABLE users ADD COLUMN invite_token TEXT")
            conn.commit()
    except Exception: pass

    conn.close()

_init_sqlite()


def _clear_data_caches():
    """Clear both the @st.cache_data function cache and the per-session state caches."""
    st.cache_data.clear()
    st.session_state.pop("_products_cache", None)
    st.session_state.pop("_inv_cache", None)


def _parse_product_qty(pname: str) -> tuple:
    """Parse 'Product Name x 3' → ('Product Name', 3). Plain names return qty=1."""
    m = re.match(r'^(.+?)\s+x\s+(\d+)$', pname.strip(), re.IGNORECASE)
    if m:
        return m.group(1).strip(), int(m.group(2))
    return pname.strip(), 1


# ─────────────────────────────────────────────
# Role-based access control
# ─────────────────────────────────────────────

_ALL_PAGES = ["Mass Email", "Products", "Inventory", "Financials", "Settings", "API Endpoints"]

# Fallback role→pages map used before DB is available
_ROLE_PAGES = {
    "admin":  list(_ALL_PAGES),
    "staff":  ["Mass Email", "Products", "Inventory", "Financials"],
    "viewer": ["Inventory", "Financials"],
}

_ROLE_LABELS = {
    "admin":  "Admin — full access",
    "staff":  "Staff — Email, Products, Inventory, Financials",
    "viewer": "Viewer — Inventory & Financials",
}


def _hash_password(password: str) -> str:
    salt = _os.urandom(32)
    key = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 100_000)
    return salt.hex() + ":" + key.hex()


def _verify_password(stored_hash: str, password: str) -> bool:
    try:
        salt_hex, key_hex = stored_hash.split(":", 1)
        salt = bytes.fromhex(salt_hex)
        key = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 100_000)
        return key.hex() == key_hex
    except Exception:
        return False


@st.cache_data(ttl=30, show_spinner=False)
def _fetch_users_cached(sb_conn_str: str, turso_key: str = "") -> list:
    """Cached fetch of users — takes hashable conn string, returns list of row dicts."""
    if sb_conn_str:
        try:
            conn = _psycopg2_connect(sb_conn_str, connect_timeout=5)
            with conn.cursor() as cur:
                cur.execute("SELECT id, email, full_name, role, created_at FROM users ORDER BY created_at")
                cols = [d[0] for d in cur.description]
                rows = [dict(zip(cols, row)) for row in cur.fetchall()]
            conn.close()
            if rows:
                return rows
        except Exception:
            pass
    if turso_key:
        try:
            _tu, _tt = turso_key.split("|", 1)
            rows = _turso_execute_direct(_tu, _tt,
                "SELECT id, email, full_name, role, created_at FROM users ORDER BY created_at")
            if rows:
                return rows
        except Exception:
            pass
    try:
        conn = _get_sqlite_conn()
        df = _sqlite_read_sql(conn, "SELECT id, email, full_name, role, created_at FROM users ORDER BY created_at")
        conn.close()
        return df.to_dict("records")
    except Exception:
        return []


def get_users_from_db(cfg: dict) -> pd.DataFrame:
    """Load users table from Supabase (preferred), Turso, or SQLite fallback. Result is cached 30s."""
    sb_cs = _get_effective_supabase_conn_str(cfg) or ""
    rows = _fetch_users_cached(sb_cs, _turso_cache_key(cfg))
    return pd.DataFrame(rows) if rows else pd.DataFrame()


@st.cache_data(ttl=30, show_spinner=False)
def _fetch_roles_cached(sb_conn_str: str, turso_key: str = "") -> list:
    """Cached fetch of roles — takes hashable conn string, returns list of row dicts."""
    if sb_conn_str:
        try:
            conn = _psycopg2_connect(sb_conn_str, connect_timeout=5)
            with conn.cursor() as cur:
                cur.execute("SELECT role_name, pages FROM roles ORDER BY role_name")
                cols = [d[0] for d in cur.description]
                rows = [dict(zip(cols, row)) for row in cur.fetchall()]
            conn.close()
            if rows:
                return rows
        except Exception:
            pass
    if turso_key:
        try:
            _tu, _tt = turso_key.split("|", 1)
            rows = _turso_execute_direct(_tu, _tt,
                "SELECT role_name, pages FROM roles ORDER BY role_name")
            if rows:
                return rows
        except Exception:
            pass
    try:
        conn = _get_sqlite_conn()
        df = _sqlite_read_sql(conn, "SELECT role_name, pages FROM roles ORDER BY role_name")
        conn.close()
        return df.to_dict("records")
    except Exception:
        return []


def get_roles_from_db(cfg: dict) -> pd.DataFrame:
    """Load roles table from Supabase (preferred), Turso, or SQLite fallback. Result is cached 30s."""
    sb_cs = _get_effective_supabase_conn_str(cfg) or ""
    rows = _fetch_roles_cached(sb_cs, _turso_cache_key(cfg))
    return pd.DataFrame(rows) if rows else pd.DataFrame()


def get_pages_for_role(role_name: str, cfg: dict) -> list:
    """Return list of page names for a given role. Falls back to _ROLE_PAGES dict."""
    roles_df = get_roles_from_db(cfg)
    if not roles_df.empty and role_name in roles_df["role_name"].values:
        row = roles_df[roles_df["role_name"] == role_name].iloc[0]
        return [p.strip() for p in str(row.get("pages", "")).split(",") if p.strip()]
    return list(_ROLE_PAGES.get(role_name, _ROLE_PAGES["admin"]))


def create_role_all_dbs(role_name: str, pages: list, cfg: dict) -> tuple[bool, str]:
    """Create or update a role in SQLite, Supabase, and Turso."""
    pages_str = ",".join(pages)
    results = []
    try:
        conn = _get_sqlite_conn()
        conn.execute(
            "INSERT INTO roles (role_name, pages) VALUES (?, ?) "
            "ON CONFLICT(role_name) DO UPDATE SET pages=excluded.pages",
            (role_name.lower().strip(), pages_str)
        )
        conn.commit()
        conn.close()
        results.append("SQLite")
    except Exception as exc:
        results.append(f"SQLite failed: {exc}")
    conn_sb = _get_supabase_conn(cfg)
    if conn_sb is not None:
        try:
            with conn_sb:
                with conn_sb.cursor() as cur:
                    cur.execute(
                        "INSERT INTO roles (role_name, pages) VALUES (%s, %s) "
                        "ON CONFLICT (role_name) DO UPDATE SET pages=EXCLUDED.pages",
                        (role_name.lower().strip(), pages_str)
                    )
            conn_sb.close()
            results.append("Supabase")
        except Exception as exc:
            results.append(f"Supabase failed: {exc}")
    if _has_turso(cfg):
        try:
            _turso_execute(cfg,
                "INSERT INTO roles (role_name, pages) VALUES (?, ?) "
                "ON CONFLICT(role_name) DO UPDATE SET pages=excluded.pages",
                (role_name.lower().strip(), pages_str))
            results.append("Turso")
        except Exception as exc:
            results.append(f"Turso failed: {exc}")
    return any("failed" not in r for r in results), " · ".join(results)


def delete_role_all_dbs(role_name: str, cfg: dict) -> tuple[bool, str]:
    """Delete a role from SQLite, Supabase, and Turso. Refuses to delete built-in roles."""
    if role_name in ("admin", "staff", "viewer"):
        return False, "Cannot delete built-in roles."
    results = []
    try:
        conn = _get_sqlite_conn()
        conn.execute("DELETE FROM roles WHERE role_name=?", (role_name,))
        conn.commit()
        conn.close()
        results.append("SQLite")
    except Exception as exc:
        results.append(f"SQLite failed: {exc}")
    conn_sb = _get_supabase_conn(cfg)
    if conn_sb is not None:
        try:
            with conn_sb:
                with conn_sb.cursor() as cur:
                    cur.execute("DELETE FROM roles WHERE role_name=%s", (role_name,))
            conn_sb.close()
            results.append("Supabase")
        except Exception as exc:
            results.append(f"Supabase failed: {exc}")
    if _has_turso(cfg):
        try:
            _turso_execute(cfg, "DELETE FROM roles WHERE role_name=?", (role_name,))
            results.append("Turso")
        except Exception as exc:
            results.append(f"Turso failed: {exc}")
    return any("failed" not in r for r in results), " · ".join(results)


def sync_local_to_supabase(cfg: dict) -> tuple[int, int, list]:
    """Sync all local SQLite users and roles to Supabase. Returns (users_synced, roles_synced, errors)."""
    errors = []
    users_synced = 0
    roles_synced = 0
    conn_sb = _get_supabase_conn(cfg)
    if conn_sb is None:
        return 0, 0, ["Supabase not connected"]
    try:
        # Sync roles
        local_conn = _get_sqlite_conn()
        local_roles = local_conn.execute("SELECT role_name, pages FROM roles").fetchall()
        with conn_sb:
            with conn_sb.cursor() as cur:
                for row in local_roles:
                    try:
                        cur.execute(
                            "INSERT INTO roles (role_name, pages) VALUES (%s, %s) "
                            "ON CONFLICT (role_name) DO UPDATE SET pages=EXCLUDED.pages",
                            (row["role_name"], row["pages"])
                        )
                        roles_synced += 1
                    except Exception as e:
                        errors.append(f"Role {row['role_name']}: {e}")
        # Sync users
        local_users = local_conn.execute("SELECT email, full_name, role, password_hash FROM users").fetchall()
        with conn_sb:
            with conn_sb.cursor() as cur:
                for row in local_users:
                    try:
                        cur.execute(
                            "INSERT INTO users (email, full_name, role, password_hash) VALUES (%s, %s, %s, %s) "
                            "ON CONFLICT (email) DO UPDATE SET full_name=EXCLUDED.full_name, role=EXCLUDED.role",
                            (row["email"], row["full_name"], row["role"], row["password_hash"])
                        )
                        users_synced += 1
                    except Exception as e:
                        errors.append(f"User {row['email']}: {e}")
        local_conn.close()
        conn_sb.close()
    except Exception as e:
        errors.append(str(e))
    return users_synced, roles_synced, errors


def create_user_all_dbs(email: str, full_name: str, role: str, password: str, cfg: dict) -> tuple[bool, str]:
    """Create a new user in SQLite, Supabase, and Turso."""
    pw_hash = _hash_password(password)
    results = []
    # SQLite
    try:
        conn = _get_sqlite_conn()
        conn.execute(
            "INSERT INTO users (email, full_name, role, password_hash) VALUES (?, ?, ?, ?)",
            (email.lower().strip(), full_name.strip(), role, pw_hash)
        )
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
                    cur.execute(
                        "INSERT INTO users (email, full_name, role, password_hash) VALUES (%s, %s, %s, %s)",
                        (email.lower().strip(), full_name.strip(), role, pw_hash)
                    )
            conn_sb.close()
            results.append("Supabase")
        except Exception as exc:
            results.append(f"Supabase failed: {exc}")
    # Turso
    if _has_turso(cfg):
        try:
            _turso_execute(cfg,
                "INSERT INTO users (email, full_name, role, password_hash) VALUES (?,?,?,?)",
                (email.lower().strip(), full_name.strip(), role, pw_hash))
            results.append("Turso")
        except Exception as exc:
            results.append(f"Turso failed: {exc}")
    return any("failed" not in r for r in results), " · ".join(results)


def delete_user_all_dbs(email: str, cfg: dict) -> tuple[bool, str]:
    """Delete a user by email from SQLite, Supabase, and Turso."""
    results = []
    try:
        conn = _get_sqlite_conn()
        conn.execute("DELETE FROM users WHERE email=?", (email.lower().strip(),))
        conn.commit()
        conn.close()
        results.append("SQLite")
    except Exception as exc:
        results.append(f"SQLite failed: {exc}")
    conn_sb = _get_supabase_conn(cfg)
    if conn_sb is not None:
        try:
            with conn_sb:
                with conn_sb.cursor() as cur:
                    cur.execute("DELETE FROM users WHERE email=%s", (email.lower().strip(),))
            conn_sb.close()
            results.append("Supabase")
        except Exception as exc:
            results.append(f"Supabase failed: {exc}")
    if _has_turso(cfg):
        try:
            _turso_execute(cfg, "DELETE FROM users WHERE email=?", (email.lower().strip(),))
            results.append("Turso")
        except Exception as exc:
            results.append(f"Turso failed: {exc}")
    return any("failed" not in r for r in results), " · ".join(results)


def create_user_with_invite(email: str, full_name: str, role: str, cfg: dict) -> tuple[bool, str, str]:
    """Create a user without a password via invite link. Returns (ok, message, invite_token)."""
    token = hashlib.sha256(
        f"{email}{time.time()}{_os.urandom(16).hex()}".encode()
    ).hexdigest()[:48]
    placeholder_hash = f"INVITE_PENDING:{token}"
    results = []
    try:
        conn = _get_sqlite_conn()
        conn.execute(
            "INSERT INTO users (email, full_name, role, password_hash, invite_token) VALUES (?, ?, ?, ?, ?)",
            (email.lower().strip(), full_name.strip(), role, placeholder_hash, token)
        )
        conn.commit()
        conn.close()
        results.append("SQLite")
    except Exception as exc:
        results.append(f"SQLite failed: {exc}")
    conn_sb = _get_supabase_conn(cfg)
    if conn_sb is not None:
        try:
            with conn_sb:
                with conn_sb.cursor() as cur:
                    cur.execute(
                        "INSERT INTO users (email, full_name, role, password_hash, invite_token) VALUES (%s, %s, %s, %s, %s)",
                        (email.lower().strip(), full_name.strip(), role, placeholder_hash, token)
                    )
            conn_sb.close()
            results.append("Supabase")
        except Exception as exc:
            results.append(f"Supabase failed: {exc}")
    if _has_turso(cfg):
        try:
            _turso_execute(cfg,
                "INSERT INTO users (email, full_name, role, password_hash, invite_token) VALUES (?,?,?,?,?)",
                (email.lower().strip(), full_name.strip(), role, placeholder_hash, token))
            results.append("Turso")
        except Exception as exc:
            results.append(f"Turso failed: {exc}")
    ok = any("failed" not in r for r in results)
    return ok, " · ".join(results), token if ok else ""


def validate_invite_token(token: str, cfg: dict) -> dict | None:
    """Return user info dict if invite token is valid and unused, else None."""
    if not token:
        return None
    _sb_cs = _get_effective_supabase_conn_str(cfg)
    if _sb_cs:
        try:
            conn = _psycopg2_connect(_sb_cs)
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT email, full_name, role FROM users WHERE invite_token=%s", (token,)
                )
                row = cur.fetchone()
            conn.close()
            if row:
                return {"email": row[0], "full_name": row[1], "role": row[2]}
        except Exception:
            pass
    if _has_turso(cfg):
        try:
            rows = _turso_execute(cfg,
                "SELECT email, full_name, role FROM users WHERE invite_token=?", (token,))
            if rows:
                return {"email": rows[0]["email"], "full_name": rows[0]["full_name"], "role": rows[0]["role"]}
        except Exception:
            pass
    try:
        conn = _get_sqlite_conn()
        row = conn.execute(
            "SELECT email, full_name, role FROM users WHERE invite_token=?", (token,)
        ).fetchone()
        conn.close()
        if row:
            return {"email": row["email"], "full_name": row["full_name"], "role": row["role"]}
    except Exception:
        pass
    return None


def complete_invite(token: str, new_password: str, cfg: dict) -> tuple[bool, str]:
    """Set password and clear invite token, completing the new-user onboarding."""
    pw_hash = _hash_password(new_password)
    results = []
    try:
        conn = _get_sqlite_conn()
        conn.execute(
            "UPDATE users SET password_hash=?, invite_token=NULL WHERE invite_token=?",
            (pw_hash, token)
        )
        conn.commit()
        conn.close()
        results.append("SQLite")
    except Exception as exc:
        results.append(f"SQLite failed: {exc}")
    conn_sb = _get_supabase_conn(cfg)
    if conn_sb is not None:
        try:
            with conn_sb:
                with conn_sb.cursor() as cur:
                    cur.execute(
                        "UPDATE users SET password_hash=%s, invite_token=NULL WHERE invite_token=%s",
                        (pw_hash, token)
                    )
            conn_sb.close()
            results.append("Supabase")
        except Exception as exc:
            results.append(f"Supabase failed: {exc}")
    if _has_turso(cfg):
        try:
            _turso_execute(cfg,
                "UPDATE users SET password_hash=?, invite_token=NULL WHERE invite_token=?",
                (pw_hash, token))
            results.append("Turso")
        except Exception as exc:
            results.append(f"Turso failed: {exc}")
    return any("failed" not in r for r in results), " · ".join(results)


def generate_new_invite_token(email: str, cfg: dict) -> tuple[bool, str]:
    """Regenerate an invite token for an existing user. Returns (ok, token)."""
    token = hashlib.sha256(
        f"{email}{time.time()}{_os.urandom(16).hex()}".encode()
    ).hexdigest()[:48]
    results = []
    try:
        conn = _get_sqlite_conn()
        conn.execute("UPDATE users SET invite_token=? WHERE email=?", (token, email.lower().strip()))
        conn.commit()
        conn.close()
        results.append("SQLite")
    except Exception as exc:
        results.append(f"SQLite failed: {exc}")
    conn_sb = _get_supabase_conn(cfg)
    if conn_sb is not None:
        try:
            with conn_sb:
                with conn_sb.cursor() as cur:
                    cur.execute(
                        "UPDATE users SET invite_token=%s WHERE email=%s", (token, email.lower().strip())
                    )
            conn_sb.close()
            results.append("Supabase")
        except Exception as exc:
            results.append(f"Supabase failed: {exc}")
    if _has_turso(cfg):
        try:
            _turso_execute(cfg,
                "UPDATE users SET invite_token=? WHERE email=?", (token, email.lower().strip()))
            results.append("Turso")
        except Exception as exc:
            results.append(f"Turso failed: {exc}")
    ok = any("failed" not in r for r in results)
    return ok, token if ok else ""


def update_user_role_all_dbs(email: str, new_role: str, cfg: dict) -> tuple[bool, str]:
    """Update a user's role in SQLite, Supabase, and Turso."""
    results = []
    try:
        conn = _get_sqlite_conn()
        conn.execute("UPDATE users SET role=? WHERE email=?", (new_role, email.lower().strip()))
        conn.commit()
        conn.close()
        results.append("SQLite")
    except Exception as exc:
        results.append(f"SQLite failed: {exc}")
    conn_sb = _get_supabase_conn(cfg)
    if conn_sb is not None:
        try:
            with conn_sb:
                with conn_sb.cursor() as cur:
                    cur.execute("UPDATE users SET role=%s WHERE email=%s", (new_role, email.lower().strip()))
            conn_sb.close()
            results.append("Supabase")
        except Exception as exc:
            results.append(f"Supabase failed: {exc}")
    if _has_turso(cfg):
        try:
            _turso_execute(cfg, "UPDATE users SET role=? WHERE email=?", (new_role, email.lower().strip()))
            results.append("Turso")
        except Exception as exc:
            results.append(f"Turso failed: {exc}")
    return any("failed" not in r for r in results), " · ".join(results)


def authenticate_user(email: str, password: str, cfg: dict) -> dict | None:
    """Return user dict {email, full_name, role, pages} if credentials valid, else None."""
    _em = email.lower().strip()
    user = None
    # Try Supabase first
    _sb_cs = _get_effective_supabase_conn_str(cfg)
    if _sb_cs:
        try:
            conn = _psycopg2_connect(_sb_cs)
            with conn.cursor() as cur:
                cur.execute("SELECT email, full_name, role, password_hash FROM users WHERE email=%s", (_em,))
                row = cur.fetchone()
            conn.close()
            if row and _verify_password(row[3], password):
                user = {"email": row[0], "full_name": row[1], "role": row[2]}
        except Exception:
            pass
    # Try Turso
    if user is None and _has_turso(cfg):
        try:
            rows = _turso_execute(cfg,
                "SELECT email, full_name, role, password_hash FROM users WHERE email=?", (_em,))
            if rows and _verify_password(rows[0]["password_hash"] or "", password):
                user = {"email": rows[0]["email"], "full_name": rows[0]["full_name"], "role": rows[0]["role"]}
        except Exception:
            pass
    # Fall back to SQLite
    if user is None:
        try:
            conn = _get_sqlite_conn()
            row = conn.execute(
                "SELECT email, full_name, role, password_hash FROM users WHERE email=?", (_em,)
            ).fetchone()
            conn.close()
            if row and _verify_password(row["password_hash"], password):
                user = {"email": row["email"], "full_name": row["full_name"], "role": row["role"]}
        except Exception:
            pass
    if user is None:
        return None
    # Load this role's page permissions from DB
    user["pages"] = get_pages_for_role(user["role"], cfg)
    return user


def save_email_template(key: str, html: str, cfg: dict) -> bool:
    """Save an email template to SQLite, Supabase, and Turso."""
    try:
        conn = _get_sqlite_conn()
        conn.execute("""
            INSERT INTO email_templates (template_key, html_content)
            VALUES (?, ?)
            ON CONFLICT(template_key) DO UPDATE SET
                html_content=excluded.html_content,
                updated_at=datetime('now')
        """, (key, html))
        conn.commit()
        conn.close()
    except Exception: pass

    conn_sb = _get_supabase_conn(cfg)
    if conn_sb is not None:
        try:
            with conn_sb:
                with conn_sb.cursor() as cur:
                    cur.execute("""
                        INSERT INTO email_templates (template_key, html_content)
                        VALUES (%s, %s)
                        ON CONFLICT(template_key) DO UPDATE SET
                            html_content=EXCLUDED.html_content,
                            updated_at=NOW()
                    """, (key, html))
            conn_sb.close()
        except Exception: pass

    if _has_turso(cfg):
        try:
            _turso_execute(cfg,
                "INSERT INTO email_templates (template_key, html_content) VALUES (?,?) "
                "ON CONFLICT(template_key) DO UPDATE SET html_content=excluded.html_content, "
                "updated_at=datetime('now')",
                (key, html))
        except Exception: pass
    return True


def load_email_template(key: str, cfg: dict) -> str:
    """Load an email template by key. Returns '' if not found."""
    # Try Supabase first
    conn_sb = _get_supabase_conn(cfg)
    if conn_sb is not None:
        try:
            with conn_sb.cursor() as cur:
                cur.execute("SELECT html_content FROM email_templates WHERE template_key=%s", (key,))
                row = cur.fetchone()
            conn_sb.close()
            if row and row[0]:
                return row[0]
        except Exception: pass
    # Try Turso
    if _has_turso(cfg):
        try:
            rows = _turso_execute(cfg,
                "SELECT html_content FROM email_templates WHERE template_key=?", (key,))
            if rows and rows[0].get("html_content"):
                return rows[0]["html_content"]
        except Exception: pass
    # Fall back to SQLite
    try:
        conn = _get_sqlite_conn()
        row = conn.execute("SELECT html_content FROM email_templates WHERE template_key=?", (key,)).fetchone()
        conn.close()
        if row and row[0]:
            return row[0]
    except Exception: pass
    return ""


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
    image_url      TEXT           NOT NULL DEFAULT 'N/A', -- one URL or comma-separated multiple: "url1,url2"
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
    id              BIGSERIAL      PRIMARY KEY,
    sku             TEXT           NOT NULL,
    name            TEXT           NOT NULL,
    category        TEXT           NOT NULL DEFAULT '',
    price           NUMERIC(10,2)  NOT NULL DEFAULT 0.00,
    description     TEXT           NOT NULL DEFAULT '',
    buy_button_url  TEXT           NOT NULL DEFAULT '',
    image_url       TEXT           NOT NULL DEFAULT 'N/A', -- one URL or comma-separated multiple: "url1,url2"
    active          BOOLEAN        NOT NULL DEFAULT TRUE,  -- true = In Store, false = Out of Store
    created_at      TIMESTAMPTZ    NOT NULL DEFAULT NOW(),
    CONSTRAINT products_sku_unique UNIQUE (sku)
);

-- Migrations for existing users (buy_button_url)
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='products' AND column_name='buy_button_url') THEN
    ALTER TABLE products ADD COLUMN buy_button_url TEXT NOT NULL DEFAULT '';
  END IF;
END $$;

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

-- ── Email templates (custom HTML templates) ──────────────────────────────
CREATE TABLE IF NOT EXISTS email_templates (
    id           BIGSERIAL     PRIMARY KEY,
    template_key TEXT          NOT NULL UNIQUE,  -- 'order_template' | 'campaign_template'
    html_content TEXT          NOT NULL DEFAULT '',
    updated_at   TIMESTAMPTZ   NOT NULL DEFAULT NOW()
);

-- ── Users table (multi-user sign-in) ─────────────────────────────────────
CREATE TABLE IF NOT EXISTS users (
    id            BIGSERIAL      PRIMARY KEY,
    email         TEXT           NOT NULL UNIQUE,
    full_name     TEXT           NOT NULL DEFAULT '',
    role          TEXT           NOT NULL DEFAULT 'staff',
    password_hash TEXT           NOT NULL DEFAULT '',
    invite_token  TEXT,
    created_at    TIMESTAMPTZ    NOT NULL DEFAULT NOW()
);

-- Migration for existing users (add invite_token column)
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='users' AND column_name='invite_token') THEN
    ALTER TABLE users ADD COLUMN invite_token TEXT;
  END IF;
END $$;

-- ── Roles table (custom role definitions) ────────────────────────────────
CREATE TABLE IF NOT EXISTS roles (
    id         BIGSERIAL     PRIMARY KEY,
    role_name  TEXT          NOT NULL UNIQUE,
    pages      TEXT          NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ   NOT NULL DEFAULT NOW()
);

-- Seed default roles (safe to run multiple times)
INSERT INTO roles (role_name, pages) VALUES
    ('admin',  'Mass Email,Products,Inventory,Financials,Settings,API Endpoints'),
    ('staff',  'Mass Email,Products,Inventory,Financials'),
    ('viewer', 'Inventory,Financials')
ON CONFLICT (role_name) DO NOTHING;

-- Migration: add Financials to default roles if missing
UPDATE roles SET pages = 'Mass Email,Products,Inventory,Financials,Settings,API Endpoints' WHERE role_name = 'admin' AND pages NOT LIKE '%Financials%';
UPDATE roles SET pages = 'Mass Email,Products,Inventory,Financials' WHERE role_name = 'staff' AND pages NOT LIKE '%Financials%';
UPDATE roles SET pages = 'Inventory,Financials' WHERE role_name = 'viewer' AND pages NOT LIKE '%Financials%';

-- ── Financials table (manual ledger entries) ────────────────────────────
CREATE TABLE IF NOT EXISTS financials (
    id              BIGSERIAL      PRIMARY KEY,
    entry_date      DATE           NOT NULL DEFAULT CURRENT_DATE,
    category        TEXT           NOT NULL DEFAULT 'Expense',
    description     TEXT           NOT NULL DEFAULT '',
    amount          NUMERIC(12,2)  NOT NULL DEFAULT 0.00,
    notes           TEXT           NOT NULL DEFAULT '',
    payment_method  TEXT           NOT NULL DEFAULT '',
    tags            TEXT           NOT NULL DEFAULT '',
    is_recurring    BOOLEAN        NOT NULL DEFAULT FALSE,
    recur_frequency TEXT           NOT NULL DEFAULT '',
    created_at      TIMESTAMPTZ    NOT NULL DEFAULT NOW()
);

-- Migrate existing financials table — add columns if missing
DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='financials' AND column_name='payment_method') THEN
        ALTER TABLE financials ADD COLUMN payment_method TEXT NOT NULL DEFAULT '';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='financials' AND column_name='tags') THEN
        ALTER TABLE financials ADD COLUMN tags TEXT NOT NULL DEFAULT '';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='financials' AND column_name='is_recurring') THEN
        ALTER TABLE financials ADD COLUMN is_recurring BOOLEAN NOT NULL DEFAULT FALSE;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='financials' AND column_name='recur_frequency') THEN
        ALTER TABLE financials ADD COLUMN recur_frequency TEXT NOT NULL DEFAULT '';
    END IF;
END $$;

-- ── Budgets table (category budget targets) ──────────────────────────────
CREATE TABLE IF NOT EXISTS fin_budgets (
    id            BIGSERIAL      PRIMARY KEY,
    category      TEXT           NOT NULL,
    period        TEXT           NOT NULL DEFAULT 'monthly',
    budget_amount NUMERIC(12,2)  NOT NULL DEFAULT 0.00,
    notes         TEXT           NOT NULL DEFAULT '',
    created_at    TIMESTAMPTZ    NOT NULL DEFAULT NOW(),
    UNIQUE(category, period)
);

-- Add your own tables below this line ──────────────────────────────────────
"""


_SECRETS_CREDENTIAL_KEYS = [
    "supabase_connection_string",
    "supabase_db_password",
    "supabase_anon_key",
    "turso_url",
    "turso_auth_token",
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
    if resp.status_code == 200 and str(body.get("status_code")) == "200":
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

_SUPABASE_POOLER_REGIONS = [
    "us-east-1", "us-east-2", "us-west-1", "us-west-2",
    "ca-central-1", "eu-west-1", "eu-west-2", "eu-central-1",
    "ap-southeast-1", "ap-southeast-2", "ap-northeast-1", "sa-east-1",
]


def _try_supabase_session_pooler(conn_str: str, connect_timeout: int) -> object:
    """Try the Supabase Session Pooler as fallback when direct connection is IPv6-only.

    Derives project-ref from the direct connection hostname (db.[ref].supabase.co),
    builds pooler URLs (aws-0-[region].pooler.supabase.com:5432), and tries each
    AWS region until one succeeds. The Session Pooler has an IPv4 A-record in every
    region and bypasses the IPv6-only direct connection limitation.
    """
    import psycopg2  # type: ignore
    import socket
    import re
    from urllib.parse import urlparse, unquote as _unquote, quote as _quote

    _p = urlparse(conn_str)
    _host = _p.hostname or ""
    _m = re.match(r"^db\.([^.]+)\.supabase\.co$", _host)
    if not _m:
        raise RuntimeError(
            "IPv6-only connection failed and host is not a recognisable Supabase direct-connection URL.\n"
            "Use the Session Pooler connection string from Supabase → Connect → Session Pooler tab."
        )
    _ref  = _m.group(1)
    _user = _unquote(_p.username or "postgres")
    _pass = _unquote(_p.password or "")
    _db   = (_p.path or "/postgres").lstrip("/") or "postgres"
    # Session pooler username uses the project-ref suffix: postgres.[ref]
    _pooler_user = f"postgres.{_ref}"

    for _region in _SUPABASE_POOLER_REGIONS:
        _pooler_host = f"aws-0-{_region}.pooler.supabase.com"
        try:
            socket.getaddrinfo(_pooler_host, 5432, socket.AF_INET)
        except Exception:
            continue
        _pooler_url = (
            f"postgresql://{_pooler_user}:{_quote(_pass, safe='')}@"
            f"{_pooler_host}:5432/{_db}"
        )
        try:
            _conn = psycopg2.connect(_pooler_url, connect_timeout=connect_timeout)
            return _conn
        except Exception as _pe:
            if "Tenant or user not found" in str(_pe):
                continue  # wrong region — try next
            raise  # different error (e.g. wrong password) — stop trying

    raise RuntimeError(
        "Could not connect to Supabase via direct connection (IPv6-only) or any Session Pooler region.\n\n"
        "Please check:\n"
        "1. Your Supabase project is not paused (free tier pauses after 1 week of no activity).\n"
        "   → Log in to supabase.com and click 'Restore project' if it shows as paused.\n"
        "2. Use the Session Pooler connection string from Supabase → Connect → Session Pooler tab.\n"
        "   It looks like: postgresql://postgres.[ref]:[password]@aws-0-[region].pooler.supabase.com:5432/postgres\n"
        "3. Your database password is correct."
    )


def _psycopg2_connect(conn_str: str, connect_timeout: int = 10):
    """Connect via psycopg2 with automatic fallbacks for IPv6-only Supabase projects.

    Strategy:
    1. Direct URL connect (works if IPv6 is available or host has IPv4)
    2. Force IPv4 via libpq keyword DSN with hostaddr= (works if host has an A-record)
    3. Supabase Session Pooler across all known AWS regions (IPv4, works even when
       the direct-connection host is IPv6-only)
    """
    import psycopg2  # type: ignore

    _IPV6_ERRORS = ("assign requested address", "Network is unreachable",
                    "could not translate host name", "Name or service not known")

    # ── Attempt 1: direct URL ────────────────────────────────────────────────
    try:
        return psycopg2.connect(conn_str, connect_timeout=connect_timeout)
    except Exception as _e1:
        _msg1 = str(_e1)
        if not any(x in _msg1 for x in _IPV6_ERRORS):
            raise  # real error (wrong password, table missing, etc.) — surface it

    # ── Attempt 2: force IPv4 via keyword DSN ───────────────────────────────
    try:
        import socket
        from urllib.parse import urlparse, unquote as _unquote
        _p    = urlparse(conn_str)
        _host = _p.hostname or ""
        _ipv4 = socket.getaddrinfo(_host, None, socket.AF_INET)[0][4][0]
        _dsn  = (
            f"host={_host} "
            f"hostaddr={_ipv4} "
            f"port={_p.port or 5432} "
            f"dbname={(_p.path or '/postgres').lstrip('/')} "
            f"user={_unquote(_p.username or 'postgres')} "
            f"password={_unquote(_p.password or '')} "
            f"sslmode=require"
        )
        return psycopg2.connect(_dsn, connect_timeout=connect_timeout)
    except Exception:
        pass

    # ── Attempt 3: Supabase Session Pooler (IPv4, all regions) ─────────────
    return _try_supabase_session_pooler(conn_str, connect_timeout)



def _get_effective_supabase_conn_str(cfg: dict) -> str:
    """Return the Supabase connection string with the stored password substituted in.

    The password is URL-encoded so that special characters like '?' or '@' don't
    corrupt the URL structure when parsed by urllib or libpq.
    """
    from urllib.parse import quote as _url_quote
    conn_str = cfg.get("supabase_connection_string", "").strip()
    password  = cfg.get("supabase_db_password", "").strip()
    if not conn_str:
        return ""
    if "[YOUR-PASSWORD]" in conn_str and password:
        return conn_str.replace("[YOUR-PASSWORD]", _url_quote(password, safe=""))
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
    """Derive the Supabase REST API URL from the connection string (for API Endpoints).

    Handles both:
    - Direct connection:  db.[ref].supabase.co  → https://[ref].supabase.co
    - Session Pooler:     username = postgres.[ref]  → https://[ref].supabase.co
    """
    import re as _re
    from urllib.parse import urlparse as _up
    conn_str = _get_effective_supabase_conn_str(cfg)
    if conn_str:
        # Direct connection format: db.[ref].supabase.co
        m = _re.search(r'@db\.([^.]+)\.supabase\.co', conn_str)
        if m:
            return f"https://{m.group(1)}.supabase.co"
        # Session pooler format: username = postgres.[ref]
        _p = _up(conn_str)
        _u = (_p.username or "")
        _pm = _re.match(r"^postgres\.([^@]+)$", _u)
        if _pm:
            return f"https://{_pm.group(1)}.supabase.co"
    return cfg.get("supabase_url", "").strip()   # fallback: old-style config


def _has_any_db(cfg: dict) -> bool:
    return True  # SQLite is always available; Supabase/Turso are optional


# ─────────────────────────────────────────────
# Turso helpers (libsql HTTP API, no extra package needed)
# ─────────────────────────────────────────────

def _turso_http_url(raw: str) -> str:
    """Convert libsql:// URL to https:// for the HTTP pipeline API."""
    u = raw.strip().rstrip("/")
    if u.startswith("libsql://"):
        return "https://" + u[len("libsql://"):]
    return u


def _has_turso(cfg: dict) -> bool:
    return bool(cfg.get("turso_url", "").strip() and cfg.get("turso_auth_token", "").strip())


def _validate_setup_credentials(cfg: dict) -> list:
    """Test every configured service and return a list of (status, label, detail, fix_hint).
    status is 'ok', 'warn', or 'err'. Called from the Get Started page after secrets are saved."""
    results = []

    # ── 1. Cloud database ──────────────────────────────────────────────
    if _has_turso(cfg):
        try:
            _turso_execute(cfg, "SELECT 1")
            results.append(("ok", "Turso Database", "Connected and responding.", ""))
        except Exception as _e:
            _em = str(_e)[:250]
            if "401" in _em or "unauthorized" in _em.lower():
                _fix = ("Your Auth Token is invalid or expired. "
                        "Go to Settings → Database → Turso and regenerate a database-specific token "
                        "(from the database page — NOT the Platform API token in the sidebar avatar menu).")
            elif "not found" in _em.lower() or "404" in _em:
                _fix = ("Database URL not found. Double-check the libsql:// URL from "
                        "your Turso database Connect section.")
            elif "timeout" in _em.lower():
                _fix = "Connection timed out. Check your internet connection and try again."
            else:
                _fix = "Go to Settings → Database → Turso and verify your URL and Auth Token."
            results.append(("err", "Turso Database", _em, _fix))
    elif _has_supabase(cfg):
        try:
            _vc = _psycopg2_connect(
                _get_effective_supabase_conn_str(cfg), connect_timeout=10
            )
            _vc.close()
            results.append(("ok", "Supabase Database", "Connected and responding.", ""))
        except Exception as _e:
            results.append(("err", "Supabase Database", str(_e)[:250],
                "Check your Connection String and Database Password in Settings → Database → Supabase."))
    else:
        results.append(("err", "Cloud Database",
            "No cloud database configured — data will be lost on every app restart.",
            "Go to Settings → Database, fill in Turso credentials, and click Setup Turso Tables."))

    # ── 2. Gmail SMTP ──────────────────────────────────────────────────
    _smtp_email = cfg.get("smtp_email", "").strip()
    _smtp_pass  = re.sub(r"\s+", "", cfg.get("smtp_password", "").strip())
    if _smtp_email and _smtp_pass:
        try:
            _srv = smtplib.SMTP("smtp.gmail.com", 587, timeout=10)
            _srv.starttls()
            _srv.login(_smtp_email, _smtp_pass)
            _srv.quit()
            results.append(("ok", "Gmail SMTP", f"Authenticated as {_smtp_email}.", ""))
        except smtplib.SMTPAuthenticationError:
            results.append(("err", "Gmail SMTP",
                "Authentication failed — Gmail rejected the App Password.",
                "Go to myaccount.google.com → Security → App Passwords and regenerate the MERIT password. "
                "Copy all 16 characters with no spaces into Settings → Email → App Password."))
        except Exception as _e:
            _em = str(_e)[:200]
            results.append(("err", "Gmail SMTP", _em,
                "Check your Gmail address and App Password in Settings → Email. "
                "Make sure 2-Step Verification is enabled on your Google account."))
    else:
        results.append(("err", "Gmail SMTP",
            "Gmail credentials not configured.",
            "Go to Settings → Email and enter your VE Gmail address and App Password."))

    # ── 3. Sender identity ──────────────────────────────────────────────
    _from  = cfg.get("from_name", "").strip()
    _subj  = cfg.get("subject", "").strip()
    if _from and _subj:
        results.append(("ok", "Sender Identity",
            f'Sending as "{_from}" · subject "{_subj}".', ""))
    else:
        _missing = []
        if not _from: _missing.append("From Name")
        if not _subj: _missing.append("Default Subject Line")
        results.append(("err", "Sender Identity",
            f"Missing: {', '.join(_missing)}.",
            "Go to Settings → Email → Sender Identity and fill in your firm name and default subject."))

    # ── 4. Image hosting (warning only — optional) ─────────────────────
    if _has_image_host(cfg):
        results.append(("ok", "Image Hosting", "API key present.", ""))
    else:
        results.append(("warn", "Image Hosting",
            "No image hosting key configured.",
            "Product images will not upload until you add a key. "
            "Get a free key from freeimage.host or imghippo.com and paste it in Settings → Image Hosting."))

    return results


def _turso_cache_key(cfg: dict) -> str:
    url = _turso_http_url(cfg.get("turso_url", "").strip())
    tok = cfg.get("turso_auth_token", "").strip()
    return f"{url}|{tok}" if (url and tok) else ""


def _turso_arg(v):
    """Convert a Python value to a Turso Hrana v2 typed arg.

    Turso type rules (from their JSON schema):
      integer → {"type":"integer","value":"<str>"}   ← value must be a JSON string
      float   → {"type":"float",  "value": <number>} ← value must be a JSON number (f64)
      text    → {"type":"text",   "value":"<str>"}
      null    → {"type":"null"}
    """
    if v is None:
        return {"type": "null"}
    if isinstance(v, bool):
        return {"type": "integer", "value": "1" if v else "0"}
    if isinstance(v, int):
        return {"type": "integer", "value": str(v)}
    if isinstance(v, float):
        return {"type": "float", "value": v}   # must be a real JSON number, NOT a string
    return {"type": "text", "value": str(v)}


def _turso_http_post(url: str, token: str, payload: dict) -> dict:
    """POST a Hrana v2 pipeline payload to Turso and return the parsed JSON result."""
    import json as _j
    import urllib.error as _ue
    data = _j.dumps(payload).encode("utf-8")
    req = _urllib_request.Request(
        f"{url}/v2/pipeline",
        data=data,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
    )
    try:
        with _urllib_request.urlopen(req, timeout=15) as resp:
            return _j.loads(resp.read())
    except _ue.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Turso HTTP {exc.code}: {body[:400]}")


def _turso_execute_direct(url: str, token: str, sql: str, params=()) -> list[dict]:
    """Execute one SQL statement on Turso via Hrana v2 HTTP. Returns list of row dicts."""
    payload = {
        "baton": None,
        "requests": [
            {"type": "execute", "stmt": {"sql": sql, "args": [_turso_arg(p) for p in params]}},
            {"type": "close"},
        ],
    }
    result = _turso_http_post(url, token, payload)

    for r in result.get("results", []):
        if r.get("type") == "error":
            raise RuntimeError(r.get("error", {}).get("message", "Turso error"))

    exec_resp = result["results"][0].get("response", {}).get("result", {})
    cols = [c["name"] for c in exec_resp.get("cols", [])]
    rows = exec_resp.get("rows", [])
    if not cols:
        return []

    def _coerce(cell):
        t, v = cell.get("type"), cell.get("value")
        if t == "null" or v is None:
            return None
        if t == "integer":
            return int(v)
        if t in ("real", "float"):
            return float(v)
        return v

    return [dict(zip(cols, [_coerce(c) for c in row])) for row in rows]


def _turso_pipeline(url: str, token: str, statements: list) -> None:
    """Execute multiple (sql, params) statements in a single Hrana v2 pipeline call."""
    requests = [
        {"type": "execute", "stmt": {"sql": sql, "args": [_turso_arg(p) for p in params]}}
        for sql, params in statements
    ]
    requests.append({"type": "close"})
    result = _turso_http_post(url, token, {"baton": None, "requests": requests})
    for r in result.get("results", []):
        if r.get("type") == "error":
            raise RuntimeError(r.get("error", {}).get("message", "Turso error"))


def _turso_execute(cfg: dict, sql: str, params=()) -> list[dict]:
    url = _turso_http_url(cfg.get("turso_url", "").strip())
    tok = cfg.get("turso_auth_token", "").strip()
    if not url or not tok:
        raise RuntimeError("Turso not configured")
    return _turso_execute_direct(url, tok, sql, params)


TURSO_SETUP_SQL = """
CREATE TABLE IF NOT EXISTS products (
    sku            TEXT PRIMARY KEY,
    item_name      TEXT NOT NULL,
    category       TEXT NOT NULL DEFAULT '',
    price          REAL NOT NULL DEFAULT 0.0,
    description    TEXT NOT NULL DEFAULT '',
    buy_button_url TEXT NOT NULL DEFAULT '',
    image_url      TEXT NOT NULL DEFAULT 'N/A',
    active         INTEGER NOT NULL DEFAULT 1,
    created_at     TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS inventory (
    sku            TEXT PRIMARY KEY,
    item_name      TEXT NOT NULL,
    category       TEXT NOT NULL DEFAULT '',
    price          REAL NOT NULL DEFAULT 0.0,
    unit_cost      REAL NOT NULL DEFAULT 0.0,
    stock_left     INTEGER NOT NULL DEFAULT 0,
    status         TEXT NOT NULL DEFAULT 'In stock',
    image_url      TEXT NOT NULL DEFAULT 'N/A',
    original_stock INTEGER NOT NULL DEFAULT 0,
    created_at     TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS outbound_logs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    recipient_name  TEXT NOT NULL,
    recipient_email TEXT NOT NULL,
    order_number    TEXT NOT NULL,
    products_list   TEXT NOT NULL,
    subtotal        REAL NOT NULL DEFAULT 0.0,
    tax             REAL NOT NULL DEFAULT 0.0,
    shipping        REAL NOT NULL DEFAULT 0.0,
    total_cost      REAL NOT NULL DEFAULT 0.0,
    timestamp       TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS email_templates (
    template_key TEXT PRIMARY KEY,
    html_content TEXT NOT NULL DEFAULT '',
    updated_at   TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    email         TEXT NOT NULL UNIQUE,
    full_name     TEXT NOT NULL DEFAULT '',
    role          TEXT NOT NULL DEFAULT 'staff',
    password_hash TEXT NOT NULL DEFAULT '',
    invite_token  TEXT,
    created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS roles (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    role_name  TEXT NOT NULL UNIQUE,
    pages      TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS financials (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    entry_date      TEXT    NOT NULL DEFAULT (date('now')),
    category        TEXT    NOT NULL DEFAULT 'Expense',
    description     TEXT    NOT NULL DEFAULT '',
    amount          REAL    NOT NULL DEFAULT 0.0,
    notes           TEXT    NOT NULL DEFAULT '',
    payment_method  TEXT    NOT NULL DEFAULT '',
    tags            TEXT    NOT NULL DEFAULT '',
    is_recurring    INTEGER NOT NULL DEFAULT 0,
    recur_frequency TEXT    NOT NULL DEFAULT '',
    created_at      TEXT    NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS fin_budgets (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    category      TEXT    NOT NULL,
    period        TEXT    NOT NULL DEFAULT 'monthly',
    budget_amount REAL    NOT NULL DEFAULT 0.0,
    notes         TEXT    NOT NULL DEFAULT '',
    created_at    TEXT    NOT NULL DEFAULT (datetime('now')),
    UNIQUE(category, period)
)
"""


def sync_local_to_turso(cfg: dict) -> tuple[int, int, list]:
    """Sync all local SQLite users and roles to Turso. Returns (users_synced, roles_synced, errors)."""
    if not _has_turso(cfg):
        return 0, 0, ["Turso not connected"]
    _surl = _turso_http_url(cfg.get("turso_url", "").strip())
    _stok = cfg.get("turso_auth_token", "").strip()
    errors = []
    users_synced = roles_synced = 0
    try:
        local_conn = _get_sqlite_conn()
        local_roles = local_conn.execute("SELECT role_name, pages FROM roles").fetchall()
        for row in local_roles:
            try:
                _turso_pipeline(_surl, _stok, [(
                    "INSERT INTO roles (role_name, pages) VALUES (?,?)"
                    " ON CONFLICT(role_name) DO UPDATE SET pages=excluded.pages",
                    (str(row["role_name"]), str(row["pages"])),
                )])
                roles_synced += 1
            except Exception as e:
                errors.append(f"Role {row['role_name']}: {e}")
        local_users = local_conn.execute(
            "SELECT email, full_name, role, password_hash, invite_token FROM users"
        ).fetchall()
        for row in local_users:
            try:
                _turso_pipeline(_surl, _stok, [(
                    "INSERT INTO users (email, full_name, role, password_hash, invite_token)"
                    " VALUES (?,?,?,?,?)"
                    " ON CONFLICT(email) DO UPDATE SET full_name=excluded.full_name,"
                    " role=excluded.role, password_hash=excluded.password_hash,"
                    " invite_token=excluded.invite_token",
                    (str(row["email"]), str(row["full_name"]), str(row["role"]),
                     str(row["password_hash"]), row["invite_token"]),
                )])
                users_synced += 1
            except Exception as e:
                errors.append(f"User {row['email']}: {e}")
        local_conn.close()
    except Exception as exc:
        errors.append(f"SQLite read failed: {exc}")
    return users_synced, roles_synced, errors


def _split_sql_statements(sql: str) -> list:
    """Split SQL into individual executable statements, respecting dollar-quoted blocks.

    A naive split on ';' breaks DO $$ ... $$; migration blocks because the PL/pgSQL
    body itself contains semicolons. This scanner tracks dollar-quote depth so that
    semicolons inside $$ ... $$ are never treated as statement terminators.
    """
    import re as _re
    statements: list = []
    buf: list = []
    dollar_tag: str | None = None
    i = 0
    while i < len(sql):
        if dollar_tag is None:
            # Detect opening dollar-quote: $tag$ or $$
            _dm = _re.match(r"\$([A-Za-z0-9_]*)\$", sql[i:])
            if _dm:
                dollar_tag = _dm.group(0)
                buf.append(dollar_tag)
                i += len(dollar_tag)
                continue
            if sql[i] == ";":
                stmt = "".join(buf).strip()
                if stmt and not all(ln.lstrip().startswith("--") for ln in stmt.splitlines() if ln.strip()):
                    statements.append(stmt)
                buf = []
                i += 1
                continue
        else:
            # Detect matching closing dollar-quote
            if sql[i : i + len(dollar_tag)] == dollar_tag:
                buf.append(dollar_tag)
                i += len(dollar_tag)
                dollar_tag = None
                continue
        buf.append(sql[i])
        i += 1
    # trailing statement without final semicolon
    stmt = "".join(buf).strip()
    if stmt and not all(ln.lstrip().startswith("--") for ln in stmt.splitlines() if ln.strip()):
        statements.append(stmt)
    return statements


def save_product_to_db(product: dict, cfg: dict) -> tuple[bool, str]:
    """Upsert one product into ALL configured databases. Always saves to SQLite."""
    _stock = int(product.get("stock_left", 0))
    _orig  = int(product.get("original_stock") if product.get("original_stock") is not None else _stock)
    _status = str(product.get("status") or (
        "Backordered" if _stock < 0 else ("Out of stock" if _stock == 0 else ("Low stock" if _stock <= 10 else "In stock"))
    ))
    row = {
        "sku":            product["sku"],
        "item_name":      product["item_name"],
        "category":       product.get("category", ""),
        "price":          product.get("price", 0.0),
        "stock_left":     _stock,
        "original_stock": _orig,
        "status":         _status,
        "image_url":      product.get("image_url", "N/A"),
        "description":    product.get("description", ""),
        "buy_button_url": product.get("buy_button_url", ""),
        "active":         product.get("active", True),
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
            INSERT INTO products (sku, item_name, category, price, description, buy_button_url, image_url, active)
            VALUES (:sku, :item_name, :category, :price, :description, :buy_button_url, :image_url, :active)
            ON CONFLICT(sku) DO UPDATE SET
                item_name=excluded.item_name, category=excluded.category,
                price=excluded.price, description=excluded.description,
                buy_button_url=excluded.buy_button_url,
                image_url=excluded.image_url, active=excluded.active
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
                    cur.execute("""
                        INSERT INTO inventory (sku,item_name,category,price,stock_left,original_stock,status,image_url)
                        VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                        ON CONFLICT(sku) DO UPDATE SET
                            item_name=EXCLUDED.item_name, category=EXCLUDED.category,
                            price=EXCLUDED.price, image_url=EXCLUDED.image_url
                    """, (row["sku"],row["item_name"],row["category"],row["price"],
                          row["stock_left"],row["original_stock"],row["status"],row["image_url"]))
                    cur.execute("""
                        INSERT INTO products (sku,name,category,price,description,buy_button_url,image_url,active)
                        VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                        ON CONFLICT(sku) DO UPDATE SET
                            name=EXCLUDED.name, category=EXCLUDED.category,
                            price=EXCLUDED.price, description=EXCLUDED.description,
                            buy_button_url=EXCLUDED.buy_button_url,
                            image_url=EXCLUDED.image_url, active=EXCLUDED.active
                    """, (row["sku"],row["item_name"],row["category"],row["price"],
                          row["description"],row["buy_button_url"],row["image_url"],row["active"]))
            conn_sb.close()
            results.append("Supabase")
        except Exception as exc:
            results.append(f"Supabase failed: {exc}")

    # ── Turso ────────────────────────────────────────────────────────
    if _has_turso(cfg):
        try:
            _turl = _turso_http_url(cfg.get("turso_url", "").strip())
            _ttok = cfg.get("turso_auth_token", "").strip()
            _price_f = float(row["price"] or 0)
            _turso_pipeline(_turl, _ttok, [
                (
                    "INSERT INTO inventory (sku,item_name,category,price,stock_left,original_stock,status,image_url)"
                    " VALUES (?,?,?,?,?,?,?,?)"
                    " ON CONFLICT(sku) DO UPDATE SET"
                    " item_name=excluded.item_name, category=excluded.category,"
                    " price=excluded.price, image_url=excluded.image_url",
                    (str(row["sku"]), str(row["item_name"]), str(row["category"]),
                     _price_f, int(row["stock_left"]), int(row["original_stock"]),
                     str(row["status"]), str(row["image_url"])),
                ),
                (
                    "INSERT INTO products (sku,item_name,category,price,description,buy_button_url,image_url,active)"
                    " VALUES (?,?,?,?,?,?,?,?)"
                    " ON CONFLICT(sku) DO UPDATE SET"
                    " item_name=excluded.item_name, category=excluded.category,"
                    " price=excluded.price, description=excluded.description,"
                    " buy_button_url=excluded.buy_button_url,"
                    " image_url=excluded.image_url, active=excluded.active",
                    (str(row["sku"]), str(row["item_name"]), str(row["category"]),
                     _price_f, str(row["description"]), str(row["buy_button_url"]),
                     str(row["image_url"]), 1 if row["active"] else 0),
                ),
            ])
            results.append("Turso")
        except Exception as exc:
            results.append(f"Turso failed: {exc}")

    ok = any("failed" not in r for r in results)
    return ok, " · ".join(results)


def load_products() -> list[dict]:
    """Return the locally-cached product list from config.json."""
    return st.session_state.cfg.get("products", [])


def load_inventory_from_sqlite() -> pd.DataFrame:
    """Load inventory table from SQLite."""
    try:
        conn = _get_sqlite_conn()
        df = _sqlite_read_sql(conn, "SELECT * FROM inventory ORDER BY item_name")
        conn.close()
        return df
    except Exception:
        return pd.DataFrame()

def set_original_stock_all_dbs(sku: str, stock: int, cfg: dict) -> tuple[bool, str]:
    """Set the original purchased stock level across all databases (absolute override)."""
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

    # Turso
    if _has_turso(cfg):
        try:
            _turso_execute(cfg, "UPDATE inventory SET original_stock=? WHERE sku=?", (stock, sku))
            results.append("Turso")
        except Exception as exc: results.append(f"Turso failed: {exc}")

    return any("failed" not in r for r in results), " · ".join(results)


def adjust_original_stock_all_dbs(sku: str, delta: int, cfg: dict) -> tuple[bool, str]:
    """Add delta to both original_stock AND stock_left across all databases.

    Use for restocking: when you purchase new inventory, both the lifetime total
    and the current available units increase by the same amount.
    """
    _status_from_stock = lambda s: (
        "Backordered" if s < 0 else ("Out of stock" if s == 0 else ("Low stock" if s <= 10 else "In stock"))
    )
    results = []
    # SQLite
    try:
        conn = _get_sqlite_conn()
        row = conn.execute("SELECT stock_left, original_stock FROM inventory WHERE sku=?", (sku,)).fetchone()
        if row is None:
            conn.close()
            return False, "SKU not found"
        new_stock = row["stock_left"] + delta
        new_orig  = row["original_stock"] + delta
        status    = _status_from_stock(new_stock)
        conn.execute(
            "UPDATE inventory SET stock_left=?, original_stock=?, status=? WHERE sku=?",
            (new_stock, new_orig, status, sku)
        )
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
                    cur.execute("SELECT stock_left, original_stock FROM inventory WHERE sku=%s", (sku,))
                    row = cur.fetchone()
                    if row:
                        new_stock = row[0] + delta
                        new_orig  = row[1] + delta
                        status    = _status_from_stock(new_stock)
                        cur.execute(
                            "UPDATE inventory SET stock_left=%s, original_stock=%s, status=%s WHERE sku=%s",
                            (new_stock, new_orig, status, sku)
                        )
            conn_sb.close()
            results.append("Supabase")
        except Exception as exc:
            results.append(f"Supabase failed: {exc}")

    # Turso
    if _has_turso(cfg):
        try:
            _tr = _turso_execute(cfg, "SELECT stock_left, original_stock FROM inventory WHERE sku=?", (sku,))
            if _tr:
                _ts = int(_tr[0].get("stock_left") or 0) + delta
                _to = int(_tr[0].get("original_stock") or 0) + delta
                _turso_execute(cfg,
                    "UPDATE inventory SET stock_left=?, original_stock=?, status=? WHERE sku=?",
                    (_ts, _to, _status_from_stock(_ts), sku))
            results.append("Turso")
        except Exception as exc:
            results.append(f"Turso failed: {exc}")

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


def adjust_inventory_turso(sku: str, delta: int, cfg: dict) -> tuple[bool, str]:
    if not _has_turso(cfg):
        return False, "Turso not configured"
    try:
        _turl = _turso_http_url(cfg.get("turso_url", "").strip())
        _ttok = cfg.get("turso_auth_token", "").strip()
        rows = _turso_execute_direct(_turl, _ttok, "SELECT stock_left FROM inventory WHERE sku=?", (str(sku),))
        if not rows:
            return False, "SKU not found in Turso"
        new_stock = int(rows[0].get("stock_left") or 0) + int(delta)
        status = ("Backordered" if new_stock < 0 else
                  "Out of stock" if new_stock == 0 else
                  "Low stock" if new_stock <= 10 else "In stock")
        stmts = [("UPDATE inventory SET stock_left=?, status=? WHERE sku=?",
                   (new_stock, str(status), str(sku)))]
        if delta > 0:
            stmts.append(("UPDATE inventory SET original_stock = original_stock + ? WHERE sku=?",
                           (int(delta), str(sku))))
        _turso_pipeline(_turl, _ttok, stmts)
        return True, f"Turso stock → {new_stock}"
    except Exception as exc:
        return False, str(exc)


def delete_product_from_db(sku: str, cfg: dict) -> tuple[bool, str]:
    """Delete a product from all configured databases (SQLite, Supabase, Turso)."""
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

    # ── Turso ────────────────────────────────────────────────────────
    if _has_turso(cfg):
        try:
            _turl2 = _turso_http_url(cfg.get("turso_url", "").strip())
            _ttok2 = cfg.get("turso_auth_token", "").strip()
            _turso_pipeline(_turl2, _ttok2, [
                ("DELETE FROM inventory WHERE sku=?", (str(sku),)),
                ("DELETE FROM products WHERE sku=?",  (str(sku),)),
            ])
            results.append("Turso")
        except Exception as exc:
            results.append(f"Turso failed: {exc}")

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

    # Turso
    if _has_turso(cfg):
        try:
            _turl3 = _turso_http_url(cfg.get("turso_url", "").strip())
            _ttok3 = cfg.get("turso_auth_token", "").strip()
            _turso_pipeline(_turl3, _ttok3, [
                ("UPDATE inventory SET stock_left=?, status=? WHERE sku=?",
                 (int(stock), str(status), str(sku))),
            ])
            results.append("Turso")
        except Exception as exc:
            results.append(f"Turso failed: {exc}")

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

    # ── Turso ────────────────────────────────────────────────────────
    if _has_turso(cfg):
        try:
            _tsurl = _turso_http_url(cfg.get("turso_url", "").strip())
            _tstok = cfg.get("turso_auth_token", "").strip()
            _sql_inv = (
                "INSERT INTO inventory (sku,item_name,category,price,stock_left,status,image_url)"
                " VALUES (?,?,?,?,?,?,?)"
                " ON CONFLICT(sku) DO UPDATE SET"
                " item_name=excluded.item_name, category=excluded.category,"
                " price=excluded.price, stock_left=excluded.stock_left,"
                " status=excluded.status, image_url=excluded.image_url"
            )
            for rec in records:
                _turso_pipeline(_tsurl, _tstok, [
                    (_sql_inv, (
                        str(rec.get("sku") or ""),
                        str(rec.get("item_name") or ""),
                        str(rec.get("category") or ""),
                        float(rec.get("price") or 0),
                        int(rec.get("stock_left") or 0),
                        str(rec.get("status") or "In stock"),
                        str(rec.get("image_url") or "N/A"),
                    )),
                ])
            synced = max(synced, len(records))
        except Exception as exc:
            errors.append(f"Turso sync failed: {exc}")

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
def _fetch_inventory_turso(turso_key: str) -> list | None:
    if not turso_key:
        return None
    try:
        _u, _t = turso_key.split("|", 1)
        rows = _turso_execute_direct(_u, _t, "SELECT * FROM inventory ORDER BY item_name")
        return rows if rows else None
    except Exception:
        return None


@st.cache_data(ttl=30, show_spinner=False)
def _fetch_inventory_sqlite_cached() -> list | None:
    df = load_inventory_from_sqlite()
    if not df.empty:
        return df.to_dict("records")
    return None


def load_inventory_preferring_cloud(cfg: dict) -> pd.DataFrame:
    """Load inventory preferring Supabase > Turso > SQLite (results cached 30 s)."""
    _sb_cs = _get_effective_supabase_conn_str(cfg)
    if _sb_cs:
        rows = _fetch_inventory_supabase(_sb_cs)
        if rows:
            return pd.DataFrame(rows)

    _tk = _turso_cache_key(cfg)
    if _tk:
        rows = _fetch_inventory_turso(_tk)
        if rows:
            return pd.DataFrame(rows)

    rows = _fetch_inventory_sqlite_cached()
    if rows:
        return pd.DataFrame(rows)
    return load_inventory_from_sqlite()


def load_products_for_catalog(cfg: dict) -> list[dict]:
    """Load product list preferring Supabase > Turso > SQLite > config.json (cached 30 s)."""
    _sb_cs = _get_effective_supabase_conn_str(cfg)
    if _sb_cs:
        rows = _fetch_inventory_supabase(_sb_cs)
        if rows:
            return rows

    _tk = _turso_cache_key(cfg)
    if _tk:
        rows = _fetch_inventory_turso(_tk)
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

    # Turso
    if _has_turso(cfg):
        try:
            _turso_execute(cfg,
                "INSERT INTO outbound_logs "
                "(recipient_name,recipient_email,order_number,products_list,subtotal,tax,shipping,total_cost) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (row["name"],row["email"],row["order"],row["prods"],
                 row["sub"],row["tax"],row["ship"],row["cost"]))
        except Exception: pass


_FIN_CATEGORIES     = ["Revenue", "Expense", "Cost of Goods (COGS)", "Marketing", "Payroll", "Operations", "Other"]
_FIN_PAYMENT_METHODS = ["", "Bank Transfer", "Credit Card", "Debit Card", "Cash", "Check", "Wire Transfer", "PayPal", "Venmo", "Stripe", "Other"]
_FIN_RECUR_OPTIONS  = ["Weekly", "Bi-weekly", "Monthly", "Quarterly", "Annual"]
_FIN_PERIODS        = ["monthly", "quarterly", "annual"]

_FIN_ALL_COLS = "id, entry_date, category, description, amount, notes, payment_method, tags, is_recurring, recur_frequency, created_at"

@st.cache_data(ttl=30, show_spinner=False)
def _fetch_financials_cached(sb_conn_str: str, turso_key: str = "") -> list:
    if sb_conn_str:
        try:
            conn = _psycopg2_connect(sb_conn_str, connect_timeout=5)
            with conn.cursor() as cur:
                cur.execute(f"SELECT {_FIN_ALL_COLS} FROM financials ORDER BY entry_date DESC, id DESC")
                cols = [d[0] for d in cur.description]
                rows = [dict(zip(cols, r)) for r in cur.fetchall()]
            conn.close()
            return rows
        except Exception:
            pass
    if turso_key:
        try:
            _tu, _tt = turso_key.split("|", 1)
            rows = _turso_execute_direct(_tu, _tt,
                f"SELECT {_FIN_ALL_COLS} FROM financials ORDER BY entry_date DESC, id DESC")
            if rows is not None:
                return rows
        except Exception:
            pass
    try:
        conn = _get_sqlite_conn()
        df = _sqlite_read_sql(conn, f"SELECT {_FIN_ALL_COLS} FROM financials ORDER BY entry_date DESC, id DESC")
        conn.close()
        return df.to_dict("records")
    except Exception:
        return []


@st.cache_data(ttl=30, show_spinner=False)
def _fetch_budgets_cached(sb_conn_str: str, turso_key: str = "") -> list:
    if sb_conn_str:
        try:
            conn = _psycopg2_connect(sb_conn_str, connect_timeout=5)
            with conn.cursor() as cur:
                cur.execute("SELECT id, category, period, budget_amount, notes, created_at FROM fin_budgets ORDER BY category, period")
                cols = [d[0] for d in cur.description]
                rows = [dict(zip(cols, r)) for r in cur.fetchall()]
            conn.close()
            return rows
        except Exception:
            pass
    if turso_key:
        try:
            _tu, _tt = turso_key.split("|", 1)
            rows = _turso_execute_direct(_tu, _tt,
                "SELECT id, category, period, budget_amount, notes, created_at FROM fin_budgets ORDER BY category, period")
            if rows is not None:
                return rows
        except Exception:
            pass
    try:
        conn = _get_sqlite_conn()
        df = _sqlite_read_sql(conn, "SELECT id, category, period, budget_amount, notes, created_at FROM fin_budgets ORDER BY category, period")
        conn.close()
        return df.to_dict("records")
    except Exception:
        return []


def get_financials_from_db(cfg: dict) -> pd.DataFrame:
    sb_cs = _get_effective_supabase_conn_str(cfg) or ""
    rows = _fetch_financials_cached(sb_cs, _turso_cache_key(cfg))
    _fin_empty_cols = ["id","entry_date","category","description","amount","notes","payment_method","tags","is_recurring","recur_frequency","created_at"]
    return pd.DataFrame(rows) if rows else pd.DataFrame(columns=_fin_empty_cols)


def get_budgets_from_db(cfg: dict) -> pd.DataFrame:
    sb_cs = _get_effective_supabase_conn_str(cfg) or ""
    rows = _fetch_budgets_cached(sb_cs, _turso_cache_key(cfg))
    return pd.DataFrame(rows) if rows else pd.DataFrame(columns=["id","category","period","budget_amount","notes","created_at"])


def add_financial_entry(entry_date: str, category: str, description: str, amount: float, notes: str, cfg: dict,
                        payment_method: str = "", tags: str = "", is_recurring: bool = False, recur_frequency: str = "") -> tuple[bool, str]:
    results = []
    _is_rec_int = 1 if is_recurring else 0
    try:
        conn = _get_sqlite_conn()
        conn.execute(
            "INSERT INTO financials (entry_date, category, description, amount, notes, payment_method, tags, is_recurring, recur_frequency) VALUES (?,?,?,?,?,?,?,?,?)",
            (entry_date, category, description, amount, notes, payment_method, tags, _is_rec_int, recur_frequency)
        )
        conn.commit(); conn.close()
        results.append("SQLite")
    except Exception as e:
        results.append(f"SQLite failed: {e}")
    conn_sb = _get_supabase_conn(cfg)
    if conn_sb is not None:
        try:
            with conn_sb:
                with conn_sb.cursor() as cur:
                    cur.execute(
                        "INSERT INTO financials (entry_date, category, description, amount, notes, payment_method, tags, is_recurring, recur_frequency) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                        (entry_date, category, description, amount, notes, payment_method, tags, is_recurring, recur_frequency)
                    )
            conn_sb.close(); results.append("Supabase")
        except Exception as e:
            results.append(f"Supabase failed: {e}")
    if _has_turso(cfg):
        try:
            _turso_execute(cfg,
                "INSERT INTO financials (entry_date, category, description, amount, notes, payment_method, tags, is_recurring, recur_frequency) VALUES (?,?,?,?,?,?,?,?,?)",
                (entry_date, category, description, amount, notes, payment_method, tags, _is_rec_int, recur_frequency))
            results.append("Turso")
        except Exception as e:
            results.append(f"Turso failed: {e}")
    _fetch_financials_cached.clear()
    return any("failed" not in r for r in results), " · ".join(results)


def update_financial_entry(row_id: int, entry_date: str, category: str, description: str, amount: float, notes: str, cfg: dict,
                           payment_method: str = "", tags: str = "", is_recurring: bool = False, recur_frequency: str = "") -> tuple[bool, str]:
    results = []
    _is_rec_int = 1 if is_recurring else 0
    try:
        conn = _get_sqlite_conn()
        conn.execute(
            "UPDATE financials SET entry_date=?, category=?, description=?, amount=?, notes=?, payment_method=?, tags=?, is_recurring=?, recur_frequency=? WHERE id=?",
            (entry_date, category, description, amount, notes, payment_method, tags, _is_rec_int, recur_frequency, row_id)
        )
        conn.commit(); conn.close()
        results.append("SQLite")
    except Exception as e:
        results.append(f"SQLite failed: {e}")
    conn_sb = _get_supabase_conn(cfg)
    if conn_sb is not None:
        try:
            with conn_sb:
                with conn_sb.cursor() as cur:
                    cur.execute(
                        "UPDATE financials SET entry_date=%s, category=%s, description=%s, amount=%s, notes=%s, payment_method=%s, tags=%s, is_recurring=%s, recur_frequency=%s WHERE id=%s",
                        (entry_date, category, description, amount, notes, payment_method, tags, is_recurring, recur_frequency, row_id)
                    )
            conn_sb.close(); results.append("Supabase")
        except Exception as e:
            results.append(f"Supabase failed: {e}")
    if _has_turso(cfg):
        try:
            _turso_execute(cfg,
                "UPDATE financials SET entry_date=?, category=?, description=?, amount=?, notes=?, payment_method=?, tags=?, is_recurring=?, recur_frequency=? WHERE id=?",
                (entry_date, category, description, amount, notes, payment_method, tags, _is_rec_int, recur_frequency, row_id))
            results.append("Turso")
        except Exception as e:
            results.append(f"Turso failed: {e}")
    _fetch_financials_cached.clear()
    return any("failed" not in r for r in results), " · ".join(results)


def delete_financial_entry(row_id: int, cfg: dict) -> tuple[bool, str]:
    results = []
    try:
        conn = _get_sqlite_conn()
        conn.execute("DELETE FROM financials WHERE id=?", (row_id,))
        conn.commit(); conn.close()
        results.append("SQLite")
    except Exception as e:
        results.append(f"SQLite failed: {e}")
    conn_sb = _get_supabase_conn(cfg)
    if conn_sb is not None:
        try:
            with conn_sb:
                with conn_sb.cursor() as cur:
                    cur.execute("DELETE FROM financials WHERE id=%s", (row_id,))
            conn_sb.close(); results.append("Supabase")
        except Exception as e:
            results.append(f"Supabase failed: {e}")
    if _has_turso(cfg):
        try:
            _turso_execute(cfg, "DELETE FROM financials WHERE id=?", (row_id,))
            results.append("Turso")
        except Exception as e:
            results.append(f"Turso failed: {e}")
    _fetch_financials_cached.clear()
    return any("failed" not in r for r in results), " · ".join(results)


def upsert_budget_entry(category: str, period: str, budget_amount: float, notes: str, cfg: dict) -> tuple[bool, str]:
    results = []
    try:
        conn = _get_sqlite_conn()
        conn.execute(
            "INSERT INTO fin_budgets (category, period, budget_amount, notes) VALUES (?,?,?,?) "
            "ON CONFLICT(category, period) DO UPDATE SET budget_amount=excluded.budget_amount, notes=excluded.notes",
            (category, period, budget_amount, notes)
        )
        conn.commit(); conn.close()
        results.append("SQLite")
    except Exception as e:
        results.append(f"SQLite failed: {e}")
    conn_sb = _get_supabase_conn(cfg)
    if conn_sb is not None:
        try:
            with conn_sb:
                with conn_sb.cursor() as cur:
                    cur.execute(
                        "INSERT INTO fin_budgets (category, period, budget_amount, notes) VALUES (%s,%s,%s,%s) "
                        "ON CONFLICT(category, period) DO UPDATE SET budget_amount=EXCLUDED.budget_amount, notes=EXCLUDED.notes",
                        (category, period, budget_amount, notes)
                    )
            conn_sb.close(); results.append("Supabase")
        except Exception as e:
            results.append(f"Supabase failed: {e}")
    if _has_turso(cfg):
        try:
            _turso_execute(cfg,
                "INSERT INTO fin_budgets (category, period, budget_amount, notes) VALUES (?,?,?,?) "
                "ON CONFLICT(category, period) DO UPDATE SET budget_amount=excluded.budget_amount, notes=excluded.notes",
                (category, period, budget_amount, notes))
            results.append("Turso")
        except Exception as e:
            results.append(f"Turso failed: {e}")
    _fetch_budgets_cached.clear()
    return any("failed" not in r for r in results), " · ".join(results)


def delete_budget_entry(row_id: int, cfg: dict) -> tuple[bool, str]:
    results = []
    try:
        conn = _get_sqlite_conn()
        conn.execute("DELETE FROM fin_budgets WHERE id=?", (row_id,))
        conn.commit(); conn.close()
        results.append("SQLite")
    except Exception as e:
        results.append(f"SQLite failed: {e}")
    conn_sb = _get_supabase_conn(cfg)
    if conn_sb is not None:
        try:
            with conn_sb:
                with conn_sb.cursor() as cur:
                    cur.execute("DELETE FROM fin_budgets WHERE id=%s", (row_id,))
            conn_sb.close(); results.append("Supabase")
        except Exception as e:
            results.append(f"Supabase failed: {e}")
    if _has_turso(cfg):
        try:
            _turso_execute(cfg, "DELETE FROM fin_budgets WHERE id=?", (row_id,))
            results.append("Turso")
        except Exception as e:
            results.append(f"Turso failed: {e}")
    _fetch_budgets_cached.clear()
    return any("failed" not in r for r in results), " · ".join(results)


def load_outbound_logs(cfg: dict) -> pd.DataFrame:
    """Load outbound logs from Supabase, Turso, or local SQLite."""
    _sb_cs = _get_effective_supabase_conn_str(cfg)
    if _sb_cs:
        try:
            conn = _psycopg2_connect(_sb_cs)
            df = pd.read_sql("SELECT * FROM outbound_logs ORDER BY created_at DESC LIMIT 500", conn)
            conn.close()
            df = df.rename(columns={"created_at": "timestamp"})
            return df
        except Exception: pass

    if _has_turso(cfg):
        try:
            rows = _turso_execute(cfg,
                "SELECT * FROM outbound_logs ORDER BY timestamp DESC LIMIT 500")
            if rows:
                return pd.DataFrame(rows)
        except Exception: pass

    try:
        conn = _get_sqlite_conn()
        df = _sqlite_read_sql(conn, "SELECT * FROM outbound_logs ORDER BY timestamp DESC LIMIT 500")
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

# Load config once per session. st.secrets is static per session so re-reading every
# rerun is wasted I/O. Settings mutations update st.session_state.cfg directly.
if "cfg" not in st.session_state:
    st.session_state.cfg = load_config()
cfg = st.session_state.cfg

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
# Login Gate — multi-user or legacy password
# ─────────────────────────────────────────────

_auth_cfg = st.session_state.cfg
_users_df  = get_users_from_db(_auth_cfg)
_has_users = not _users_df.empty

# Only enforce the multi-user login gate after setup is complete (secrets saved to Streamlit).
# During initial setup (no secrets yet) users can be created freely without getting locked out.
_login_secrets_active = False
try:
    _login_secrets_active = hasattr(st, "secrets") and "merit" in st.secrets
except Exception:
    pass

# ── Invite Link Handler ────────────────────────────────────────────────────
# When ?invite=TOKEN is in the URL, show the Set Password page instead of login.
_invite_token_param = st.query_params.get("invite", "")
if _invite_token_param:
    _invite_user_info = validate_invite_token(_invite_token_param, _auth_cfg)
    st.markdown("""
        <style>
        [data-testid="stSidebar"] { display: none; }
        .main .block-container {
            padding-top: 8vh !important;
            padding-bottom: 2rem !important;
            max-width: 100% !important;
        }
        .merit-invite-card {
            background: linear-gradient(135deg, #0f172a 0%, #1e293b 100%);
            border: 1px solid rgba(99,102,241,0.25);
            border-radius: 1.25rem;
            padding: 2rem 2rem 1.5rem 2rem;
            box-shadow: 0 25px 60px rgba(0,0,0,0.45);
            text-align: center;
            margin-bottom: 1rem;
        }
        .merit-invite-logo {
            display: block;
            width: 60px; height: 60px;
            background: linear-gradient(135deg, #6366f1, #8b5cf6);
            border-radius: 50%;
            font-size: 1.6rem;
            line-height: 60px;
            text-align: center;
            margin: 0 auto 0.75rem auto;
            box-shadow: 0 0 20px rgba(99,102,241,0.45);
        }
        .merit-invite-title {
            color: #f1f5f9;
            font-size: 1.6rem;
            font-weight: 700;
            margin: 0 0 0.25rem 0;
            text-align: center;
        }
        .merit-invite-sub { color: #94a3b8; font-size: 0.9rem; margin: 0 0 0.2rem 0; text-align: center; }
        .merit-invite-hint { color: #64748b; font-size: 0.85rem; margin: 0; text-align: center; }
        </style>
    """, unsafe_allow_html=True)
    _inv_c1, _inv_c2, _inv_c3 = st.columns([1, 2, 1])
    with _inv_c2:
        _firm_li = _auth_cfg.get("from_name", "MERIT").strip()
        _firm_label = _firm_li if _firm_li else "MERIT"
        if _invite_user_info:
            st.markdown(
                f'<div class="merit-invite-card">'
                f'<div class="merit-invite-logo">M</div>'
                f'<h1 class="merit-invite-title">{_firm_label}</h1>'
                f'<p class="merit-invite-sub">Welcome, {_invite_user_info["full_name"]}!</p>'
                f'<p class="merit-invite-hint">Create your password to get started.</p>'
                f'</div>',
                unsafe_allow_html=True,
            )
            with st.container(border=True):
                _ic1, _ic2 = st.columns(2)
                _ic1.markdown(f"**Email**\n\n{_invite_user_info['email']}")
                _ic2.markdown(f"**Role**\n\n{_invite_user_info['role'].capitalize()}")
                st.divider()
                _inv_pass  = st.text_input("New Password", type="password", placeholder="At least 6 characters", key="inv_pass")
                _inv_pass2 = st.text_input("Confirm Password", type="password", placeholder="Re-enter password", key="inv_pass2")
                st.write("")
                if st.button("Set Password & Sign In", type="primary", key="inv_btn", use_container_width=True):
                    if len(_inv_pass) < 6:
                        st.toast("Password must be at least 6 characters.", icon=None)
                        st.error("Password must be at least 6 characters.")
                    elif _inv_pass != _inv_pass2:
                        st.toast("Passwords do not match.", icon=None)
                        st.error("Passwords do not match.")
                    else:
                        _inv_ok, _inv_msg = complete_invite(_invite_token_param, _inv_pass, _auth_cfg)
                        if _inv_ok:
                            _invite_user_info["pages"] = get_pages_for_role(_invite_user_info["role"], _auth_cfg)
                            st.session_state["auth_user"] = _invite_user_info
                            st.session_state["authenticated"] = True
                            st.query_params.clear()
                            _fetch_users_cached.clear()
                            st.toast(f"Welcome to MERIT, {_invite_user_info['full_name'].split()[0]}!", icon=None)
                            st.rerun()
                        else:
                            st.toast("Failed to set password. Try again.", icon=None)
                            st.error(f"Failed to set password: {_inv_msg}")
        else:
            st.markdown(
                f'<div class="merit-invite-card">'
                f'<div class="merit-invite-logo">M</div>'
                f'<h1 class="merit-invite-title">{_firm_label}</h1>'
                f'</div>',
                unsafe_allow_html=True,
            )
            st.warning("This invite link is invalid or has already been used. Ask your admin for a new link.")
    st.stop()

if _has_users and _login_secrets_active:
    # Multi-user email/password auth
    if not st.session_state.get("auth_user"):
        st.markdown("""
            <style>
            [data-testid="stSidebar"] { display: none; }
            .main .block-container {
                padding-top: 8vh !important;
                padding-bottom: 2rem !important;
                max-width: 100% !important;
            }
            .merit-login-card {
                background: linear-gradient(135deg, #0f172a 0%, #1e293b 100%);
                border: 1px solid rgba(99,102,241,0.25);
                border-radius: 1.25rem;
                padding: 2.5rem 2rem 2rem 2rem;
                box-shadow: 0 25px 60px rgba(0,0,0,0.45);
                text-align: center;
            }
            .merit-logo-ring {
                display: block;
                width: 64px; height: 64px;
                background: linear-gradient(135deg, #6366f1, #8b5cf6);
                border-radius: 50%;
                font-size: 1.8rem;
                margin: 0 auto 1rem auto;
                box-shadow: 0 0 24px rgba(99,102,241,0.5);
                line-height: 64px;
                text-align: center;
            }
            .merit-login-title {
                color: #f1f5f9;
                font-size: 1.6rem;
                font-weight: 700;
                margin: 0 0 0.25rem 0;
                letter-spacing: -0.5px;
                text-align: center;
            }
            .merit-login-sub {
                color: #94a3b8;
                font-size: 0.9rem;
                margin-bottom: 1.75rem;
                text-align: center;
            }
            </style>
        """, unsafe_allow_html=True)
        _li_c1, _li_c2, _li_c3 = st.columns([1, 2, 1])
        with _li_c2:
            _sb_co_li = _auth_cfg.get("from_name", "MERIT").strip()
            _li_title = _sb_co_li if _sb_co_li else "MERIT"
            st.markdown(
                f'<div class="merit-login-card">'
                f'<div class="merit-logo-ring">M</div>'
                f'<h1 class="merit-login-title">{_li_title}</h1>'
                f'<p class="merit-login-sub">Sign in to your workspace</p>'
                f'</div>',
                unsafe_allow_html=True,
            )
            st.write("")
            with st.container(border=True):
                _li_email = st.text_input("Email", placeholder="you@example.com", key="li_email")
                _li_pass  = st.text_input("Password", type="password", placeholder="••••••••", key="li_pass")
                st.write("")
                if st.button("Sign In", type="primary", key="li_btn", use_container_width=True):
                    if _li_email.strip() and _li_pass.strip():
                        _li_user = authenticate_user(_li_email.strip(), _li_pass.strip(), _auth_cfg)
                        if _li_user:
                            st.session_state["auth_user"] = _li_user
                            st.session_state["authenticated"] = True
                            _li_name = _li_user.get("full_name", "").split()[0] if _li_user.get("full_name") else "back"
                            st.toast(f"Welcome back, {_li_name}!", icon=None)
                            st.rerun()
                        else:
                            st.toast("Sign-in failed. Check your credentials.", icon=None)
                            st.error("Incorrect email or password.")
                    else:
                        st.toast("Enter your email and password to continue.", icon=None)
                        st.warning("Please enter your email and password.")
                st.caption("Contact your admin if you need access or forgot your password.")
        st.stop()
# (No legacy password gate — individual user accounts handle all access control)

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

    # Determine which pages this user can see based on role + DB-loaded permissions
    _cur_user  = st.session_state.get("auth_user", {}) or {}
    _cur_role  = _cur_user.get("role", "admin") if _cur_user else "admin"
    # Use pages stored in auth_user at login (from roles table); fall back to static dict
    _base_pages = list(_cur_user.get("pages") or _ROLE_PAGES.get(_cur_role, _ROLE_PAGES["admin"]))

    # Show Get Started until secrets are saved AND all validation checks pass
    _setup_validated_ok = st.session_state.get("_setup_validated_ok", False)
    _setup_complete = _secrets_active and _setup_validated_ok

    if not _setup_complete and _cur_role == "admin":
        _nav_pages = ["Get Started"] + _base_pages
    else:
        _nav_pages = _base_pages

    # Ensure current value is valid
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

    # Show current user + logout
    if _cur_user:
        st.divider()
        st.caption(f"Signed in as **{_cur_user.get('full_name') or _cur_user.get('email', '')}**")
        st.caption(f"Role: {_cur_user.get('role', '').capitalize()}")
        if st.button("Sign Out", key="btn_signout", width='stretch'):
            st.session_state.pop("auth_user", None)
            st.session_state.pop("authenticated", None)
            st.rerun()

    st.caption("Version: **v1.8.0**")
    
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
        # Support comma-separated image URLs — use only the first one for emails
        if img_url and "," in img_url:
            img_url = img_url.split(",")[0].strip()
        if img_url and img_url not in ("N/A", ""):
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
                "total_cost":    _parse_money(tx.get('total', tx.get('total_cost', 0.0))),
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
    _gs_has_sb       = _has_supabase(cfg)
    _gs_has_turso_gs = _has_turso(cfg)
    _gs_has_img      = _has_image_host(cfg)
    _gs_has_smtp     = bool(cfg.get("smtp_email") and cfg.get("smtp_password"))
    _gs_has_identity = bool(cfg.get("from_name") and cfg.get("subject"))
    _gs_has_secrets  = False
    try:
        _gs_has_secrets = hasattr(st, "secrets") and "merit" in st.secrets
    except Exception:
        pass

    # Step 1 = users exist locally
    _gs_local_users = get_users_from_db(cfg)
    _gs_has_users   = not _gs_local_users.empty

    st.title("Get Started with MERIT")
    st.caption("Complete the steps below in order to fully configure MERIT for your firm.")

    st.info("**Device Recommendation:** MERIT runs on **Streamlit**, which often has issues on school-issued Chromebooks. For the best experience, use your **personal laptop** or your **school-provided VE laptop**.")
    st.error("**VE Email Requirement:** Use your **official VE email address** (e.g. yourcompanyname@veinternational.org) for all account registrations — Supabase, Turso, Gmail SMTP, and Image Hosting.")

    # ── Checklist ───────────────────────────────────────────────────
    _step1_ok = _gs_has_users
    _step2_ok = _gs_has_sb or _gs_has_turso_gs   # either cloud DB counts
    _step3_ok = _gs_has_img
    _step4_ok = _gs_has_smtp
    _step5_ok = _gs_has_identity
    _step6_ok = _gs_has_secrets and st.session_state.get("_setup_validated_ok", False)

    st.markdown("### Setup Checklist")
    _cl1, _cl2, _cl3, _cl4, _cl5, _cl6 = st.columns(6)
    with _cl1:
        if _step1_ok: st.success("Step 1 — Users")
        else: st.error("Step 1 — Create Users")
    with _cl2:
        if _step2_ok:
            _db_label = ("Supabase + Turso" if (_gs_has_sb and _gs_has_turso_gs)
                         else ("Turso" if _gs_has_turso_gs else "Supabase"))
            st.success(f"Step 2 — {_db_label}")
        else: st.warning("Step 2 — Connect DB")
    with _cl3:
        if _step3_ok: st.success("Step 3 — Images")
        else: st.warning("Step 3 — Add Key")
    with _cl4:
        if _step4_ok: st.success("Step 4 — Email")
        else: st.warning("Step 4 — Configure")
    with _cl5:
        if _step5_ok: st.success("Step 5 — Sender")
        else: st.warning("Step 5 — Identity")
    with _cl6:
        if _step6_ok: st.success("Step 6 — Secrets")
        else: st.warning("Step 6 — Save TOML")

    # ── Validation (auto-runs once secrets are saved and app reboots) ───
    if _gs_has_secrets:
        if "setup_validation_results" not in st.session_state:
            with st.spinner("Verifying all credentials from your Secrets TOML…"):
                _run_val = _validate_setup_credentials(cfg)
                _run_all_ok = all(r[0] != "err" for r in _run_val)
                st.session_state["setup_validation_results"] = _run_val
                st.session_state["_setup_validated_ok"] = _run_all_ok

        _val_results    = st.session_state["setup_validation_results"]
        _val_passed     = st.session_state.get("_setup_validated_ok", False)
        _val_has_errors = any(r[0] == "err" for r in _val_results)

        st.subheader("Credential Verification")
        if _val_passed:
            st.success("All checks passed — your setup is complete. Navigate to any page from the sidebar.")
        else:
            st.error(
                "Some checks failed. Fix the issues shown below, update your credentials in **Settings**, "
                "re-save the Secrets TOML, and click **Re-run Checks** below."
            )

        for _vs, _vl, _vd, _vf in _val_results:
            if _vs == "ok":
                st.success(f"**{_vl}** — {_vd}")
            elif _vs == "warn":
                with st.container(border=True):
                    st.warning(f"**{_vl}** — {_vd}")
                    if _vf:
                        st.caption(f"Fix: {_vf}")
            else:
                with st.container(border=True):
                    st.error(f"**{_vl}** — {_vd}")
                    if _vf:
                        st.markdown(f"**How to fix:** {_vf}")

        _vr_c1, _vr_c2 = st.columns([1, 4])
        with _vr_c1:
            if st.button("Re-run Checks", key="btn_rerun_val", type="secondary"):
                st.session_state.pop("setup_validation_results", None)
                st.session_state.pop("_setup_validated_ok", None)
                st.rerun()
        if _val_passed:
            with _vr_c2:
                if st.button("Enter MERIT →", key="btn_enter_merit", type="primary"):
                    _first_page = (
                        [p for p in list(_cur_user.get("pages") or _ROLE_PAGES.get(_cur_role, ["Mass Email"]))
                         if p != "Get Started"] or ["Mass Email"]
                    )[0]
                    st.session_state["sidebar_page"] = _first_page
                    st.rerun()

    st.divider()

    # ── STEP 1: Users & Custom Roles ─────────────────────────────────
    with st.expander("Step 1 — Create Your Admin Account (Do This First)", expanded=not _step1_ok):
        st.markdown("""
Create at least one **Admin** user so you can sign in after setup is complete.

**After setup is done** (secrets saved + app reboots), go to **Settings → Team** to invite additional
team members — they receive a shareable link and set their own password, no need to share credentials.

**Roles** control which pages each person can see. The three built-in roles cover most firms.
        """)

        _gs_roles_df = get_roles_from_db(cfg)
        _gs_role_options = list(_gs_roles_df["role_name"].values) if not _gs_roles_df.empty else ["admin", "staff", "viewer"]

        # ── Create User form ──────────────────────────────────────
        st.subheader("Add a User")
        _gs_u_c1, _gs_u_c2 = st.columns(2)
        with _gs_u_c1:
            _gs_u_name  = st.text_input("Full Name", placeholder="Jane Smith", key="gs_u_name")
            _gs_u_email = st.text_input("Email", placeholder="jane@yourfirm.org", key="gs_u_email")
        with _gs_u_c2:
            _gs_u_role  = st.selectbox(
                "Role", _gs_role_options,
                format_func=lambda r: _ROLE_LABELS.get(r, r.capitalize()),
                key="gs_u_role"
            )
            _gs_u_pass  = st.text_input("Password", type="password", key="gs_u_pass")
            _gs_u_pass2 = st.text_input("Confirm Password", type="password", key="gs_u_pass2")

        if st.button("Create User", type="primary", key="btn_gs_create_user"):
            if not _gs_u_name.strip():
                st.error("Full name is required.")
            elif not _gs_u_email.strip() or "@" not in _gs_u_email:
                st.error("A valid email is required.")
            elif len(_gs_u_pass) < 6:
                st.error("Password must be at least 6 characters.")
            elif _gs_u_pass != _gs_u_pass2:
                st.error("Passwords do not match.")
            else:
                _gs_ok, _gs_msg = create_user_all_dbs(
                    _gs_u_email.strip(), _gs_u_name.strip(), _gs_u_role, _gs_u_pass, cfg
                )
                if _gs_ok:
                    st.toast(f"User {_gs_u_name.strip()} created.", icon=None)
                    st.success(f"User **{_gs_u_name.strip()}** created with role **{_gs_u_role}**.")
                    _fetch_users_cached.clear()
                    st.rerun()
                else:
                    st.error(f"Failed: {_gs_msg}")

        # ── Existing users list ───────────────────────────────────
        if not _gs_local_users.empty:
            st.divider()
            st.subheader("Current Users")
            for _, _gu in _gs_local_users.iterrows():
                _gu_c1, _gu_c2, _gu_c3, _gu_c4 = st.columns([3, 2, 2, 1])
                _gu_c1.markdown(f"**{_gu.get('full_name', '')}**  \n{_gu.get('email', '')}")
                _gu_c2.caption(f"Role: **{_gu.get('role', '')}**")
                _pages_preview = ", ".join(get_pages_for_role(str(_gu.get("role", "")), cfg))
                _gu_c3.caption(_pages_preview)
                with _gu_c4:
                    if st.button("Remove", key=f"gs_del_{_gu.get('email', '')}", type="secondary"):
                        _del_ok, _del_msg = delete_user_all_dbs(str(_gu.get("email", "")), cfg)
                        if _del_ok:
                            st.toast("User removed.", icon=None)
                            _fetch_users_cached.clear()
                            st.rerun()
                        else:
                            st.error(f"Failed: {_del_msg}")
        else:
            st.info("No users yet. Create at least one Admin user above.")

        # ── Custom Roles ──────────────────────────────────────────
        st.divider()
        st.subheader("Custom Roles")
        st.caption("Create roles with exactly the page permissions your firm needs. Built-in roles (admin, staff, viewer) cannot be deleted.")

        with st.container(border=True):
            _gs_new_role_name = st.text_input("New Role Name", placeholder="e.g. finance", key="gs_new_role_name",
                                               help="Lowercase, no spaces. e.g. 'finance' or 'ceo'")
            st.caption("Select which pages this role can access:")
            _gs_page_cols = st.columns(len(_ALL_PAGES))
            _gs_checked_pages = []
            for _gpi, _gpname in enumerate(_ALL_PAGES):
                with _gs_page_cols[_gpi]:
                    if st.checkbox(_gpname, key=f"gs_pg_{_gpi}", value=True):
                        _gs_checked_pages.append(_gpname)
            if st.button("Create Role", key="btn_gs_create_role", type="primary"):
                _rn = _gs_new_role_name.strip().lower().replace(" ", "_")
                if not _rn:
                    st.error("Role name is required.")
                elif not _gs_checked_pages:
                    st.error("Select at least one page.")
                else:
                    _rok, _rmsg = create_role_all_dbs(_rn, _gs_checked_pages, cfg)
                    if _rok:
                        st.toast(f"Role {_rn} created.", icon=None)
                        st.success(f"Role **{_rn}** created.")
                        _fetch_roles_cached.clear()
                        st.rerun()
                    else:
                        st.error(f"Failed: {_rmsg}")

        # Show all roles
        if not _gs_roles_df.empty:
            st.subheader("All Roles")
            for _, _rrow in _gs_roles_df.iterrows():
                _rr1, _rr2, _rr3 = st.columns([2, 5, 1])
                _rr1.markdown(f"**{_rrow.get('role_name', '')}**")
                _rr2.caption(str(_rrow.get("pages", "")))
                with _rr3:
                    _is_builtin = _rrow.get("role_name", "") in ("admin", "staff", "viewer")
                    if not _is_builtin:
                        if st.button("Del", key=f"gs_del_role_{_rrow.get('role_name', '')}", type="secondary"):
                            _drok, _drmsg = delete_role_all_dbs(str(_rrow.get("role_name", "")), cfg)
                            if _drok:
                                st.toast("Role deleted.", icon=None)
                                _fetch_roles_cached.clear()
                                st.rerun()
                    else:
                        st.caption("built-in")

    # ── STEP 2: Database ──────────────────────────────────────────────
    with st.expander("Step 2 — Connect a Cloud Database (Supabase or Turso)", expanded=not _step2_ok and _step1_ok):
        st.markdown("""
MERIT needs a cloud database so your products, inventory, users, and financials persist
even when the app restarts. Connect **either Supabase or Turso** — or both for redundancy.
Both are free for VEI firms.
        """)

        _db_opt_tab1, _db_opt_tab2 = st.tabs(["Option A — Turso (Recommended)", "Option B — Supabase"])

        with _db_opt_tab1:
            st.markdown("""
Turso is a fast, distributed SQLite database — easy to set up and free for VEI firms.

**IMPORTANT:** Use your **official VE email address** when signing up.

#### 1. Sign in to Turso
Go to [turso.tech](https://turso.tech) and sign in with your VE email.

#### 2. Create your database
1. On the **Databases** page, click **Create database**.
2. **Name** — enter your organization name (e.g. `bluepeak-ventures`).
3. Leave the **Group** as the default.
4. Click **Create database**.

#### 3. Copy your Database URL
On the database page, look in the **Connect** section and copy the `libsql://` link.
It looks like: `libsql://[your-org-name]-[username].turso.io`

Paste it into **Settings → Database → Turso → Database URL**.

#### 4. Get your Auth Token
Right below the `libsql://` URL on your database page you will see a **Create a token** link — click it.

- **Expiration:** 1 year
- **Authorization:** Read & Write

Click **Create** and copy the long string of letters that appears (starts with `eyJ…`).

Paste it into **Settings → Database → Turso → Auth Token**.

> **Note:** This is a database-specific token — do NOT use the Platform API token from the sidebar avatar menu. That one only manages Turso itself and will be rejected with a 401 error.

#### 5. Setup tables
In MERIT go to **Settings → Database** and click **Setup Turso Tables**.
This creates all MERIT tables in Turso and syncs your users and roles from Step 1.
            """)
            if _gs_has_turso_gs:
                st.success("Turso is connected.")
            else:
                st.warning("Turso not yet configured — follow the steps above.")

        with _db_opt_tab2:
            st.markdown("""
Supabase is a PostgreSQL-based cloud database. It offers more features and works well for
larger firms or those already using Supabase.

**IMPORTANT:** Use your **official VE email address** when signing up.

#### 1. Sign up at Supabase
Go to [supabase.com](https://supabase.com) → **Sign Up** with your VE email.

#### 2. Create a new project

| Field | What to enter |
|---|---|
| **Organization** | Your VE email (pre-selected) |
| **Project name** | Your VEI firm name (e.g. `BluePeak Ventures`) |
| **Database password** | Create your own — **do NOT use Generate**. Write it down. |
| **Region** | Closest region to your location |

Click **Create new project** and wait about 60 seconds.

#### 3. Get your connection string

1. Click the green **Connect** button at the top right.
2. Select the **Session Pooler** tab.
3. Copy the connection string — it looks like:
   `postgresql://postgres.xxxxxxxxxxxx:[YOUR-PASSWORD]@aws-0-us-east-1.pooler.supabase.com:5432/postgres`
4. Go to **Settings → Database** and paste your connection string and password.
5. Click **Setup Tables** — this creates all MERIT tables AND syncs your users and roles from Step 1.

#### 4. Get your Anon Key (for API Endpoints)

1. Supabase Dashboard → gear icon (⚙) → **Project Settings** → **API**.
2. Under **Legacy API keys** → copy the **anon / public** key (starts with `eyJ…`).
3. Paste it into **Settings → Database → Supabase Anon Key**.
            """)
            if _gs_has_sb:
                st.success("Supabase is connected.")
            else:
                st.warning("Supabase not yet configured — follow the steps above.")

    # ── STEP 3: Image Hosting ─────────────────────────────────────────
    with st.expander("Step 3 — Set Up Image Hosting", expanded=not _step3_ok and _step2_ok):
        st.markdown("""
Product images must be hosted online. Pick one free service:

**Use your official VE email when signing up.**

#### Option A — Freeimage.host (recommended)
1. Go to [freeimage.host](https://freeimage.host) and sign in.
2. Click the top-left menu → **API** → copy your API key.
3. Paste it into **Settings → Image Hosting**.

#### Option B — Imghippo
1. Go to [imghippo.com](https://imghippo.com) → create a free account.
2. Go to Settings → API Keys → copy the API Version 1 key.
3. Paste it into **Settings → Image Hosting**.
        """)

    # ── STEP 4: Gmail SMTP ───────────────────────────────────────────
    with st.expander("Step 4 — Configure Gmail SMTP", expanded=not _step4_ok and _step3_ok):
        st.markdown("""
MERIT sends order emails via your official VE Gmail account.

1. Go to [myaccount.google.com](https://myaccount.google.com) → **Security** → enable **2-Step Verification**.
2. Search for **App passwords** → create one named `MERIT Email`.
3. Copy the 16-character password Google shows you.
4. In **Settings → Email**, paste your VE Gmail address and the App Password.
        """)

    # ── STEP 5: Sender Identity ──────────────────────────────────────
    with st.expander("Step 5 — Set Sender Identity", expanded=not _step5_ok and _step4_ok):
        st.markdown("""
Controls who the email appears to come from.

1. In **Settings → Email**, fill in **Sender Identity**:
   - **From Name**: Your VEI firm name (e.g. `Acme VEI`).
   - **Default Subject Line**: e.g. `Your order from Acme VEI`.
        """)

    # ── STEP 6: Secrets TOML ─────────────────────────────────────────
    with st.expander("Step 6 — Save Secrets TOML (Final Step)", expanded=not _step6_ok and _step5_ok):
        if _gs_has_secrets:
            # Secrets are active — point to the validation results above
            if st.session_state.get("_setup_validated_ok"):
                st.success("Secrets are active and all checks passed.")
            else:
                st.warning(
                    "Secrets are active but some checks failed. "
                    "See **Credential Verification** above for details on what to fix."
                )
        else:
            st.markdown("""
Streamlit Cloud forgets everything on reboot. Saving a **Secrets TOML** makes all your credentials permanent.
After saving and rebooting, MERIT automatically verifies every credential.

1. Complete Steps 1–5 above.
2. Go to **Settings → Secrets** tab and copy the generated code block.
3. Click **Manage app** (bottom-right corner of your Streamlit Cloud page) → **⋮** → **Settings** → **Secrets**.
4. Paste the block and click **Save**.
5. Go back to **Manage app** → click **⋮** → click **Reboot app**.
6. Wait for the app to come back online — MERIT will run a full credential check automatically. Fix any issues flagged above, then you are done.
            """)

    st.divider()
    st.subheader("What each page does")
    st.markdown("""
| Page | What it does |
|---|---|
| **Mass Email** | Upload CSV orders, send bulk emails, manage templates and campaigns |
| **Products** | Add, edit, and delete products with images and descriptions |
| **Inventory** | Stock overview, adjust stock, and original stock tracking |
| **Financials** | Revenue overview, ledger, order history, and product revenue breakdowns |
| **Settings** | All credentials — Supabase, Turso, email, image hosting, team management with invite links |
| **API Endpoints** | Pre-built code to connect your website to the live product database |
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
    _has_cloud_db = _has_supabase(cfg) or _has_turso(cfg)
    if not _has_cloud_db:
        st.warning(
            "**No cloud database connected.** Products are only saved locally to `data.db` on this machine. "
            "If this computer is lost or the app is redeployed, all product and inventory data will be gone. "
            "Go to **Settings → Database** to connect Turso or Supabase."
        )

    if "_products_cache" not in st.session_state:
        with st.spinner("Loading products…"):
            st.session_state["_products_cache"] = load_products_for_catalog(cfg)
    products = st.session_state["_products_cache"]

    # Compute sync targets for display in this page
    _p_has_sb = _has_supabase(cfg)
    _p_has_turso_p = _has_turso(cfg)
    _p_sync = ["SQLite"] + (["Turso"] if _p_has_turso_p else []) + (["Supabase"] if _p_has_sb else [])
    _p_sync_str = " + ".join(_p_sync)

    tab_catalog, tab_add, tab_edit, tab_delete, tab_prod_docs = st.tabs(
        ["Catalog", "Add Products", "Edit Products", "Delete Products", "Documentation"]
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
                _img_raw = prod.get("image_url", "N/A")
                # Use first URL when multiple images are stored comma-separated
                _img = _img_raw.split(",")[0].strip() if _img_raw and "," in _img_raw else _img_raw
                has_img = bool(_img and _img not in ("N/A", ""))

                _c_img, _c_txt, _c_act = st.columns([1, 5, 2], vertical_alignment="center")
                with _c_img:
                    if has_img:
                        st.image(_img, width=80)
                    else:
                        st.markdown("<div style='width:80px;height:80px;background:#f4f4f5;border-radius:8px;display:flex;align-items:center;justify-content:center;color:#bbb;font-size:11px;'>No image</div>", unsafe_allow_html=True)
                with _c_txt:
                    _store_active = prod.get("active", True)
                    _store_badge = "In Store" if _store_active else "Out of Store"
                    st.markdown(f"**{_name}**  ·  {_store_badge}")
                    st.caption(f"`{_sku}`  ·  {prod.get('category','General')}  ·  ${prod.get('price',0):.2f}  ·  Stock: {prod.get('stock_left',0)}")
                    if prod.get("description"):
                        st.caption(f"{prod['description'][:120]}")
                    if prod.get("buy_button_url"):
                        st.caption(f"[Buy Button]({prod['buy_button_url']})")
                
                with _c_act:
                    with st.popover("Add Image", width="stretch"):
                        st.markdown("##### Add Product Image")
                        _new_file = st.file_uploader("img", type=["jpg","jpeg","png","webp"], key=f"cat_repl_{_sku}_{i}", label_visibility="collapsed")
                        if _new_file and _has_image_host(cfg):
                            if st.button("Upload & Save", key=f"cat_repl_btn_{_sku}_{i}", type="primary", width="stretch"):
                                with st.spinner("Uploading..."):
                                    try:
                                        _new_url = upload_image(_new_file.read(), cfg, name=_name)
                                        _cur_urls_cat = [u.strip() for u in str(_img_raw).split(",") if u.strip() and u.strip() != "N/A"]
                                        _cur_urls_cat.insert(0, _new_url)  # prepend so new image becomes the primary
                                        _combined_url = ",".join(_cur_urls_cat)
                                        prod["image_url"] = _combined_url
                                        save_product_to_db(prod, cfg)
                                        _cfg_prods = [dict(p) for p in cfg.get("products", [])]
                                        for _cpc in _cfg_prods:
                                            if _cpc.get("sku") == _sku:
                                                _cpc["image_url"] = _combined_url
                                        cfg["products"] = _cfg_prods
                                        save_config(cfg)
                                        st.session_state.cfg = cfg
                                        st.toast("Image added.", icon=None)
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
        st.info("Everything you type in the product names must be the same as in the VEI Store Manager and the Wholesale Marketplace for inventory deduction to work correctly.")
        st.caption(f"Add products individually or in bulk. Syncing to: **{_p_sync_str}**")
        
        _add_single_exp = st.expander("Add Single Product", expanded=True)
        with _add_single_exp:
            col_left, col_right = st.columns([3, 2])
            with col_left:
                p_sku           = st.text_input("SKU *",          placeholder="SKU-001",      key="p_sku")
                p_name          = st.text_input(
                    "Product Name *", placeholder="Blue T-Shirt", key="p_name",
                    help="IMPORTANT: This must match EXACTLY the Item Name you used in the VEI Store Manager — including capitalization and spacing. The Buy Button URL is generated from this name.",
                )
                p_category      = st.text_input("Category",       placeholder="Clothing",     key="p_category")
                p_price         = st.number_input("Price ($)", min_value=0.0, step=0.01, format="%.2f", key="p_price")
                p_description   = st.text_area("Description", placeholder="Short product description shown on storefront.", key="p_description", height=80)
                p_buy_btn_url   = st.text_input(
                    "Buy Button URL",
                    placeholder="https://portal.veinternational.org/buybuttons/us019814/btn/product-name/",
                    key="p_buy_btn_url",
                    help="VEI buy button link. The slug at the end must match exactly your Store Manager item name (lowercased, spaces replaced with hyphens). Example: 'Blue T-Shirt' → .../btn/blue-t-shirt/",
                )
                if p_name.strip() and not st.session_state.get("p_buy_btn_url"):
                    _auto_slug = re.sub(r'[^a-z0-9\-]', '-', p_name.strip().lower()).strip('-')
                    _auto_slug = re.sub(r'-+', '-', _auto_slug)
                    st.caption(f"Suggested URL slug: `…/btn/{_auto_slug}/`")
                p_store_status  = st.selectbox("Store Status", ["In Store", "Out of Store"], index=0, key="p_store_status",
                                               help="In Store = visible on your storefront. Out of Store = hidden from customers.")
            with col_right:
                p_images = st.file_uploader(
                    "Product Images",
                    type=["jpg", "jpeg", "png", "webp"],
                    key="p_image",
                    accept_multiple_files=True,
                    help="Upload one or more images. Multiple images are stored as a comma-separated list; the first image appears in emails and on the storefront.",
                )
                if p_images:
                    _prev_cols = st.columns(min(len(p_images), 3))
                    for _pi, _pf in enumerate(p_images):
                        _prev_cols[_pi % 3].image(_pf, use_container_width=True)

            if st.button("Add Product", type="primary", width="stretch", key="btn_add_product"):
                if not p_sku.strip():
                    st.error("SKU is required.")
                elif not p_name.strip():
                    st.error("Product Name is required.")
                else:
                    image_url = "N/A"
                    if p_images:
                        if not _has_image_host(cfg):
                            st.warning("Images skipped — add an image hosting key in Settings first.")
                        else:
                            with st.spinner(f"Uploading {len(p_images)} image(s) and adding product..."):
                                _uploaded_urls = []
                                for _img_file in p_images:
                                    try:
                                        _img_file.seek(0)
                                        _url = upload_image(_img_file.read(), cfg, name=p_name.strip())
                                        _uploaded_urls.append(_url)
                                    except Exception as _img_err:
                                        st.error(f"Image upload failed: {_img_err}")
                                if _uploaded_urls:
                                    image_url = ",".join(_uploaded_urls)
                    product = {
                        "sku":            p_sku.strip().upper(),
                        "item_name":      p_name.strip(),
                        "category":       p_category.strip() or "General",
                        "price":          round(float(p_price), 2),
                        "stock_left":     0,
                        "status":         "In stock",
                        "description":    p_description.strip(),
                        "buy_button_url": p_buy_btn_url.strip(),
                        "active":         p_store_status == "In Store",
                        "image_url":      image_url,
                    }
                    ok, saved_to = save_product_to_db(product, cfg)
                    if not ok:
                        st.toast("Something went wrong. Please try again.", icon=None)
                    _cp = cfg.get("products", [])
                    cfg["products"] = [p for p in _cp if p.get("sku") != product["sku"]]
                    cfg["products"].append(product)
                    save_config(cfg)
                    st.session_state.cfg = cfg
                    st.toast("Product added successfully.", icon=None)
                    st.success(f"**{product['item_name']}** added · Synced to: {saved_to}")
                    _clear_data_caches()
                    time.sleep(0.5)
                    st.rerun()

        _add_bulk_exp = st.expander("Add Bulk Products", expanded=False)
        with _add_bulk_exp:
            st.caption("Add multiple products at once. Each card has full fields — SKU, Name, Category, Price, Description, Buy URL, and Image.")

            # CSV import at the top
            _bulk_csv_col, _bulk_csv_btn = st.columns([3, 1])
            with _bulk_csv_col:
                _bulk_csv = st.file_uploader(
                    "Import from CSV (SKU, Name, Category, Price, Description, BuyURL)",
                    type=["csv"], key="bulk_csv",
                    help="Columns auto-detected. At minimum include SKU and Name.",
                )
            with _bulk_csv_btn:
                st.markdown("<div style='height:28px;'></div>", unsafe_allow_html=True)
                if _bulk_csv and st.button("Load CSV Rows", key="pb_load_csv", width="stretch"):
                    try:
                        _csv_df = pd.read_csv(_bulk_csv)
                        _csv_df.columns = [c.strip() for c in _csv_df.columns]
                        _csv_cmap = {}
                        for _c in _csv_df.columns:
                            _cl = _c.lower()
                            if "sku" in _cl: _csv_cmap[_c] = "SKU"
                            elif "name" in _cl or "product" in _cl: _csv_cmap[_c] = "Name"
                            elif "cat" in _cl: _csv_cmap[_c] = "Category"
                            elif "price" in _cl: _csv_cmap[_c] = "Price"
                            elif "desc" in _cl: _csv_cmap[_c] = "Description"
                            elif "url" in _cl or "buy" in _cl: _csv_cmap[_c] = "BuyURL"
                        _csv_df = _csv_df.rename(columns=_csv_cmap)
                        if "pb_ids" not in st.session_state:
                            st.session_state.pb_ids  = []
                            st.session_state.pb_next = 0
                        _nxt = st.session_state.pb_next
                        for _, _r in _csv_df.iterrows():
                            _sv = str(_r.get("SKU", "")).strip().upper()
                            _nv = str(_r.get("Name", "")).strip()
                            if not _sv or not _nv:
                                continue
                            st.session_state[f"pb_sku_{_nxt}"]    = _sv
                            st.session_state[f"pb_name_{_nxt}"]   = _nv
                            st.session_state[f"pb_cat_{_nxt}"]    = str(_r.get("Category", "General")).strip() or "General"
                            st.session_state[f"pb_price_{_nxt}"]  = float(_r.get("Price", 0) or 0)
                            st.session_state[f"pb_desc_{_nxt}"]   = str(_r.get("Description", "")).strip()
                            st.session_state[f"pb_buyurl_{_nxt}"] = str(_r.get("BuyURL", "")).strip()
                            st.session_state.pb_ids.append(_nxt)
                            _nxt += 1
                        st.session_state.pb_next = _nxt
                        st.toast(f"Loaded {_nxt - (st.session_state.pb_next - _nxt + _nxt - st.session_state.pb_next)} rows", icon=None)
                        st.rerun()
                    except Exception as _pce:
                        st.error(f"CSV load error: {_pce}")

            st.divider()

            if "pb_ids" not in st.session_state:
                st.session_state.pb_ids  = list(range(3))
                st.session_state.pb_next = 3

            for _rid in list(st.session_state.pb_ids):
                with st.container(border=True):
                    _pb_r1 = st.columns([1.2, 2, 1.2, 1.2, 0.35])
                    with _pb_r1[0]:
                        st.text_input("SKU *", key=f"pb_sku_{_rid}", placeholder="SKU-001")
                    with _pb_r1[1]:
                        st.text_input("Product Name *", key=f"pb_name_{_rid}", placeholder="Blue T-Shirt")
                    with _pb_r1[2]:
                        st.text_input("Category", key=f"pb_cat_{_rid}", placeholder="General")
                    with _pb_r1[3]:
                        st.number_input("Price ($)", key=f"pb_price_{_rid}", min_value=0.0, step=0.01, format="%.2f")
                    with _pb_r1[4]:
                        st.markdown("<div style='margin-top:24px;'></div>", unsafe_allow_html=True)
                        if st.button("×", key=f"pb_del_{_rid}", help="Remove row"):
                            st.session_state.pb_ids.remove(_rid)
                            st.rerun()
                    _pb_r2 = st.columns([2, 2, 2])
                    with _pb_r2[0]:
                        st.text_area("Description", key=f"pb_desc_{_rid}", placeholder="Short product description…", height=68)
                    with _pb_r2[1]:
                        st.text_input("Buy Button URL", key=f"pb_buyurl_{_rid}", placeholder="https://portal.veinternational.org/…")
                    with _pb_r2[2]:
                        st.file_uploader("Product Image", key=f"pb_img_{_rid}", type=["jpg","jpeg","png","webp"])

            _pb_act1, _pb_act2 = st.columns(2)
            with _pb_act1:
                if st.button("+ Add Product Row", width="stretch", key="pb_add_row"):
                    st.session_state.pb_ids.append(st.session_state.pb_next)
                    st.session_state.pb_next += 1
                    st.rerun()
            with _pb_act2:
                if st.button("Add All to Products", type="primary", width="stretch", key="btn_bulk_add"):
                    with st.spinner("Processing products..."):
                        _pb_rows = []
                        for _rid in st.session_state.pb_ids:
                            _bsku  = str(st.session_state.get(f"pb_sku_{_rid}", "")).strip().upper()
                            _bname = str(st.session_state.get(f"pb_name_{_rid}", "")).strip()
                            if _bsku and _bname:
                                _pb_rows.append({
                                    "sku":    _bsku,
                                    "name":   _bname,
                                    "cat":    str(st.session_state.get(f"pb_cat_{_rid}", "")).strip() or "General",
                                    "price":  round(float(st.session_state.get(f"pb_price_{_rid}", 0.0)), 2),
                                    "desc":   str(st.session_state.get(f"pb_desc_{_rid}", "")).strip(),
                                    "buyurl": str(st.session_state.get(f"pb_buyurl_{_rid}", "")).strip(),
                                    "img":    st.session_state.get(f"pb_img_{_rid}"),
                                })

                        added = 0
                        for _r in _pb_rows:
                            _url = "N/A"
                            if _r["img"] and _has_image_host(cfg):
                                try:
                                    _r["img"].seek(0)
                                    _url = upload_image(_r["img"].read(), cfg, name=_r["name"])
                                except Exception: pass
                            _p = {
                                "sku": _r["sku"], "item_name": _r["name"], "category": _r["cat"],
                                "price": _r["price"], "stock_left": 0, "status": "In stock",
                                "image_url": _url, "description": _r["desc"],
                                "buy_button_url": _r["buyurl"], "active": True,
                            }
                            save_product_to_db(_p, cfg)
                            _cp = cfg.get("products", [])
                            cfg["products"] = [x for x in _cp if x.get("sku") != _r["sku"]]
                            cfg["products"].append(_p)
                            added += 1
                        save_config(cfg)
                        st.session_state.cfg = cfg
                        st.session_state.pb_ids  = list(range(3))
                        st.session_state.pb_next = 3
                        st.toast(f"Added {added} products.", icon=None)
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
                # Show current images (comma-separated support)
                _cur_img_raw = str(_eprod.get("image_url", "N/A"))
                _cur_urls = [u.strip() for u in _cur_img_raw.split(",") if u.strip() and u.strip() != "N/A"]
                if _cur_urls:
                    st.markdown("**Current images** — first image is used in emails and on storefront")
                    _img_disp_cols = st.columns(min(len(_cur_urls), 4))
                    for _ci, _curl in enumerate(_cur_urls):
                        with _img_disp_cols[_ci % 4]:
                            st.image(_curl, use_container_width=True)
                            st.caption(f"Image {_ci + 1}{' (primary)' if _ci == 0 else ''}")
                            _eimg_c1, _eimg_c2 = st.columns(2)
                            with _eimg_c1:
                                if st.button(f"Remove", key=f"rm_img_{_edit_sku}_{_ci}", width='stretch'):
                                    _new_urls = [u for idx2, u in enumerate(_cur_urls) if idx2 != _ci]
                                    _eprod["image_url"] = ",".join(_new_urls) if _new_urls else "N/A"
                                    save_product_to_db(_eprod, cfg)
                                    _cp2 = cfg.get("products", [])
                                    cfg["products"] = [dict(p, image_url=_eprod["image_url"]) if p.get("sku") == _edit_sku else p for p in _cp2]
                                    save_config(cfg)
                                    st.session_state.cfg = cfg
                                    _clear_data_caches()
                                    st.rerun()
                            with _eimg_c2:
                                with st.popover("Replace", use_container_width=True):
                                    st.markdown(f"**Replace image {_ci + 1}**")
                                    _repl_file = st.file_uploader(
                                        "New image", type=["jpg","jpeg","png","webp"],
                                        key=f"repl_{_edit_sku}_{_ci}",
                                        label_visibility="collapsed",
                                    )
                                    if _repl_file:
                                        st.image(_repl_file, use_container_width=True)
                                        if _has_image_host(cfg):
                                            if st.button("Upload & Replace", key=f"repl_btn_{_edit_sku}_{_ci}", type="primary", width='stretch'):
                                                with st.spinner("Uploading replacement…"):
                                                    try:
                                                        _repl_file.seek(0)
                                                        _new_repl_url = upload_image(_repl_file.read(), cfg, name=str(_eprod.get("item_name", _edit_sku)))
                                                        _replaced = list(_cur_urls)
                                                        _replaced[_ci] = _new_repl_url
                                                        _eprod["image_url"] = ",".join(_replaced)
                                                        save_product_to_db(_eprod, cfg)
                                                        _cp3 = cfg.get("products", [])
                                                        cfg["products"] = [dict(p, image_url=_eprod["image_url"]) if p.get("sku") == _edit_sku else p for p in _cp3]
                                                        save_config(cfg)
                                                        st.session_state.cfg = cfg
                                                        _clear_data_caches()
                                                        st.toast("Image replaced.", icon=None)
                                                        st.rerun()
                                                    except Exception as _re:
                                                        st.error(f"Replace failed: {_re}")
                                        else:
                                            st.warning("Configure image hosting in Settings first.")

                with st.form(key=f"edit_form_{_edit_sku}"):
                    _e_c1, _e_c2 = st.columns(2)
                    with _e_c1:
                        _e_name       = st.text_input("Product Name *", value=str(_eprod.get("item_name", "")))
                        _e_cat        = st.text_input("Category",       value=str(_eprod.get("category", "")))
                        _e_price      = st.number_input("Price ($)", value=float(_eprod.get("price", 0.0)), min_value=0.0, step=0.01, format="%.2f")
                        _e_store_idx  = 0 if _eprod.get("active", True) else 1
                        _e_store      = st.selectbox("Store Status", ["In Store", "Out of Store"], index=_e_store_idx,
                                                     help="In Store = visible on storefront. Out of Store = hidden from customers.")
                    with _e_c2:
                        _e_desc       = st.text_area("Description", value=str(_eprod.get("description", "")), height=80)
                        _e_buy_url    = st.text_input(
                            "Buy Button URL",
                            value=str(_eprod.get("buy_button_url", "")),
                            placeholder="https://portal.veinternational.org/buybuttons/us019814/btn/product-name/",
                            help="VEI buy button link consumers click to purchase.",
                        )
                        _e_files = st.file_uploader(
                            "Add images",
                            type=["jpg", "png", "webp", "jpeg"],
                            key=f"e_file_{_edit_sku}",
                            accept_multiple_files=True,
                            help="Upload new images to add to this product. Existing images are kept unless you remove them above.",
                        )

                    if st.form_submit_button("Save Changes", type="primary", width="stretch"):
                        with st.spinner("Saving..."):
                            _existing_urls = [u.strip() for u in str(_eprod.get("image_url", "N/A")).split(",") if u.strip() and u.strip() != "N/A"]
                            if _e_files and _has_image_host(cfg):
                                for _ef in _e_files:
                                    try:
                                        _new_u = upload_image(_ef.read(), cfg, name=_e_name.strip() or _edit_sku)
                                        _existing_urls.append(_new_u)
                                    except Exception as _eu_err:
                                        st.error(f"Image upload failed: {_eu_err}")
                            _final_url = ",".join(_existing_urls) if _existing_urls else "N/A"

                            _upd = {
                                "sku":            _edit_sku,
                                "item_name":      _e_name.strip() or _eprod.get("item_name", ""),
                                "category":       _e_cat.strip() or _eprod.get("category", "General"),
                                "price":          round(_e_price, 2),
                                "image_url":      _final_url,
                                "stock_left":     _eprod.get("stock_left", 0),
                                "status":         _eprod.get("status", "In stock"),
                                "description":    _e_desc.strip(),
                                "buy_button_url": _e_buy_url.strip(),
                                "active":         _e_store == "In Store",
                            }
                            _ok, _msg = save_product_to_db(_upd, cfg)
                            if not _ok: st.toast("Error saving to database.", icon=None)
                            _cp = cfg.get("products", [])
                            cfg["products"] = [_upd if p.get("sku") == _edit_sku else p for p in _cp]
                            if not any(p.get("sku") == _edit_sku for p in _cp): cfg["products"].append(_upd)
                            save_config(cfg)
                            st.session_state.cfg = cfg
                            st.toast("Product updated.", icon=None)
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
                        st.toast(f"Deleted {len(_bd_selected)} items.", icon=None)
                        _clear_data_caches()
                        time.sleep(0.5)
                        st.rerun()

    with tab_prod_docs:
        st.subheader("Products Page Documentation")
        st.markdown("""
### How the Products System Works

MERIT maintains two synchronized tables for every product:

| Table | Purpose |
|---|---|
| **products** | Clean catalog — name, price, description, buy button URL, store status (In Store / Out of Store) |
| **inventory** | Stock tracking — same product info plus `stock_left`, `status`, `original_stock` |

Both tables are updated simultaneously whenever you add, edit, or delete a product.

---

### Product Fields

| Field | Required | Notes |
|---|---|---|
| **SKU** | Yes | Unique product code. Use something consistent like `SKU-001`. Cannot be changed after creation — delete and re-add if needed. |
| **Product Name** | Yes | **MUST match exactly** the Item Name in VEI Store Manager (same capitalization, same spacing). This is used for inventory deduction matching when emails are sent. |
| **Category** | No | Used for filtering on your storefront website. Keep consistent (e.g. always "Apparel" not sometimes "apparel"). |
| **Price** | Yes | Retail price in USD. |
| **Description** | No | Shown on your storefront product detail page. Can be empty. |
| **Buy Button URL** | No | Direct VEI purchase link. The slug after `/btn/` must match your Store Manager item name (lowercased, spaces → hyphens). Example: `Blue T-Shirt` → `.../btn/blue-t-shirt/` |
| **Store Status** | Yes | **In Store** = visible on storefront. **Out of Store** = hidden from customers. Corresponds to `active = true/false` in the database. |
| **Product Image** | No | Uploaded to Freeimage.host or Imghippo. Multiple images supported — first image is used in order confirmation emails and as the primary storefront image. |

---

### Adding Products

**Single Product** — fill in the form and click **Add Product**. Images are uploaded automatically.

**Bulk Products** — use the card-based form to add multiple products at once, or import from a CSV file. CSV must have at minimum `SKU` and `Name` columns.

---

### Editing Products

Select a product from the dropdown. You can:
- **Remove** an existing image (removes that URL from the comma-separated list)
- **Replace** an existing image (uploads a new one and swaps it in place)
- **Add new images** (appends to the list, new images become secondary)
- Edit all other fields

Click **Save Changes** to update both the products and inventory tables simultaneously.

---

### Deleting Products

Deleting a product removes it from **both** the products and inventory tables in SQLite and Supabase. This action is permanent — there is no undo.

---

### Store Status vs. Stock Status

These are two separate flags:

- **Store Status** (`active` field in products table): Is the product listed on your storefront? Set in Products → Edit Products.
- **Stock Status** (`status` field in inventory table): Is the product physically in stock? Set automatically based on `stock_left` in Inventory → Adjust Stock.

A product can be "In Store" but "Out of stock" (listed but sold out). Your storefront should respect both: show an "Out of stock" badge but still display the product.

---

### Buy Button URL — VEI Specific

The buy button URL format is:
```
https://portal.veinternational.org/buybuttons/[FIRM-ID]/btn/[product-name]/
```

Where `[product-name]` is your Store Manager item name, lowercased with spaces replaced by hyphens. **This must match exactly** what VEI has configured in the Store Manager, or the button will return a 404 error.
        """)


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
    st.caption("Stock overview and adjustments. See the **Financials** page for revenue and ledger tracking.")

    tab_overview, tab_adjust, tab_original, tab_inv_docs, tab_inv_reset = st.tabs(
        ["Overview", "Adjust Stock", "Original Stock", "Documentation", "Reset Inventory"]
    )

    # Load shared data
    if "_inv_cache" not in st.session_state:
        with st.spinner("Loading inventory…"):
            st.session_state["_inv_cache"] = load_inventory_preferring_cloud(cfg)
    inv_df = st.session_state["_inv_cache"]
    _has_sb_inv  = _has_supabase(cfg)
    _has_trs_inv = _has_turso(cfg)

    # ── OVERVIEW ────────────────────────────────
    with tab_overview:
        if inv_df.empty:
            st.info("No products found. Add products in the **Products** page first.")
        else:
            _ov_stock    = inv_df["stock_left"].fillna(0).astype(int)
            _ov_orig     = inv_df.get("original_stock", pd.Series([0]*len(inv_df))).fillna(0).astype(int)
            _ov_price    = inv_df.get("price", pd.Series([0.0]*len(inv_df))).fillna(0)

            # Revenue from outbound logs
            _ov_logs = load_outbound_logs(cfg)
            _ov_total_rev = 0.0
            _ov_total_ord = 0
            if not _ov_logs.empty:
                _cost_col_ov = "total_cost" if "total_cost" in _ov_logs.columns else None
                if _cost_col_ov:
                    _ov_total_rev = pd.to_numeric(_ov_logs[_cost_col_ov], errors="coerce").fillna(0).sum()
                    _ov_total_ord = len(_ov_logs)

            # ── KPI Metrics ─────────────────────────
            _ov_r1c1, _ov_r1c2, _ov_r1c3, _ov_r1c4 = st.columns(4)
            _ov_r1c1.metric("Total Products",    len(inv_df))
            _ov_r1c2.metric("Total Stock Units", int(_ov_stock.sum()))
            _ov_r1c3.metric("Low Stock Items",   int(((_ov_stock > 0) & (_ov_stock <= 10)).sum()))
            _ov_r1c4.metric("Out of Stock",      int((_ov_stock == 0).sum()))

            _ov_r2c1, _ov_r2c2, _ov_r2c3, _ov_r2c4 = st.columns(4)
            _ov_r2c1.metric("Total Revenue",     f"${_ov_total_rev:,.2f}")
            _ov_r2c2.metric("Total Orders Sent", f"{_ov_total_ord:,}")
            _ov_catalog_val = float((_ov_stock * _ov_price.values).sum())
            _ov_r2c3.metric("Inventory Value",   f"${_ov_catalog_val:,.2f}")
            _ov_r2c4.metric("Backordered",       int((_ov_stock < 0).sum()))

            st.divider()

            # ── Stock Level Chart ───────────────────
            if "item_name" in inv_df.columns:
                _ov_chart = (
                    inv_df[["item_name", "stock_left"]]
                    .copy()
                    .rename(columns={"item_name": "Product", "stock_left": "Stock Left"})
                    .sort_values("Stock Left", ascending=False)
                    .set_index("Product")
                )
                st.subheader("Current Stock Levels")
                st.bar_chart(_ov_chart["Stock Left"], color="#4F46E5")

            st.divider()

            # ── Full Product Stock Table ────────────
            st.subheader("All Products")
            _tbl_cols = ["item_name", "sku", "category", "price", "stock_left", "original_stock", "status"]
            _tbl_df = inv_df[[c for c in _tbl_cols if c in inv_df.columns]].copy()
            _tbl_df = _tbl_df.rename(columns={
                "item_name": "Product", "sku": "SKU", "category": "Category",
                "price": "Price ($)", "stock_left": "Current Stock",
                "original_stock": "Original Stock", "status": "Status"
            })
            st.dataframe(
                _tbl_df,
                use_container_width=True,
                hide_index=True,
                column_config={
                    "Price ($)": st.column_config.NumberColumn(format="$%.2f"),
                    "Current Stock": st.column_config.NumberColumn(),
                    "Original Stock": st.column_config.NumberColumn(),
                }
            )
            st.caption("To modify stock levels use **Adjust Stock** or **Original Stock** tabs. To edit product details go to the **Products** page.")

    # ── ADJUST STOCK ────────────────────────────
    with tab_adjust:
        if inv_df.empty:
            st.info("No products found. Add products in the **Products** page first.")
        else:
            _sync_targets = ["SQLite"]
            if _has_trs_inv: _sync_targets.append("Turso")
            if _has_sb_inv:  _sync_targets.append("Supabase")

            st.info(
                "**Adjust Stock** makes manual corrections to **Current Stock only**. "
                "Use it to fix errors or write-offs. "
                "To record new inventory purchases, use the **Original Stock** tab instead."
            )
            st.caption(f"Synced to: **{' + '.join(_sync_targets)}**")

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
                        if _has_turso(cfg): adjust_inventory_turso(_asku, _adelta, cfg)
                        _adj_applied += 1
                    if _adj_applied:
                        st.toast("Stock updated successfully.", icon=None)
                        st.success(f"Applied {_adj_applied} adjustment(s) · {' + '.join(_sync_targets)}")
                        _clear_data_caches()
                        time.sleep(0.5)
                        st.rerun()
                    else:
                        st.warning("All deltas are 0 — set a non-zero amount first.")

            st.divider()

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
                        _first_img = _pimg.split(",")[0].strip()
                        if _first_img: st.image(_first_img, width=56)
                    else:
                        st.markdown("<div style='width:56px;height:56px;background:#f4f4f5;border-radius:8px;display:flex;align-items:center;justify-content:center;color:#bbb;font-size:10px;'>No img</div>", unsafe_allow_html=True)
                with _rc2:
                    st.markdown(f"**{_pname}**")
                    st.caption(f"{_psku}  ·  {_pcat}")
                with _rc3:
                    st.markdown(
                        f"<div style='display:flex;align-items:center;'>"
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
                                    st.toast("Something went wrong. Please try again.", icon=None)
                                if _has_sb_inv: adjust_inventory_supabase(_psku, int(_delta_val), cfg)
                                if _has_turso(cfg): adjust_inventory_turso(_psku, int(_delta_val), cfg)
                                st.toast(f"Stock updated: {_pname}", icon=None)
                                _clear_data_caches()
                                time.sleep(0.5)
                                st.rerun()
            st.divider()

    # ── ORIGINAL STOCK ──────────────────────────
    with tab_original:
        if inv_df.empty:
            st.info("No products found. Add products in the **Products** page first.")
        else:
            st.markdown("#### Restock — Add or Subtract Inventory")
            st.info(
                "**This is the main way to record new inventory.**  \n"
                "When you purchase stock from the VEI Wholesale Marketplace, enter the amount here. "
                "The number you enter is **added to** (or subtracted from) both the Original Stock total "
                "and the Current Stock available for sale. "
                "Current Stock is then automatically reduced each time order emails are sent."
            )

            _sync_targets_orig = ["SQLite"]
            if _has_trs_inv: _sync_targets_orig.append("Turso")
            if _has_sb_inv:  _sync_targets_orig.append("Supabase")
            st.caption(f"Synced to: **{' + '.join(_sync_targets_orig)}**")

            st.divider()

            for _, _pr in inv_df.iterrows():
                _osku    = str(_pr.get("sku", ""))
                _oname   = str(_pr.get("item_name", _osku))
                _ostock  = int(_pr.get("original_stock", 0))
                _ocurr   = int(_pr.get("stock_left", 0))
                _oimg    = str(_pr.get("image_url", ""))

                _oc1, _oc2, _oc3, _oc4, _oc5 = st.columns([1, 3.5, 2.5, 2, 1.5], vertical_alignment="center")
                with _oc1:
                    if _oimg and _oimg not in ("N/A", "", "nan"):
                        _ofirst = _oimg.split(",")[0].strip()
                        if _ofirst: st.image(_ofirst, width=56)
                    else:
                        st.markdown("<div style='width:56px;height:56px;background:#f4f4f5;border-radius:8px;display:flex;align-items:center;justify-content:center;color:#bbb;font-size:10px;'>No img</div>", unsafe_allow_html=True)
                with _oc2:
                    st.markdown(f"**{_oname}**")
                    st.caption(f"{_osku}")
                with _oc3:
                    st.markdown(
                        f"<div style='display:flex;gap:24px;'>"
                        f"<div><div style='font-size:20px;font-weight:700;color:#818cf8;'>{_ostock}</div>"
                        f"<div style='font-size:10px;color:#94a3b8;'>Original</div></div>"
                        f"<div><div style='font-size:20px;font-weight:700;color:#ffffff;'>{_ocurr}</div>"
                        f"<div style='font-size:10px;color:#94a3b8;'>Current</div></div>"
                        f"</div>",
                        unsafe_allow_html=True
                    )
                with _oc4:
                    _restock_delta = st.number_input(
                        "Add / Subtract", step=1, value=0,
                        key=f"orig_delta_{_osku}", label_visibility="collapsed",
                        help="Positive = bought more stock. Negative = reduce due to loss or return."
                    )
                with _oc5:
                    if st.button("Apply", key=f"btn_orig_{_osku}", width="stretch", type="primary"):
                        with st.spinner("Applying..."):
                            if _restock_delta == 0:
                                st.toast(f"{_oname}: amount is 0, nothing changed.")
                            else:
                                ok, _msg = adjust_original_stock_all_dbs(_osku, int(_restock_delta), cfg)
                                if ok:
                                    _dir = "added" if _restock_delta > 0 else "removed"
                                    st.toast(f"{abs(_restock_delta)} units {_dir} — {_oname}", icon="📦")
                                    # Auto-log COGS in Financials when buying stock
                                    if _restock_delta > 0:
                                        _unit_price = float(_pr.get("price", 0) or 0)
                                        _cogs_amt   = _unit_price * int(_restock_delta)
                                        import datetime as _dt
                                        add_financial_entry(
                                            str(_dt.date.today()),
                                            "Cost of Goods (COGS)",
                                            f"Inventory purchase: {_oname} × {int(_restock_delta)} units @ ${_unit_price:.2f}",
                                            _cogs_amt,
                                            f"SKU: {_osku}",
                                            cfg,
                                        )
                                        _fetch_financials_cached.clear()
                                    _clear_data_caches()
                                    time.sleep(0.5)
                                    st.rerun()
                                else:
                                    st.error(f"Failed to update some databases: {_msg}")
                st.divider()

    # ── DOCUMENTATION ────────────────────────────
    with tab_inv_docs:
        st.subheader("Inventory System Documentation")
        st.markdown("""
### How Inventory Works in MERIT

MERIT tracks two numbers per product:

| Field | Meaning |
|---|---|
| **Original Stock** | Running lifetime total of all units you have ever purchased |
| **Current Stock** | Units available right now — decreases automatically as orders are sent |

---

### Original Stock Tab — Restocking

Use the **Original Stock** tab whenever you purchase new inventory from the VEI Wholesale Marketplace.

- Enter a **positive number** to add units (e.g. received 50 new T-shirts → enter +50)
- Enter a **negative number** to subtract units (e.g. damaged goods, returns → enter −5)
- Clicking **Apply** updates **both** Original Stock and Current Stock by that same amount

> This is the primary way to record inventory purchases. MERIT does not connect to the Wholesale Marketplace automatically.

---

### Adjust Stock Tab — Manual Corrections

Use **Adjust Stock** for one-off corrections to Current Stock **only** (does not change Original Stock):

- Fix a counting error
- Write off damaged or lost units that you already received
- Manual reconciliation after a physical stock count

---

### Current Stock Changes Automatically

Every time you send order confirmation emails from the **Mass Email** page, MERIT deducts the ordered quantities from Current Stock. You do not need to manually update anything after sending emails.

---

### Status Labels

| Status | Condition |
|---|---|
| **In stock** | More than 10 units available |
| **Low stock** | 1–10 units available |
| **Out of stock** | 0 units |
| **Backordered** | Negative (oversold) |

---

### Negative Stock and Email Sending

MERIT enforces a **pre-send stock check** when sending order emails:

- If any product in the send queue already has `stock_left ≤ 0`, the entire send session is **blocked**
- You must either adjust stock upward in **Original Stock** or **Adjust Stock**, or remove those orders from the queue
- Products that fall below zero after a send session are marked **Backordered** and blocked from the next session

This prevents overselling and keeps physical inventory in sync with MERIT.

---

### Financials Page

Revenue tracking, the ledger, and order history have moved to the dedicated **Financials** page in the sidebar.

---

### Data Storage

- **SQLite (Local):** Primary local database, always active
- **Supabase (Cloud):** All changes are synced in real-time when connected — recommended for persistence across deployments
        """)

    # ── RESET INVENTORY ──────────────────────────
    with tab_inv_reset:
        st.subheader("Reset Inventory")
        st.warning(
            "**This is a destructive action.** "
            "Resetting inventory wipes **all stock levels** across every database — "
            "SQLite, Turso, and Supabase. Product records (names, prices, descriptions) "
            "are kept. Only stock quantities are cleared."
        )

        _ri_mode = st.radio(
            "What do you want to reset?",
            ["Zero out all stock (set every product to 0 units)", "Delete all inventory rows entirely"],
            key="ri_mode",
        )
        _ri_zero = _ri_mode.startswith("Zero")

        st.divider()
        st.markdown("**Type** `RESET` **below to confirm, then click the button.**")
        _ri_confirm = st.text_input("Confirmation", placeholder="RESET", key="ri_confirm_text", label_visibility="collapsed")

        _ri_cols = st.columns([1, 3])
        with _ri_cols[0]:
            _ri_go = st.button(
                "Reset Inventory" if _ri_zero else "Delete All Inventory Rows",
                type="primary",
                use_container_width=True,
                key="btn_ri_go",
                disabled=(_ri_confirm.strip() != "RESET"),
            )

        if _ri_go and _ri_confirm.strip() == "RESET":
            _ri_results = []

            # ── SQLite ──────────────────────────────────────────────────
            try:
                _ri_conn = _get_sqlite_conn()
                if _ri_zero:
                    _ri_conn.execute(
                        "UPDATE inventory SET stock_left=0, original_stock=0, status='Out of stock'"
                    )
                else:
                    _ri_conn.execute("DELETE FROM inventory")
                _ri_conn.commit()
                _ri_conn.close()
                _ri_results.append("SQLite")
            except Exception as _rie:
                _ri_results.append(f"SQLite failed: {_rie}")

            # ── Turso ───────────────────────────────────────────────────
            if _has_trs_inv:
                try:
                    _ri_turl = _turso_http_url(cfg.get("turso_url", "").strip())
                    _ri_ttok = cfg.get("turso_auth_token", "").strip()
                    if _ri_zero:
                        _turso_pipeline(_ri_turl, _ri_ttok, [(
                            "UPDATE inventory SET stock_left=0, original_stock=0, status='Out of stock'",
                            (),
                        )])
                    else:
                        _turso_pipeline(_ri_turl, _ri_ttok, [
                            ("DELETE FROM inventory", ()),
                        ])
                    _ri_results.append("Turso")
                except Exception as _rie2:
                    _ri_results.append(f"Turso failed: {_rie2}")

            # ── Supabase ────────────────────────────────────────────────
            _ri_sb = _get_supabase_conn(cfg)
            if _ri_sb is not None:
                try:
                    with _ri_sb:
                        with _ri_sb.cursor() as _ri_cur:
                            if _ri_zero:
                                _ri_cur.execute(
                                    "UPDATE inventory SET stock_left=0, original_stock=0, status='Out of stock'"
                                )
                            else:
                                _ri_cur.execute("DELETE FROM inventory")
                    _ri_sb.close()
                    _ri_results.append("Supabase")
                except Exception as _rie3:
                    _ri_results.append(f"Supabase failed: {_rie3}")

            # ── result ──────────────────────────────────────────────────
            _ri_ok = any("failed" not in r for r in _ri_results)
            _ri_label = "zeroed" if _ri_zero else "deleted"
            if _ri_ok:
                st.toast(f"Inventory {_ri_label}.", icon=None)
                st.success(f"Inventory {_ri_label} · {' + '.join(_ri_results)}")
            else:
                st.toast("Reset failed.", icon=None)
                st.error(f"Reset failed: {' · '.join(_ri_results)}")

            _clear_data_caches()
            st.session_state.pop("_inv_cache", None)
            if _ri_ok:
                import time as _t; _t.sleep(0.4)
                st.rerun()

# ═════════════════════════════════════════════
# FINANCIALS PAGE
# ═════════════════════════════════════════════

elif page == "Financials":
    cfg = st.session_state.cfg

    st.title("Financials")
    st.caption("Revenue and expense tracking. Inventory purchases auto-log as COGS.")

    # ── Load data ─────────────────────────────────────────────────
    _fin_logs   = load_outbound_logs(cfg)
    _fin_ledger = get_financials_from_db(cfg)

    # Parse outbound log revenue
    _fin_df   = _fin_logs.copy()
    _ts_col   = "timestamp" if "timestamp" in _fin_df.columns else ("created_at" if "created_at" in _fin_df.columns else None)
    _cost_col = "total_cost" if "total_cost" in _fin_df.columns else None
    _order_revenue = 0.0
    _order_count   = 0
    if _ts_col and _cost_col and not _fin_df.empty:
        _fin_df["_date"] = pd.to_datetime(_fin_df[_ts_col], errors="coerce")
        _fin_df["_cost"] = pd.to_numeric(_fin_df[_cost_col], errors="coerce").fillna(0)
        _fin_df = _fin_df.dropna(subset=["_date"])
        _order_revenue = float(_fin_df["_cost"].sum())
        _order_count   = len(_fin_df)

    # Load inventory for Revenue by Product
    if "_inv_cache" not in st.session_state:
        with st.spinner("Loading inventory…"):
            st.session_state["_inv_cache"] = load_inventory_preferring_cloud(cfg)
    _fin_inv_df = st.session_state["_inv_cache"]

    # Parse ledger amounts
    _rev_cats = {"Revenue"}
    _exp_cats = {"Expense", "Cost of Goods (COGS)", "Marketing", "Payroll", "Operations", "Other"}
    _led_revenue = 0.0
    _led_expense = 0.0
    if not _fin_ledger.empty and "amount" in _fin_ledger.columns:
        _fin_ledger["_amount"] = pd.to_numeric(_fin_ledger["amount"], errors="coerce").fillna(0)
        _led_revenue = float(_fin_ledger[_fin_ledger["category"].isin(_rev_cats)]["_amount"].sum())
        _led_expense = float(_fin_ledger[_fin_ledger["category"].isin(_exp_cats)]["_amount"].sum())

    _total_revenue_all = _order_revenue + _led_revenue
    _net_income        = _total_revenue_all - _led_expense

    # ── Radio mode ────────────────────────────────────────────────
    _fin_mode = st.radio(
        "Financial View",
        ["Overview", "Add Entry", "Ledger", "Order Revenue", "Revenue by Product"],
        horizontal=True,
        label_visibility="collapsed",
        key="fin_mode_radio",
    )

    # ════ OVERVIEW ═══════════════════════════════════════════════
    if _fin_mode == "Overview":
        _fma, _fmb, _fmc, _fmd = st.columns(4)
        _fma.metric("Total Revenue",   f"${_total_revenue_all:,.2f}")
        _fmb.metric("Order Revenue",   f"${_order_revenue:,.2f}")
        _fmc.metric("Ledger Revenue",  f"${_led_revenue:,.2f}")
        _fmd.metric("Total Expenses",  f"${_led_expense:,.2f}")

        _fme, _fmf, _fmg, _fmh = st.columns(4)
        _fme.metric("Net Income",      f"${_net_income:,.2f}", delta="profit" if _net_income >= 0 else "loss")
        _fmf.metric("Total Orders",    f"{_order_count:,}")
        _avg_ord = _order_revenue / _order_count if _order_count else 0
        _fmg.metric("Avg Order Value", f"${_avg_ord:,.2f}")
        _ledger_entries = len(_fin_ledger) if not _fin_ledger.empty else 0
        _fmh.metric("Ledger Entries",  f"{_ledger_entries:,}")

        if not _fin_df.empty and _ts_col and _cost_col:
            st.divider()
            st.subheader("Monthly Order Revenue")
            _date_col = _fin_df["_date"]
            if _date_col.dt.tz is not None:
                _date_col = _date_col.dt.tz_convert(None)
            _monthly_chart = _fin_df.groupby(_date_col.dt.to_period("M"))["_cost"].sum().reset_index()
            _monthly_chart.columns = ["Month", "Revenue"]
            _monthly_chart["Month"] = _monthly_chart["Month"].astype(str)
            st.bar_chart(_monthly_chart.set_index("Month")["Revenue"], color="#16a34a")

        if not _fin_ledger.empty:
            st.divider()
            st.subheader("Expenses by Category")
            _exp_totals = _fin_ledger[_fin_ledger["category"].isin(_exp_cats)].groupby("category")["_amount"].sum().reset_index()
            _exp_totals.columns = ["Category", "Amount ($)"]
            _exp_totals = _exp_totals.sort_values("Amount ($)", ascending=False)
            if not _exp_totals.empty:
                st.bar_chart(_exp_totals.set_index("Category")["Amount ($)"], color="#ef4444")

    # ════ ADD ENTRY ══════════════════════════════════════════════
    elif _fin_mode == "Add Entry":
        st.subheader("Add Financial Entry")
        st.caption("Inventory purchases are logged automatically — use this for other income and expenses.")
        _ae1, _ae2 = st.columns(2)
        with _ae1:
            _ae_date = st.date_input("Date", value="today", key="fin_ae_date")
            _ae_cat  = st.selectbox("Category", _FIN_CATEGORIES, key="fin_ae_cat")
        with _ae2:
            _ae_amt  = st.number_input("Amount ($)", min_value=0.0, step=0.01, format="%.2f", key="fin_ae_amt")
            _ae_desc = st.text_input("Description", placeholder="e.g. Office supplies", key="fin_ae_desc")
        _ae_notes = st.text_area("Notes (optional)", height=80, key="fin_ae_notes")

        if st.button("Add Entry", type="primary", key="btn_fin_add"):
            if not _ae_desc.strip():
                st.error("Description is required.")
            elif _ae_amt <= 0:
                st.error("Amount must be greater than 0.")
            else:
                _aok, _amsg = add_financial_entry(
                    str(_ae_date), _ae_cat, _ae_desc.strip(), float(_ae_amt), _ae_notes.strip(), cfg
                )
                if _aok:
                    st.toast(f"Entry added — {_ae_cat}: ${_ae_amt:,.2f}", icon=None)
                    st.success(f"Entry added — {_ae_cat}: ${_ae_amt:,.2f} ({_ae_desc.strip()})")
                    _fetch_financials_cached.clear()
                    st.rerun()
                else:
                    st.error(f"Failed: {_amsg}")

    # ════ LEDGER ═════════════════════════════════════════════════
    elif _fin_mode == "Ledger":
        st.subheader("Financial Ledger")
        st.caption("All entries — manually added and auto-logged from inventory purchases.")

        if _fin_ledger.empty:
            st.info("No entries yet. Add entries manually or purchase inventory to auto-log COGS.")
        else:
            _lf_cats = ["All"] + _FIN_CATEGORIES
            _lf_cat  = st.selectbox("Filter by Category", _lf_cats, key="fin_lf_cat")
            _led_view = _fin_ledger.copy()
            if _lf_cat != "All":
                _led_view = _led_view[_led_view["category"] == _lf_cat]

            _disp_cols = ["id","entry_date","category","description","amount","notes"]
            _disp_cols = [c for c in _disp_cols if c in _led_view.columns]
            _disp_led  = _led_view[_disp_cols].copy()
            _disp_led["amount"] = pd.to_numeric(_disp_led["amount"], errors="coerce").round(2)
            _disp_led = _disp_led.rename(columns={
                "id":"ID","entry_date":"Date","category":"Category",
                "description":"Description","amount":"Amount ($)","notes":"Notes"
            })
            st.dataframe(_disp_led, use_container_width=True, hide_index=True,
                column_config={
                    "Amount ($)": st.column_config.NumberColumn(format="$%.2f"),
                    "Date":       st.column_config.TextColumn(),
                })
            _csv_bytes = _disp_led.to_csv(index=False).encode()
            st.download_button("Download CSV", data=_csv_bytes, file_name="merit_ledger.csv", mime="text/csv", key="fin_dl_csv")

            st.divider()
            st.subheader("Edit / Delete Entry")
            _all_ids = list(_fin_ledger["id"].astype(int))
            _sel_id  = st.selectbox(
                "Select entry", _all_ids,
                format_func=lambda i: f"#{i} — {_fin_ledger[_fin_ledger['id'].astype(int)==i]['description'].values[0] if len(_fin_ledger[_fin_ledger['id'].astype(int)==i]) else i}",
                key="fin_sel_id"
            )
            _sel_row = _fin_ledger[_fin_ledger["id"].astype(int) == int(_sel_id)]
            if not _sel_row.empty:
                _sr = _sel_row.iloc[0]
                _ed1, _ed2 = st.columns(2)
                with _ed1:
                    _ed_date = st.date_input(
                        "Date",
                        value=pd.to_datetime(str(_sr.get("entry_date",""))).date() if _sr.get("entry_date") else None,
                        key="fin_ed_date"
                    )
                    _ed_cat = st.selectbox(
                        "Category", _FIN_CATEGORIES,
                        index=_FIN_CATEGORIES.index(str(_sr.get("category","Expense"))) if str(_sr.get("category","Expense")) in _FIN_CATEGORIES else 0,
                        key="fin_ed_cat"
                    )
                with _ed2:
                    _ed_amt  = st.number_input("Amount ($)", value=float(_sr.get("amount",0) or 0), min_value=0.0, step=0.01, format="%.2f", key="fin_ed_amt")
                    _ed_desc = st.text_input("Description", value=str(_sr.get("description","")), key="fin_ed_desc")
                _ed_notes = st.text_area("Notes", value=str(_sr.get("notes","")), height=70, key="fin_ed_notes")

                _edc1, _edc2 = st.columns(2)
                with _edc1:
                    if st.button("Save Changes", type="primary", width='stretch', key="btn_fin_save"):
                        _uok, _umsg = update_financial_entry(
                            int(_sel_id), str(_ed_date), _ed_cat, _ed_desc.strip(), float(_ed_amt), _ed_notes.strip(), cfg
                        )
                        if _uok:
                            st.toast("Entry updated.", icon=None)
                            st.success("Entry updated.")
                            _fetch_financials_cached.clear()
                            st.rerun()
                        else:
                            st.toast("Failed to update entry.", icon=None)
                            st.error(f"Failed: {_umsg}")
                with _edc2:
                    if st.button("Delete Entry", type="secondary", width='stretch', key="btn_fin_del"):
                        _dok, _dmsg = delete_financial_entry(int(_sel_id), cfg)
                        if _dok:
                            st.toast("Entry deleted.")
                            _fetch_financials_cached.clear()
                            st.rerun()
                        else:
                            st.error(f"Failed: {_dmsg}")

    # ════ ORDER REVENUE ══════════════════════════════════════════
    elif _fin_mode == "Order Revenue":
        st.subheader("Order Revenue — Outbound Email Log")
        st.caption("Revenue automatically tracked from every order confirmation email sent.")
        if _fin_df.empty:
            st.info("No orders sent yet. Revenue is captured automatically when emails are sent from Mass Email.")
        else:
            _fin_has_sub  = "subtotal"  in _fin_df.columns
            _fin_has_tax  = "tax"       in _fin_df.columns
            _fin_has_ship = "shipping"  in _fin_df.columns
            _total_sub    = pd.to_numeric(_fin_df.get("subtotal",  0), errors="coerce").fillna(0).sum() if _fin_has_sub  else 0
            _total_tax    = pd.to_numeric(_fin_df.get("tax",       0), errors="coerce").fillna(0).sum() if _fin_has_tax  else 0
            _total_ship   = pd.to_numeric(_fin_df.get("shipping",  0), errors="coerce").fillna(0).sum() if _fin_has_ship else 0

            _oa, _ob, _oc, _od = st.columns(4)
            _oa.metric("Total",    f"${_order_revenue:,.2f}")
            _ob.metric("Subtotal", f"${_total_sub:,.2f}")
            _oc.metric("Tax",      f"${_total_tax:,.2f}")
            _od.metric("Shipping", f"${_total_ship:,.2f}")

            st.divider()
            _log_disp = _fin_df.copy()
            _log_rename = {
                "recipient_name": "Name", "recipient_email": "Email",
                "order_number": "Order #", "products_list": "Products",
                "subtotal": "Sub ($)", "tax": "Tax ($)", "shipping": "Ship ($)",
                "total_cost": "Total ($)", "timestamp": "Sent At", "created_at": "Sent At"
            }
            _log_disp = _log_disp.rename(columns={k: v for k, v in _log_rename.items() if k in _log_disp.columns})
            _log_cols = ["Sent At","Name","Email","Order #","Products","Sub ($)","Tax ($)","Ship ($)","Total ($)"]
            _log_disp = _log_disp[[c for c in _log_cols if c in _log_disp.columns]]
            st.dataframe(
                _log_disp, use_container_width=True, hide_index=True,
                column_config={
                    "Total ($)": st.column_config.NumberColumn(format="$%.2f"),
                    "Sub ($)":   st.column_config.NumberColumn(format="$%.2f"),
                    "Tax ($)":   st.column_config.NumberColumn(format="$%.2f"),
                    "Ship ($)":  st.column_config.NumberColumn(format="$%.2f"),
                    "Sent At":   st.column_config.DatetimeColumn(format="MMM DD, YYYY, HH:mm"),
                    "Products":  st.column_config.TextColumn(width="large"),
                }
            )
            _ord_csv = _log_disp.to_csv(index=False).encode()
            st.download_button("Download Order Log CSV", data=_ord_csv, file_name="merit_orders.csv", mime="text/csv", key="fin_dl_ord")

    # ════ REVENUE BY PRODUCT ═════════════════════════════════════
    elif _fin_mode == "Revenue by Product":
        st.subheader("Revenue by Product")
        st.caption("Calculated from price × quantity across all sent order emails.")
        _price_lookup: dict = {}
        if not _fin_inv_df.empty and "item_name" in _fin_inv_df.columns and "price" in _fin_inv_df.columns:
            for _, _plr in _fin_inv_df.iterrows():
                _price_lookup[str(_plr["item_name"]).lower().strip()] = float(_plr.get("price", 0) or 0)
        _prod_revenue: dict[str, float] = {}
        _prod_units:   dict[str, int]   = {}
        _prod_orders:  dict[str, int]   = {}
        _pl_col = "products_list" if "products_list" in _fin_df.columns else None
        if _pl_col and not _fin_df.empty:
            for _, _frow in _fin_df.iterrows():
                for _pentry in [p.strip() for p in str(_frow.get(_pl_col,"")).split(",") if p.strip()]:
                    _pname, _pqty = _parse_product_qty(_pentry)
                    _pkey   = _pname.lower().strip()
                    _pprice = _price_lookup.get(_pkey, 0.0)
                    if not _pprice:
                        for _lk, _lv in _price_lookup.items():
                            if _pkey in _lk or _lk in _pkey:
                                _pprice = _lv; break
                    _prod_revenue[_pname] = _prod_revenue.get(_pname, 0.0) + _pprice * _pqty
                    _prod_units[_pname]   = _prod_units.get(_pname, 0) + _pqty
                    _prod_orders[_pname]  = _prod_orders.get(_pname, 0) + 1
        if _prod_revenue:
            _pp_df = pd.DataFrame([
                {"Product": p, "Units Sold": _prod_units.get(p,0), "Orders": _prod_orders.get(p,0), "Revenue ($)": round(_prod_revenue.get(p,0.0),2)}
                for p in sorted(_prod_revenue, key=_prod_revenue.get, reverse=True)
            ])
            st.bar_chart(_pp_df.set_index("Product")["Revenue ($)"], color="#f59e0b")
            st.dataframe(_pp_df, use_container_width=True, hide_index=True,
                column_config={"Revenue ($)": st.column_config.NumberColumn(format="$%.2f")})
            _pp_csv = _pp_df.to_csv(index=False).encode()
            st.download_button("Download CSV", data=_pp_csv, file_name="merit_revenue_by_product.csv", mime="text/csv", key="fin_dl_pp")
        else:
            st.info("Product revenue will appear once orders are sent from the Mass Email page.")

    st.divider()
    if st.button("Refresh", key="btn_fin_refresh", help="Reload all financial data"):
        _clear_data_caches()
        _fetch_financials_cached.clear()
        _fetch_budgets_cached.clear()
        st.rerun()

# ═════════════════════════════════════════════
# SETTINGS PAGE
# ═════════════════════════════════════════════

elif page == "Settings":
    st.title("Settings")
    st.caption("Changes are saved automatically when you leave a field.")

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
        "inp_sb_anon":          "supabase_anon_key",
        "inp_turso_url":        "turso_url",
        "inp_turso_token":      "turso_auth_token",
    }

    for _ss_k, _cfg_k in _SETTINGS_KEY_MAP.items():
        _val = cfg.get(_cfg_k, "")
        if not st.session_state.get(_ss_k) and _val:
            st.session_state[_ss_k] = _val

    # Banner when all fields are loaded from Streamlit Secrets
    _stg_secrets_live = False
    try:
        _stg_secrets_live = hasattr(st, "secrets") and "merit" in st.secrets
    except Exception:
        pass
    if _stg_secrets_live:
        st.info("Settings auto-loaded from your Streamlit Secrets. Any changes you save here will take effect immediately and will be reflected in the Secrets tab for your next TOML update.")

    def _auto_save_settings():
        _new = {**st.session_state.cfg}
        for _ss_k, _cfg_k in _SETTINGS_KEY_MAP.items():
            _new[_cfg_k] = st.session_state.get(_ss_k, "")
        _new["smtp_password"] = re.sub(r"\s+", "", _new.get("smtp_password", ""))
        try:
            save_config(_new)
            st.session_state.cfg = _new
        except Exception as _e:
            st.error(f"Auto-save failed: {_e}")

    def _on_sb_change():
        _auto_save_settings()
        st.session_state.pop("_sb_test_result", None)
        st.session_state["_sb_test_pending"] = True

    def _on_smtp_change():
        _auto_save_settings()
        st.session_state.pop("_smtp_test_result", None)
        st.session_state["_smtp_test_pending"] = True

    def _on_fi_change():
        _auto_save_settings()
        st.session_state.pop("_fi_test_result", None)
        st.session_state["_fi_test_pending"] = True

    def _on_ih_change():
        _auto_save_settings()
        st.session_state.pop("_ih_test_result", None)
        st.session_state["_ih_test_pending"] = True

    def _on_turso_change():
        _auto_save_settings()
        st.session_state.pop("_turso_test_result", None)
        st.session_state["_turso_test_pending"] = True

    _s_tab_db, _s_tab_email, _s_tab_img, _s_tab_team, _s_tab_secrets = st.tabs(
        ["Database", "Email", "Image Hosting", "Team", "Secrets"]
    )

    # ════════════════ DATABASE TAB ════════════════════════════════════
    with _s_tab_db:

        # ── Status banner ────────────────────────────────────────────
        _db_turso_live = _has_turso(cfg)
        _db_sb_live    = _has_supabase(cfg)
        _dbs_active    = [n for n, v in [("Turso", _db_turso_live), ("Supabase", _db_sb_live)] if v]
        if _dbs_active:
            st.success(f"Connected: {' + '.join(_dbs_active)}")
        else:
            st.warning("No cloud database connected. Set up Turso or Supabase below.")

        st.divider()

        # ════ TURSO (primary) ════════════════════════════════════════
        st.subheader("Turso")
        st.caption("Recommended — distributed SQLite. No extra packages needed.")

        _tc1, _tc2 = st.columns([3, 2])
        with _tc1:
            inp_turso_url = st.text_input(
                "Database URL",
                placeholder="libsql://[org-name]-[username].turso.io",
                help="Turso Dashboard → your database → Connect section → libsql:// URL",
                key="inp_turso_url",
                on_change=_on_turso_change,
            )
        with _tc2:
            inp_turso_token = st.text_input(
                "Auth Token",
                type="password",
                placeholder="eyJ...",
                help="Turso Dashboard → your database → Connect tab → Auth Tokens → Generate Token (NOT Platform API Tokens)",
                key="inp_turso_token",
                on_change=_on_turso_change,
            )

        _turso_url_val  = inp_turso_url.strip()
        _turso_tok_val  = inp_turso_token.strip()
        _turso_cfg_ready = bool(_turso_url_val and _turso_tok_val)

        if st.session_state.pop("_turso_test_pending", False) and _turso_cfg_ready:
            with st.spinner("Testing Turso connection..."):
                try:
                    _test_cfg = {**cfg, "turso_url": _turso_url_val, "turso_auth_token": _turso_tok_val}
                    _turso_execute(_test_cfg, "SELECT 1")
                    st.session_state["_turso_test_result"] = ("ok", "Connected to Turso successfully.")
                except Exception as _te:
                    st.session_state["_turso_test_result"] = ("err", str(_te)[:300])

        if "_turso_test_result" in st.session_state:
            _tr = st.session_state["_turso_test_result"]
            if _tr[0] == "ok":
                st.toast("Turso connected!", icon=None)
                st.success(_tr[1])
            else:
                st.toast("Turso connection failed.", icon=None)
                st.error(f"Turso connection failed: {_tr[1]}")

        if st.button("Setup Turso Tables", type="primary", width="stretch",
                     key="btn_setup_turso", disabled=not _turso_cfg_ready):
            with st.spinner("Creating tables in Turso..."):
                try:
                    _turso_setup_cfg = {**cfg, "turso_url": _turso_url_val, "turso_auth_token": _turso_tok_val}
                    _ok_t, _fail_t = 0, []
                    for _stmt in [s.strip() for s in TURSO_SETUP_SQL.split(";") if s.strip()]:
                        try:
                            _turso_execute(_turso_setup_cfg, _stmt)
                            _ok_t += 1
                        except Exception as _se:
                            _fail_t.append(f"{_stmt[:60]}… → {str(_se)[:100]}")
                    if not _fail_t:
                        st.toast("Turso tables ready!")
                        st.success("Tables created successfully.")
                        with st.spinner("Syncing users and roles to Turso..."):
                            _u_cnt, _r_cnt, _sync_errs = sync_local_to_turso(_turso_setup_cfg)
                        if _sync_errs:
                            st.warning(f"Synced {_u_cnt} users, {_r_cnt} roles — some errors: {'; '.join(_sync_errs[:3])}")
                        elif _u_cnt or _r_cnt:
                            st.info(f"Synced {_u_cnt} user(s) and {_r_cnt} role(s) to Turso.")
                    else:
                        st.warning(f"{_ok_t} OK, {len(_fail_t)} failed:")
                        for _f in _fail_t:
                            st.caption(_f)
                except Exception as exc:
                    st.error(f"Setup failed: {exc}")

        st.divider()

        # ════ SUPABASE (secondary) ═══════════════════════════════════
        st.subheader("Supabase")
        st.caption("PostgreSQL cloud database — optional, works alongside Turso.")

        inp_sb_conn = st.text_input(
            "Connection String",
            placeholder="postgresql://postgres.xxxxxxxxxxxx:[YOUR-PASSWORD]@aws-0-us-east-1.pooler.supabase.com:5432/postgres",
            help="Supabase Dashboard → Connect → Session Pooler tab → Connection string",
            key="inp_sb_conn",
            on_change=_on_sb_change,
        )
        _sc1, _sc2 = st.columns(2)
        with _sc1:
            inp_sb_pass = st.text_input(
                "Database Password",
                type="password",
                placeholder="Your Supabase database password",
                help="The password you set when creating your Supabase project",
                key="inp_sb_pass",
                on_change=_on_sb_change,
            )
        with _sc2:
            inp_sb_anon = st.text_input(
                "Anon / Public Key",
                type="password",
                placeholder="eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
                help="Supabase Dashboard → gear icon → API → Legacy API keys → anon / public",
                key="inp_sb_anon",
                on_change=_auto_save_settings,
            )

        _sb_conn_val = inp_sb_conn.strip()
        _sb_pass_val = inp_sb_pass.strip()
        _sb_effective = ""
        if _sb_conn_val:
            if "[YOUR-PASSWORD]" in _sb_conn_val and _sb_pass_val:
                from urllib.parse import quote as _url_quote_sb
                _sb_effective = _sb_conn_val.replace("[YOUR-PASSWORD]", _url_quote_sb(_sb_pass_val, safe=""))
            elif "[YOUR-PASSWORD]" not in _sb_conn_val:
                _sb_effective = _sb_conn_val

        if _sb_conn_val and "[YOUR-PASSWORD]" in _sb_conn_val and not _sb_pass_val:
            st.warning("Enter your Database Password to complete the connection string.")

        if st.session_state.pop("_sb_test_pending", False) and _sb_effective:
            with st.spinner("Testing Supabase connection..."):
                try:
                    _tc = _psycopg2_connect(_sb_effective)
                    _tc.close()
                    st.session_state["_sb_test_result"] = ("ok", "Connected to Supabase successfully.")
                except Exception as _tce:
                    st.session_state["_sb_test_result"] = ("err", str(_tce))

        if "_sb_test_result" in st.session_state:
            _sbr = st.session_state["_sb_test_result"]
            if _sbr[0] == "ok":
                st.toast("Supabase connected!", icon=None)
                st.success(_sbr[1])
            else:
                st.toast("Supabase connection failed.", icon=None)
                st.error(f"Supabase connection failed: {_sbr[1]}")

        if st.button("Setup Supabase Tables", type="primary", width="stretch",
                     key="btn_setup_sb", disabled=not _sb_effective):
            with st.spinner("Creating tables in Supabase..."):
                try:
                    _conn = _psycopg2_connect(_sb_effective, connect_timeout=15)
                    _cur = _conn.cursor()
                    _statements = _split_sql_statements(SETUP_SQL)
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
                        st.toast("Supabase tables ready!")
                        st.success("Tables created successfully.")
                        with st.spinner("Syncing users and roles to Supabase..."):
                            _u_cnt, _r_cnt, _sync_errs = sync_local_to_supabase(cfg)
                        if _sync_errs:
                            st.warning(f"Synced {_u_cnt} users, {_r_cnt} roles — some errors: {'; '.join(_sync_errs[:3])}")
                        elif _u_cnt or _r_cnt:
                            st.info(f"Synced {_u_cnt} user(s) and {_r_cnt} role(s) to Supabase.")
                    else:
                        st.warning(f"{_ok} OK, {len(_fail)} failed:")
                        for _f in _fail:
                            st.caption(_f)
                except Exception as exc:
                    st.error(f"Setup failed: {exc}")

    # ════════════════ EMAIL TAB ═══════════════════════════════════════
    with _s_tab_email:
        st.subheader("Gmail SMTP")
        _e1, _e2 = st.columns(2)
        with _e1:
            inp_smtp_email = st.text_input(
                "Gmail Address",
                placeholder="yourfirm@gmail.com",
                help="The Gmail account emails are sent from",
                key="_cfg_smtp_email",
                on_change=_on_smtp_change,
            )
        with _e2:
            inp_smtp_pass = st.text_input(
                "App Password",
                type="password",
                placeholder="xxxx xxxx xxxx xxxx",
                help="Google Account → Security → App Passwords → create one named MERIT",
                key="_cfg_smtp_pass",
                on_change=_on_smtp_change,
            )

        if st.session_state.pop("_smtp_test_pending", False) and inp_smtp_email.strip() and inp_smtp_pass.strip():
            with st.spinner("Testing Gmail connection..."):
                try:
                    _srv = smtplib.SMTP("smtp.gmail.com", 587, timeout=10)
                    _srv.starttls()
                    _srv.login(inp_smtp_email.strip(), re.sub(r"\s+", "", inp_smtp_pass.strip()))
                    _srv.quit()
                    st.session_state["_smtp_test_result"] = ("ok", "Gmail connected successfully.")
                except Exception as _smtpe:
                    _smtp_em = str(_smtpe)
                    if len(_smtp_em) > 300 or "DeltaGenerator" in _smtp_em:
                        _smtp_em = "Login failed — check your Gmail address and App Password."
                    st.session_state["_smtp_test_result"] = ("err", _smtp_em[:300])

        if "_smtp_test_result" in st.session_state:
            _smr = st.session_state["_smtp_test_result"]
            if _smr[0] == "ok":
                st.success(_smr[1])
            else:
                st.error(f"Connection failed: {_smr[1]}")

        st.divider()
        st.subheader("Sender Identity")
        _si1, _si2 = st.columns(2)
        with _si1:
            inp_from_name = st.text_input(
                "From Name",
                placeholder="Your VEI Firm Name",
                help="Shown as the sender name in the recipient's inbox",
                key="_cfg_from_name",
                on_change=_auto_save_settings,
            )
        with _si2:
            inp_subject = st.text_input(
                "Default Subject Line",
                placeholder="Your order is here",
                help="Use {order_number} to insert the order number",
                key="_cfg_subject",
                on_change=_auto_save_settings,
            )

    # ════════════════ IMAGE HOSTING TAB ══════════════════════════════
    with _s_tab_img:
        st.subheader("Image Hosting")
        st.caption("Product images are uploaded automatically when you add a product. Set up one service.")

        _img_tab_fi, _img_tab_ih = st.tabs(["Freeimage.host", "Imghippo"])

        with _img_tab_fi:
            inp_freeimage_key = st.text_input(
                "Freeimage.host API Key",
                type="password",
                placeholder="your_api_key_here",
                help="freeimage.host → Menu → API → copy your key",
                key="inp_freeimage_key",
                on_change=_on_fi_change,
            )
            if st.session_state.pop("_fi_test_pending", False) and inp_freeimage_key.strip():
                with st.spinner("Testing Freeimage.host..."):
                    try:
                        import requests as _rq
                        import base64 as _b64
                        # 1×1 white PNG — valid enough for an API key check
                        _fi_raw = _b64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAAC0lEQVQI12NgAAIABQAABjE+ibYAAAAASUVORK5CYII=")
                        _fi_resp = _rq.post(
                            "https://freeimage.host/api/1/upload",
                            data={"key": inp_freeimage_key.strip(), "action": "upload", "format": "json"},
                            files={"source": ("test.png", io.BytesIO(_fi_raw), "image/png")},
                            timeout=20,
                        )
                        _fi_body = _fi_resp.json() if _fi_resp.content else {}
                        if _fi_resp.status_code == 200 and str(_fi_body.get("status_code")) == "200":
                            st.session_state["_fi_test_result"] = ("ok", "Key verified.")
                        else:
                            st.session_state["_fi_test_result"] = ("err", str(_fi_body.get("status_txt") or f"HTTP {_fi_resp.status_code}")[:120])
                    except Exception as _fie:
                        _fi_em = str(_fie)
                        st.session_state["_fi_test_result"] = ("err", "Connection failed — check your internet." if len(_fi_em) > 200 else _fi_em[:200])
            if "_fi_test_result" in st.session_state:
                _fir = st.session_state["_fi_test_result"]
                if _fir[0] == "ok":
                    st.success("Freeimage.host is working.")
                else:
                    st.error(f"Test failed: {_fir[1]}")

        with _img_tab_ih:
            inp_imgbb_key = st.text_input(
                "Imghippo API Key",
                type="password",
                placeholder="your_imghippo_api_key",
                help="imghippo.com → Settings → API Keys → Generate",
                key="inp_imgbb_key",
                on_change=_on_ih_change,
            )
            if st.session_state.pop("_ih_test_pending", False) and inp_imgbb_key.strip():
                with st.spinner("Testing Imghippo..."):
                    try:
                        import requests as _rq
                        import base64 as _b64
                        _ih_raw = _b64.b64decode("/9j/4AAQSkZJRgABAQEASABIAAD/2wBDAAgGBgcGBQgHBwcJCQgKDBQNDAsLDBkSEw8UHRofHh0aHBwgJC4nICIsIxwcKDcpLDAxNDQ0Hyc5PTgyPC4zNDL/2wBDAQkJCQwLDBgNDRgyIRwhMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjL/wAARCAABAAEDASIAAhEBAxEB/8QAFAABAAAAAAAAAAAAAAAAAAAACf/EABQQAQAAAAAAAAAAAAAAAAAAAAD/xAAUAQEAAAAAAAAAAAAAAAAAAAAA/8QAFBEBAAAAAAAAAAAAAAAAAAAAAP/aAAwDAQACEQMRAD8AJQAB/9k=")
                        _ih_resp = _rq.post(
                            "https://api.imghippo.com/v1/upload",
                            data={"api_key": inp_imgbb_key.strip(), "title": "api_test"},
                            files={"file": ("test.jpg", io.BytesIO(_ih_raw), "image/jpeg")},
                            timeout=20,
                        )
                        _ih_body = _ih_resp.json() if _ih_resp.content else {}
                        if _ih_resp.status_code == 200 and _ih_body.get("success"):
                            st.session_state["_ih_test_result"] = ("ok", "Key verified.")
                        elif _ih_resp.status_code == 401:
                            st.session_state["_ih_test_result"] = ("err", "Invalid API key.")
                        elif _ih_resp.status_code == 429:
                            st.session_state["_ih_test_result"] = ("warn", "Rate limited — wait a minute and retry.")
                        else:
                            st.session_state["_ih_test_result"] = ("err", f"HTTP {_ih_resp.status_code}")
                    except Exception as _ihe:
                        _ih_em = str(_ihe)
                        st.session_state["_ih_test_result"] = ("err", "Connection failed." if len(_ih_em) > 200 else _ih_em[:200])
            if "_ih_test_result" in st.session_state:
                _ihr = st.session_state["_ih_test_result"]
                if _ihr[0] == "ok":
                    st.success("Imghippo is working.")
                elif _ihr[0] == "warn":
                    st.warning(_ihr[1])
                else:
                    st.error(f"Test failed: {_ihr[1]}")

    # ════════════════ TEAM TAB ════════════════════════════════════════
    with _s_tab_team:
        st.subheader("Team Access")
        st.caption("Manage roles and the users assigned to them. Admins can change any user's role.")

        _ta_roles_df  = get_roles_from_db(cfg)
        _ta_users     = get_users_from_db(cfg)
        _ta_role_names = list(_ta_roles_df["role_name"].values) if not _ta_roles_df.empty else ["admin", "staff", "viewer"]
        _ta_cur_user  = st.session_state.get("auth_user", {}) or {}
        _ta_is_admin  = (_ta_cur_user.get("role", "admin") == "admin") or (not _ta_cur_user)
        _ta_builtin   = {"admin", "staff", "viewer"}

        _ta_tab_roles, _ta_tab_users = st.tabs(["Roles", "Users"])

        # ════════════════ ROLES TAB ═══════════════════════════════════
        with _ta_tab_roles:
            st.write("Each role defines which pages its members can access.")

            # Create new role
            with st.expander("Create New Role", expanded=False):
                _rm_name = st.text_input("Role Name", placeholder="e.g. manager", key="rm_role_name")
                st.write("Pages this role can access:")
                _rm_page_cols = st.columns(len(_ALL_PAGES))
                _rm_checked = []
                for _rp_i, _rp_name in enumerate(_ALL_PAGES):
                    with _rm_page_cols[_rp_i]:
                        if st.checkbox(_rp_name, key=f"rm_page_{_rp_i}"):
                            _rm_checked.append(_rp_name)
                if st.button("Save Role", type="primary", key="btn_rm_create", disabled=not _ta_is_admin):
                    if not _rm_name.strip():
                        st.error("Role name is required.")
                    elif not _rm_checked:
                        st.error("Select at least one page.")
                    else:
                        _rm_ok, _rm_msg = create_role_all_dbs(_rm_name.strip().lower(), _rm_checked, cfg)
                        if _rm_ok:
                            st.toast(f"Role {_rm_name.strip()} saved.", icon=None)
                            st.success(f"Role **{_rm_name.strip()}** saved with: {', '.join(_rm_checked)}")
                            _fetch_roles_cached.clear()
                            st.rerun()
                        else:
                            st.error(f"Failed: {_rm_msg}")
                if not _ta_is_admin:
                    st.caption("Only admins can create roles.")

            # All roles list
            if not _ta_roles_df.empty:
                for _, _rr in _ta_roles_df.iterrows():
                    _rr_name  = str(_rr.get("role_name", ""))
                    _rr_pages = [p.strip() for p in str(_rr.get("pages", "")).split(",") if p.strip()]
                    _rr_is_builtin = _rr_name in _ta_builtin
                    with st.container(border=True):
                        _rrc1, _rrc2, _rrc3 = st.columns([5, 1, 1])
                        with _rrc1:
                            _rr_label = f"**{_rr_name.capitalize()}**"
                            if _rr_is_builtin:
                                _rr_label += " — *built-in*"
                            st.markdown(_rr_label)
                            # Page permission badges
                            _badge_html = " ".join(
                                f'<span style="background:#1f7aec;color:#fff;padding:2px 8px;border-radius:10px;font-size:0.75rem;margin-right:4px">{p}</span>'
                                if p in _rr_pages else
                                f'<span style="background:#333;color:#666;padding:2px 8px;border-radius:10px;font-size:0.75rem;margin-right:4px;text-decoration:line-through">{p}</span>'
                                for p in _ALL_PAGES
                            )
                            st.markdown(_badge_html, unsafe_allow_html=True)
                        with _rrc2:
                            if _ta_is_admin:
                                _rr_edit_key = f"_editing_role_{_rr_name}"
                                _rr_editing = st.session_state.get(_rr_edit_key, False)
                                if st.button("Edit" if not _rr_editing else "Cancel", key=f"rm_edit_{_rr_name}", width='stretch'):
                                    st.session_state[_rr_edit_key] = not _rr_editing
                                    st.rerun()
                        with _rrc3:
                            if not _rr_is_builtin and _ta_is_admin:
                                if st.button("Delete", key=f"rm_del_{_rr_name}", width='stretch'):
                                    _rrd_ok, _rrd_msg = delete_role_all_dbs(_rr_name, cfg)
                                    if _rrd_ok:
                                        st.toast(f"Role '{_rr_name}' deleted.")
                                        _fetch_roles_cached.clear()
                                        st.rerun()
                                    else:
                                        st.error(f"Failed: {_rrd_msg}")
                    if _ta_is_admin and st.session_state.get(f"_editing_role_{_rr_name}", False):
                        with st.container(border=True):
                            st.markdown(f"**Edit pages for: {_rr_name}**")
                            _edit_pages = []
                            _ep_cols = st.columns(len(_ALL_PAGES))
                            for _epi, _ep in enumerate(_ALL_PAGES):
                                with _ep_cols[_epi]:
                                    if st.checkbox(_ep, value=(_ep in _rr_pages), key=f"ep_{_rr_name}_{_ep}"):
                                        _edit_pages.append(_ep)
                            _ep_save, _ep_cancel = st.columns(2)
                            with _ep_save:
                                if st.button("Save", key=f"ep_save_{_rr_name}", width='stretch'):
                                    _ep_ok, _ep_msg = create_role_all_dbs(_rr_name, _edit_pages, cfg)
                                    if _ep_ok:
                                        st.toast(f"Role '{_rr_name}' updated.")
                                        _fetch_roles_cached.clear()
                                        st.session_state[f"_editing_role_{_rr_name}"] = False
                                        st.rerun()
                                    else:
                                        st.error(f"Failed: {_ep_msg}")
                            with _ep_cancel:
                                if st.button("Cancel", key=f"ep_cancel_{_rr_name}", width='stretch'):
                                    st.session_state[f"_editing_role_{_rr_name}"] = False
                                    st.rerun()

        # ════════════════ USERS TAB ═══════════════════════════════════
        with _ta_tab_users:

            _ta_secrets_active = False
            try:
                _ta_secrets_active = hasattr(st, "secrets") and "merit" in st.secrets
            except Exception:
                pass

            if not _ta_secrets_active:
                st.warning(
                    "**Setup not complete.** User management is available after you finish **Get Started** "
                    "and save your Secrets TOML — the app reboots once secrets are saved, then you can "
                    "create and invite team members here."
                )
            else:
                st.caption(
                    "Create team members and send them a shareable invite link. "
                    "They set their own password when they open the link — no admin needs to share a password."
                )

                # ── Invite new user ───────────────────────────────────
                with st.expander("Invite New Team Member", expanded=_ta_users.empty):
                    _um_c1, _um_c2 = st.columns(2)
                    with _um_c1:
                        _um_name  = st.text_input("Full Name", placeholder="Jane Smith", key="um_name")
                        _um_email = st.text_input("Email", placeholder="jane@yourfirm.org", key="um_email")
                    with _um_c2:
                        _um_role  = st.selectbox(
                            "Role", _ta_role_names,
                            format_func=lambda r: _ROLE_LABELS.get(r, r.capitalize()),
                            key="um_role"
                        )
                        _um_invite_mode = st.radio(
                            "Password method",
                            ["Send invite link (recommended)", "Set password now"],
                            key="um_invite_mode",
                            horizontal=True,
                        )
                        if _um_invite_mode == "Set password now":
                            _um_pass  = st.text_input("Password", type="password", key="um_pass")
                            _um_pass2 = st.text_input("Confirm Password", type="password", key="um_pass2")

                    if st.button("Create User", type="primary", key="btn_um_create", disabled=not _ta_is_admin):
                        if not _um_name.strip():
                            st.error("Full name is required.")
                        elif not _um_email.strip() or "@" not in _um_email:
                            st.error("A valid email is required.")
                        elif _um_invite_mode == "Set password now":
                            _um_pass_val  = st.session_state.get("um_pass", "")
                            _um_pass2_val = st.session_state.get("um_pass2", "")
                            if len(_um_pass_val) < 6:
                                st.error("Password must be at least 6 characters.")
                            elif _um_pass_val != _um_pass2_val:
                                st.error("Passwords do not match.")
                            else:
                                _um_ok, _um_msg = create_user_all_dbs(_um_email.strip(), _um_name.strip(), _um_role, _um_pass_val, cfg)
                                if _um_ok:
                                    st.toast(f"User {_um_name.strip()} created.", icon=None)
                                    st.success(f"User **{_um_name.strip()}** created with role **{_um_role}**.")
                                    _fetch_users_cached.clear()
                                    st.rerun()
                                else:
                                    st.error(f"Failed: {_um_msg}")
                        else:
                            # Invite link flow
                            _inv_ok, _inv_msg, _inv_tok = create_user_with_invite(
                                _um_email.strip(), _um_name.strip(), _um_role, cfg
                            )
                            if _inv_ok:
                                _base_url = st.session_state.get("_app_base_url", "")
                                _invite_url = f"{_base_url}?invite={_inv_tok}" if _base_url else f"?invite={_inv_tok}"
                                st.toast(f"Invite link created for {_um_name.strip()}.", icon=None)
                                st.success(f"User **{_um_name.strip()}** created. Share the invite link below:")
                                st.code(_invite_url, language="text")
                                st.caption("The link is single-use. Once they set their password, it expires automatically.")
                                _fetch_users_cached.clear()
                            else:
                                st.error(f"Failed: {_inv_msg}")
                    if not _ta_is_admin:
                        st.caption("Only admins can create users.")

                # ── Capture app base URL for invite links ─────────────
                try:
                    _hdrs = getattr(st, "context", None)
                    _hdrs = getattr(_hdrs, "headers", None) if _hdrs else None
                    if _hdrs:
                        _detected_base = _hdrs.get("origin", "") or _hdrs.get("referer", "").rstrip("/")
                        if _detected_base and "localhost" not in _detected_base and "127.0.0.1" not in _detected_base:
                            st.session_state["_app_base_url"] = _detected_base
                except Exception:
                    pass

                # ── All users — role management + invite link generation ──
                if not _ta_users.empty:
                    st.divider()
                    for _, _ur in _ta_users.iterrows():
                        _ur_email_val = str(_ur.get("email", ""))
                        _ur_role_val  = str(_ur.get("role", "viewer"))
                        _ur_pages     = get_pages_for_role(_ur_role_val, cfg)
                        _is_self      = (_ta_cur_user.get("email", "").lower() == _ur_email_val.lower())

                        with st.container(border=True):
                            _uc1, _uc2, _uc3, _uc4 = st.columns([4, 3, 1.2, 1])
                            with _uc1:
                                st.markdown(f"**{_ur.get('full_name', '')}**  \n{_ur_email_val}")
                            with _uc2:
                                if _ta_is_admin and not _is_self:
                                    _new_role_sel = st.selectbox(
                                        "Role",
                                        _ta_role_names,
                                        index=_ta_role_names.index(_ur_role_val) if _ur_role_val in _ta_role_names else 0,
                                        format_func=lambda r: _ROLE_LABELS.get(r, r.capitalize()),
                                        key=f"ur_role_sel_{_ur_email_val}",
                                        label_visibility="collapsed",
                                    )
                                    if _new_role_sel != _ur_role_val:
                                        if st.button("Save", key=f"ur_role_save_{_ur_email_val}", width='stretch'):
                                            _uro_ok, _uro_msg = update_user_role_all_dbs(_ur_email_val, _new_role_sel, cfg)
                                            if _uro_ok:
                                                st.toast(f"Role updated to {_new_role_sel}.")
                                                _fetch_users_cached.clear()
                                                st.rerun()
                                            else:
                                                st.error(f"Failed: {_uro_msg}")
                                    _preview_pages = get_pages_for_role(_new_role_sel, cfg)
                                    _badge2 = " ".join(
                                        f'<span style="background:#1f7aec;color:#fff;padding:1px 7px;border-radius:8px;font-size:0.72rem;margin-right:3px">{p}</span>'
                                        for p in _preview_pages
                                    ) or "<span style='color:#888;font-size:0.72rem'>No pages</span>"
                                    st.markdown(_badge2, unsafe_allow_html=True)
                                else:
                                    st.caption(_ROLE_LABELS.get(_ur_role_val, _ur_role_val.capitalize()))
                                    _badge3 = " ".join(
                                        f'<span style="background:#1f7aec;color:#fff;padding:1px 7px;border-radius:8px;font-size:0.72rem;margin-right:3px">{p}</span>'
                                        for p in _ur_pages
                                    ) or "<span style='color:#888;font-size:0.72rem'>No pages</span>"
                                    st.markdown(_badge3, unsafe_allow_html=True)
                            with _uc3:
                                if _ta_is_admin and not _is_self:
                                    if st.button("Invite Link", key=f"um_invite_{_ur_email_val}", width='stretch',
                                                 help="Generate a new shareable link for this user to set or reset their password"):
                                        _ri_ok, _ri_tok = generate_new_invite_token(_ur_email_val, cfg)
                                        if _ri_ok:
                                            _base_url2 = st.session_state.get("_app_base_url", "")
                                            _ri_url = f"{_base_url2}?invite={_ri_tok}" if _base_url2 else f"?invite={_ri_tok}"
                                            st.session_state[f"_invite_link_{_ur_email_val}"] = _ri_url
                                            _fetch_users_cached.clear()
                                        else:
                                            st.error("Failed to generate invite link.")
                                _shown_link = st.session_state.get(f"_invite_link_{_ur_email_val}", "")
                                if _shown_link:
                                    st.code(_shown_link, language="text")
                            with _uc4:
                                if st.button("Remove", key=f"um_del_{_ur_email_val}",
                                             disabled=_is_self or not _ta_is_admin,
                                             help="Cannot remove your own account" if _is_self else
                                                  "Only admins can remove users" if not _ta_is_admin else None,
                                             use_container_width=True):
                                    _del_ok, _del_msg = delete_user_all_dbs(_ur_email_val, cfg)
                                    if _del_ok:
                                        st.toast("User removed.")
                                        _fetch_users_cached.clear()
                                        st.rerun()
                                    else:
                                        st.error(f"Failed: {_del_msg}")
                else:
                    st.info("No users yet. Use the **Invite New Team Member** form above.")

    # ════════════════ SECRETS TAB ════════════════════════════════════
    with _s_tab_secrets:
        st.subheader("Secrets TOML")
        st.caption(
            "Streamlit Cloud wipes local files on every restart. Pasting this block into "
            "Streamlit Secrets makes your credentials permanent."
        )

        _gs_secrets_active = False
        try:
            _gs_secrets_active = hasattr(st, "secrets") and "merit" in st.secrets
        except Exception:
            pass

        if _gs_secrets_active:
            st.success("Secrets are active — credentials survive app restarts.")
        else:
            st.info(
                "After filling in your credentials on the other tabs, copy the block below, "
                "then go to **Manage app → ⋮ → Settings → Secrets**, paste it, and click Save."
            )

        _toml_cfg = st.session_state.cfg
        def _toml_escape(v: str) -> str:
            return v.replace("\\", "\\\\").replace('"', '\\"')

        _toml_lines = ["[merit]"]
        for _tk in _SECRETS_CREDENTIAL_KEYS:
            _tv = _toml_cfg.get(_tk, "")
            _toml_lines.append(f'{_tk} = "{_toml_escape(str(_tv))}"')
        st.code("\n".join(_toml_lines), language="toml")


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
        "Every product you add or edit in MERIT automatically updates in your cloud database. "
        "This page gives you everything you need to connect that database to a website built on "
        "Bolt.new, Lovable, Cursor, v0, or any other platform."
    )

    _api_has_sb  = _has_supabase(cfg)
    _api_has_trs = _has_turso(cfg)

    if not (_api_has_sb or _api_has_trs):
        st.warning(
            "**No cloud database connected.** "
            "Go to **Get Started → Step 2** or **Settings → Database** to connect "
            "Supabase or Turso, then click **Setup Tables**."
        )
        st.stop()

    # ── Key values banner ────────────────────────────────────────────
    _api_anon_key = cfg.get("supabase_anon_key", "").strip()
    _kv1, _kv2 = st.columns(2)
    if _api_has_sb:
        with _kv1:
            st.markdown("**Your Supabase URL** — paste this into your website builder")
            st.code(_sb_url_ph, language="text")
        with _kv2:
            st.markdown("**Your Supabase Anon Key**")
            if _api_anon_key:
                st.code(_api_anon_key, language="text")
                st.caption("Safe to use in public website code — never use your DB password in a website.")
            else:
                st.info("Anon key not saved yet. Go to **Settings → Supabase Anon Key** and paste the `eyJ…` key from Supabase → Project Settings → API.")
    elif _api_has_trs:
        _trs_http = _turso_http_url(cfg.get("turso_url", "").strip())
        with _kv1:
            st.markdown("**Your Turso Database URL**")
            st.code(_trs_http, language="text")
        with _kv2:
            st.markdown("**Turso API** — your website calls this HTTP endpoint directly")
            st.info(
                "Turso uses a REST-style HTTP API (`/v2/pipeline`). "
                "See the **AI Prompts** tab below for ready-to-use code that queries your Turso database from a website."
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

        # Turso-only banner — different API than Supabase
        if _api_has_trs and not _api_has_sb:
            _trs_url_ai = _turso_http_url(cfg.get("turso_url", "").strip())
            st.info(
                "You are using **Turso** as your database. "
                "Unlike Supabase, Turso does not have a public anon-key REST API — "
                "your website must call a **serverless function** (Vercel/Netlify/Cloudflare Worker) "
                "that proxies queries to Turso. The prompt below includes ready-to-use code for this setup."
            )
            _turso_master_prompt = f"""\
=== MERIT DATABASE SCHEMA (Turso / SQLite) ===

Turso database HTTP URL : {_trs_url_ai}

IMPORTANT: Do NOT expose your Turso auth token in public website code.
Instead, create a serverless function (Vercel API route, Netlify Function, or Cloudflare Worker)
that holds the token server-side and proxies SELECT queries to Turso.

--- TABLE: inventory  (PRIMARY table for storefront — has live stock levels) ---
Column          Type      Notes
-----------     --------  -----------------------------------------
sku             TEXT      unique product code — use as the URL slug
item_name       TEXT      product display name
category        TEXT      product category — use for filter buttons
price           REAL      retail price in USD
stock_left      INTEGER   units currently in stock
status          TEXT      'In stock' | 'Low stock' | 'Out of stock'
image_url       TEXT      one or more images, comma-separated — ALWAYS take only the FIRST
original_stock  INTEGER   initial stock quantity
created_at      TEXT      ISO timestamp

CRITICAL STOREFRONT RULES:
  1. Only show products WHERE stock_left > 0
  2. Use the status field for badge text

--- TABLE: products  (catalog with descriptions and buy buttons) ---
Column          Type      Notes
-----------     --------  -----------------------------------------
sku             TEXT      matches inventory.sku
name            TEXT      product display name
category        TEXT
price           REAL
description     TEXT      full product description
buy_button_url  TEXT      direct VEI purchase link — use as Buy Now href; hide if empty
image_url       TEXT      comma-separated, take first URL only
active          INTEGER   1 = In Store (show), 0 = Out of Store (hide)
created_at      TEXT

CRITICAL: Always filter WHERE active = 1. Never show Out-of-Store products.

=== SERVERLESS PROXY (required — never expose Turso token to browser) ===

// Example: Vercel API route  /api/products.js
export default async function handler(req, res) {{
  const sql = "SELECT i.sku, i.item_name, i.category, i.price, i.stock_left, i.status, i.image_url, p.description, p.buy_button_url FROM inventory i LEFT JOIN products p ON p.sku = i.sku WHERE i.stock_left > 0 AND (p.active IS NULL OR p.active = 1) ORDER BY i.item_name";
  const resp = await fetch("{_trs_url_ai}/v2/pipeline", {{
    method: "POST",
    headers: {{ "Authorization": "Bearer YOUR_TURSO_AUTH_TOKEN", "Content-Type": "application/json" }},
    body: JSON.stringify({{ requests: [{{ type: "execute", stmt: {{ sql }} }}, {{ type: "close" }}] }})
  }});
  const data = await resp.json();
  const cols = data.results[0].response.result.cols.map(c => c.name);
  const rows = data.results[0].response.result.rows.map(r =>
    Object.fromEntries(cols.map((c, i) => [c, r[i].value]))
  );
  res.json(rows);
}}

// In your React component:
const [products, setProducts] = useState([]);
useEffect(() => {{
  fetch('/api/products').then(r => r.json()).then(setProducts);
}}, []);

=== IMAGE RULES ===
const getImage = (url) => url?.split(',')[0]?.trim() || null;
// Show grey placeholder if getImage returns null or 'N/A'

=== WHAT TO BUILD ===
Build a modern VEI firm product storefront. Fetch data through the /api/products serverless proxy above.

1. Product grid — responsive (1 col mobile, 2 col tablet, 3 col desktop)
   - Each card: image (first URL), item_name, price, status badge, Buy Now button
   - Buy Now = <a href={{buy_button_url}}>Buy Now</a>; hide if empty
   - Badges: In stock → green, Low stock → amber, Out of stock → red

2. Category filter pills at top — "All" default, client-side filter

3. Product detail page /products/:sku — fetch single product, show description, large image, Buy Now

4. No Realtime subscription needed — poll /api/products every 60s if you want live updates
"""
            st.markdown("**Paste this into any AI builder (Cursor, v0, Lovable, ChatGPT):**")
            st.code(_turso_master_prompt, language="text")
            st.stop()

        _api_anon_ai_saved = cfg.get("supabase_anon_key", "").strip()
        if _api_anon_ai_saved:
            st.caption("Your Supabase anon key is saved — it is pre-filled into every prompt below. Just copy and paste.")
        else:
            st.caption(
                "Save your Supabase anon key in **Settings → Supabase Anon Key** and it will be pre-filled into all prompts below. "
                "Otherwise replace `YOUR_SUPABASE_ANON_KEY` manually."
            )

        _ai_master, _ai_bolt, _ai_lovable, _ai_cursor = st.tabs(
            ["Master Context Block", "Bolt.new", "Lovable", "Cursor / v0 / General"]
        )

        # ── shared schema text used across all prompts ──────────────────
        _api_anon_ai = cfg.get("supabase_anon_key", "").strip() or "YOUR_SUPABASE_ANON_KEY"
        _schema_block = f"""\
=== MERIT DATABASE SCHEMA (Supabase / PostgreSQL) ===

Supabase project URL : {_sb_url_ai}
Supabase anon key    : {_api_anon_ai}   ← paste this into your website code

--- TABLE: inventory  (PRIMARY table for storefront — has live stock levels) ---
Column          Type              Notes
-----------     ----------------  -----------------------------------------
id              BIGSERIAL PK      auto-increment primary key, do not use in app logic
sku             TEXT NOT NULL     unique product code — use as the URL slug (e.g. /products/SKU-001)
item_name       TEXT NOT NULL     product display name — show this as the product title
category        TEXT              product category — use for filter buttons
price           NUMERIC(10,2)     retail price in USD
stock_left      INTEGER           units currently in stock — deducted automatically when MERIT sends order emails
status          TEXT              stock status label: 'In stock' | 'Low stock' | 'Out of stock' | 'Backordered'
image_url       TEXT              one or more images — may be a single HTTPS URL or multiple URLs separated by commas
                                  ALWAYS take only the FIRST URL if there are multiple: image_url.split(',')[0]
original_stock  INTEGER           initial stock set when the product was first added
created_at      TIMESTAMPTZ       timestamp when the product was created

CRITICAL STOREFRONT RULES:
  1. ONLY show products where stock_left > 0 (out-of-stock products must be hidden or greyed out)
  2. Use the status field for badge text but stock_left > 0 is the definitive in-stock check
  3. The inventory table is updated in real time — subscribe to Supabase Realtime for live updates

--- TABLE: products  (clean catalog — use when you need description and buy button) ---
Column          Type              Notes
-----------     ----------------  -----------------------------------------
id              BIGSERIAL PK
sku             TEXT NOT NULL     matches inventory.sku — use to JOIN or cross-reference
name            TEXT NOT NULL     product display name (same as inventory.item_name)
category        TEXT              product category
price           NUMERIC(10,2)     retail price in USD
description     TEXT              full product description — show on product detail page (may be empty string)
buy_button_url  TEXT              direct VEI buy link — e.g. https://portal.veinternational.org/buybuttons/us019814/btn/product-name/
                                  Use as the href for the "Buy Now" button. If empty string → hide or disable the button.
image_url       TEXT              same format as inventory.image_url — take first URL if comma-separated
active          BOOLEAN           store status: true = In Store (show to customers), false = Out of Store (hide from customers)
                                  ALWAYS filter: active = true when fetching for the storefront
created_at      TIMESTAMPTZ

CRITICAL: Always filter products WHERE active = true. Out of Store products must never appear on the storefront.

BUY BUTTON RULE:
  buy_button_url is a direct VEI purchase link managed by VEI International.
  Render it as: <a href="{{product.buy_button_url}}" target="_blank" rel="noopener">Buy Now</a>
  Do NOT wrap it in your own cart logic — clicking it goes directly to the VEI purchase interface.
  If buy_button_url is an empty string → hide or disable the Buy Now button entirely.

--- TABLE: outbound_logs  (order history — read-only for website display) ---
Column            Type              Notes
-----------       ----------------  -----------------------------------------
id                BIGSERIAL PK
recipient_name    TEXT              customer name
recipient_email   TEXT              customer email
order_number      TEXT              order reference number
products_list     TEXT              comma-separated list of product names ordered
subtotal          NUMERIC(10,2)     order subtotal before tax and shipping
tax               NUMERIC(10,2)     tax amount
shipping          NUMERIC(10,2)     shipping amount
total_cost        NUMERIC(10,2)     final total (subtotal + tax + shipping)
created_at        TIMESTAMPTZ       when the order email was sent

=== IMAGE RULES ===
- image_url stores one OR multiple images separated by commas: "https://url1.com" or "https://url1.com,https://url2.com"
- ALWAYS use only the FIRST image for display: const imgSrc = product.image_url?.split(',')[0]?.trim() || ''
- If the first URL is 'N/A', empty, or null → show a grey placeholder div instead of a broken image
- Never proxy, re-upload, or modify image URLs — they are already hosted on a CDN
- Use onError fallback: <img src={{imgSrc}} onError={{e => e.target.style.display='none'}} />

=== STORE STATUS RULES ===
- inventory table: filter WHERE stock_left > 0 to show only in-stock products
- products table: filter WHERE active = true to show only "In Store" products
- A product can be "In Store" (active=true) but still out of stock (stock_left=0)
  In that case show it with an "Out of stock" badge but hide the buy button

=== RLS (ROW LEVEL SECURITY) ===
These policies allow any visitor with the anon key to read — but not write — your data.
Run this SQL once in Supabase Dashboard → SQL Editor → New Query:

  ALTER TABLE inventory ENABLE ROW LEVEL SECURITY;
  ALTER TABLE products  ENABLE ROW LEVEL SECURITY;
  ALTER TABLE outbound_logs ENABLE ROW LEVEL SECURITY;

  CREATE POLICY "Public read inventory" ON inventory FOR SELECT USING (true);
  CREATE POLICY "Public read products"  ON products  FOR SELECT USING (true);

MERIT writes data using the direct PostgreSQL connection string (server-side, bypasses RLS).
The anon key used by the website is strictly read-only — visitors cannot modify any data.

=== SUPABASE REALTIME (live inventory updates) ===
1. Supabase Dashboard → Database → Replication → toggle ON for: inventory, products
2. In your JS/TS code subscribe to changes so the UI updates automatically when MERIT sends an order email and deducts stock

=== ENV VARIABLES ===
For Bolt.new / Lovable / Vite projects:
  VITE_SUPABASE_URL      = {_sb_url_ai}
  VITE_SUPABASE_ANON_KEY = {_api_anon_ai}

For Next.js projects:
  NEXT_PUBLIC_SUPABASE_URL      = {_sb_url_ai}
  NEXT_PUBLIC_SUPABASE_ANON_KEY = {_api_anon_ai}"""

        # ── Fetch real product data from Supabase for AI prompts ─────────
        _products_block = ""
        try:
            _ai_conn_str = _get_effective_supabase_conn_str(cfg)
            if _ai_conn_str.startswith("postgresql://"):
                _ai_conn = _psycopg2_connect(_ai_conn_str)
                try:
                    _ai_cur = _ai_conn.cursor()
                    _ai_cur.execute("""
                        SELECT
                            p.sku,
                            p.name,
                            p.category,
                            p.price,
                            p.description,
                            p.buy_button_url,
                            p.active,
                            p.image_url   AS prod_image,
                            i.stock_left,
                            i.status      AS stock_status,
                            i.image_url   AS inv_image
                        FROM products p
                        LEFT JOIN inventory i ON i.sku = p.sku
                        ORDER BY p.name
                    """)
                    _ai_cols = [d[0] for d in _ai_cur.description]
                    _ai_rows = [dict(zip(_ai_cols, row)) for row in _ai_cur.fetchall()]
                    _ai_cur.close()
                    if _ai_rows:
                        _prod_lines = []
                        for _r in _ai_rows:
                            _desc   = str(_r.get("description") or "").strip()
                            _buy    = str(_r.get("buy_button_url") or "").strip()
                            _active = "In Store" if _r.get("active") else "Out of Store"
                            _img    = str(_r.get("inv_image") or _r.get("prod_image") or "").strip()
                            _img_first = _img.split(",")[0].strip() if _img and "," in _img else _img
                            _stock  = _r.get("stock_left")
                            _status = str(_r.get("stock_status") or ("In stock" if _stock and _stock > 0 else "Out of stock"))
                            _line = (
                                f"  SKU: {_r['sku']}\n"
                                f"    Name: {_r['name']}\n"
                                f"    Category: {_r.get('category', '') or '(none)'}\n"
                                f"    Price: ${float(_r.get('price') or 0):.2f}\n"
                                f"    Store Status: {_active}\n"
                                f"    Stock Status: {_status} ({_stock if _stock is not None else 'N/A'} units)\n"
                                f"    Description: {_desc if _desc else '(none — do not invent one)'}\n"
                                f"    Buy Button URL: {_buy if _buy else '(none — hide Buy Now button)'}\n"
                                f"    Primary Image URL: {_img_first if _img_first and _img_first != 'N/A' else '(none)'}"
                            )
                            _prod_lines.append(_line)
                        _products_block = (
                            "\n\n=== YOUR ACTUAL PRODUCTS (live from Supabase) ===\n"
                            "Use these exact values when building the storefront. "
                            "Do NOT invent descriptions, buy links, or image URLs.\n"
                            "Each entry below is one product with all fields needed for a product card and detail page.\n\n"
                            + "\n\n".join(_prod_lines)
                            + "\n\n--- END OF PRODUCT LIST ---\n"
                            "RULES:\n"
                            "- Buy Button URL is the direct VEI purchase link — use as href for Buy Now button\n"
                            "- If Buy Button URL is '(none)', hide or disable the Buy Now button\n"
                            "- Primary Image URL: use as <img src>, show grey placeholder if '(none)'\n"
                            "- image_url may contain comma-separated URLs — always use only the first one\n"
                            "- Store Status 'Out of Store' = do NOT show this product to customers\n"
                            "- Stock Status shows current availability — use for badge text\n"
                        )
                finally:
                    _ai_conn.close()
        except Exception:
            pass  # If fetch fails, prompts still work — AI will query Supabase itself

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
Build a modern, professional product storefront for a VEI (Virtual Enterprise International) firm.
Read data from the Supabase database described above. Do NOT create or modify any database tables.

CRITICAL RULES (apply these before writing any code):
- image_url may contain multiple comma-separated URLs — ALWAYS use only the FIRST: url?.split(',')[0]?.trim()
- Show grey placeholder when image is missing, 'N/A', or empty
- inventory table: only show WHERE stock_left > 0
- products table: only show WHERE active = true (In Store)
- buy_button_url is a direct VEI purchase link — use as Buy Now href, never add custom cart logic around it

Requirements:
1. Product grid — responsive layout (1 col mobile, 2 col tablet, 3 col desktop)
   - Fetch from inventory WHERE stock_left > 0, ORDER BY item_name
   - Each card: product image (first URL only), item_name, price, stock status badge, Buy Now button
   - Buy Now button = <a href={{buy_button_url}} target="_blank">Buy Now</a>; hide if buy_button_url is empty
   - Status badges: "In stock" green, "Low stock" amber, "Out of stock" red

2. Category filter — horizontal pill buttons at the top, "All" selected by default
   - Fetch distinct category values from the inventory table (WHERE stock_left > 0)
   - Client-side filtering — clicking a pill instantly filters the product grid

3. Product detail page — route: /products/[sku]
   - Fetch from inventory (stock) and products (description, buy_button_url, active) by sku
   - Large image left (first URL), details right
   - Show: item_name, price, category, description, status badge
   - Buy Now button → href=buy_button_url; disable and grey out when stock_left = 0 or Out of Store

4. Cart — localStorage only, no login required
   - Slide-in drawer on right, triggered by header cart icon (shows item count badge)
   - Quantity +/-, remove button, item subtotal, grand total
   - Checkout modal: Name, Email, Message → confirmation on submit

5. Realtime — subscribe to Supabase Realtime on the inventory table
   - On any change (INSERT/UPDATE/DELETE) → refetch the product list automatically
   - This keeps stock levels live when MERIT processes orders and deducts inventory

6. RLS — run the RLS SQL (in the Schema & Security SQL tab) in Supabase before going live"""
            _master_prompt += _products_block
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
I already have a Supabase database set up and connected. Do NOT create any new tables or modify existing ones.

{_schema_block}

Build a VEI (Virtual Enterprise International) firm product storefront using the exact schema above.

Tech stack: React + Vite + Tailwind CSS + @supabase/supabase-js

IMPORTANT RULES BEFORE YOU START:
- Do not invent column names — use only the exact columns listed in the schema above
- image_url may contain multiple URLs separated by commas — always use only the FIRST one: item.image_url?.split(',')[0]?.trim()
- Only show products from inventory WHERE stock_left > 0
- Only show products from products table WHERE active = true (In Store)
- buy_button_url links directly to the VEI purchase page — do not wrap in custom cart logic

Pages to build:
1. / (Home) — product grid
   - Fetch from inventory WHERE stock_left > 0, ORDER BY item_name ASC
   - Responsive grid: 1 col (mobile) → 2 col (tablet) → 3 col (desktop)
   - Product card:
     • Image: const src = item.image_url?.split(',')[0]?.trim(); show grey placeholder if src is 'N/A' or empty
     • item_name as title, price formatted as $X.XX
     • Status badge: green = "In stock", amber = "Low stock", red = "Out of stock"
     • "Buy Now" button → href=item.buy_button_url, target="_blank"; hide button if buy_button_url is empty
   - Category filter pills at top (fetch distinct category values from inventory, "All" selected by default)
   - Sort toggle: A-Z / Price Low-High / Price High-Low

2. /products/:sku — product detail
   - Fetch from inventory WHERE sku = route param (for stock data)
   - Also fetch from products WHERE sku = route param (for description and buy_button_url)
   - Large image left, details right
   - Show: item_name, price, category, status badge, stock_left count, description
   - "Buy Now" button → href=products.buy_button_url; disable and grey out if stock_left = 0 or buy_button_url is empty
   - Breadcrumb: Home → [category] → [item_name]

3. Cart (slide-in drawer, not a separate page)
   - State in localStorage key "merit_cart"
   - Each item: {{ sku, item_name, price, image_url (first URL only), quantity }}
   - +/- quantity buttons, remove button, item subtotal, grand total
   - Checkout modal: Name, Email, Message fields → confirmation message on submit (no backend needed)

Supabase Realtime:
- Subscribe to postgres_changes on the inventory table
- On any INSERT, UPDATE, or DELETE event → refetch the product list immediately
- This keeps stock levels live as MERIT processes orders

Use the exact env var names: VITE_SUPABASE_URL and VITE_SUPABASE_ANON_KEY"""
            _bolt_prompt += _products_block
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
My tables already exist. Only read from them using SELECT queries via the Supabase JS client.

{_schema_block}

Build a product storefront for my VEI (Virtual Enterprise International) firm.

Design: clean and professional, white background, dark navy (#18181b) header, rounded product cards with subtle shadows, mobile-first responsive layout.

CRITICAL IMAGE RULE:
  image_url may contain multiple comma-separated URLs. Always take only the first:
  const imgSrc = row.image_url?.split(',')[0]?.trim() || ''
  Show a grey placeholder if imgSrc is empty, null, or 'N/A'.

CRITICAL STORE STATUS RULES:
  - inventory table: only show rows WHERE stock_left > 0
  - products table: only show rows WHERE active = true (In Store)
  - Always apply both filters — never show out-of-stock or Out-of-Store products

--- PAGE: / (Product Catalog) ---
- Query: SELECT * FROM inventory WHERE stock_left > 0 ORDER BY item_name ASC
- Responsive product grid (1 col mobile, 2 col tablet, 3 col desktop)
- Each product card:
    • Product image (first URL from image_url, grey placeholder if missing)
    • item_name as card title
    • price formatted as "$X.XX"
    • Status badge: "In stock" → green, "Low stock" → amber, "Out of stock" → red/grey
    • "Buy Now" button → href = buy_button_url from products table (JOIN on sku); hide if buy_button_url is empty
- Horizontal category filter pills at top (distinct inventory.category values, "All" default)
- Client-side search bar filtering item_name in real time

--- PAGE: /product/:sku ---
- Fetch from inventory WHERE sku = URL param (stock data)
- Also fetch from products WHERE sku = URL param (description, buy_button_url, active status)
- Two-column layout: large image left, details panel right
- Show: item_name, price, category, status badge, description
- "Buy Now" button → href = products.buy_button_url, opens in new tab; grey out if stock_left = 0 or buy_button_url empty
- Back link: ← Back to catalog

--- COMPONENT: Cart Drawer ---
- Triggered by cart icon in navbar (shows item count badge)
- Slides in from the right side
- Line items: image thumbnail (first URL), item_name, $price × qty, remove button
- Order total at bottom
- "Request Order" button → modal form (Name, Email, Message) → thank-you message on submit

--- REALTIME ---
Subscribe to Supabase Realtime on the inventory table (postgres_changes, event: '*').
On any change event (INSERT/UPDATE/DELETE) → refetch the catalog immediately.
This ensures stock levels update automatically when MERIT sends order emails.

--- ENV VARS ---
VITE_SUPABASE_URL      = {_sb_url_ai}
VITE_SUPABASE_ANON_KEY = {_api_anon_ai}"""
            _lovable_prompt += _products_block
            st.code(_lovable_prompt, language="text")

        # ── Cursor / v0 / General ───────────────────────────────────────
        with _ai_cursor:
            st.markdown("""
**Works with Cursor, v0.dev, Claude, ChatGPT, or any AI assistant.**
Paste the prompt below into the AI chat after opening your project.
For **v0.dev** just paste it directly into the v0 prompt bar.
            """)
            _cursor_prompt = f"""\
I need to build a product storefront that reads from my existing Supabase database.
Use ONLY the exact column names and table structures listed below. Do not invent new columns or tables.

{_schema_block}

=== IMPLEMENTATION INSTRUCTIONS ===

Step 1 — Supabase client setup
  import {{ createClient }} from '@supabase/supabase-js'
  const supabase = createClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL,   // or import.meta.env.VITE_SUPABASE_URL for Vite
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY
  )

Step 2 — Fetch in-stock, In-Store products (inventory table)
  const {{ data: products }} = await supabase
    .from('inventory')
    .select('sku, item_name, category, price, stock_left, status, image_url')
    .gt('stock_left', 0)       // only in-stock products
    .order('item_name', {{ ascending: true }})

Step 3 — Parse product image (may have multiple comma-separated URLs)
  // ALWAYS use only the first URL:
  const getImage = (url) => {{
    const first = url?.split(',')[0]?.trim() || ''
    return first && first !== 'N/A' ? first : null
  }}
  // In JSX:
  const imgSrc = getImage(product.image_url)
  <img src={{imgSrc || '/placeholder.png'}} alt={{product.item_name}}
       onError={{e => {{ e.target.src = '/placeholder.png' }}}} />

Step 4 — Fetch a single product by SKU (join both tables)
  // inventory row (stock data):
  const {{ data: inv }} = await supabase.from('inventory').select('*').eq('sku', sku).single()
  // products row (description, buy_button_url, active/store status):
  const {{ data: prod }} = await supabase.from('products').select('*').eq('sku', sku).single()

Step 5 — Fetch distinct categories for the filter bar
  const {{ data: cats }} = await supabase.from('inventory').select('category').gt('stock_left', 0)
  const categories = [...new Set(cats?.map(r => r.category).filter(Boolean))]

Step 6 — Buy Now button rules
  // buy_button_url is a direct VEI purchase link — do NOT add custom cart logic
  // Show the button only if buy_button_url is non-empty AND stock_left > 0:
  {{prod?.buy_button_url && inv?.stock_left > 0 && (
    <a href={{prod.buy_button_url}} target="_blank" rel="noopener">Buy Now</a>
  )}}

Step 7 — Store status filter (products table)
  // When reading from the products table, always filter WHERE active = true:
  const {{ data }} = await supabase.from('products').select('*').eq('active', true)

Step 8 — Subscribe to Realtime (inventory updates from MERIT)
  const channel = supabase
    .channel('merit-inventory')
    .on('postgres_changes', {{ event: '*', schema: 'public', table: 'inventory' }},
      () => fetchProducts()   // re-fetch on any stock change
    )
    .subscribe()
  // Cleanup on unmount: supabase.removeChannel(channel)

Step 9 — RLS SQL (run once in Supabase SQL Editor before going live)
  ALTER TABLE inventory ENABLE ROW LEVEL SECURITY;
  ALTER TABLE products  ENABLE ROW LEVEL SECURITY;
  CREATE POLICY "Public read inventory" ON inventory FOR SELECT USING (true);
  CREATE POLICY "Public read products"  ON products  FOR SELECT USING (true);

=== BUILD THE FOLLOWING ===
- Responsive product grid (3 cols desktop, 1 col mobile) from inventory table (stock_left > 0 only)
- Category filter pills using distinct inventory.category values
- Product detail page /products/[sku] — show description from products table, buy_button_url as Buy Now link
- Store status awareness: Out of Store products (active = false) are never shown
- Multiple image support: always extract first URL from comma-separated image_url
- Cart stored in localStorage (sku, item_name, price, first image URL, quantity)
- Checkout modal (Name, Email, Message) with confirmation on submit
- Realtime subscription so the page updates automatically when MERIT sends order emails and deducts stock"""
            _cursor_prompt += _products_block
            st.code(_cursor_prompt, language="text")

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
            "These are the URLs your website calls to read product data. "
            "The AI Prompts tab generates the full code for you, but these endpoints are here to test, debug, or copy into tools like Postman."
        )

        # ── How authentication works ───────────────────────────────────
        _rest_anon = cfg.get("supabase_anon_key", "").strip() or "YOUR_SUPABASE_ANON_KEY"
        with st.expander("How to authenticate — read this first", expanded=True):
            st.markdown(f"""
**Every request needs two headers:**

| Header | Value |
|---|---|
| `apikey` | Your Supabase **anon / public** key |
| `Authorization` | `Bearer {_rest_anon}` |

{"✅ **Your anon key is saved** and pre-filled in all examples below." if _rest_anon != "YOUR_SUPABASE_ANON_KEY" else "**Where to get your anon key:** Supabase Dashboard → gear icon → Project Settings → API → copy **anon / public** key (starts with `eyJ…`). Then save it in **Settings → Supabase Anon Key**."}

The anon key is safe to put in your website. It is read-only when Row Level Security is enabled (the Setup Tables button enables this).
""")
            st.code(
                f"apikey: {_rest_anon}\nAuthorization: Bearer {_rest_anon}",
                language="http",
            )

        st.markdown(f"**Base URL:** `{_api_rest_base}`")
        st.divider()

        st.markdown("#### Products + live stock (`inventory` table)")
        _inv_rows = [
            ("GET", f"{_api_rest_base}/inventory?select=*",                                  "All products (all columns)"),
            ("GET", f"{_api_rest_base}/inventory?select=*&stock_left=gte.1&order=item_name", "In-stock only, A to Z"),
            ("GET", f"{_api_rest_base}/inventory?select=*&category=eq.Apparel",              "Filter by category (replace Apparel)"),
            ("GET", f"{_api_rest_base}/inventory?sku=eq.SKU001&select=*",                    "One product by SKU"),
            ("GET", f"{_api_rest_base}/inventory?select=sku,item_name,price,stock_left",     "Specific columns only"),
            ("GET", f"{_api_rest_base}/inventory?stock_left=gte.1&order=price.asc&select=*", "In-stock, sorted by price (low→high)"),
        ]
        st.dataframe(
            pd.DataFrame(_inv_rows, columns=["Method", "URL", "What it returns"]),
            use_container_width=True, hide_index=True,
        )

        st.markdown("#### Clean catalog (description + buy button) — `products` table")
        _prod_rows = [
            ("GET", f"{_api_rest_base}/products?select=*&active=eq.true",                     "All active (In Store) products"),
            ("GET", f"{_api_rest_base}/products?select=*&active=eq.true&order=name",          "Active, A to Z"),
            ("GET", f"{_api_rest_base}/products?category=eq.Apparel&active=eq.true&select=*", "Filter by category + active"),
            ("GET", f"{_api_rest_base}/products?sku=eq.SKU001&select=*",                      "One product by SKU (description + buy URL)"),
        ]
        st.dataframe(
            pd.DataFrame(_prod_rows, columns=["Method", "URL", "What it returns"]),
            use_container_width=True, hide_index=True,
        )

        st.divider()
        st.markdown("#### Curl examples — test in your terminal")
        st.code(f"""\
# Get all in-stock products
curl "{_api_rest_base}/inventory?select=*&stock_left=gte.1&order=item_name" \\
  -H "apikey: {_rest_anon}" \\
  -H "Authorization: Bearer {_rest_anon}"

# Get one product by SKU
curl "{_api_rest_base}/inventory?sku=eq.SKU001&select=*" \\
  -H "apikey: {_rest_anon}" \\
  -H "Authorization: Bearer {_rest_anon}"

# Get all active products with description and buy button
curl "{_api_rest_base}/products?select=*&active=eq.true&order=name" \\
  -H "apikey: {_rest_anon}" \\
  -H "Authorization: Bearer {_rest_anon}"
""", language="bash")

        st.divider()
        st.markdown("#### PostgREST filter operators (use in URL parameters)")
        _ops = [
            ("eq", "equal to", "category=eq.Apparel"),
            ("neq", "not equal", "status=neq.Out of stock"),
            ("gt / gte", "greater than / or equal", "stock_left=gte.1  ·  price=gt.10"),
            ("lt / lte", "less than / or equal", "price=lte.50"),
            ("like", "pattern match (case-sensitive)", "item_name=like.*Shirt*"),
            ("ilike", "pattern match (case-insensitive)", "item_name=ilike.*shirt*"),
            ("in", "matches any in list", "category=in.(Apparel,Accessories)"),
            ("is", "is null / true / false", "active=is.true"),
            ("order", "sort results", "order=price.asc  ·  order=item_name.desc"),
            ("limit", "max rows returned", "limit=10"),
            ("offset", "skip rows (pagination)", "offset=20&limit=10"),
        ]
        st.dataframe(
            pd.DataFrame(_ops, columns=["Operator", "Meaning", "Example"]),
            use_container_width=True, hide_index=True,
        )

        st.divider()
        st.info(
            "**Tip:** Combine multiple filters with `&`. "
            "Example: in-stock Apparel sorted by price → "
            f"`{_api_rest_base}/inventory?select=*&category=eq.Apparel&stock_left=gte.1&order=price.asc`"
        )

    # ── Code Snippets ─────────────────────────────────────────────────
    with _tab_code:
        st.markdown("### Ready-to-paste code snippets")
        _code_caption_anon = cfg.get("supabase_anon_key", "").strip()
        if _code_caption_anon:
            st.caption("Your Supabase anon key is pre-filled in all snippets below — just copy and paste.")
        else:
            st.caption("Save your anon key in **Settings → Supabase Anon Key** to pre-fill it here. Otherwise replace `YOUR_SUPABASE_ANON_KEY` manually.")

        _ex_js, _ex_ts, _ex_react, _ex_rt = st.tabs(
            ["JavaScript", "TypeScript / Next.js", "React Hook", "Real-time (live updates)"]
        )

        _code_anon = cfg.get("supabase_anon_key", "").strip() or "YOUR_SUPABASE_ANON_KEY"
        with _ex_js:
            st.markdown("Works in any plain HTML/JS project or Bolt.new:")
            st.code(f"""\
// Step 1 — install:  npm install @supabase/supabase-js
import {{ createClient }} from '@supabase/supabase-js'

const supabase = createClient(
  '{_sb_url_ph}',
  '{_code_anon}'
)

// Fetch all in-stock products
async function getProducts() {{
  const {{ data, error }} = await supabase
    .from('inventory')
    .select('*')
    .gt('stock_left', 0)       // only show products that have stock
    .order('item_name', {{ ascending: true }})

  if (error) throw error
  return data  // each item has: sku, item_name, price, image_url, stock_left, category
}}
""", language="javascript")

        with _ex_ts:
            st.markdown("For Next.js or any TypeScript project:")
            st.code("""\
// lib/supabase.ts
import { createClient } from '@supabase/supabase-js'
export const supabase = createClient(
  process.env.NEXT_PUBLIC_SUPABASE_URL!,
  process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!
)
""", language="typescript")

        with _ex_react:
            st.markdown("A React hook that auto-refreshes when MERIT updates a product:")
            st.code("""\
// hooks/useProducts.ts
import { useEffect, useState } from 'react'
import { supabase } from '../lib/supabase'

export function useProducts(category?: string) {
  const [products, setProducts] = useState([])
  const [loading, setLoading]   = useState(true)

  async function fetchProducts() {
    let q = supabase
      .from('inventory')
      .select('*')
      .gt('stock_left', 0)
      .order('item_name')

    if (category) q = q.eq('category', category)

    const { data } = await q
    setProducts(data ?? [])
    setLoading(false)
  }

  useEffect(() => {
    fetchProducts()

    // Subscribe so the page updates automatically when you change products in MERIT
    const channel = supabase
      .channel('merit-live')
      .on('postgres_changes', { event: '*', schema: 'public', table: 'inventory' },
        () => fetchProducts()
      )
      .subscribe()

    return () => { supabase.removeChannel(channel) }
  }, [category])

  return { products, loading }
}
""", language="typescript")

        with _ex_rt:
            st.markdown(
                "To make your site update **live** when you change something in MERIT, "
                "first enable Replication in Supabase Dashboard → Database → Replication → toggle `inventory` ON, "
                "then use this code:"
            )
            st.code(f"""\
import {{ createClient }} from '@supabase/supabase-js'

const supabase = createClient('{_sb_url_ph}', '{_code_anon}')

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
# MASS EMAIL PAGE
# ═════════════════════════════════════════════

elif page == "Mass Email":

    cfg = st.session_state.cfg
    missing_cfg = [k for k in ("from_name", "smtp_email", "smtp_password") if not cfg.get(k)]
    if missing_cfg:
        st.warning("Go to **Settings** and fill in your SMTP credentials before sending.")

    st.title("Mass Email")
    st.caption("Send professional order confirmations or run bulk email campaigns from one place.")

    # Build catalog lookup once — used for image-match warnings and inventory deduction
    _catalog_products = load_products_for_catalog(cfg)
 
    if not _catalog_products:
        st.warning("No products found. Add products in the **Products** page first.")
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

    tab_order, tab_campaign, tab_email_docs = st.tabs(
        ["Order Entry", "Email Campaigns", "Documentation"]
    )

    # ─ Order Entry (Single / Bulk / Excel) ──────────────────
    with tab_order:
        _mode = st.radio("Entry Method", ["Single Order", "Bulk Table", "Excel Import", "Order Template"], horizontal=True, label_visibility="collapsed")
        
        if _mode == "Single Order":
            st.markdown("#### Add one order")
            c1, c2, c3 = st.columns(3)
            with c1:
                s_name  = st.text_input("Name *",    key="s_name",  placeholder="Jane Smith")
                s_email = st.text_input("Email *",   key="s_email", placeholder="jane@example.com")
            with c2:
                s_order = st.text_input("Order # *", key="s_order", placeholder="ORD-1001")
            with c3:
                pass

            s_prods = st.text_area(
                "Products *", key="s_prods", height=80,
                placeholder="Blue T-Shirt\nBlack Jeans",
                help="One product per line, or separate with | or ;",
            )

            st.markdown("**Order Totals**")
            _sc1, _sc2, _sc3, _sc4, _sc5 = st.columns(5)
            with _sc1:
                s_subtotal = st.number_input("Subtotal ($)", key="s_subtotal", min_value=0.0, step=0.01, format="%.2f")
            with _sc2:
                s_discount = st.number_input("Discount ($)", key="s_discount", min_value=0.0, step=0.01, format="%.2f")
            with _sc3:
                s_tax = st.number_input("Tax ($)", key="s_tax", min_value=0.0, step=0.01, format="%.2f")
            with _sc4:
                s_shipping = st.number_input("Shipping ($)", key="s_shipping", min_value=0.0, step=0.01, format="%.2f")
            with _sc5:
                s_cost = st.number_input("Total ($) *", key="s_cost", min_value=0.0, step=0.01, format="%.2f",
                                         help="Leave 0 to auto-calculate: Subtotal − Discount + Tax + Shipping")
            _s_auto = round(s_subtotal - s_discount + s_tax + s_shipping, 2)
            _s_final = s_cost if s_cost > 0 else _s_auto
            if s_subtotal > 0 and s_cost == 0:
                st.caption(f"Auto-calculated total: **${_s_auto:.2f}**")

            if st.button("Add to Queue", key="single_add", type="primary"):
                if s_name and s_email and s_order and s_prods and _s_final > 0:
                    if add_to_queue(s_name, s_email, s_order, s_prods, s_subtotal, s_tax, s_shipping, _s_final, s_discount):
                        st.success(f"Added {s_name} to the queue.")
                        st.rerun()
                else:
                    st.error("All fields marked with * are required and Total must be > $0.")
        elif _mode == "Bulk Table":
            st.markdown("#### Enter multiple orders")
            st.caption("Fill in the table directly, or upload a CSV. Columns: Name, Email, Order #, Products, Subtotal, Discount, Tax, Shipping, Total.")

            _bulk_ord_csv = st.file_uploader("Import Orders from CSV", type=["csv"], key="bulk_orders_csv",
                                              help="CSV must have at least: Name, Email, Order #, Products, Total columns.")
            _BULK_INIT = {
                "Name":     pd.Series([], dtype=str),
                "Email":    pd.Series([], dtype=str),
                "Order #":  pd.Series([], dtype=str),
                "Products": pd.Series([], dtype=str),
                "Subtotal": pd.Series([], dtype=float),
                "Discount": pd.Series([], dtype=float),
                "Tax":      pd.Series([], dtype=float),
                "Shipping": pd.Series([], dtype=float),
                "Total":    pd.Series([], dtype=float),
            }
            _BULK_BASE = pd.DataFrame(_BULK_INIT)
            if _bulk_ord_csv:
                try:
                    _bdf = pd.read_csv(_bulk_ord_csv)
                    _bdf.columns = [c.strip() for c in _bdf.columns]
                    _bc = {}
                    for _col in _bdf.columns:
                        _cl = _col.lower().replace(" ", "_").replace("#", "")
                        if "name" in _cl and "item" not in _cl: _bc[_col] = "Name"
                        elif "email" in _cl: _bc[_col] = "Email"
                        elif "order" in _cl: _bc[_col] = "Order #"
                        elif "product" in _cl or "item" in _cl: _bc[_col] = "Products"
                        elif "subtotal" in _cl or "sub_total" in _cl: _bc[_col] = "Subtotal"
                        elif "discount" in _cl: _bc[_col] = "Discount"
                        elif "tax" in _cl: _bc[_col] = "Tax"
                        elif "ship" in _cl or "freight" in _cl: _bc[_col] = "Shipping"
                        elif "total" in _cl: _bc[_col] = "Total"
                    _bdf = _bdf.rename(columns=_bc)
                    for _fc in ["Subtotal", "Discount", "Tax", "Shipping", "Total"]:
                        if _fc not in _bdf.columns: _bdf[_fc] = 0.0
                        else: _bdf[_fc] = pd.to_numeric(_bdf[_fc], errors="coerce").fillna(0.0)
                    _keep = [c for c in ["Name","Email","Order #","Products","Subtotal","Discount","Tax","Shipping","Total"] if c in _bdf.columns]
                    _BULK_BASE = _bdf[_keep].copy()
                    st.success(f"CSV loaded — {len(_BULK_BASE)} row(s) ready to review and add.")
                except Exception as _be:
                    st.error(f"CSV read error: {_be}")

            edited = st.data_editor(_BULK_BASE, num_rows="dynamic", use_container_width=True, key="bulk_editor")
            if st.button("Add All to Queue", type="primary", key="bulk_add"):
                added = 0
                for _, row in edited.iterrows():
                    nm   = str(row.get("Name", "") or "").strip()
                    em   = str(row.get("Email", "") or "").strip()
                    on   = str(row.get("Order #", "") or "").strip()
                    pr   = str(row.get("Products", "") or "").strip()
                    sub  = float(row.get("Subtotal", 0) or 0)
                    disc = float(row.get("Discount", 0) or 0)
                    tax  = float(row.get("Tax", 0) or 0)
                    ship = float(row.get("Shipping", 0) or 0)
                    tot  = float(row.get("Total", 0) or 0)
                    if tot == 0: tot = round(sub - disc + tax + ship, 2)
                    if nm and em and on and pr and tot > 0:
                        if add_to_queue(nm, em, on, pr, sub, tax, ship, tot, disc): added += 1
                if added:
                    st.success(f"Added {added} order(s) to the queue.")
                    st.rerun()
        elif _mode == "Excel Import":
            st.markdown("#### Import from VEI Checkout Excel File")
            xl_file = st.file_uploader("Choose an Excel file", type=["xlsx"], key="excel_upload")
            if st.button("Import Excel", type="primary", key="btn_xl_import"):
                if xl_file:
                    with st.spinner("Importing..."):
                        rows, warns = parse_excel_file(xl_file.read())
                        for w in warns: st.warning(w)
                        if rows:
                            st.session_state.queue.extend(rows)
                            st.success(f"Imported {len(rows)} order(s) from Excel.")
                            st.rerun()
                        else:
                            st.error("No valid orders found.")

        else:  # Order Template
            st.markdown("#### Customize your order email layout")
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

            _db_tpl = load_email_template("order_template", cfg)
            _current_tpl = _db_tpl or cfg.get("email_html_template", "").strip()
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
                        save_email_template("order_template", _tpl_input.strip(), cfg)
                        st.toast("Template saved to config and database.", icon="💾")
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

            if "_tpl_preview_html" in st.session_state:
                st.markdown("---")
                st.markdown("**Email preview** — sample order: Jane Smith · ORD-1001 · Blue T-Shirt, Black Jeans")
                st.components.v1.html(st.session_state["_tpl_preview_html"], height=800, scrolling=True)

    # ── Email Campaigns ──────────────────────────
    with tab_campaign:
        _camp_cfg = st.session_state.cfg
        _camp_from = _camp_cfg.get("from_name", "")
        _camp_smtp_email = _camp_cfg.get("smtp_email", "").strip()
        _camp_smtp_pass  = (_camp_cfg.get("smtp_password", "") or "").replace(" ", "")

        if not _camp_smtp_email or not _camp_smtp_pass:
            st.warning("Configure your Gmail credentials in **Settings → Email** before sending campaigns.")

        _camp_mode = st.radio(
            "Campaign Mode",
            ["Upload CSV", "Paste Contacts", "Email Template"],
            horizontal=True,
            label_visibility="collapsed",
            key="camp_mode_radio",
        )

        # Resolve contacts from whichever source was used last
        _camp_contacts_parsed: list[dict] = st.session_state.get("_camp_csv_contacts") or []

        # ── Upload CSV ────────────────────────────────────────────────
        if _camp_mode == "Upload CSV":
            st.caption(
                "Upload a CSV with at minimum an **Email** column. "
                "Include a **Name** column for personalized greetings."
            )
            with st.expander("CSV format example"):
                st.code("Name,Email\nJane Smith,jane@example.com\nJohn Doe,john@veinternational.org", language="text")
            _camp_csv_file = st.file_uploader("Contacts CSV", type=["csv"], key="camp_csv_upload",
                                               label_visibility="collapsed")
            if _camp_csv_file:
                try:
                    _cdf = pd.read_csv(_camp_csv_file)
                    _cdf.columns = [c.strip() for c in _cdf.columns]
                    _c_email_col = next((c for c in _cdf.columns if "email" in c.lower()), None)
                    _c_name_col  = next((c for c in _cdf.columns if "name" in c.lower()), None)
                    if not _c_email_col:
                        st.error(f"No email column found. Columns: {list(_cdf.columns)}")
                    else:
                        _file_contacts: list[dict] = []
                        for _, _ccr in _cdf.iterrows():
                            _cem = str(_ccr[_c_email_col]).strip()
                            _cnm = (str(_ccr[_c_name_col]).strip()
                                    if _c_name_col else _cem.split("@")[0].replace(".", " ").title())
                            if validate_email(_cem):
                                _file_contacts.append({"name": _cnm, "email": _cem})
                        if _file_contacts:
                            st.session_state["_camp_csv_contacts"] = _file_contacts
                            _camp_contacts_parsed = _file_contacts
                            st.success(f"CSV loaded — **{len(_file_contacts)}** valid contact(s)")
                            st.dataframe(pd.DataFrame(_file_contacts[:15]), use_container_width=True, hide_index=True)
                            if len(_file_contacts) > 15:
                                st.caption(f"… and {len(_file_contacts) - 15} more")
                        else:
                            st.warning("No valid email addresses found.")
                            st.session_state.pop("_camp_csv_contacts", None)
                except Exception as _cfe:
                    st.error(f"CSV read error: {_cfe}")
            elif st.session_state.get("_camp_csv_contacts"):
                st.info(f"{len(st.session_state['_camp_csv_contacts'])} contact(s) loaded from CSV. Upload a new file to replace.")
                st.dataframe(pd.DataFrame(st.session_state["_camp_csv_contacts"][:10]), use_container_width=True, hide_index=True)

        # ── Paste Contacts ────────────────────────────────────────────
        elif _camp_mode == "Paste Contacts":
            st.caption("One contact per line. Accepted: `Name, email`  ·  `email only`  ·  tab-separated paste from a spreadsheet.")
            with st.expander("Example formats"):
                st.code("Jane Smith, jane@example.com\njohn@veinternational.org\nJohn Doe\tjohn@veinternational.org", language=None)
            _camp_contacts_raw = st.text_area(
                "Contact List",
                placeholder="Jane Smith, jane@example.com\nJohn Doe, john@veinternational.org",
                height=200,
                key="camp_contacts_bulk",
                label_visibility="collapsed",
            )
            _text_contacts: list[dict] = []
            if _camp_contacts_raw.strip():
                for _line in _camp_contacts_raw.strip().split("\n"):
                    _line = _line.strip()
                    if not _line or _line.startswith("#"):
                        continue
                    if "\t" in _line:
                        _parts = [p.strip() for p in _line.split("\t")]
                        for _p in _parts:
                            if "@" in _p:
                                _nm2 = next((pp for pp in _parts if pp != _p and "@" not in pp), _p.split("@")[0])
                                _text_contacts.append({"name": _nm2, "email": _p})
                                break
                    elif "," in _line:
                        _pts = [p.strip() for p in _line.split(",", 1)]
                        if len(_pts) == 2 and "@" in _pts[1]:
                            _text_contacts.append({"name": _pts[0], "email": _pts[1]})
                        elif len(_pts) == 2 and "@" in _pts[0]:
                            _text_contacts.append({"name": _pts[1], "email": _pts[0]})
                    elif "@" in _line:
                        _text_contacts.append({"name": _line.split("@")[0].replace(".", " ").title(), "email": _line})
                if _text_contacts:
                    st.session_state["_camp_csv_contacts"] = _text_contacts
                    _camp_contacts_parsed = _text_contacts
                    st.success(f"**{len(_text_contacts)}** contact(s) parsed")

        # ── Email Template ────────────────────────────────────────────
        elif _camp_mode == "Email Template":
            _camp_ai_prompt = """\
You are building an HTML email template for a marketing/broadcast campaign.
Use ONLY these variables (double curly braces, exactly as shown):
  {{name}}         — recipient's name
  {{from_name}}    — your VEI firm name

Requirements:
- Return a COMPLETE HTML document (<!DOCTYPE html> … </html>)
- Email-safe: inline styles only, no external CSS or JS, table-based layout
- Mobile-friendly: max content width 600 px, readable on small screens
- Must include {{name}} for personalization

Design brief: [describe your campaign style here — e.g. "modern and bold, high contrast, blue background with white text, include a 'Shop Now' button style link"]
"""
            with st.expander("AI prompt — paste into any AI to generate a template"):
                st.code(_camp_ai_prompt, language=None)
                st.caption("Replace the design brief, paste into your AI, then copy the HTML back here.")

            _camp_subject = st.text_input(
                "Subject Line",
                key="camp_subject",
                placeholder="Important update from your VEI firm",
            )

            st.markdown("**HTML Template**")
            st.caption("Use `{{name}}` for recipient name and `{{from_name}}` for your firm name.")
            _camp_tpl_raw = st.text_area(
                "Campaign HTML",
                value=_DEFAULT_CAMPAIGN_TEMPLATE,
                height=240,
                key="camp_html",
                label_visibility="collapsed",
            )

            _camp_prev_col, _camp_send_col = st.columns(2)
            with _camp_prev_col:
                if st.button("Preview Email", width="stretch", key="btn_camp_preview"):
                    st.session_state["_camp_preview_html"] = (
                        _camp_tpl_raw
                        .replace("{{name}}", "Jane Smith")
                        .replace("{{from_name}}", _camp_from or "Your VEI Firm")
                    )
            if "_camp_preview_html" in st.session_state:
                with st.expander("Email Preview", expanded=True):
                    st.components.v1.html(st.session_state["_camp_preview_html"], height=500, scrolling=True)

            _camp_contact_count = len(_camp_contacts_parsed)
            if _camp_contact_count == 0:
                st.info("No contacts loaded yet — go to **Upload CSV** or **Paste Contacts** first.")

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

    with tab_email_docs:
        st.subheader("Mass Email — Documentation")
        st.markdown("""
### How Order Emails Work

MERIT builds personalized HTML order confirmation emails and sends them via your Gmail account (SMTP). Here is the complete flow:

---

### Entry Methods

| Method | Use when |
|---|---|
| **Single Order** | You have one order to add manually |
| **Bulk Table** | You have several orders — type them in the table or upload a CSV |
| **Excel Import** | You exported a checkout report from VEI Store Manager (two-sheet Excel: Transactions + Transaction Items) |
| **Order Template** | You want to customize the HTML email design |

---

### Queue System

Orders are not sent immediately — they are added to a **Queue** first. This lets you:
- Review all orders before sending
- Spot unmatched products (shown in red)
- Delete individual orders that look wrong
- Send all at once with one click

**Unmatched products** appear in red in the queue. This means the product name in the order doesn't match any product in your catalog. Fix this by either correcting the product name in the order or adding the product in the Products page.

---

### Inventory Deduction

When an email is sent successfully, MERIT automatically deducts 1 unit of stock per product per order. For products ordered in quantities (e.g. "Blue T-Shirt x 3"), **3 units** are deducted.

**Important:** Orders cannot be sent if any product in the queue has 0 or negative stock. You will see an error and must either:
- Adjust stock in Inventory → Adjust Stock
- Remove the order from the queue

---

### Excel Import Format

MERIT expects the VEI Store Manager export format with two sheets:
- **Sheet 1 (Transactions):** One row per order — Transaction No, Customer Email, Billing Name, Subtotal, Tax, Shipping, Total
- **Sheet 2 (Transaction Items):** One row per item — Transaction No, Item Name, Quantity

Items are automatically grouped by Transaction No. Quantities > 1 appear as "Item Name x N" in the products field.

---

### Product Image Attachments

When sending order emails, MERIT automatically downloads each product's image (from your image host) and attaches it to the email as a file. Recipients see the product images both embedded in the email body AND as downloadable attachments.

---

### Email Template Variables

Use these in your custom HTML template (Order Template mode):

| Variable | What it inserts |
|---|---|
| `{{name}}` | Customer name |
| `{{order_number}}` | Order number |
| `{{from_name}}` | Your VEI firm name |
| `{{items_html}}` | Ready-made HTML product rows (with images) |
| `{{subtotal}}` | Subtotal ($) |
| `{{discount}}` | Discount ($) |
| `{{tax}}` | Tax ($) |
| `{{shipping}}` | Shipping ($) |
| `{{total_cost}}` | Order total ($) |

---

### Order Totals Auto-Calculation

In Single Order and Bulk Table entry, if you leave **Total** at $0, it auto-calculates as:
```
Total = Subtotal − Discount + Tax + Shipping
```

---

### Saving Templates

Order templates are saved to:
1. `config.json` (local)
2. SQLite database (`email_templates` table)
3. Supabase (`email_templates` table) — if connected

Templates persist across app reboots when Supabase is connected.
        """)

    # ── Queue ───────────────────────────────────

    st.divider()
    queue = st.session_state.queue

    # Build product image lookup for the queue preview and email sending
    # Use only the first image URL if multiple are stored comma-separated
    def _first_img(url: str) -> str:
        return url.split(",")[0].strip() if url and "," in url else url

    _products_lookup: dict[str, str] = {
        p["item_name"]: _first_img(p["image_url"])
        for p in _catalog_products
        if p.get("image_url") and _first_img(p["image_url"]) not in ("N/A", "")
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
                    st.toast("Queue cleared.", icon=None)
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
                    st.caption(f"Unmatched: {', '.join(unmatched)}")
            with row_r:
                if st.button("Delete", key=f"del_{i}", width="stretch"):
                    with st.spinner("Deleting..."):
                        st.session_state.queue.pop(i)
                        st.toast("Order removed.", icon=None)
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

            # ── Pre-send stock check ──────────────────────────────────
            _blocked_items: list[str] = []
            _stock_sim: dict[str, int] = dict(_presend_stock)
            for _chk_order in queue:
                for _chk_p in split_products(_chk_order.get("products", "")):
                    _chk_name, _chk_qty = _parse_product_qty(_chk_p)
                    _chk_spl = _chk_name.lower().strip()
                    _chk_sku = _name_to_sku.get(_chk_spl)
                    if not _chk_sku:
                        for _cn2, _cs2 in _name_to_sku.items():
                            if _chk_spl in _cn2 or _cn2 in _chk_spl:
                                _chk_sku = _cs2
                                break
                    if _chk_sku:
                        _cur = _stock_sim.get(_chk_sku, 0)
                        if _cur <= 0:
                            _blocked_items.append(f"'{_chk_name}' is already out of stock (stock: {_cur})")
                        _stock_sim[_chk_sku] = _cur - _chk_qty

            if _blocked_items:
                _unique_blocked = list(dict.fromkeys(_blocked_items))
                st.error("**Cannot send — out-of-stock products in queue:**\n" + "\n".join(f"• {b}" for b in _unique_blocked[:8]))
                st.info("Remove these orders from the queue or adjust stock in Inventory → Adjust Stock before sending.")
                st.stop()

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

                msg = MIMEMultipart("mixed")
                msg["From"]    = f"{from_name} <{smtp_email}>"
                msg["To"]      = order["email"]
                msg["Subject"] = subject
                _alt_part = MIMEMultipart("alternative")
                _alt_part.attach(MIMEText(build_text(order, from_name), "plain"))
                _alt_part.attach(MIMEText(
                    build_html(order, from_name, _products_lookup, cfg.get("email_html_template")),
                    "html",
                ))
                msg.attach(_alt_part)
                # Attach product images as files
                _attached_img_names: set[str] = set()
                for _att_p in split_products(order.get("products", "")):
                    _att_name, _ = _parse_product_qty(_att_p)
                    _att_url = _products_lookup.get(_att_name)
                    if not _att_url:
                        for _pk, _pv in _products_lookup.items():
                            if _att_name.lower() in _pk.lower() or _pk.lower() in _att_name.lower():
                                _att_url = _pv
                                break
                    if _att_url and _att_url not in ("N/A", ""):
                        _safe_fn = re.sub(r"[^\w]", "_", _att_name)[:40]
                        if _safe_fn not in _attached_img_names:
                            try:
                                with _urllib_request.urlopen(_att_url, timeout=6) as _ir:
                                    _img_bytes = _ir.read()
                                _img_part = MIMEImage(_img_bytes)
                                _img_part.add_header("Content-Disposition", "attachment",
                                                     filename=f"{_safe_fn}.jpg")
                                msg.attach(_img_part)
                                _attached_img_names.add(_safe_fn)
                            except Exception:
                                pass

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
                    "Date": datetime.now().strftime("%Y-%m-%d %H:%M"),
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
                        _pclean, _pqty = _parse_product_qty(_spname)
                        _spl = _pclean.lower().strip()
                        _matched_sku = _name_to_sku.get(_spl)
                        if not _matched_sku:
                            for _cn, _csku in _name_to_sku.items():
                                if _spl in _cn or _cn in _spl:
                                    _matched_sku = _csku
                                    break
                        if _matched_sku:
                            _deductions[_matched_sku] = _deductions.get(_matched_sku, 0) + _pqty
            if _deductions:
                for _dsku, _dqty in _deductions.items():
                    adjust_inventory_sqlite(_dsku, -_dqty)
                    if _has_sb_send:    adjust_inventory_supabase(_dsku, -_dqty, cfg)
                    if _has_turso(cfg): adjust_inventory_turso(_dsku, -_dqty, cfg)
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
                st.toast(f"All {sent_n} emails sent!", icon=None)
                st.success(f"All {sent_n} emails sent successfully.{_inv_note}")
            else:
                st.toast(f"{sent_n} sent, {failed_n} failed.", icon=None)
                st.warning(f"{sent_n} sent, {failed_n} failed. See the results table above.")

            st.session_state.queue    = []
            st.toast("All emails sent!", icon=None)
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

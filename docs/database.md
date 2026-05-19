# Database Architecture

MERIT supports three database layers that work together to keep your data fast, persistent, and redundant.


## Overview

| Layer | Technology | Role |
|---|---|---|
| **Turso** | Distributed SQLite (libSQL) | Primary cloud database — recommended for all firms |
| **Supabase** | PostgreSQL | Secondary cloud database — optional, adds API key for storefront integration |
| **SQLite** | Local file (`data.db`) | Local cache — always available, used during initial setup |

When both Turso and Supabase are connected, every write goes to all three simultaneously. Reads prefer Turso → Supabase → SQLite in that order.


## Turso (Primary)

Turso uses the libSQL HTTP API (Hrana v2). No extra Python packages are required — MERIT communicates with it using the standard library `urllib.request`.

### Connection

You need two values from your Turso database page:

| Field | Format | Where to find it |
|---|---|---|
| **Database URL** | `libsql://[db-name]-[username].turso.io` | Connect section on the database page |
| **Auth Token** | `eyJ…` (JWT) | Create a token link on the database page |

Paste both into **Settings → Database → Turso**.

### Token type

Use the **database-specific token** created from the database page. Do NOT use the Platform API token from the sidebar avatar menu — that token controls Turso account management and will be rejected with a 401 error on database queries.

Token settings:
- **Expiration:** 1 year
- **Authorization:** Read & Write

### Tables

MERIT creates and manages the following tables in Turso:

| Table | Contents |
|---|---|
| `users` | Firm members — email, hashed password, role, invite token |
| `roles` | Role definitions — role name and permitted pages |
| `inventory` | Products — SKU, name, price, description, images, stock levels |
| `outbound_logs` | Order email audit trail — recipient, items, cost breakdown |
| `financials` | Manual ledger entries |
| `fin_budgets` | Budget line items |
| `email_templates` | Saved email templates |

Run **Settings → Database → Setup Turso Tables** to create these tables and sync users and roles from SQLite.


## Supabase (Secondary)

Supabase provides a PostgreSQL database and an Anon Key used for storefront API access (Row Level Security policies on the `inventory` and `products` tables).

### Connection

You need two values from your Supabase project:

| Field | Format | Where to find it |
|---|---|---|
| **Connection String** | `postgresql://postgres.xxx:[PASSWORD]@...` | Connect button → Session Pooler tab |
| **Anon Key** | `eyJ…` (JWT) | Project Settings → API → Legacy API keys |

Paste both into **Settings → Database → Supabase**.

### When to use Supabase

- You need an Anon Key for Row Level Security on your storefront website.
- Your firm is already using Supabase for other purposes.
- You want a PostgreSQL backup in addition to Turso.

Turso is sufficient for all core MERIT functionality. Supabase is optional.


## SQLite (Local Cache)

`data.db` lives alongside `app.py` on the Streamlit Cloud server. It is used for:

- Storing users and roles before cloud credentials are configured.
- Serving as an offline fallback if both cloud databases are unavailable.

> [!WARNING]
> Streamlit Cloud restarts periodically and can wipe `data.db`. Always save your Secrets TOML so your cloud database credentials are restored on reboot. Your actual data lives in Turso/Supabase, not in `data.db`.


## Write Priority

All write operations (create/update/delete) go to every connected database:

```
SQLite → Turso (if configured) → Supabase (if configured)
```

Failures in one database are reported but do not block the others.

## Read Priority

All read operations use the first available source:

```
Turso → Supabase → SQLite
```

Results are cached for 30 seconds to reduce API calls.


## Sync

If you configure Turso after already having data in SQLite, run **Settings → Database → Setup Turso Tables**. This creates the schema and syncs all existing users and roles from SQLite into Turso.

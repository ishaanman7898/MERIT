"""
Quick integration test: add, verify, then delete a test product in Turso.
Run with:  python test_turso.py
Reads credentials from config.json (same as the app).
"""
import json, urllib.request, urllib.error
from pathlib import Path

# ── load config ────────────────────────────────────────────────────────────
cfg = json.loads(Path("config.json").read_text(encoding="utf-8"))
raw_url = cfg.get("turso_url", "").strip()
token   = cfg.get("turso_auth_token", "").strip()
if not raw_url or not token:
    raise SystemExit("turso_url / turso_auth_token not set in config.json")

url = raw_url.replace("libsql://", "https://", 1).rstrip("/")
print(f"Connecting to: {url}\n")

# ── Hrana v2 helpers ───────────────────────────────────────────────────────
def _arg(v):
    if v is None:                return {"type": "null"}
    if isinstance(v, bool):      return {"type": "integer", "value": "1" if v else "0"}
    if isinstance(v, int):       return {"type": "integer", "value": str(v)}
    if isinstance(v, float):     return {"type": "float",   "value": v}   # JSON number, NOT string
    return {"type": "text", "value": str(v)}

def pipeline(stmts):
    requests = [{"type": "execute", "stmt": {"sql": sql, "args": [_arg(p) for p in params]}}
                for sql, params in stmts]
    requests.append({"type": "close"})
    payload = json.dumps({"baton": None, "requests": requests}).encode()
    req = urllib.request.Request(
        f"{url}/v2/pipeline", data=payload,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            result = json.loads(r.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {e.code}: {body[:500]}")
    for r in result.get("results", []):
        if r.get("type") == "error":
            raise RuntimeError(r.get("error", {}).get("message", "Turso error"))
    return result

def query(sql, params=()):
    result = pipeline([(sql, params)])
    resp = result["results"][0].get("response", {}).get("result", {})
    cols = [c["name"] for c in resp.get("cols", [])]
    def coerce(cell):
        t, v = cell.get("type"), cell.get("value")
        if t == "null" or v is None: return None
        if t == "integer": return int(v)
        if t in ("real", "float"): return float(v)
        return v
    return [dict(zip(cols, [coerce(c) for c in row])) for row in resp.get("rows", [])]

# ── test ───────────────────────────────────────────────────────────────────
TEST_SKU = "TEST-BLUE-JPG"

print("1. Inserting test product (blue.jpg) into inventory + products...")
pipeline([
    (
        "INSERT INTO inventory (sku,item_name,category,price,stock_left,original_stock,status,image_url)"
        " VALUES (?,?,?,?,?,?,?,?)"
        " ON CONFLICT(sku) DO UPDATE SET item_name=excluded.item_name, category=excluded.category,"
        " price=excluded.price, image_url=excluded.image_url",
        (TEST_SKU, "blue.jpg", "Test", 9.99, 5, 5, "In stock", "N/A"),
    ),
    (
        "INSERT INTO products (sku,item_name,category,price,description,buy_button_url,image_url,active)"
        " VALUES (?,?,?,?,?,?,?,?)"
        " ON CONFLICT(sku) DO UPDATE SET item_name=excluded.item_name, category=excluded.category,"
        " price=excluded.price, description=excluded.description,"
        " buy_button_url=excluded.buy_button_url, image_url=excluded.image_url, active=excluded.active",
        (TEST_SKU, "blue.jpg", "Test", 9.99, "A test product", "", "N/A", 1),
    ),
])
print("   INSERT OK\n")

print("2. Reading back from inventory...")
rows = query("SELECT sku, item_name, price, stock_left FROM inventory WHERE sku=?", (TEST_SKU,))
assert rows, "Product not found after insert!"
r = rows[0]
assert r["item_name"] == "blue.jpg",  f"item_name mismatch: {r}"
assert r["price"]     == 9.99,        f"price mismatch: {r}"
assert r["stock_left"] == 5,          f"stock_left mismatch: {r}"
print(f"   {r}\n")

print("3. Reading back from products...")
rows2 = query("SELECT sku, item_name, active FROM products WHERE sku=?", (TEST_SKU,))
assert rows2, "Product row not found in products table!"
print(f"   {rows2[0]}\n")

print("4. Updating price to 14.99...")
pipeline([("UPDATE inventory SET price=? WHERE sku=?", (14.99, TEST_SKU))])
rows3 = query("SELECT price FROM inventory WHERE sku=?", (TEST_SKU,))
assert rows3[0]["price"] == 14.99, f"Update failed: {rows3}"
print("   UPDATE OK\n")

print("5. Deleting test product...")
pipeline([
    ("DELETE FROM inventory WHERE sku=?", (TEST_SKU,)),
    ("DELETE FROM products  WHERE sku=?", (TEST_SKU,)),
])
rows4 = query("SELECT sku FROM inventory WHERE sku=?", (TEST_SKU,))
assert not rows4, "Delete failed — row still present!"
print("   DELETE OK\n")

print("ALL TESTS PASSED — Turso add / edit / delete works correctly.")

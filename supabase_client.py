"""
Shared Supabase client helper.
Reads credentials from config.json and returns a ready-to-use client.
"""
import json
from pathlib import Path

_CONFIG_FILE = Path(__file__).parent / "config.json"


def _load_cfg() -> dict:
    try:
        if _CONFIG_FILE.exists():
            return json.loads(_CONFIG_FILE.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}


def get_authed_supabase():
    """Return a Supabase client using the service-role key from config.json.
    Raises RuntimeError if credentials are missing."""
    cfg = _load_cfg()
    url = cfg.get("supabase_url", "").strip()
    # Prefer service_role key for full backend access; fall back to anon key.
    key = (cfg.get("supabase_service_role_key") or cfg.get("supabase_key") or "").strip()

    if not url or not key:
        raise RuntimeError(
            "Supabase credentials not configured. "
            "Go to Settings → Database Connections and save your Project URL and key."
        )

    try:
        from supabase import create_client  # type: ignore
    except ImportError as exc:
        raise RuntimeError("supabase package not installed. Run: pip install supabase") from exc

    return create_client(url, key)

# supabase_client.py
# Provides authenticated Supabase client initialization.
# All modules import get_authed_supabase() from here — never create clients directly.

import streamlit as st
from supabase import create_client, Client


def get_authed_supabase() -> Client:
    """Return an authenticated Supabase client using st.secrets credentials.

    Raises a clear error if SUPABASE_URL or SUPABASE_KEY are missing from secrets.
    """
    url = st.secrets.get("SUPABASE_URL")
    key = st.secrets.get("SUPABASE_KEY")

    if not url or not key:
        raise ValueError(
            "Supabase credentials are missing. "
            "Please set SUPABASE_URL and SUPABASE_KEY in .streamlit/secrets.toml"
        )

    return create_client(url, key)

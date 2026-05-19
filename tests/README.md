# Tests

This folder contains development and integration tests.

## Files

| File | Purpose |
|---|---|
| `test_turso.py` | Turso HTTP API integration test — verifies database URL, auth token, and table schema |

## Running

```
python tests/test_turso.py
```

Requires `turso_url` and `turso_auth_token` to be set in `config.json`.

Test files are excluded from git tracking (see `.gitignore`).

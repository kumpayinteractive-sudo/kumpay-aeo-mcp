"""Configuration for the Kumpay AEO MCP server (separate from the Whop project)."""
from __future__ import annotations

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

SERPSLING_AUTH_KEY: str | None = os.getenv("SERPSLING_AUTH_KEY")
SERPSLING_BASE_URL: str = os.getenv(
    "SERPSLING_BASE_URL", "https://api.serpsling.com"
).rstrip("/")

ADMIN_TOKEN: str | None = os.getenv("ADMIN_TOKEN")
DB_PATH: str = os.getenv("DB_PATH", str(BASE_DIR / "data" / "mcp.db"))
KEY_PEPPER: str = os.getenv("KEY_PEPPER", "dev-pepper-change-me")

# Buyer-facing safety rails
SITE_AUDIT_DEFAULT_PAGES = int(os.getenv("SITE_AUDIT_DEFAULT_PAGES", "20"))
SITE_AUDIT_MAX_PAGES = int(os.getenv("SITE_AUDIT_MAX_PAGES", "100"))
CREATE_WAIT_TIMEOUT_S = int(os.getenv("CREATE_WAIT_TIMEOUT_S", "180"))
CREATE_WAIT_INTERVAL_S = int(os.getenv("CREATE_WAIT_INTERVAL_S", "10"))

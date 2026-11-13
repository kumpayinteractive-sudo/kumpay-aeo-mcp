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

# Hosts the MCP transport accepts (SDK DNS-rebinding protection: any Host
# not on this list gets 421). Comma-separated; "host:*" matches any port.
# The public domain MUST be listed or no MCP client can connect.
MCP_ALLOWED_HOSTS: list[str] = [
    h.strip()
    for h in os.getenv(
        "MCP_ALLOWED_HOSTS",
        "mcp.kumpaytech.com,"
        "r2ot9tnjjrkic0tnxurot7oc.45.92.158.28.sslip.io,"
        "127.0.0.1:*,localhost:*",
    ).split(",")
    if h.strip()
]

# Buyer-facing safety rails
SITE_AUDIT_DEFAULT_PAGES = int(os.getenv("SITE_AUDIT_DEFAULT_PAGES", "20"))
SITE_AUDIT_MAX_PAGES = int(os.getenv("SITE_AUDIT_MAX_PAGES", "100"))
CREATE_WAIT_TIMEOUT_S = int(os.getenv("CREATE_WAIT_TIMEOUT_S", "180"))
CREATE_WAIT_INTERVAL_S = int(os.getenv("CREATE_WAIT_INTERVAL_S", "10"))

# Kumpay AEO MCP

[![mcptry](https://mcptry.com/badge/io.github.kumpayinteractive-sudo/kumpay-aeo-mcp)](https://mcptry.com/servers/io.github.kumpayinteractive-sudo/kumpay-aeo-mcp)

Remote MCP server that gives AI agents live SEO data: SERP competition
analysis, keyword research, backlink profiles, full site audits, and
AI-search visibility scoring — via 7 metered MCP tools.

By [Kumpay Tech](https://kumpaytech.com) — the team behind
[Kumpay AEO](https://kumpaytech.com), the AI visibility audit tool.

## How it works

- MCP endpoint (Streamable HTTP): `POST /mcp`
- Buyers authenticate with a per-buyer key: `Authorization: Bearer sk_mcp_...`
- The upstream provider key lives only in this server's env — never sent
  to buyers.
- Every tool call is metered into a SQLite ledger (buyer, tool, credits).

## Quick start (local)

```bash
git clone https://github.com/kumpayinteractive-sudo/kumpay-aeo-mcp
cd kumpay-aeo-mcp
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env   # fill in SERPSLING_AUTH_KEY, ADMIN_TOKEN, KEY_PEPPER

# create a buyer key
.venv/bin/python -m app.store create-key --name "test-buyer"

# run
.venv/bin/uvicorn app.server:app --port 8080
```

Connect an MCP client to `http://localhost:8080/mcp` with header
`Authorization: Bearer <key>`.

## Tools (v1)

| Tool | Cost |
|---|---|
| `keyword_research` | 0 credits |
| `competition_analysis` | 10 credits flat |
| `backlink_analysis` | 10 credits flat |
| `site_audit` | 1 credit / page (default 20, max 100) |
| `ai_visibility_audit` | 0 credits |
| `get_analysis_status` | free |
| `locations` | free |

Costs are the values measured live against the upstream provider
on 2026-10-12.

## Buyer key management

```bash
python -m app.store create-key --name "acme"   # prints key once
python -m app.store list-keys
python -m app.store revoke --name "acme"
python -m app.store usage --name "acme"
```

## Admin

- `GET /health` → `{"ok": true}`
- `GET /admin/usage?token=...` → credit usage per buyer/tool
- `GET /admin/buyers?token=...` → buyer list

## Deploy (Coolify)

Separate service from the Whop app. Uses the included `Dockerfile`
(port 8080). Required env: `SERPSLING_AUTH_KEY`, `ADMIN_TOKEN`,
`KEY_PEPPER`. Needs a real domain + HTTPS before pointing buyers at it.
Persist `/app/data` (SQLite) with a volume.

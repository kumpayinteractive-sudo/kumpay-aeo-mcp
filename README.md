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

## Hermes Agent plugin

This repo is also a Portable Agent Plugins v1 package for
[Hermes Agent](https://hermes-agent.nousresearch.com): `plugin.json` +
`mcp.json` + the `kumpay-aeo` skill under `skills/`.

Install (before the catalog listing merges):

```bash
hermes plugins install kumpayinteractive-sudo/kumpay-aeo-mcp --no-enable
hermes plugins enable kumpay-aeo
```

Then add your API key to `~/.hermes/.env`:

```
KUMPAY_AEO_API_KEY=sk_mcp_...
```

Buy a credit pack at https://whop.kumpaytech.com — Starter is $29 for
100 credits, one-time, credits never expire. Then email
kumpaytech@gmail.com with your purchase receipt to get your API key
(keys are issued manually). Paid tools: competition and backlink analysis
€2.63 each, site audits €0.26 per page (effective prices at the Starter
rate; larger packs cost less per call). Keyword research, AI visibility
audits, status checks and location lookups are free. The plugin declares
a €26.35 spend limit per chat, and Hermes asks before each call.

Disclosure: every tool call goes to `https://mcp.kumpaytech.com/mcp` and
forwards the domains, keywords and business names you check to Kumpay
Tech's upstream SEO data provider. The plugin collects no telemetry.
Installing the plugin runs no code on your machine — it only registers
the hosted MCP server and loads the skill. (The server source in this repo
is for self-hosting; see Quick start above.)

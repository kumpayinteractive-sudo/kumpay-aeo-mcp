---
name: kumpay-aeo
description: "Use Kumpay AEO whenever a task needs live SEO or AI-search visibility data: keyword research with volume and CPC, SERP competition analysis for a domain, backlink profiles, full site audits, or checking whether AI answers (ChatGPT, Perplexity, Google AI Overviews) mention a brand. Paid tools cost Kumpay credits — competition and backlink analysis 10 credits each, site audits 1 credit per page; keyword research, AI visibility audits, status checks and location lookups are free. Requires a Kumpay AEO API key."
---

# Kumpay AEO

Kumpay AEO gives your agent live SEO data from a hosted MCP server at
`https://mcp.kumpaytech.com/mcp`, through 7 metered tools. Hermes shows the
server as `kumpay-aeo`; tool names below are the server's own (Hermes may
prefix them, e.g. `mcp__kumpay-aeo__keyword_research`).

| Tool | Cost | What it does |
|---|---|---|
| `locations` | free | Location (integer) and language codes for the tools below |
| `keyword_research` | 0 credits | Keyword ideas, volume, CPC for seed keywords |
| `competition_analysis` | 10 credits | SERP competition for a domain or URL |
| `backlink_analysis` | 10 credits | Backlink profile: summary + top referring domains |
| `site_audit` | 1 credit / page | Crawl a site for SEO issues (default 20 pages, max 100) |
| `ai_visibility_audit` | 0 credits | Whether AI answers mention a business, and who gets named instead |
| `get_analysis_status` | 0 credits | Poll an analysis started by another tool |

## When to reach for Kumpay AEO

- "What keywords should this site target?" — `keyword_research`.
- "Who ranks for this topic, and what keywords do they win?" — `competition_analysis`.
- "Who links to this domain?" — `backlink_analysis`.
- "Audit this site for SEO issues." — `site_audit`.
- "Does ChatGPT / Perplexity / Google AI Overviews mention this brand?" —
  `ai_visibility_audit`.

Example asks: "Use Kumpay AEO to research keywords for a sourdough bakery in
Austin", "Use Kumpay AEO to check whether ChatGPT mentions acme.com", "Use
Kumpay AEO to audit example.com for SEO issues".

## Connect and sign in

Every tool needs a Kumpay AEO API key, including the free ones (the key is
how usage is metered).

1. Buy a credit pack at https://whop.kumpaytech.com — Starter is $29 for
   100 credits, one-time, credits never expire. Then email
   kumpaytech@gmail.com with your purchase receipt to get your API key
   (keys are issued manually).
2. Add the key to your Hermes environment (never paste it into the chat,
   and never write it into this plugin's `mcp.json`):

   ```
   KUMPAY_AEO_API_KEY=sk_mcp_...
   ```

   in `~/.hermes/.env`, then restart Hermes (or `/reload-mcp`).
3. If a tool answers 401, the key is missing, wrong, or revoked — check
   `~/.hermes/.env` and reload.

To self-host instead, clone https://github.com/kumpayinteractive-sudo/kumpay-aeo-mcp
and run the server locally (see its README), then define your own `kumpay-aeo`
server in `config.yaml` pointing at your instance. A `config.yaml` server
with the same name replaces this package's entry.

## The method

1. **Get codes first.** `locations` returns the integer location codes and
   language codes the other tools need. Keyword research and competition
   analysis are country-level only (94 countries) — there are no city or
   state codes, so never promise per-city data.

```tool
locations
```

2. **Start free.** `keyword_research` and `ai_visibility_audit` cost
   nothing — run them before any paid tool.

```tool
keyword_research {"seed_keywords": ["sourdough bakery"], "location": 2840, "language": "en"}
```

```tool
ai_visibility_audit {"business_name": "Acme Bakery", "website_url": "https://acme.com"}
```

   `ai_visibility_audit` takes `site_type`: `online_only` (default) or
   `local` — local needs `location_code` (from `locations`) and
   `location_name`.
3. **Paid tools: say the cost first.** Before calling `competition_analysis`
   (10 credits), `backlink_analysis` (10 credits) or `site_audit`
   (1 credit per page requested), tell the user what it costs. Hermes asks
   the user to approve each call anyway, and refuses paid calls in
   unattended runs.

```tool
competition_analysis {"target": "acme.com", "location": 2840, "language": "en"}
```

```tool
backlink_analysis {"target": "acme.com"}
```

```tool
site_audit {"target": "https://acme.com", "page_limit": 20}
```

   Never raise `page_limit` above what the user agreed — each page is
   1 credit, and the maximum is 100.
4. **Poll if an analysis is still running.** A paid analysis may return an
   `analysis_id` instead of results. Poll it with `get_analysis_status`
   (free) until it completes — `kind` is `competition`, `backlink`,
   `site_audit` or `ai_visibility`.

```tool
get_analysis_status {"kind": "competition", "analysis_id": "<id from the analysis>"}
```

## Money rules

- The plugin declares a **100-credit spend limit per chat** (one Starter
  pack). A call that would take the chat past it asks first, even on a
  trusted server. The user can raise or remove it in their own
  `config.yaml` (`spend_limit`, `0` turns it off).
- Costs are facts about the server: they stay in force even if the user
  defines their own `kumpay-aeo` server in `config.yaml`, unless that
  entry sets its own costs.
- Never invent prices, credit balances, or results. If a tool errors or
  returns no data, say so and suggest the next step — do not fill the gap
  with made-up numbers.
- Never promise a brand *will* be mentioned by AI answers, a ranking
  position, or traffic. Report what the tools return, nothing more.

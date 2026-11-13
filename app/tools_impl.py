"""MCP tool implementations: SEO data tools with buyer metering.

Every tool keeps the upstream API key server-side. Buyer identity comes from
the Bearer key (see server.py) via a contextvar. Credit costs below are the
values measured live 2026-10-12 (see references in the sibling project).
"""
from __future__ import annotations

import contextvars
import json

from . import config, store
from .serpsling import SerpslingClient, SerpslingError

buyer_ctx: contextvars.ContextVar[str] = contextvars.ContextVar(
    "mcp_buyer", default="")

_client: SerpslingClient | None = None


def get_client() -> SerpslingClient:
    global _client
    if _client is None:
        _client = SerpslingClient()
    return _client


# ---------------------------------------------------------------- summaries
def _scalars(item: dict, limit: int = 10) -> dict:
    out = {}
    for k, v in item.items():
        if isinstance(v, (str, int, float, bool)) or v is None:
            out[k] = v
        if len(out) >= limit:
            break
    return out


def _first_list(data: dict, *keys: str) -> list:
    for k in keys:
        v = data.get(k)
        if isinstance(v, list) and v:
            return v
    for v in data.values():
        if isinstance(v, list) and v and isinstance(v[0], dict):
            return v
    return []


def _summarize_list(items: list, n: int) -> list:
    return [_scalars(i) if isinstance(i, dict) else i for i in items[:n]]


def _base(data: dict, extra: dict | None = None) -> dict:
    out = {"status": data.get("status"), "id": data.get("_id") or data.get("id")}
    if extra:
        out.update(extra)
    return out


def summarize_keyword_research(data: dict) -> dict:
    kws = _first_list(data, "keywords", "results", "keyword")
    rows = []
    for item in kws[:25]:
        if not isinstance(item, dict):
            continue
        row = {"keyword": item.get("keyword")}
        # verified shape: stats.keyword_data.keyword_info.{search_volume, cpc}
        info = (((item.get("stats") or {}).get("keyword_data") or {})
                .get("keyword_info") or {})
        if isinstance(info, dict):
            for f in ("search_volume", "cpc", "competition"):
                if f in info:
                    row[f] = info[f]
        rows.append(row)
    return _base(data, {"count": len(kws), "keywords": rows})


def summarize_competition(data: dict) -> dict:
    # Verified shape (sibling Django app, live 2026-10-11):
    # keywords[].{keyword, ranking.{rank_absolute,url,etv},
    #              stats.keyword_data.{keyword_info.search_volume,
    #                                   keyword_properties.keyword_difficulty}}
    kws = _first_list(data, "keywords", "keyword")
    rows = []
    for kw in kws[:20]:
        if not isinstance(kw, dict):
            continue
        ranking = kw.get("ranking") or {}
        stats = kw.get("stats") or {}
        kd = stats.get("keyword_data") or {}
        info = kd.get("keyword_info") or {}
        props = kd.get("keyword_properties") or {}
        k = kw.get("keyword")
        rows.append({
            "keyword": k if isinstance(k, str) else (k or {}).get("keyword", ""),
            "rank": ranking.get("rank_absolute"),
            "url": ranking.get("url"),
            "etv": ranking.get("etv"),
            "volume": info.get("search_volume"),
            "difficulty": props.get("keyword_difficulty"),
        })
    summary = data.get("summary")
    return _base(data, {
        "keyword_count": len(kws),
        "keywords": rows,
        "summary": _scalars(summary) if isinstance(summary, dict) else summary,
    })


def summarize_backlink(data: dict) -> dict:
    summary = data.get("summary")
    domains = _first_list(data, "referringDomains", "referring_domains",
                          "domains")
    return _base(data, {
        "summary": _scalars(summary) if isinstance(summary, dict) else summary,
        "referring_domains": _summarize_list(domains, 10),
    })


def summarize_site_audit(data: dict) -> dict:
    summary = data.get("summary")
    issues = _first_list(data, "issues", "errors", "warnings")
    return _base(data, {
        "summary": _scalars(summary) if isinstance(summary, dict) else summary,
        "top_issues": _summarize_list(issues, 15),
    })


def summarize_ai_visibility(data: dict) -> dict:
    recs = _first_list(data, "recommendations", "actions")
    return _base(data, {
        "score": data.get("score") or data.get("overallScore"),
        "recommendation_count": len(recs),
        "recommendations": _summarize_list(recs, 10),
    })


_SUMMARIZERS = {
    "competition": summarize_competition,
    "backlink": summarize_backlink,
    "site_audit": summarize_site_audit,
    "ai_visibility": summarize_ai_visibility,
}

_GETTERS = {
    "competition": "get_competition_analysis",
    "backlink": "get_backlink_analysis",
    "site_audit": "get_site_audit",
    "ai_visibility": "get_ai_visibility_audit",
}


def _pending(kind: str, id_: str, status: str) -> dict:
    return {"status": status, "analysis_id": id_,
            "hint": f"Still {status}. Call get_analysis_status with "
                    f"kind='{kind}' and this analysis_id to poll again."}


def _waiter_for(client, kind: str):
    names = {
        "competition": "wait_competition_analysis",
        "backlink": "wait_backlink_analysis",
        "site_audit": "wait_site_audit",
        "ai_visibility": "wait_ai_visibility_audit",
    }
    return getattr(client, names[kind])


def _create_and_wait(kind: str, create_fn, timeout: int | None = None) -> dict:
    client = get_client()
    created = create_fn()
    id_ = created.get("_id") or created.get("id")
    if not id_:
        raise SerpslingError(f"Serpsling returned no id: "
                             f"{json.dumps(created)[:300]}")
    store.log_usage(buyer_ctx.get(), kind, _COSTS[kind],
                    detail=f"target id {id_}")
    data = _waiter_for(client, kind)(id_, timeout)
    if data.get("status") != "complete":
        return _pending(kind, id_, data.get("status", "unknown"))
    return _SUMMARIZERS[kind](data)


# ------------------------------------------------------------------- costs
# Measured live 2026-10-12. site_audit is metered per requested page below.
_COSTS = {
    "keyword_research": 0,
    "competition": 10,
    "backlink": 10,
    "ai_visibility": 0,
}


# ------------------------------------------------------------------- tools
def keyword_research(seed_keywords: list[str], location: int,
                     language: str) -> dict:
    """Run keyword research for seed keywords. Costs 0 Serpsling credits."""
    client = get_client()
    created = client.create_keyword_research(seed_keywords, location, language)
    kr_id = created.get("_id") or created.get("id")
    store.log_usage(buyer_ctx.get(), "keyword_research", 0,
                    detail=f"kr {kr_id}")
    data = client.wait_keyword_research(kr_id)
    if data.get("status") != "complete":
        return _pending("keyword_research", kr_id, data.get("status",
                                                             "unknown"))
    return summarize_keyword_research(data)


def competition_analysis(target: str, location: int, language: str,
                         type_: str = "domain") -> dict:
    """Analyze SERP competition for a domain or URL. Costs 10 credits."""
    return _create_and_wait(
        "competition",
        lambda: get_client().create_competition_analysis(
            type_, target, location, language))


def backlink_analysis(target: str, type_: str = "domain") -> dict:
    """Analyze backlinks for a domain or URL. Costs 10 credits (flat)."""
    return _create_and_wait(
        "backlink",
        lambda: get_client().create_backlink_analysis(type_, target))


def site_audit(target: str,
               page_limit: int = config.SITE_AUDIT_DEFAULT_PAGES) -> dict:
    """Crawl a site for SEO issues. Costs 1 credit per page requested."""
    page_limit = max(1, min(config.SITE_AUDIT_MAX_PAGES, page_limit))
    client = get_client()
    created = client.create_site_audit(target, page_limit)
    audit_id = created.get("_id") or created.get("id")
    store.log_usage(buyer_ctx.get(), "site_audit", page_limit,
                    detail=f"audit {audit_id}, {page_limit} pages requested")
    data = client.wait_site_audit(audit_id)
    if data.get("status") != "complete":
        return _pending("site_audit", audit_id, data.get("status", "unknown"))
    return summarize_site_audit(data)


def ai_visibility_audit(business_name: str, website_url: str,
                        site_type: str = "online_only",
                        location_code: int | None = None,
                        location_name: str | None = None) -> dict:
    """Audit how visible a business is to AI search. Costs 0 credits."""
    location = None
    if site_type == "local" and location_code:
        location = {"locationCode": location_code,
                    "locationName": location_name or ""}
    return _create_and_wait(
        "ai_visibility",
        lambda: get_client().create_ai_visibility_audit(
            business_name, website_url, site_type, location))


def get_analysis_status(kind: str, analysis_id: str) -> dict:
    """Poll a previously started analysis. Costs 0 credits.

    kind: competition | backlink | site_audit | ai_visibility
    """
    if kind not in _GETTERS:
        raise ValueError(f"unknown kind '{kind}'")
    data = getattr(get_client(), _GETTERS[kind])(analysis_id)
    store.log_usage(buyer_ctx.get(), "get_analysis_status", 0,
                    detail=f"{kind} {analysis_id}")
    if data.get("status") != "complete":
        return _pending(kind, analysis_id, data.get("status", "unknown"))
    if kind in _SUMMARIZERS:
        return _SUMMARIZERS[kind](data)
    return _base(data)


_locations_cache: list | None = None


def locations() -> dict:
    """List location/language codes for keyword & competition tools. Free."""
    global _locations_cache
    if _locations_cache is None:
        _locations_cache = get_client().locations_languages()
    store.log_usage(buyer_ctx.get(), "locations", 0)
    return {"count": len(_locations_cache),
            "locations": _locations_cache[:100]}

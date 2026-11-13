"""Kumpay AEO MCP server.

Remote MCP endpoint (Streamable HTTP) at /mcp, protected by per-buyer
Bearer keys. The upstream provider key never leaves this server.

Run:
    uvicorn app.server:app --host 0.0.0.0 --port 8080
Buyer keys:
    python -m app.store create-key --name "acme"
"""
from __future__ import annotations

import functools

import contextlib

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from mcp.server.mcpserver import MCPServer
from starlette.middleware.base import BaseHTTPMiddleware

from . import config, store, tools_impl
from .tools_impl import buyer_ctx

mcp = MCPServer(
    name="kumpay-aeo-mcp",
    instructions=(
        "SEO data tools for AI agents (competition, keywords, "
        "backlinks, site audit, AI visibility). Each tool states its "
        "credit cost up front; usage is metered per buyer key."
    ),
)


def _require_buyer(fn):
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        if not buyer_ctx.get():
            raise RuntimeError("unauthenticated: no buyer key")
        return fn(*args, **kwargs)
    return wrapper


@mcp.tool(description="Keyword research for seed keywords. COST: 0 credits. "
          "location is an integer code from locations; language "
          "is a code like 'en'. Waits for completion and returns top keywords.")
@_require_buyer
def keyword_research(seed_keywords: list[str], location: int,
                     language: str) -> dict:
    return tools_impl.keyword_research(seed_keywords, location, language)


@mcp.tool(description="SERP competition analysis for a domain or URL. "
          "COST: 10 credits flat. Returns competitor keyword summary; if the "
          "analysis is still running, returns an analysis_id to poll with "
          "get_analysis_status.")
@_require_buyer
def competition_analysis(target: str, location: int, language: str,
                         type_: str = "domain") -> dict:
    return tools_impl.competition_analysis(target, location, language, type_)


@mcp.tool(description="Backlink analysis for a domain or URL. "
          "COST: 10 credits flat. Returns summary + top referring domains.")
@_require_buyer
def backlink_analysis(target: str, type_: str = "domain") -> dict:
    return tools_impl.backlink_analysis(target, type_)


@mcp.tool(description="Crawl a site for SEO issues. COST: 1 credit per page "
          "requested (default 20, max 100). Returns issue summary.")
@_require_buyer
def site_audit(target: str, page_limit: int = 20) -> dict:
    return tools_impl.site_audit(target, page_limit)


@mcp.tool(description="Audit a business's visibility in AI search results. "
          "COST: 0 credits. site_type is 'online_only' or 'local' (local "
          "needs location_code).")
@_require_buyer
def ai_visibility_audit(business_name: str, website_url: str,
                        site_type: str = "online_only",
                        location_code: int | None = None,
                        location_name: str | None = None) -> dict:
    return tools_impl.ai_visibility_audit(business_name, website_url,
                                          site_type, location_code,
                                          location_name)


@mcp.tool(description="Poll a previously started analysis. COST: 0 credits. "
          "kind: competition | backlink | site_audit | ai_visibility.")
@_require_buyer
def get_analysis_status(kind: str, analysis_id: str) -> dict:
    return tools_impl.get_analysis_status(kind, analysis_id)


@mcp.tool(description="Location/language codes for the keyword and "
          "competition tools. COST: free.")
@_require_buyer
def locations() -> dict:
    return tools_impl.locations()


class BuyerAuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if request.url.path.startswith("/mcp"):
            auth = request.headers.get("authorization", "")
            raw = auth[7:] if auth.lower().startswith("bearer ") else ""
            buyer = store.resolve_buyer(raw) if raw else None
            if not buyer:
                return JSONResponse({"error": "invalid or missing buyer key"},
                                    status_code=401)
            buyer_ctx.set(buyer)
        return await call_next(request)


_mcp_app = mcp.streamable_http_app(streamable_http_path="/")


@contextlib.asynccontextmanager
async def _lifespan(app: FastAPI):
    # The mounted MCP app's own lifespan (session manager task group)
    # is not auto-run on mount, so enter it explicitly here.
    async with _mcp_app.router.lifespan_context(_mcp_app):
        yield


app = FastAPI(title="Kumpay AEO MCP", lifespan=_lifespan)
app.add_middleware(BuyerAuthMiddleware)
app.mount("/mcp", _mcp_app)


@app.get("/health")
def health():
    return {"ok": True, "service": "kumpay-aeo-mcp"}


def _admin_ok(request: Request) -> bool:
    return bool(config.ADMIN_TOKEN) and \
        request.query_params.get("token") == config.ADMIN_TOKEN


@app.get("/admin/usage")
def admin_usage(request: Request, buyer: str | None = None):
    if not _admin_ok(request):
        return JSONResponse({"error": "forbidden"}, status_code=403)
    return {"usage": store.usage_summary(buyer)}


@app.get("/admin/buyers")
def admin_buyers(request: Request):
    if not _admin_ok(request):
        return JSONResponse({"error": "forbidden"}, status_code=403)
    return {"buyers": store.list_keys()}

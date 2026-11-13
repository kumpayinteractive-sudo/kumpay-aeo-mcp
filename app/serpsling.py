"""Thin Serpsling API client for the MCP wrapper.

Endpoint shapes verified live 2026-10-11/12 against the Serpsling dashboard API
(see the sibling project's integrations/serpsling.py and the Postman collection).
Never guess a schema here -- verify against those sources first.
"""
from __future__ import annotations

import time

import httpx

from . import config


class SerpslingError(RuntimeError):
    pass


class SerpslingClient:
    def __init__(self, auth_key: str | None = None,
                 base_url: str | None = None, timeout: int = 60):
        key = auth_key or config.SERPSLING_AUTH_KEY
        if not key:
            raise SerpslingError("SERPSLING_AUTH_KEY is not set")
        self._key = key
        self._base = (base_url or config.SERPSLING_BASE_URL).rstrip("/")
        self._client = httpx.Client(
            timeout=timeout,
            trust_env=False,  # ignore proxy env vars (may be malformed)
            headers={"AUTH_KEY": key, "Accept": "application/json"},
        )

    # ---- low-level ----
    def _request(self, method: str, path: str,
                 json: dict | None = None) -> dict:
        """Single HTTP layer; the local test harness monkeypatches this to
        route through the Secure Vault surrogate instead of a raw env key."""
        resp = self._client.request(method, self._base + path, json=json)
        if resp.status_code >= 400:
            raise SerpslingError(
                f"Serpsling {resp.status_code}: {resp.text[:500]}")
        try:
            return resp.json()
        except ValueError:
            raise SerpslingError(f"Serpsling non-JSON response: {resp.text[:200]}")

    def _wait(self, getter, id_: str,
              timeout: int | None = None) -> dict:
        timeout = timeout if timeout is not None else config.CREATE_WAIT_TIMEOUT_S
        interval = max(5, config.CREATE_WAIT_INTERVAL_S)
        deadline = time.time() + timeout
        while time.time() < deadline:
            data = getter(id_)
            if data.get("status") in ("complete", "error"):
                return data
            time.sleep(interval)
        # Return the pending record so the caller can hand back the id.
        return getter(id_)

    # ---- meta (0 credits) ----
    def locations_languages(self) -> list:
        return self._request(
            "GET", "/private/competition_analysis/locations_languages")

    def get_credits(self) -> dict:
        return self._request("GET", "/private/credits")

    # ---- keyword research (0 credits, verified) ----
    def create_keyword_research(self, seed_keywords: list[str], location: int,
                                language: str) -> dict:
        return self._request("POST", "/private/keyword_research/custom", json={
            "seedKeyword": seed_keywords,
            "location": location,
            "language": language,
        })

    def get_keyword_research(self, kr_id: str) -> dict:
        return self._request("GET", f"/private/keyword_research/{kr_id}")

    def wait_keyword_research(self, kr_id: str,
                              timeout: int | None = None) -> dict:
        return self._wait(self.get_keyword_research, kr_id, timeout)

    # ---- competition analysis (10 credits flat, verified) ----
    def create_competition_analysis(self, type_: str, target: str, location: int,
                                    language: str) -> dict:
        return self._request("POST", "/private/competition_analysis", json={
            "type": type_,  # "domain" | "url"
            "target": target,
            "location": location,
            "language": language,
        })

    def get_competition_analysis(self, analysis_id: str) -> dict:
        return self._request(
            "GET", f"/private/competition_analysis/{analysis_id}")

    def wait_competition_analysis(self, analysis_id: str,
                                  timeout: int | None = None) -> dict:
        return self._wait(self.get_competition_analysis, analysis_id, timeout)

    # ---- backlink analysis (10 credits flat, verified) ----
    def create_backlink_analysis(self, type_: str, target: str) -> dict:
        return self._request("POST", "/private/backlink_analysis", json={
            "type": type_,  # "domain" | "url"
            "target": target,
        })

    def get_backlink_analysis(self, analysis_id: str) -> dict:
        return self._request(
            "GET", f"/private/backlink_analysis/{analysis_id}")

    def wait_backlink_analysis(self, analysis_id: str,
                               timeout: int | None = None) -> dict:
        return self._wait(self.get_backlink_analysis, analysis_id, timeout)

    # ---- site audit (1 credit/page, verified) ----
    def create_site_audit(self, target: str, page_limit: int) -> dict:
        return self._request("POST", "/private/site_audit", json={
            "target": target,
            "pageLimit": page_limit,  # 1..1000
        })

    def get_site_audit(self, audit_id: str) -> dict:
        return self._request("GET", f"/private/site_audit/{audit_id}")

    def wait_site_audit(self, audit_id: str,
                        timeout: int | None = None) -> dict:
        return self._wait(self.get_site_audit, audit_id, timeout)

    # ---- AI visibility audit (0 credits observed, verified) ----
    def create_ai_visibility_audit(self, business_name: str, website_url: str,
                                   site_type: str,
                                   location: dict | None = None) -> dict:
        body: dict = {
            "businessName": business_name,
            "websiteUrl": website_url,
            "siteType": site_type,  # "local" | "online_only"
            "addressHidden": False,
        }
        if location:
            body["location"] = location  # {locationCode, locationName}
        return self._request("POST", "/private/ai_visibility_audit", json=body)

    def get_ai_visibility_audit(self, audit_id: str) -> dict:
        return self._request("GET", f"/private/ai_visibility_audit/{audit_id}")

    def wait_ai_visibility_audit(self, audit_id: str,
                                 timeout: int | None = None) -> dict:
        return self._wait(self.get_ai_visibility_audit, audit_id, timeout)

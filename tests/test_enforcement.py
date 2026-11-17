"""End-to-end enforcement tests.

A real server (uvicorn, in-process thread) + a real MCP client
(mcp SDK streamable HTTP) + a STUBBED upstream provider. No live
Serpsling calls are made and no real provider credits are spent.

Run:  .venv/bin/python -m unittest discover -s tests -v
"""
import asyncio
import socket
import tempfile
import threading
import time
import unittest
import uuid
from unittest import mock

import httpx

from app import config, store, tools_impl
from app.serpsling import SerpslingError

ADMIN_TOKEN = "test-admin-token-only"


def _free_port() -> int:
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


class FakeSerpslingClient:
    """Stub provider: completes instantly, records calls, can fail on demand."""

    def __init__(self):
        self.fail_next_create = False
        self.creates: list[tuple] = []
        self.site_audit_pages: list[int] = []

    def _maybe_fail(self):
        if self.fail_next_create:
            self.fail_next_create = False
            raise SerpslingError("simulated provider failure")

    def _complete(self, id_, **extra):
        data = {"status": "complete", "_id": id_}
        data.update(extra)
        return data

    def create_competition_analysis(self, type_, target, location, language):
        self._maybe_fail()
        self.creates.append(("competition", target))
        return {"_id": "comp-1", "status": "running"}

    def wait_competition_analysis(self, analysis_id, timeout=None):
        return self._complete(analysis_id, keywords=[{
            "keyword": "test kw",
            "ranking": {"rank_absolute": 3, "url": "https://example.com",
                        "etv": 10},
            "stats": {"keyword_data": {
                "keyword_info": {"search_volume": 100},
                "keyword_properties": {"keyword_difficulty": 20},
            }},
        }], summary={"total": 1})

    def get_competition_analysis(self, analysis_id):
        return self.wait_competition_analysis(analysis_id)

    def create_backlink_analysis(self, type_, target):
        self._maybe_fail()
        self.creates.append(("backlink", target))
        return {"_id": "bl-1", "status": "running"}

    def wait_backlink_analysis(self, analysis_id, timeout=None):
        return self._complete(analysis_id, summary={"backlinks": 5},
                              referringDomains=[{"domain": "example.com"}])

    def get_backlink_analysis(self, analysis_id):
        return self.wait_backlink_analysis(analysis_id)

    def create_site_audit(self, target, page_limit):
        self._maybe_fail()
        self.creates.append(("site_audit", target))
        self.site_audit_pages.append(page_limit)
        return {"_id": "audit-1", "status": "running"}

    def wait_site_audit(self, audit_id, timeout=None):
        return self._complete(audit_id, summary={"pages": 1}, issues=[])

    def get_site_audit(self, audit_id):
        return self.wait_site_audit(audit_id)

    def create_keyword_research(self, seed_keywords, location, language):
        self._maybe_fail()
        self.creates.append(("keyword_research", tuple(seed_keywords)))
        return {"_id": "kr-1", "status": "running"}

    def wait_keyword_research(self, kr_id, timeout=None):
        return self._complete(kr_id, keywords=[{
            "keyword": "kw",
            "stats": {"keyword_data": {"keyword_info": {
                "search_volume": 50, "cpc": 1.0, "competition": 0.5}}},
        }])

    def create_ai_visibility_audit(self, business_name, website_url,
                                   site_type, location=None):
        self._maybe_fail()
        self.creates.append(("ai_visibility", business_name))
        return {"_id": "ai-1", "status": "running"}

    def wait_ai_visibility_audit(self, audit_id, timeout=None):
        return self._complete(audit_id, score=80, recommendations=[])

    def get_ai_visibility_audit(self, audit_id):
        return self.wait_ai_visibility_audit(audit_id)

    def locations_languages(self):
        return [{"code": 1, "name": "United States"}]


class EnforcementE2ETest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls._db_patch = mock.patch.object(
            config, "DB_PATH", cls.tmp.name + "/e2e.db")
        cls._db_patch.start()
        cls._token_patch = mock.patch.object(
            config, "ADMIN_TOKEN", ADMIN_TOKEN)
        cls._token_patch.start()
        cls.fake = FakeSerpslingClient()
        cls._client_patch = mock.patch.object(
            tools_impl, "get_client", lambda: cls.fake)
        cls._client_patch.start()

        from app.server import app  # noqa: E402  (import after patches)
        import uvicorn  # noqa: E402

        cls.port = _free_port()
        cls.base = f"http://127.0.0.1:{cls.port}"
        uv_config = uvicorn.Config(
            app, host="127.0.0.1", port=cls.port, log_level="error")
        cls.uv_server = uvicorn.Server(uv_config)
        cls.thread = threading.Thread(target=cls.uv_server.run, daemon=True)
        cls.thread.start()
        deadline = time.time() + 20
        while time.time() < deadline:
            try:
                resp = httpx.get(f"{cls.base}/health", timeout=2,
                                 trust_env=False)
                if resp.status_code == 200:
                    break
            except httpx.HTTPError:
                time.sleep(0.2)
        else:
            raise RuntimeError("test server did not come up")

    @classmethod
    def tearDownClass(cls):
        cls.uv_server.should_exit = True
        cls.thread.join(timeout=10)
        cls._client_patch.stop()
        cls._token_patch.stop()
        cls._db_patch.stop()
        cls.tmp.cleanup()

    def setUp(self):
        self.fake.fail_next_create = False
        self.fake.creates.clear()
        self.fake.site_audit_pages.clear()

    # ------------------------------------------------------------ helpers
    def _new_buyer(self, credits=0):
        name = f"e2e-{uuid.uuid4().hex[:8]}"
        key = store.create_key(name, credits=credits)
        return name, key

    def _http(self):
        return httpx.Client(base_url=self.base, timeout=10, trust_env=False)

    def _mcp_call(self, key, tool, args):
        """Call one MCP tool over real HTTP with a real SDK client."""
        async def run():
            import httpx2
            from mcp import ClientSession
            from mcp.client.streamable_http import streamable_http_client

            headers = {"Authorization": f"Bearer {key}"}
            async with httpx2.AsyncClient(
                    headers=headers, trust_env=False,
                    timeout=30.0) as http_client:
                async with streamable_http_client(
                        f"{self.base}/mcp",
                        http_client=http_client) as (read, write):
                    async with ClientSession(read, write) as session:
                        await session.initialize()
                        return await session.call_tool(tool, args)

        return asyncio.run(run())

    @staticmethod
    def _text(result):
        return "".join(
            c.text for c in result.content if hasattr(c, "text"))

    # ------------------------------------------------------------ HTTP layer
    def test_health_ok(self):
        with self._http() as http:
            self.assertEqual(http.get("/health").status_code, 200)

    def test_mcp_requires_bearer_key(self):
        with self._http() as http:
            self.assertEqual(http.post("/mcp", json={}).status_code, 401)
            bad = http.post("/mcp", json={},
                            headers={"Authorization": "Bearer nope"})
            self.assertEqual(bad.status_code, 401)

    def test_admin_balance_header_guard(self):
        name, _ = self._new_buyer(credits=7)
        with self._http() as http:
            no_header = http.get("/admin/balance", params={"buyer": name})
            self.assertEqual(no_header.status_code, 403)
            wrong = http.get("/admin/balance", params={"buyer": name},
                             headers={"X-Admin-Token": "wrong"})
            self.assertEqual(wrong.status_code, 403)
            # Query ?token= must NOT work on the new header-only endpoints.
            query = http.get("/admin/balance",
                             params={"buyer": name, "token": ADMIN_TOKEN})
            self.assertEqual(query.status_code, 403)
            unknown = http.get("/admin/balance", params={"buyer": "ghost"},
                               headers={"X-Admin-Token": ADMIN_TOKEN})
            self.assertEqual(unknown.status_code, 404)
            ok = http.get("/admin/balance", params={"buyer": name},
                          headers={"X-Admin-Token": ADMIN_TOKEN})
            self.assertEqual(ok.status_code, 200)
            self.assertEqual(ok.json()["credits"], 7)

    def test_admin_grant_endpoint(self):
        name, _ = self._new_buyer()
        with self._http() as http:
            no_header = http.post("/admin/grant",
                                  json={"buyer": name, "credits": 10})
            self.assertEqual(no_header.status_code, 403)
            headers = {"X-Admin-Token": ADMIN_TOKEN}
            bad_body = http.post("/admin/grant", json={"buyer": name},
                                 headers=headers)
            self.assertEqual(bad_body.status_code, 400)
            zero = http.post("/admin/grant",
                             json={"buyer": name, "credits": 0},
                             headers=headers)
            self.assertEqual(zero.status_code, 400)
            unknown = http.post("/admin/grant",
                                json={"buyer": "ghost", "credits": 10},
                                headers=headers)
            self.assertEqual(unknown.status_code, 404)
            ok = http.post("/admin/grant",
                           json={"buyer": name, "credits": 30},
                           headers=headers)
            self.assertEqual(ok.status_code, 200)
            self.assertEqual(ok.json()["credits"], 30)
        self.assertEqual(store.get_balance(name), 30)

    def test_old_query_token_admin_endpoints_still_work(self):
        self._new_buyer(credits=3)
        with self._http() as http:
            resp = http.get("/admin/buyers", params={"token": ADMIN_TOKEN})
            self.assertEqual(resp.status_code, 200)
            self.assertTrue(any(b["credits"] == 3
                                for b in resp.json()["buyers"]))
            usage = http.get("/admin/usage", params={"token": ADMIN_TOKEN})
            self.assertEqual(usage.status_code, 200)

    # ------------------------------------------------------------ enforcement
    def test_paid_tool_insufficient_balance(self):
        name, key = self._new_buyer(credits=0)
        result = self._mcp_call(key, "competition_analysis", {
            "target": "example.com", "location": 1, "language": "en"})
        self.assertTrue(result.is_error)
        self.assertIn("insufficient credits: this call costs 10, "
                      "balance is 0", self._text(result))
        self.assertEqual(store.get_balance(name), 0)
        self.assertEqual(store.usage_summary(name), [])
        self.assertEqual(self.fake.creates, [])  # provider never called

    def test_paid_tool_success_deducts_and_logs(self):
        name, key = self._new_buyer(credits=10)
        result = self._mcp_call(key, "competition_analysis", {
            "target": "example.com", "location": 1, "language": "en"})
        self.assertFalse(result.is_error)
        self.assertIn("test kw", self._text(result))
        self.assertEqual(store.get_balance(name), 0)
        usage = store.usage_summary(name)
        self.assertEqual(len(usage), 1)
        self.assertEqual(usage[0]["tool"], "competition")
        self.assertEqual(usage[0]["credits"], 10)

    def test_backlink_costs_10(self):
        name, key = self._new_buyer(credits=25)
        result = self._mcp_call(key, "backlink_analysis",
                                {"target": "example.com"})
        self.assertFalse(result.is_error)
        self.assertEqual(store.get_balance(name), 15)

    def test_free_tool_ignores_zero_balance(self):
        name, key = self._new_buyer(credits=0)
        result = self._mcp_call(key, "keyword_research", {
            "seed_keywords": ["kw"], "location": 1, "language": "en"})
        self.assertFalse(result.is_error)
        self.assertEqual(store.get_balance(name), 0)

    def test_free_status_and_locations_unaffected(self):
        _, key = self._new_buyer(credits=0)
        status = self._mcp_call(key, "get_analysis_status",
                                {"kind": "competition",
                                 "analysis_id": "comp-1"})
        self.assertFalse(status.is_error)
        locs = self._mcp_call(key, "locations", {})
        self.assertFalse(locs.is_error)

    def test_refund_on_provider_failure(self):
        name, key = self._new_buyer(credits=10)
        self.fake.fail_next_create = True
        result = self._mcp_call(key, "competition_analysis", {
            "target": "example.com", "location": 1, "language": "en"})
        self.assertTrue(result.is_error)
        # Provider crashes surface as the SDK's generic tool error (the
        # raw upstream text is deliberately not forwarded to buyers).
        self.assertIn("Error executing tool competition_analysis",
                      self._text(result))
        self.assertEqual(store.get_balance(name), 10)  # fully refunded
        self.assertEqual(store.usage_summary(name), [])

    def test_site_audit_clamps_to_100_pages(self):
        name, key = self._new_buyer(credits=100)
        result = self._mcp_call(key, "site_audit",
                                {"target": "example.com",
                                 "page_limit": 500})
        self.assertFalse(result.is_error)
        self.assertEqual(self.fake.site_audit_pages, [100])
        self.assertEqual(store.get_balance(name), 0)
        usage = store.usage_summary(name)
        self.assertEqual(usage[0]["tool"], "site_audit")
        self.assertEqual(usage[0]["credits"], 100)

    def test_site_audit_insufficient_for_requested_pages(self):
        name, key = self._new_buyer(credits=5)
        result = self._mcp_call(key, "site_audit",
                                {"target": "example.com",
                                 "page_limit": 20})
        self.assertTrue(result.is_error)
        self.assertIn("insufficient credits: this call costs 20, "
                      "balance is 5", self._text(result))
        self.assertEqual(store.get_balance(name), 5)
        self.assertEqual(self.fake.site_audit_pages, [])

    def test_site_audit_refund_on_provider_failure(self):
        name, key = self._new_buyer(credits=20)
        self.fake.fail_next_create = True
        result = self._mcp_call(key, "site_audit",
                                {"target": "example.com",
                                 "page_limit": 20})
        self.assertTrue(result.is_error)
        self.assertEqual(store.get_balance(name), 20)
        self.assertEqual(store.usage_summary(name), [])


if __name__ == "__main__":
    unittest.main()

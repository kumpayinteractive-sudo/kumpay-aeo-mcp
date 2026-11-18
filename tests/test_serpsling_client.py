"""Serpsling client: buyer-supplied ids must never escape their endpoint.

Regression tests for the path-traversal hole in the pre-fix getters: an
analysis id such as "../../private/credits" was interpolated raw into the
request URL, and httpx normalizes dot segments, so a buyer could reach
other provider endpoints (e.g. the shared pool balance) through
get_analysis_status. Ids are now percent-encoded (same as the sibling
Django client).

Run:  .venv/bin/python -m unittest discover -s tests -v
"""
import unittest

from app.serpsling import SerpslingClient


class _FakeResponse:
    def __init__(self, url):
        self.status_code = 200
        self._url = url

    def json(self):
        return {"status": "complete", "_id": "x", "echo_url": self._url}


class _CapturingTransport:
    """Stands in for httpx.Client: records the requested URL, returns ok."""

    def __init__(self):
        self.urls = []

    def request(self, method, url, json=None):
        self.urls.append(str(url))
        return _FakeResponse(str(url))


class TestIdQuoting(unittest.TestCase):
    def _client(self):
        client = SerpslingClient(auth_key="test-key",
                                 base_url="https://api.test.invalid")
        client._client = _CapturingTransport()
        return client

    def test_normal_ids_pass_through_unchanged(self):
        client = self._client()
        client.get_competition_analysis("507f1f77bcf86cd799439011")
        client.get_keyword_research("abc123")
        self.assertEqual(
            client._client.urls[0],
            "https://api.test.invalid/private/competition_analysis/"
            "507f1f77bcf86cd799439011")
        self.assertEqual(
            client._client.urls[1],
            "https://api.test.invalid/private/keyword_research/abc123")

    def test_traversal_ids_are_percent_encoded(self):
        client = self._client()
        client.get_competition_analysis("../../private/credits")
        client.get_backlink_analysis("../../../private/auth")
        client.get_site_audit("..%2f..%2fprivate%2fcredits")
        client.get_ai_visibility_audit("x/../../private/credits")
        client.get_keyword_research("../../private/credits")
        expected_prefixes = [
            "https://api.test.invalid/private/competition_analysis/",
            "https://api.test.invalid/private/backlink_analysis/",
            "https://api.test.invalid/private/site_audit/",
            "https://api.test.invalid/private/ai_visibility_audit/",
            "https://api.test.invalid/private/keyword_research/",
        ]
        for url, prefix in zip(client._client.urls, expected_prefixes):
            # The id must stay one encoded path segment under its own
            # endpoint: no dot segment may survive to be normalized away.
            self.assertTrue(url.startswith(prefix), url)
            self.assertNotIn("/../", url,
                             f"dot segment survived in {url}")
            self.assertFalse(url.endswith("/.."),
                             f"dot segment survived in {url}")
        self.assertTrue(
            client._client.urls[0].endswith(
                "/private/competition_analysis/..%2F..%2Fprivate%2Fcredits"),
            client._client.urls[0])

    def test_slashes_and_query_chars_are_encoded(self):
        client = self._client()
        client.get_site_audit("a/b?c=d&e=f#frag")
        url = client._client.urls[0]
        self.assertTrue(
            url.endswith("/private/site_audit/a%2Fb%3Fc%3Dd%26e%3Df%23frag"),
            url)


if __name__ == "__main__":
    unittest.main()

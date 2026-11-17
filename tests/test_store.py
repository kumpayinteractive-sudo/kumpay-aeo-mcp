"""Unit tests for app.store: keys, balances, reserve/refund, migration.

Run:  .venv/bin/python -m unittest discover -s tests -v
All tests use a temporary SQLite DB; the repo's data/mcp.db is untouched.
"""
import io
import sqlite3
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest import mock

from app import config, store

OLD_BUYERS_SCHEMA = """
CREATE TABLE buyers (
    id INTEGER PRIMARY KEY,
    name TEXT UNIQUE NOT NULL,
    key_hash TEXT NOT NULL,
    key_prefix TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 1,
    created_at INTEGER NOT NULL
);
CREATE TABLE usage (
    id INTEGER PRIMARY KEY,
    buyer_name TEXT NOT NULL,
    tool TEXT NOT NULL,
    credits INTEGER NOT NULL,
    detail TEXT,
    created_at INTEGER NOT NULL
);
"""


class StoreTestBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        patch = mock.patch.object(
            config, "DB_PATH", self.tmp.name + "/test.db")
        patch.start()
        self.addCleanup(patch.stop)


class TestCreateAndBalance(StoreTestBase):
    def test_new_buyer_starts_at_zero(self):
        store.create_key("acme")
        self.assertEqual(store.get_balance("acme"), 0)

    def test_create_key_with_initial_credits(self):
        store.create_key("acme", credits=100)
        self.assertEqual(store.get_balance("acme"), 100)

    def test_create_key_negative_credits_raises(self):
        with self.assertRaises(ValueError):
            store.create_key("acme", credits=-1)

    def test_create_duplicate_name_raises(self):
        store.create_key("acme")
        with self.assertRaises(SystemExit):
            store.create_key("acme")

    def test_get_balance_unknown_buyer_is_none(self):
        self.assertIsNone(store.get_balance("ghost"))


class TestGrant(StoreTestBase):
    def test_grant_adds_and_returns_new_balance(self):
        store.create_key("acme")
        self.assertEqual(store.grant_credits("acme", 100), 100)
        self.assertEqual(store.grant_credits("acme", 50), 150)
        self.assertEqual(store.get_balance("acme"), 150)

    def test_grant_unknown_buyer_raises(self):
        with self.assertRaises(ValueError):
            store.grant_credits("ghost", 10)

    def test_grant_non_positive_raises(self):
        store.create_key("acme")
        with self.assertRaises(ValueError):
            store.grant_credits("acme", 0)
        with self.assertRaises(ValueError):
            store.grant_credits("acme", -5)
        self.assertEqual(store.get_balance("acme"), 0)


class TestReserveRefund(StoreTestBase):
    def test_reserve_success_deducts(self):
        store.create_key("acme", credits=25)
        self.assertTrue(store.reserve_credits("acme", 10))
        self.assertEqual(store.get_balance("acme"), 15)

    def test_reserve_insufficient_returns_false_balance_unchanged(self):
        store.create_key("acme", credits=3)
        self.assertFalse(store.reserve_credits("acme", 10))
        self.assertEqual(store.get_balance("acme"), 3)

    def test_reserve_exact_balance_then_empty(self):
        store.create_key("acme", credits=10)
        self.assertTrue(store.reserve_credits("acme", 10))
        self.assertEqual(store.get_balance("acme"), 0)
        self.assertFalse(store.reserve_credits("acme", 1))
        self.assertEqual(store.get_balance("acme"), 0)

    def test_reserve_zero_cost_is_noop_success(self):
        store.create_key("acme")
        self.assertTrue(store.reserve_credits("acme", 0))
        self.assertEqual(store.get_balance("acme"), 0)

    def test_reserve_unknown_buyer_false(self):
        self.assertFalse(store.reserve_credits("ghost", 10))

    def test_refund_restores_in_full(self):
        store.create_key("acme", credits=25)
        store.reserve_credits("acme", 10)
        store.refund_credits("acme", 10)
        self.assertEqual(store.get_balance("acme"), 25)

    def test_refund_zero_is_noop(self):
        store.create_key("acme", credits=5)
        store.refund_credits("acme", 0)
        self.assertEqual(store.get_balance("acme"), 5)

    def test_balance_never_goes_negative(self):
        store.create_key("acme", credits=7)
        for _ in range(5):
            store.reserve_credits("acme", 3)
        self.assertEqual(store.get_balance("acme"), 1)
        self.assertFalse(store.reserve_credits("acme", 2))
        self.assertEqual(store.get_balance("acme"), 1)


class TestMigration(StoreTestBase):
    def _build_old_db(self, buyer="legacy"):
        path = self.tmp.name + "/old.db"
        conn = sqlite3.connect(path)
        conn.executescript(OLD_BUYERS_SCHEMA)
        conn.execute(
            "INSERT INTO buyers (name, key_hash, key_prefix, created_at)"
            " VALUES (?, 'hash', 'prefix', 1)", (buyer,))
        conn.commit()
        conn.close()
        return path

    def test_old_schema_gets_credits_column_default_zero(self):
        path = self._build_old_db()
        with mock.patch.object(config, "DB_PATH", path):
            self.assertEqual(store.get_balance("legacy"), 0)
            conn = sqlite3.connect(path)
            cols = {r[1] for r in conn.execute("PRAGMA table_info(buyers)")}
            conn.close()
        self.assertIn("credits", cols)

    def test_old_schema_buyer_can_grant_and_reserve(self):
        path = self._build_old_db()
        with mock.patch.object(config, "DB_PATH", path):
            self.assertFalse(store.reserve_credits("legacy", 1))
            self.assertEqual(store.grant_credits("legacy", 10), 10)
            self.assertTrue(store.reserve_credits("legacy", 10))
            self.assertEqual(store.get_balance("legacy"), 0)

    def test_migration_is_idempotent(self):
        path = self._build_old_db()
        with mock.patch.object(config, "DB_PATH", path):
            for _ in range(3):
                self.assertEqual(store.get_balance("legacy"), 0)
            self.assertEqual(store.grant_credits("legacy", 5), 5)


class TestListKeys(StoreTestBase):
    def test_list_keys_includes_credits(self):
        store.create_key("a", credits=10)
        store.create_key("b")
        rows = {r["name"]: r for r in store.list_keys()}
        self.assertEqual(rows["a"]["credits"], 10)
        self.assertEqual(rows["b"]["credits"], 0)


class TestCLI(StoreTestBase):
    def _run(self, argv):
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = store.main(argv)
        return code, buf.getvalue()

    def test_cli_grant_and_balance(self):
        store.create_key("acme")
        code, out = self._run(["grant", "--name", "acme", "--credits", "40"])
        self.assertEqual(code, 0)
        self.assertIn("40 credits", out)
        code, out = self._run(["balance", "--name", "acme"])
        self.assertEqual(code, 0)
        self.assertIn("40 credits", out)

    def test_cli_grant_unknown_buyer_fails(self):
        code, out = self._run(["grant", "--name", "ghost", "--credits", "5"])
        self.assertEqual(code, 1)
        self.assertIn("not found", out)

    def test_cli_balance_unknown_buyer(self):
        code, out = self._run(["balance", "--name", "ghost"])
        self.assertEqual(code, 0)
        self.assertIn("not found", out)

    def test_cli_create_key_with_credits(self):
        code, out = self._run(
            ["create-key", "--name", "acme", "--credits", "100"])
        self.assertEqual(code, 0)
        self.assertIn("100", out)
        self.assertEqual(store.get_balance("acme"), 100)


if __name__ == "__main__":
    unittest.main()

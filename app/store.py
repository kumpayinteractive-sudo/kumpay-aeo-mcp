"""Buyer key management + credit-usage ledger (SQLite).

Keys are stored as sha256(pepper + key); raw keys are shown once at creation.
Balances live in the buyers.credits column (added by migration on old DBs).
Paid tools reserve credits BEFORE the provider call and refund in full if
the provider call fails, so a buyer is only charged for accepted work.
Run as a CLI:
    python -m app.store create-key --name "acme" [--credits 100]
    python -m app.store list-keys
    python -m app.store revoke --name "acme"
    python -m app.store usage [--name "acme"]
    python -m app.store grant --name "acme" --credits 100
    python -m app.store balance --name "acme"
"""
from __future__ import annotations

import argparse
import hashlib
import secrets
import sqlite3
import sys
import time
from pathlib import Path

from mcp.server.mcpserver.exceptions import ToolError

from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS buyers (
    id INTEGER PRIMARY KEY,
    name TEXT UNIQUE NOT NULL,
    key_hash TEXT NOT NULL,
    key_prefix TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 1,
    credits INTEGER NOT NULL DEFAULT 0,
    created_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS usage (
    id INTEGER PRIMARY KEY,
    buyer_name TEXT NOT NULL,
    tool TEXT NOT NULL,
    credits INTEGER NOT NULL,
    detail TEXT,
    created_at INTEGER NOT NULL
);
"""


def _migrate(conn: sqlite3.Connection) -> None:
    """Additive migrations for DBs created before a schema change.

    Safe to run on every connection: only ALTERs when the column is
    missing, and tolerates a concurrent first-boot ALTER from another
    thread (duplicate-column error is ignored).
    """
    cols = {r[1] for r in conn.execute("PRAGMA table_info(buyers)")}
    if "credits" not in cols:
        try:
            conn.execute(
                "ALTER TABLE buyers ADD COLUMN credits"
                " INTEGER NOT NULL DEFAULT 0")
            conn.commit()
        except sqlite3.OperationalError as e:
            if "duplicate column" not in str(e).lower():
                raise


def _db() -> sqlite3.Connection:
    Path(config.DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(config.DB_PATH)
    conn.executescript(SCHEMA)
    _migrate(conn)
    return conn


class InsufficientCreditsError(ToolError):
    """Raised when a buyer cannot cover a paid tool call.

    Subclasses the SDK's ToolError (an *anticipated* failure), so the
    client receives is_error=True WITH this message in content. A plain
    exception would reach the buyer only as the generic
    "Error executing tool <name>".
    """

    def __init__(self, cost: int, balance: int):
        self.cost = cost
        self.balance = balance
        super().__init__(
            f"insufficient credits: this call costs {cost}, "
            f"balance is {balance}")


def _hash(raw: str) -> str:
    return hashlib.sha256((config.KEY_PEPPER + raw).encode()).hexdigest()


def create_key(name: str, credits: int = 0) -> str:
    """Create a buyer key. New buyers start at 0 unless `credits` is given
    (e.g. a pack bought before the key exists). Never auto-grants."""
    if credits < 0:
        raise ValueError("credits must be >= 0")
    raw = "sk_mcp_" + secrets.token_urlsafe(24)
    conn = _db()
    try:
        conn.execute(
            "INSERT INTO buyers (name, key_hash, key_prefix, credits,"
            " created_at) VALUES (?, ?, ?, ?, ?)",
            (name, _hash(raw), raw[:12], credits, int(time.time())),
        )
        conn.commit()
    except sqlite3.IntegrityError:
        raise SystemExit(f"buyer '{name}' already exists")
    finally:
        conn.close()
    return raw


def resolve_buyer(raw: str) -> str | None:
    """Return buyer name for a valid active key, else None."""
    conn = _db()
    try:
        row = conn.execute(
            "SELECT name, active FROM buyers WHERE key_hash = ?",
            (_hash(raw),),
        ).fetchone()
    finally:
        conn.close()
    if row and row[1]:
        return row[0]
    return None


def get_balance(name: str) -> int | None:
    """Current credit balance, or None if the buyer does not exist."""
    conn = _db()
    try:
        row = conn.execute(
            "SELECT credits FROM buyers WHERE name = ?", (name,)).fetchone()
    finally:
        conn.close()
    return row[0] if row else None


def grant_credits(name: str, credits: int) -> int:
    """Add credits to a buyer (pack purchase). Returns the new balance."""
    if credits <= 0:
        raise ValueError("credits must be a positive integer")
    conn = _db()
    try:
        cur = conn.execute(
            "UPDATE buyers SET credits = credits + ? WHERE name = ?",
            (credits, name))
        if cur.rowcount == 0:
            raise ValueError(f"buyer '{name}' not found")
        conn.commit()
        row = conn.execute(
            "SELECT credits FROM buyers WHERE name = ?", (name,)).fetchone()
    finally:
        conn.close()
    return row[0]


def reserve_credits(name: str, cost: int) -> bool:
    """Atomically deduct `cost` if the balance covers it.

    Single conditional UPDATE: rowcount 1 means reserved, 0 means
    insufficient (or unknown buyer). The balance can never go negative.
    Zero-cost calls are a no-op and always succeed.
    """
    if cost <= 0:
        return True
    conn = _db()
    try:
        cur = conn.execute(
            "UPDATE buyers SET credits = credits - ?"
            " WHERE name = ? AND credits >= ?",
            (cost, name, cost))
        conn.commit()
        return cur.rowcount == 1
    finally:
        conn.close()


def refund_credits(name: str, cost: int) -> None:
    """Return a reservation in full (provider call failed)."""
    if cost <= 0:
        return
    conn = _db()
    try:
        conn.execute(
            "UPDATE buyers SET credits = credits + ? WHERE name = ?",
            (cost, name))
        conn.commit()
    finally:
        conn.close()


def revoke(name: str) -> bool:
    conn = _db()
    try:
        cur = conn.execute(
            "UPDATE buyers SET active = 0 WHERE name = ?", (name,))
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def list_keys() -> list[dict]:
    conn = _db()
    try:
        rows = conn.execute(
            "SELECT name, key_prefix, active, created_at, credits FROM buyers"
            " ORDER BY created_at").fetchall()
    finally:
        conn.close()
    return [{"name": r[0], "prefix": r[1], "active": bool(r[2]),
             "created": r[3], "credits": r[4]} for r in rows]


def log_usage(buyer: str, tool: str, credits: int, detail: str = "") -> None:
    conn = _db()
    try:
        conn.execute(
            "INSERT INTO usage (buyer_name, tool, credits, detail, created_at)"
            " VALUES (?, ?, ?, ?, ?)",
            (buyer, tool, credits, detail[:500], int(time.time())),
        )
        conn.commit()
    finally:
        conn.close()


def usage_summary(name: str | None = None) -> list[dict]:
    conn = _db()
    try:
        if name:
            rows = conn.execute(
                "SELECT buyer_name, tool, SUM(credits), COUNT(*) FROM usage"
                " WHERE buyer_name = ? GROUP BY buyer_name, tool",
                (name,)).fetchall()
        else:
            rows = conn.execute(
                "SELECT buyer_name, tool, SUM(credits), COUNT(*) FROM usage"
                " GROUP BY buyer_name, tool").fetchall()
    finally:
        conn.close()
    return [{"buyer": r[0], "tool": r[1], "credits": r[2], "calls": r[3]}
            for r in rows]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("create-key"); p.add_argument("--name", required=True)
    p.add_argument("--credits", type=int, default=0)
    sub.add_parser("list-keys")
    p = sub.add_parser("revoke"); p.add_argument("--name", required=True)
    p = sub.add_parser("usage"); p.add_argument("--name", default=None)
    p = sub.add_parser("grant"); p.add_argument("--name", required=True)
    p.add_argument("--credits", type=int, required=True)
    p = sub.add_parser("balance"); p.add_argument("--name", required=True)
    args = ap.parse_args(argv)

    if args.cmd == "create-key":
        try:
            raw = create_key(args.name, args.credits)
        except ValueError as e:
            print(e)
            return 1
        print(f"buyer: {args.name}\nkey:   {raw}\n"
              f"credits: {args.credits}\n"
              "Save this key now -- it is never shown again.")
    elif args.cmd == "list-keys":
        for k in list_keys():
            print(k)
    elif args.cmd == "revoke":
        print("revoked" if revoke(args.name) else "not found")
    elif args.cmd == "usage":
        for u in usage_summary(args.name):
            print(u)
    elif args.cmd == "grant":
        try:
            new = grant_credits(args.name, args.credits)
        except ValueError as e:
            print(e)
            return 1
        print(f"{args.name}: {new} credits")
    elif args.cmd == "balance":
        bal = get_balance(args.name)
        if bal is None:
            print("not found")
        else:
            print(f"{args.name}: {bal} credits")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

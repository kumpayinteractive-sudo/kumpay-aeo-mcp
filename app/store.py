"""Buyer key management + credit-usage ledger (SQLite).

Keys are stored as sha256(pepper + key); raw keys are shown once at creation.
Run as a CLI:
    python -m app.store create-key --name "acme"
    python -m app.store list-keys
    python -m app.store revoke --name "acme"
    python -m app.store usage [--name "acme"]
"""
from __future__ import annotations

import argparse
import hashlib
import secrets
import sqlite3
import sys
import time
from pathlib import Path

from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS buyers (
    id INTEGER PRIMARY KEY,
    name TEXT UNIQUE NOT NULL,
    key_hash TEXT NOT NULL,
    key_prefix TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 1,
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


def _db() -> sqlite3.Connection:
    Path(config.DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(config.DB_PATH)
    conn.executescript(SCHEMA)
    return conn


def _hash(raw: str) -> str:
    return hashlib.sha256((config.KEY_PEPPER + raw).encode()).hexdigest()


def create_key(name: str) -> str:
    raw = "sk_mcp_" + secrets.token_urlsafe(24)
    conn = _db()
    try:
        conn.execute(
            "INSERT INTO buyers (name, key_hash, key_prefix, created_at)"
            " VALUES (?, ?, ?, ?)",
            (name, _hash(raw), raw[:12], int(time.time())),
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
            "SELECT name, key_prefix, active, created_at FROM buyers"
            " ORDER BY created_at").fetchall()
    finally:
        conn.close()
    return [{"name": r[0], "prefix": r[1], "active": bool(r[2]),
             "created": r[3]} for r in rows]


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
    sub.add_parser("list-keys")
    p = sub.add_parser("revoke"); p.add_argument("--name", required=True)
    p = sub.add_parser("usage"); p.add_argument("--name", default=None)
    args = ap.parse_args(argv)

    if args.cmd == "create-key":
        raw = create_key(args.name)
        print(f"buyer: {args.name}\nkey:   {raw}\n"
              "Save this key now -- it is never shown again.")
    elif args.cmd == "list-keys":
        for k in list_keys():
            print(k)
    elif args.cmd == "revoke":
        print("revoked" if revoke(args.name) else "not found")
    elif args.cmd == "usage":
        for u in usage_summary(args.name):
            print(u)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

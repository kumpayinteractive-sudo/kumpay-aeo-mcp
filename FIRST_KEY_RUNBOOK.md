# First Buyer Key Runbook — Kumpay AEO MCP

Credit enforcement is live: every buyer key has a balance, paid tools
reserve credits **before** calling the provider and refund in full if the
provider call fails. Keys start at **0 credits** — nothing is auto-granted.

## Costs (per tool call)

| Tool | Cost |
|---|---|
| competition_analysis | 10 flat |
| backlink_analysis | 10 flat |
| site_audit | 1 per page requested (default 20, max 100, clamped server-side) |
| keyword_research | 0 |
| ai_visibility_audit | 0 |
| get_analysis_status | 0 |
| locations | 0 |

Credit packs (Whop, one-time, never expire): Starter $29 = **100** credits,
Growth $79 = **300**, Scale $199 = **1,000**.

All `python -m app.store ...` commands run in the **Coolify Terminal** for
the mcp app (shell starts in `/app`). `ADMIN_TOKEN` is in the app's
Environment Variables in Coolify — copy it from there, never paste it in chat.

## Step 0 — Confirm the new code is live

```bash
curl -s -o /dev/null -w "%{http_code}\n" \
  "https://mcp.kumpaytech.com/admin/balance?buyer=probe"
```

- `403` = new code is live (it refused you for having no token — correct).
- `404` = old code is still serving. Redeploy in Coolify first, then retry.

## Step 1 — DO THIS FIRST: persistence check (before any real key)

The database lives at `/app/data/mcp.db` inside the container. If Coolify
wipes it on redeploy, keys AND balances are destroyed. Prove it survives:

```bash
python -m app.store create-key --name persistence-test
python -m app.store grant --name persistence-test --credits 5
python -m app.store balance --name persistence-test   # expect: 5 credits
```

Now redeploy the app in Coolify (Deploy button), wait for it to come back,
then in the Terminal again:

```bash
python -m app.store balance --name persistence-test
```

- Still `5 credits` = persistence OK. Clean up:
  `python -m app.store revoke --name persistence-test`
- `not found` = the DB was wiped on redeploy. **STOP — do not issue a real
  key yet.** In Coolify, add a persistent volume for `/app/data` on the
  mcp app, redeploy, and repeat this check until the balance survives.

## Step 2 — Issue a key (after a Whop purchase)

1. Buyer emails their receipt to kumpaytech@gmail.com. Verify the payment
   in Whop first — never issue a key on an unverified claim.
2. In the Coolify Terminal, create the key (use the buyer's name/handle):

```bash
python -m app.store create-key --name "buyer-name"
```

3. Grant the pack they bought (Starter 100 / Growth 300 / Scale 1000):

```bash
python -m app.store grant --name "buyer-name" --credits 100
python -m app.store balance --name "buyer-name"   # expect: 100 credits
```

4. Send the buyer their key (shown once at creation — it is never shown
   again) plus the setup line: set `KUMPAY_AEO_API_KEY` to the key in
   `~/.hermes/.env`, then install the `kumpay-aeo` plugin from the
   Hermes catalog.

## Step 3 — Verify enforcement works (test buyer, not a real key)

From any machine with curl. Replace `TESTKEY` with a test buyer's key
(create one with 0 credits first) and `ADMINTOKEN` with the ADMIN_TOKEN
from Coolify env vars.

```bash
BASE=https://mcp.kumpaytech.com
KEY=TESTKEY
ACC="Accept: application/json, text/event-stream"

# Open an MCP session (note: -L follows the /mcp redirect; the Accept
# header must list BOTH types or the server answers 406)
curl -s -L -D /tmp/h.txt -o /dev/null -X POST $BASE/mcp \
  -H "Authorization: Bearer $KEY" -H "Content-Type: application/json" \
  -H "$ACC" \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2026-07-28","capabilities":{},"clientInfo":{"name":"curl","version":"1.0"}}}'
SID=$(grep -i '^mcp-session-id:' /tmp/h.txt | tr -d '\r' | awk '{print $2}')

curl -s -L -o /dev/null -X POST $BASE/mcp \
  -H "Authorization: Bearer $KEY" -H "Mcp-Session-Id: $SID" \
  -H "Content-Type: application/json" -H "$ACC" \
  -d '{"jsonrpc":"2.0","method":"notifications/initialized"}'

# Paid call with 0 balance — expect isError:true and the text
# "insufficient credits: this call costs 10, balance is 0"
curl -s -L -X POST $BASE/mcp \
  -H "Authorization: Bearer $KEY" -H "Mcp-Session-Id: $SID" \
  -H "Content-Type: application/json" -H "$ACC" \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"competition_analysis","arguments":{"target":"example.com","location":1,"language":"en"}}}'

# Grant 10, then the same call must succeed and deduct
curl -s -X POST $BASE/admin/grant -H "X-Admin-Token: ADMINTOKEN" \
  -H "Content-Type: application/json" \
  -d '{"buyer":"test-buyer-name","credits":10}'

curl -s -L -X POST $BASE/mcp \
  -H "Authorization: Bearer $KEY" -H "Mcp-Session-Id: $SID" \
  -H "Content-Type: application/json" -H "$ACC" \
  -d '{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"competition_analysis","arguments":{"target":"example.com","location":1,"language":"en"}}}'

# Balance must now be 0 again
curl -s "$BASE/admin/balance?buyer=test-buyer-name" \
  -H "X-Admin-Token: ADMINTOKEN"
```

## Ongoing ops (Coolify Terminal)

```bash
python -m app.store balance --name "buyer-name"          # check balance
python -m app.store usage --name "buyer-name"            # per-tool spend
python -m app.store grant --name "buyer-name" --credits 100   # top-up
python -m app.store revoke --name "buyer-name"           # disable a key
python -m app.store list-keys                            # all buyers
```

HTTP equivalents (need the `X-Admin-Token` header — query `?token=` does
NOT work on these two endpoints):

```bash
curl -s "https://mcp.kumpaytech.com/admin/balance?buyer=buyer-name" \
  -H "X-Admin-Token: ADMINTOKEN"
curl -s -X POST https://mcp.kumpaytech.com/admin/grant \
  -H "X-Admin-Token: ADMINTOKEN" -H "Content-Type: application/json" \
  -d '{"buyer":"buyer-name","credits":100}'
```

## Rules

- Never issue a key before the buyer paid (verify in Whop first).
- Never share ADMIN_TOKEN or a buyer key in chat, screenshots, or email
  threads — keys go to the buyer only, once.
- A revoked key stops working immediately, but its balance stays on the
  record; re-granting to a revoked buyer does not reactivate it.
- If a buyer reports "insufficient credits" mid-work, check their balance
  and usage first — the error message already names the cost and balance.

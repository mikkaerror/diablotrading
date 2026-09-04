# Paper MTM OAuth Freshness

## Belief

An independent paper mark-to-market run must renew a near-expiry Schwab
market-data access token before requesting an option chain.

## Evidence

On 2026-09-01, the daily options tape was healthy at 11:51, but the paper
mark-to-market refresh at 12:03 used an expired token and received HTTP 401.
The refresh token remained valid. Adding the same read-only token-renewal
check used by daily ops produced a healthy DELL chain and mark at 12:15.

## Rule

- Mark-to-market may refresh only the ignored local OAuth token vault before a
  read-only option-chain request.
- Fixture and explicit token-override paths make no OAuth request.
- If renewal cannot succeed, do not poll with a known-stale token; publish the
  existing chain-unavailable diagnostic instead.
- Token renewal never changes a paper ticket, approval, risk setting, broker
  submit flag, or live-trading authority.

## Falsifier

If a current token produces a 401 after the renewal check, or a fresh token
does not restore a chain fetch, the root cause is no longer token expiry and
the provider response and endpoint contract need investigation.

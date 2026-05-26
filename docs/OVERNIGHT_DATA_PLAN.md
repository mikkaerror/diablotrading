# Overnight Data Plan

Purpose: make the overnight desk boring, repeatable, and clear about which data
source owns which decision. The goal is to run all math while the laptop is
quiet, then use thinkorswim only when the operator intentionally opens it.

## Source Authority

| Layer | Primary use | Authority | Notes |
|---|---|---|---|
| Schwab API | Options chains, bid/ask, Greeks, IV, open interest, expected move, approved-account balances and positions | Primary options market data plus account truth | Read-only lanes. OAuth/token refresh is local and ignored. Account sync persists only the approved suffix. No order endpoints. |
| thinkorswim | Visual review, manual trading, fills/watchlist/export evidence | Manual cockpit and supervised fallback | Must use the already-open app. Scripts should not launch new TOS windows. |
| Google Earnings Tracker | Universe, earnings timing, model scores, setup bias | Strategy source of truth | Morning jobs update and read this before briefs. |
| Local/yfinance artifacts | Fallback research and backtests | Fallback only | Useful when Schwab is unavailable; not preferred for final option quote quality. |

## Before-Bed Checklist

1. Leave normal automation alone. Keep these safe defaults unless you are
   intentionally supervising broker capture:

   ```bash
   TOS_EXPORT_AUTOMATION_ENABLED=0
   TOS_BACKGROUND_EXPORT_ALLOWED=0
   ```

2. If broker evidence is needed overnight, manually open the existing
   thinkorswim app and navigate to `Monitor > Account Statement`. Do not let a
   script open TOS.

3. Confirm TOS capture posture:

   ```bash
   python3 inferno_tos_export_stability.py --attempts 5
   ```

4. Confirm the full bedside readiness memo:

   ```bash
   python3 inferno_night_prep.py
   ```

5. Refresh Schwab options quality for the active shortlist:

   ```bash
   ./run_inferno_schwab_daily_ops.sh
   ```

6. Only when you are physically supervising TOS and want an export capture, run:

   ```bash
   ./run_inferno_desktop_automation.sh --export-first --require-tos-running
   ```

## Interpret The Night Prep Source Posture

- `schwabOptionsReady=true`: Schwab chain data exists and can enrich strike
  selection and risk checks.
- `schwabOptionsReady=false`: Schwab is unavailable or stale. Treat option
  quality as untrusted until the read-only tape refreshes.
- `tosCaptureReady=true`: the already-open TOS window is ready for read-only
  broker capture.
- `tosCaptureReady=false` with `overnightMathReady=true`: safe low-power mode.
  The desk can still update math, tracker evidence, backtests, and email briefs.
- Any `FAIL`: clear it before trusting the next unattended morning run.

## Safety Contract

- No live submit from the overnight diagnostics.
- No broker order endpoints from the Schwab adapters or daily ops tape.
- Schwab account reads are allowed only for the approved suffix and remain
  read-only.
- No new TOS instance opened by background jobs.
- Broker capture is useful evidence, not permission to trade.
- Final live orders still require explicit operator approval.

# Decision Checklists

These are the short lists you use when you do not want to think too much.

## Morning Checklist

1. Did the brief arrive?
2. Did `Inferno Doctor` report healthy?
3. Which names are in `Top Opportunities`?
4. Which names actually cleared the `Trade Gate Sanctum`?
5. Which names are in the `Accumulation Vault`?

## Earnings Trade Checklist

1. Is the ticker in the shortlist?
2. Did it clear the gates?
3. Is the trigger live?
4. Is the timing inside the real strike window?
5. Is the setup one you actually want to execute?
6. Can you explain the trade in one sentence?
7. Do you already know the fallback route?

If any answer is no, slow down.

## Long-Term Buy Checklist

1. Do I already believe in the company?
2. Would I still want it six to twelve months from now?
3. Is this a calmer entry, not a hotter one?
4. Is the lane saying `Accumulate` or at least `Nibble`?
5. Am I adding because it is better priced, not because I feel FOMO?

## Capital Deployment Checklist

1. Run `./run_inferno_capital_launch_check.sh --deployable-cash 1000`.
2. If the verdict is `blocked`, do not deploy fresh capital.
3. If the verdict is `manual-ready-with-warnings`, explicitly accept or clear every warning first.
4. Confirm the account suffix still matches local approved config.
5. Confirm auto live trading is still `False`.
6. Keep every order inside the printed allocator guardrails.
7. Can the trade survive being wrong without damaging the week?
8. Did you explicitly approve the final order before submit?

## Twice-Daily Action Pulse Checklist

1. Did the `Open Watch` email arrive before the 7:30 AM Mountain open?
2. Did the `Pre-Close Watch` email arrive before the 2:00 PM Mountain close?
3. If either pulse says `blocked`, do not deploy fresh capital.
4. If either pulse lists human decisions, resolve those before sizing anything new.
5. If the pulse says `manual-ready-with-warnings`, explicitly accept the warnings before acting.
6. Keep final trade entry manual and account-scoped to the approved suffix.

## Delivery And Capture Checklist

1. Did the morning brief arrive?
2. Did approval dispatch and approval inbox both report `ok=True`?
3. Did TOS export verifier confirm the already-open read-only window?
4. Did Downloads watch run after export?
5. Did fill ingest report zero unexpected unmatched rows?
6. Did the command center refresh after capture?

## End-Of-Day Checklist

1. Which names looked real before the open?
2. Which ones actually behaved that way?
3. Where did the desk save me from forcing action?
4. Did I override the system anywhere?
5. If I lost, was it a good loss or a sloppy loss?

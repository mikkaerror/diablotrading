# Simons / Renaissance Principles — Mapped to the Desk

Six philosophical primitives Renaissance has been consistent about for
35 years, and how each one shows up — or *should* show up — in this
codebase. Source threads: Zuckerman, *The Man Who Solved the Market*
(2019); the Acquired Renaissance Technologies episode (2021); Simons'
MIT and IAS public talks; multiple Berlekamp interviews.

The point of this doc is not to romanticise Renaissance. The point is
that a few of their cultural commitments map cleanly to safety rails
and audit rules on a much smaller desk, and naming the mapping makes
the rails harder to drift away from.

## 1. One model

> *At Renaissance, every researcher feeds signals into one combined
> model. No silos. Everyone runs the same map.*

**Our analogue.** `inferno_brain_console.py` + `reports/model_command_center_latest.txt`
are the desk's "one map." When the gates, the briefing, the audit, and
the artifacts disagree, the artifact-of-record wins (see
[`docs/PROJECT_STATUS.md`](PROJECT_STATUS.md): "If this doc disagrees
with those artifacts, the artifacts win"). The recurring temptation
is to maintain a private model in chat or in a scratch notebook; the
discipline is to commit it into the brain console or kill it.

## 2. Bad ideas are good, no ideas are terrible

> *Renaissance rewards exploring weak hypotheses. The worst sin is
> not trying.*

**Our analogue.** `inferno_hypothesis_lab.py` and the paper-bootstrap
slate exist for exactly this reason — they let candidate edges run as
shadow research without ever touching authority. The conviction audit
treats a *missing* bear bullet as the auditor's failure, not the
trade's cleanliness; this is the same posture inverted.

## 3. Shared compensation pool / no individual stars

> *Performance is attributed to the firm, not to people. There is no
> star quant whose departure breaks the system.*

**Our analogue.** Coordination notes (`coordination/model_notes.jsonl`)
and active missions (`coordination/active_missions.json`) deliberately
hide which model did which work behind a small surface — the desk
should keep working if Codex or Claude is offline for a day. The
five-doc anchor (`PROJECT_STATUS`, `MODEL_COLLABORATION_BRIEF`,
`MODEL_THEORY`, `MODULE_INDEX`, `ENGINEERING_CONVENTIONS`) is built
the same way: durable, not author-attributed.

## 4. Survival before growth

> *Simons: "Our job is to survive. If we're wrong, we can always add
> later." Renaissance enforces position limits, correlation caps, and
> tail-risk protection.*

**Our analogue.** This is the safety rails section of
[`MODEL_COLLABORATION_BRIEF.md`](MODEL_COLLABORATION_BRIEF.md): no
trades without confirmation; only the configured approved suffix is
approved; paper evidence gates promotion; broker submit OFF. The
audit's mandatory bear and pre-committed falsification triggers are
the same instinct at the per-trade level — never put on a position
without already knowing how it ends.

## 5. Models decay; re-validate continuously

> *What worked last year may not work next. Renaissance runs continuous
> regime tests and abandons signals that stop firing.*

**Our analogue.** `inferno_regime_drift.py` (two-sided CUSUM, MATH §12)
is the desk's own decay detector. `inferno_falsification_engine` /
`inferno_devils_advocate` are the falsification layer that keeps
claimed edges honest. The conviction audit's *first* universal
falsification trigger is "fold if the devil's-advocate verdict on the
active strategy flips to `edges-falsified` before the trade closes" —
this is the Simons principle in code.

## 6. Advantage must be real after costs

> *Backtest-pretty edges that don't survive transaction costs are not
> real edges. Test net of slippage, fees, and capacity.*

**Our analogue.** The desk's options-risk-budget cap and the
quarter-Kelly cap together set a hard ceiling on per-ticket risk; the
slippage check the auditor flags in research notes (§2.4) is the
single piece *not yet in code*. When the snapshot pipeline carries
bid-ask spreads, the audit will add a disagreement rule that fires
when round-trip spread exceeds a meaningful fraction of the implied
move.

---

## What this is *not*

This doc is not a transferable strategy. Medallion's specific edge —
high-frequency cross-sectional stat-arb across thousands of
instruments — is closed to outside money for a reason: capacity. The
strategy does not survive at our size, and our desk does not survive
at theirs. What transfers is the *posture*: small uncorrelated edges,
sized conservatively, continuously falsified, with survival as the
non-negotiable.

If a future feature ever conflicts with one of the six principles
above, the principle wins. If a principle ever conflicts with a
safety rail in [`MODEL_COLLABORATION_BRIEF.md`](MODEL_COLLABORATION_BRIEF.md),
the safety rail wins.

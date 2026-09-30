# W1 — exact-construction approval routing and dawn overlap

Status: deployed to the canonical Mac. Focused and full isolated CI checks pass; hosted branch CI passed run 36731019495. Canonical pre-delegate publication succeeded at 08:42:59 Mountain with unchanged decision/fill logs. Deployment receipts are recorded in the operating plan.

## Approval routing

The canonical Mac strike cycle now creates a separate approval item for every freshly evaluated paper construction it records: primary, cap-fit/rehearsal variant and defined-risk iron fly. Items expose strategy, maximum loss, family, event, source timestamp, ledger ticket ID and an exact-construction token. A priced alternate relegated to the shadow display can supply a cap-fit variant through the existing constructor; its original shadow primary is not staged. Answered-family and all other delegate rules still apply to the resulting strategy.

The identity binds ticker, event, strategy, expiration, full legs (including prices/quantities), debit/credit, maximum loss, family and arm. Only an identical construction retains its decision. Changed prices, legs or risk require a fresh decision. Scoped items require their token even when only one exists, preventing an old ticker-level card from approving a different structure. CLI, email replies and the API reject ambiguous ticker actions. `./inferno today` reads these exact candidates and passes their tokens. Legacy ticker decisions cannot make a different variant executable.

The delegate resolves each token to its matching canonical ledger candidate, using that candidate's source age and all entry blockers. Its `decide()` policy and constants are unchanged. Passed events are computed from the dated event instead of a frozen countdown. On the post-delegate cycle, the same construction receives only its own decision and reruns normal paper risk, liquidity, decision-card, process and exposure checks. A blocked, never-opened ticket can transition to staged under its original ID; opened, filled and closed records are preserved.

Morning refresh retains scoped decisions until canonical repricing replaces their candidates. Variant-pricing changes and routing upgrades invalidate the Mac staging cache. No additional automated approval path exists. The paper delegate remains the only delegated decider; no live/broker flag, risk constant or prereg rule changes.

The saved-tape replay used no live decisions and saved no canonical ledger or approval queue. At 08:32:39 Mountain, ACN's iron fly was held for spread/quote-quality and exposure blocks; APLD's iron fly was held for trigger and spread blocks. The historical $330 ACN spread had been superseded by a $400 priced candidate that failed the unchanged reward/risk and liquidity gates, so the existing cap-fit constructor did not admit it. This repair does not resurrect the old quote or promise a trade. The $330 versus $12,520 routing regression is also covered by deterministic fixtures.

## September 30 dawn evidence

Read-only Gmail and local audit review found:

| Mountain time | Receipt |
|---|---|
| 06:05:51 | ACN delegated rejection in `data/operator_decisions.csv` |
| 06:06:12 | Morning pipeline receipt in `reports/brief_log.jsonl` |
| 06:06:35 | VRT and ACN delegated rejections; ACN was processed twice |
| 06:06:40 | First Desk Editor email, without a canonical publication warning |
| 06:06:53 | Second Desk Editor email, with `Canonical sources changed during publication; retry snapshot` |

The two email receipts are Gmail messages `1a0f235b64e0b251` and `1a0f235e727fd0e6`. Gmail displays Pacific time; the table converts both to Mountain. The local mail-state `sentAt` of 06:05:50 is the invocation timestamp passed into the mailer, not SMTP delivery time.

This strongly supports the same overlapping dawn/mailer execution as the cause. The publisher takes source hashes, uploads immutable objects, then compares current source hashes before publishing the pointer. Another invocation advancing approval decisions while publication was in flight would trigger precisely this refusal. The historical error lacks changed-file and process IDs, so it cannot prove which writer changed which source. It was a rejected inconsistent publication, not evidence that a mixed snapshot was published.

Claude's mailer lock now covers the pipeline and delivery. The existing Mac cycle lock plus durable bounded publication retry/backoff remains in place. Later successful publications are recorded locally, including 07:47:47 and 08:08:14; unchanged retries do not replay staging. No additional email was sent during this investigation.

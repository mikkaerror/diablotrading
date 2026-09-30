"""Read-only measurement audit. Observations are not authority or proof of edge."""
from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from datetime import date
from pathlib import Path
from typing import Any

from inferno_config import local_now
from inferno_io import atomic_write_json, atomic_write_text
from inferno_paper_provenance import load_fill_source
from inferno_paper_funnel import weekly_funnel
from inferno_research_records import shadow_records
from inferno_strategy_lab import closed_trade_records
from server import DATA_DIR, REPORTS_DIR

RESEARCH_AUDIT_STAGE = 'research-audit-research-only'
RESEARCH_AUDIT_FILE = DATA_DIR / 'inferno_research_audit.json'
RESEARCH_AUDIT_TEXT_FILE = REPORTS_DIR / 'research_audit_latest.txt'
SOURCES = {
    'paper': 'inferno_paper_execution_ledger.json',
    'shadow': 'inferno_shadow_evidence.json',
    'calibration': 'inferno_score_calibration.json',
    'conviction': 'inferno_conviction_research.json',
    'industry': 'inferno_industry_coverage.json',
    'shortPremium': 'inferno_short_premium_study.json',
    'cash': 'inferno_cash_attribution.json',
    'loop': 'inferno_evidence_goal_loop.json',
    'alternativePricing': 'inferno_strategy_alternative_pricing.json',
    'brokerTransactions': 'inferno_schwab_transaction_ledger.json',
}
CITATIONS = [
    'docs/MODEL_RESEARCH_GUIDELINES.md',
    'docs/RESEARCH_MEASUREMENT_AUDIT_2026-09-28.md',
    'https://www.gipsstandards.org/standards/gips-standards-for-firms/gips-standards-handbook-for-firms/',
    'https://www.davidhbailey.com/dhbpapers/backtest-prob.pdf',
]


def load_sources(directory: Path = DATA_DIR) -> tuple[dict, dict]:
    sources, receipts = {}, {}
    for name, filename in SOURCES.items():
        path = directory / filename
        receipt = {'path': str(path), 'status': 'missing'}
        try:
            raw = path.read_bytes()
            receipt.update(sha256=hashlib.sha256(raw).hexdigest(), bytes=len(raw))
            payload = json.loads(raw)
            if not isinstance(payload, dict):
                raise ValueError('expected object')
            sources[name] = payload
            receipt.update(status='read', generatedAt=payload.get('generatedAt'), updatedAt=payload.get('updatedAt'))
        except FileNotFoundError:
            pass
        except (OSError, ValueError):
            receipt['status'] = 'unreadable'
        receipts[name] = receipt
    return sources, receipts


def forward_collection_status(sources: dict, qualified: list[dict], *, today: date | None = None) -> dict:
    """Diagnose the existing campaign's funnel; never change its evaluator/gates."""
    today = today or local_now().date()
    def campaign(row):
        labels = [row.get(k) for k in ('strategy', 'recommendedStrategy', 'arm', 'campaignArm')]
        labels.append((row.get('strikePlan') or {}).get('strategy'))
        return 'SHORT_PREMIUM_DEFINED' in labels
    pricing = sources.get('alternativePricing')
    paper = sources.get('paper')
    candidates = [row for row in (pricing or {}).get('items') or [] if campaign(row)]
    stages, reasons = Counter(), Counter()
    for row in candidates:
        plan = row.get('strikePlan') or {}
        if row.get('status') != 'priced':
            stage = 'data-or-pricing-unavailable'
            reasons[str(row.get('reason') or row.get('status') or 'unspecified-pricing-failure')] += 1
        elif not plan.get('legs'):
            stage = 'construction-missing'
        elif row.get('optimizerPassed') is not True:
            stage = 'construction-or-economics-blocked'
            reasons.update(plan.get('optimizerBlocks') or ['optimizer-not-passed'])
        elif row.get('paperRiskPassed') is not True:
            stage = 'risk-blocked'
            reasons.update((row.get('riskVerdict') or {}).get('blocks') or ['risk-not-passed'])
        elif row.get('combinedPassed') is not True:
            stage = 'combined-gate-unconfirmed'
        else:
            stage = 'research-ready-not-approved'
        stages[stage] += 1
    tickets = [row for row in (paper or {}).get('items') or [] if campaign(row)]
    ids = {row.get('ticketId') for row in tickets if row.get('ticketId')}
    reconciled = [row for row in qualified if row.get('ticketId') in ids]
    costs_known = [row for row in reconciled if ((row.get('provenance') or {}).get('pnlReconciliation') or {}).get('netPnl') is not None]
    forward = (sources.get('shortPremium') or {}).get('forwardCampaign') or {}
    try:
        end = date.fromisoformat(forward.get('timeboxEnd') or '')
        remaining = (end - today).days
    except ValueError:
        remaining = None
    missing = [key for key in ('alternativePricing', 'paper', 'shortPremium') if not sources.get(key)]
    phase = 'deadline-unknown' if remaining is None else 'expired' if remaining < 0 else 'active'
    result = {
        'protocol': 'docs/SHORT_PREMIUM_PREREG_2026-07-07.md',
        'deadline': forward.get('timeboxEnd'), 'daysRemaining': remaining, 'phase': phase,
        'sourceMissing': missing,
        'latestBatchCandidates': len(candidates) if pricing else None,
        'latestBatchDistinctNames': len({r.get('ticker') for r in candidates if r.get('ticker')}) if pricing else None,
        'firstBlockingStageCounts': dict(sorted(stages.items())) if pricing else None,
        'blockingReasons': dict(reasons.most_common()),
        'campaignPaperRows': len(tickets) if paper else None,
        'campaignFillReconciledEvents': len({r['eventId'] for r in reconciled}) if paper else None,
        'campaignReportedCostEvents': len({r['eventId'] for r in costs_known}) if paper else None,
        'studyReportedEvents': forward.get('distinctEvents'),
        'eligibleUniverseChanged': False, 'evaluatorChanged': False,
        'limitations': [
            'Latest pricing batch is not coverage of the entire eligible universe.',
            'Funnel uses the first failed stage; simultaneous later blockers may also exist.',
            'A priced candidate is not approval, a fill, a fixed-exit outcome or independent evidence.',
            'Fill reconciliation and reported costs alone do not establish compliance with every registered protocol rule.',
            'The existing deadline and evaluator are observed, not extended or replaced.',
        ],
    }
    state = {k: v for k, v in result.items() if k != 'daysRemaining'}
    result['meaningfulStateSha256'] = hashlib.sha256(json.dumps(state, sort_keys=True).encode()).hexdigest()
    return result


def build_research_audit(*, sources: dict | None = None, fill_source: dict | None = None,
                         receipts: dict | None = None, previous: dict | None = None) -> dict[str, Any]:
    if sources is None:
        sources, receipts = load_sources()
        fill_source = load_fill_source() if fill_source is None else fill_source
    # Injected evidence must not silently reconcile against the real runtime.
    fill_source = fill_source if fill_source is not None else {'status': 'not-supplied', 'rows': []}
    missing = [name for name in SOURCES if not isinstance(sources.get(name), dict) or not sources[name]]
    paper = sources.get('paper') or {}
    qualified = closed_trade_records(paper.get('items') or [], fill_source) if 'paper' not in missing else []
    shadow = shadow_records(sources.get('shadow') or {})
    calibration = sources.get('calibration') or {}
    diagnostics = calibration.get('evidenceDiagnostics') or {}
    timing = diagnostics.get('shadowTimingRows') or {}
    coverage = (sources.get('conviction') or {}).get('coverage') or {}
    industry = sources.get('industry') or {}
    forward = (sources.get('shortPremium') or {}).get('forwardCampaign') or {}
    cash = (sources.get('cash') or {}).get('realizedOptionsProfit') or {}
    loop = sources.get('loop') or {}
    collection = forward_collection_status(sources, qualified)
    collection['meaningfulStateChanged'] = collection['meaningfulStateSha256'] != ((previous or {}).get('forwardCollection') or {}).get('meaningfulStateSha256')
    broker = sources.get('brokerTransactions') or {}
    broker_summary = broker.get('transactionSummary') or {}
    metrics = {
        'qualifiedPaperFills': len(qualified) if 'paper' not in missing else None,
        'qualifiedPaperEvents': len({r['eventId'] for r in qualified}) if 'paper' not in missing else None,
        'paperFillsWithReportedCosts': sum(r['provenance']['pnlReconciliation']['netPnl'] is not None for r in qualified) if 'paper' not in missing else None,
        'paperFillSourceStatus': fill_source.get('status', 'unknown'),
        'shadowRows': len(shadow) if 'shadow' not in missing else None,
        'shadowClosedRows': sum(r['outcomeStatus'] == 'closed' for r in shadow) if 'shadow' not in missing else None,
        'shadowScorableRows': sum(r['outcomeStatus'] == 'closed' and r['estimatedPnl'] is not None and r['maxLossDollars'] is not None for r in shadow) if 'shadow' not in missing else None,
        'prematureShadowLabels': timing.get('closed-before-expiration-session'),
        'unverifiedSettlementLabels': timing.get('unverified-settlement-time'),
        'legacyEntryScoreRows': (diagnostics.get('scoreProvenanceRows') or {}).get('legacy-entry-unverified'),
        'exposureGroups': diagnostics.get('exposureGroups'),
        'repeatedExposureRows': diagnostics.get('repeatedExposureRows'),
        'issuerReviewDue': industry.get('issuerReviewDue'),
        'issuerLinkedRows': (industry.get('evidenceCounts') or {}).get('issuer-linked-research'),
        'convictionEvidenceGrades': coverage.get('evidenceGradeCounts'),
        'shortPremiumForwardEvents': forward.get('distinctEvents'),
        'shortPremiumForwardNames': forward.get('distinctNames'),
        'realizedOptionsProfitKnown': cash.get('known'),
        'lastRunPromotionEvidenceDelta': (loop.get('progressDelta') or {}).get('promotionEvidenceDelta'),
        'fullRunAcceptanceRate': (loop.get('economics') or {}).get('fullRunAcceptanceRate'),
        'brokerOptionLegs': broker_summary.get('optionLegCount'),
        'brokerMatchedContractNetCash': (broker_summary.get('closedContractCashReconciliation') or {}).get('matchedNetCash'),
        'brokerEvidenceRetainedAfterFailure': broker.get('retainedPriorEvidence', False) if broker else None,
    }
    gaps = []
    def gap(key, area, observation, next_step):
        gaps.append({'id': key, 'area': area, 'observation': observation, 'nextStep': next_step})
    if missing:
        gap('missing-inputs', 'knowledge', 'Missing or unreadable sources: ' + ', '.join(missing), 'Restore source evidence; unknown values must not become zero or a clean verdict.')
    if metrics['qualifiedPaperFills'] is not None and metrics['qualifiedPaperFills'] != metrics['paperFillsWithReportedCosts']:
        gap('paper-costs', 'returns', 'Some reconciled fills lack reported round-trip costs.', 'Record source-supported fees; keep gross and net performance separate.')
    if fill_source.get('status') != 'ok':
        gap('fill-source', 'measurement', 'Fill source is unavailable or not valid.', 'Restore the operator fill log before interpreting qualified counts.')
    if metrics['prematureShadowLabels'] or metrics['unverifiedSettlementLabels'] or metrics['legacyEntryScoreRows']:
        gap('archive-provenance', 'assumptions', 'Historical shadow labels and entry features have provenance defects.', 'Keep the archive descriptive; gather immutable entry features and eligible later quotes prospectively.')
    if metrics['repeatedExposureRows']:
        gap('dependent-rows', 'measurement', 'Repeated exposures are not independent market events.', 'Report event counts, cluster descriptive intervals, and separate events across future test periods.')
    if metrics['issuerReviewDue']:
        gap('issuer-evidence', 'knowledge', 'Issuer-level evidence is due for part of the tracked universe.', 'Prioritize dated issuer sources for actionable and portfolio-relevant names; record contrary evidence and a falsifier.')
    if forward.get('distinctEvents') == 0:
        gap('short-premium-forward', 'strategy', 'Backward short-premium results have no forward event sample.', 'Collect quoted wings, bid/ask execution costs and fixed-exit outcomes under existing gates; backward proxies cannot authorize trading.')
    if collection['latestBatchCandidates'] and not (collection['firstBlockingStageCounts'] or {}).get('research-ready-not-approved'):
        gap('forward-collection-blocked', 'operations', f"All {collection['latestBatchCandidates']} latest campaign candidates stop before the combined research gate: {collection['firstBlockingStageCounts']}.", 'Repair source coverage first; record construction failures. Any proposed gate or protocol change requires a separate measured review; do not approve tickets to manufacture a sample.')
    if collection['phase'] == 'expired' or (collection['daysRemaining'] is not None and collection['daysRemaining'] <= 7 and not collection['campaignReportedCostEvents']):
        gap('forward-protocol-deadline', 'measurement', f"Existing campaign deadline {collection['deadline']}; reported-cost campaign events={collection['campaignReportedCostEvents']}.", 'Record an expired or underfilled experiment honestly; do not restart its clock or relabel historical simulations as forward outcomes.')
    if broker and not broker.get('ok'):
        gap('broker-evidence-refresh', 'returns', 'The latest broker transaction read is not healthy; retained facts are older evidence.', 'Restore the read-only source; do not treat a new report timestamp as a new broker observation.')
    if cash.get('known') is not True:
        gap('account-attribution', 'returns', 'Realized options profit is not source-proven.', 'Reconcile lots, costs, external flows and valuation dates before claiming account alpha or sweepable profit.')
    # These limitations are structural until an independently reviewed protocol changes.
    gap('prospective-validation', 'assumptions', 'Retrospective splits and fitted coefficients do not establish out-of-sample edge.', 'Register candidate rules, trials, dates, costs, fixed horizons and baselines before scoring future observations, including rejected candidates.')
    gap('capital-comparability', 'capital', 'Trade R and synthetic paper P/L are not deployable account returns.', 'Report actual size, shared exposure and live-size feasibility separately; budget and capital-stepper changes require operator acknowledgement.')
    if metrics['lastRunPromotionEvidenceDelta'] == 0:
        gap('activity-versus-evidence', 'operations', 'The latest loop added no qualified promotion evidence.', 'Keep acquisition/repair progress distinct from validated outcomes and retain no-progress backoff.')
    prior = (previous or {}).get('metrics') or {}
    progress_keys = ('qualifiedPaperEvents', 'paperFillsWithReportedCosts', 'shortPremiumForwardEvents', 'issuerReviewDue')
    delta = {k: metrics[k] - prior[k] if isinstance(metrics[k], (int, float)) and not isinstance(metrics[k], bool)
             and isinstance(prior.get(k), (int, float)) and not isinstance(prior[k], bool) else None for k in progress_keys}
    return {
        'generatedAt': local_now().isoformat(), 'stage': RESEARCH_AUDIT_STAGE,
        'researchOnly': True, 'promotable': False, 'authorityChanged': False,
        'liveTradingAllowed': False, 'brokerSubmitAllowed': False,
        'verdict': 'measurement-gaps-open', 'gapCount': len(gaps),
        'metrics': metrics, 'gaps': gaps, 'sourceReceipts': receipts or {},
        'forwardCollection': collection,
        'weeklyFunnel': weekly_funnel(paper, {'records': [
            {'recordId': r['ticketId'], 'source': 'paper-execution-ledger', 'promotionEligible': True}
            for r in qualified]}),
        'sourceMissing': missing, 'metricDeltaSincePreviousAudit': delta,
        'acceptedPromotionProgress': False, 'citations': CITATIONS,
        'limitations': [
            'Source timestamps and hashes describe saved artifacts, not independent verification or market freshness.',
            'Exposure groups are ticker/expiration proxies, not proven independent events.',
            'Deltas are observations, not attributed causal improvements. A successful audit is not trading progress.',
            'This report does not approve, reject, close, rank or route tickets and is not a gate input.',
        ],
    }


def research_audit_text(payload: dict) -> str:
    lines = ['Inferno research measurement audit', '', f"Generated: {payload.get('generatedAt')}",
             f"Verdict: {payload.get('verdict')} | open gaps: {payload.get('gapCount')}", '', 'Measurements:']
    lines.extend(f'- {key}: {value if value is not None else "unknown"}' for key, value in payload.get('metrics', {}).items())
    collection = payload.get('forwardCollection') or {}
    lines.extend(['', 'Weekly paper funnel (creation cohorts; reasons overlap):'])
    for row in payload.get('weeklyFunnel', []):
        lines.append(f"- {row['week']} {row['strategy']}: {row['proposed']} proposed -> {row['blocked']} blocked -> {row['staged']} staged -> {row['filled']} filled -> {row['qualified']} qualified; reasons={row['blockedByReason']}")
    lines.extend(['', 'Existing forward campaign:',
                  f"- Latest candidate stages: {collection.get('firstBlockingStageCounts')}",
                  f"- Paper rows: {collection.get('campaignPaperRows')} | fill-reconciled events: {collection.get('campaignFillReconciledEvents')} | reported-cost events: {collection.get('campaignReportedCostEvents')}",
                  f"- Deadline: {collection.get('deadline')} | days remaining: {collection.get('daysRemaining')} | meaningful state changed: {collection.get('meaningfulStateChanged')}"])
    lines.extend(['', 'Research backlog:'])
    lines.extend(f"- [{r['area']}] {r['observation']} Next: {r['nextStep']}" for r in payload.get('gaps', []))
    lines.extend(['', 'Limits:', *[f'- {s}' for s in payload.get('limitations', [])]])
    return '\n'.join(lines) + '\n'


def save_research_audit(payload: dict) -> None:
    atomic_write_json(RESEARCH_AUDIT_FILE, payload)
    atomic_write_text(RESEARCH_AUDIT_TEXT_FILE, research_audit_text(payload))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['run', 'status'], nargs='?', default='run')
    args = parser.parse_args()
    if args.command == 'status':
        print(RESEARCH_AUDIT_TEXT_FILE.read_text() if RESEARCH_AUDIT_TEXT_FILE.exists() else 'No research audit; run first.', end='')
        return 0 if RESEARCH_AUDIT_TEXT_FILE.exists() else 1
    try:
        previous = json.loads(RESEARCH_AUDIT_FILE.read_text())
        if not isinstance(previous, dict):
            previous = None
    except (OSError, ValueError):
        previous = None
    report = build_research_audit(previous=previous)
    save_research_audit(report)
    print(research_audit_text(report), end='')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

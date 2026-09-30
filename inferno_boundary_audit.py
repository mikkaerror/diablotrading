"""Read-only four-eyes audit. Never acknowledges or repairs a policy change."""
from __future__ import annotations

import argparse
import json
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from inferno_io import atomic_write_json, atomic_write_text

ROOT = Path(__file__).resolve().parent
# Prospective adoption boundary, not a moving last-success cursor. Unresolved
# changes therefore never age out of the nightly audit.
ADOPTION_BASE = '4c8c9d0d01ce1dacf1a09d2842f0b7b087528a85'
SAFES = frozenset({
    'inferno_config.py', 'inferno_math_config.py', 'inferno_risk_policy.py', 'inferno_risk_gate_audit.py',
    'inferno_authority_controller.py', 'inferno_strategy_lab.py',
    'inferno_promotion_evidence_lineage.py', 'inferno_paper_execution.py',
    'inferno_paper_delegate.py', 'inferno_paper_approval_routes.py',
    'inferno_approval_queue.py', 'inferno_execution_clerk.py',
    'inferno_ledger_ownership.py', 'inferno_ticket_cap_policy.py',
    'inferno_drawdown_protocol.py', 'inferno_trade_evidence.py',
    'inferno_short_premium_shadow.py', 'inferno_short_premium_study.py',
    'inferno_earnings_runner.py', 'inferno_prereg_integrity.py',
    'research/prereg_registry.json', 'research/strategy_lifecycle.json',
    'inferno_boundary_audit.py', 'CLAUDE.md', 'nightly_optimize.sh',
    'inferno_edge_research.py', 'inferno_strategy_optimizer.py',
    'inferno_process_compliance.py', 'inferno_desk_chief.py',
    'inferno_desk_chief_runner.py', 'coordination/desk_roles.json',
})
AGENTS = {'codex', 'claude'}


def git(root, *args):
    result = subprocess.run(['git', '-C', str(root), *args], capture_output=True, text=True, timeout=30)
    if result.returncode:
        raise ValueError(f'Git history unavailable: {result.stderr.strip()}')
    return result.stdout


def protected(path, registered=()):
    return (path in SAFES or path in registered or
            path.startswith(('inferno_risk_', 'inferno_authority_')) or
            (path.startswith('docs/') and 'PREREG' in path.upper()))


def registered_paths(root, revision):
    names = git(root, 'ls-tree', '-r', '--name-only', revision).splitlines()
    if 'research/prereg_registry.json' not in names:
        return set()
    registry = json.loads(git(root, 'show', f'{revision}:research/prereg_registry.json'))
    result = set()
    for entry in registry['experiments'].values():
        result.update([entry['doc'], entry['module'].replace('.', '/') + '.py'])
    return result


def records(root):
    notes_path = root / 'coordination/model_notes.jsonl'
    notes = [json.loads(line) for line in notes_path.read_text().splitlines() if line.strip()] if notes_path.exists() else []
    acks = []
    for path in sorted((root / 'coordination/operator_acks').glob('*.json')):
        ack = json.loads(path.read_text())
        if ack.get('scope') == 'four-eyes-change':
            acks.append({**ack, '_path': str(path.relative_to(root))})
    return notes, acks


def review_status(commit, author, notes, acks):
    """Exact target + distinct named agent + active operator consent; no fuzzy matches."""
    if author not in AGENTS:
        return {'passed': False, 'reasons': ['missing or ambiguous Agent-Author trailer (codex or claude)']}
    marker = f'[four-eyes commit={commit} author={author} verdict=approved]'
    reviews = [n for n in notes if n.get('author') in AGENTS - {author}
               and marker in str(n.get('body', '')) and n.get('id') and n.get('createdAt')
               and str(n.get('body', '')).replace(marker, '').strip()]
    # Duplicate IDs make the purported review ambiguous, even if one copy passes.
    reviews = [n for n in reviews if sum(x.get('id') == n['id'] for x in notes) == 1]
    if not reviews:
        return {'passed': False, 'reasons': ['missing approved review note from the other agent']}
    for note in reviews:
        bound_acks = [a for a in acks if a.get('changeCommit') == commit and a.get('reviewNoteId') == note['id']]
        if len(bound_acks) != 1:
            continue  # Conflicting/duplicate acknowledgements cannot resurrect a revoked OK.
        for ack in bound_acks:
            if (ack.get('active') is True and ack.get('operator') == 'Mikka'
                and ack.get('scope') == 'four-eyes-change'
                and ack.get('changeCommit') == commit and ack.get('reviewNoteId') == note['id']
                and ack.get('authorAgent') == author and ack.get('approvedAt')
                and ack.get('operatorStatement')):
                return {'passed': True, 'reasons': [], 'reviewNoteId': note['id'],
                        'reviewer': note['author'], 'operatorAck': ack.get('_path')}
    return {'passed': False, 'reasons': ["missing active Mikka OK bound to this commit and review note"]}


def build_boundary_audit(root=ROOT, *, base=ADOPTION_BASE):
    root = Path(root)
    report = {'generatedAt': datetime.now(timezone.utc).isoformat(),
              'stage': 'boundary-audit-research-only', 'researchOnly': True,
              'promotable': False, 'authorityChanged': False,
              'liveTradingAllowed': False, 'brokerSubmitAllowed': False, 'baseCommit': base,
              'commits': [], 'alerts': [], 'uncommittedSafetyPaths': []}
    try:
        head = git(root, 'rev-parse', 'HEAD').strip()
        report['headCommit'] = head
        git(root, 'merge-base', '--is-ancestor', base, head)
        notes, acks = records(root)
        paths = registered_paths(root, base)
        for commit in reversed(git(root, 'rev-list', f'{base}..{head}').splitlines()):
            parents = git(root, 'rev-list', '--parents', '-n', '1', commit).split()[1:]
            # Include old registry paths, so removing a registration cannot hide
            # a changed collector; examine every parent of a merge.
            paths |= registered_paths(root, commit)
            for parent in parents:
                paths |= registered_paths(root, parent)
            changed = set(git(root, 'diff-tree', '--root', '-m', '--no-commit-id',
                              '--name-only', '-r', '--no-renames', commit).splitlines())
            touched = sorted(p for p in changed if protected(p, paths))
            if not touched:
                continue
            message = git(root, 'show', '-s', '--format=%B', commit)
            authors = re.findall(r'^Agent-Author:\s*(codex|claude)\s*$', message, re.M)
            author = authors[0] if len(authors) == 1 else None
            status = review_status(commit, author, notes, acks)
            report['commits'].append({'commit': commit, 'authorAgent': author, 'paths': touched, **status})
            if not status['passed']:
                report['alerts'].append(f"{commit}: {'; '.join(status['reasons'])}")
        dirty = set(git(root, 'diff', '--name-only', '--no-renames', 'HEAD').splitlines())
        dirty.update(git(root, 'ls-files', '--others', '--exclude-standard').splitlines())
        report['uncommittedSafetyPaths'] = sorted(p for p in dirty if protected(p, paths))
        if report['uncommittedSafetyPaths']:
            report['alerts'].append('Uncommitted safety changes require an exact committed review target')
    except (OSError, ValueError, KeyError, TypeError, AttributeError, subprocess.SubprocessError) as exc:
        report['alerts'].append(f'Audit incomplete: {exc}')
    report['ok'] = not report['alerts']
    report['verdict'] = 'clear' if report['ok'] else 'review-required'
    return report


def boundary_text(report):
    lines = ['Inferno Four-Eyes Boundary Audit', f"Generated: {report['generatedAt']}",
             f"Verdict: {report['verdict']}", f"Base: {report['baseCommit']}",
             f"Safety commits checked: {len(report['commits'])}"]
    lines += ['POSSIBLE BOUNDARY DRIFT: ' + a for a in report['alerts']]
    lines += ['Uncommitted: ' + p for p in report['uncommittedSafetyPaths']]
    return '\n'.join(lines) + '\n'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=ROOT)
    parser.add_argument('--check', action='store_true', help='Read-only stdout audit; do not save report files')
    args = parser.parse_args()
    report = build_boundary_audit(args.root)
    if not args.check:
        atomic_write_json(args.root / 'data/inferno_boundary_audit.json', report)
        atomic_write_text(args.root / 'reports/boundary_audit_latest.txt', boundary_text(report))
    print(boundary_text(report))
    return 0 if report['ok'] else 1


if __name__ == '__main__':
    raise SystemExit(main())

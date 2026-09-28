"""Append-only local research archive. Stores observations, never makes decisions."""
from __future__ import annotations

import argparse
import base64
import csv
import hashlib
import io
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import uuid
import zlib
from contextlib import closing
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / 'data'
ARCHIVE_DIR = DATA_DIR / 'decision_archive'
ARCHIVE_FILE = DATA_DIR / 'inferno_decision_archive.json'
TEXT_FILE = ROOT / 'reports' / 'decision_archive_latest.txt'
ARCHIVE_STAGE = 'decision-archive-research-only'
# Only these local evidence files are captured. No credentials or broker API calls.
SOURCES = {
    'inferno_paper_execution_ledger.json': ('paper', 'items'),
    'inferno_shadow_evidence.json': ('shadow', 'items'),
    'inferno_fast_paper_ledger.json': ('simulation', 'items'),
    'inferno_scenario_evidence.json': ('scenario', 'observations'),
    'inferno_approval_queue.json': ('approval-state', 'items'),
    'inferno_strike_plan.json': ('proposal', 'items'),
    'operator_decisions.csv': ('decision-log', None),
}
VOLATILE = {'generatedAt', 'updatedAt', 'refreshedAt', 'lastAttemptAt', 'lastSuccessfulAt'}
TABLES = ('objects', 'snapshots', 'versions', 'annotations', 'captures')


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True, allow_nan=False)


def digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def stable(value: Any) -> Any:
    # Only outer refresh bookkeeping is ignored. Nested quote/source timestamps
    # are evidence and must survive even when the price is unchanged.
    if isinstance(value, dict):
        return {k: v for k, v in value.items() if k not in VOLATILE}
    return value


def code_receipt() -> dict:
    try:
        commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, stderr=subprocess.DEVNULL, timeout=5).decode().strip()
    except (OSError, subprocess.SubprocessError):
        commit = 'unavailable'
    names = ('inferno_decision_archive.py', 'inferno_config.py', 'inferno_risk_policy.py',
             'inferno_strategy_lab.py', 'inferno_paper_execution.py', 'inferno_shadow_evidence.py',
             'inferno_fast_paper_cohort.py', 'inferno_approval_queue.py', 'inferno_io.py', 'today.py', 'server.py', 'inferno_paper_delegate.py')
    return {'commit': commit, 'files': {name: digest((ROOT/name).read_bytes()) for name in names if (ROOT/name).exists()}}


def connect(directory: Path, *, readonly: bool = False) -> sqlite3.Connection:
    path = directory / 'archive.sqlite3'
    if readonly:
        db = sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True, timeout=30)
    else:
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        db = sqlite3.connect(path, timeout=30)
        os.chmod(path, 0o600)
        db.execute('PRAGMA foreign_keys=ON')
        db.execute('PRAGMA synchronous=FULL')
        db.executescript('''
            CREATE TABLE IF NOT EXISTS captures (capture_id TEXT PRIMARY KEY, source TEXT NOT NULL, captured_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS objects (sha TEXT PRIMARY KEY, body BLOB NOT NULL);
            CREATE TABLE IF NOT EXISTS snapshots (
              id INTEGER PRIMARY KEY, source TEXT NOT NULL, raw_sha TEXT NOT NULL REFERENCES objects(sha),
              captured_at TEXT NOT NULL, mode TEXT NOT NULL, code_json TEXT NOT NULL,
              parse_error TEXT, row_count INTEGER NOT NULL, previous_hash TEXT NOT NULL, chain_hash TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS versions (
              id INTEGER PRIMARY KEY, entity TEXT NOT NULL, snapshot_id INTEGER NOT NULL REFERENCES snapshots(id),
              row_index INTEGER NOT NULL, semantic_sha TEXT NOT NULL, raw_json BLOB NOT NULL,
              ticker TEXT NOT NULL, case_key TEXT NOT NULL, identity_basis TEXT NOT NULL,
              summary_json TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS version_snapshot ON versions(snapshot_id);
            CREATE INDEX IF NOT EXISTS version_entity ON versions(entity, id);
            CREATE INDEX IF NOT EXISTS version_ticker ON versions(ticker, id);
            CREATE INDEX IF NOT EXISTS version_case ON versions(case_key, id);
            CREATE INDEX IF NOT EXISTS snapshot_source ON snapshots(source, id);
            CREATE TABLE IF NOT EXISTS annotations (
              id INTEGER PRIMARY KEY, version_id INTEGER NOT NULL REFERENCES versions(id),
              recorded_at TEXT NOT NULL, author TEXT NOT NULL, reason TEXT NOT NULL);
        ''')
        for table in TABLES:
            for operation in ('UPDATE', 'DELETE'):
                db.execute(f"CREATE TRIGGER IF NOT EXISTS no_{operation}_{table} BEFORE {operation} ON {table} BEGIN SELECT RAISE(ABORT, 'archive is append-only'); END")
        db.commit()
    db.row_factory = sqlite3.Row
    return db


def parse_source(source: str, raw: bytes) -> list[dict]:
    lane, key = SOURCES[source]
    text = raw.decode('utf-8-sig')
    if lane == 'decision-log':
        reader = csv.DictReader(io.StringIO(text))
        if not {'timestamp', 'ticker', 'action'} <= set(reader.fieldnames or []):
            raise ValueError('decision log is missing timestamp/ticker/action columns')
        rows = [{('_unmappedColumns' if k is None else k): v for k, v in row.items()} for row in reader]
    else:
        payload = json.loads(text, parse_constant=lambda x: (_ for _ in ()).throw(ValueError('nonfinite JSON')))
        if not isinstance(payload, dict) or not isinstance(payload.get(key), list):
            raise ValueError(f'expected {key} list')
        rows = payload[key]
    if not all(isinstance(row, dict) for row in rows):
        raise ValueError('non-object record')
    return rows


def identity(row: dict, fallback: str) -> tuple[str, str]:
    """Contract exposure identity, NOT an independent-event or execution count."""
    plan = row.get('strikePlan') if isinstance(row.get('strikePlan'), dict) else {}
    ticker = str(row.get('ticker') or row.get('symbol') or '').upper()
    strategy = row.get('strategy') or plan.get('strategy')
    expiration = row.get('expiration') or plan.get('expiration')
    legs = row.get('legs') or plan.get('legs') or []
    if ticker and strategy and expiration and legs and all(isinstance(l, dict) and l.get('symbol') and l.get('instruction') for l in legs):
        normalized = sorted((str(l['symbol']).strip().upper(), str(l['instruction']).upper(), str(l.get('quantity') or 'unknown')) for l in legs)
        return digest(canonical([ticker, strategy, expiration, normalized]).encode()), 'same-contract-exposure-not-independent-event'
    return digest(fallback.encode()), 'source-record-only-incomplete-contract-identity'


def summary(row: dict, lane: str) -> dict:
    verdict = row.get('riskVerdict') if isinstance(row.get('riskVerdict'), dict) else {}
    reasons = {key: row[key] for key in ('rationale', 'note', 'reason', 'decisionReason', 'blockReasons', 'intentBlocks', 'researchNotes', 'notes') if row.get(key)}
    for key in ('reasons', 'hardFails', 'warnings', 'checks'):
        if verdict.get(key):
            reasons['risk.' + key] = verdict[key]
    plan = row.get('strikePlan') if isinstance(row.get('strikePlan'), dict) else {}
    outcome = row.get('outcome') if isinstance(row.get('outcome'), dict) else {}
    return {
        'lane': lane, 'sourceStatus': row.get('action') or row.get('approvalStatus') or row.get('status') or row.get('intentStatus'),
        'sourceClaimedAt': row.get('timestamp') or row.get('decisionAt') or row.get('createdAt') or row.get('generatedAt'),
        'tradeDate': row.get('tradeDate'), 'eventIdAsReported': row.get('eventId'),
        'strategy': row.get('strategy') or plan.get('strategy'),
        'reasonsAsRecorded': reasons, 'reasonStatus': 'recorded-source-text' if reasons else 'not-recorded',
        'decisionRationaleStatus': ('recorded' if row.get('rationale') else 'not-recorded') if lane == 'decision-log' else 'not-a-decision-log',
        'outcomeAsRecorded': outcome, 'riskPassedAsReported': verdict.get('passed'),
        'interpretation': 'source statement; approval is not execution; a simulation is not a broker fill',
    }


def chain_value(previous: str, source: str, sha: str, captured: str, mode: str, code: str, error: str | None, count: int) -> str:
    return digest(canonical([previous, source, sha, captured, mode, code, error, count]).encode())


def ingest(db: sqlite3.Connection, envelope: dict) -> tuple[int, int]:
    if db.execute('SELECT 1 FROM captures WHERE capture_id=?', (envelope['captureId'],)).fetchone():
        return 0, 0
    source, raw = envelope['source'], base64.b64decode(envelope['body'], validate=True)
    db.execute('INSERT INTO captures VALUES (?,?,?)', (envelope['captureId'], source, envelope['capturedAt']))
    sha = digest(raw)
    latest = db.execute('SELECT raw_sha FROM snapshots WHERE source=? ORDER BY id DESC LIMIT 1', (source,)).fetchone()
    if latest and latest['raw_sha'] == sha:
        return 0, 0
    error = None
    try:
        rows = parse_source(source, raw)
    except (ValueError, UnicodeError, csv.Error) as exc:
        rows, error = [], f'{type(exc).__name__}: {exc}'
    db.execute('INSERT OR IGNORE INTO objects VALUES (?,?)', (sha, zlib.compress(raw)))
    prior = db.execute('SELECT chain_hash FROM snapshots ORDER BY id DESC LIMIT 1').fetchone()
    previous = prior['chain_hash'] if prior else ''
    code = canonical(envelope['code'])
    chain = chain_value(previous, source, sha, envelope['capturedAt'], envelope['mode'], code, error, len(rows))
    sid = db.execute('INSERT INTO snapshots(source,raw_sha,captured_at,mode,code_json,parse_error,row_count,previous_hash,chain_hash) VALUES (?,?,?,?,?,?,?,?,?)',
                     (source, sha, envelope['capturedAt'], envelope['mode'], code, error, len(rows), previous, chain)).lastrowid
    added = 0
    occurrences = Counter()
    for index, row in enumerate(rows):
        lane = SOURCES[source][0]
        # IDs only join within their source. CSV row ordinals preserve identical repeated entries.
        rid = row.get('ticketId') or row.get('observationId') or row.get('id') or row.get('token')
        if lane == 'decision-log':
            rid = f'csv-row:{index}'
        if not rid:
            fallback = canonical([row.get('ticker'), row.get('sourceLane'), row.get('routeFamily'), row.get('tradeDate')])
            rid = identity(row, fallback)[0]
        occurrences[str(rid)] += 1
        entity = canonical([source, str(rid), occurrences[str(rid)]])
        semantic = digest(canonical(stable(row)).encode())
        old = db.execute('SELECT semantic_sha FROM versions WHERE entity=? ORDER BY id DESC LIMIT 1', (entity,)).fetchone()
        if old and old['semantic_sha'] == semantic:
            continue
        case, basis = identity(row, entity)
        db.execute('INSERT INTO versions(entity,snapshot_id,row_index,semantic_sha,raw_json,ticker,case_key,identity_basis,summary_json) VALUES (?,?,?,?,?,?,?,?,?)',
                   (entity, sid, index, semantic, zlib.compress(canonical(row).encode()), str(row.get('ticker') or row.get('symbol') or '').upper(), case, basis, canonical(summary(row, lane))))
        added += 1
    return 1, added


def spool_capture(source: str, raw: bytes, directory: Path, mode: str) -> None:
    pending = directory / 'pending'
    pending.mkdir(parents=True, exist_ok=True, mode=0o700)
    envelope = {'captureId': uuid.uuid4().hex, 'source': source, 'body': base64.b64encode(raw).decode(), 'capturedAt': now_iso(), 'mode': mode, 'code': code_receipt()}
    fd, name = tempfile.mkstemp(prefix='.writing-', dir=pending)
    try:
        with os.fdopen(fd, 'wb') as handle:
            handle.write(zlib.compress(canonical(envelope).encode()))
            handle.flush(); os.fsync(handle.fileno())
        target = pending / f"{envelope['capturedAt'].replace(':', '-')}-{uuid.uuid4().hex}.capture"
        os.replace(name, target)
    except BaseException:
        Path(name).unlink(missing_ok=True)
        raise


def drain(directory: Path) -> dict:
    db = connect(directory)
    completed = []
    counts = {'newSnapshots': 0, 'newVersions': 0}
    try:
        db.execute('BEGIN IMMEDIATE')
        # Enumerate under the DB writer lock; concurrent writers cannot reorder this queue.
        for path in sorted((directory/'pending').glob('*.capture')):
            try:
                envelope = json.loads(zlib.decompress(path.read_bytes()))
            except FileNotFoundError:
                continue
            a, b = ingest(db, envelope)
            counts['newSnapshots'] += a; counts['newVersions'] += b
            completed.append(path)
        db.commit()
        for path in completed:
            path.unlink(missing_ok=True)
    except BaseException:
        db.rollback()
        raise
    finally:
        db.close()
    return counts


def capture_bytes(path: Path, raw: bytes, *, mode: str = 'persistence-observation', directory: Path | None = None) -> dict:
    if path.name not in SOURCES:
        return {'newSnapshots': 0, 'newVersions': 0}
    directory = directory or path.parent / 'decision_archive'
    spool_capture(path.name, raw, directory, mode)
    return drain(directory)


def capture_saved_file(path: Path) -> None:
    """Best-effort observer for direct CSV writers; never changes a decision."""
    from inferno_io import archive_written_evidence
    try:
        archive_written_evidence(path, path.read_bytes())
    except OSError as exc:
        print(f"Decision archive could not read decision log: {exc}", file=sys.stderr)


def verify(directory: Path) -> dict:
    errors = []
    with closing(connect(directory, readonly=True)) as db:
        if db.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
            errors.append('sqlite-integrity')
        for row in db.execute('SELECT * FROM objects'):
            try:
                if digest(zlib.decompress(row['body'])) != row['sha']:
                    errors.append('object-hash:' + row['sha'])
            except zlib.error:
                errors.append('object-decompression:' + row['sha'])
        previous = ''
        for row in db.execute('SELECT * FROM snapshots ORDER BY id'):
            calculated = chain_value(previous, row['source'], row['raw_sha'], row['captured_at'], row['mode'], row['code_json'], row['parse_error'], row['row_count'])
            if row['previous_hash'] != previous or row['chain_hash'] != calculated:
                errors.append('snapshot-chain:' + str(row['id']))
            previous = row['chain_hash']
        for row in db.execute('SELECT id,raw_json,semantic_sha FROM versions'):
            if digest(canonical(stable(json.loads(zlib.decompress(row['raw_json'])))).encode()) != row['semantic_sha']:
                errors.append('record-hash:' + str(row['id']))
        for snapshot in db.execute('SELECT s.id,s.source,o.body FROM snapshots s JOIN objects o ON o.sha=s.raw_sha WHERE s.parse_error IS NULL'):
            try:
                original = parse_source(snapshot['source'], zlib.decompress(snapshot['body']))
                for row in db.execute('SELECT id,row_index,raw_json FROM versions WHERE snapshot_id=?', (snapshot['id'],)):
                    if row['row_index'] >= len(original) or json.loads(zlib.decompress(row['raw_json'])) != original[row['row_index']]:
                        errors.append('record-source-mismatch:' + str(row['id']))
            except (ValueError, UnicodeError, zlib.error):
                errors.append('source-record-verification:' + str(snapshot['id']))
        if list(db.execute('PRAGMA foreign_key_check')):
            errors.append('foreign-key-check')
    return {'ok': not errors, 'errors': errors, 'headHash': previous}


def build_decision_archive(directory: Path = ARCHIVE_DIR) -> dict:
    with closing(connect(directory, readonly=True)) as db:
        counts = {t: db.execute(f'SELECT COUNT(*) FROM {t}').fetchone()[0] for t in TABLES}
        latest = list(db.execute('SELECT * FROM snapshots WHERE id IN (SELECT MAX(id) FROM snapshots GROUP BY source)'))
        latest_versions = list(db.execute('SELECT summary_json,identity_basis FROM versions WHERE id IN (SELECT MAX(id) FROM versions GROUP BY entity)'))
        counts['sourceRecords'] = len(latest_versions)
        counts['contractExposureGroups'] = db.execute("SELECT COUNT(DISTINCT case_key) FROM versions WHERE identity_basis='same-contract-exposure-not-independent-event'").fetchone()[0]
        counts['recordsWithoutReason'] = sum(json.loads(r['summary_json'])['reasonStatus'] == 'not-recorded' for r in latest_versions)
        counts['decisionLogsWithoutRationale'] = sum(json.loads(r['summary_json'])['decisionRationaleStatus'] == 'not-recorded' for r in latest_versions)
        counts['pendingCaptures'] = len(list((directory/'pending').glob('*.capture')))
        failure_log = directory / 'capture_failures.jsonl'
        counts['captureFailureEvents'] = len(failure_log.read_text().splitlines()) if failure_log.exists() else 0
        counts['incompleteCaptureFiles'] = len(list((directory/'pending').glob('.writing-*')))
    integrity = verify(directory)
    missing = sorted(set(SOURCES) - {r['source'] for r in latest})
    errors = [{'source': r['source'], 'error': r['parse_error']} for r in latest if r['parse_error']]
    return {'generatedAt': now_iso(), 'stage': ARCHIVE_STAGE, 'researchOnly': True,
            'promotable': False, 'authorityChanged': False, 'liveTradingAllowed': False, 'brokerSubmitAllowed': False,
            'verdict': 'healthy' if integrity['ok'] and not missing and not errors and not counts['pendingCaptures'] and not counts['incompleteCaptureFiles'] and not counts['captureFailureEvents'] else 'attention',
            'counts': counts, 'integrity': integrity, 'missingSources': missing, 'sourceErrors': errors,
            'sources': [{k: r[k] for k in ('source','raw_sha','captured_at','mode','row_count')} for r in latest],
            'retention': 'permanent core evidence; no automatic deletion; relevance evaluated separately',
            'limitations': ['Historical imports are observations captured now, not reconstructed decision-time knowledge.',
                           'Missing rationale stays unknown. Approval is not execution. No rows grant authority.',
                           'Contract exposure groups are not independent-event counts. Source rows remain separate.',
                           'Local hash verification detects inconsistency, not malicious rewriting by the file owner.',
                           'Local backup is not off-device disaster recovery.'],
            'citations': ['docs/DECISION_ARCHIVE.md']}


def decision_archive_text(report: dict) -> str:
    lines = ['Inferno decision archive', '', f"Generated: {report['generatedAt']}", f"Status: {report['verdict']}",
             f"Counts: {report['counts']}", f"Integrity: {report['integrity']}", f"Retention: {report['retention']}",
             f"Missing sources: {report['missingSources']}", f"Source errors: {report['sourceErrors']}", '',
             'Find history: ./inferno archive history --ticker SYMBOL',
             'Inspect a version: ./inferno archive show --record-id ID', '', *report['limitations']]
    return '\n'.join(lines) + '\n'


def save_decision_archive(report: dict) -> None:
    from inferno_io import atomic_write_json, atomic_write_text
    atomic_write_json(ARCHIVE_FILE, report)
    atomic_write_text(TEXT_FILE, decision_archive_text(report))


def history(directory: Path, *, ticker: str, limit: int = 20, before: int | None = None) -> list[dict]:
    with closing(connect(directory, readonly=True)) as db:
        rows = db.execute('SELECT v.*,s.source,s.captured_at,s.mode FROM versions v JOIN snapshots s ON s.id=v.snapshot_id WHERE ticker=? AND v.id<? ORDER BY v.id DESC LIMIT ?',
                          (ticker.upper(), before if before is not None else 9223372036854775807, max(1,min(limit,200))))
        return [{'recordId': r['id'], 'source': r['source'], 'capturedAt': r['captured_at'], 'captureMode': r['mode'],
                 'caseKey': r['case_key'], 'identityBasis': r['identity_basis'], **json.loads(r['summary_json'])} for r in rows]


def show(directory: Path, record_id: int) -> dict:
    with closing(connect(directory, readonly=True)) as db:
        row = db.execute('SELECT v.*,s.source,s.raw_sha,s.captured_at,s.mode,s.code_json FROM versions v JOIN snapshots s ON s.id=v.snapshot_id WHERE v.id=?', (record_id,)).fetchone()
        if row is None:
            raise ValueError('record not found')
        notes = [dict(r) for r in db.execute('SELECT * FROM annotations WHERE version_id=? ORDER BY id', (record_id,))]
        return {'recordId': record_id, 'source': row['source'], 'sourceSha256': row['raw_sha'], 'sourceRowIndex': row['row_index'],
                'capturedAt': row['captured_at'], 'captureMode': row['mode'], 'caseKey': row['case_key'],
                'sourceRecord': json.loads(zlib.decompress(row['raw_json'])), 'summary': json.loads(row['summary_json']),
                'codeReceipt': json.loads(row['code_json']), 'retrospectiveAnnotations': notes}


def annotate(directory: Path, record_id: int, author: str, reason: str) -> None:
    if not author.strip() or not reason.strip():
        raise ValueError('author and reason are required')
    with closing(connect(directory)) as db:
        db.execute('INSERT INTO annotations(version_id,recorded_at,author,reason) VALUES (?,?,?,?)', (record_id, now_iso(), author.strip(), reason.strip()))
        db.commit()


def backup(directory: Path, destination: Path) -> dict:
    destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    # Refuse overwrite; every recovery copy is immutable by convention.
    fd = os.open(destination, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600); os.close(fd)
    try:
        with closing(connect(directory, readonly=True)) as source, closing(sqlite3.connect(destination)) as target:
            source.backup(target)
            if target.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                raise ValueError('backup integrity failed')
        return {'path': str(destination), 'sha256': digest(destination.read_bytes()), 'sqliteIntegrity': 'ok'}
    except BaseException:
        destination.unlink(missing_ok=True)
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', nargs='?', default='run', choices=['run','status','verify','history','show','annotate','backup'])
    parser.add_argument('--ticker'); parser.add_argument('--record-id', type=int)
    parser.add_argument('--limit', type=int, default=20); parser.add_argument('--before', type=int)
    parser.add_argument('--author'); parser.add_argument('--reason'); parser.add_argument('--destination', type=Path)
    args = parser.parse_args()
    try:
        if args.command == 'run':
            drain(ARCHIVE_DIR)
            for source in SOURCES:
                path = DATA_DIR/source
                if path.exists():
                    capture_bytes(path, path.read_bytes(), mode='saved-state-observation')
            report = build_decision_archive(); save_decision_archive(report)
            print(decision_archive_text(report), end='')
            return 0 if report['verdict'] == 'healthy' else 1
        if args.command == 'status':
            report = build_decision_archive(); print(decision_archive_text(report), end='')
            return 0 if report['verdict'] == 'healthy' else 1
        if args.command == 'verify':
            result = verify(ARCHIVE_DIR); print(json.dumps(result, indent=2)); return 0 if result['ok'] else 1
        if args.command == 'history':
            if not args.ticker: parser.error('history requires --ticker')
            result = history(ARCHIVE_DIR, ticker=args.ticker, limit=args.limit, before=args.before)
        elif args.command == 'show':
            if args.record_id is None: parser.error('show requires --record-id')
            result = show(ARCHIVE_DIR, args.record_id)
        elif args.command == 'annotate':
            if args.record_id is None or not args.author or not args.reason: parser.error('annotate requires --record-id, --author, --reason')
            annotate(ARCHIVE_DIR, args.record_id, args.author, args.reason)
            result = {'recordId': args.record_id, 'annotation': 'appended retrospectively; no decision changed'}
        else:
            if not args.destination: parser.error('backup requires --destination')
            result = backup(ARCHIVE_DIR, args.destination)
        print(json.dumps(result, indent=2)); return 0
    except (OSError, ValueError, sqlite3.Error, zlib.error) as exc:
        print(f'Decision archive error: {exc}', file=sys.stderr); return 1


if __name__ == '__main__':
    raise SystemExit(main())

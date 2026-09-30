"""Versioned, hash-verified canonical paper snapshots; publication is not a ticket action."""
from __future__ import annotations
import argparse
import hashlib
import json
import subprocess
import tempfile
from pathlib import Path
from inferno_ledger_ownership import ROOT, PROTECTED_PATHS, require_paper_writer, approved_budget_environment

PREFIX = 'canonical-paper'
POINTER = PREFIX + '/current.json'
REQUIRED = {'data/inferno_paper_execution_ledger.json', 'data/inferno_approval_queue.json', 'data/inferno_tos_fill_log.csv'}


def snapshot(root=ROOT):
    contents = {}; files = []
    for name in PROTECTED_PATHS:
        path = root/name
        if not path.exists():
            if name in REQUIRED: raise ValueError(f'Required canonical source missing: {name}')
            continue
        raw = path.read_bytes(); contents[name] = raw
        files.append({'path': name, 'sha256': hashlib.sha256(raw).hexdigest(), 'bytes': len(raw)})
    revision = hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest()
    return {'version': 1, 'owner': 'mac', 'revision': revision, 'files': files,
            'paperBudget': approved_budget_environment(), 'researchOnly': True}, contents


def restore_snapshot(bucket, root=ROOT):
    """Validate every source before replacing any local read-only copy."""
    manifest = json.loads(bucket.blob(POINTER).download_as_bytes())
    paths = [f['path'] for f in manifest['files']]
    if manifest.get('owner') != 'mac' or not REQUIRED.issubset(paths) or len(set(paths)) != len(paths):
        raise ValueError('Invalid canonical paper snapshot manifest')
    revision = hashlib.sha256(json.dumps(manifest['files'], sort_keys=True).encode()).hexdigest()
    if revision != manifest.get('revision'): raise ValueError('Canonical snapshot revision mismatch')
    contents = {}
    for entry in manifest['files']:
        name = entry['path']
        if name not in PROTECTED_PATHS: raise ValueError('Unexpected canonical path')
        raw = bucket.blob(f'{PREFIX}/{revision}/{name}').download_as_bytes()
        if hashlib.sha256(raw).hexdigest() != entry['sha256'] or len(raw) != entry['bytes']:
            raise ValueError(f'Canonical snapshot checksum mismatch: {name}')
        contents[name] = raw
    from inferno_io import atomic_write_text, atomic_write_json
    for name, raw in contents.items():
        atomic_write_text(root/name, raw.decode('utf-8'))
    atomic_write_json(root/'data/inferno_canonical_paper_receipt.json', manifest)
    return manifest


def publish(bucket_name):
    require_paper_writer('canonical snapshot publication')
    manifest, contents = snapshot()
    base = 'gs://' + bucket_name + '/'
    def run(*args):
        binary = str(Path.home()/'.local/bin/gcloud') if (Path.home()/'.local/bin/gcloud').exists() else 'gcloud'
        return subprocess.run([binary, 'storage', *args], capture_output=True, text=True, timeout=120)
    prior = run('objects', 'describe', base+POINTER, '--format=value(generation)')
    if prior.returncode and not ('404' in prior.stderr or 'not found' in prior.stderr.lower()):
        raise RuntimeError('Cannot read canonical pointer generation: '+prior.stderr)
    generation = prior.stdout.strip() if prior.returncode == 0 else '0'
    if generation != '0':
        current = run('cat', base+POINTER+'#'+generation)
        if current.returncode: raise RuntimeError(current.stderr)
        if json.loads(current.stdout).get('revision') == manifest['revision']:
            return {'status': 'unchanged', 'revision': manifest['revision']}
    with tempfile.TemporaryDirectory() as tmp:
        for name, raw in contents.items():
            path = Path(tmp)/Path(name).name; path.write_bytes(raw)
            target = base+PREFIX+'/'+manifest['revision']+'/'+name
            result = run('cp', str(path), target, '--if-generation-match=0', '--quiet')
            if result.returncode:
                existing = run('cat', target)
                if existing.returncode or existing.stdout.encode() != raw:
                    raise RuntimeError('Immutable snapshot upload failed: '+result.stderr)
        # Do not publish a mixture if another local writer changed a source.
        if snapshot()[0]['revision'] != manifest['revision']:
            raise RuntimeError('Canonical sources changed during publication; retry snapshot')
        path = Path(tmp)/'current.json'; path.write_text(json.dumps(manifest, indent=2)+'\n')
        result = run('cp', str(path), base+POINTER, '--if-generation-match='+generation, '--quiet')
        if result.returncode: raise RuntimeError('Canonical pointer update failed: '+result.stderr)
    return {'status': 'published', 'revision': manifest['revision'], 'fileCount': len(contents)}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bucket', default='ohsheetohsheet-inferno-state')
    args=parser.parse_args()
    print(json.dumps(publish(args.bucket), indent=2))


if __name__ == '__main__': main()

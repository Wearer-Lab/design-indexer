#!/usr/bin/env python3
"""Resumable public GitHub CAD/BIM file-link indexer."""
import argparse
import base64
import json
import os
import urllib.error
import urllib.parse
from pathlib import Path

from crawler import Client, get_tree, q

FORMATS = {
    '.stl': 'STL', '.stp': 'STEP', '.step': 'STEP', '.glb': 'glTF GLB',
    '.igs': 'IGES', '.iges': 'IGES', '.x_t': 'Parasolid text',
    '.x_b': 'Parasolid binary', '.dwg': 'AutoCAD DWG', '.dxf': 'DXF',
    '.sldprt': 'SolidWorks part', '.sldasm': 'SolidWorks assembly',
    '.ipt': 'Inventor part', '.iam': 'Inventor assembly',
    '.aim': 'Inventor assembly (possible)', '.catpart': 'CATIA part',
    '.catproduct': 'CATIA assembly', '.cgr': 'CATIA graphics',
    '.rvt': 'Revit project', '.rfa': 'Revit family',
    '.3dm': 'Rhino 3DM', '.f3d': 'Fusion 360 design',
    '.f3z': 'Fusion 360 assembly',
}
AMBIGUOUS = {'.bak': 'AutoCAD backup (possible)',
             '.prt': 'Creo or Siemens NX part/assembly',
             '.asm': 'Creo assembly (possible)',
             '.pln': 'Archicad project (possible)'}
MAX_PROBE = 2_000_000
MAX_CANDIDATE = 100_000_000
OLE = bytes.fromhex('d0cf11e0a1b11ae1')


def classify(path, head=None):
    ext = Path(path.lower()).suffix
    if ext in FORMATS:
        fmt = FORMATS[ext]
        # These headers are standardized and quick to verify when available.
        if head is not None:
            if ext == '.glb' and not head.startswith(b'glTF'):
                return None
            if ext == '.dwg' and not head.startswith(b'AC10'):
                return None
            if ext == '.f3z' and not head.startswith(b'PK'):
                return None
            if ext == '.3dm' and not head.startswith(b'3D Geometry File Format'):
                return None
            if ext in ('.stp', '.step') and b'ISO-10303-21' not in head[:2048]:
                return None
        return fmt, ('header_verified' if head is not None and ext in {
            '.glb', '.dwg', '.f3z', '.3dm', '.stp', '.step'} else 'extension_only')
    if ext == '.bak':
        return ('AutoCAD DWG backup', 'header_verified') if head and head.startswith(b'AC10') else None
    if ext in ('.prt', '.asm', '.pln'):
        if head is not None and (not head or (b'\x00' not in head[:1024] and head[:1024].isascii())):
            return None
        return AMBIGUOUS[ext], 'ambiguous_extension'
    return None


def load(path):
    if path.exists():
        return json.loads(path.read_text())
    return {'since': 0, 'pending': None, 'scanned': 0, 'entries': {}, 'skipped': []}


def save(path, state):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(state, sort_keys=True, separators=(',', ':')) + '\n')
    tmp.replace(path)
    rows = sorted(state['entries'].values(), key=lambda row: (row['repo_id'], row['path']))
    for name, body in (
        ('cad_links.jsonl', ''.join(json.dumps(row, sort_keys=True) + '\n' for row in rows)),
        ('cad_links.txt', ''.join(row['url'] + '\n' for row in rows)),
    ):
        output = path.parent / name
        tmp = output.with_suffix('.tmp')
        tmp.write_text(body)
        tmp.replace(output)


def scan_repo(client, repo, state):
    name, rid = repo['full_name'], repo['id']
    info = client.get('/repos/' + '/'.join(q(part) for part in name.split('/')))
    if not info or not info.get('default_branch'):
        return
    name = info['full_name']
    branch = client.get('/repos/' + name + '/branches/' + q(info['default_branch']))
    if not branch:
        return
    commit = branch['commit']['sha']
    for path, node in get_tree(client, name, branch['commit']['commit']['tree']['sha']):
        ext = Path(path.lower()).suffix
        size = node.get('size', 0)
        if (ext not in FORMATS and ext not in AMBIGUOUS) or size < 8 or size > MAX_CANDIDATE:
            continue
        head = None
        if size <= MAX_PROBE:
            blob = client.get('/repos/' + name + '/git/blobs/' + q(node['sha']))
            if blob and blob.get('encoding') == 'base64':
                head = base64.b64decode(blob['content'])[:4096]
        if ext == '.bak' and head is None:
            continue
        result = classify(path, head)
        if not result:
            continue
        fmt, validation = result
        # Git LFS pointers are metadata, not the CAD bytes at the Git blob URL.
        if head and head.startswith(b'version https://git-lfs.github.com/spec/v1'):
            continue
        url = 'https://github.com/' + name + '/blob/' + commit + '/' + urllib.parse.quote(path, safe='/')
        state['entries'][str(rid) + ':' + path] = {
            'repo_id': rid, 'repo': name, 'path': path, 'format': fmt,
            'validation': validation, 'size': size, 'url': url,
            'blob_sha': node['sha'], 'commit': commit,
        }


def run(args):
    path = Path(args.state)
    state = load(path)
    client = Client(os.environ['GITHUB_TOKEN'], args.max_requests)
    processed = 0
    try:
        while processed < args.max_repos and client.left > 5:
            if not state['pending']:
                batch = client.get('/repositories?since=' + str(state['since']) + '&per_page=100')
                if not batch:
                    break
                state['pending'] = batch
            repo = state['pending'][0]
            try:
                scan_repo(client, repo, state)
            except RuntimeError as exc:
                if 'budget' in str(exc):
                    break
                state['skipped'].append({'id': repo['id'], 'repo': repo['full_name'], 'error': str(exc)})
            except urllib.error.HTTPError as exc:
                if exc.code in (403, 429):
                    break
                state['skipped'].append({'id': repo['id'], 'repo': repo['full_name'], 'error': str(exc.code)})
            state['pending'].pop(0)
            state['since'] = repo['id']
            state['scanned'] += 1
            processed += 1
            save(path, state)
    finally:
        save(path, state)
    print(json.dumps({'scanned_this_run': processed, 'scanned_total': state['scanned'],
                      'links': len(state['entries']), 'requests_left': client.left,
                      'skipped': len(state['skipped'])}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--state', default='data/cad_state.json')
    parser.add_argument('--max-repos', type=int, default=12)
    parser.add_argument('--max-requests', type=int, default=35)
    run(parser.parse_args())

#!/usr/bin/env python3
"""Bounded, resumable GitHub public PCB file indexer (standard library only)."""
import argparse
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

API = 'https://api.github.com'
UNIQUE = {'.kicad_pcb': 'KiCad', '.pcbdoc': 'Altium', '.lpp': 'LibrePCB'}
AMBIGUOUS = {'.brd', '.pcb'}


def detect(path, data):
    suffix = Path(path.lower()).suffix
    if suffix in UNIQUE:
        name = UNIQUE[suffix]
        if name == 'KiCad' and not data.lstrip().startswith(b'(kicad_pcb'):
            return None
        if name == 'LibrePCB' and b'librepcb' not in data.lower()[:2048]:
            return None
        if name == 'Altium' and not data.startswith(bytes.fromhex('d0cf11e0a1b11ae1')):
            return None
        return name
    if suffix == '.brd' and b'<eagle' in data[:4096].lower():
        return 'Eagle'
    if suffix == '.pcb' and (data.startswith(b'PCB[') or b'geda' in data[:2048].lower()):
        return 'gEDA'
    return None


class Client:
    def __init__(self, token, max_requests):
        self.token, self.left = token, max_requests

    def get(self, path, binary=False):
        if self.left <= 0:
            raise RuntimeError('request budget reached')
        self.left -= 1
        req = urllib.request.Request(API + path, headers={
            'Accept': 'application/vnd.github+json',
            'User-Agent': 'pcb-public-indexer',
            'X-GitHub-Api-Version': '2022-11-28',
            'Authorization': 'Bearer ' + self.token,
        })
        for attempt in range(3):
            try:
                with urllib.request.urlopen(req, timeout=25) as resp:
                    body = resp.read()
                    return body if binary else json.loads(body)
            except urllib.error.HTTPError as exc:
                if exc.code == 403:
                    try:
                        message = json.loads(exc.read()).get('message', '')
                    except (ValueError, UnicodeDecodeError):
                        message = ''
                    if message.lower() == 'repository access blocked':
                        return None
                if exc.code in (404, 409, 422):
                    return None
                if exc.code in (403, 429) and attempt < 2:
                    reset = int(exc.headers.get('X-RateLimit-Reset', '0'))
                    delay = max(2, min(60, reset - int(time.time()))) if reset else 10 * (attempt + 1)
                    time.sleep(delay)
                    continue
                raise


def q(value):
    return urllib.parse.quote(str(value), safe='')


def get_tree(client, repo, sha, prefix='', depth=0):
    tree = client.get('/repos/' + repo + '/git/trees/' + q(sha) + '?recursive=1')
    if not tree:
        return []
    if not tree.get('truncated'):
        return [(prefix + x['path'], x) for x in tree.get('tree', []) if x['type'] == 'blob']
    # Recursive responses may be truncated. Walk each subtree without dropping files.
    if depth > 24:
        raise RuntimeError('tree nesting limit exceeded')
    shallow = client.get('/repos/' + repo + '/git/trees/' + q(sha))
    if not shallow or shallow.get('truncated'):
        raise RuntimeError('tree cannot be read completely')
    out = []
    for x in shallow['tree']:
        if x['type'] == 'blob':
            out.append((prefix + x['path'], x))
        elif x['type'] == 'tree':
            out.extend(get_tree(client, repo, x['sha'], prefix + x['path'] + '/', depth + 1))
    return out


def state_load(path):
    if path.exists():
        return json.loads(path.read_text())
    return {'since': 0, 'pending': None, 'entries': {}, 'scanned': 0, 'skipped': []}


def save(state, target):
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix('.tmp')
    tmp.write_text(json.dumps(state, sort_keys=True, separators=(',', ':')) + '\n')
    tmp.replace(target)
    entries = sorted(state['entries'].values(), key=lambda x: (x['repo_id'], x['path']))
    out = target.parent / 'pcb_links.jsonl'
    tmp = out.with_suffix('.tmp')
    tmp.write_text(''.join(json.dumps(x, sort_keys=True) + '\n' for x in entries))
    tmp.replace(out)
    (target.parent / 'github_links.txt').write_text(''.join(x['url'] + '\n' for x in entries))


def scan_repo(client, repo, state):
    name, rid = repo['full_name'], repo['id']
    # A repo may have been renamed or deleted. No candidate is falsely marked valid.
    info = client.get('/repos/' + '/'.join(q(part) for part in name.split('/')))
    if not info or not info.get('default_branch'):
        return
    name = info['full_name']
    branch = client.get('/repos/' + name + '/branches/' + q(info['default_branch']))
    if not branch:
        return
    sha = branch['commit']['commit']['tree']['sha']
    for path, node in get_tree(client, name, sha):
        ext = Path(path.lower()).suffix
        if ext not in UNIQUE and ext not in AMBIGUOUS:
            continue
        if node.get('size', 0) > 20_000_000 or node.get('size', 0) < 8:
            continue
        blob = client.get('/repos/' + name + '/git/blobs/' + q(node['sha']))
        if not blob or blob.get('encoding') != 'base64':
            continue
        import base64
        data = base64.b64decode(blob['content'])
        fmt = detect(path, data)
        if not fmt:
            continue
        url = 'https://github.com/' + name + '/blob/' + branch['commit']['sha'] + '/' + urllib.parse.quote(path, safe='/')
        state['entries'][str(rid) + ':' + path] = {
            'repo_id': rid, 'repo': name, 'path': path, 'format': fmt,
            'url': url, 'blob_sha': node['sha'], 'commit': branch['commit']['sha'],
        }


def run(args):
    state_path = Path(args.state)
    state = state_load(state_path)
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
            save(state, state_path)
    finally:
        save(state, state_path)
    print(json.dumps({'repos_this_run': processed, 'repos_total': state['scanned'], 'links': len(state['entries']), 'since': state['since'], 'requests_left': client.left, 'skipped': len(state['skipped'])}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--state', default='data/state.json')
    parser.add_argument('--max-repos', type=int, default=250)
    parser.add_argument('--max-requests', type=int, default=1500)
    run(parser.parse_args())

#!/usr/bin/env python3
"""Resolve BoardRepo public project pages to their linked GitHub repositories."""
import argparse
import json
import os
import re
import subprocess
import time
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit

SITEMAP = 'https://boardrepo.com/sitemap.xml'
NON_PROJECT = {'compare', 'guides', 'news', 'component', 'tag', 'browse', 'docs',
               'connect', 'about', 'contact', 'faq', 'security', 'privacy',
               'terms', 'copyright', 'dashboard', 'settings', 'signin', 'api'}
NAME = re.compile(r'^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$')


def project_links(xml_bytes):
    root = ET.fromstring(xml_bytes)
    links = set()
    for node in root.iter():
        if node.tag.rsplit('}', 1)[-1] != 'loc' or not node.text:
            continue
        parsed = urlsplit(node.text.strip())
        segments = parsed.path.strip('/').split('/')
        if (parsed.scheme == 'https' and parsed.netloc == 'boardrepo.com'
                and len(segments) == 2 and segments[0] not in NON_PROJECT
                and all(segments) and not parsed.query and not parsed.fragment):
            links.add('https://boardrepo.com/' + '/'.join(segments))
    return sorted(links)


class SourceLinks(HTMLParser):
    def __init__(self):
        super().__init__()
        self.anchor = None
        self.candidates = []

    def handle_starttag(self, tag, attrs):
        if tag == 'a':
            self.anchor = [dict(attrs).get('href', ''), '']

    def handle_data(self, data):
        if self.anchor is not None:
            self.anchor[1] += data

    def handle_endtag(self, tag):
        if tag != 'a' or self.anchor is None:
            return
        href, label = self.anchor
        self.anchor = None
        parsed = urlsplit(href)
        parts = parsed.path.strip('/').split('/')
        if parsed.scheme != 'https' or parsed.netloc != 'github.com' or len(parts) < 2:
            return
        repo = '/'.join(parts[:2])
        if not NAME.fullmatch(repo) or parts[0].lower() in {'user-attachments', 'features', 'topics'}:
            return
        # BoardRepo's primary source anchor labels the repository owner/name
        # and often points to a pinned /tree/<commit> snapshot.
        clean_label = label.strip().removeprefix('github.com/')
        if clean_label == repo or (len(parts) == 2 and label.strip() == href):
            self.candidates.append('https://github.com/' + repo)


def source_repo(html):
    parser = SourceLinks()
    parser.feed(html.decode('utf-8', 'replace'))
    return parser.candidates[0] if parser.candidates else None


def download(url):
    return subprocess.run(['curl', '--fail', '--location', '--silent', '--show-error',
                           '--max-time', '30', '--user-agent', 'pcb-public-indexer/1.0', url],
                          check=True, capture_output=True).stdout


def atomic_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(value, sort_keys=True, separators=(',', ':')) + '\n')
    temp.replace(path)


def run(destination, state_file, limit):
    projects = project_links(download(SITEMAP))
    if not projects:
        raise RuntimeError('BoardRepo sitemap has no project URLs; previous index retained')
    state_path = Path(state_file)
    state = json.loads(state_path.read_text()) if state_path.exists() else {'resolved': {}, 'unresolved': []}
    resolved = state['resolved']
    unresolved = set(state['unresolved'])
    todo = [url for url in projects if url not in resolved and url not in unresolved][:limit]
    def fetch(url):
        try:
            repo = source_repo(download(url))
            return url, repo, None
        except (subprocess.CalledProcessError, TimeoutError, ValueError) as exc:
            return url, None, str(exc)

    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = []
        for url in todo:
            futures.append(pool.submit(fetch, url))
            time.sleep(0.5)  # Keep initial request rate around two pages per second.
        for future in as_completed(futures):
            url, repo, error = future.result()
            if repo:
                resolved[url] = repo
            elif error:
                print(f'Retry on next run: {url}: {error}')
            else:
                unresolved.add(url)
    state['unresolved'] = sorted(unresolved)
    atomic_json(state_path, state)
    output = Path(destination)
    output.parent.mkdir(parents=True, exist_ok=True)
    temp = output.with_suffix('.tmp')
    temp.write_text(''.join(url + '\n' for url in sorted(set(resolved.values()))))
    temp.replace(output)
    remaining = len([url for url in projects if url not in resolved and url not in unresolved])
    if os.environ.get('GITHUB_OUTPUT'):
        with open(os.environ['GITHUB_OUTPUT'], 'a') as output_status:
            output_status.write(f'needs_more={str(remaining > 0).lower()}\nremaining={remaining}\n')
    print(f'BoardRepo: {len(resolved)} project pages resolved; {len(unresolved)} without a source link; {len(projects)} listed; {len(todo)} checked this run; {remaining} remaining')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', default='data/boardrepo_links.txt')
    parser.add_argument('--state', default='data/boardrepo_state.json')
    parser.add_argument('--max-pages', type=int, default=300)
    args = parser.parse_args()
    run(args.output, args.state, args.max_pages)

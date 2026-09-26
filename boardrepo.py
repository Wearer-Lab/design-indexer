#!/usr/bin/env python3
"""Index publicly listed BoardRepo project URLs from its sitemap."""
import argparse
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import urlsplit

SITEMAP = 'https://boardrepo.com/sitemap.xml'
NON_PROJECT = {'compare', 'guides', 'news', 'component', 'tag', 'browse', 'docs',
               'connect', 'about', 'contact', 'faq', 'security', 'privacy',
               'terms', 'copyright', 'dashboard', 'settings', 'signin', 'api'}


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


def run(destination):
    content = subprocess.run(['curl', '--fail', '--location', '--silent', '--show-error',
                              '--max-time', '45', '--user-agent', 'pcb-public-indexer/1.0',
                              SITEMAP], check=True, capture_output=True).stdout
    links = project_links(content)
    if not links:
        raise RuntimeError('BoardRepo sitemap contained no public project URLs; keeping previous index')
    output = Path(destination)
    output.parent.mkdir(parents=True, exist_ok=True)
    temp = output.with_suffix('.tmp')
    temp.write_text(''.join(link + '\n' for link in links))
    temp.replace(output)
    print(f'BoardRepo public project links: {len(links)}')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', default='data/boardrepo_links.txt')
    args = parser.parse_args()
    run(args.output)

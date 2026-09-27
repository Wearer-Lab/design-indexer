import unittest
import tempfile
import json
import os
import io
import urllib.error
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace
from crawler import Client, detect, run


class DetectionTest(unittest.TestCase):
    def test_signatures(self):
        self.assertEqual(detect('test.kicad_pcb', b'(kicad_pcb (version 1))'), 'KiCad')
        self.assertIsNone(detect('test.kicad_pcb', b'garbage'))
        self.assertEqual(detect('test.brd', b'<?xml version="1.0"?><eagle version="9">'), 'Eagle')
        self.assertIsNone(detect('test.brd', b'random'))
        self.assertEqual(detect('test.PcbDoc', bytes.fromhex('d0cf11e0a1b11ae1') + b'payload'), 'Altium')


class BlockedRepositoryTest(unittest.TestCase):
    def test_access_blocked_does_not_stall_cursor(self):
        exc = urllib.error.HTTPError('https://api.github.com/repos/reinh/dm', 403,
                                     'Forbidden', {}, io.BytesIO(b'{"message":"Repository access blocked"}'))
        with patch('crawler.urllib.request.urlopen', side_effect=exc):
            self.assertIsNone(Client('test', 5).get('/repos/reinh/dm'))


class PageBoundaryTest(unittest.TestCase):
    def test_fetches_next_page_after_pending_drains(self):
        pages = [
            [{'id': 1, 'full_name': 'a/one'}, {'id': 2, 'full_name': 'a/two'}],
            [{'id': 3, 'full_name': 'a/three'}],
        ]
        paths = []

        def fake_get(client, path, binary=False):
            paths.append(path)
            return pages.pop(0) if pages else []

        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / 'state.json'
            with patch.dict(os.environ, {'GITHUB_TOKEN': 'test'}), \
                 patch('crawler.Client.get', fake_get), \
                 patch('crawler.scan_repo', lambda *args: None):
                run(SimpleNamespace(state=str(state), max_repos=3, max_requests=30))
            saved = json.loads(state.read_text())
            self.assertEqual(saved['scanned'], 3)
            self.assertEqual(saved['since'], 3)
            self.assertEqual(paths, [
                '/repositories?since=0&per_page=100',
                '/repositories?since=2&per_page=100',
            ])


if __name__ == '__main__':
    unittest.main()

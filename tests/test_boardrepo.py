import unittest
from boardrepo import project_links, source_repo


class BoardRepoTest(unittest.TestCase):
    def test_only_project_urls(self):
        data = b'''<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
          <url><loc>https://boardrepo.com/alice/board</loc></url>
          <url><loc>https://boardrepo.com/tag/kicad</loc></url>
          <url><loc>https://boardrepo.com/news/launch</loc></url>
          <url><loc>https://boardrepo.com/alice/board</loc></url>
          <url><loc>https://evil.example/alice/board</loc></url>
        </urlset>'''
        self.assertEqual(project_links(data), ['https://boardrepo.com/alice/board'])

    def test_source_uses_labeled_project_link_not_readme_links(self):
        html = b'''<a href="https://github.com/other/unrelated">README</a>
          <a href="https://github.com/0101shift/project_oak/tree/abc123">0101shift/project_oak</a>'''
        self.assertEqual(source_repo(html), 'https://github.com/0101shift/project_oak')
        self.assertIsNone(source_repo(b'<a href="https://github.com/other/unrelated">README</a>'))


if __name__ == '__main__':
    unittest.main()

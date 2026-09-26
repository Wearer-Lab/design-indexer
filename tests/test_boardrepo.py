import unittest
from boardrepo import project_links


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


if __name__ == '__main__':
    unittest.main()

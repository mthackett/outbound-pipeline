import os
import json
import tempfile
import unittest
from job_pipeline.domain.models import QuickLink
from job_pipeline.domain.services import QuickLinksService


class TestQuickLinksService(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.test_json_path = os.path.join(self.temp_dir.name, "test_quicklinks.json")

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_default_quicklinks_structure(self):
        defaults = QuickLinksService.get_default_quicklinks()
        self.assertTrue(len(defaults) >= 3)
        titles = [l.title for l in defaults]
        self.assertIn("LinkedIn Profile", titles)
        self.assertIn("GitHub Portfolio", titles)
        for link in defaults:
            self.assertTrue(link.url.startswith("http"))
            self.assertTrue(link.id)

    def test_load_when_file_not_found_creates_defaults(self):
        self.assertFalse(os.path.exists(self.test_json_path))
        links = QuickLinksService.load_quicklinks(self.test_json_path)
        self.assertTrue(len(links) >= 3)
        # Should now exist because defaults were written
        self.assertTrue(os.path.exists(self.test_json_path))

    def test_save_and_reload_custom_links(self):
        custom_links = [
            QuickLink(
                id="link-test-1",
                title="My Custom Portfolio",
                url="https://custom-portfolio.io",
                category="Portfolio",
                icon="🚀"
            ),
            QuickLink(
                id="link-test-2",
                title="Substack Newsletter",
                url="https://newsletter.example.com",
                category="Other",
                icon="✍️"
            )
        ]
        saved = QuickLinksService.save_quicklinks(custom_links, self.test_json_path)
        self.assertTrue(saved)

        reloaded = QuickLinksService.load_quicklinks(self.test_json_path)
        self.assertEqual(len(reloaded), 2)
        self.assertEqual(reloaded[0].title, "My Custom Portfolio")
        self.assertEqual(reloaded[0].url, "https://custom-portfolio.io")
        self.assertEqual(reloaded[0].icon, "🚀")
        self.assertEqual(reloaded[1].title, "Substack Newsletter")

    def test_format_clipboard_bundle(self):
        links = [
            QuickLink(title="LinkedIn", url="https://linkedin.com/in/test"),
            QuickLink(title="GitHub", url="https://github.com/test")
        ]
        bundle = QuickLinksService.format_clipboard_bundle(links)
        expected = "LinkedIn: https://linkedin.com/in/test\nGitHub: https://github.com/test"
        self.assertEqual(bundle, expected)


if __name__ == "__main__":
    unittest.main()

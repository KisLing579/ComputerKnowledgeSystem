import tempfile
import unittest
from pathlib import Path

from rendering.manim.render import quarantine_invalid_text_cache


class RenderCacheTests(unittest.TestCase):
    def test_only_damaged_svg_is_quarantined(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cache = root / "texts"
            cache.mkdir()
            (cache / "valid.svg").write_text('<svg xmlns="http://www.w3.org/2000/svg"/>')
            (cache / "empty.svg").write_text("")
            (cache / "partial.svg").write_text("<svg>")
            self.assertEqual(quarantine_invalid_text_cache(root), 2)
            self.assertTrue((cache / "valid.svg").exists())
            self.assertEqual(len(list(cache.glob("*.bak"))), 2)
            self.assertEqual(quarantine_invalid_text_cache(root), 0)

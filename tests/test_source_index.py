import unittest
from unittest.mock import patch

from casehunter.discovery.source_index import expand_year_index, is_year_index


class SourceIndexTests(unittest.TestCase):
    def test_year_index_detection(self):
        self.assertTrue(is_year_index("https://www.leylobby.gob.cl/instituciones/AM010/audiencias/2026"))
        self.assertFalse(is_year_index("https://www.leylobby.gob.cl/instituciones/AM010/audiencias/2026/2701"))

    def test_expand_year_index_keeps_subject_links_only(self):
        html = """<table><tr><td><a href='/instituciones/AM010/audiencias/2026/2701'>Ver Detalle</a></td></tr></table>
        <a href='/instituciones/AM010/audiencias/2026/2701/999'>audiencia</a>"""
        fake = {"source_url":"https://www.leylobby.gob.cl/instituciones/AM010/audiencias/2026","raw_html":html,"text":"x"}
        with patch("casehunter.discovery.source_index.fetch_public_document", return_value=fake):
            result = expand_year_index(fake["source_url"])
        self.assertEqual(result, ["https://www.leylobby.gob.cl/instituciones/AM010/audiencias/2026/2701"])


if __name__ == "__main__":
    unittest.main()

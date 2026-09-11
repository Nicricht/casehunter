import unittest
from unittest.mock import patch

from casehunter.discovery.collector import fetch_public_document
from casehunter.watch_source_adapters import discover_official_links, source_kind


class FakeHeaders:
    def __init__(self, content_type="application/pdf", charset=None):
        self.content_type = content_type
        self.charset = charset

    def get_content_type(self):
        return self.content_type

    def get_content_charset(self):
        return self.charset


class FakeResponse:
    def __init__(self, body=b"%PDF-demo", url="https://municipio.gob.cl/resolucion-pago.pdf", content_type="application/pdf"):
        self.body = body
        self.url = url
        self.headers = FakeHeaders(content_type)

    def read(self, *_args):
        return self.body

    def geturl(self):
        return self.url

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class PdfWatchTests(unittest.TestCase):
    @patch("casehunter.discovery.collector.extract_pdf_text")
    @patch("casehunter.discovery.collector.urlopen")
    def test_public_document_extracts_native_pdf_text(self, mocked_urlopen, mocked_extract):
        mocked_urlopen.return_value = FakeResponse()
        mocked_extract.return_value = "Resolución de pago proveedor Alembic"

        result = fetch_public_document("https://municipio.gob.cl/resolucion-pago.pdf")

        self.assertEqual(result["content_type"], "application/pdf")
        self.assertIn("Resolución de pago", result["text"])
        self.assertIsNone(result["raw_html"])
        mocked_extract.assert_called_once()

    @patch("casehunter.discovery.collector.extract_pdf_text")
    @patch("casehunter.discovery.collector.urlopen")
    def test_scanned_pdf_is_not_silently_accepted(self, mocked_urlopen, mocked_extract):
        mocked_urlopen.return_value = FakeResponse(url="https://municipio.gob.cl/decreto-pago.pdf")
        mocked_extract.side_effect = ValueError("El PDF no contiene texto nativo extraíble. Puede requerir OCR.")

        with self.assertRaisesRegex(ValueError, "OCR"):
            fetch_public_document("https://municipio.gob.cl/decreto-pago.pdf")

    def test_relevant_official_pdf_can_be_discovered(self):
        html = '<a href="/docs/resolucion-pago-proveedores.pdf">Resolución</a>'
        links = discover_official_links(html, "https://municipio.gob.cl/transparencia")
        self.assertEqual(links, ["https://municipio.gob.cl/docs/resolucion-pago-proveedores.pdf"])
        self.assertEqual(source_kind(links[0]), "OFFICIAL_PDF")

    def test_generic_official_pdf_is_not_auto_added(self):
        html = '<a href="/docs/manual-usuario.pdf">Manual</a>'
        links = discover_official_links(html, "https://municipio.gob.cl/transparencia")
        self.assertEqual(links, [])


if __name__ == "__main__":
    unittest.main()

import unittest
from io import BytesIO

from pypdf import PdfWriter

from casehunter.discovery.collector import extract_pdf_text


def blank_pdf_bytes():
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


class PdfOcrTests(unittest.TestCase):
    def test_scanned_pdf_uses_ocr_fallback(self):
        raw = blank_pdf_bytes()
        calls = []

        def fake_ocr(value):
            calls.append(len(value))
            return "ALEMBIC PHARMACEUTICALS factura pendiente compromiso de pago"

        text = extract_pdf_text(raw, ocr_engine=fake_ocr)
        self.assertIn("ALEMBIC PHARMACEUTICALS", text)
        self.assertEqual(len(calls), 1)

    def test_ocr_can_be_disabled(self):
        raw = blank_pdf_bytes()
        with self.assertRaises(ValueError):
            extract_pdf_text(raw, allow_ocr=False)

    def test_tiny_native_layer_prefers_richer_ocr(self):
        # A blank PDF exercises the same branch as scanned PDFs with an
        # insignificant native text layer. The injected engine keeps the unit
        # test independent from the system Tesseract binary.
        raw = blank_pdf_bytes()
        text = extract_pdf_text(raw, ocr_engine=lambda _raw: "pago pendiente $5.178.271 solicitud de recursos")
        self.assertIn("5.178.271", text)


if __name__ == "__main__":
    unittest.main()

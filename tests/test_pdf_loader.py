import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools.pdf_loader import _get_pdf_page_count, chunk_pages


class PdfLoaderTests(unittest.TestCase):
    def test_chunk_pages_returns_empty_for_no_pages(self):
        self.assertEqual(chunk_pages([]), [])

    def test_chunk_pages_preserves_page_metadata(self):
        pages = [{"page": 1, "text": "First page content."}]
        chunks = chunk_pages(pages)
        self.assertTrue(chunks)
        self.assertTrue(all(chunk["page"] == 1 for chunk in chunks))

    @patch("tools.pdf_loader.PyPDF2.PdfReader")
    def test_page_count_includes_non_text_pages(self, reader_cls):
        reader_cls.return_value.pages = [object(), object(), object()]
        with tempfile.NamedTemporaryFile(suffix=".pdf") as pdf:
            self.assertEqual(_get_pdf_page_count(Path(pdf.name)), 3)
        reader_cls.assert_called_once()


if __name__ == "__main__":
    unittest.main()

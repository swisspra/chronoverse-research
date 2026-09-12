"""Bounded read-only PDF extraction worker; never executes PDF actions or OCR."""
from io import BytesIO
import json
import sys


def main():
    try:
        import resource
        resource.setrlimit(resource.RLIMIT_CPU, (15, 15))
        resource.setrlimit(resource.RLIMIT_AS, (1024 * 1024 * 1024, 1024 * 1024 * 1024))
    except (ImportError, OSError, ValueError):
        # Parent still enforces wall time, input bytes, page and extracted-character limits.
        pass
    try:
        from pypdf import PdfReader
        data = sys.stdin.buffer.read(10 * 1024 * 1024 + 1)
        if len(data) > 10 * 1024 * 1024:
            raise ValueError("PDF exceeds 10 MiB upload limit")
        reader = PdfReader(BytesIO(data), strict=False)
        if reader.is_encrypted:
            raise ValueError("Encrypted PDF is unsupported; upload an unlocked text PDF")
        if len(reader.pages) > 200:
            raise ValueError("PDF exceeds 200-page limit")
        pages, empty, total = [], [], 0
        for index, page in enumerate(reader.pages, 1):
            text = page.extract_text() or ""
            total += len(text)
            if total > 2_000_000:
                raise ValueError("PDF extracted text exceeds 2,000,000-character limit")
            if text.strip():
                pages.append({"page":index,"text":text})
            else:
                empty.append(index)
        if not pages:
            raise ValueError("PDF has no extractable text. Scanned/image-only PDFs require OCR before upload")
        print(json.dumps({"pages":pages,"empty_pages":empty}))
    except Exception as exc:
        print(json.dumps({"error":f"PDF extraction failed: {exc}"}))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

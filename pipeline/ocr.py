"""Text of an image or of scanned PDF pages, by OCR (RapidOCR, which reads Traditional Chinese).

pipeline/fetch.py runs it in an environment of its own, only for what has no text:
  uv run -q --isolated --with rapidocr==3.10.0 --with onnxruntime==1.32.0 --with pymupdf python -I pipeline/ocr.py <file> [<page>,...]
(the versions are pinned in fetch.py, OCR_RAPIDOCR and OCR_ONNX)
Prints a JSON list: the text of each page asked for (0-based), or of the image, lines top to bottom.
"""
import json
import logging
import sys

logging.disable(logging.CRITICAL)
from rapidocr import RapidOCR  # noqa: E402

engine = RapidOCR()


def read(image) -> str:
    return "\n".join(engine(image).txts or [])


path = sys.argv[1]
with open(path, "rb") as f:
    head = f.read(5)
if head == b"%PDF-":
    import pymupdf  # noqa: PLC0415

    doc = pymupdf.open(path)
    pages = [int(p) for p in sys.argv[2].split(",")] if len(sys.argv) > 2 else range(doc.page_count)
    out = [read(doc[p].get_pixmap(dpi=200).tobytes("png")) for p in pages]
else:
    out = [read(path)]
print(json.dumps(out, ensure_ascii=False))

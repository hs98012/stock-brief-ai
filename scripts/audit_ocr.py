#!/usr/bin/env python3
"""Read-only OCR comparison on the same original PDFs; never rewrites DB pages."""
import argparse
import hashlib
import json
import time
from pathlib import Path

import pytesseract
from pdf2image import convert_from_path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pdf-dir", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--dpi", type=int, nargs="+", default=[200, 300])
    args = parser.parse_args()
    results = []
    for document in json.loads(args.manifest.read_text()):
        path = args.pdf_dir / document["filename"]
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest != document["sha256"]:
            raise ValueError(f"PDF hash mismatch: {path.name}")
        for dpi in args.dpi:
            started = time.monotonic()
            image = convert_from_path(str(path), dpi=dpi, first_page=1, last_page=1)[0]
            text = pytesseract.image_to_string(image, lang="kor+eng")
            results.append({"filename": path.name, "sha256": digest, "page": 1, "dpi": dpi,
                "seconds": round(time.monotonic() - started, 3), "text": text})
    print(json.dumps({"tesseract_version": str(pytesseract.get_tesseract_version()), "results": results},
        ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

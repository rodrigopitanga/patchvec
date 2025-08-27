# (C) 2025 Rodrigo Rodrigues da Silva <rodrigopitanga@posteo.net>
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations
import io, csv
from .config import CFG
from typing import Dict, Iterable, Tuple
from pypdf import PdfReader

TXT_CHUNK_SIZE = int(CFG.get("preprocess.txt_chunk_size", 1000))
TXT_CHUNK_OVERLAP = int(CFG.get("preprocess.txt_chunk_overlap", 200))

def _chunks(text: str, size: int = TXT_CHUNK_SIZE, overlap: int = TXT_CHUNK_OVERLAP):
    text = text or ""
    step = max(size - overlap, 1)
    i = 0
    while i < len(text):
        yield text[i : i + size]
        i += step

def preprocess(filename: str, content: bytes):
    """
    Yields (local_id, text, extra_meta):
    - PDF: one chunk per page
    - TXT: char-based chunks
    - CSV: one chunk per row ("; " join)
    """
    ext = filename.lower().rsplit(".", 1)[-1] if "." in filename else ""
    if ext == "pdf":
        reader = PdfReader(io.BytesIO(content))
        for i, page in enumerate(reader.pages):
            text = page.extract_text() or ""
            yield f"page_{i}", text, {"page": i}
    elif ext == "txt":
        text = content.decode("utf-8", errors="ignore")
        for i, chunk in enumerate(_chunks(text)):
            yield f"chunk_{i}", chunk, {"chunk": i}
    elif ext == "csv":
        text = content.decode("utf-8", errors="ignore")
        r = csv.reader(io.StringIO(text))
        for i, row in enumerate(r):
            yield f"row_{i}", "; ".join("" if c is None else str(c) for c in row), {"row": i}
    else:
        raise ValueError(f"unsupported file type: {ext or 'unknown'}")

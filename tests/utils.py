# (C) 2025 Rodrigo Rodrigues da Silva <rodrigopitanga@posteo.net>
# SPDX-License-Identifier: GPL-3.0-or-later

import os, json

class FakeEmbeddings:
    """Tiny in-memory txtai. Keeps interface you use in tests."""
    def __init__(self, config):  # config unused
        self._docs = {}  # rid -> (text, meta_json)

    def index(self, docs):
        for rid, text, meta_json in docs:
            assert isinstance(meta_json, str)
            self._docs[rid] = (text, meta_json)

    def search(self, query, k):
        q = (query or "").lower()
        out = []
        for rid, (text, _) in self._docs.items():
            if q in (text or "").lower():
                out.append({"id": rid, "score": float(len(q)), "text": text})
        return out[:k]

    def lookup(self, ids):
        return {rid: self._docs.get(rid, ("", ""))[0] for rid in ids}

    def delete(self, ids):
        for rid in ids:
            self._docs.pop(rid, None)

    def save(self, path):
        os.makedirs(path, exist_ok=True)
        with open(os.path.join(path, "_fake_index.json"), "w", encoding="utf-8") as f:
            json.dump(self._docs, f, ensure_ascii=False)

    def load(self, path):
        p = os.path.join(path, "_fake_index.json")
        if os.path.isfile(p):
            with open(p, "r", encoding="utf-8") as f:
                self._docs = json.load(f)

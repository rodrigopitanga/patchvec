<!-- (C) 2025 Rodrigo Rodrigues da Silva <rodrigopitanga@posteo.net> -->
<!-- SPDX-License-Identifier: GPL-3.0-or-later -->

vvv# PatchVec test suite (minimal per spec)

- pytest + fastapi.testclient
- DummyStore in-memory injected via `app.state.store`
- Covers: health; create/delete collection; TXT upload; search POST & GET; reupload same docid (calls purge); auth static (Bearer); CLI flow
- No source-code changes; tests only tweak `CFG._data`

## Run
pip install -r requirements-test.txt
pytest -q

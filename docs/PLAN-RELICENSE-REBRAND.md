<!-- (C) 2026 Rodrigo Rodrigues da Silva <rodrigo@flowlexi.com> -->
<!-- SPDX-License-Identifier: AGPL-3.0-or-later -->

# PLAN-RELICENSE-REBRAND

Plan for relicensing (AGPLv3+), author contact update, and staged rebranding.

## Decisions

- License: **AGPL-3.0-or-later** (verbatim license text in `LICENSE`).
- Author contact email: **rodrigo@flowlexi.com**.
- Product name: **PaveDB**.
- Package name can remain **`pave`**.
- Rebrand in two phases:
  - **0.5.9** internal-only (code, prefixes, metadata).
  - **0.6.0** external/user-visible (docs, logs, UI, messages).

## Relicensing scope (AGPLv3+)

### Required updates

- `LICENSE` — replace with verbatim AGPLv3-or-later text.
- SPDX headers — already `AGPL-3.0-or-later` across repo; no change needed:
  - `pave/**/*.py`, `tests/**/*.py`, `benchmarks/**/*.py`, `scripts/**/*.py`
  - `README*.md`, `ABOUT.md`, `ROADMAP.md`, `CHANGELOG.md`, `CONTRIBUTING.md`
  - `docs/*.md`, `pave/assets/ui.html`
  - `pavecli.sh`, `pavesrv.sh`, `pave.toml`, `requirements-cpu.txt`,
    `docker-compose.yml`, `setup.py`, etc.
- `setup.py`:
  - `license="AGPL-3.0-or-later"`.
  - Update classifiers if license classifiers are added later.
- License mentions in docs/UI:
  - `README.md`, `ABOUT.md`, `README-benchmarks.md`
  - `pave/ui.py` (`license_name`, `license_url`)
  - `pave/assets/ui.html` (license link placeholder)

### Author email change

Replace `rodrigopitanga@posteo.net` with `rodrigo@flowlexi.com` everywhere.

## Rebrand scope (PaveDB)

### Phase 1 — Internal (0.5.9)

Goal: update internal identifiers and metadata without changing external docs.

Likely touchpoints:

- Internal prefixes:
  - Metrics prefix (`pave/metrics.py`, tests asserting prefix).
  - Logger name (`pave/config.py`).
  - Temp/archive prefixes (`pave/service.py`, `pave/cli.py`).
- Packaging + metadata:
  - `setup.py` name/description/URLs as needed (package name can stay `pave`).
  - `pave.toml` (if it contains project name).
- CI + container references:
  - `.gitlab-ci.yml` (if internal metadata or package names used).
  - `Dockerfile`, `docker-compose.yml` (only if internal names are embedded).
- Tests that assert name or prefix:
  - `tests/test_metrics.py`
  - `tests/test_upload_search_txt.py`

Non-goal: user-facing strings (saved for Phase 2).

### Phase 2 — External (0.6.0)

Goal: update user-visible branding and docs.

Touchpoints:

- Docs and public references:
  - `README.md`, `ABOUT.md`, `CHANGELOG.md`, `ROADMAP.md`,
    `README-benchmarks.md`, `docs/*.md`
  - Public URLs and install snippets.
- UI / logs / CLI:
  - `pave/main.py` startup banner and log messages.
  - `pave/ui.py`, `pave/assets/ui.html`.
- Docker/pip guidance in docs:
  - Image names, URLs, CLI examples.

## Notes

- Package name remains `pave` for now; rebrand is primarily product-facing.
- Internal rebrand must not break compatibility without explicit migration.
- External rebrand should land only after internal names are stable.

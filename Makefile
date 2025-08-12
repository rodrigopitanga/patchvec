# PatchVec — Makefile
# External name: patchvec ; internal package: pave
# CPU-only by default for dev. Set USE_GPU=1 to install GPU deps instead.

PYTHON          ?= python
PIP             ?= $(PYTHON) -m pip
UVICORN         ?= $(PYTHON) -m uvicorn
PKG_NAME        ?= patchvec
PKG_INTERNAL    ?= pave

VENV            ?= .venv
PYTHON_BIN      ?= $(VENV)/bin/python
PIP_BIN         ?= $(VENV)/bin/pip

HOST            ?= 0.0.0.0
PORT            ?= 8086
WORKERS         ?= 1
RELOAD          ?= 1
LOG_LEVEL       ?= info

# Requirements flavor (cpu default)
USE_GPU         ?= 0
REQ_MAIN_CPU    ?= requirements-cpu.txt
REQ_MAIN_GPU    ?= requirements.txt
REQ_TEST        ?= requirements-test.txt

# Version helpers
VERSION         ?= $(shell sed -n 's/^ *version="\([^"]*\)".*/\1/p' setup.py | head -1)
ARCHIVE_BASENAME := $(PKG_NAME)-$(VERSION)
DIST_DIR        := dist
BUILD_DIR       := build
ART_DIR         := artifacts

.PHONY: help
help:
	@echo "🍰 PatchVec Make Targets"
	@echo "  venv            Create local virtualenv (.venv)"
	@echo "  install         Install runtime deps (CPU by default; USE_GPU=1 for GPU)"
	@echo "  install-dev     Install dev/test deps (CPU by default; USE_GPU=1 for GPU)"
	@echo "  test            Run pytest"
	@echo "  serve           Run API server (dev, autoreload)"
	@echo "  cli             Run CLI (pass ARGS='...')"
	@echo "  bump            Bump file versions everywhere"
	@echo "  build           Build sdist+wheel to ./dist"
	@echo "  package         Build artifacts (.zip + .tar.gz) to ./artifacts"
	@echo "  clean           Remove caches"
	@echo "  clean-dist      Remove dist/build/artifacts"
	@echo "  release         Bump/tag/push; also updates Dockerfile & compose (VERSION=x.y.z)"

$(VENV)/bin/activate:
	$( PYTHON) -m venv $(VENV)
	@echo "Run '. $(VENV)/bin/activate' to activate the venv"

.PHONY: venv
venv: $(VENV)/bin/activate

define install_main
	@if [ "$(USE_GPU)" = "1" ]; then \
	  echo "Installing GPU deps from $(REQ_MAIN_GPU)"; \
	  $(PIP_BIN) install --upgrade pip; \
	  $(PIP_BIN) install -r $(REQ_MAIN_GPU) | grep -v "Requirement already satisfied"; \
	else \
	  echo "Installing CPU deps from $(REQ_MAIN_CPU)"; \
	  $(PIP_BIN) install --upgrade pip; \
	  $(PIP_BIN) install -r $(REQ_MAIN_CPU) | grep -v "Requirement already satisfied"; \
	fi
endef

.PHONY: install
install: venv
	$(install_main)
	@echo "✅ Runtime deps installed."

.PHONY: install-dev
install-dev: install
	@if [ -f "$(REQ_TEST)" ]; then $(PIP_BIN) install -r $(REQ_TEST) | grep -v "Requirement already satisfied"; else $(PIP_BIN) install pytest httpx | grep -v "Requirement already satisfied"; fi
	@echo "✅ Dev/test deps installed."

.PHONY: test
test: install-dev
	PATCHVEC_CONFIG=./config.yml.example PYTHONPATH=. $(PYTHON_BIN) -m pytest -q

.PHONY: serve
serve: install
	@echo "Starting server on $(HOST):$(PORT) (reload=$(RELOAD), workers=$(WORKERS))"
	PYTHONPATH=. PATCHVEC_CONFIG=./config.yml.example \
	$(UVICORN) $(PKG_INTERNAL).main:app --host $(HOST) --port $(PORT) --log-level $(LOG_LEVEL) $(if $(filter 1,$(RELOAD)),--reload,) --workers $(WORKERS)

.PHONY: cli
cli: install
	PYTHONPATH=. PATCHVEC_CONFIG=./config.yml.example \
	$(PYTHON_BIN) -m $(PKG_INTERNAL).cli $(ARGS)

.PHONY: bump
bump:
	@if [ -z "$(VERSION)" ]; then \
	  echo "Error: VERSION is not set. Usage: make bump VERSION=0.5.4"; \
	  exit 1; \
	fi
	@echo "Bumping version to $(VERSION)..."
	# setup.py: version="x.y.z"
	@if [ -f setup.py ]; then \
	  sed -i -E 's/(version=)\"[0-9]+\.[0-9]+\.[0-9]+\"/\1"$(VERSION)"/' setup.py; \
	fi
	# pave/main.py: VERSION = "x.y.z"
	@if [ -f pave/main.py ] && grep -qE '^VERSION\s*=' pave/main.py; then \
	  sed -i -E 's/^VERSION\s*=.*/VERSION = "$(VERSION)"/' pave/main.py; \
	fi
	# Dockerfile: ARG APP_VERSION or LABEL version
	@if [ -f Dockerfile ]; then \
	  if grep -qE '^ARG +APP_VERSION=' Dockerfile; then \
	    sed -i -E 's/^(ARG +APP_VERSION=).*/\1$(VERSION)/' Dockerfile; \
	  fi; \
	  if grep -qE 'LABEL +version=' Dockerfile; then \
	    sed -i -E 's/(LABEL +version=)\"[^\"]*\"/\1"$(VERSION)"/' Dockerfile; \
	  fi; \
	fi
	# docker-compose.yml: image: patchvec:x.y.z
	@if [ -f docker-compose.yml ] && grep -qE 'image:\s*patchvec:' docker-compose.yml; then \
	  sed -i -E 's/(image:\s*patchvec:).*/\1$(VERSION)/' docker-compose.yml; \
	fi
	# README.md example tags for docker build/run
	@if [ -f README.md ] && grep -q 'docker build -t patchvec:' README.md; then \
	  sed -i -E 's@(docker build -t patchvec:).*@\1$(VERSION) \.@' README.md; \
	fi
	@if [ -f README.md ] && grep -q 'docker run --rm -p 8080:8080 -v $$\(pwd\)/data:/app/data patchvec:' README.md; then \
	  sed -i -E 's@(docker run --rm -p 8080:8080 -v \$$\(pwd\)/data:/app/data patchvec:).*@\1$(VERSION)@' README.md; \
	fi
	@echo "✅ Bumped to $(VERSION). Review changes, then commit:"
	@echo "   git add -A && git commit -m \"chore: bump version to $(VERSION)\""

.PHONY: build
build: install
	rm -rf $(DIST_DIR) $(BUILD_DIR)
	$(PYTHON_BIN) -m pip install build twine
	$(PYTHON_BIN) -m build
	$(PYTHON_BIN) -m twine check $(DIST_DIR)/*

$(ART_DIR):
	mkdir -p $(ART_DIR)

.PHONY: package
package: build $(ART_DIR)
	@echo "Creating archives for $(ARCHIVE_BASENAME)"
	# .zip of source tree (exclude venv, dist, build, artifacts, .git)
	zip -rq $(ART_DIR)/$(ARCHIVE_BASENAME).zip . -x "$(VENV)/*" "$(DIST_DIR)/*" "$(BUILD_DIR)/*" "$(ART_DIR)/*" ".git/*" || true
	# .tar.gz from sdist if available, else from tree
	if ls $(DIST_DIR)/*.tar.gz >/dev/null 2>&1; then \
	  cp $(DIST_DIR)/*.tar.gz $(ART_DIR)/$(ARCHIVE_BASENAME).tar.gz; \
	else \
	  tar --exclude="$(VENV)" --exclude="$(DIST_DIR)" --exclude="$(BUILD_DIR)" --exclude="$(ART_DIR)" --exclude=".git" \
	    -czf $(ART_DIR)/$(ARCHIVE_BASENAME).tar.gz . ; \
	fi
	@echo "Artifacts available in $(ART_DIR)/"

.PHONY: clean
clean:
	rm -rf __pycache__ */__pycache__ *.pyc *.pyo *.pyd .pytest_cache .ruff_cache .mypy_cache .pytype
	find . -name '*.egg-info' -prune -exec rm -rf {} +
	@echo "Cleaned caches."

.PHONY: clean-dist
clean-dist:
	rm -rf $(DIST_DIR) $(BUILD_DIR) $(ART_DIR)
	@echo "Removed dist/build/artifacts."


# Release flow:
# - ensure clean tree
# - (optional) bump versions (setup.py, pave/main.py, Dockerfile, compose, README tags) unless SKIP_BUMP=1
# - update CHANGELOG with sorted commit subjects since last tag
# - run tests (must pass) and build (must succeed); otherwise revert
# - commit, tag, push
# - package artifacts (.zip .tar.gz)
.PHONY: release
release:
	@if [ -z "$(VERSION)" ]; then echo "Set VERSION=x.y.z (e.g., 'make release VERSION=0.5.4')"; exit 1; fi
	@if [ -n "$$(git status --porcelain)" ]; then echo "Working tree not clean"; exit 1; fi
	@set -e; \
	LAST_TAG=$$(git describe --tags --abbrev=0 2>/dev/null || true); \
	revert_changes() { \
	  echo "Reverting version bumps and changelog..."; \
	  git restore --staged CHANGELOG.md setup.py README.md Dockerfile docker-compose.yml $(PKG_INTERNAL)/main.py 2>/dev/null || true; \
	  git checkout -- CHANGELOG.md setup.py README.md Dockerfile docker-compose.yml $(PKG_INTERNAL)/main.py 2>/dev/null || true; \
	}; \
	# 1) Bump (unless SKIP_BUMP=1)
	if [ "$(SKIP_BUMP)" != "1" ]; then \
	  echo "Bumping to $(VERSION) via 'make bump'..."; \
	  $(MAKE) bump VERSION=$(VERSION); \
	fi; \
	# 2) Update CHANGELOG with a Python helper (no shell-escape issues)
	$(PYTHON_BIN) scripts/update_changelog.py $(VERSION) || { echo "Changelog generation failed"; exit 1; } \
	# Stage files so we can revert if tests/build fail
	git add CHANGELOG.md setup.py README.md Dockerfile docker-compose.yml $(PKG_INTERNAL)/main.py 2>/dev/null || true; \
	# 3) Tests
	echo "Running tests..."; \
	$(MAKE) test || { echo "Tests failed."; revert_changes; exit 1; }; \
	# 4) Build dists
	echo "Building dists..."; \
	$(MAKE) build || { echo "Build failed."; revert_changes; exit 1; }; \
	# 5) Commit, tag, push
	git commit -m "chore(release): v$(VERSION)"; \
	git tag v$(VERSION); \
	git push origin HEAD --tags; \
	# 6) Package artifacts
	$(MAKE) package; \
	echo "Release v$(VERSION) done."


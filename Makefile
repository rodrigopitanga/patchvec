# PatchVec — Makefile
# External name: patchvec ; internal package: pave
# CPU-only by default for dev. Set USE_GPU=1 to install GPU deps instead.

PYTHON          ?= python3
PIP             ?= $(PYTHON) -m pip
UVICORN         ?= uvicorn
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

# Docker / publish
REGISTRY        ?=                  # e.g. registry.gitlab.com/<group>/patchvec
IMAGE_NAME      ?= $(PKG_NAME)
DOCKERFILE      ?= Dockerfile
CONTEXT         ?= .
PUSH_LATEST     ?= 1
DOCKER_PUBLISH  ?= 0               # set to 1 to publish during `make release`

.PHONY: help
help:
	@echo "🍰 PatchVec Make Targets"
	@echo "  venv            Create local virtualenv (.venv)"
	@echo "  install         Install runtime deps (CPU by default; USE_GPU=1 for GPU)"
	@echo "  install-dev     Install dev/test deps (CPU by default; USE_GPU=1 for GPU)"
	@echo "  test            Run pytest"
	@echo "  serve           Run API server (dev, autoreload) — bootstraps everything"
	@echo "  cli             Run CLI (pass ARGS='...')"
	@echo "  bump            Bump file versions everywhere"
	@echo "  build           Build sdist+wheel to ./dist"
	@echo "  package         Build artifacts (.zip + .tar.gz) to ./artifacts"
	@echo "  docker-build    Build Docker image (VERSION=x.y.z)"
	@echo "  docker-push     Push Docker image (VERSION=x.y.z, REGISTRY=...)"
	@echo "  clean           Remove caches"
	@echo "  clean-dist      Remove dist/build/artifacts"
	@echo "  release         Bump/tag/push; updates CHANGELOG; optional Docker publish"

# -------- venv (robust, idempotent) --------
$(VENV)/.created:
	@if ! command -v $(PYTHON) >/dev/null 2>&1; then echo "ERROR: '$(PYTHON)' not found"; exit 127; fi
	@echo "Creating virtual environment in $(VENV) using: $(PYTHON)"
	@$(PYTHON) -m venv $(VENV)
	@$(PIP_BIN) install -q --upgrade pip
	@touch $@

.PHONY: venv
venv: $(VENV)/.created
	@echo "✅ Virtual env ready: $(VENV)"

# -------- install --------
define install_main
	@if [ "$(USE_GPU)" = "1" ]; then \
	  echo "Installing GPU deps from $(REQ_MAIN_GPU)"; \
	  $(PIP_BIN) install -q -r $(REQ_MAIN_GPU); \
	else \
	  echo "Installing CPU deps from $(REQ_MAIN_CPU)"; \
	  $(PIP_BIN) install -q -r $(REQ_MAIN_CPU); \
	fi
endef

.PHONY: install
install: venv
	$(install_main)
	@echo "✅ Runtime deps installed."

.PHONY: install-dev
install-dev: install
	@if [ -f "$(REQ_TEST)" ]; then $(PIP_BIN) install -q -r $(REQ_TEST); else $(PIP_BIN) install -q pytest httpx; fi
	@echo "✅ Dev/test deps installed."

# -------- test / serve / cli --------
.PHONY: test
test: install-dev
	PATCHVEC_CONFIG=./config.yml.example PYTHONPATH=. $(PYTHON_BIN) -m pytest -q

.PHONY: serve
serve: install
	@echo "Starting server on $(HOST):$(PORT) (reload=$(RELOAD), workers=$(WORKERS))"
	PYTHONPATH=. PATCHVEC_CONFIG=./config.yml.example \
	$(PYTHON_BIN) -m $(UVICORN) $(PKG_INTERNAL).main:app --host $(HOST) --port $(PORT) --log-level $(LOG_LEVEL) $(if $(filter 1,$(RELOAD)),--reload,) --workers $(WORKERS)

.PHONY: cli
cli: install
	PYTHONPATH=. PATCHVEC_CONFIG=./config.yml.example \
	$(PYTHON_BIN) -m $(PKG_INTERNAL).cli $(ARGS)

# -------- bump --------
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
	@if [ -f README.md ] && grep -q 'docker run --rm -p 8086:8086 -v $$\(pwd\)/data:/app/data patchvec:' README.md; then \
	  sed -i -E 's@(docker run --rm -p 8086:8086 -v \$$\(pwd\)/data:/app/data patchvec:).*@\1$(VERSION)@' README.md; \
	fi
	@echo "✅ Bumped to $(VERSION). Review changes, then commit:"
	@echo "   git add -A && git commit -m \"chore: bump version to $(VERSION)\""

# -------- build / package --------
.PHONY: build
build: install
	rm -rf $(DIST_DIR) $(BUILD_DIR)
	$(PYTHON_BIN) -m pip install -q build twine
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
	@echo "✅ Artifacts available in $(ART_DIR)/"

# -------- docker build/push --------
.PHONY: docker-build
docker-build:
	@if [ -z "$(VERSION)" ]; then echo "Set VERSION=x.y.z (e.g., 'make docker-build VERSION=0.5.4')"; exit 1; fi
	@if [ -n "$(REGISTRY)" ]; then \
	  echo "Building $(REGISTRY)/$(IMAGE_NAME):$(VERSION) from $(DOCKERFILE)"; \
	  docker build -t $(REGISTRY)/$(IMAGE_NAME):$(VERSION) -f $(DOCKERFILE) $(CONTEXT); \
	else \
	  echo "Building $(IMAGE_NAME):$(VERSION) from $(DOCKERFILE)"; \
	  docker build -t $(IMAGE_NAME):$(VERSION) -f $(DOCKERFILE) $(CONTEXT); \
	fi
	@if [ "$(PUSH_LATEST)" = "1" ]; then \
	  if [ -n "$(REGISTRY)" ]; then \
	    docker tag $(REGISTRY)/$(IMAGE_NAME):$(VERSION) $(REGISTRY)/$(IMAGE_NAME):latest; \
	  else \
	    docker tag $(IMAGE_NAME):$(VERSION) $(IMAGE_NAME):latest; \
	  fi; \
	fi

.PHONY: docker-push
docker-push:
	@if [ -z "$(VERSION)" ]; then echo "Set VERSION=x.y.z (e.g., 'make docker-push VERSION=0.5.4')"; exit 1; fi
	@if [ -n "$(REGISTRY)" ]; then \
	  echo "Pushing $(REGISTRY)/$(IMAGE_NAME):$(VERSION)"; \
	  docker push $(REGISTRY)/$(IMAGE_NAME):$(VERSION); \
	  if [ "$(PUSH_LATEST)" = "1" ]; then docker push $(REGISTRY)/$(IMAGE_NAME):latest; fi; \
	else \
	  echo "Pushing $(IMAGE_NAME):$(VERSION)"; \
	  docker push $(IMAGE_NAME):$(VERSION); \
	  if [ "$(PUSH_LATEST)" = "1" ]; then docker push $(IMAGE_NAME):latest; fi; \
	fi

# -------- clean --------
.PHONY: clean
clean:
	rm -rf __pycache__ */__pycache__ *.pyc *.pyo *.pyd .pytest_cache .ruff_cache .mypy_cache .pytype
	find . -name '*.egg-info' -prune -exec rm -rf {} +
	@echo "Cleaned caches."

.PHONY: clean-dist
clean-dist:
	rm -rf $(DIST_DIR) $(BUILD_DIR) $(ART_DIR)
	@echo "Removed dist/build/artifacts."

# -------- release --------
# - ensure clean tree
# - (optional) bump versions unless SKIP_BUMP=1
# - update CHANGELOG via scripts/update_changelog.py
# - run tests and build; otherwise revert
# - commit, tag, push
# - package artifacts
# - optionally docker-build & docker-push when DOCKER_PUBLISH=1
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
	if [ "$(SKIP_BUMP)" != "1" ]; then \
	  echo "Bumping to $(VERSION) via 'make bump'..."; \
	  $(MAKE) bump VERSION=$(VERSION); \
	fi; \
	$(PYTHON_BIN) scripts/update_changelog.py $(VERSION) || { echo "Changelog generation failed"; exit 1; }; \
	git add CHANGELOG.md setup.py README.md Dockerfile docker-compose.yml $(PKG_INTERNAL)/main.py 2>/dev/null || true; \
	echo "Running tests..."; \
	$(MAKE) test || { echo "Tests failed."; revert_changes; exit 1; }; \
	echo "Building dists..."; \
	$(MAKE) build || { echo "Build failed."; revert_changes; exit 1; }; \
	git commit -m "chore(release): v$(VERSION)"; \
	git tag v$(VERSION); \
	git push origin HEAD --tags; \
	$(MAKE) package; \
	echo "Release v$(VERSION) done."


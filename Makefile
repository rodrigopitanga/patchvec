# Patchvec — Makefile
#
# Basic usage:
#   make install            # default: GPU deps (requirements.txt)
#   make install USE_CPU=1  # override: CPU-only deps (requirements-cpu.txt)
#
# GPU by default. Set USE_CPU=1 to install CPU deps instead.

PKG_NAME        := patchvec
PKG_ICON	:= 🍰
PKG_LONGNAME    := $(PKG_ICON) Patchvec
PKG_INTERNAL   	:= pave
REGISTRY_HOST	?= registry.gitlab.com
REGISTRY_GROUP	?= flowlexi

PYTHON          ?= python3
PIP             ?= $(PYTHON) -m pip
UVICORN         ?= uvicorn

VENV            ?= .venv-$(PKG_INTERNAL)
PYTHON_BIN      ?= $(VENV)/bin/python
PIP_BIN         ?= $(VENV)/bin/pip

DEV		?= 1
AUTH_MODE	?= none
HOST            ?= 0.0.0.0
PORT            ?= 8086
WORKERS         ?= 1
RELOAD          ?= 1
LOG_LEVEL       ?= debug

# Requirements flavor (gpu default)
USE_CPU ?= 0
REQ_MAIN_CPU    ?= requirements-cpu.txt
REQ_MAIN_GPU    ?= requirements.txt
REQ_TEST        ?= requirements-test.txt

# Version helpers - setup.py source of truth
VERSION         ?= $(shell sed -n 's/^ *version="\([^"]*\)".*/\1/p' setup.py | head -1)
ARCHIVE_BASENAME := $(PKG_NAME)-$(VERSION)
DIST_DIR        := dist
BUILD_DIR       := build
ART_DIR         := artifacts

# Docker / publish
DOCKERFILE      ?= Dockerfile
CONTEXT         ?= .
PUSH_LATEST     ?= 1
DOCKER_PUBLISH  ?= 1
REGISTRY        ?= $(REGISTRY_HOST)/$(REGISTRY_GROUP)/$(PKG_NAME)
IMAGE_NAME 	?= $(PKG_NAME)
ifeq ($(USE_CPU),1)
    IMAGE_TAG 	:= $(VERSION)-cpu
    LATEST_TAG 	:= latest-cpu
else
    IMAGE_TAG 	:= $(VERSION)-gpu
    LATEST_TAG 	:= latest-gpu
endif
BUILD_VARIANT 	:= $(if $(filter 1,$(USE_CPU)),cpu,gpu)
BUILD_ID 	?= $(shell date -u +%Y%m%d%H%M%S)-$(shell git rev-parse --short HEAD)-$(BUILD_VARIANT)

.ONESHELL:
SHELL := /bin/bash

.PHONY: help
help:
	@echo "$(PKG_LONGNAME) Make Targets"
	@echo "  venv            Create local virtualenv (.venv)"
	@echo "  install         Install runtime deps (GPU by default; USE_CPU=1 for CPU)"
	@echo "  install-dev     Install dev/test deps (GPU by default; USE_CPU=1 for CPU)"
	@echo "  test            Run pytest"
	@echo "  serve           Run API server (DEV: PATCHVEC_DEV=1, auth=none, loopback)"
	@echo "  cli             Run CLI (pass ARGS='...')"
	@echo "  bump            Bump file versions everywhere"
	@echo "  build           Build sdist+wheel to ./dist"
	@echo "  package         Build artifacts (.zip + .tar.gz) to ./artifacts"
	@echo "  docker-build    Build Docker image (VERSION=x.y.z)"
	@echo "  docker-push     Push Docker image (VERSION=x.y.z, REGISTRY=...)"
	@echo "  deps-clean      Remove .venv (deps dir)"
	@echo "  dist-clean      Remove dist/build/caches/artifacts"
	@echo "  data-clean      Remove local data/indexes"
	@echo "  clean           Full clean (except deps)"
	@echo "  check           Run end-to-end demo inside Docker container"
	@echo "  release         Bump/tag/push; updates CHANGELOG; optional Docker publish"
	@echo "  publish-test    Upload to TestPyPI (builds first)"
	@echo "  publish         Upload to PyPI (builds first)"

# -------- venv (robust, idempotent) --------
$(VENV)/.created:
	@if ! command -v $(PYTHON) >/dev/null 2>&1; then echo "ERROR: '$(PYTHON)' not found"; exit 127; fi
	@echo "⏳ Creating virtual environment in $(VENV) using: $(PYTHON)"
	@$(PYTHON) -m venv $(VENV) --prompt $(PKG_NAME)
	@$(PIP_BIN) install -q --upgrade pip
	@touch $@

.PHONY: venv
venv: $(VENV)/.created
	@echo "✅ Virtual env ready 👉 Run: source $(VENV)/bin/activate"

# -------- install --------
define install_main
	@if [ "$(USE_CPU)" = "1" ]; then \
	  echo "Installing CPU deps from $(REQ_MAIN_CPU)"; \
	  $(PIP_BIN) install -q -r $(REQ_MAIN_CPU); \
	else \
	  echo "Installing GPU deps from $(REQ_MAIN_GPU)"; \
	  $(PIP_BIN) install -q -r $(REQ_MAIN_GPU); \
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
	PYTHONPATH=. $(PYTHON_BIN) -m pytest -q

.PHONY: serve
serve: install
	@echo "Starting 🍰 server on $(HOST):$(PORT) [auth.mode=$(AUTH_MODE)]"
	PYTHONPATH=. \
	PATCHVEC_DEV=$(DEV) \
	PATCHVEC_AUTH__MODE=$(AUTH_MODE) \
	PATCHVEC_AUTH__GLOBAL_KEY=$(CHECK_TOKEN) \
	PATCHVEC_SERVER__LOG_LEVEL=$(LOG_LEVEL) \
	PATCHVEC_SERVER_HOST=$(HOST) \
	PATCHVEC_SERVER_PORT=$(PORT) \
	$(PYTHON_BIN) -m $(PKG_INTERNAL).main

.PHONY: cli
cli: install
	PYTHONPATH=. $(PYTHON_BIN) -m $(PKG_INTERNAL).cli $(ARGS)

# -------- bump --------
.PHONY: bump
bump:
	@if [ -z "$(VERSION)" ]; then \
	  echo "Error: VERSION is not set. Usage: make bump VERSION=0.5.4"; \
	  exit 1; \
	fi
	@echo "Bumping version to $(VERSION)..."

	# setup.py: version="x.y.z" or version="x.y.zdevN"
	@if [ -f setup.py ]; then \
	  sed -i -E 's/(version=)\"[^\"]*\"/\1"$(VERSION)"/' setup.py; \
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
	@if [ -f README.md ] && grep -q 'docker build --progress=plain --build-arg USE_CPU=$(USE_CPU) --build-arg BUILD_ID=$(BUILD_ID) -t patchvec:' README.md; then \
	  sed -i -E 's@(docker build --progress=plain --build-arg USE_CPU=$(USE_CPU) --build-arg BUILD_ID=$(BUILD_ID) -t patchvec:).*@\1$(VERSION) \.@' README.md; \
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
docker-build: install
	@if [ -z "$(VERSION)" ]; then echo "Set VERSION=x.y.z (e.g., 'make docker-build VERSION=0.5.4')"; exit 1; fi
	@if [ -n "$(REGISTRY)" ]; then \
	  echo "Building $(REGISTRY)/$(IMAGE_NAME):$(IMAGE_TAG) from $(DOCKERFILE)"; \
	  docker build --progress=plain --build-arg USE_CPU=$(USE_CPU) --build-arg BUILD_ID=$(BUILD_ID) -t $(REGISTRY)/$(IMAGE_NAME):$(IMAGE_TAG) -f $(DOCKERFILE) $(CONTEXT); \
	else \
	  echo "Building $(IMAGE_NAME):$(IMAGE_TAG) from $(DOCKERFILE)"; \
	  docker build --progress=plain --build-arg USE_CPU=$(USE_CPU) --build-arg BUILD_ID=$(BUILD_ID) -t $(IMAGE_NAME):$(IMAGE_TAG) -f $(DOCKERFILE) $(CONTEXT); \
	fi
	@if [ "$(PUSH_LATEST)" = "1" ]; then \
	  if [ -n "$(REGISTRY)" ]; then \
	    docker tag $(REGISTRY)/$(IMAGE_NAME):$(IMAGE_TAG) $(REGISTRY)/$(IMAGE_NAME):$(LATEST_TAG); \
	  else \
	    docker tag $(IMAGE_NAME):$(IMAGE_TAG) $(IMAGE_NAME):$(LATEST_TAG); \
	  fi; \
	fi

.PHONY: docker-push
docker-push:
	@if [ -z "$(VERSION)" ]; then echo "Set VERSION=x.y.z (e.g., 'make docker-push VERSION=0.5.4')"; exit 1; fi
	@if [ -n "$(REGISTRY)" ]; then \
	  echo "Pushing $(REGISTRY)/$(IMAGE_NAME):$(IMAGE_TAG)"; \
	  docker push $(REGISTRY)/$(IMAGE_NAME):$(IMAGE_TAG); \
	  if [ "$(PUSH_LATEST)" = "1" ]; then docker push $(REGISTRY)/$(IMAGE_NAME):$(LATEST_TAG); fi; \
	else \
	  echo "Pushing $(IMAGE_NAME):$(IMAGE_TAG)"; \
	  docker push $(IMAGE_NAME):$(IMAGE_TAG); \
	  if [ "$(PUSH_LATEST)" = "1" ]; then docker push $(IMAGE_NAME):$(LATEST_TAG); fi; \
	fi

.PHONY: docker-save
docker-save:
        docker save -o patchvec.tar $(IMAGE_NAME)-dev:$(LATEST_TAG)

# SSH deploy to dev server
.PHONY: deploy-dev
deploy-dev: docker-save
	@echo "🚀 Deploy via SSH para $(DEV_HOST)"
	ssh -i $(SSH_KEY_PATH) $(DEV_USER)@$(DEV_HOST) "\
	docker stop patchvec-dev || true && \
	docker rm patchvec-dev || true && \
	docker image rm $(IMAGE_NAME):$(LATEST_TAG) || true"
	scp -i $(SSH_KEY_PATH) patchvec.tar $(DEV_USER)@$(DEV_HOST):~/patchvec.tar
	ssh -i $(SSH_KEY_PATH) $(DEV_USER)@$(DEV_HOST) "\
	docker load -i patchvec.tar && \
	docker run -d --name patchvec-dev \
	-p 8086:8086 \
	-e PATCHVEC_AUTH__GLOBAL_KEY=$(PATCHVEC_AUTH__GLOBAL_KEY) \
	$(IMAGE_NAME)-dev:$(LATEST_TAG)"

# -------- clean (refactored) --------
.PHONY: dist-clean
dist-clean:
	rm -rf __pycache__ */__pycache__ *.pyc *.pyo *.pyd .pytest_cache .ruff_cache .mypy_cache .pytype
	find . -name '*.egg-info' -prune -exec rm -rf {} +
	rm -rf $(DIST_DIR) $(BUILD_DIR) $(ART_DIR)
	-@rm -f uvicorn-demo.log .demo.pid .e2e_ingest.json .e2e_search.json
	@echo "Cleaned build/dist/artifacts."

.PHONY: data-clean
data-clean:
	-@rm -rf data/ var/lib/patchvec/data 2>/dev/null || true
	@echo "Cleaned data/indexes."

.PHONY: clean
clean: dist-clean data-clean
	@echo "Cleaned caches and data."


.PHONY: dep-clean
dep-clean:
	rm -rf $(VENV)
	@echo "Cleaned deps (.venv)."

# -------- release --------
# (unchanged)
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
	if [ "$(DOCKER_PUBLISH)" = "1" ]; then \
	  echo "Publishing Docker image(s)..."; \
	  $(MAKE) docker-build VERSION=$(VERSION) REGISTRY="$(REGISTRY)" IMAGE_NAME="$(IMAGE_NAME)"; \
	  $(MAKE) docker-push  VERSION=$(VERSION) REGISTRY="$(REGISTRY)" IMAGE_NAME="$(IMAGE_NAME)"; \
	fi; \
	echo "✅ Release v$(VERSION) done."

# ------------------- E2E CHECK (dockerized) -------------------
# Build+run container, create collection, ingest 20k leagues, search, stop.

CHECK_NAME        ?= patchvec-check
CHECK_HOST        ?= 127.0.0.1
CHECK_PORT        ?= 8088
CHECK_TIMEOUT_S   ?= 45

# Auth + API params
CHECK_AUTH_MODE   ?= static
CHECK_TOKEN       ?= sekret-token
CHECK_TENANT      ?= demo
CHECK_COLL        ?= books
CHECK_DOCID       ?= DEMO-TXT
CHECK_QUERY       ?= currents
CHECK_K           ?= 7

# Vector backend
CHECK_TXTAI_BACKEND ?= faiss

# Test document (host path)
CHECK_TXT_FILE    ?= ./demo/20k_leagues.txt

# Image ref (fallback to :latest if VERSION is empty)
CHECK_TAG   := $(if $(strip $(VERSION)),$(VERSION),latest)
ifdef REGISTRY
CHECK_IMAGE := $(REGISTRY)/$(IMAGE_NAME):$(CHECK_TAG)
else
CHECK_IMAGE := $(IMAGE_NAME):$(CHECK_TAG)
endif

.PHONY: check-up
check-up:
	@set -euo pipefail; set -x; \
	IMG="$(CHECK_IMAGE)"; \
	if ! docker image inspect $$IMG >/dev/null 2>&1; then docker build --build-arg USE_CPU=$(USE_CPU) --build-arg BUILD_ID=$(BUILD_ID) -t $$IMG -f "$(DOCKERFILE)" "$(CONTEXT)"; fi; \
	docker rm -f $(CHECK_NAME) >/dev/null 2>&1 || true; \
	docker run -d --rm \
	  --name $(CHECK_NAME) \
	  -p "$(CHECK_PORT):8086" \
	  --env PATCHVEC_AUTH__MODE=$(CHECK_AUTH_MODE) \
	  --env PATCHVEC_AUTH__GLOBAL_KEY=$(CHECK_TOKEN) \
	  --env PATCHVEC_SERVER__HOST=$(CHECK_HOST) \
	  --env PATCHVEC_SERVER__PORT=$(CHECK_PORT) \
	  --env PATCHVEC_VECTOR_STORE__TYPE=default \
	  --env PATCHVEC_VECTOR_STORE__TXTAI__BACKEND=$(CHECK_TXTAI_BACKEND) \
	  $$IMG

.PHONY: check-down
check-down:
	@docker rm -f $(CHECK_NAME) >/dev/null 2>&1 || true

.PHONY: check
check: install
	@set -euo pipefail; \
	IMG="$(CHECK_IMAGE)"; \
	if ! command -v docker >/dev/null 2>&1; then echo "docker not found"; exit 127; fi; \
	if ! docker image inspect "$$IMG" >/dev/null 2>&1; then \
	  echo "Image $$IMG not found. Building locally..."; \
	  docker build --build-arg USE_CPU=$(USE_CPU) --build-arg BUILD_ID=$(BUILD_ID) -t "$$IMG" -f "$(DOCKERFILE)" "$(CONTEXT)"; \
	fi; \
	echo "==> Running container: $(CHECK_NAME) on $(CHECK_HOST):$(CHECK_PORT)"; \
	docker rm -f $(CHECK_NAME) >/dev/null 2>&1 || true; \
	docker run -d --rm \
	  --name $(CHECK_NAME) \
	  -p $(CHECK_PORT):8086 \
	  -e PATCHVEC_AUTH__MODE=$(CHECK_AUTH_MODE) \
	  -e PATCHVEC_AUTH__GLOBAL_KEY=$(CHECK_TOKEN) \
	  -e PATCHVEC_SERVER__HOST=$(CHECK_HOST) \
	  -e PATCHVEC_SERVER__PORT=$(CHECK_PORT) \
	  -e PATCHVEC_VECTOR_STORE__TYPE=default \
	  -e PATCHVEC_VECTOR_STORE__TXTAI__BACKEND=$(CHECK_TXTAI_BACKEND) \
	  "$$IMG" >/dev/null; \
	trap 'echo "==> Stopping container $(CHECK_NAME)"; docker rm -f $(CHECK_NAME) >/dev/null 2>&1 || true' EXIT INT TERM; \
	BASE="http://$(CHECK_HOST):$(CHECK_PORT)"; \
	echo "==> Waiting for live $$BASE/health/live (timeout $(CHECK_TIMEOUT_S)s)"; \
	for i in $$(seq 1 $(CHECK_TIMEOUT_S)); do \
	  if curl -sf "$$BASE/health/live" >/dev/null; then echo "   Live."; break; fi; \
	  sleep 1; \
	  if ! docker ps --format '{{.Names}}' | grep -q '^$(CHECK_NAME)$$'; then \
	    echo "Container died early; logs:"; docker logs $(CHECK_NAME) || true; exit 1; \
	  fi; \
	  if [ $$i -eq $(CHECK_TIMEOUT_S) ]; then \
	    echo "Timeout waiting for live"; docker logs $(CHECK_NAME) || true; exit 1; \
	  fi; \
	done; \
	AHDR=""; if [ "$(CHECK_AUTH_MODE)" = "static" ]; then AHDR="Authorization: Bearer $(CHECK_TOKEN)"; fi; \
	echo "==> Create collection: $(CHECK_TENANT)/$(CHECK_COLL)"; \
	if [ -n "$$AHDR" ]; then \
	  curl -sf -X POST "$$BASE/collections/$(CHECK_TENANT)/$(CHECK_COLL)" -H "$$AHDR" -H "Content-Length: 0" >/dev/null; \
	else \
	  curl -sf -X POST "$$BASE/collections/$(CHECK_TENANT)/$(CHECK_COLL)" -H "Content-Length: 0" >/dev/null; \
	fi; \
	[ -f "$(CHECK_TXT_FILE)" ] || { echo "Missing file: $(CHECK_TXT_FILE)"; exit 1; }; \
	echo "==> Ingest: $(CHECK_TXT_FILE) (docid=$(CHECK_DOCID))"; \
	if [ -n "$$AHDR" ]; then \
	  curl -sf -X POST "$$BASE/collections/$(CHECK_TENANT)/$(CHECK_COLL)/documents" -H "$$AHDR" \
	    -F "file=@$(CHECK_TXT_FILE)" \
	    -F "docid=$(CHECK_DOCID)" \
	    -F "metadata={\"lang\":\"en\",\"source\":\"Gutenberg\"}" >/dev/null; \
	else \
	  curl -sf -X POST "$$BASE/collections/$(CHECK_TENANT)/$(CHECK_COLL)/documents" \
	    -F "file=@$(CHECK_TXT_FILE)" \
	    -F "docid=$(CHECK_DOCID)" \
	    -F "metadata={\"lang\":\"en\",\"source\":\"Gutenberg\"}" >/dev/null; \
	fi; \
	echo "==> Search (GET) q='$(CHECK_QUERY)' k=$(CHECK_K)"; \
	ENCQ=$$(printf %s "$(CHECK_QUERY)" | jq -sRr @uri 2>/dev/null || printf %s "$(CHECK_QUERY)"); \
	if [ -n "$$AHDR" ]; then \
	  curl -sf "$$BASE/collections/$(CHECK_TENANT)/$(CHECK_COLL)/search?q=$$ENCQ&k=$(CHECK_K)" -H "$$AHDR" | tee .check_search.json >/dev/null; \
	else \
	  curl -sf "$$BASE/collections/$(CHECK_TENANT)/$(CHECK_COLL)/search?q=$$ENCQ&k=$(CHECK_K)" | tee .check_search.json >/dev/null; \
	fi; \
	grep -q '"matches":\[\{' .check_search.json || { echo "Empty search results"; exit 1; }; \
	echo "✅ make check passed."

.PHONY: publish-test publish

# Upload para o TestPyPI (faz build antes)
publish-test: build
	$(PYTHON_BIN) -m twine upload --repository testpypi $(DIST_DIR)/*

# Upload para o PyPI oficial (requer token)
publish: build
	$(PYTHON_BIN) -m twine upload $(DIST_DIR)/*

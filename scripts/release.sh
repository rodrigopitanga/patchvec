#!/usr/bin/env bash
set -euo pipefail

# Release helper for PatchVec
# - CPU-only env by default
# - runs tests, builds
# - updates version, CHANGELOG (sorted commit messages since last tag)
# - commits, tags, pushes
# - creates .zip and .tar.gz artifacts

VERSION="${1:-}"
if [[ -z "$VERSION" ]]; then
  echo "Usage: $0 <version>"
  exit 1
fi

# Ensure clean tree
if [[ -n "$(git status --porcelain)" ]]; then
  echo "Error: working tree not clean. Commit or stash first."
  exit 1
fi

# Prefer local venv if present
if [[ -d ".venv" && -x ".venv/bin/activate" ]]; then
  # shellcheck disable=SC1091
  source ".venv/bin/activate"
fi

# CPU-only deps for reproducible release
if [[ -f "requirements-cpu.txt" ]]; then
  python -m pip install --upgrade pip
  pip install -r requirements-cpu.txt
fi
# Test deps
if [[ -f "requirements-test.txt" ]]; then
  pip install -r requirements-test.txt
else
  pip install pytest httpx
fi

# Tests must pass
PATCHVEC_CONFIG=./config.yml.example PYTHONPATH=. pytest -q

# Build
python -m pip install build twine
python -m build
twine check dist/*

# Update versions
sed -i.bak -E "s/version=\"[0-9]+\.[0-9]+\.[0-9]+\"/version=\"$VERSION\"/" setup.py && rm -f setup.py.bak
if grep -qE '^VERSION\s*=' pave/main.py; then
  sed -i.bak -E "s/^VERSION\s*=.*/VERSION = \"$VERSION\"/" pave/main.py && rm -f pave/main.py.bak
fi

# Update CHANGELOG with sorted commit subjects since last tag
DATE="$(date +%Y-%m-%d)"
LAST_TAG="$(git describe --tags --abbrev=0 2>/dev/null || true)"
if [[ -n "$LAST_TAG" ]]; then
  COMMITS="$(git log --format=%s "$LAST_TAG"..HEAD | sed '/^$/d' | sort -f)"
else
  COMMITS="$(git log --format=%s | sed '/^$/d' | sort -f)"
fi

HEADER="## $VERSION — $DATE\n\n### Commits"
TMPFILE="$(mktemp)"
{
  echo -e "$HEADER"
  echo "$COMMITS" | sed 's/^/- /'
  echo -e "\n---"
  cat CHANGELOG.md 2>/dev/null || true
} > "$TMPFILE"
mv "$TMPFILE" CHANGELOG.md

# Commit/tag/push
git commit -am "chore(release): v$VERSION"
git tag "v$VERSION"
git push origin HEAD --tags

# Create artifacts
mkdir -p artifacts
zip -rq "artifacts/patchvec-$VERSION.zip" . -x ".venv/*" "dist/*" "build/*" "artifacts/*" ".git/*"
if ls dist/*.tar.gz >/dev/null 2>&1; then
  cp dist/*.tar.gz "artifacts/patchvec-$VERSION.tar.gz"
else
  tar --exclude=".venv" --exclude="dist" --exclude="build" --exclude="artifacts" --exclude=".git" \
    -czf "artifacts/patchvec-$VERSION.tar.gz" .
fi

echo "Done. Artifacts in ./artifacts"

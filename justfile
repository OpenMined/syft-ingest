_cyan := '\033[0;36m'
_red := '\033[0;31m'
_green := '\033[0;32m'
_nc := '\033[0m'

set shell := ["bash", "-cu"]

# List available commands
default:
    @just --list

# Run tests (pass args like: just test -k test_name)
test *args:
    uv run pytest -n auto {{args}}

# Run notebook E2E tests (requires API keys for BrightData cells)
test-nb *args:
    uv run pytest --nbmake notebooks/ -x {{args}}

# Show current version
show-version:
    @grep '^version = ' pyproject.toml | sed 's/version = "\(.*\)"/\1/'

# Bump version (PATCH, MINOR, MAJOR)
bump type="PATCH":
    uv run cz bump --increment {{type}} --yes
    uv lock
    git add uv.lock
    git commit --amend --no-edit

# Build wheel
build:
    rm -rf dist
    uv build

# Remove caches
clean:
    @echo -e "{{_red}}Cleaning caches…{{_nc}}"
    find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
    find . -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null || true
    find . -type d -name ".ruff_cache" -exec rm -rf {} + 2>/dev/null || true
    @echo -e "{{_green}}Done.{{_nc}}"

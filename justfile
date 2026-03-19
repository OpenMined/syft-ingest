_cyan := '\033[0;36m'
_red := '\033[0;31m'
_green := '\033[0;32m'
_nc := '\033[0m'

set shell := ["bash", "-cu"]

# List available commands
default:
    @just --list

# Remove caches
clean:
    @echo -e "{{_red}}Cleaning caches…{{_nc}}"
    find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
    find . -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null || true
    find . -type d -name ".ruff_cache" -exec rm -rf {} + 2>/dev/null || true
    @echo -e "{{_green}}Done.{{_nc}}"

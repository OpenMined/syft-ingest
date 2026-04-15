# Releasing syft-ingest

## Prerequisites

- `OM_PYPI_TOKEN` secret must be set in the GitHub repo settings
  (Settings > Secrets and variables > Actions). Use the same org-scoped
  PyPI token used for other OpenMined packages.

## Automated release (recommended)

1. Go to **Actions > Release** in GitHub.
2. Click **Run workflow**, pick `patch` / `minor` / `major`.
3. The workflow will: run tests, bump version, build, push tag, upload to
   PyPI, and create a GitHub Release.

Use `skip_publish: true` for a dry run that builds but doesn't push or upload.

## Local commands

```bash
just show-version      # current version
just bump PATCH        # bump version (PATCH/MINOR/MAJOR) — commits + tags
just build             # build wheel into dist/
just test              # run tests
```

## Version sync

Commitizen keeps these in sync automatically on `just bump`:

| Location                      | Example          |
|-------------------------------|------------------|
| `pyproject.toml` → `version`  | `"0.2.0"`       |
| `syft_ingest/__init__.py`     | `__version__`    |
| Git tag                       | `v0.2.0`         |

## Consuming in syft-influencer

After publishing, add to syft-influencer's `pyproject.toml`:

```toml
dependencies = [
    "syft-ingest>=0.1.0",
]
```

Then `uv sync` in syft-influencer to pull it from PyPI.

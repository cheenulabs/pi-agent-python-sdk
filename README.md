# Pi coding agent Python client

A Python interface to an existing Pi coding agent installation. This PR
introduces package metadata, typed wire records, and checked errors. Transport,
async, and synchronous clients follow in separate PRs.

The package is under review and unpublished. Python 3.11 or newer is required;
the recorded Pi protocol baseline is 0.85.1. See
[protocol discovery](docs/discovery.md) for scope and upstream evidence.

## Validate this stage

```sh
uv sync --locked --group dev
uv run pytest
uv run ruff check .
uv run mypy
uv run python -m build
uv run twine check dist/*
```

These checks require no provider credentials. Keep this PR open for user review;
passing checks do not authorize a merge.

# Pi coding agent Python client

A small Python interface to an existing [Pi coding agent](https://github.com/earendil-works/pi)
installation. Pi runs your agent; this library manages its RPC subprocess and
provides typed async and synchronous access from Python.

**Under development.** The first release is not yet published. The recorded
protocol baseline is Pi 0.85.1. Python 3.11 or newer is required. Pi requires
its own Node.js installation and configuration.

See the [implementation plan](PLAN.md), [protocol discovery](docs/discovery.md),
and [implementation record](docs/implementation.md).

## Development

```sh
uv sync --group dev
uv run pytest
uv run ruff check .
uv run mypy
uv run python -m build
uv run twine check dist/*
```

Tests use synthetic data. Integration tests use an isolated Pi installation
and a local faux provider; live provider tests require explicit opt-in.

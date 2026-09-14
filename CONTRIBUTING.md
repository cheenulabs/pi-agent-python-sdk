# Contributing

Keep the client small and reviewable. Pi owns agent behavior, credentials,
configuration, models, extensions, tools, and session storage. Preserve its
defaults unless the caller explicitly overrides them.

Use Python 3.11-compatible syntax, standard-library runtime dependencies,
explicit public methods, and typed wire dictionaries. Comments should explain
non-obvious ordering, cancellation, and compatibility decisions. Public
docstrings should describe behavior and failure conditions.

Test through public interfaces or the private subprocess seam with a fake
executable. Cover observable behavior and failures; avoid tests that merely
repeat code structure. Use synthetic data and isolated temporary directories.
Never include real credentials, conversations, provider headers, or private
configuration in fixtures, diagnostics, examples, or issue reports.

Set up the locked development environment and isolated test runtime:

```sh
uv sync --locked --group dev
npm ci --prefix tests/pi --ignore-scripts --no-audit --no-fund
```

Before a pull request, run:

```sh
uv run pytest -m "not live"
uv run ruff check .
uv run ruff format --check .
uv run mypy
uv run mypy --strict examples scripts/check_examples.py
uv run python scripts/check_examples.py
uv run python scripts/check_upstream.py
uv run python -m build
uv run twine check dist/*
uv run python scripts/check_distribution.py
```

Without Node/Pi, local unit work may skip offline integration. CI sets
`PI_CLIENT_REQUIRE_INTEGRATION=1` and checks `PI_CLIENT_EXPECTED_PI_VERSION`,
so missing or incorrect runtimes fail instead of silently skipping coverage.
Do not enable live model tests unless you intend to use your configured Pi;
see [maintenance](docs/maintenance.md) for the explicit opt-in.

Describe the concrete behavior change and relevant validation. Changes to the
supported protocol need updates to types, fixtures, documentation, and the
coverage inventory. Unknown upstream metadata must remain accessible.

Keep reviews attached to the concrete milestone and address findings before
merging. [Review records](docs/reviews.md) show the initial standards and plan
coverage reviews. [Maintenance](docs/maintenance.md) and
[releasing](docs/releasing.md) explain the automated compatibility gates and
external setup required for publication.

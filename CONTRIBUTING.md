# Contributing

Keep the client small and reviewable. Pi owns agent behavior, credentials,
configuration, models, extensions, tools, and session storage. Preserve its
defaults unless the caller explicitly overrides them.

`PiClient` and `AsyncPiClient` stay focused on Pi's RPC protocol. The proposed
experimental `pi_agent.durable` backend may drive the real upstream Harness
through a thin Node host, never a Python port. It reuses core private transport,
limits, subscription, error, and (if approved) sync-bridge modules. Follow the
[Durable design decisions](docs/durable.md#design-decisions): dependencies flow
from durable to core only, Python runtime dependencies stay zero, and the host
keeps protocol bookkeeping only. Its SDK transport envelope does not make it a
Pi RPC server. Pure-Python fake-host tests join the required test matrix; host
and integration tests belong to a separate, initially non-required `durable`
CI job. Core changes must pass all existing tests unmodified.

[#116](https://github.com/cheenulabs/pi-agent-python-sdk/issues/116) proceeds one
milestone PR at a time. M0 is documentation only, not an implemented backend or
owner approval. Q1 scope approval is required before proceeding beyond M0;
Q2 separately gates the sync bridge refactor (otherwise v0 is async-only).
Start each later milestone only after the previous PR is approved and merged.

Use Python 3.11-compatible syntax, standard-library runtime dependencies,
explicit public methods, and typed wire dictionaries. Comments should explain
non-obvious ordering, cancellation, and compatibility decisions. Public
docstrings should describe behavior and failure conditions.

Test through public interfaces or the private subprocess seam with a fake
executable. Cover observable behavior and failures; avoid tests that merely
repeat code structure. Use synthetic data and isolated temporary directories.
Never include real credentials, conversations, provider headers, or private
configuration in fixtures, diagnostics, examples, or issue reports.

Run the checks available on the proposed branch and record any missing
prerequisites. Validation results apply to the tested commit.

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
uv run mypy --strict examples scripts/check_examples.py scripts/check_parity.py
uv run python scripts/check_examples.py
uv run python scripts/check_parity.py
uv run python scripts/check_upstream.py
uv run python -m build
uv run twine check dist/*
uv run python scripts/check_distribution.py --parity
```

Without Node/Pi, local unit work may skip offline integration. CI sets
`PI_CLIENT_REQUIRE_INTEGRATION=1` and checks `PI_CLIENT_EXPECTED_PI_VERSION`,
so missing or incorrect runtimes fail instead of silently skipping coverage.
Do not enable live model tests unless you intend to use your configured Pi;
see [maintenance](docs/maintenance.md) for the explicit opt-in.

Describe the concrete behavior change and relevant validation. Changes to the
supported protocol need updates to types, fixtures, documentation, and the
coverage inventory. Unknown upstream metadata must remain accessible.

Use `.github/pull_request_template.md` for new PRs and keep descriptions current
when scope changes. Titles follow `type(scope): concise description`, for example
`fix(rpc): bound retained run messages`. Complete the Overview, Files changed and
why, and Validation sections with concrete changes and observed results.

Address review findings before merging. Merge each PR only after explicit
approval, using squash. After merging, restack each dependent branch's own
commits onto its updated base, retarget the next PR to main, and rerun its
checks. Keep auto-merge off. Publishing requires separate explicit approval.

[Maintenance](docs/maintenance.md) and
[releasing](docs/releasing.md) explain the automated compatibility gates and
external setup required for publication.

## Coding agent instructions

Maintain shared instructions in [AGENTS.md](AGENTS.md). `CLAUDE.md` is a relative
symlink to it; `GEMINI.md` imports it, and `.github/copilot-instructions.md` asks
Copilot to read it. Cursor can use `AGENTS.md` directly, so a separate Cursor
rules file is unnecessary. These entry points carry no separate project policy.

On Windows, check out with symlink support enabled (Developer Mode or the
necessary privileges and Git's `core.symlinks=true`) to use `CLAUDE.md` as a link.
If a checkout materializes it as a plain file containing `AGENTS.md`, load the
canonical file explicitly in the agent instead. Preserve the committed symlink.

Check loaded instructions in a new Claude session with `/context`, or in Gemini
with `/memory show`. Copilot's pointer requires the agent to read `AGENTS.md`;
it is not a guarantee that every Copilot feature automatically loads that file.

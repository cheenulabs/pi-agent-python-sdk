# Agent instructions

This file is the canonical repository guidance. Edit it when shared instructions
change; `CLAUDE.md` links here, and the Gemini and Copilot entry points refer here.
Paths below are relative to the repository root.

## Scope and implementation

- The distribution is `pi-agent-python-sdk`; Python code imports `pi_agent`.
- Keep `PiClient` and `AsyncPiClient` focused on Pi's RPC protocol. Pi owns
  models, authentication, tools, extensions, configuration, and session storage.
  Preserve Pi's defaults unless the caller explicitly overrides them.
- The proposed experimental `pi_agent.durable` backend may ship a thin Node host
  driving the real upstream Harness, not a Python port. It reuses core private
  modules for transport, limits, subscriptions, errors, and (if approved) the
  sync bridge. Follow the design decisions in [durable](docs/durable.md): keep
  dependencies one-way, runtime Python dependencies at zero, and Durable tests
  isolated as specified there. The host uses the SDK transport envelope; it is
  not a Pi RPC server. Q1 owner approval gates work beyond docs-only M0; Q2
  separately gates the sync bridge refactor. See [#116](https://github.com/cheenulabs/pi-agent-python-sdk/issues/116).
- Read [CONTRIBUTING.md](CONTRIBUTING.md) before changing code or preparing a PR;
  it defines coding conventions, test setup, and required validation commands.
- For lifecycle, transport, or run changes, read [RPC structure](docs/rpc.md) and
  [errors and cancellation](docs/errors.md). Keep synchronous behavior delegated
  to the async implementation.
- For public interface or protocol changes, read [API reference](docs/api.md),
  [protocol discovery](docs/discovery.md), and [compatibility](docs/compatibility.md).
  Update affected types, fixtures, examples, and documentation together. Preserve
  unknown upstream fields and events.
- For Pi version updates, follow [maintenance](docs/maintenance.md). For package
  metadata or publishing changes, follow [releasing](docs/releasing.md).

## Validation

- Run the checks in CONTRIBUTING.md before a PR. Report results for the proposed
  commit and identify unavailable prerequisites or checks that were not run.
- Use the isolated test runtime and synthetic data. Live model tests require
  explicit opt-in; examples run directly may use the caller's configured provider.
- Keep credentials, conversations, and private configuration out of fixtures,
  diagnostics, and review material.

## Review and merge policy

- Before creating or updating a PR, read [.github/pull_request_template.md](.github/pull_request_template.md).
  Use a `type(scope): concise description` title and fill its Overview, Files
  changed and why, and Validation sections with the final scope and actual results.
- Prepare focused PRs and leave them open for the user's review.
- Merge only after the user explicitly approves the specific PR. Engineering
  reviews and passing CI do not substitute for that approval. Keep auto-merge off.
- Use squash merging for an approved PR. Before merging the next stacked PR,
  restack its remaining commits onto the updated base and rerun its checks.
- Publishing or creating a release requires explicit user approval after the
  publishing setup and release candidate are ready for review.
- Preserve unrelated local edits.

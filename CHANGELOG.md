# Changelog

## Unreleased

- Rename the unpublished distribution to `pi-coding-agent-python-sdk` and the
  Python import to `pi_agent`. Source-checkout users must update their imports.

- Keep the standalone SDK scoped to core RPC with zero runtime dependencies;
  document loading caller-owned extensions through native Pi arguments.
- Prevent owned runs from claiming delayed events after low-level submissions.
- Bound retained run messages independently of event queues.
- Preserve unknown usage measurements, concatenate final text blocks directly,
  and measure run latency from submission to settlement.
- Reject malformed known text deltas while preserving unknown event variants.

## 0.1.0rc1 — TestPyPI rehearsal candidate (unpublished)

This candidate prepares the first TestPyPI publishing rehearsal. It has not
been uploaded to TestPyPI or PyPI; publication requires the reviewed workflow
and release environment setup described in [the release guide](docs/releasing.md).

- Add `AsyncPiClient` and `PiClient` with explicit methods for all 33 Pi 0.85.1 RPC commands.
- Add typed wire payloads, future-only event subscriptions, extension dialogs,
  streamed text, and settled results with session identity and observed usage.
- Preserve Pi configuration while owning process readiness, bounded I/O,
  checked failures, cancellation cleanup, and offline compatibility checks.
- Add deterministic subprocess tests and isolated real-Pi integration using a
  local faux provider, including retries, compaction, tools, and saved sessions.
- Add nine runnable examples and guides for the API, errors, compatibility,
  dependency updates, and releases.
- Add Python/platform CI, Dependabot, daily latest-Pi checks, reviewed source
  fingerprints, distribution inspection, and Trusted Publishing workflows.

The first public release is pending public repository visibility, owner-controlled
release settings, and package-index configuration. No package-index publication
is implied by this entry.

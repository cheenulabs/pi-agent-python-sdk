# Changelog

## Unreleased

- Share deadline validation across runs, commands, collectors, and limits; invalid
  types and integers too large for timers consistently raise `ValueError`.
- Document the retained run/stream conveniences and the reasons for their
  internal ownership, session, and cleanup rules.

## 0.1.0

- Introduce the `pi-agent-python-sdk` distribution with the `pi_agent` Python
  import. Users of earlier source checkouts must update their imports.
- Keep the standalone SDK scoped to core RPC with zero runtime dependencies;
  document loading caller-owned extensions through native Pi arguments.
- Prevent owned runs from claiming delayed events after low-level submissions.
- Bound retained run messages independently of event queues.
- Preserve unknown usage measurements, concatenate final text blocks directly,
  and measure run latency from submission to settlement.
- Reject malformed known text deltas while preserving unknown event variants.
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
- Verify published wheel and source hashes, and smoke-test index installations
  before promoting the same artifacts from TestPyPI to PyPI.

# Changelog

## Unreleased

- Clarify Python interface choice, async event consumption, and structured-output
  boundaries; demonstrate thinking, tool events, and unknown metadata.
- Stop process observations without closing Pi, then drain buffered records;
  report scoped stop, discard, overflow, and process termination separately.
- Allow sequential async stream iterator reuse while retaining concurrent-reader
  and result-drain protections.
- Keep a healthy client usable after locally rejected, unsent input, without
  relaxing ownership or cleanup for commands that may have reached Pi.

- Update the tested Pi runtime to 0.86.0, retaining 0.85.1 as the minimum.
- Describe system transcript messages, session usage entries, compaction system
  snapshots, and model prompt-cache metadata in the wire annotations. Preserve
  legacy optional fields and raw metadata; Pi still owns transcript and cache behavior.

## 0.2.0

### Breaking changes

- `prompt()` returns `None` after checked acknowledgement. Use `request("prompt", ...)`
  for the response envelope and ID; `AcceptanceReceipt` is removed.
- `cycle_thinking_level()` and `export_html()` return their complete result
  dictionaries, preserving unknown fields. Read `result["level"]` or `result["path"]`.
- Session mutations invalidate cached identity without an implicit state query.
  Call `get_state()` explicitly when updated identity is needed.

### Added

- TypeScript-style listeners and settlement helpers: `on_event()`,
  `collect_events()`, `wait_for_idle()`, and `prompt_and_wait()` through both facades.
- Opt-in observation of original stderr/stdout bytes and all parsed RPC objects,
  with bounded queues and explicit completion/loss status.
- Subscriptions before startup, including extension events and startup failures.
- Maintained TypeScript command/event comparison for source checkouts and installed
  wheels across supported Python and operating-system versions.

### Fixed

- Stream events before prompt acknowledgement while still requiring successful
  acknowledgement and settlement before completing a result.
- Preserve UI callback causes; dialog expiry cancels only the dialog, and late
  handler answers cannot override it.
- Deliver buffered event prefixes before terminal failures; preserve overflow
  errors during concurrent blocking-context cleanup.
- Yield during finite output bursts and batch blocking reads; result-only runs
  no longer buffer discarded progress. Slow consumers still fail explicitly.
- Preserve JSON-escaped lone surrogates on outbound commands and UI replies.

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

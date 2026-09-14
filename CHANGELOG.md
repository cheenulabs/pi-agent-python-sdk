# Changelog

## Unreleased

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

The first public release is pending repository access, remote CI, and package
index configuration. No package-index publication is implied by this entry.

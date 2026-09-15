# Implementation reviews

Reviews compare an explicit milestone with the plan and CONTRIBUTING.md.
These are engineering reviews, not independent GitHub approvals. The first
three reviews are now recorded on their merged PRs; remote status is tracked
in [implementation.md](implementation.md).

## Foundation

Initial review: `33a668e...c43e3e5`.

**Standards review:** one high-priority lifecycle finding. Version-check
cleanup could hang on a full stdout pipe after killing its child. No other
documented violations or actionable design smells were found.

**Plan coverage review:** two findings. Owned-process exit was not observed
independently of stdout EOF, so descendants retaining stdout could leave
callers waiting. CLI validation could hide reserved options after
`--use-theme` or `--tui-mode`, whose value consumption is conditional upstream.

Corrections add independent child-exit observation, close parent pipe handles
after the child exits, reuse that cleanup for version checks, and validate
the conditional CLI arguments. Regression tests cover flooding version output,
descendant-held pipes, a final 500 KB JSON response without a newline, and
reserved arguments hidden behind those options.

Integration testing also exposed a Python 3.11 cancellation race when
`asyncio.wait_for` completed alongside cancellation. The response deadline now
uses `asyncio.timeout` on the calling task; cancelling at prompt acceptance
waits for owned-run cleanup instead of silently continuing the run.

Validation after corrections: 104 foundation tests and 25 public async-client
tests pass. Ruff passes for the reviewed foundation and async files.

[PR #1](https://github.com/cheenulabs/pi-coding-agent-python-client/pull/1)
was merged after repeating validation at `50e8238`: 104 tests, Ruff lint,
package/test formatting, and strict mypy passed.

## Async commands and owned runs

Standards reviewed `50e8238...564535f`; plan coverage reviewed
`50e8238...8c3b4a4`, including offline real-Pi tests.

**Standards review:** two high-priority issues. Closing from an async UI
callback cancelled and gathered the callback itself. UI callbacks could also
accumulate without a bound even when event subscriptions were bounded.

Corrections exclude the current callback from close, and bound outstanding UI
work by the same record/byte limits as subscriptions. Overflow closes the
client with a dedicated handler error. Regression tests exercise both cases.
A closed, unentered stream also now fails before claiming the conversation.

**Plan coverage review:** one high-priority cancellation issue. Successful
abort/clear-queue responses did not prove that pending extension preflight had
stopped. A gated real-Pi confirmation resumed the original command after the
owned call had timed out. Cancellation before acknowledgement or an observed
start now closes Pi. The reviewer revalidated this with a delayed input hook;
the child closed and its handler was cancelled before the gate was released.

After corrections, 29 async behavior tests, 17 sync facade tests, and 16 real-Pi
lifecycle tests passed together. The separate 12-test real-Pi command suite
covers every one of the 33 commands. Ruff and strict mypy pass. These checks do
not constitute remote CI. [PR #2](https://github.com/cheenulabs/pi-coding-agent-python-client/pull/2)
was subsequently merged after exact-commit validation at `ba9b049`: 161 tests
with no skips, Ruff lint, package formatting, and strict mypy passed.

## Synchronous facade

Both reviews compared `ba9b049...ec6427e`.

**Standards review:** two medium-priority issues. Event-loop allocation failure
could leave startup waiting forever, and repeated `iter()` calls rejected
normal Python iterator use. Startup now signals both readiness and completion
on failure; stream iterators return themselves idempotently.

**Plan coverage review:** one high-priority and one medium-priority issue.
Ctrl-C during a stream read/result could leave its owned run active after the
caller caught the interrupt. Context cleanup could also raise while another
thread was closing the client. Interrupted owned stream operations now await
run cleanup, and contexts coordinate with enclosing shutdown.

Regression validation: 27 sync tests and 29 async behavior tests pass together.
Tests cover interrupts before/during stream operations, loop/thread startup
failure, repeated iteration, and both context kinds during concurrent close.
Ruff and strict mypy pass.

[PR #3](https://github.com/cheenulabs/pi-coding-agent-python-client/pull/3)
was merged after exact-commit validation at `89bf2c5`: 188 tests with no skips,
Ruff lint, package formatting, and strict mypy passed. All three milestone
reruns used isolated worktrees on Linux with Python 3.14.2; the async/sync
milestones used real Pi 0.85.1. Earlier doc/test whitespace deviations are
corrected in the final package branch.

## Public package and compatibility automation

Both reviews compared `89bf2c5...0856b0a`.

**Standards review:** the fingerprint list omitted imported RPC payload
definitions, and successful pytest exit did not prove that offline integration
had actually run when prerequisites were missing.

**Plan coverage review:** reproduced the missing-runtime case as 29 skipped
tests with exit code zero. It also identified omitted framing/agent-loop
sources in the source-change report. These were medium-priority gate gaps.

The source inventory now includes those definitions, framing, agent-loop,
runtime, CLI and package metadata. CI requires Node and the real runtime,
checks its exact selected version, and fails instead of skipping when missing.
Focused tests cover missing/wrong runtimes, version/source drift, explicit
baseline recording, and agreement with the offline compatibility constants.

Archive inspection found an unanchored README pattern including a test README
in the source distribution. Explicit file selection corrected it; rebuilt
archives and installed-wheel sync/async smoke checks pass.

Final lifecycle review also caught an async startup-close issue: waiting for
the caller's entire task could deadlock with its enclosing finally block.
Shutdown now waits for startup cleanup completion, independently of the user
task. Dedicated regressions cover close during version probing, startup UI
callbacks, caller finally blocks, and subscription byte limits.

Final verification is recorded in [validation.md](validation.md). The public
docs include all command methods, behavioral guides, nine checked examples,
and concise public method docstrings. Fresh independent Standards and Spec
reviews of `89bf2c5...de6f612` found no unresolved blocking findings. Actual
platform CI and publication remain required; static workflow review does not
prove that they passed.

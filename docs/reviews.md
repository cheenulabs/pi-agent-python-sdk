# Implementation reviews

Reviews compare an explicit milestone with the plan and CONTRIBUTING.md.
These are local engineering reviews, not GitHub approvals or remote merges.

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

Remote PR creation is still pending access to the configured repository.

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
not constitute remote CI or a GitHub merge.

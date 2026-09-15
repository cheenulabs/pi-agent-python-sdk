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

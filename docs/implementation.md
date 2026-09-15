# Implementation record

The implementation follows [PLAN.md](../PLAN.md) and the pinned
[discovery findings](discovery.md). Each stage needs tests and review before
integration. This record distinguishes local completion from remote merges.

| Stage | Status | Evidence |
|---|---|---|
| Foundation: package, types, errors, subprocess | Reviewed and merged | [PR #1](https://github.com/cheenulabs/pi-coding-agent-python-client/pull/1), `50e8238`; 104 exact-commit tests |
| Full command and extension UI coverage | Reviewed and merged | [PR #2](https://github.com/cheenulabs/pi-coding-agent-python-client/pull/2), `ba9b049`; all 33 commands exercised against Pi |
| Owned runs and streams | Reviewed and merged | PR #2; 161 exact-commit tests including offline real-Pi lifecycle checks |
| Synchronous facade | Reviewed and merged | [PR #3](https://github.com/cheenulabs/pi-coding-agent-python-client/pull/3), `89bf2c5`; 188 exact-commit tests |
| Integration, public docs, packaging, CI | Local validation passed; remote CI pending | `feat/public-package`; 205 tests on each of Python 3.11–3.14, nine example smokes, archive checks |
| Upstream maintenance and release setup | Local workflows written; external setup pending | Dependabot, latest-Pi checks, source drift report, Trusted Publishing workflow |

Repository access was restored on 2026-09-15. The documentation baseline and
first three implementation milestones are pushed and merged. GitHub rejected
the final branch's workflow files because the current CLI authorization lacks
the `workflow` scope; that refresh is pending.

See [review findings and corrections](reviews.md) for the standards and plan
coverage reviews. Each merged PR contains its engineering review and exact-head
validation. These author-recorded reviews are not independent GitHub approvals.
GitHub CI on macOS/Windows, required-check settings, TestPyPI rehearsal, Trusted
Publisher setup, release publication, and final installed-index verification
remain outstanding until the relevant external access exists.

The [validation audit](validation.md) maps the complete plan to current
evidence and explicitly separates external gates from completed local work.

## PR sequence

The branches are stacked. The remote was bootstrapped with the documentation
baseline (`33a668e`); milestones 1–3 were reviewed and merged in order:

1. `feat/foundation`: typed wire surface, exceptions, CLI/version validation,
   owned transport and failure handling.
2. `feat/async-client`: every command and UI interaction, run/stream ownership,
   settlement/results, plus offline real-Pi integration.
3. `feat/sync-client`: the persistent-loop blocking facade, iterator contexts,
   interrupt handling and concurrent lifecycle behavior.
4. `feat/public-package`: public documentation/examples, packaging validation,
   CI, Dependabot, compatibility automation, and final review corrections.

Merge commits preserve the stacked ancestry. The merged commits are
`df0f9e5` (foundation), `67d944f` (async), and `36a8ad5` (sync). No workflow was
present in those milestones; their checks ran in isolated local worktrees.
The final package PR must pass its actual GitHub platform matrix before merge.
Final first-release work follows [releasing.md](releasing.md).

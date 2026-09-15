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
| Integration, public docs, packaging, CI | Reviewed and merged; all platform CI gates passed | [PR #4](https://github.com/cheenulabs/pi-coding-agent-python-client/pull/4); 205 tests per platform job, nine example smokes, archive checks |
| Upstream maintenance | Latest-Pi and all three Dependabot update jobs passed | [Latest-Pi run](https://github.com/cheenulabs/pi-coding-agent-python-client/actions/runs/34919463989); Pi 0.85.1, 30 offline integration tests and source comparison passed |
| Release preparation | Reviewed candidate built; owner setup and publication pending | [PR #5](https://github.com/cheenulabs/pi-coding-agent-python-client/pull/5), unpublished `0.1.0rc1` for the TestPyPI rehearsal |

Repository access and workflow authorization were restored on 2026-09-15.
All four milestone branches are pushed, with reviews recorded on their PRs.
All four implementation milestones are merged. PR #4's final head `90f5c16`
passed [run 34919253348](https://github.com/cheenulabs/pi-coding-agent-python-client/actions/runs/34919253348)
before merge commit `14de2fe`. The release candidate's current merge state and
checks are recorded on PR #5.

See [review findings and corrections](reviews.md) for the standards and plan
coverage reviews. Each merged PR contains its engineering review and exact-head
validation. These author-recorded reviews are not independent GitHub approvals.
Public repository visibility, required-check settings, TestPyPI rehearsal,
Trusted Publishers, deployment approvals, release publication, and final
installed-index verification remain outstanding. The personal repository
owner must configure visibility and protections; collaborator push access is
insufficient. [Releasing](releasing.md) lists the exact setup fields.

The [validation audit](validation.md) maps the complete plan to current
evidence and explicitly separates external gates from completed local work.

## PR sequence

The branches are stacked. The remote was bootstrapped with the documentation
baseline (`33a668e`); milestones 1–4 were reviewed and merged in order:

1. `feat/foundation`: typed wire surface, exceptions, CLI/version validation,
   owned transport and failure handling.
2. `feat/async-client`: every command and UI interaction, run/stream ownership,
   settlement/results, plus offline real-Pi integration.
3. `feat/sync-client`: the persistent-loop blocking facade, iterator contexts,
   interrupt handling and concurrent lifecycle behavior.
4. `feat/public-package`: public documentation/examples, packaging validation,
   CI, Dependabot, compatibility automation, and final review corrections.

Merge commits preserve the stacked ancestry. The merged commits are
`df0f9e5` (foundation), `67d944f` (async), `36a8ad5` (sync), and `14de2fe`
(public package). No workflow was
present in those milestones; their checks ran in isolated local worktrees.
The final package PR's matrix passed on all supported platforms, including
Windows after correcting a UTF-8 document read in a coverage test. Its final
head must retain successful CI before merge.
Final first-release work follows [releasing.md](releasing.md).

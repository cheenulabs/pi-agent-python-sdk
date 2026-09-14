# Implementation record

The implementation follows [PLAN.md](../PLAN.md) and the pinned
[discovery findings](discovery.md). Each stage needs tests and review before
integration. This record distinguishes local completion from remote merges.

| Stage | Status | Evidence |
|---|---|---|
| Foundation: package, types, errors, subprocess | Implemented and reviewed locally | `feat/foundation`, `50e8238` |
| Full command and extension UI coverage | Implemented and reviewed locally | `feat/async-client`, `ba9b049`; all 33 commands exercised against Pi |
| Owned runs and streams | Implemented and reviewed locally | `ba9b049`; fake-process and offline real-Pi lifecycle tests |
| Synchronous facade | Implemented and reviewed locally | `feat/sync-client`, `89bf2c5`; 27 sync regression tests |
| Integration, public docs, packaging, CI | Local validation passed; remote CI pending | `feat/public-package`; 205 tests on each of Python 3.11–3.14, nine example smokes, archive checks |
| Upstream maintenance and release setup | Local workflows written; external setup pending | Dependabot, latest-Pi checks, source drift report, Trusted Publishing workflow |

Remote PR work is pending repository access: the configured public GitHub
repository returned 404 at implementation startup. Local work continues.

See [review findings and corrections](reviews.md) for the standards and plan
coverage reviews. No remote pull request or merge has been claimed. GitHub
CI on macOS/Windows, required-check settings, TestPyPI rehearsal, Trusted
Publisher setup, release publication, and final installed-index verification
remain outstanding until the relevant external access exists.

The [validation audit](validation.md) maps the complete plan to current
evidence and explicitly separates external gates from completed local work.

## PR sequence once repository access is restored

The local branches are stacked and have not been pushed. Bootstrap the empty
remote with local main (`33a668e`), then open, review and merge these in order:

1. `feat/foundation`: typed wire surface, exceptions, CLI/version validation,
   owned transport and failure handling.
2. `feat/async-client`: every command and UI interaction, run/stream ownership,
   settlement/results, plus offline real-Pi integration.
3. `feat/sync-client`: the persistent-loop blocking facade, iterator contexts,
   interrupt handling and concurrent lifecycle behavior.
4. `feat/public-package`: public documentation/examples, packaging validation,
   CI, Dependabot, compatibility automation, and final review corrections.

Use merge commits to preserve the stacked ancestry, or deliberately restack
later branches after squashing. Record the existing engineering reviews on the
actual PRs, wait for required checks, then merge. No remote PR/merge identifiers
exist yet. Final first-release work follows [releasing.md](releasing.md).

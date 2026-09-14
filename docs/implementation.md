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
| Integration, public docs, packaging, CI | Final validation in progress | `feat/public-package`; Linux Python matrix running |
| Upstream maintenance and release setup | Local workflows written; external setup pending | Dependabot, latest-Pi checks, source drift report, Trusted Publishing workflow |

Remote PR work is pending repository access: the configured public GitHub
repository returned 404 at implementation startup. Local work continues.

See [review findings and corrections](reviews.md) for the standards and plan
coverage reviews. No remote pull request or merge has been claimed. GitHub
CI on macOS/Windows, required-check settings, TestPyPI rehearsal, Trusted
Publisher setup, release publication, and final installed-index verification
remain outstanding until the relevant external access exists.

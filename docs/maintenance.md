# Maintaining Pi compatibility

The library never upgrades the user's runtime. Maintain the test runtime in
`tests/pi/package.json` and its npm lockfile. `compatibility.json` records the
minimum/tested versions, source commit, and reviewed upstream fingerprints.

Dependabot checks Pi daily with no configured cooldown. Python development
and build dependencies use the **uv** ecosystem weekly, so `pyproject.toml`
and `uv.lock` stay consistent; GitHub Actions updates are also weekly.

The daily/manual Latest Pi compatibility workflow resolves npm's exact
latest stable release, installs it into disposable CI storage, runs real-Pi
integration tests, and compares its source with the reviewed baseline. It
never writes a version PR or silently approves a new release. Dependabot's
version PR is the single update PR. Its normal CI jobs provide the test and
source-review results; review artifacts remain attached to the workflow run
linked from the PR checks.

## Reviewing an update

1. Check the Dependabot PR's exact package version and npm integrity lock.
2. Read `upstream-report.md` in the `protocol-review` artifact. It compares
   command declarations, runtime dispatch, the TypeScript client, serializer,
   event/message/session types, and changelog against the reviewed commit.
3. Review every changed surface, update Python types/methods/tests and the
   discovery coverage inventory where needed, then run the complete suite.
   Behavioral tests passing does not establish that the surface is unchanged.
4. After reviewing the candidate, explicitly record it:

   ```sh
   uv run python scripts/check_upstream.py --record
   ```

5. Update the offline constants in `_launch.py` and the public compatibility
   guide. The ordinary check rejects disagreement with the recorded version.
   Keep the minimum version unless a deliberate compatibility decision changes it.
6. Re-run CI. The matrix checks the pin across Python 3.11–3.14 on Linux and
   Python 3.14 on macOS/Windows. When the minimum differs, an additional Linux
   integration job checks it. The `required` job fails unless every test,
   quality, and protocol job succeeds.
7. Review and merge the PR. A compatible Pi update may only require a tested
   version documentation update; client behavior changes need a package release.

You can inspect a candidate before changing the test pin:

```sh
uv run python scripts/check_upstream.py --version latest
```

This check is a maintainer command with network access. It is not imported or
packaged as runtime behavior. Source drift or an unrecorded version exits with
failure and leaves the reviewed baseline untouched. `--record` is explicit,
and still requires human review and successful integration tests.

## CI and scheduling

PR tests have read-only repository permissions and no publishing credentials.
Actions are pinned to commits; Dependabot updates those pins. No tests use
live providers automatically. A manual smoke test is available only with
`PI_CLIENT_LIVE_TESTS=1`; it uses the caller's configured Pi and may incur model
usage. Optional `PI_CLIENT_LIVE_PROVIDER` and `PI_CLIENT_LIVE_MODEL` select the
configured model explicitly.

Configure branch protection to require `required`, prevent force pushes, and
require resolved discussions. For a solo maintainer, do not require approval
from the PR author; record the engineering review and let mandatory checks
enforce the merge gate. Enable Dependabot alerts and security updates in the
repository settings when access is available.

Scheduled workflows can be delayed or disabled after repository inactivity.
Check workflow health and use manual dispatch when needed. This project does
not promise immediate compatibility with an unseen upstream release.

References: [Dependabot options](https://docs.github.com/en/code-security/reference/supply-chain-security/dependabot-options-reference),
[scheduled workflows](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule).

## Preserve the TypeScript comparison

Run `uv run python scripts/check_parity.py` after the locked Pi test runtime is
installed. The check verifies the embedded upstream source against the recorded
baseline before comparing commands/results and event delivery. Update the small
fixture and maintained [behavior contract](compatibility.md#typescript-behavior-contract)
when an intentional protocol/interface change is approved. Preserve the existing
failure, UI, output, and bounded-delivery regressions; do not change Python to
reproduce upstream error-handling or listener-mutation bugs. Run the comparison
again after internal simplifications and on the release candidate. After building,
run `uv run python scripts/check_distribution.py --parity` to repeat it against
the installed wheel alongside `run()`/streaming and protocol-helper smoke checks.

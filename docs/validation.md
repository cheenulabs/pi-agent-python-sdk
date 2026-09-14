# Implementation validation and remaining gates

Audited on **2026-09-15** against the actual implementation and Pi **0.85.1**.
This is evidence of local readiness, not a claim that the full public-release
goal has been achieved. Remote work remains incomplete.

## Executed checks

| Check | Observed result |
|---|---|
| Linux Python 3.11, 3.12, 3.13, 3.14 full suite | 205 passed on each; one live-model test explicitly deselected |
| Real Pi test prerequisites | Required mode enabled; exact runtime version 0.85.1 checked |
| Nine runnable example entry points | Passed with isolated real Pi and a faux provider; owned processes reaped and sync threads joined |
| Ruff check and format | Passed |
| Strict mypy | Package, examples, and example-smoke script passed |
| Upstream source comparison | All recorded fingerprints and offline version constants match npm Pi 0.85.1 and commit d981de1229ef899957bbe968bc8dcda02a21f477 |
| Actionlint 1.7.12 | All three workflow files passed |
| Wheel and source archive | Built successfully; Twine metadata checks passed; no test/npm runtime included |
| Installed wheel outside checkout | Fresh environment, no runtime dependencies, isolated Python import; sync and async runs passed |
| Markdown | Relative links, table widths, Python code fences, and formatting checked |

The Python matrix used isolated uv environments and this command, changing the
selected Python version for each run:

```sh
PI_CLIENT_REQUIRE_INTEGRATION=1 PI_CLIENT_EXPECTED_PI_VERSION=0.85.1 \
  uv run --locked --isolated --python 3.14 --group dev pytest -m 'not live' -q
```

See [CONTRIBUTING.md](../CONTRIBUTING.md) for the remaining reproducible checks.
No live provider, existing user configuration, or production service was used.

## Plan-to-evidence audit

| Plan requirement | Authoritative local evidence | Status / limit |
|---|---|---|
| Discovery, TS reference, existing Python behavior | [discovery.md](discovery.md), immutable source links and full inventory | Complete |
| Public package metadata, license, zero dependencies, typed marker | pyproject.toml, LICENSE, py.typed; built metadata and distribution checker | Local artifacts verified; index name/publisher ownership not established |
| Normal Pi defaults; explicit executable/env/session options | client.py constructor, _launch.py; launch and isolated-runtime tests | Implemented; no configuration or runtime installation side effects |
| All 33 RPC commands and meaningful return values | types.py, explicit async/sync methods, test_commands.py, sync forwarding/signature checks | All 33 exercised against real Pi through async core; blocking real-Pi scenarios also pass |
| Events, nested deltas, messages, entries and extension UI | test_types.py compares discovered unions; real UI and stream tests | 23 session events, two extra RPC record types, 12 nested variants, nine UI methods, seven message roles and nine entry variants represented |
| Omission/null/future-field compatibility | Type annotations, null fake responses, real veto/missing-text responses, unknown event tests | Verified documented cases; unseen upstream semantics are not certified |
| Readiness, framing, size limits, response correlation and failure | test_transport.py and test_launch.py | Includes fragmented UTF-8, Unicode separators, EOF record, malformed/oversized input, duplicates, errors and uncertain deadlines |
| Process cleanup under exit/cancellation/full or inherited pipes | Transport regression tests and startup/UI/finally close tests | Owned process and handles verified; arbitrary extension descendants are not controlled |
| One owned run, concurrent controls, retries and settlement | test_client.py, test_runs.py | Includes events before acknowledgement, queued steer/follow-up, retries, overflow/compaction recovery and no-start closure |
| Results, partial failures, stop reasons, identity and usage | Fake and real run tests; extension session replacement | No stale previous answer; unknown usage stays unknown; observed assistant usage only |
| Bounded subscriptions and UI handling | Record/byte overflow tests, blocked callbacks, UI close/error/reply tests | Explicit failures; blocked user callback threads cannot be forcibly terminated |
| Cancellation and interruption | Async task/context/timeout cases; sync Ctrl-C read/result/run tests | Cleanup retains ownership; uncertain preflight closes Pi |
| Sync facade parity and thread lifecycle | test_sync.py; real sync tool/retry/stream/queue tests and examples | Explicit methods, persistent loop, startup failures, concurrent close and iterator behavior verified |
| Three test layers | Fake executable suites, real faux-provider integration, opt-in test_live.py | First two executed; live test implemented but deliberately not run |
| Python/OS CI and package gates | ci.yml; local four-Python matrix; Actionlint | Linux verified locally; GitHub, macOS and Windows execution pending |
| Public docs, comments and runnable examples | README, API/usage/error/compatibility guides, public docstrings, scripts/check_examples.py | Nine examples executed; ordinary Markdown guides retained |
| Dependency updates and latest stable Pi | dependabot.yml, latest-pi.yml, check_upstream.py, compatibility.json | Local configuration and current baseline verified; scheduled execution and repository settings pending |
| Source drift review blocks unnoticed changes | Fingerprint inventory, diff report, maintenance regression tests, CI protocol gate | Explicit recording required; behavior tests do not automatically bless new versions |
| Review milestones and cleanup | [reviews.md](reviews.md), stacked branch history | Engineering reviews/fixes complete locally; remote PR review/merge still pending |
| TestPyPI rehearsal and reviewed 0.1.0 release | publish.yml, [releasing.md](releasing.md), built archives | Not executed; Trusted Publishers and environments need external setup |

## External gates still required

The configured repository is
`https://github.com/cheenulabs/pi-coding-agent-python-client`. Git and GitHub API
access returned **404**; the available GitHub login is `has-c`, with no second
configured account. No push, remote PR creation, merge, environment setup, or
package publication succeeded or has been claimed.

Required next evidence:

1. Correct repository location or restored write access.
2. Actual PRs and merges for the stacked branches in [implementation.md](implementation.md).
3. Successful remote CI, including macOS and Windows, on the release commit;
   required checks and Dependabot settings configured.
4. PyPI/TestPyPI project ownership and Trusted Publishers, approved environments,
   a successful rehearsal, then the reviewed release and clean index install.

Until those states are observed, the end-to-end goal remains incomplete.

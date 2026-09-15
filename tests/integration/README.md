# Real Pi offline fixture

`fixture.ts` runs inside the real Pi runtime. It uses Pi's public
`createFauxCore`, `fauxAssistantMessage`, and extension APIs; it never calls
an external model. The synthetic API key is a literal test value, and the
provider's unused base URL is `http://localhost:0`.

Install the pinned runtime from the repository root:

```sh
npm ci --prefix tests/pi --ignore-scripts --no-audit --no-fund
```

Use Node 22.19.0 or newer. On Linux/macOS, the executable is
`tests/pi/node_modules/.bin/pi`. On Windows, npm creates `pi.cmd`; a harness
can also invoke Node with
`tests/pi/node_modules/@earendil-works/pi-coding-agent/dist/bundle/cli.js`.
Resolve paths before changing the child's working directory.

## Isolation

Each test must create separate temporary project and configuration directories,
set `PI_CODING_AGENT_DIR` to that configuration directory, and pass a minimal
environment containing PATH and any OS-required process variables. Do not
inherit provider credentials. Start Pi with:

```text
--mode rpc --provider python-fixture --model fixture
--no-builtin-tools --no-extensions --no-skills --no-prompt-templates
--no-context-files --no-themes --no-approve
--extension <absolute-path-to-fixture.ts>
```

`--no-builtin-tools` keeps the fixture's harmless `fixture_echo` tool enabled.
`--no-tools` excludes extension tools too. Tests should retain persistence in
the temporary configuration directory when checking session commands;
`--no-session` is suitable for scenarios that intentionally disable it.

For fast retries and useful small-session compaction, write this synthetic
`settings.json` to the temporary configuration directory before launch:

```json
{
  "retry": {"enabled": true, "maxRetries": 2, "baseDelayMs": 1},
  "compaction": {"enabled": false, "keepRecentTokens": 1}
}
```

Wait for `get_state` readiness; verify its selected provider is
`python-fixture`. Both `fixture` and `fixture-other` are reasoning-enabled
offline models, allowing model/thinking command coverage without credentials.

## Response scripts

Submit `/fixture-script ` followed by a JSON array using `prompt()` and await
its acceptance before invoking `run()` or `stream()`. This command replaces
the provider's queued responses. Each step represents one model invocation;
retry and tool continuations consume another step. Exhausting the queue
produces Pi's explicit faux-provider error instead of making a network call.
Session replacement recreates extension state, so prepare a new response script
after switching sessions. The new-session command uses Pi's `withSession`
callback and fresh replacement context to do this safely.

```python
import json

await pi.prompt('/fixture-script ' + json.dumps([
    {"thinking": "synthetic reasoning", "text": "Hello fixture"},
]))
result = await pi.run("synthetic user input")
assert result.text == "Hello fixture"
```

Useful scripts:

| Scenario | Steps |
|---|---|
| Tool then answer | `[{"tool":"fixture_echo","arguments":{"text":"echo result"}},{"text":"tool complete"}]` |
| Retry then recover | `[{"stopReason":"error","error":"overloaded_error"},{"text":"recovered"}]` |
| Pause until cancellation/release | `[{"wait":"provider-gate","text":"released"}]` |
| Pause inside a tool | `[{"tool":"fixture_echo","arguments":{"text":"done","wait":"tool-gate"}},{"text":"complete"}]` |
| A nonstandard final reason | `[{"text":"partial","stopReason":"length"}]` |

Steps accept optional `text`, `thinking`, `tool`, `arguments`, `stopReason`,
`error`, and `wait` fields. Usage is Pi's own faux-provider estimate, which
allows usage aggregation assertions without pretending it is real billing.
Text block chunking comes from the upstream faux implementation. Assert
concatenated content and valid ordering, not a particular delta count.

`/fixture-gates` emits a notification containing the waiting gate names as a
JSON array. `/fixture-release <name>` releases a waiting gate; an early release
has no effect. Subscribe before checking readiness/releasing. Use distinct gate
names per active operation. Aborting the provider/tool/compaction also releases
its wait through the actual AbortSignal.

Release commands are normal extension prompts. During an owned run, send
`prompt("/fixture-release provider-gate", streaming_behavior="steer")` so the
request explicitly opts into the client's allowed steering route. Pi handles
the extension command before queueing ordinary model input. Low-level
`prompt()` with `events()` also supports these scenarios. High-level
cancellation tests need no release command. Avoid sleeps to guess whether an
operation is waiting: observe tool/compaction start, or the gate notification.

## Extension scenarios

| Input or command | Behavior |
|---|---|
| `fixture handled` | Ordinary input consumed by an input handler without starting a run |
| `/fixture-error` | Throws a fixed extension error; Pi still accepts the handled command |
| `/fixture-ui select` | Select dialog with `one` and `two` options |
| `/fixture-ui confirm` | Confirmation dialog |
| `/fixture-ui input` | Input dialog with a placeholder |
| `/fixture-ui editor` | Editor dialog with prefilled text |
| `/fixture-ui display` | Status, widget, title, editor-text, and notification events |
| `/fixture-veto on` / `off` | Enable/disable cancellation of new/switch/fork session operations |
| `/fixture-compact-gate <name>` | Pause the next compaction at that named gate |
| `/fixture-native-compaction on` / `off` | Run Pi's native summarization using queued faux responses, or restore the fixed summary |
| `/fixture-new-session-and-run` | Change session through the extension command context, then send synthetic input to the agent |
| `/fixture-entry` | Append a synthetic custom entry and emit `entry_appended` |

Dialog results are echoed in a notification as `{"result":...}`; missing
string responses become `null`. Reply with the dialog ID, using `confirmed`
for confirmation and `value` for the other dialogs. Replies have no command
acknowledgement. Unhandled/cancelled dialogs use the runtime's normal behavior.

Compaction is replaced by a `session_before_compact` handler returning the
fixed summary `Synthetic offline compaction summary` and the preparation's
real entry ID/token count. Create some conversation history first. This
exercises the real compaction lifecycle without invoking a summarization
provider. The run tests separately enable automatic compaction and script a
context-overflow error followed by recovery. Native summarization tests enable
`/fixture-native-compaction on`, then queue a `terminated` error and a recovered
summary to verify Pi's summarization retry events without external calls.

## Verified foundation

An isolated raw-JSONL probe against Pi 0.85.1 on Linux verified readiness,
model selection, text/thinking streaming, successful custom-tool execution,
automatic retry recovery, abort while the provider waits, all nine UI methods,
custom compaction, and new-session veto. These observations establish that
the fixture works; the Python package's integration tests must separately
assert the public client's behavior and all 33 command mappings. The fixture
does not access external services or existing user configuration.

`test_commands.py` checks the explicit command methods and UI surface.
`test_runs.py` checks settled results, streaming/tool usage, automatic retries,
steering and follow-up continuations, task/context/deadline cancellation,
handled-input start deadlines, partial errors, session identity refresh,
compaction recovery, and cancellation of active retry, compaction, and bash.

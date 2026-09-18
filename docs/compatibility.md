# Compatibility

This is a development preview. There is no published PyPI release yet; install
from the source checkout as described in the [README](../README.md). Compatibility
claims below distinguish the recorded protocol baseline from platform test
targets.

Check the proposed commit's CI results before relying on platform support.

## Runtime requirements

| Component | Policy |
|---|---|
| Python | Package requires 3.11 or newer; Linux CI targets 3.11, 3.12, 3.13, and 3.14 |
| Pi | Minimum and recorded tested protocol version: **0.85.1** |
| Node.js | Pi 0.85.1 requires **22.19.0 or newer** |
| Python runtime dependencies | None beyond the standard library |
| Platforms | CI targets Linux with Python 3.11–3.14; macOS and Windows with Python 3.14 |

Python's open-ended `>=3.11` metadata does not assert that every future Python
version has passed tests. Similarly, successfully launching an untested Pi
version is not a compatibility certification.

The pinned Pi source is commit
[`d981de1229ef899957bbe968bc8dcda02a21f477`](https://github.com/earendil-works/pi/tree/d981de1229ef899957bbe968bc8dcda02a21f477).
The [discovery document](discovery.md) records the upstream types, serializer,
implementation, and observed runtime behavior used to build the client. The
package wraps Pi's RPC protocol and is not an official upstream Python SDK.

## Startup version policy

Startup invokes the selected executable with `--version`; it does not contact npm,
PyPI, GitHub, or another version service. After startup:

| Selected executable | Behavior |
|---|---|
| Recognized version below 0.85.1 | Reject with `PiVersionError` |
| Exactly 0.85.1 | `pi_version="0.85.1"`, `compatibility="tested"` |
| Recognized newer version | Allow by default, with `compatibility="untested"` |
| Recognized untested version and `strict_version=True` | Reject with `PiVersionError` |
| Unparseable/custom version output | Reject unless `allow_unknown_version=True` |
| Explicit unknown-version override | `pi_version=None`, `compatibility="unknown"` |

Before startup, compatibility is `"unchecked"`. The unknown-version option is an
explicit override for custom executables and also permits unknown output when
strict checking is enabled. It does not allow a recognized version below the
minimum. Version output must be a plain numeric `major.minor.patch` string;
prerelease suffixes and custom banners are treated as unknown.

Strict checking can be useful when an application requires the recorded Pi
baseline. Applications that accept newer versions should inspect compatibility
and run their own integration checks before depending on new behavior.

## Runtime ownership and defaults

Pi must be installed separately. The client never silently installs, downloads,
or upgrades it. It also does not load credentials into Python models, implement
provider authentication, install extensions, or replace Pi's configuration.
Normal Pi configuration and environment inheritance remain in effect unless the
caller supplies overrides.

Each client owns a new `pi --mode rpc` subprocess. It cannot attach to a running
Pi terminal UI, and selecting an existing session file is different from
attaching to another process. The protocol has no general capability/version RPC,
shutdown command, session-listing RPC, tree-navigation RPC, or arbitrary
register-tool RPC. The Python client does not invent these capabilities.

## Windows executable resolution

Pi's known npm `.cmd`/`.bat` shim layout is resolved to Node and the installed Pi
CLI file without using a shell. If your package manager uses another layout,
provide the actual paths explicitly:

```python
from pi_coding_agent_client import PiClient


def main() -> None:
    # Replace both paths with the locations in your installation.
    with PiClient(executable=["node", "C:/path/to/pi/dist/bundle/cli.js"]) as pi:
        print(pi.get_state()["sessionId"])


if __name__ == "__main__":
    main()
```

This launch support does not substitute for testing Windows process cancellation,
pipes, or Pi's own tool prerequisites. The current verification scope remains
the platform table above.

## New protocol fields and events

Typed dictionaries describe the known wire surface. Unknown event types and
additional fields remain accessible through `Event.raw`; provider metadata stays
ordinary JSON-compatible data. The client does not discard those fields or
reconstruct a parallel assistant state machine.

Forward access to raw fields does not guarantee semantic compatibility. A future
Pi change to command results, event ordering, settlement, or UI behavior may need
a client update. Use `request()` for raw command access while retaining checked
responses and ownership restrictions, not to bypass them.

## Compatibility validation

Tests separate deterministic synthetic-process behavior from integration with a
real Pi installation. Real integration tests use a local faux provider and
isolated temporary config/projects, so they need no external credentials or
provider calls. Model-backed smoke tests must be explicitly enabled.

The compatibility gates cover command mappings, wire omissions, extension UI,
sessions, retries and compaction, streaming settlement, and cancellation.
See [CONTRIBUTING.md](../CONTRIBUTING.md) for validation commands and the
[integration setup](../tests/integration/README.md) for fixture configuration.
Automated latest-stable checks run in CI, not during package import or startup.
The [maintenance guide](maintenance.md) describes upstream protocol review,
and the [release checklist](releasing.md) records publication requirements.

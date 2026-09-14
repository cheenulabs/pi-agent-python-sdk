"""Review Pi source drift independently of behavioral integration tests.

Only --record replaces the reviewed baseline. Normal checks never update it.
This is a maintainer/CI utility; the installed client makes no network checks.
"""

from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import re
from pathlib import Path
from urllib.parse import quote
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
BASELINE = ROOT / "compatibility.json"
PACKAGE = "@earendil-works/pi-coding-agent"
FILES = (
    "packages/coding-agent/src/modes/rpc/rpc-types.ts",
    "packages/coding-agent/src/modes/rpc/rpc-mode.ts",
    "packages/coding-agent/src/modes/rpc/rpc-client.ts",
    "packages/coding-agent/src/modes/json-event.ts",
    "packages/coding-agent/src/core/agent-session.ts",
    "packages/coding-agent/src/core/session-manager.ts",
    "packages/coding-agent/src/core/messages.ts",
    "packages/agent/src/types.ts",
    "packages/ai/src/types.ts",
    "packages/coding-agent/CHANGELOG.md",
)


def fetch(url: str) -> bytes:
    with urlopen(url, timeout=30) as response:
        return response.read()


def source(commit: str, path: str) -> bytes:
    return fetch(f"https://raw.githubusercontent.com/earendil-works/pi/{commit}/{path}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", help="Exact candidate version, or latest; default is test pin")
    parser.add_argument(
        "--record", action="store_true", help="Record a baseline after manual review"
    )
    args = parser.parse_args()
    version = (
        args.version
        or json.loads((ROOT / "tests/pi/package.json").read_text())["devDependencies"][PACKAGE]
    )
    if version != "latest" and not re.fullmatch(r"\d+\.\d+\.\d+", version):
        parser.error("version must be a stable x.y.z release or latest")
    metadata = json.loads(fetch(f"https://registry.npmjs.org/{quote(PACKAGE, safe='')}/{version}"))
    exact = metadata["version"]
    commit = metadata["gitHead"]
    if not re.fullmatch(r"\d+\.\d+\.\d+", exact) or not re.fullmatch(r"[a-f0-9]{40}", commit):
        raise ValueError("Registry metadata does not identify a stable version and source commit")
    old = json.loads(BASELINE.read_text()) if BASELINE.exists() else {}
    current_sources = {path: source(commit, path) for path in FILES}
    fingerprints = {
        path: hashlib.sha256(data).hexdigest() for path, data in current_sources.items()
    }
    changed = [
        path for path in FILES if old.get("sourceSha256", {}).get(path) != fingerprints[path]
    ]
    report = [
        "# Pi compatibility review",
        "",
        f"Candidate: **{exact}** (`{commit}`).",
        f"Recorded tested version: **{old.get('testedVersion', 'none')}**.",
        "",
        "Integration results are a separate CI check. "
        "Passing old tests does not approve source drift.",
        "",
    ]
    for path in changed:
        report.extend(
            [
                f"## {path}",
                "",
                f"[Candidate source](https://github.com/earendil-works/pi/blob/{commit}/{path})",
                "",
            ]
        )
        if "upstreamCommit" in old:
            previous = source(old["upstreamCommit"], path).decode().splitlines()
            diff = difflib.unified_diff(
                previous,
                current_sources[path].decode().splitlines(),
                fromfile="reviewed",
                tofile="candidate",
                lineterm="",
            )
            report.extend(["```diff", *diff, "```", ""])
        else:
            report.extend(["No previous source fingerprint exists.", ""])
    if not changed:
        report.append("No fingerprinted source files changed.")
    (ROOT / "upstream-report.md").write_text("\n".join(report) + "\n", encoding="utf-8")
    if args.record:
        baseline = {
            "minimumVersion": old.get("minimumVersion", "0.85.1"),
            "testedVersion": exact,
            "upstreamCommit": commit,
            "sourceSha256": fingerprints,
        }
        BASELINE.write_text(json.dumps(baseline, indent=2) + "\n", encoding="utf-8")
        print(
            f"Recorded Pi {exact}; review the diff and update types, tests, "
            "constants and docs before merging."
        )
        return 0
    mismatch = exact != old.get("testedVersion") or commit != old.get("upstreamCommit")
    if changed or mismatch:
        print(
            f"Pi {exact} needs review: {len(changed)} source fingerprints changed; "
            "see upstream-report.md"
        )
        return 1
    # Keep the runtime's offline compatibility claim synchronized with the reviewed record.
    constants = (ROOT / "src/pi_coding_agent_client/_launch.py").read_text()
    for name, value in (
        ("MINIMUM_PI_VERSION", old["minimumVersion"]),
        ("TESTED_PI_VERSION", exact),
    ):
        if f'{name} = "{value}"' not in constants:
            print(f"{name} disagrees with compatibility.json")
            return 1
    print(f"Pi {exact} matches the reviewed protocol source ({commit})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

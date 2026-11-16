"""Check local Durable pins; optionally report an already-resolved npm latest version.

This maintenance utility does not install, upgrade, or contact a provider.
The SDK never invokes it at runtime.
"""

from __future__ import annotations

import argparse
import ast
import json
import re
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
PACKAGES = (
    "@earendil-works/pi-durable",
    "@earendil-works/pi-ai",
    "@earendil-works/chord",
    "@earendil-works/pi-coding-agent",
)


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"Expected an object in {path.name}")
    return value


def check_pins(root: Path) -> str:
    """Fail on any disagreement, including nested lockfile copies of pinned packages."""
    compatibility = read_json(root / "compatibility.json")
    version = compatibility["durable"]["testedVersion"]
    if not isinstance(version, str) or not re.fullmatch(r"\d+\.\d+\.\d+", version):
        raise ValueError("Durable testedVersion must be an exact stable version")
    manifest = read_json(root / "durable-host/package.json")["dependencies"]
    lock = read_json(root / "durable-host/package-lock.json")["packages"]
    for package in PACKAGES:
        if manifest.get(package) != version or lock[""]["dependencies"].get(package) != version:
            raise ValueError(f"{package} manifest/lock root pin disagrees with {version}")
        installed = [
            entry.get("version")
            for path, entry in lock.items()
            if path == f"node_modules/{package}" or path.endswith(f"/node_modules/{package}")
        ]
        if not installed or any(pin != version for pin in installed):
            raise ValueError(f"{package} locked versions disagree with {version}")
    tree = ast.parse((root / "src/pi_agent/durable/__init__.py").read_text(encoding="utf-8"))
    constants = [
        ast.literal_eval(node.value)
        for node in tree.body
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name) and target.id == "TESTED_PI_DURABLE_VERSION"
            for target in node.targets
        )
    ]
    if constants != [version]:
        raise ValueError("TESTED_PI_DURABLE_VERSION disagrees with compatibility.json")
    return version


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--latest", help="Compare with exact npm latest resolved by CI (no download)"
    )
    args = parser.parse_args()
    try:
        version = check_pins(ROOT)
    except (ValueError, KeyError, TypeError, OSError) as exc:
        print(f"Durable pin check failed: {exc}")
        return 1
    print(f"Durable pins agree at {version}")
    if args.latest is not None:
        if not re.fullmatch(r"\d+\.\d+\.\d+", args.latest):
            parser.error("--latest must be an exact stable x.y.z version")
        drift = args.latest != version
        report = (
            "# Pi Durable drift report\n\n"
            f"Recorded tested version: **{version}**.\n\n"
            f"npm latest: **{args.latest}**.\n\n"
            + (
                "Version drift requires review; no pin was changed.\n"
                if drift
                else "No version drift detected; this does not certify source compatibility.\n"
            )
        )
        (ROOT / "durable-drift-report.md").write_text(report, encoding="utf-8")
        return int(drift)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

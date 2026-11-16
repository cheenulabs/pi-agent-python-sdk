"""The core package does not eagerly import its experimental backend."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def test_core_import_does_not_load_durable(tmp_path: Path) -> None:
    subprocess.run(
        [
            sys.executable,
            "-I",
            "-c",
            "import sys; import pi_agent; "
            "assert not any(n == 'pi_agent.durable' or n.startswith('pi_agent.durable.') "
            "for n in sys.modules)",
        ],
        cwd=tmp_path,
        check=True,
        timeout=30,
    )

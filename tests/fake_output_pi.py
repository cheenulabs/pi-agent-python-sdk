"""Synthetic output with explicit command boundaries and no credentials."""

import json
import subprocess
import sys

START = b"startup\xff\xe2"
NORMAL = b"\x82\xac" + b"diagnostic" * 1000
END = b"shutdown\x00\xfe"

if "--version" in sys.argv:
    sys.stderr.buffer.write(b"version probe is separate")
    print("0.85.1")
    sys.exit()

sys.stderr.buffer.write(START)
sys.stderr.buffer.flush()
for line in sys.stdin:
    request = json.loads(line)
    command = request["type"]
    if command == "diagnostic":
        sys.stderr.buffer.write(NORMAL)
        sys.stderr.buffer.flush()
    if command == "inherit":
        subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(2)"], stdin=subprocess.DEVNULL
        )
    print(
        json.dumps(
            {
                "type": "response",
                "id": request["id"],
                "command": command,
                "success": True,
                "data": {
                    "sessionId": "fixture",
                    "isStreaming": False,
                    "isCompacting": False,
                    "pendingMessageCount": 0,
                },
            }
        ),
        flush=True,
    )
sys.stderr.buffer.write(END)
sys.stderr.buffer.flush()

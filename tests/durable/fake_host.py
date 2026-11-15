"""Synthetic Durable protocol peer; no Node, provider, or private configuration."""

from __future__ import annotations

import json
import os
import sys

mode = sys.argv[1] if len(sys.argv) > 1 else "normal"
seen: set[str] = set()
for line in sys.stdin:
    request = json.loads(line)
    command = request["type"]
    if mode == "startup_timeout" and command == "hello":
        continue
    if mode == "exit" and command == "wait":
        sys.exit(4)
    if mode == "stderr" and command == "hello":
        sys.stderr.write("synthetic-private-diagnostic-" * 100)
        sys.stderr.flush()
    if mode == "timeout_" + command and command not in seen:
        seen.add(command)
        continue
    data: object = {}
    if command == "hello":
        data = {
            "protocol": 1 if mode == "protocol" else 0,
            "pid": os.getpid(),
            "piDurable": "1.5.2",
        }
    elif command == "root":
        data = {"conversationId": 1}
    elif command == "submit":
        data = {"submissionId": 8}
    elif command == "wait":
        data = {"submission": {"status": "done", "future": {"retained": True}}}
    elif command == "entries":
        data = {"entries": [{"id": 1, "future": True}]}
    if mode.startswith("wrong_") and command == mode.removeprefix("wrong_"):
        data = {"submission": {"status": []}} if command == "wait" else []
    response = dict(type="response", id=request["id"], command=command, success=True, data=data)
    if mode in {"error", "stderr"} and command == "abort":
        response = dict(
            type="response",
            id=request["id"],
            command=command,
            success=False,
            error="synthetic-private-error",
            code="not_found",
        )
    print(json.dumps(response), flush=True)

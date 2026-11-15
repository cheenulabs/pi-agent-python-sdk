"""Synthetic Durable protocol peer; no Node, provider, or private configuration."""

from __future__ import annotations

import json
import os
import sys

mode = sys.argv[1] if len(sys.argv) > 1 else "normal"
seen: set[str] = set()
unwatched: list[str] = []
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
        data = {"entries": [{"id": 1, "future": True, "unwatched": unwatched}]}
    elif command == "unwatch":
        unwatched.append(request["watchId"])
    if mode.startswith("wrong_") and command == mode.removeprefix("wrong_"):
        data = {"submission": {"status": []}} if command == "wait" else []
    response = dict(type="response", id=request["id"], command=command, success=True, data=data)
    if (mode in {"error", "stderr"} and command == "abort") or (
        mode == "watch_error" and command == "watch"
    ):
        response = dict(
            type="response",
            id=request["id"],
            command=command,
            success=False,
            error="synthetic-private-error",
            code="not_found",
        )
    print(json.dumps(response), flush=True)
    if command == "watch" and response["success"]:
        count = 5 if mode == "burst" else 1
        for index in range(count):
            print(
                json.dumps(
                    dict(
                        type="durable_watch",
                        watchId=request["watchId"],
                        entries=[{"id": index + 1}],
                        live=None,
                        gap=False,
                        snapshot=index == 0,
                        future=True,
                    )
                ),
                flush=True,
            )
        if mode == "watch_end":
            print(
                json.dumps(
                    dict(type="durable_watch_end", watchId=request["watchId"], kind="ended")
                ),
                flush=True,
            )

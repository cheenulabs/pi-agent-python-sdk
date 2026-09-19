"""Deterministic subprocess fixture. Its control commands are test-only."""

from __future__ import annotations

import json
import os
import sys
import time
from typing import Any


def emit(record: dict[str, Any], *, newline: bool = True) -> None:
    data = json.dumps(record).encode("utf-8")
    sys.stdout.buffer.write(data + (b"\n" if newline else b""))
    sys.stdout.buffer.flush()


def response(request: dict[str, Any], **extra: Any) -> dict[str, Any]:
    return {
        "type": "response",
        "id": request["id"],
        "command": request["type"],
        "success": True,
        **extra,
    }


def main() -> None:
    if "--version" in sys.argv:
        print("0.85.1")
        return
    held: list[dict[str, Any]] = []
    for line in sys.stdin.buffer:
        request = json.loads(line)
        command = request["type"]
        if command == "extension_ui_response":
            emit({"type": "ui_received", "reply": request})
        elif command == "record_size":
            emit(response(request, data={"bytes": len(line) - 1}))
        elif command == "ui_input":
            emit(
                {
                    "type": "extension_ui_request",
                    "id": "string-dialog",
                    "method": request["method"],
                    "title": "Synthetic input",
                }
            )
            emit(response(request))
        elif command == "echo":
            emit(response(request, data=request.get("data")))
        elif command == "get_state":
            emit(
                response(
                    request,
                    data={
                        "sessionId": "fake-session",
                        "isStreaming": False,
                        "isCompacting": False,
                        "steeringMode": "all",
                        "followUpMode": "all",
                        "thinkingLevel": "off",
                        "autoCompactionEnabled": True,
                        "autoRetryEnabled": True,
                        "messageCount": 0,
                        "pendingMessageCount": 0,
                    },
                )
            )
        elif command == "fail":
            emit(response(request, success=False, error="synthetic failure"))
        elif command == "hold":
            held.append(request)
            emit({"type": "held", "id": request["id"]})
        elif command == "release":
            for previous in reversed(held):
                emit(response(previous, data=previous.get("data")))
            held.clear()
            emit(response(request))
        elif command == "duplicate":
            reply = response(request)
            emit(reply)
            emit(reply)
            emit({"type": "response", "id": "never-assigned", "command": "echo", "success": True})
        elif command == "fragment":
            data = json.dumps(response(request, data="é\u2028\u2029"), ensure_ascii=False).encode(
                "utf-8"
            )
            for byte in data + b"\r\n\n":
                os.write(sys.stdout.fileno(), bytes([byte]))
        elif command == "coalesce":
            records = [{"type": "new_future_event", "extra": True}, response(request)]
            os.write(
                sys.stdout.fileno(), b"\n".join(json.dumps(r).encode() for r in records) + b"\n"
            )
        elif command == "burst_exit":
            records = [{"type": "future", "sequence": i} for i in range(5000)]
            records.append(response(request))
            sys.stdout.buffer.write(b"\n".join(json.dumps(r).encode() for r in records))
            sys.stdout.buffer.flush()
            return
        elif command == "eof":
            emit(response(request), newline=False)
            return
        elif command == "raw":
            sys.stdout.buffer.write(bytes.fromhex(request["hex"]))
            sys.stdout.buffer.flush()
            if request.get("exit"):
                return
        elif command == "mismatch":
            emit(response(request, command="different"))
        elif command == "uncorrelated":
            emit({"type": "response", "command": "parse", "success": False, "error": "bad"})
        elif command == "exit":
            return
        elif command == "stderr":
            sys.stderr.write(request["data"])
            sys.stderr.flush()
            emit(response(request))
        elif command == "stop_reading":
            emit(response(request))
            # Deliberately wedged process; the parent must terminate it.
            time.sleep(3600)
        elif command in {"abort", "clear_queue"}:
            emit(response(request, data={"steering": [], "followUp": []}))
        else:
            emit(response(request, success=False, error=f"Unknown fake command: {command}"))


if __name__ == "__main__":
    main()

"""Synthetic command results and an explicit log of requests received by Pi."""

import json
import sys

if "--version" in sys.argv:
    print("0.85.1")
    raise SystemExit

received = []
cancelled = False
reject_state = False
nullable = False
for line in sys.stdin:
    request = json.loads(line)
    command = request["type"]
    response = {"type": "response", "id": request["id"], "command": command, "success": True}
    data = {}
    if command == "configure":
        cancelled = request.get("cancelled", False)
        nullable = request.get("nullable", False)
        reject_state = request.get("reject_state", False)
        received.clear()
    elif command == "received":
        data = {"requests": received}
    else:
        received.append({k: v for k, v in request.items() if k != "id"})
        if command == "get_state":
            data = {
                "sessionId": "fixture",
                "isStreaming": False,
                "isCompacting": False,
                "pendingMessageCount": 0,
            }
            if reject_state:
                response.update(success=False, error="Unexpected state refresh")
        elif command == "cycle_thinking_level":
            data = None if nullable else {"level": "high", "futureMetadata": {"kept": [1, 2]}}
        elif command == "export_html":
            data = {"path": "/synthetic/export.html", "futureMetadata": {"kept": [1, 2]}}
        elif command in {"new_session", "switch_session", "fork", "clone"}:
            data = {"cancelled": cancelled}
        elif command == "prompt" and request["message"] == "reject":
            response.update(success=False, error="Synthetic rejection")
    if response["success"]:
        response["data"] = data
    print(json.dumps(response), flush=True)

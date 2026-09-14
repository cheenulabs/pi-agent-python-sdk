"""Credential-free child for blocking-facade lifecycle and interaction tests."""

import json
import sys


def emit(record):
    print(json.dumps(record), flush=True)


def reply(request, data=None):
    record = {
        "type": "response",
        "id": request["id"],
        "command": request["type"],
        "success": True,
    }
    if data is not None:
        record["data"] = data
    emit(record)


if "--version" in sys.argv:
    print("0.85.1")
    raise SystemExit

streaming = False
session_name = None
dialog = None
for line in sys.stdin:
    request = json.loads(line)
    command = request["type"]
    if command == "get_state":
        state = {
            "sessionId": "synthetic-session",
            "isStreaming": streaming,
            "isCompacting": False,
            "pendingMessageCount": 0,
        }
        if session_name is not None:
            state["sessionName"] = session_name
        reply(request, state)
    elif command == "prompt":
        message = request["message"]
        if message == "/confirm":
            dialog = request
            emit(
                {
                    "type": "extension_ui_request",
                    "id": "dialog-1",
                    "method": "confirm",
                    "title": "Synthetic",
                    "message": "Continue?",
                }
            )
        else:
            reply(request)
            streaming = True
            emit({"type": "agent_start"})
            if message != "hold":
                emit(
                    {
                        "type": "message_update",
                        "assistantMessageEvent": {"type": "text_delta", "delta": message},
                    }
                )
                emit(
                    {
                        "type": "message_end",
                        "message": {
                            "role": "assistant",
                            "content": [{"type": "text", "text": message}],
                            "stopReason": "stop",
                        },
                    }
                )
                streaming = False
                emit({"type": "agent_end", "messages": [], "willRetry": False})
                emit({"type": "agent_settled"})
    elif command == "extension_ui_response":
        emit({"type": "synthetic_ui_reply", "reply": request})
        if dialog is not None:
            reply(dialog)
            dialog = None
    elif command == "clear_queue":
        reply(request, {"steering": [], "followUp": []})
    elif command == "abort":
        streaming = False
        emit({"type": "agent_settled"})
        reply(request)
    elif command == "set_session_name":
        session_name = request["name"]
        reply(request)
    elif command == "fail":
        emit(
            {
                "type": "response",
                "id": request["id"],
                "command": command,
                "success": False,
                "error": "synthetic rejection",
            }
        )
    elif command == "silent":
        emit({"type": "synthetic_waiting"})
    elif command == "exit":
        break
    else:
        reply(request, {key: value for key, value in request.items() if key not in {"type", "id"}})

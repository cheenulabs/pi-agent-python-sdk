"""Small scripted RPC child for public client failure and ordering tests."""

from __future__ import annotations

import json
import sys
import time


def emit(record):
    print(json.dumps(record, ensure_ascii=False), flush=True)


def reply(request, data=None, **extra):
    emit(
        {
            "type": "response",
            "command": request["type"],
            "id": request["id"],
            "success": True,
            "data": data,
            **extra,
        }
    )


def assistant(text="answer", reason="stop", usage=True):
    message = {
        "role": "assistant",
        "content": [{"type": "text", "text": text}],
        "stopReason": reason,
    }
    if usage:
        message["usage"] = {
            "input": 2,
            "output": 3,
            "cacheRead": 1,
            "cacheWrite": 0,
            "totalTokens": 6,
            "reasoning": 1,
            "cost": {"total": 0.01},
        }
    return {"type": "message_end", "message": message}


def main():
    if "--version" in sys.argv:
        print("0.85.1")
        return
    active = False
    ui_prompt = None
    pending_prompt = None
    startup_ui = "--startup-ui" in sys.argv
    for line in sys.stdin:
        request = json.loads(line)
        command = request["type"]
        if command == "get_state":
            if "--slow-state" in sys.argv:
                time.sleep(0.1)
            if startup_ui:
                startup_ui = False
                ui_prompt = request
                emit(
                    {
                        "type": "extension_ui_request",
                        "id": "startup",
                        "method": "confirm",
                        "title": "Fixture",
                        "message": "Start?",
                    }
                )
                continue
            reply(
                request,
                {
                    "sessionId": "current-session",
                    "isStreaming": active,
                    "isCompacting": False,
                    "pendingMessageCount": 0,
                },
            )
        elif command == "prompt":
            message = request["message"]
            if message in {"preack-paused", "preack-settled"}:
                pending_prompt = request
                active = message == "preack-paused"
                # Coalesce a complete batch before accepting any further commands.
                records = [{"type": "agent_start"}]
                if not active:
                    records.extend([assistant(), {"type": "agent_settled"}])
                sys.stdout.write("".join(json.dumps(record) + "\n" for record in records))
                sys.stdout.flush()
                continue
            if message == "rejected":
                reply(request, success=False, error="synthetic rejection")
                continue
            if message == "handled":
                reply(request)
                continue
            if message in {"ui", "ui-started"}:
                if message == "ui-started":
                    active = True
                    reply(request)
                    emit({"type": "agent_start"})
                else:
                    ui_prompt = request
                emit(
                    {
                        "type": "extension_ui_request",
                        "id": "dialog",
                        "method": "confirm",
                        "title": "Fixture",
                        "message": "Continue?",
                    }
                )
                continue
            emit({"type": "agent_start"})
            if message == "paused":
                active = True
                reply(request)
                continue
            if message.startswith("messages:"):
                reply(request)
                for index in range(int(message.split(":")[1])):
                    emit(assistant(str(index)))
                    time.sleep(0.005)  # consumer drains; aggregate retention still grows
                emit({"type": "agent_settled"})
                continue
            if message.startswith("usage:"):
                for changes in json.loads(message.removeprefix("usage:")):
                    event = assistant()
                    usage_changes = changes.pop("usage", {})
                    if usage_changes is None:
                        event["message"]["usage"] = None
                    else:
                        event["message"]["usage"].update(usage_changes)
                    event["message"].update(changes)
                    emit(event)
                emit({"type": "agent_settled"})
                reply(request)
                continue
            if message != "empty":
                emit({"type": "message_end", "message": {"role": "user", "content": message}})
                for _ in range(400 if message == "flood" else 1):
                    emit(
                        {
                            "type": "message_update",
                            "usage": {"totalTokens": 100},
                            "assistantMessageEvent": {
                                "type": "text_delta",
                                "contentIndex": 0,
                                "delta": "answer",
                            },
                        }
                    )
                if message == "recovered":
                    emit(assistant("", "error"))
                    emit({"type": "agent_end", "messages": [], "willRetry": True})
                    emit(
                        {
                            "type": "auto_retry_start",
                            "attempt": 1,
                            "maxAttempts": 2,
                            "delayMs": 0,
                            "errorMessage": "synthetic",
                        }
                    )
                reason = message.split(":", 1)[1] if message.startswith("stop:") else "stop"
                emit(assistant(reason=reason, usage=message != "unknown_usage"))
            emit({"type": "agent_end", "messages": [], "willRetry": False})
            emit({"type": "agent_settled"})
            reply(request)
        elif command == "extension_ui_response":
            emit({"type": "fixture_ui_reply", "reply": request})
            if ui_prompt is not None:
                reply(ui_prompt)
                ui_prompt = None
        elif command == "clear_queue":
            if "--fail-cleanup" in sys.argv:
                reply(request, success=False, error="synthetic cleanup failure")
                continue
            emit({"type": "queue_update", "steering": [], "followUp": []})
            reply(request, {"steering": [], "followUp": []})
        elif command == "abort":
            if active:
                active = False
                emit(assistant("partial", "aborted"))
                emit({"type": "agent_settled"})
            reply(request)
        elif command == "steer":
            if request["message"] == "exit":
                return
            if pending_prompt is not None and request["message"] in {"ack", "reject"}:
                if request["message"] == "reject":
                    reply(pending_prompt, success=False, error="synthetic late rejection")
                else:
                    reply(pending_prompt)
                pending_prompt = None
            if active and request["message"] == "release":
                active = False
                emit(assistant())
                emit({"type": "agent_settled"})
            reply(request)
        elif command == "emit":
            for record in request["records"]:
                emit(record)
            reply(request)
        elif command in {"cycle_model", "cycle_thinking_level"}:
            reply(request, None)
        elif command == "get_last_assistant_text":
            reply(request, {})
        else:
            emit({"type": "fixture_request", "request": request})
            reply(request, {})


if __name__ == "__main__":
    main()

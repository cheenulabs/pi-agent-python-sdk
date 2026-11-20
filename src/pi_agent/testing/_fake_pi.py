"""Scripted stand-in for ``pi --mode rpc``, launched by :class:`pi_agent.testing.FakePi`.

Standard library only and free of package imports, so it runs by file path with
any interpreter and environment. Arguments: ``<script.json> <requests.jsonl>``
followed by the options the client appends, which are ignored.
"""

from __future__ import annotations

import json
import sys
import time
from typing import Any


def _emit(record: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(record) + "\n")
    sys.stdout.flush()


def _respond(request: dict[str, Any], data: Any = None, error: str | None = None) -> None:
    record: dict[str, Any] = {
        "type": "response",
        "id": request.get("id"),
        "command": request.get("type"),
        "success": error is None,
    }
    if error is not None:
        record["error"] = error
    elif data is not None:
        record["data"] = data
    _emit(record)


def _assistant(reply: dict[str, Any], model: dict[str, str]) -> dict[str, Any]:
    content: list[dict[str, Any]] = []
    if reply.get("thinking"):
        content.append({"type": "thinking", "thinking": reply["thinking"]})
    content.append({"type": "text", "text": reply["text"]})
    usage = {
        "input": 0,
        "output": 0,
        "cacheRead": 0,
        "cacheWrite": 0,
        "totalTokens": 0,
        "cost": {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0, "total": 0},
    }
    usage.update(reply.get("usage") or {})
    message: dict[str, Any] = {
        "role": "assistant",
        "content": content,
        "api": "fake",
        "provider": model["provider"],
        "model": model["id"],
        "usage": usage,
        "stopReason": reply["stop_reason"],
        "timestamp": int(time.time() * 1000),
    }
    if reply.get("error_message") is not None:
        message["errorMessage"] = reply["error_message"]
    return message


def main() -> None:
    script = json.loads(open(sys.argv[1], encoding="utf-8").read())
    if "--version" in sys.argv[3:]:
        print(script["version"])
        return
    replies: list[dict[str, Any]] = script["replies"]
    model: dict[str, str] = script["model"]
    messages: list[dict[str, Any]] = []
    with open(sys.argv[2], "a", encoding="utf-8") as log:
        for line in sys.stdin:
            request = json.loads(line)
            log.write(json.dumps(request) + "\n")
            log.flush()
            command = request.get("type")
            if command == "get_state":
                _respond(
                    request,
                    {
                        "sessionId": script["session_id"],
                        "thinkingLevel": "off",
                        "isStreaming": False,
                        "isCompacting": False,
                        "steeringMode": "all",
                        "followUpMode": "all",
                        "autoCompactionEnabled": False,
                        "messageCount": len(messages),
                        "pendingMessageCount": 0,
                    },
                )
            elif command == "prompt":
                if not replies:
                    _respond(request, error="FakePi has no scripted reply left for this prompt")
                    continue
                reply = replies.pop(0)
                user = {
                    "role": "user",
                    "content": [{"type": "text", "text": request.get("message", "")}],
                    "timestamp": int(time.time() * 1000),
                }
                assistant = _assistant(reply, model)
                messages.extend((user, assistant))
                _respond(request, {"disposition": "started"})
                _emit({"type": "agent_start"})
                _emit({"type": "message_start", "message": user})
                _emit({"type": "message_end", "message": user})
                _emit({"type": "message_start", "message": {**assistant, "content": []}})
                if reply["text"]:
                    _emit(
                        {
                            "type": "message_update",
                            "message": assistant,
                            "assistantMessageEvent": {
                                "type": "text_delta",
                                "contentIndex": len(assistant["content"]) - 1,
                                "delta": reply["text"],
                            },
                        }
                    )
                _emit({"type": "message_end", "message": assistant})
                _emit({"type": "agent_end", "messages": [user, assistant], "willRetry": False})
                _emit({"type": "agent_settled"})
            elif command == "abort":
                _respond(request)
            elif command == "clear_queue":
                _respond(request, {"steering": [], "followUp": []})
            elif command == "get_messages":
                _respond(request, {"messages": messages})
            elif command == "get_last_assistant_text":
                texts = [
                    block["text"]
                    for message in messages[-1:]
                    for block in message["content"]
                    if block["type"] == "text"
                ]
                _respond(request, {"text": "".join(texts) if texts else None})
            elif command == "extension_ui_response":
                continue
            else:
                _respond(request, error=f"FakePi does not implement {command!r}")


if __name__ == "__main__":
    main()

"""Answer extension dialogs: python examples/ui.py '/your-installed-extension-command'."""

import argparse

from pi_agent import PiClient
from pi_agent.types import ExtensionUIRequest


def handle_ui(request: ExtensionUIRequest) -> str | bool | None:
    """Synchronous callbacks run off the loop; never call PiClient methods here."""
    if request["method"] == "confirm":
        return input(f"{request['title']}: {request['message']} [y/N] ").lower() == "y"
    if request["method"] == "select":
        print(request["title"])
        for index, option in enumerate(request["options"], start=1):
            print(f"{index}. {option}")
        answer = input("Choice number (empty cancels): ")
        if not answer.isdigit() or not 1 <= int(answer) <= len(request["options"]):
            return None
        return request["options"][int(answer) - 1]
    if request["method"] == "input" or request["method"] == "editor":
        # A single-line replacement is sufficient for this small example.
        return input(f"{request['title']}: ")
    if request["method"] == "notify":
        print(request["message"])
    # Status/widget/title/editor-text requests need no reply.
    return None


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", help="Installed extension command that requests UI")
    args = parser.parse_args()
    with PiClient(ui_handler=handle_ui) as pi:
        # Handled extension commands may never emit agent_start or agent_settled.
        receipt = pi.prompt(args.command)
        print(f"Command acknowledged: {receipt['success']}")


if __name__ == "__main__":
    main()

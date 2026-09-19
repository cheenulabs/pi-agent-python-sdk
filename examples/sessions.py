"""Inspect a session: python examples/sessions.py [--session SESSION] [--cwd PROJECT]."""

import argparse

from pi_agent import PiClient


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--session", help="Existing session selected using Pi's --session rules")
    parser.add_argument("--cwd", default=".")
    args = parser.parse_args()
    with PiClient(cwd=args.cwd, session=args.session) as pi:
        state = pi.get_state()
        print(f"Session ID: {state['sessionId']}")
        print(f"Session file: {state.get('sessionFile') or '(not available)'}")
        print(f"Session name: {state.get('sessionName') or '(unnamed)'}")
        print(f"Entries: {len(pi.get_entries()['entries'])}")


if __name__ == "__main__":
    main()

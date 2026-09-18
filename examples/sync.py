"""Run a prompt using your configured Pi installation: python examples/sync.py."""

import argparse

from pi_agent import PiClient


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "prompt", nargs="?", default="Explain this project's purpose without changing files."
    )
    args = parser.parse_args()
    with PiClient() as pi:
        result = pi.run(args.prompt)
        print(result.text)
        print(f"Stop reason: {result.stop_reason}")


if __name__ == "__main__":
    main()

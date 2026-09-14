"""Send a local image: python examples/images.py diagram.png 'Explain this diagram'."""

import argparse
import base64
from pathlib import Path

from pi_coding_agent_client import ImageContent, PiClient

MIME_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("image", type=Path)
    parser.add_argument("prompt", nargs="?", default="Describe this image.")
    args = parser.parse_args()
    mime_type = MIME_TYPES.get(args.image.suffix.lower())
    if mime_type is None:
        parser.error("Use a PNG, JPEG, GIF, or WebP file supported by your selected model.")
    image: ImageContent = {
        "type": "image",
        "data": base64.b64encode(args.image.read_bytes()).decode("ascii"),
        "mimeType": mime_type,
    }
    with PiClient() as pi:
        print(pi.run(args.prompt, images=[image]).text)


if __name__ == "__main__":
    main()

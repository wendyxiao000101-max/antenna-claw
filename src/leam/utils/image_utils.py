import base64
from typing import Dict, Iterable, List



def encode_images(paths: Iterable[str]) -> List[Dict]:
    """Convert images to base64 format for API use."""
    encoded: List[Dict] = []
    for path in paths:
        try:
            with open(path, "rb") as image_file:
                encoded_bytes = base64.b64encode(image_file.read())
            encoded.append(
                {
                    "type": "image_url",
                    "image_url": {
                        "url": (
                            "data:image/jpeg;base64,"
                            f"{encoded_bytes.decode('utf-8')}"
                        )
                    },
                }
            )
        except Exception as exc:
            print(f"Error encoding image {path}: {exc}")
    return encoded

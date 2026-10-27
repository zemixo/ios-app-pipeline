"""Write synthetic artifacts for the quickstart; never claim these are Xcode results."""
import json
import os
from pathlib import Path
import struct
import sys
import zlib


def png(width=16, height=16):
    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
    rows = b"".join(b"\0" + bytes([23, 31, 56]) * width for _ in range(height))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(rows)) + chunk(b"IEND", b""))


if __name__ == "__main__":
    out = Path(os.environ["PIPELINE_STEP_DIR"])
    if sys.argv[1] == "prepare":
        (out / "synthetic.json").write_text(json.dumps({"synthetic": True, "purpose": "Exercise orchestration, not iOS app correctness."}))
    elif sys.argv[1] == "screenshot":
        (out / "synthetic.png").write_bytes(png())
    else:
        raise SystemExit("Unknown fixture operation")

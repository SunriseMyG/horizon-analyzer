"""Write scenarios/fixtures/broken-model.glb: a .glb that no importer can read.

It starts like a real binary glTF (magic "glTF", version 2, a JSON chunk header) so it gets past
a check on the file extension or the magic bytes, but its JSON chunk is cut off mid-object. The
engine scenario imports it to check that Horizon refuses it with a clear error instead of
crashing or adding a broken asset.

Usage: python scripts/make_broken_glb.py
"""

import struct
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "scenarios" / "fixtures" / "broken-model.glb"


def main() -> None:
    json_chunk = b'{"asset":{"version":"2.0"},"meshes":[{"primitives":[{"attributes":{"POSITION":'  # truncated
    json_chunk += b" " * (-len(json_chunk) % 4)
    body = struct.pack("<I4s", len(json_chunk), b"JSON") + json_chunk
    header = struct.pack("<4sII", b"glTF", 2, 12 + len(body))
    OUT.write_bytes(header + body)
    print(f"written {OUT} ({OUT.stat().st_size} bytes)")


if __name__ == "__main__":
    main()

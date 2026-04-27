# qr_engine.py

import json
import qrcode
from PIL import Image


# -----------------------------
# Generate QR image (MAIN)
# -----------------------------
def make_qr(text, size=300):
    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=10,
        border=2
    )
    qr.add_data(text)
    qr.make(fit=True)

    img = qr.make_image(fill_color="black", back_color="white").convert("RGB")
    return img.resize((size, size), Image.NEAREST)


# -----------------------------
# Tile QR payload
# -----------------------------
def tile_qr_payload(tile, room, ts, ss, h):
    return json.dumps({
        "type": "tile",
        "id": tile.tile_id,
        "size": [round(tile.x1 - tile.x0, 3), round(tile.y1 - tile.y0, 3)],
        "z": [round(tile.z0, 3), round(tile.z1, 3)],
        "pipe_length": round(tile.pipe_length_m, 3),
        "pipe_in": round(tile.pipe_inlet_temp_c, 2),
        "pipe_out": round(tile.pipe_outlet_temp_c, 2)
    })


# -----------------------------
# Pipe QR payload
# -----------------------------
def pipe_qr_payload(part, h):
    return json.dumps({
        "type": "pipe",
        "id": part.part_id,
        "tile": part.tile_id,
        "kind": part.kind,  # straight / bend
        "points": len(part.points),
        "recommended_pipe": h.recommended_pipe
    })
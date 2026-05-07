import json
import qrcode
from PIL import Image

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

def tile_qr_payload(tile, room, ts, ss, h):
    return json.dumps({
        "type": "tile",
        "id": tile.tile_id,
        "room": {
            "length_m": round(room.length_m, 3),
            "width_m": round(room.width_m, 3)
        },
        "tile_spec": {
            "length_m": round(ts.length_m, 3),
            "width_m": round(ts.width_m, 3),
            "thickness_m": round(ts.thickness_m, 3)
        },
        "support_spec": {
            "plate_radius_m": round(ss.plate_radius_m, 4),
            "plate_height_m": round(ss.plate_height_m, 4),
            "column_radius_m": round(ss.column_radius_m, 4),
            "column_height_m": round(ss.column_height_m, 4),
            "cylinder_detail": getattr(ss, "cylinder_detail", 24)
        },
        "heating": {
            "tile_pipe_layout": getattr(h, "pipe_layout", "meander"),
            "room_pipe_layout": "one_pipe_per_tile_snake",
            "pipe_outer_diameter_m": round(h.pipe_outer_diameter_m, 4),
            "pipe_spacing_m": round(getattr(h, "pipe_spacing_m", 0.0), 4),
            "edge_cover_m": round(h.edge_cover_m, 4),
            "top_cover_m": round(h.top_cover_m, 4),
            "inlet_temp_c": round(h.inlet_temp_c, 2),
            "room_temp_c": round(h.room_temp_c, 2),
            "heat_loss_per_m_k": round(h.heat_loss_per_m_k, 4),
            "recommended_pipe": h.recommended_pipe
        },
        "bounds": [
            round(tile.x0, 3),
            round(tile.y0, 3),
            round(tile.x1, 3),
            round(tile.y1, 3)
        ],
        "size": [round(tile.x1 - tile.x0, 3), round(tile.y1 - tile.y0, 3)],
        "z": [round(tile.z0, 3), round(tile.z1, 3)],
        "pipe_length": round(tile.pipe_length_m, 3),
        "pipe_in": round(tile.pipe_inlet_temp_c, 2),
        "pipe_out": round(tile.pipe_outlet_temp_c, 2),
        "pipe_points": [
            [round(p.x, 3), round(p.y, 3), round(p.z, 3), round(p.temp_c, 2)]
            for p in tile.pipe_points
        ],
        "pipe_parts": [
            {
                "id": part.part_id,
                "kind": part.kind,
                "points": len(part.points)
            }
            for part in tile.pipe_parts
        ]
    })

def pipe_qr_payload(part, h):
    return json.dumps({
        "type": "pipe",
        "id": part.part_id,
        "tile": part.tile_id,
        "kind": part.kind,
        "points": len(part.points),
        "point_data": [
            [round(p.x, 3), round(p.y, 3), round(p.z, 3), round(p.temp_c, 2)]
            for p in part.points
        ],
        "tile_pipe_layout": getattr(h, "pipe_layout", "meander"),
        "room_pipe_layout": "one_pipe_per_tile_snake",
        "pipe_outer_diameter_m": round(h.pipe_outer_diameter_m, 4),
        "pipe_spacing_m": round(getattr(h, "pipe_spacing_m", 0.0), 4),
        "recommended_pipe": h.recommended_pipe
    })
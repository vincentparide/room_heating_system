import math

from PIL import Image, ImageDraw

try:
    import qrcode
except ImportError:
    qrcode = None


def _missing_qr_image(size):
    img = Image.new("RGB", (size, size), "white")
    draw = ImageDraw.Draw(img)
    margin = max(10, size // 20)
    draw.rectangle((0, 0, size - 1, size - 1), outline="black")
    text = (
        "QR package missing\n\n"
        "Install in this Python:\n"
        "python -m pip install qrcode[pil]"
    )
    draw.multiline_text((margin, margin), text, fill="black", spacing=6)
    return img


def make_qr(text, size=300):
    if qrcode is None:
        return _missing_qr_image(size)

    errors = []
    for correction in (qrcode.constants.ERROR_CORRECT_M, qrcode.constants.ERROR_CORRECT_L):
        try:
            qr = qrcode.QRCode(
                version=None,
                error_correction=correction,
                box_size=10,
                border=2
            )
            qr.add_data(text)
            qr.make(fit=True)
            break
        except Exception as exc:
            errors.append(exc)
            qr = None
    if qr is None:
        raise errors[-1]
    img = qr.make_image(fill_color="black", back_color="white").convert("RGB")
    return img.resize((size, size), Image.NEAREST)


def _pt(p):
    return [round(p.x, 3), round(p.y, 3), round(p.z, 3), round(p.temp_c, 2)]


def _part_length(part):
    if len(part.points) < 2:
        return 0.0
    pts = part.points
    return sum(
        math.dist((a.x, a.y, a.z), (b.x, b.y, b.z))
        for a, b in zip(pts[:-1], pts[1:])
    )


def _part_samples(part):
    pts = part.points
    if not pts:
        return []
    indexes = sorted({0, len(pts) // 2, len(pts) - 1})
    return [_pt(pts[i]) for i in indexes]


def _part_summary(part):
    return {
        "id": part.part_id,
        "type": "curved" if part.kind == "bend" else "straight",
        "points": len(part.points),
        "length_m": round(_part_length(part), 3),
        "samples": _part_samples(part)
    }


def _fmt_point(p):
    return f"x={p.x:.3f} m, y={p.y:.3f} m, z={p.z:.3f} m, temp={p.temp_c:.2f} °C"


def _sample_lines(part, prefix="  "):
    pts = part.points
    if not pts:
        return [f"{prefix}Samples: none"]
    indexes = sorted({0, len(pts) // 2, len(pts) - 1})
    labels = ["Start", "Middle", "End"] if len(indexes) == 3 else ["Start", "End"] if len(indexes) == 2 else ["Point"]
    return [f"{prefix}{label}: {_fmt_point(pts[index])}" for label, index in zip(labels, indexes)]


def tile_qr_payload(tile, room, ts, ss, h):
    return "\n".join([
        "TILE FLUID TEMPERATURE DATA",
        "",
        f"Tile ID: {tile.tile_id}",
        "",
        f"Incoming fluid temp: {tile.pipe_inlet_temp_c:.2f} °C",
        f"Outlet fluid temp: {tile.pipe_outlet_temp_c:.2f} °C",
        f"Tile fluid ΔT: {tile.pipe_inlet_temp_c - tile.pipe_outlet_temp_c:.2f} K",
        "",
        "Whole Circuit",
        f"Circuit inlet temp: {h.inlet_temp_c:.2f} °C",
        f"Circuit outlet temp: {getattr(h, 'return_temp_c', 0.0):.2f} °C",
        f"Calculated circuit ΔT: {getattr(h, 'calculated_water_delta_t_k', 0.0):.2f} K",
        f"Water density: {getattr(h, 'water_density_kg_m3', 0.0):.1f} kg/m³",
        f"Mass flow: {getattr(h, 'mass_flow_kg_h', 0.0):.2f} kg/h",
        f"Volume flow: {getattr(h, 'volume_flow_l_min', 0.0):.3f} L/min",
    ])


def pipe_qr_payload(part, h):
    lines = [
        "PIPE QR DATA",
        "",
        "Pipe Section",
        f"  ID: {part.part_id}",
        f"  Tile: {part.tile_id}",
        f"  Type: {'curved' if part.kind == 'bend' else 'straight'}",
        f"  Length: {_part_length(part):.3f} m",
        f"  Points: {len(part.points)}",
        "",
        "Samples",
    ]
    lines.extend(_sample_lines(part, "  "))
    lines.extend([
        "",
        "Heating",
        "  Pipe route: one_pipe_per_tile_snake",
        f"  Pipe orientation: {getattr(h, 'pipe_orientation', 'auto')}",
        f"  Pipe outer diameter: {h.pipe_outer_diameter_m:.4f} m",
        f"  Pipe spacing: {getattr(h, 'pipe_spacing_m', 0.0):.4f} m",
        f"  Inlet/Outlet tile number: {getattr(h, 'inlet_tile_index', 0)}",
        f"  Inlet/Outlet direction: {getattr(h, 'connection_direction', 'left')}",
        f"  Inlet/Outlet spacing: {getattr(h, 'pipe_connection_spacing_m', 0.0):.4f} m",
        f"  Recommended pipe: {h.recommended_pipe}",
        "",
        "Fluid Temperature",
        f"  Section entry temp: {part.points[0].temp_c if part.points else 0.0:.2f} °C",
        f"  Section exit temp: {part.points[-1].temp_c if part.points else 0.0:.2f} °C",
        f"  Section ΔT: {(part.points[0].temp_c - part.points[-1].temp_c) if part.points else 0.0:.2f} K",
        f"  Volume flow: {getattr(h, 'volume_flow_l_min', 0.0):.3f} L/min",
    ])
    return "\n".join(lines)

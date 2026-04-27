# layout_engine.py
from models import Tile, Support, RoomCircuit, PipePart
from geometry import tile_segments, uniq, polyline_length_xy
from pipe_engine import build_single_pipe_tile_path, neighbor_side, simulate_pipe_temperature
from qr_engine import pipe_qr_payload, tile_qr_payload

def build_room_circuit(room, tiles, xsegs, ysegs, h):
    nx, ny = len(xsegs), len(ysegs)
    order = []
    for yi in range(ny):
        xs = range(nx) if yi % 2 == 0 else range(nx - 1, -1, -1)
        for xi in xs: order.append((xi, yi))

    tile_map = {(xi, yi): tiles[yi + xi * ny] for xi in range(nx) for yi in range(ny)}
    room_pts = []
    room_parts = []

    def append_pt(p):
        if room_pts:
            last = room_pts[-1]
            if ((last.x - p.x)**2 + (last.y - p.y)**2 + (last.z - p.z)**2)**0.5 < 1e-9: return
        room_pts.append(p)

    for k, (xi, yi) in enumerate(order):
        t = tile_map[(xi, yi)]
        prev = order[k - 1] if k > 0 else None
        nxt = order[k + 1] if k < len(order) - 1 else None
        entry = "left" if prev is None else neighbor_side(prev[0] - xi, prev[1] - yi)
        exit_ = "right" if nxt is None else neighbor_side(nxt[0] - xi, nxt[1] - yi)
        pts, parts, Tin, Tout = build_single_pipe_tile_path(t, entry, exit_, h, PipePart)
        t.pipe_points = pts
        t.pipe_parts = parts
        t.pipe_inlet_temp_c = Tin
        t.pipe_outlet_temp_c = Tout
        t.pipe_length_m = polyline_length_xy([(p.x, p.y) for p in pts])
        for p in pts: append_pt(p)
        room_parts.extend(parts)

    full_pts, Tin, Tout = simulate_pipe_temperature([(p.x, p.y, p.z) for p in room_pts], h)
    return RoomCircuit(full_pts, room_parts, polyline_length_xy([(p.x, p.y) for p in full_pts]), Tin, Tout)

def compute_layout(room, ts, ss, h):
    xsegs = tile_segments(room.length_m, ts.length_m)
    ysegs = tile_segments(room.width_m, ts.width_m)
    z0 = 2 * ss.plate_height_m + ss.column_height_m
    z1 = z0 + ts.thickness_m
    tiles = []
    idx = 0
    for xi, (x0, x1, xf) in enumerate(xsegs):
        for yi, (y0, y1, yf) in enumerate(ysegs):
            tiles.append(Tile(x0, y0, x1, y1, z0, z1, bool(xf or yf), f"T{idx:03d}_x{xi}_y{yi}"))
            idx += 1
    xs = uniq([0.0] + [a for a, _, _ in xsegs] + [b for _, b, _ in xsegs])
    ys = uniq([0.0] + [a for a, _, _ in ysegs] + [b for _, b, _ in ysegs])
    supports = []
    seen = set()
    pr = ss.plate_radius_m
    for x in xs:
        for y in ys:
            cx = min(max(x, pr), room.length_m - pr)
            cy = min(max(y, pr), room.width_m - pr)
            key = (round(cx, 6), round(cy, 6))
            if key not in seen:
                seen.add(key)
                supports.append(Support(cx, cy, 0.0))
    circuit = build_room_circuit(room, tiles, xsegs, ysegs, h)
    for t in tiles:
        for p in getattr(t, "pipe_parts", []): p.qr_payload = pipe_qr_payload(p, h)
        t.qr_payload = tile_qr_payload(t, room, ts, ss, h)
    return tiles, supports, z0, z1, circuit
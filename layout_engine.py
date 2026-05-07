from models import Tile, Support, RoomCircuit, PipePart
from geometry import tile_segments, uniq, polyline_length_xy
from pipe_engine import build_single_pipe_tile_path, neighbor_side, simulate_pipe_temperature
from qr_engine import pipe_qr_payload, tile_qr_payload

def build_pipe_order(nx, ny):
    if nx <= 0 or ny <= 0:
        return []
    if ny < 2:
        return [(xi, 0) for xi in range(nx)]

    return_y = ny - 1
    main_ys = list(range(return_y))
    start_upward = (nx % 2 == 1)
    order = []

    for xi in range(nx):
        upward = start_upward if xi % 2 == 0 else not start_upward
        ys = main_ys if upward else list(reversed(main_ys))
        for yi in ys:
            order.append((xi, yi))

    for xi in range(nx - 1, -1, -1):
        order.append((xi, return_y))

    return order

def outside_side_for(cell, nx, ny):
    xi, yi = cell
    if yi == ny - 1:
        return "top"
    if yi == 0:
        return "bottom"
    if xi == 0:
        return "left"
    if xi == nx - 1:
        return "right"
    return "left"

def build_room_circuit(room, tiles, xsegs, ysegs, h):
    nx, ny = len(xsegs), len(ysegs)
    order = build_pipe_order(nx, ny)

    tile_map = {(xi, yi): tiles[yi + xi * ny] for xi in range(nx) for yi in range(ny)}
    room_pts = []
    room_parts = []
    ordered_tiles = []
    
    def append_pt(p):
        if room_pts:
            last = room_pts[-1]
            if ((last.x - p.x)**2 + (last.y - p.y)**2 + (last.z - p.z)**2)**0.5 < 1e-9: return
        room_pts.append(p)

    for k, (xi, yi) in enumerate(order):
        t = tile_map[(xi, yi)]
        prev = order[k - 1] if k > 0 else None
        nxt = order[k + 1] if k < len(order) - 1 else None
        entry = outside_side_for((xi, yi), nx, ny) if prev is None else neighbor_side(prev[0] - xi, prev[1] - yi)
        exit_ = outside_side_for((xi, yi), nx, ny) if nxt is None else neighbor_side(nxt[0] - xi, nxt[1] - yi)
        pts, parts, Tin, Tout = build_single_pipe_tile_path(t, entry, exit_, h, PipePart)
        
        t.pipe_points = pts
        t.pipe_parts = parts
        t.pipe_inlet_temp_c = Tin
        t.pipe_outlet_temp_c = Tout
        t.pipe_length_m = polyline_length_xy([(p.x, p.y) for p in pts])
        ordered_tiles.append(t)  
        for p in pts: append_pt(p)
        room_parts.extend(parts)

    full_pts, Tin, Tout = simulate_pipe_temperature([(p.x, p.y, p.z) for p in room_pts], h)
    temp_by_coord = {(round(p.x, 9), round(p.y, 9), round(p.z, 9)): p.temp_c for p in full_pts}

    def apply_global_temperatures(points):
        for p in points:
            key = (round(p.x, 9), round(p.y, 9), round(p.z, 9))
            if key in temp_by_coord:
                p.temp_c = temp_by_coord[key]

    for t in ordered_tiles:
        apply_global_temperatures(t.pipe_points)
        for part in t.pipe_parts:
            apply_global_temperatures(part.points)
        if t.pipe_points:
            t.pipe_inlet_temp_c = t.pipe_points[0].temp_c
            t.pipe_outlet_temp_c = t.pipe_points[-1].temp_c   
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

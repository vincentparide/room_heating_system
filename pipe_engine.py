import math
from geometry import round_corners_tagged
from models import PipePoint, PipePart

def neighbor_side(dx, dy):
    if dx == -1: return "left"
    if dx == 1: return "right"
    if dy == -1: return "bottom"
    if dy == 1: return "top"
    return "left"

def side_mid(tile, side, z):
    cx = 0.5 * (tile.x0 + tile.x1)
    cy = 0.5 * (tile.y0 + tile.y1)
    if side == "left": return (tile.x0, cy, z)
    if side == "right": return (tile.x1, cy, z)
    if side == "bottom": return (cx, tile.y0, z)
    if side == "top": return (cx, tile.y1, z)

def simulate_pipe_temperature(points3d, h):
    if not points3d: return [], h.inlet_temp_c, h.inlet_temp_c
    out = []
    total = 0.0
    for i, p in enumerate(points3d):
        if i > 0: total += math.dist(points3d[i - 1], p)
        temp = h.room_temp_c + (h.inlet_temp_c - h.room_temp_c) * math.exp(-h.heat_loss_per_m_k * total)
        out.append(PipePoint(p[0], p[1], p[2], temp))
    return out, h.inlet_temp_c, out[-1].temp_c

def build_single_pipe_tile_path(tile, entry, exit_, h, PipePartClass):
    z = tile.z1 - h.top_cover_m - 0.5 * h.pipe_outer_diameter_m
    p_in = side_mid(tile, entry, z)
    p_out = side_mid(tile, exit_, z)
    p_mid = (0.5 * (tile.x0 + tile.x1), 0.5 * (tile.y0 + tile.y1), z)

    base = [(p_in[0], p_in[1]), (p_mid[0], p_mid[1]), (p_out[0], p_out[1])]
    r = h.bend_radius_factor * (0.5 * h.pipe_outer_diameter_m)
    tagged = round_corners_tagged(base, r)

    pts = []
    parts = []
    current = None
    current_type = None
    part_id = 0

    for x, y, is_bend in tagged:
        p = PipePoint(x, y, z)
        pts.append(p)
        typ = "bend" if is_bend else "straight"
        if current_type is None:
            current_type = typ
            current = [p]
            continue
        if typ != current_type:
            if current_type == "bend":
                current.append(p)
            parts.append(PipePartClass(part_id=f"{tile.tile_id}_P{part_id}", kind=current_type, tile_id=tile.tile_id, points=current))
            part_id += 1
            current = [p] if current_type == "bend" else [current[-1], p]
            current_type = typ
        else:
            current.append(p)
    if current:
        parts.append(PipePartClass(part_id=f"{tile.tile_id}_P{part_id}", kind=current_type, tile_id=tile.tile_id, points=current))

    pts3d = [(p.x, p.y, p.z) for p in pts]
    sim_pts, Tin, Tout = simulate_pipe_temperature(pts3d, h)
    point_map = {id(src): dst for src, dst in zip(pts, sim_pts)}
    for part in parts:
        part.points = [point_map[id(p)] for p in part.points]
    return sim_pts, parts, Tin, Tout

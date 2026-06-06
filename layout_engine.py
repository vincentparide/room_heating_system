import math

from models import Tile, Support, RoomCircuit, PipePart, PipePoint
from geometry import tile_segments, uniq, polyline_length_xy, round_corners_tagged
from pipe_engine import pipe_temperature_at_distance, simulate_pipe_temperature
from qr_engine import pipe_qr_payload, tile_qr_payload
from en1264_engine import apply_en1264_design

REFERENCE_TILE = (0, 0)
_DIRECTION_TO_SIDE = {
    "left": "left",
    "right": "right",
    "up": "top",
    "top": "top",
    "down": "bottom",
    "bottom": "bottom",
}
_SWAPPED_SIDE = {
    "left": "bottom",
    "right": "top",
    "bottom": "left",
    "top": "right",
}


def _clamp_index(value, max_index):
    try:
        index = int(value)
    except (TypeError, ValueError):
        index = 0
    return max(0, min(max_index, index))


def _connection_side(tile, room):
    distances = [
        ("bottom", tile.y0),
        ("top", room.width_m - tile.y1),
        ("left", tile.x0),
        ("right", room.length_m - tile.x1),
    ]
    return min(distances, key=lambda item: item[1])[0]


def _connection_sides(tile, room):
    eps = 1e-9
    distances = [
        ("bottom", tile.y0),
        ("top", room.width_m - tile.y1),
        ("left", tile.x0),
        ("right", room.length_m - tile.x1),
    ]
    sides = [side for side, distance in distances if abs(distance) <= eps]
    return sides or [_connection_side(tile, room)]


def _requested_connection_side(h, swapped=False):
    side = _DIRECTION_TO_SIDE.get(str(getattr(h, "connection_direction", "left")).lower(), "left")
    return _SWAPPED_SIDE[side] if swapped else side


def _candidate_connection_sides(tile, room, h, swapped=False):
    sides = _connection_sides(tile, room)
    if len(sides) <= 1:
        return sides
    requested = _requested_connection_side(h, swapped)
    if requested not in sides:
        available = ", ".join("up" if side == "top" else "down" if side == "bottom" else side for side in sides)
        raise ValueError(f"Inlet/Outlet direction must match this corner tile ({available})")
    return [requested]


def _is_boundary_tile(tile, room):
    eps = 1e-9
    return (
        abs(tile.x0) <= eps or
        abs(tile.y0) <= eps or
        abs(tile.x1 - room.length_m) <= eps or
        abs(tile.y1 - room.width_m) <= eps
    )


def _connection_point(tile, side, edge, offset=0.0):
    width = tile.x1 - tile.x0
    depth = tile.y1 - tile.y0
    x_margin = min(max(edge, 0.0), 0.45 * width)
    y_margin = min(max(edge, 0.0), 0.45 * depth)

    if side in ("bottom", "top"):
        lo = tile.x0 + x_margin
        hi = tile.x1 - x_margin
        x = 0.5 * (tile.x0 + tile.x1) + offset
        if hi > lo:
            x = min(max(x, lo), hi)
        else:
            x = 0.5 * (tile.x0 + tile.x1)
        y = tile.y0 if side == "bottom" else tile.y1
        return x, y

    lo = tile.y0 + y_margin
    hi = tile.y1 - y_margin
    y = 0.5 * (tile.y0 + tile.y1) + offset
    if hi > lo:
        y = min(max(y, lo), hi)
    else:
        y = 0.5 * (tile.y0 + tile.y1)
    x = tile.x0 if side == "left" else tile.x1
    return x, y


def _inner_connection_point(tile, side, room, edge, offset=0.0):
    x, y = _connection_point(tile, side, edge, offset)
    if side == "bottom":
        return x, min(room.width_m - edge, max(edge, y + edge))
    if side == "top":
        return x, max(edge, min(room.width_m - edge, y - edge))
    if side == "left":
        return min(room.length_m - edge, max(edge, x + edge)), y
    return max(edge, min(room.length_m - edge, x - edge)), y


def _outer_connection_point(tile, side, edge, offset=0.0, extension=0.0):
    x, y = _connection_point(tile, side, edge, offset)
    ext = max(float(extension), 0.0)
    if side == "bottom":
        return x, y - ext
    if side == "top":
        return x, y + ext
    if side == "left":
        return x - ext, y
    return x + ext, y


def _connection_axis_limits(tile, side, edge):
    if side in ("bottom", "top"):
        span = tile.x1 - tile.x0
    else:
        span = tile.y1 - tile.y0
    margin = min(max(edge, 0.0), 0.45 * span)
    center = 0.5 * span
    return span, margin, margin - center, span - margin - center


def _corner_outer_offset(tile, side, room, edge):
    eps = 1e-9
    span, margin, _, _ = _connection_axis_limits(tile, side, edge)
    center = 0.5 * span
    if side in ("bottom", "top"):
        if abs(tile.x0) <= eps:
            return margin - center
        if abs(tile.x1 - room.length_m) <= eps:
            return span - margin - center
        return None
    if abs(tile.y0) <= eps:
        return margin - center
    if abs(tile.y1 - room.width_m) <= eps:
        return span - margin - center
    return None


def _connection_offsets(tile, side, room, h, edge, planned_exit_dy):
    _, _, lo, hi = _connection_axis_limits(tile, side, edge)
    available = max(hi - lo, 0.0)
    min_spacing = max(2.5 * getattr(h, "pipe_outer_diameter_m", 0.016), 0.0)
    requested = max(float(getattr(h, "pipe_connection_spacing_m", 0.10)), 0.0)
    spacing = min(max(requested, min_spacing), available)

    outer_offset = _corner_outer_offset(tile, side, room, edge)
    if outer_offset is not None:
        direction = 1.0 if outer_offset <= 0.0 else -1.0
        inner_offset = max(lo, min(hi, outer_offset + direction * spacing))
        return outer_offset, inner_offset

    half = 0.5 * spacing
    outlet_offset = -half if planned_exit_dy > 0.0 else half
    inlet_offset = -outlet_offset
    return inlet_offset, outlet_offset


def _corner_tangent_vector(tile, side, room, edge):
    outer_offset = _corner_outer_offset(tile, side, room, edge)
    if outer_offset is None:
        return 0.0, 0.0
    sign = 1.0 if outer_offset <= 0.0 else -1.0
    if side in ("bottom", "top"):
        return sign, 0.0
    return 0.0, sign


def _corner_tangent_approach(tile, side, room, edge, x, y, distance):
    tx, ty = _corner_tangent_vector(tile, side, room, edge)
    if abs(tx) < 1e-12 and abs(ty) < 1e-12:
        return x, y
    pad_x = min(max(edge, 0.0), 0.45 * (tile.x1 - tile.x0))
    pad_y = min(max(edge, 0.0), 0.45 * (tile.y1 - tile.y0))
    ax = x + tx * max(distance, 0.0)
    ay = y + ty * max(distance, 0.0)
    ax = max(tile.x0 + pad_x, min(tile.x1 - pad_x, ax))
    ay = max(tile.y0 + pad_y, min(tile.y1 - pad_y, ay))
    ax = max(edge, min(room.length_m - edge, ax))
    ay = max(edge, min(room.width_m - edge, ay))
    return ax, ay


def _side_inward_vector(side):
    if side == "bottom":
        return 0.0, 1.0
    if side == "top":
        return 0.0, -1.0
    if side == "left":
        return 1.0, 0.0
    return -1.0, 0.0


def _clamp_tile_interior_point(tile, room, edge, x, y):
    pad_x = min(max(edge, 0.0), 0.45 * (tile.x1 - tile.x0))
    pad_y = min(max(edge, 0.0), 0.45 * (tile.y1 - tile.y0))
    x = max(tile.x0 + pad_x, min(tile.x1 - pad_x, x))
    y = max(tile.y0 + pad_y, min(tile.y1 - pad_y, y))
    return (
        max(edge, min(room.length_m - edge, x)),
        max(edge, min(room.width_m - edge, y)),
    )


def _corner_pre_exit_points(tile, side, room, edge, x, y, tangent_distance, inward_distance):
    tx, ty = _corner_tangent_vector(tile, side, room, edge)
    nx, ny = _side_inward_vector(side)
    pre_exit = _clamp_tile_interior_point(
        tile,
        room,
        edge,
        x + nx * inward_distance,
        y + ny * inward_distance,
    )
    approach = _clamp_tile_interior_point(
        tile,
        room,
        edge,
        pre_exit[0] + tx * tangent_distance,
        pre_exit[1] + ty * tangent_distance,
    )
    return approach, pre_exit


def _corner_connector_radius(base_radius, tile, spacing_distance):
    tile_span = max(tile.x1 - tile.x0, tile.y1 - tile.y0)
    radius = max(base_radius, 0.85 * spacing_distance, 0.10)
    if tile_span > 1e-9:
        radius = min(radius, 0.45 * tile_span)
    return radius


def _segment_interval_in_tile(a, b, tile):
    dx = b.x - a.x
    dy = b.y - a.y
    t0, t1 = 0.0, 1.0

    for p, q in (
        (-dx, a.x - tile.x0),
        (dx, tile.x1 - a.x),
        (-dy, a.y - tile.y0),
        (dy, tile.y1 - a.y),
    ):
        if abs(p) < 1e-12:
            if q < 0.0:
                return None
            continue
        r = q / p
        if p < 0.0:
            if r > t1:
                return None
            t0 = max(t0, r)
        else:
            if r < t0:
                return None
            t1 = min(t1, r)

    if t1 <= t0:
        return None
    return t0, t1


def _segment_length_in_tile(a, b, tile):
    interval = _segment_interval_in_tile(a, b, tile)
    if interval is None:
        return 0.0
    t0, t1 = interval
    return math.hypot(b.x - a.x, b.y - a.y) * (t1 - t0)


def _temperature_at_pipe_distance(circuit, distance_m, h):
    return pipe_temperature_at_distance(distance_m, circuit.total_length_m, h)


def _tile_pipe_distance_intervals(circuit, tile):
    intervals = []
    distance_before = 0.0
    for a, b in zip(circuit.pipe_points[:-1], circuit.pipe_points[1:]):
        segment_length = math.dist((a.x, a.y, a.z), (b.x, b.y, b.z))
        interval = _segment_interval_in_tile(a, b, tile)
        if interval is not None and segment_length > 1e-9:
            t0, t1 = interval
            start = distance_before + segment_length * t0
            end = distance_before + segment_length * t1
            if end > start:
                intervals.append((start, end))
        distance_before += segment_length
    return intervals


def _merge_pipe_distance_intervals(intervals, gap_tol=1e-5, min_length=1e-6):
    merged = []
    for start, end in sorted(intervals):
        if end - start <= min_length:
            continue
        if not merged or start > merged[-1][1] + gap_tol:
            merged.append([start, end])
        else:
            merged[-1][1] = max(merged[-1][1], end)
    return [(start, end) for start, end in merged]


def _partial_tile_multi_pass_violations(circuit, tiles, allowed_tile_ids=None):
    allowed = set(allowed_tile_ids or ())
    violations = []
    for tile in tiles:
        if not tile.is_fractional or tile.tile_id in allowed:
            continue
        passes = _merge_pipe_distance_intervals(_tile_pipe_distance_intervals(circuit, tile))
        if len(passes) > 1:
            violations.append((tile.tile_id, len(passes)))
    return violations


def _tile_pipe_length(circuit, tile):
    length = 0.0
    for part in circuit.pipe_parts:
        for a, b in zip(part.points[:-1], part.points[1:]):
            length += _segment_length_in_tile(a, b, tile)
    return length


def _uncovered_tiles(circuit, tiles):
    return [tile for tile in tiles if _tile_pipe_length(circuit, tile) <= 1e-7]


def _orient(a, b, c):
    return (b.x - a.x) * (c.y - a.y) - (b.y - a.y) * (c.x - a.x)


def _segments_cross(a, b, c, d):
    eps = 1e-9
    if (
        max(a.x, b.x) + eps < min(c.x, d.x) or
        max(c.x, d.x) + eps < min(a.x, b.x) or
        max(a.y, b.y) + eps < min(c.y, d.y) or
        max(c.y, d.y) + eps < min(a.y, b.y)
    ):
        return False
    if (
        math.hypot(a.x - c.x, a.y - c.y) < eps or
        math.hypot(a.x - d.x, a.y - d.y) < eps or
        math.hypot(b.x - c.x, b.y - c.y) < eps or
        math.hypot(b.x - d.x, b.y - d.y) < eps
    ):
        return False
    o1 = _orient(a, b, c)
    o2 = _orient(a, b, d)
    o3 = _orient(c, d, a)
    o4 = _orient(c, d, b)
    return o1 * o2 < -eps and o3 * o4 < -eps


def _point_segment_distance(p, a, b):
    dx = b.x - a.x
    dy = b.y - a.y
    length2 = dx * dx + dy * dy
    if length2 < 1e-18:
        return math.hypot(p.x - a.x, p.y - a.y)
    t = ((p.x - a.x) * dx + (p.y - a.y) * dy) / length2
    t = max(0.0, min(1.0, t))
    x = a.x + t * dx
    y = a.y + t * dy
    return math.hypot(p.x - x, p.y - y)


def _segment_distance(a, b, c, d):
    if _segments_cross(a, b, c, d):
        return 0.0
    return min(
        _point_segment_distance(a, c, d),
        _point_segment_distance(b, c, d),
        _point_segment_distance(c, a, b),
        _point_segment_distance(d, a, b),
    )


def _points_close(a, b, tol=1e-8):
    return math.hypot(a.x - b.x, a.y - b.y) <= tol


def _crossing_segments(circuit):
    segments = []
    order = 0
    for part_index, part in enumerate(circuit.pipe_parts):
        pts = part.points
        if len(pts) < 2:
            continue
        if part.kind == "straight":
            segments.append((pts[0], pts[-1], order, part_index))
            order += 1
            continue
        step = max(1, len(pts) // 8)
        sampled = pts[::step]
        if sampled[-1] is not pts[-1]:
            sampled.append(pts[-1])
        for a, b in zip(sampled[:-1], sampled[1:]):
            segments.append((a, b, order, part_index))
            order += 1
    return segments


def _crossing_count(circuit, clearance=0.0):
    segments = _crossing_segments(circuit)
    crossings = 0
    for i, (a, b, order_a, part_a) in enumerate(segments):
        for j in range(i + 1, len(segments)):
            c, d, order_b, part_b = segments[j]
            if abs(order_a - order_b) <= 10:
                continue
            if abs(part_a - part_b) <= 1:
                continue
            if (
                _points_close(a, c) or _points_close(a, d) or
                _points_close(b, c) or _points_close(b, d)
            ):
                continue
            if _segment_distance(a, b, c, d) <= clearance:
                crossings += 1
    return crossings


def _edge_run_length(circuit, xsegs, ysegs, tolerance):
    x_edges = [xsegs[0][0]] + [x1 for _, x1, _ in xsegs]
    y_edges = [ysegs[0][0]] + [y1 for _, y1, _ in ysegs]
    total = 0.0
    for a, b, _, _ in _crossing_segments(circuit):
        dx = b.x - a.x
        dy = b.y - a.y
        length = math.hypot(dx, dy)
        if length <= tolerance:
            continue
        if abs(dx) <= tolerance and min(abs(a.x - x) for x in x_edges) <= tolerance:
            total += length
        elif abs(dy) <= tolerance and min(abs(a.y - y) for y in y_edges) <= tolerance:
            total += length
    return total


def _point_in_tile(p, tile):
    eps = 1e-9
    return (
        tile.x0 - eps <= p.x <= tile.x1 + eps and
        tile.y0 - eps <= p.y <= tile.y1 + eps
    )


def _assign_circuit_to_tiles(tiles, circuit, h):
    for tile in tiles:
        tile.pipe_points = [p for p in circuit.pipe_points if _point_in_tile(p, tile)]
        tile.pipe_parts = []
        tile.pipe_length_m = 0.0
        tile.pipe_entry_distance_m = 0.0
        tile.pipe_exit_distance_m = 0.0
        for part in circuit.pipe_parts:
            part_len = 0.0
            for a, b in zip(part.points[:-1], part.points[1:]):
                part_len += _segment_length_in_tile(a, b, tile)
            if part_len > 1e-7:
                tile.pipe_parts.append(part)
                tile.pipe_length_m += part_len

        intervals = _tile_pipe_distance_intervals(circuit, tile)
        if intervals:
            tile.pipe_entry_distance_m = min(start for start, _ in intervals)
            tile.pipe_exit_distance_m = max(end for _, end in intervals)
            tile.pipe_inlet_temp_c = _temperature_at_pipe_distance(circuit, tile.pipe_entry_distance_m, h)
            tile.pipe_outlet_temp_c = _temperature_at_pipe_distance(circuit, tile.pipe_exit_distance_m, h)
        else:
            tile.pipe_inlet_temp_c = 0.0
            tile.pipe_outlet_temp_c = 0.0


def _resimulate_circuit_temperatures(circuit, h):
    coords = [(p.x, p.y, p.z) for p in circuit.pipe_points]
    full_pts, tin, tout = simulate_pipe_temperature(coords, h)
    point_map = {id(src): dst for src, dst in zip(circuit.pipe_points, full_pts)}
    for part in circuit.pipe_parts:
        part.points = [point_map[id(p)] for p in part.points]
    circuit.pipe_points = full_pts
    circuit.inlet_temp_c = tin
    circuit.outlet_temp_c = tout
    h.calculated_water_delta_t_k = tin - tout
    return circuit


class _AxisRoom:
    def __init__(self, length_m, width_m):
        self.length_m = length_m
        self.width_m = width_m


def _copy_tiles(tiles):
    return [
        Tile(t.x0, t.y0, t.x1, t.y1, t.z0, t.z1, t.is_fractional, t.tile_id)
        for t in tiles
    ]


def _swap_tiles_xy(tiles):
    return [
        Tile(t.y0, t.x0, t.y1, t.x1, t.z0, t.z1, t.is_fractional, t.tile_id)
        for t in tiles
    ]


def _swap_circuit_xy(circuit):
    for p in circuit.pipe_points:
        p.x, p.y = p.y, p.x


def _build_axis_room_circuit(
    room, tiles, xsegs, ysegs, h,
    start_from_top_override=None,
    reverse_lanes=False,
    inlet_side_override=None,
    outlet_side_override=None,
):
    nx, ny = len(xsegs), len(ysegs)
    if not tiles or nx <= 0 or ny <= 0:
        return RoomCircuit()

    min_tile = min(
        min((x1 - x0) for x0, x1, _ in xsegs),
        min((y1 - y0) for y0, y1, _ in ysegs)
    )
    tile_map = {(xi, yi): tiles[yi + xi * ny] for xi in range(nx) for yi in range(ny)}
    ref = tile_map.get(REFERENCE_TILE, tiles[0])
    max_tile_index = len(tiles) - 1
    inlet_index = _clamp_index(getattr(h, "inlet_tile_index", 0), max_tile_index)
    outlet_index = inlet_index
    h.inlet_tile_index = inlet_index
    h.outlet_tile_index = outlet_index
    inlet_tile = tiles[inlet_index]
    outlet_tile = tiles[outlet_index]
    if not _is_boundary_tile(inlet_tile, room):
        raise ValueError("Inlet/Outlet must be a boundary tile")
    z = inlet_tile.z1 - h.top_cover_m - 0.5 * h.pipe_outer_diameter_m

    edge = max(h.edge_cover_m, 1.5 * h.pipe_outer_diameter_m)
    max_step = max(0.02, min(min_tile * 0.25, max(h.pipe_spacing_m, 0.05)))
    x_lanes = [
        0.5 * (x0 + x1)
        for x0, x1, _ in xsegs
        if edge <= 0.5 * (x0 + x1) <= room.length_m - edge
    ]
    if not x_lanes:
        x_lanes = [min(max(0.5 * (inlet_tile.x0 + inlet_tile.x1), edge), room.length_m - edge)]
    if reverse_lanes:
        x_lanes = list(reversed(x_lanes))

    first_y0, first_y1, _ = ysegs[0]
    last_y0, last_y1, _ = ysegs[-1]
    inlet_side = inlet_side_override or _connection_side(inlet_tile, room)
    if start_from_top_override is None:
        start_from_top = inlet_side == "top" or (inlet_side in ("left", "right") and 0.5 * (inlet_tile.y0 + inlet_tile.y1) > 0.5 * room.width_m)
    else:
        start_from_top = bool(start_from_top_override)
    planned_exit_dy = -1.0 if start_from_top else 1.0
    if len(x_lanes) > 1:
        last_bend_index = len(x_lanes) - 2
        if start_from_top:
            planned_exit_dy = 1.0 if last_bend_index % 2 == 0 else -1.0
        else:
            planned_exit_dy = -1.0 if last_bend_index % 2 == 0 else 1.0

    bottom_inner_y = first_y0 + 0.75 * (first_y1 - first_y0)
    top_inner_y = last_y1 - 0.75 * (last_y1 - last_y0)
    bottom_outer_y = max(edge, first_y1 - 0.75 * (first_y1 - first_y0))
    top_outer_y = min(room.width_m - edge, last_y0 + 0.75 * (last_y1 - last_y0))

    bottom_turn_y = bottom_inner_y
    top_turn_y = top_inner_y
    if planned_exit_dy < 0.0:
        top_turn_y = top_outer_y
    else:
        bottom_turn_y = bottom_outer_y

    min_gap_y = max(2.5 * h.pipe_outer_diameter_m, 0.04)
    if top_turn_y <= bottom_turn_y + min_gap_y:
        bottom_turn_y = first_y0 + 0.60 * (first_y1 - first_y0)
        top_turn_y = last_y1 - 0.60 * (last_y1 - last_y0)
    if top_turn_y <= bottom_turn_y + min_gap_y:
        bottom_turn_y = edge
        top_turn_y = room.width_m - edge

    room_pts = []
    room_parts = []

    def append_point(x, y):
        if room_pts:
            last = room_pts[-1]
            if math.dist((last.x, last.y, last.z), (x, y, z)) < 1e-9:
                return last
        p = PipePoint(x, y, z)
        room_pts.append(p)
        return p

    def add_part(kind, points):
        clean = []
        for p in points:
            if not clean or math.dist((clean[-1].x, clean[-1].y, clean[-1].z), (p.x, p.y, p.z)) > 1e-9:
                clean.append(p)
        if len(clean) < 2:
            return
        room_parts.append(PipePart(f"ROOM_P{len(room_parts):03d}", kind, "ROOM", clean))

    def append_straight_to(x, y):
        if not room_pts:
            append_point(x, y)
            return
        start = room_pts[-1]
        length = math.hypot(x - start.x, y - start.y)
        if length < 1e-9:
            return
        steps = max(1, int(math.ceil(length / max_step)))
        part_points = [start]
        for i in range(1, steps + 1):
            a = i / steps
            part_points.append(append_point(start.x + (x - start.x) * a, start.y + (y - start.y) * a))
        add_part("straight", part_points)

    def append_arc(cx, cy, radius, a0, a1):
        steps = max(24, int(64 * abs(a1 - a0) / math.pi))
        part_points = []
        for i in range(steps + 1):
            a = a0 + (a1 - a0) * (i / steps)
            part_points.append(append_point(cx + radius * math.cos(a), cy + radius * math.sin(a)))
        add_part("bend", part_points)

    def append_rounded_polyline(points, radius):
        points = [p for i, p in enumerate(points) if i == 0 or math.hypot(p[0] - points[i - 1][0], p[1] - points[i - 1][1]) > 1e-9]
        if len(points) < 2:
            return
        tagged = round_corners_tagged(points, radius)
        current_kind = None
        current_points = []
        for x, y, is_bend in tagged:
            p = append_point(x, y)
            kind = "bend" if is_bend else "straight"
            if current_kind is None:
                current_kind = kind
                current_points = [p]
            elif kind != current_kind:
                if current_kind == "bend":
                    current_points.append(p)
                add_part(current_kind, current_points)
                current_points = [p] if current_kind == "bend" else [current_points[-1], p]
                current_kind = kind
            else:
                current_points.append(p)
        add_part(current_kind, current_points)

    def turn_radius(i):
        return 0.5 * abs(x_lanes[i + 1] - x_lanes[i])

    connector_r = min(max(0.08, 0.30 * min_tile), max(0.01, 0.35 * room.width_m))
    outlet_side = outlet_side_override or (inlet_side if inlet_tile is outlet_tile else _connection_side(outlet_tile, room))
    connection_extension = max(float(getattr(h, "pipe_connection_extension_m", 0.0)), 0.0)
    inlet_offset, outlet_offset = _connection_offsets(
        inlet_tile,
        inlet_side,
        room,
        h,
        edge,
        planned_exit_dy,
    )
    inlet_x, inlet_y = _connection_point(inlet_tile, inlet_side, edge, inlet_offset)
    inlet_outer_x, inlet_outer_y = _outer_connection_point(
        inlet_tile, inlet_side, edge, inlet_offset, connection_extension
    )
    inlet_inner_x, inlet_inner_y = _inner_connection_point(
        inlet_tile, inlet_side, room, edge, inlet_offset
    )

    append_point(inlet_outer_x, inlet_outer_y)
    start_y = top_outer_y if start_from_top else bottom_outer_y
    if start_from_top and start_y <= top_turn_y:
        start_y = min(room.width_m - edge, top_turn_y + min_gap_y)
    elif not start_from_top and start_y >= bottom_turn_y:
        start_y = max(edge, bottom_turn_y - min_gap_y)
    if len(x_lanes) > 1:
        first_run_end_y = (bottom_turn_y + turn_radius(0)) if start_from_top else (top_turn_y - turn_radius(0))
    else:
        first_run_end_y = bottom_turn_y if start_from_top else top_turn_y
    append_rounded_polyline([
        (inlet_outer_x, inlet_outer_y),
        (inlet_x, inlet_y),
        (inlet_inner_x, inlet_inner_y),
        (inlet_inner_x, start_y),
        (x_lanes[0], start_y),
        (x_lanes[0], first_run_end_y),
    ], connector_r)

    if len(x_lanes) == 1:
        append_straight_to(x_lanes[0], bottom_turn_y if start_from_top else top_turn_y)

    final_exit_dy = -1.0 if start_from_top else 1.0
    for i, x in enumerate(x_lanes[:-1]):
        nxt = x_lanes[i + 1]
        cx = 0.5 * (x + nxt)
        radius = turn_radius(i)
        turn_at_top = (i % 2 == 0) != start_from_top
        if turn_at_top:
            cy = top_turn_y - radius
            append_straight_to(x, cy)
            append_arc(cx, cy, radius, math.pi, 0.0)
            final_exit_dy = -1.0
        else:
            cy = bottom_turn_y + radius
            append_straight_to(x, cy)
            append_arc(cx, cy, radius, math.pi, 2.0 * math.pi)
            final_exit_dy = 1.0

    low_return_y = bottom_outer_y
    high_return_y = top_outer_y
    if high_return_y <= top_turn_y:
        high_return_y = min(room.width_m - edge, top_turn_y + min_gap_y)
    if low_return_y >= bottom_turn_y:
        low_return_y = max(edge, bottom_turn_y - min_gap_y)

    return_y = high_return_y if final_exit_dy > 0.0 else low_return_y
    outlet_x, outlet_y = _connection_point(outlet_tile, outlet_side, edge, outlet_offset)
    outlet_inner_x, outlet_inner_y = _inner_connection_point(
        outlet_tile, outlet_side, room, edge, outlet_offset
    )
    outlet_outer_x, outlet_outer_y = _outer_connection_point(
        outlet_tile, outlet_side, edge, outlet_offset, connection_extension
    )

    outlet_path = [
        (room_pts[-1].x, room_pts[-1].y),
        (room_pts[-1].x, return_y),
    ]
    corner_parallel_exit = (
        inlet_tile is outlet_tile and
        inlet_side == outlet_side and
        _corner_outer_offset(outlet_tile, outlet_side, room, edge) is not None
    )
    outlet_connector_r = connector_r
    if corner_parallel_exit:
        spacing_distance = math.hypot(outlet_inner_x - inlet_inner_x, outlet_inner_y - inlet_inner_y)
        outlet_connector_r = _corner_connector_radius(connector_r, outlet_tile, spacing_distance)
        tangent_distance = max(2.0 * outlet_connector_r, spacing_distance)
        inward_distance = max(1.45 * outlet_connector_r, 0.75 * spacing_distance)
        tangent_span = (
            outlet_tile.x1 - outlet_tile.x0
            if outlet_side in ("bottom", "top")
            else outlet_tile.y1 - outlet_tile.y0
        )
        inward_span = (
            outlet_tile.y1 - outlet_tile.y0
            if outlet_side in ("bottom", "top")
            else outlet_tile.x1 - outlet_tile.x0
        )
        tangent_distance = min(tangent_distance, 0.80 * tangent_span)
        inward_distance = min(inward_distance, 0.65 * inward_span)
        approach, pre_exit = _corner_pre_exit_points(
            outlet_tile,
            outlet_side,
            room,
            edge,
            outlet_inner_x,
            outlet_inner_y,
            tangent_distance,
            inward_distance,
        )
        outlet_path.extend([
            (approach[0], return_y),
            approach,
            pre_exit,
            (outlet_inner_x, outlet_inner_y),
        ])
    else:
        outlet_path.extend([
            (outlet_inner_x, return_y),
            (outlet_inner_x, outlet_inner_y),
        ])
    outlet_path.extend([
        (outlet_x, outlet_y),
        (outlet_outer_x, outlet_outer_y),
    ])
    append_rounded_polyline(outlet_path, outlet_connector_r)

    route_length_m = polyline_length_xy([(p.x, p.y) for p in room_pts])
    apply_en1264_design(h, room.length_m * room.width_m, route_length_m)
    full_pts, Tin, Tout = simulate_pipe_temperature([(p.x, p.y, p.z) for p in room_pts], h)
    point_map = {id(src): dst for src, dst in zip(room_pts, full_pts)}
    for part in room_parts:
        part.points = [point_map[id(p)] for p in part.points]

    for tile in tiles:
        tile.pipe_points = [p for p in full_pts if _point_in_tile(p, tile)]
        tile.pipe_parts = []
        tile.pipe_length_m = 0.0
        for part in room_parts:
            part_len = 0.0
            for a, b in zip(part.points[:-1], part.points[1:]):
                part_len += _segment_length_in_tile(a, b, tile)
            if part_len > 1e-7:
                tile.pipe_parts.append(part)
                tile.pipe_length_m += part_len
        if tile.pipe_points:
            tile.pipe_inlet_temp_c = tile.pipe_points[0].temp_c
            tile.pipe_outlet_temp_c = tile.pipe_points[-1].temp_c
        else:
            tile.pipe_inlet_temp_c = 0.0
            tile.pipe_outlet_temp_c = 0.0

    return RoomCircuit(
        full_pts,
        room_parts,
        polyline_length_xy([(p.x, p.y) for p in full_pts]),
        Tin,
        Tout,
        inlet_tile.tile_id,
        outlet_tile.tile_id,
    )


def build_room_circuit(room, tiles, xsegs, ysegs, h, allow_partial_multi_pass=False):
    if not tiles or not xsegs or not ysegs:
        return RoomCircuit()

    max_tile_index = len(tiles) - 1
    inlet_index = _clamp_index(getattr(h, "inlet_tile_index", 0), max_tile_index)
    outlet_index = inlet_index
    h.inlet_tile_index = inlet_index
    h.outlet_tile_index = outlet_index
    swapped_room = _AxisRoom(room.width_m, room.length_m)
    swapped_tiles_for_sides = _swap_tiles_xy(tiles)
    vertical_inlet_sides = _candidate_connection_sides(tiles[inlet_index], room, h, False)
    horizontal_inlet_sides = _candidate_connection_sides(swapped_tiles_for_sides[inlet_index], swapped_room, h, True)

    candidates = []
    for start_from_top in (False, True):
        for reverse_lanes in (False, True):
            for inlet_side in vertical_inlet_sides:
                vertical_tiles = _copy_tiles(tiles)
                vertical = _build_axis_room_circuit(
                    room, vertical_tiles, xsegs, ysegs, h,
                    start_from_top, reverse_lanes, inlet_side, inlet_side
                )
                vertical.pipe_orientation = "vertical"
                candidates.append(vertical)

            for inlet_side in horizontal_inlet_sides:
                horizontal_tiles = _swap_tiles_xy(tiles)
                horizontal = _build_axis_room_circuit(
                    swapped_room, horizontal_tiles, ysegs, xsegs, h,
                    start_from_top, reverse_lanes, inlet_side, inlet_side
                )
                _swap_circuit_xy(horizontal)
                horizontal.pipe_orientation = "horizontal"
                candidates.append(horizontal)

    non_crossing_candidates = [
        circuit for circuit in candidates
        if _crossing_count(circuit, 0.0) == 0
    ]
    if not non_crossing_candidates:
        raise ValueError("Pipe route would cross. Try another Inlet/Outlet direction or tile layout.")
    candidates = non_crossing_candidates

    if not allow_partial_multi_pass:
        allowed_partial_tile_ids = {tiles[inlet_index].tile_id}
        partial_safe_candidates = [
            circuit for circuit in candidates
            if not _partial_tile_multi_pass_violations(circuit, tiles, allowed_partial_tile_ids)
        ]
        if not partial_safe_candidates:
            sample = _partial_tile_multi_pass_violations(candidates[0], tiles, allowed_partial_tile_ids)
            sample_ids = ", ".join(tile_id for tile_id, _ in sample[:3])
            suffix = f" Offending partial tile(s): {sample_ids}." if sample_ids else ""
            raise ValueError(
                "Pipe route would pass through a partial tile more than once."
                f"{suffix} Try another tile layout or Inlet/Outlet direction."
            )
        candidates = partial_safe_candidates

    def route_score(circuit):
        bend_count = sum(1 for part in circuit.pipe_parts if part.kind == "bend")
        uncovered_count = len(_uncovered_tiles(circuit, tiles))
        clearance = max(getattr(h, "pipe_outer_diameter_m", 0.016) * 1.25, 0.012)
        crossing_count = _crossing_count(circuit, clearance)
        edge_run_length = _edge_run_length(circuit, xsegs, ysegs, clearance)
        bend_penalty = max(getattr(h, "pipe_spacing_m", 0.05), 0.05) * bend_count
        return (
            uncovered_count,
            crossing_count,
            round(edge_run_length, 6),
            circuit.total_length_m + bend_penalty,
            circuit.total_length_m,
            len(circuit.pipe_parts),
            0 if circuit.pipe_orientation == "vertical" else 1,
        )

    chosen = min(
        candidates,
        key=route_score,
    )
    h.pipe_orientation = chosen.pipe_orientation
    apply_en1264_design(h, room.length_m * room.width_m, chosen.total_length_m)
    _resimulate_circuit_temperatures(chosen, h)
    _assign_circuit_to_tiles(tiles, chosen, h)
    return chosen


def compute_layout(room, ts, ss, h):
    xsegs = tile_segments(
        room.length_m,
        ts.length_m,
        getattr(ts, "partial_x_side", "right"),
        getattr(ts, "full_tile_offset_x_m", 0.0),
        getattr(ts, "partial_x_positions", None),
    )
    ysegs = tile_segments(
        room.width_m,
        ts.width_m,
        getattr(ts, "partial_y_side", "top"),
        getattr(ts, "full_tile_offset_y_m", 0.0),
        getattr(ts, "partial_y_positions", None),
    )
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
    manual_fractional_layout = (
        getattr(ts, "partial_x_side", "") == "manual" or
        getattr(ts, "partial_y_side", "") == "manual"
    )
    circuit = build_room_circuit(room, tiles, xsegs, ysegs, h, manual_fractional_layout)
    for t in tiles:
        for p in getattr(t, "pipe_parts", []): p.qr_payload = pipe_qr_payload(p, h)
        t.qr_payload = tile_qr_payload(t, room, ts, ss, h)
    return tiles, supports, z0, z1, circuit

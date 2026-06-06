import math


def _manual_partial_widths(leftover, placement, offset):
    if leftover <= 1e-6:
        return []
    if placement in ("center", "split"):
        first = 0.5 * leftover
        return [first, leftover - first]
    if placement in ("custom", "manual"):
        first = max(0.0, min(float(offset), leftover))
        widths = []
        if first > 1e-6:
            widths.append(first)
        if leftover - first > 1e-6:
            widths.append(leftover - first)
        return widths
    return [leftover]


def _default_partial_positions(full_count, placement, count):
    if count <= 0:
        return []
    if placement in ("start", "left", "bottom"):
        positions = [0]
    elif placement in ("center", "split"):
        positions = [0, full_count]
    else:
        positions = [full_count]
    while len(positions) < count:
        positions.append(full_count)
    return positions[:count]


def tile_segments(total, size, placement="end", offset=0.0, partial_positions=None):
    total = max(float(total), 0.0)
    size = max(float(size), 1e-9)
    if total <= 1e-9:
        return []

    full_count = int(math.floor((total + 1e-9) / size))
    while full_count > 0 and full_count * size > total + 1e-9:
        full_count -= 1
    leftover = max(total - full_count * size, 0.0)
    if full_count <= 0:
        return [(0.0, total, True)]

    if placement == "manual" and leftover > 1e-6:
        widths = _manual_partial_widths(leftover, placement, offset)
        positions = list(partial_positions or [])
        defaults = _default_partial_positions(full_count, placement, len(widths))
        while len(positions) < len(widths):
            positions.append(defaults[len(positions)])
        positions = [max(0, min(full_count, int(round(p)))) for p in positions[:len(widths)]]

        by_position = {}
        for width, position in zip(widths, positions):
            if width > 1e-6:
                by_position.setdefault(position, []).append(width)

        segs = []
        x = 0.0
        for i in range(full_count + 1):
            for width in by_position.get(i, []):
                x2 = min(x + width, total)
                if x2 - x > 1e-6:
                    segs.append((x, x2, True))
                x = x2
            if i < full_count:
                x2 = min(x + size, total)
                if x2 - x > 1e-6:
                    segs.append((x, x2, abs((x2 - x) - size) > 1e-6))
                x = x2
        return segs

    if leftover <= 1e-6:
        leading = 0.0
    elif placement in ("start", "left", "bottom"):
        leading = leftover
    elif placement in ("center", "split"):
        leading = 0.5 * leftover
    elif placement == "custom":
        leading = max(0.0, min(float(offset), leftover))
    else:
        leading = 0.0

    segs = []
    x = 0.0
    if leading > 1e-6:
        segs.append((0.0, leading, True))
        x = leading

    for _ in range(full_count):
        x2 = min(x + size, total)
        if x2 - x > 1e-6:
            segs.append((x, x2, abs((x2 - x) - size) > 1e-6))
        x = x2

    if total - x > 1e-6:
        segs.append((x, total, True))
    return segs

def uniq(vals, tol=1e-9):
    vals = sorted(vals)
    out = []
    for v in vals:
        if not out or abs(v - out[-1]) > tol:
            out.append(v)
    return out

def polyline_length_xy(pts):
    if len(pts) < 2: return 0.0
    return sum(math.hypot(x2 - x1, y2 - y1) for (x1, y1), (x2, y2) in zip(pts[:-1], pts[1:]))

def norm(x, y):
    L = math.hypot(x, y)
    return (x / L, y / L) if L > 1e-12 else (0.0, 0.0)

def dot(ax, ay, bx, by): return ax * bx + ay * by
def cross(ax, ay, bx, by): return ax * by - ay * bx

def round_corners_tagged(pts, r):
    """Generates TRUE circular arcs (C-Shapes) for bends."""
    if len(pts) < 3 or r <= 1e-9:
        return [(p[0], p[1], False) for p in pts]

    out = []
    out.append((pts[0][0], pts[0][1], False))

    for i in range(1, len(pts) - 1):
        p0, p1, p2 = pts[i - 1], pts[i], pts[i + 1]
        v1 = (p1[0] - p0[0], p1[1] - p0[1])
        v2 = (p2[0] - p1[0], p2[1] - p1[1])
        
        L1, L2 = math.hypot(*v1), math.hypot(*v2)
        if L1 < 1e-9 or L2 < 1e-9:
            out.append((p1[0], p1[1], False))
            continue

        u1, u2 = norm(*v1), norm(*v2)
        d = max(-1.0, min(1.0, dot(-u1[0], -u1[1], u2[0], u2[1])))
        ang = math.acos(d)

        if ang < 1e-3 or abs(math.pi - ang) < 1e-3:
            out.append((p1[0], p1[1], False))
            continue

        tangent = math.tan(ang / 2.0)
        trim = r * tangent
        trim = min(trim, min(L1, L2) * 0.45)
        arc_r = trim / tangent if abs(tangent) > 1e-12 else r

        t1 = (p1[0] - u1[0] * trim, p1[1] - u1[1] * trim)
        t2 = (p1[0] + u2[0] * trim, p1[1] + u2[1] * trim)

        out.append((t1[0], t1[1], False))

        # TRUE CIRCULAR ARC
        cr = cross(u1[0], u1[1], u2[0], u2[1])
        n1 = (-u1[1], u1[0])
        if cr < 0: n1 = (-n1[0], -n1[1])
        
        cx = t1[0] + n1[0] * arc_r
        cy = t1[1] + n1[1] * arc_r
        
        a1 = math.atan2(t1[1] - cy, t1[0] - cx)
        a2 = math.atan2(t2[1] - cy, t2[0] - cx)
        
        da = a2 - a1
        if cr > 0: 
            while da < 0: da += 2 * math.pi
        else:
            while da > 0: da -= 2 * math.pi
            
        steps = max(16, int(64 * abs(da) / math.pi))
        for k in range(1, steps):
            a = a1 + da * (k / steps)
            out.append((cx + arc_r * math.cos(a), cy + arc_r * math.sin(a), True)) # True = Bend

        out.append((t2[0], t2[1], False))

    out.append((pts[-1][0], pts[-1][1], False))
    
    # Cleanup duplicates
    clean = [out[0]]
    for p in out[1:]:
        if math.hypot(p[0] - clean[-1][0], p[1] - clean[-1][1]) > 1e-9:
            clean.append(p)
    return clean

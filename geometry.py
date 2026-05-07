import math

def tile_segments(total, size):
    segs = []
    x = 0.0
    while x < total:
        x2 = min(x + size, total)
        segs.append((x, x2, abs((x2 - x) - size) > 1e-6))
        x += size
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

        trim = r * math.tan(ang / 2.0)
        trim = min(trim, min(L1, L2) * 0.45)

        t1 = (p1[0] - u1[0] * trim, p1[1] - u1[1] * trim)
        t2 = (p1[0] + u2[0] * trim, p1[1] + u2[1] * trim)

        out.append((t1[0], t1[1], False))

        # TRUE CIRCULAR ARC
        cr = cross(u1[0], u1[1], u2[0], u2[1])
        n1 = (-u1[1], u1[0])
        if cr < 0: n1 = (-n1[0], -n1[1])
        
        cx = t1[0] + n1[0] * r
        cy = t1[1] + n1[1] * r
        
        a1 = math.atan2(t1[1] - cy, t1[0] - cx)
        a2 = math.atan2(t2[1] - cy, t2[0] - cx)
        
        da = a2 - a1
        if cr > 0: 
            while da < 0: da += 2 * math.pi
        else:
            while da > 0: da -= 2 * math.pi
            
        steps = 16 
        for k in range(1, steps):
            a = a1 + da * (k / steps)
            out.append((cx + r * math.cos(a), cy + r * math.sin(a), True)) # True = Bend

        out.append((t2[0], t2[1], False))

    out.append((pts[-1][0], pts[-1][1], False))
    
    # Cleanup duplicates
    clean = [out[0]]
    for p in out[1:]:
        if math.hypot(p[0] - clean[-1][0], p[1] - clean[-1][1]) > 1e-9:
            clean.append(p)
    return clean
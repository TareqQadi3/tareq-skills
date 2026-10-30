#!/usr/bin/env python3
"""Magical Surprise Eggs - procedural 3D-shaded YouTube Short for "عالم المغامرات".

Renders 1080x1920 @30fps, 28 s, with synthesized sound effects only (no music,
no voice). Pure numpy + ffmpeg. Usage:
    python3 render.py out.mp4 [--preview t1,t2,...]
"""
import math
import subprocess
import sys
import wave
from multiprocessing import Pool

import numpy as np

W, H, FPS, DUR = 1080, 1920, 30, 28.0
NFRAMES = int(FPS * DUR)

L = np.array([-0.45, -0.65, 0.62]); L /= np.linalg.norm(L)
HV = L + np.array([0, 0, 1.0]); HV /= np.linalg.norm(HV)

# When set to an RGB colour, every ellipsoid is drawn as a flat silhouette in
# that colour (used by the "guess the shadow" episode).
SILHOUETTE = None


def C(h):
    h = h.lstrip('#')
    return np.array([int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)], np.float32)


# ----------------------------------------------------------------------------
# Rendering primitives
# ----------------------------------------------------------------------------

def _box(cx, cy, r):
    x0, x1 = max(0, int(cx - r - 2)), min(W, int(cx + r + 3))
    y0, y1 = max(0, int(cy - r - 2)), min(H, int(cy + r + 3))
    if x0 >= x1 or y0 >= y1:
        return None
    X, Y = np.meshgrid(np.arange(x0, x1, dtype=np.float32) + 0.5,
                       np.arange(y0, y1, dtype=np.float32) + 0.5)
    return x0, x1, y0, y1, X, Y


def ell(cv, cx, cy, rx, ry, col, ang=0.0, shade=1.0, spec=0.35, gloss=30,
        clip=None, alpha=1.0, pattern=None, egg=0.0, spin=0.0):
    """Shaded ellipsoid ('clay 3D' look) composited onto cv."""
    if SILHOUETTE is not None:
        col, pattern, shade, spec = SILHOUETTE, None, min(shade, 0.3), 0.0
    if rx < 0.6 or ry < 0.6 or alpha <= 0.002:
        return
    b = _box(cx, cy, max(rx, ry) * (1 + abs(egg)) + 1)
    if b is None:
        return
    x0, x1, y0, y1, X, Y = b
    c, s = math.cos(ang), math.sin(ang)
    dx, dy = X - cx, Y - cy
    xl = dx * c + dy * s
    yl = -dx * s + dy * c
    v = yl / ry
    u = xl / (rx * (1 + egg * v))
    r = np.sqrt(u * u + v * v)
    a = np.clip((1 - r) * min(rx, ry) + 0.5, 0, 1) * alpha
    if clip is not None:
        a = a * clip(u, v)
    if not a.any():
        return
    nz = np.sqrt(np.clip(1 - r * r, 0, 1))
    nx = u * c - v * s
    ny = u * s + v * c
    if pattern is not None:
        cs, sn = math.cos(spin), math.sin(spin)
        px = u * cs + nz * sn
        pz = -u * sn + nz * cs
        base = pattern(px, v, pz)
    else:
        base = np.asarray(col, np.float32)[None, None, :]
    if shade > 0:
        ndl = nx * L[0] + ny * L[1] + nz * L[2]
        diff = np.clip((ndl + 0.35) / 1.35, 0, 1)
        lit = base * ((1 - shade) + shade * (0.42 + 0.70 * diff))[..., None]
        lit = lit + base * (0.10 * shade * np.clip(ny, 0, 1))[..., None]
        if spec > 0:
            nh = np.clip(nx * HV[0] + ny * HV[1] + nz * HV[2], 0, 1)
            lit = lit + (spec * nh ** gloss)[..., None]
        rim = (shade * 0.22 * (1 - nz) ** 3)[..., None]
        lit = lit + rim * np.array([1.0, 0.95, 1.0], np.float32)
    else:
        lit = np.broadcast_to(base, a.shape + (3,))
    reg = cv[y0:y1, x0:x1]
    a3 = a[..., None]
    reg *= (1 - a3)
    reg += lit * a3


def soft(cv, cx, cy, rx, ry, col, alpha, power=2.0):
    """Soft blob (shadows, glows)."""
    b = _box(cx, cy, max(rx, ry))
    if b is None or alpha <= 0.002:
        return
    x0, x1, y0, y1, X, Y = b
    r2 = ((X - cx) / rx) ** 2 + ((Y - cy) / ry) ** 2
    a = (np.clip(1 - r2, 0, 1) ** power * alpha)[..., None]
    reg = cv[y0:y1, x0:x1]
    reg *= (1 - a)
    reg += np.asarray(col, np.float32) * a


def seg(cv, x0, y0, x1, y1, w, col, alpha=1.0):
    r = w / 2 + 1
    b = _box((x0 + x1) / 2, (y0 + y1) / 2, max(abs(x1 - x0), abs(y1 - y0)) / 2 + r)
    if b is None:
        return
    bx0, bx1, by0, by1, X, Y = b
    dx, dy = x1 - x0, y1 - y0
    l2 = dx * dx + dy * dy + 1e-6
    t = np.clip(((X - x0) * dx + (Y - y0) * dy) / l2, 0, 1)
    d = np.hypot(X - (x0 + t * dx), Y - (y0 + t * dy))
    a = (np.clip(w / 2 - d + 0.5, 0, 1) * alpha)[..., None]
    reg = cv[by0:by1, bx0:bx1]
    reg *= (1 - a)
    reg += np.asarray(col, np.float32) * a


def sparkle(cv, cx, cy, size, col=(1, 1, 0.85), alpha=1.0, ang=0.0):
    soft(cv, cx, cy, size * 1.1, size * 1.1, col, 0.35 * alpha)
    b = _box(cx, cy, size)
    if b is None or alpha <= 0.01:
        return
    x0, x1, y0, y1, X, Y = b
    c, s = math.cos(ang), math.sin(ang)
    xl = ((X - cx) * c + (Y - cy) * s) / size
    yl = (-(X - cx) * s + (Y - cy) * c) / size
    f = np.sqrt(np.abs(xl)) + np.sqrt(np.abs(yl))
    a = (np.clip((1 - f) * size * 0.35 + 0.5, 0, 1) * alpha)[..., None]
    reg = cv[y0:y1, x0:x1]
    reg *= (1 - a)
    reg += np.asarray(col, np.float32) * a


def heart(cv, cx, cy, size, col, alpha=1.0, ang=0.0):
    b = _box(cx, cy, size * 1.4)
    if b is None or alpha <= 0.01:
        return
    x0, x1, y0, y1, X, Y = b
    c, s = math.cos(ang), math.sin(ang)
    x = ((X - cx) * c + (Y - cy) * s) / size
    y = -(-(X - cx) * s + (Y - cy) * c) / size + 0.15
    f = (x * x + y * y - 1) ** 3 - x * x * y ** 3
    a = (np.clip(-f * size * 0.6 + 0.5, 0, 1) * alpha)
    shadeg = (1.05 - 0.25 * np.clip(-(x + y) * 0.5 + 0.5, 0, 1))[..., None]
    hl = np.clip(1 - ((x + 0.45) ** 2 + (y - 0.35) ** 2) / 0.06, 0, 1)[..., None]
    out = np.asarray(col, np.float32) * shadeg + hl * 0.6
    a3 = a[..., None]
    reg = cv[y0:y1, x0:x1]
    reg *= (1 - a3)
    reg += out * a3


def bubble(cv, cx, cy, r, alpha=1.0):
    b = _box(cx, cy, r)
    if b is None:
        return
    x0, x1, y0, y1, X, Y = b
    d = np.hypot(X - cx, Y - cy) / r
    edge = np.clip((1 - d) * r + 0.5, 0, 1)
    a = (edge * (0.12 + 0.55 * np.clip(d, 0, 1) ** 6) * alpha)[..., None]
    hue = np.stack([0.75 + 0.25 * np.sin(6 * d + X / 40), 0.85 + 0.15 * np.cos(5 * d),
                    1.0 + 0 * d], -1).astype(np.float32)
    reg = cv[y0:y1, x0:x1]
    reg *= (1 - a)
    reg += hue * a
    ell(cv, cx - r * 0.35, cy - r * 0.4, r * 0.22, r * 0.14, (1, 1, 1), ang=-0.6,
        shade=0, alpha=0.8 * alpha)


# ----------------------------------------------------------------------------
# Easing helpers
# ----------------------------------------------------------------------------

def clamp01(x):
    return max(0.0, min(1.0, x))


def ease_out_back(x, k=1.70158):
    x = clamp01(x) - 1
    return 1 + (k + 1) * x ** 3 + k * x ** 2


def ease_io(x):
    x = clamp01(x)
    return x * x * (3 - 2 * x)


def damp(t, freq=3.0, decay=5.0):
    return math.exp(-decay * t) * math.sin(2 * math.pi * freq * t) if t > 0 else 0.0


def blink(t, seed):
    p = (t + seed * 1.37) % 2.9
    return 0.08 if p < 0.12 else 1.0


# ----------------------------------------------------------------------------
# Rig: a local coordinate frame for building characters out of ellipsoids
# ----------------------------------------------------------------------------

class Rig:
    def __init__(self, cv, x, y, s=1.0, sx=1.0, sy=1.0, rot=0.0):
        self.cv, self.x, self.y, self.s = cv, x, y, s
        self.sx, self.sy, self.rot = sx, sy, rot
        self.c, self.sn = math.cos(rot), math.sin(rot)

    def p(self, lx, ly):
        px, py = lx * self.s * self.sx, ly * self.s * self.sy
        return self.x + px * self.c - py * self.sn, self.y + px * self.sn + py * self.c

    def e(self, lx, ly, rx, ry, col, ang=0.0, **kw):
        x, y = self.p(lx, ly)
        ell(self.cv, x, y, rx * self.s * self.sx, ry * self.s * self.sy, col,
            ang=ang + self.rot, **kw)

    def soft(self, lx, ly, rx, ry, col, alpha):
        x, y = self.p(lx, ly)
        soft(self.cv, x, y, rx * self.s, ry * self.s, col, alpha)


INK = C('#2b1a2e')
WHITE = np.array([1, 1, 1], np.float32)
CHEEK = C('#ff8fb1')
MOUTH = C('#7a1f3d')
TONGUE = C('#ff7a95')


def eyes(rg, x, y, size, st, pupil=INK, sclera=True):
    op = st.get('blink', 1.0)
    lx, ly = st.get('look', (0, 0))
    for sgn in (-1, 1):
        ex = sgn * x
        if st.get('happy'):
            pts = [rg.p(ex + math.cos(a) * size * 0.75, y + size * 0.3 - math.sin(a) * size * 0.6)
                   for a in np.linspace(0.15, math.pi - 0.15, 9)]
            for (a0, b0), (a1, b1) in zip(pts, pts[1:]):
                seg(rg.cv, a0, b0, a1, b1, max(2.5, size * 0.3 * rg.s), INK)
            continue
        if st.get('dizzy'):
            rg.e(ex, y, size * 0.9, size * 1.05 * op, WHITE, shade=0.3, spec=0.2)
            rg.e(ex + sgn * size * 0.2, y + size * 0.1, size * 0.45, size * 0.5 * op, pupil, shade=0.2, spec=0)
            continue
        if sclera:
            rg.e(ex, y, size * 0.92, size * 1.12 * op, WHITE, shade=0.35, spec=0.3)
        rg.e(ex + lx * size * 0.25, y + size * 0.12 + ly * size * 0.25, size * 0.66,
             size * 0.82 * op, pupil, shade=0.25, spec=0.15)
        if op > 0.5:
            rg.e(ex + lx * size * 0.25 - size * 0.22, y - size * 0.18 + ly * size * 0.25,
                 size * 0.22, size * 0.24, WHITE, shade=0)
            rg.e(ex + lx * size * 0.25 + size * 0.2, y + size * 0.38 + ly * size * 0.25,
                 size * 0.1, size * 0.1, WHITE, shade=0)


def mouth(rg, x, y, w, st):
    m = st.get('mouth', 'smile')
    op = st.get('mopen', 0.6)
    if m == 'o':
        rg.e(x, y, w * 0.45, w * 0.55 * (0.5 + op), MOUTH, shade=0.3, spec=0)
        rg.e(x, y + w * 0.25 * (0.5 + op), w * 0.3, w * 0.18, TONGUE, shade=0.2, spec=0)
    else:
        h = w * (0.35 + 0.55 * op)
        half = lambda u, v: np.clip(v * 30 + 0.5, 0, 1)
        rg.e(x, y, w, h, MOUTH, shade=0.3, spec=0, clip=half)
        rg.e(x, y + h * 0.62, w * 0.55, h * 0.32, TONGUE, shade=0.2, spec=0)


def cheeks(rg, x, y, r):
    for sgn in (-1, 1):
        rg.e(sgn * x, y, r, r * 0.62, CHEEK, shade=0, alpha=0.55)


# ----------------------------------------------------------------------------
# Eggs
# ----------------------------------------------------------------------------

def zig(u):
    tri = 2 * np.abs((u * 3.5 + 0.25) % 1 - 0.5)
    return -0.09 + 0.12 * tri


def _dir_dots(n, seed):
    rng = np.random.default_rng(seed)
    out = []
    i = 0
    while len(out) < n:
        v = rng.normal(size=3)
        v /= np.linalg.norm(v)
        if all(np.dot(v, o) < 0.86 for o in out):
            out.append(v)
        i += 1
    return out


DOTS1 = _dir_dots(26, 3)
DOTS3 = _dir_dots(30, 9)
DOT_COLS = [C('#ffe066'), C('#ff8fab'), C('#7bdff2'), C('#ffffff'), C('#b8f2a0')]


def pat_dots(base, dots, cols, rad=0.93):
    def f(px, py, pz):
        out = np.empty(px.shape + (3,), np.float32)
        out[:] = base
        for k, d in enumerate(dots):
            dd = px * d[0] + py * d[1] + pz * d[2]
            m = np.clip((dd - rad) * 60, 0, 1)[..., None]
            if m.any():
                out = out * (1 - m) + cols[k % len(cols)] * m
        return out
    return f


def pat_zigband(base, band):
    def f(px, py, pz):
        ang = np.arctan2(px, pz)
        z = 0.12 * np.abs(((ang * 2.5) % 1) - 0.5) * 2
        m1 = np.clip((0.16 - np.abs(py - 0.1 - z + 0.06)) * 40, 0, 1)[..., None]
        m2 = np.clip((0.05 - np.abs(py + 0.38 - z * 0.6)) * 40, 0, 1)[..., None]
        out = np.broadcast_to(base, px.shape + (3,)).astype(np.float32)
        out = out * (1 - m1) + band * m1
        return out * (1 - m2) + WHITE * m2
    return f


def pat_waves(base, stripe):
    def f(px, py, pz):
        ang = np.arctan2(px, pz)
        w = py + 0.07 * np.sin(ang * 6)
        m = np.clip((0.07 - np.abs(((w * 3.2) % 1) - 0.5) * 0.4) * 50, 0, 1)[..., None]
        out = np.broadcast_to(base, px.shape + (3,)).astype(np.float32)
        return out * (1 - m) + stripe * m
    return f


RAINBOW = [C('#ff7b7b'), C('#ffb36b'), C('#ffe36b'), C('#8fe388'), C('#6bc5ff'), C('#b28dff')]


def pat_rainbow():
    def f(px, py, pz):
        ang = np.arctan2(px, pz)
        k = (py + 1 + 0.05 * np.sin(ang * 5)) * 3.0
        idx = np.clip(k.astype(int), 0, 5)
        frac = k - np.floor(k)
        cols = np.stack(RAINBOW)
        out = cols[idx]
        line = np.clip((0.06 - np.abs(frac - 0.5) + 0.44) * 0, 0, 1)
        sp = np.clip((np.sin(ang * 9) * np.sin(py * 14) - 0.93) * 15, 0, 1)[..., None]
        return out * (1 - sp) + WHITE * sp + line[..., None] * 0
    return f


EGGS = [
    dict(col=C('#6fe3c1'), pat=pat_dots(C('#6fe3c1'), DOTS1, [WHITE], 0.965)),
    dict(col=C('#ff8fbf'), pat=pat_zigband(C('#ff8fbf'), C('#ffe066'))),
    dict(col=C('#b49cff'), pat=pat_dots(C('#b49cff'), DOTS3, DOT_COLS, 0.95)),
    dict(col=C('#63b8ff'), pat=pat_waves(C('#63b8ff'), WHITE)),
    dict(col=C('#ffd36b'), pat=pat_rainbow()),
]

EGG_CX, EGG_BASE = 540.0, 1330.0
ERX, ERY = 225.0, 300.0
EGG_CY = EGG_BASE - ERY
INNER = C('#fff3d6')


def egg_full(cv, k, cx, cy, sx=1.0, sy=1.0, ang=0.0, spin=0.0, crack=0.0, clip=None, alpha=1.0):
    e = EGGS[k]
    rx, ry = ERX * sx, ERY * sy
    ell(cv, cx, cy, rx, ry, e['col'], ang=ang, spec=0.55, gloss=26, egg=0.12,
        pattern=e['pat'], spin=spin, clip=clip, alpha=alpha)
    if crack > 0:
        c, s = math.cos(ang), math.sin(ang)
        us = np.linspace(-crack, crack, max(3, int(crack * 22)))
        pts = []
        for u in us:
            vv = float(zig(np.array(u)))
            lx = u * rx * (1 + 0.12 * vv) * 0.985
            ly = vv * ry
            pts.append((cx + lx * c - ly * s, cy + lx * s + ly * c))
        dark = e['col'] * 0.35
        for (a0, b0), (a1, b1) in zip(pts, pts[1:]):
            seg(cv, a0, b0, a1, b1, 6, dark)


def clip_bottom(u, v):
    return np.clip((v - zig(u)) * 300 + 0.5, 0, 1)


def clip_top(u, v):
    return np.clip((zig(u) - v) * 300 + 0.5, 0, 1)


# ----------------------------------------------------------------------------
# Characters (original designs). Local frame: body centre at (0,0), feet ~ +135
# ----------------------------------------------------------------------------

def draw_chick(rg, st):
    Y, O = C('#ffd23f'), C('#ff9f1c')
    st['skin'] = Y
    fl = st.get('flap', 0.0)
    for sg in (-1, 1):
        rg.e(sg * 48, 132, 40, 17, O, spec=0.3)
    for sg in (-1, 1):
        rg.e(sg * 140, 15, 46, 72, C('#ffc21a'), ang=sg * (0.45 + fl))
    rg.e(0, 0, 152, 146, Y, spec=0.3)
    rg.e(0, 52, 98, 76, C('#ffe98a'), shade=0.5, spec=0)
    if not st.get('hat'):
        for k, a in enumerate((-0.45, 0, 0.45)):
            rg.e(math.sin(a) * 30, -150 - math.cos(a) * 18, 14, 34, C('#ffc21a'), ang=a)
    eyes(rg, 54, -32, 34, st)
    cheeks(rg, 98, 22, 24)
    op = st.get('mopen', 0.3)
    rg.e(0, 32 + 14 * op, 22, 12 + 6 * op, C('#e5731a'), spec=0.2)
    rg.e(0, 16, 32, 18, O, spec=0.5)
    if st.get('hat'):
        hx, hy = rg.p(0, -95)
        hs = rg.s * 0.7
        egg_full(rg.cv, 0, hx, hy, sx=hs * rg.sx, sy=hs * rg.sy, ang=rg.rot + st.get('hat_tilt', 0.12),
                 clip=clip_top)


def draw_bunny(rg, st):
    Wt, P = C('#fff1f6'), C('#ffb3cf')
    st['skin'] = Wt
    eb = st.get('ear', 0.0)
    for sg in (-1, 1):
        a = sg * (0.18 + eb * 0.6) + eb * 0.2
        px, py = sg * 48, -150
        cx, cy = px + math.sin(a) * 85, py - math.cos(a) * 85
        rg.e(cx, cy, 34, 98, Wt, ang=a)
        rg.e(cx + math.sin(a) * 6, cy - math.cos(a) * 6 + 4, 17, 70, P, ang=a, shade=0.5, spec=0.1)
    for sg in (-1, 1):
        rg.e(sg * 58, 130, 48, 22, Wt)
    rg.e(0, 45, 122, 102, Wt, spec=0.25)
    rg.e(0, -68, 128, 112, Wt, spec=0.3)
    for sg in (-1, 1):
        rg.e(sg * 52, 52, 30, 36, Wt)
    eyes(rg, 48, -82, 33, st)
    cheeks(rg, 88, -40, 24)
    tw = st.get('twitch', 0.0)
    st2 = dict(st, mopen=0.35)
    mouth(rg, 0, -18, 22, st2)
    for sg in (-1, 1):
        rg.e(sg * 7, -10, 7, 10, WHITE, shade=0.2, spec=0)
    rg.e(0, -44 + tw * 3, 15 * (1 + tw * 0.15), 10, C('#ff6f9f'), spec=0.6)


def draw_panda(rg, st):
    Wt, B = C('#ffffff'), C('#2e2a36')
    st['skin'] = Wt
    for sg in (-1, 1):
        rg.e(sg * 98, -158, 44, 42, B)
    for sg in (-1, 1):
        rg.e(sg * 56, 130, 46, 24, B)
    rg.e(0, 45, 124, 104, Wt, spec=0.25)
    for sg in (-1, 1):
        rg.e(sg * 108, 40 + st.get('wave', 0) * sg * -20, 40, 56, B, ang=sg * -0.3)
    rg.e(0, -60, 138, 120, Wt, spec=0.3)
    for sg in (-1, 1):
        rg.e(sg * 52, -66, 38, 48, B, ang=sg * 0.55, shade=0.6)
    st2 = dict(st, skin=B)
    eyes(rg, 52, -68, 22, st2)
    cheeks(rg, 95, -22, 24)
    rg.e(0, -22, 19, 13, B, spec=0.6)
    mouth(rg, 0, -6, 24, st)


def draw_elephant(rg, st):
    G, P = C('#a9c4ff'), C('#ffb8d4')
    st['skin'] = G
    fl = st.get('flap', 0.0)
    for sg in (-1, 1):
        rg.e(sg * 128, -62, 86 * (1 + 0.12 * fl), 96, G, ang=sg * 0.15)
        rg.e(sg * 132, -58, 56 * (1 + 0.12 * fl), 66, P, shade=0.5, spec=0.1, ang=sg * 0.15)
    for sg in (-1, 1):
        rg.e(sg * 58, 132, 46, 24, G)
    rg.e(0, 50, 120, 100, G, spec=0.25)
    rg.e(0, -62, 124, 112, G, spec=0.3)
    eyes(rg, 50, -92, 30, st)
    cheeks(rg, 86, -40, 24)
    k = st.get('trunk', 0.0)
    down = [(0, -30), (6, 2), (18, 32), (38, 54), (62, 60), (82, 48), (92, 26)]
    up = [(0, -30), (8, 0), (30, 20), (58, 14), (80, -8), (94, -36), (100, -66)]
    rad = [30, 28, 26, 24, 22, 20, 19]
    for (a, b), (c2, d), r in zip(down, up, rad):
        rg.e(a + (c2 - a) * k, b + (d - b) * k, r, r, G, spec=0.25)
    tx, ty = down[-1][0] + (up[-1][0] - down[-1][0]) * k, down[-1][1] + (up[-1][1] - down[-1][1]) * k
    rg.e(tx, ty - 4, 11, 8, C('#6f86c9'), shade=0.3, spec=0)
    st2 = dict(st, mopen=0.2)
    mouth(rg, -42, -6, 16, st2)
    st['tip'] = rg.p(tx, ty - 10)


def draw_dino(rg, st):
    G, Bl, O = C('#7bdc6a'), C('#d9f7a8'), C('#ff9b5e')
    st['skin'] = G
    rg.e(118, 92, 72, 34, G, ang=-0.55)
    for k, a in enumerate((-0.6, -0.2, 0.2, 0.6)):
        rg.e(math.sin(a) * 118, -78 - math.cos(a) * 112, 20, 32, O, ang=a)
    for sg in (-1, 1):
        rg.e(sg * 56, 132, 48, 24, G)
    rg.e(0, 48, 124, 104, G, spec=0.25)
    rg.e(0, 62, 80, 70, Bl, shade=0.5, spec=0)
    for sg in (-1, 1):
        rg.e(sg * 98, 30 - st.get('arms', 0) * 25, 22, 30, G, ang=sg * -0.4)
    rg.e(0, -76, 132, 112, G, spec=0.3)
    eyes(rg, 52, -100, 31, st)
    cheeks(rg, 92, -52, 24)
    for sg in (-1, 1):
        rg.e(sg * 16, -50, 6, 5, C('#3f7d36'), shade=0)
    ro = st.get('roar', 0.0)
    if ro > 0.05:
        rg.e(0, -10, 46 * ro, 34 * ro, MOUTH, shade=0.3, spec=0)
        rg.e(0, -10 + 18 * ro, 28 * ro, 12 * ro, TONGUE, shade=0.2, spec=0)
        for sg in (-1, 1):
            rg.e(sg * 22 * ro, -10 - 28 * ro, 6 * ro, 8 * ro, WHITE, shade=0.2, spec=0)
    else:
        mouth(rg, 0, -16, 26, st)


ANIMALS = [draw_chick, draw_bunny, draw_panda, draw_elephant, draw_dino]
SLOTS = [150, 345, 540, 735, 930]
SHELF_Y, SHELF_S = 1690.0, 0.40

# ----------------------------------------------------------------------------
# Timeline
# ----------------------------------------------------------------------------
CYCLE = 4.6
POP = 1.6
HOP0, HOP1 = 3.4, 4.0
FIN0 = 22.4
DROP0 = 27.4


def gag_state(k, lt):
    """Per-animal expression/pose while in the egg; lt = time since pop."""
    st = dict(blink=blink(lt, k), mouth='smile', mopen=0.6)
    if lt < 0.35:
        st.update(mouth='o', mopen=0.5 + lt, blink=1.0)
    if k == 0:  # chick: shell lands on its head
        st['flap'] = 0.25 * math.sin(lt * 25) if 0.75 < lt < 1.6 else 0.0
        if lt > 0.7:
            st['hat'] = True
            st['hat_tilt'] = 0.12 + 0.2 * damp(lt - 0.7, 3, 4)
            st['look'] = (0, -1) if lt < 1.1 else (0, 0)
        if 0.7 < lt < 1.0:
            st.update(mouth='o', blink=1.0)
        elif lt > 1.0:
            st.update(happy=lt > 1.1 and lt < 1.7)
    elif k == 1:  # bunny: springy ears + nose twitch + hop
        st['ear'] = damp(lt - 0.25, 2.5, 2.5) * 0.9 if lt > 0.25 else 0
        st['twitch'] = math.sin(lt * 50) if 1.4 < lt < 1.75 else 0
        if 0.9 < lt < 1.4:
            st['happy'] = True
    elif k == 2:  # panda: spin then dizzy
        if 1.15 < lt < 1.8:
            st['dizzy'] = True
            st['mouth'] = 'o'
            st['mopen'] = 0.2
        st['wave'] = math.sin(lt * 14) if lt > 1.8 else 0
    elif k == 3:  # elephant: bubbles
        st['trunk'] = ease_io((lt - 0.4) / 0.3) * (1 - ease_io((lt - 1.65) / 0.2))
        st['flap'] = math.sin(lt * 16) if lt > 0.4 else 0
        if 0.9 < lt < 1.6:
            st['happy'] = True
    elif k == 4:  # dino: tiny "roar"
        r = ease_io((lt - 0.45) / 0.3) * (1 - ease_io((lt - 1.05) / 0.15))
        st['roar'] = r
        st['arms'] = r
        if 1.2 < lt < 1.8:
            st['happy'] = True
    return st


def gag_pose(k, lt):
    """Returns (dx, dy, rot, sx, sy) offsets for the gag."""
    dx = dy = rot = 0.0
    sx = sy = 1.0
    if k == 1 and 1.0 < lt < 1.5:
        p = (lt - 1.0) / 0.5
        dy = -170 * 4 * p * (1 - p)
        sy, sx = 1.08, 0.94
    if k == 2 and 0.45 < lt < 1.15:
        rot = 2 * math.pi * ease_io((lt - 0.45) / 0.7)
    if k == 2 and lt > 1.15:
        rot = 0.12 * damp(lt - 1.15, 2, 3) * 3
    if k == 4:
        rot = -0.12 * ease_io((lt - 0.3) / 0.2) * (1 - ease_io((lt - 1.05) / 0.2))
    return dx, dy, rot, sx, sy


def squash_in(t):
    """Squash/stretch after landing."""
    if t <= 0:
        return 1.0, 1.0
    d = damp(t, 3.2, 6.0)
    return 1 + 0.16 * d, 1 - 0.16 * d


def draw_shelf_friend(cv, k, t, x, y, s, extra=None):
    st = dict(blink=blink(t, k + 3), mouth='smile', mopen=0.5)
    if k == 0:
        st['hat'] = True
    if extra:
        st.update(extra)
    bob = math.sin((t / DUR) * 2 * math.pi * 14 + k * 1.3)
    sx, sy = 1 + 0.03 * bob, 1 - 0.03 * bob
    soft(cv, x, SHELF_Y + 4, 70, 14, (0.2, 0.35, 0.2), 0.35)
    rg = Rig(cv, x, y + 135 * s * (1 - sy), s, sx, sy)
    ANIMALS[k](rg, st)


# Particle events: (time, kind, x, y, seed)
EVENTS = []
for _i in range(5):
    _t0 = _i * CYCLE
    EVENTS.append((_t0 + POP, 'burst', EGG_CX, EGG_CY - 20, _i))
    EVENTS.append((_t0 + 3.55, 'poof', EGG_CX, EGG_CY + 120, _i + 10))
EVENTS.append((FIN0 + 2.0, 'rain', 540, -40, 77))

CONF_COLS = [C(h) for h in ('#ff6b9d', '#ffd23f', '#6fe3c1', '#63b8ff', '#b49cff', '#ff9f1c')]


def draw_particles(cv, t):
    for (te, kind, x, y, seed) in EVENTS:
        dt = t - te
        if kind == 'burst' and 0 <= dt < 1.6:
            rng = np.random.default_rng(seed)
            for j in range(34):
                ang = rng.uniform(-math.pi * 0.95, -math.pi * 0.05)
                sp = rng.uniform(500, 1200)
                vx, vy = math.cos(ang) * sp, math.sin(ang) * sp
                px = x + vx * dt * 0.8
                py = y + vy * dt + 0.5 * 1600 * dt * dt
                spin = rng.uniform(5, 12) * dt + j
                a = clamp01((1.6 - dt) / 0.5)
                ell(cv, px, py, 13, 7 * abs(math.cos(spin)) + 1.5, CONF_COLS[j % 6],
                    ang=spin * 0.7, spec=0.4, alpha=a)
            for j in range(12):
                ang = rng.uniform(0, 2 * math.pi)
                rr = 120 + 260 * (1 - math.exp(-4 * dt)) + rng.uniform(0, 80)
                a = clamp01(1 - dt / 1.1) * (0.6 + 0.4 * math.sin(dt * 20 + j))
                sparkle(cv, x + math.cos(ang) * rr, y + math.sin(ang) * rr * 0.9,
                        rng.uniform(18, 34), alpha=a, ang=dt * 2)
        elif kind == 'poof' and 0 <= dt < 0.8:
            rng = np.random.default_rng(seed)
            for j in range(10):
                ang = rng.uniform(0, 2 * math.pi)
                rr = 60 + 200 * (1 - math.exp(-5 * dt))
                sparkle(cv, x + math.cos(ang) * rr, y + math.sin(ang) * rr * 0.6,
                        rng.uniform(14, 26), alpha=clamp01(1 - dt / 0.8))
            for j in range(6):
                ang = j * math.pi / 3
                rr = 80 * (1 - math.exp(-6 * dt)) + 30
                soft(cv, x + math.cos(ang) * rr, y + math.sin(ang) * rr * 0.5,
                     70, 55, (1, 1, 1), 0.55 * clamp01(1 - dt / 0.7))
        elif kind == 'rain' and 0 <= dt < 3.2:
            rng = np.random.default_rng(seed)
            for j in range(60):
                x0 = rng.uniform(0, W)
                d0 = rng.uniform(0, 0.8)
                tt = dt - d0
                if tt < 0:
                    continue
                py = y + 600 * tt + rng.uniform(-60, 0)
                px = x0 + 40 * math.sin(tt * 4 + j)
                spin = tt * rng.uniform(5, 10) + j
                ell(cv, px, py, 12, 6 * abs(math.cos(spin)) + 1.5, CONF_COLS[j % 6],
                    ang=spin * 0.6, spec=0.4, alpha=clamp01((3.2 - dt) / 0.5))


# ----------------------------------------------------------------------------
# Background (static, rendered once per worker)
# ----------------------------------------------------------------------------
_BG = None


def background():
    global _BG
    if _BG is not None:
        return _BG
    cv = np.zeros((H, W, 3), np.float32)
    y = np.linspace(0, 1, H, dtype=np.float32)[:, None]
    top, mid, low = C('#8fd3ff'), C('#cfe9ff'), C('#ffe1f0')
    g = np.where(y < 0.5, top + (mid - top) * (y / 0.5)[..., None][:, 0],
                 mid + (low - mid) * ((y - 0.5) / 0.5)[..., None][:, 0])
    cv[:] = g[:, None, :] if g.ndim == 2 else g
    soft(cv, 880, 230, 420, 420, (1, 0.98, 0.85), 0.55, power=1.5)
    ell(cv, 880, 230, 95, 95, C('#fff4b0'), shade=0.15, spec=0)
    for (cx, cy, s) in ((220, 330, 1.0), (820, 560, 0.75), (380, 760, 0.55)):
        for (dx, dy, r) in ((-90, 20, 70), (-30, -20, 95), (60, -5, 85), (120, 25, 60), (10, 35, 80)):
            ell(cv, cx + dx * s, cy + dy * s, r * s, r * s * 0.85, (1, 1, 1), shade=0.35, spec=0)
    ell(cv, 120, 1560, 520, 260, C('#a6e3a1'), shade=0.45, spec=0)
    ell(cv, 980, 1530, 560, 240, C('#9ddc96'), shade=0.45, spec=0)
    ell(cv, 540, 1980, 900, 360, C('#7fd17a'), shade=0.5, spec=0.05)
    rng = np.random.default_rng(5)
    for _ in range(70):
        fx, fy = rng.uniform(0, W), rng.uniform(1660, 1920)
        col = [C('#ffffff'), C('#ffd23f'), C('#ff8fbf'), C('#b49cff')][rng.integers(4)]
        r = rng.uniform(6, 11)
        for k in range(5):
            a = k * 2 * math.pi / 5
            ell(cv, fx + math.cos(a) * r, fy + math.sin(a) * r * 0.7, r * 0.7, r * 0.55, col, shade=0.3, spec=0)
        ell(cv, fx, fy, r * 0.5, r * 0.4, C('#ffb703'), shade=0.3, spec=0)
    # cushion / pedestal
    soft(cv, EGG_CX, EGG_BASE + 70, 330, 60, (0.25, 0.2, 0.35), 0.35)
    ell(cv, EGG_CX, EGG_BASE + 38, 285, 80, C('#ff9ec8'), spec=0.35, gloss=20)
    ell(cv, EGG_CX, EGG_BASE + 22, 240, 52, C('#ffb6d6'), shade=0.6, spec=0.2)
    for k in range(10):
        a = k * 2 * math.pi / 10
        ell(cv, EGG_CX + math.cos(a) * 262, EGG_BASE + 40 + math.sin(a) * 70, 14, 14, C('#ffe066'), spec=0.6)
    yy = (np.arange(H, dtype=np.float32)[:, None] - H / 2) / H
    xx = (np.arange(W, dtype=np.float32)[None, :] - W / 2) / W
    vig = 1 - 0.18 * (xx ** 2 + yy ** 2) * 2
    cv *= vig[..., None]
    _BG = cv
    return cv


def ambient(cv, t):
    rng = np.random.default_rng(42)
    for j in range(14):
        x0, y0 = rng.uniform(0, W), rng.uniform(0, H)
        k = int(rng.integers(1, 3))
        y = (y0 - (t / DUR) * H * k) % (H + 200) - 100
        x = x0 + 30 * math.sin(2 * math.pi * (t / DUR) * 6 + j)
        a = 0.35 + 0.3 * math.sin(2 * math.pi * (t / DUR) * 10 + j * 1.7)
        sparkle(cv, x, y, rng.uniform(8, 16), col=(1, 1, 1), alpha=a)


# ----------------------------------------------------------------------------
# Frame composition
# ----------------------------------------------------------------------------

def egg_drop(cv, k, dt):
    """dt in [-0.6, 0): egg falls onto the cushion. dt >= 0 handled by wiggle."""
    p = (dt + 0.6) / 0.42
    if p < 1:
        y = -350 + (EGG_CY + 350) * p * p
        sh = p
        soft(cv, EGG_CX, EGG_BASE + 8, 230 * (0.4 + 0.6 * sh), 30, (0.3, 0.15, 0.3), 0.35 * sh)
        egg_full(cv, k, EGG_CX, y, sx=0.96, sy=1.06, spin=p * 2)
    else:
        tt = (dt + 0.6) - 0.42
        sx, sy = squash_in(tt)
        soft(cv, EGG_CX, EGG_BASE + 8, 230, 30, (0.3, 0.15, 0.3), 0.35)
        egg_full(cv, k, EGG_CX, EGG_BASE - ERY * sy, sx=sx, sy=sy)


def wiggle_angle(lt):
    bursts = ((0.0, 0.45, 0.08), (0.55, 1.0, 0.12), (1.1, 1.55, 0.17))
    for (a, b, amp) in bursts:
        if a <= lt < b:
            p = (lt - a) / (b - a)
            return amp * math.sin(p * 2 * math.pi * 2) * math.sin(p * math.pi), p
    return 0.0, 0.0


def draw_egg_stage(cv, k, lt, t):
    """lt: local cycle time (0 .. CYCLE)."""
    if lt < POP:
        a, _ = wiggle_angle(lt)
        crack = 0.0
        if lt > 0.45:
            crack = 0.28
        if lt > 1.0:
            crack = 0.62
        if lt > 1.5:
            crack = 1.0
        hop = 0.0
        if 1.1 < lt < 1.55:
            p = (lt - 1.1) / 0.45
            hop = -40 * abs(math.sin(p * 2 * math.pi))
        pre = (lt - 1.45) / 0.15 if lt > 1.45 else 0
        sx, sy = 1 + 0.05 * pre, 1 - 0.05 * pre
        soft(cv, EGG_CX, EGG_BASE + 8, 230, 30, (0.3, 0.15, 0.3), 0.35)
        cx = EGG_CX + ERY * sy * math.sin(a)
        cy = EGG_BASE + hop - ERY * sy * math.cos(a)
        egg_full(cv, k, cx, cy, sx=sx, sy=sy, ang=a, spin=a * 2.5, crack=crack)
        # hook sparkles orbiting the egg
        for j in range(5):
            ang = t * 2.2 + j * 2 * math.pi / 5
            sparkle(cv, EGG_CX + math.cos(ang) * 300, EGG_CY + math.sin(ang) * 360,
                    20 + 6 * math.sin(t * 6 + j), alpha=0.75 + 0.25 * math.sin(t * 5 + j), ang=t)
        return
    pt = lt - POP
    shell_gone = lt > HOP0 + 0.15
    shell_scale = 1.0
    if lt > 3.5:
        shell_scale = max(0.0, 1 - (lt - 3.5) / 0.25)
    rock = 0.06 * damp(pt, 2.5, 3.0)
    soft(cv, EGG_CX, EGG_BASE + 8, 230 * max(shell_scale, 0.3), 30, (0.3, 0.15, 0.3), 0.35)
    bcx = EGG_CX + ERY * math.sin(rock)
    bcy = EGG_BASE - ERY * math.cos(rock)
    if shell_scale > 0:
        ell(cv, bcx, bcy - 14 * shell_scale, ERX * 0.96 * shell_scale, ERX * 0.22 * shell_scale,
            INNER * 0.82, ang=rock, shade=0.4, spec=0)
    # animal inside the egg
    if lt < HOP0:
        rise = ease_out_back(pt / 0.45, 2.2)
        ay = EGG_CY + 280 - 330 * rise
        st = gag_state(k, pt)
        dx, dy, rot, gsx, gsy = gag_pose(k, pt)
        ssx, ssy = (1 - 0.12 * damp(pt, 2.5, 4), 1 + 0.12 * damp(pt, 2.5, 4))
        rg = Rig(cv, EGG_CX + dx, ay + dy, 1.0, ssx * gsx, ssy * gsy, rot)
        ANIMALS[k](rg, st)
        if k == 2 and 1.15 < pt < 1.8:
            for j in range(3):
                ang = pt * 9 + j * 2 * math.pi / 3
                sparkle(cv, EGG_CX + math.cos(ang) * 120, ay - 200 + math.sin(ang) * 30,
                        22, col=(1, 0.9, 0.3), alpha=1.0)
        if k == 3:
            draw_bubbles(cv, pt, st.get('tip', (EGG_CX + 100, ay - 70)))
        if k == 4 and 1.0 < pt < 2.2:
            q = pt - 1.0
            heart(cv, EGG_CX + 40 * math.sin(q * 5), ay - 60 - 260 * q, 26 + 10 * min(q * 3, 1),
                  C('#ff5c8a'), alpha=clamp01((2.2 - pt) / 0.4))
    if shell_scale > 0:
        egg_full(cv, k, bcx, EGG_BASE - ERY * shell_scale * math.cos(rock), sx=shell_scale,
                 sy=shell_scale, ang=rock, clip=clip_bottom)
    # flying top shell
    if k == 0:
        if pt < 0.7:
            p = pt / 0.7
            hx, hy = EGG_CX, EGG_CY - 330 + 95 - 0  # chick head target (in-egg pose)
            sx0, sy0 = EGG_CX, EGG_CY
            x = sx0 + (hx - sx0) * p
            y = sy0 + (hy - sy0) * p - 650 * math.sin(math.pi * p)
            sc = 1 - 0.3 * p
            egg_full(cv, k, x, y, sx=sc, sy=sc, ang=p * 2 * math.pi + 0.12 * p, clip=clip_top)
    else:
        if pt < 1.2:
            dirn = -1 if k % 2 else 1
            x = EGG_CX + dirn * 520 * pt
            y = EGG_CY - 1500 * pt + 0.5 * 2600 * pt * pt
            egg_full(cv, k, x, y, ang=dirn * 5 * pt, clip=clip_top)


def draw_bubbles(cv, pt, tip):
    for j in range(9):
        t0 = 0.55 + j * 0.11
        dt = pt - t0
        if dt < 0 or dt > 1.6:
            continue
        rng = np.random.default_rng(100 + j)
        x = tip[0] + rng.uniform(20, 90) * dt + 18 * math.sin(dt * 6 + j)
        y = tip[1] - 260 * dt - 20
        r = rng.uniform(22, 40) * min(1, dt * 6)
        if dt > 1.45:
            sparkle(cv, x, y, r * 0.8, col=(0.85, 0.95, 1), alpha=(1.6 - dt) / 0.15)
        else:
            bubble(cv, x, y, r)


def draw_hopper(cv, k, lt, t):
    """Animal hopping from the egg to its shelf slot (lt in HOP0..HOP1)."""
    p = (lt - HOP0) / (HOP1 - HOP0)
    e = ease_io(p)
    x0, y0 = EGG_CX, EGG_CY - 50
    x1, y1 = SLOTS[k], SHELF_Y - 135 * SHELF_S
    x = x0 + (x1 - x0) * e
    y = y0 + (y1 - y0) * e - 380 * math.sin(math.pi * p)
    s = 1 + (SHELF_S - 1) * e
    st = dict(blink=1.0, happy=True, mouth='smile', mopen=0.7)
    if k == 0:
        st['hat'] = True
    sx = 1 - 0.08 * math.sin(math.pi * p)
    rg = Rig(cv, x, y, s, sx, 2 - sx, 0.25 * math.sin(2 * math.pi * p) * (1 if x1 > x0 else -1))
    ANIMALS[k](rg, st)


def draw_finale(cv, t):
    fl = t - FIN0
    for k in range(5):
        x = SLOTS[k]
        y = SHELF_Y - 135 * SHELF_S
        extra = {}
        jt = fl - (0.3 + 0.25 * k)
        jy = 0.0
        if 0 < jt < 0.45:
            jy = -150 * 4 * (jt / 0.45) * (1 - jt / 0.45)
            extra['happy'] = True
        jt2 = fl - 2.0
        if 0 < jt2 < 0.5:
            jy = -220 * 4 * (jt2 / 0.5) * (1 - jt2 / 0.5)
            extra.update(happy=True)
        if 0.45 < fl - (0.3 + 0.25 * k) < 0.7:
            extra.update(mouth='o', mopen=0.4)
        # hop off to the right, rightmost first
        ho = fl - (3.0 + 0.18 * (4 - k))
        if ho > 0:
            p = min(1.0, ho / 0.7)
            x = x + (1300 - x) * ease_io(p)
            jy = -260 * math.sin(math.pi * p)
            extra['happy'] = True
            if p >= 1:
                continue
        s = SHELF_S
        draw_shelf_friend(cv, k, t, x, y + jy, s, extra)
        if 0.2 < jt < 1.4:
            heart(cv, x + 20 * math.sin(jt * 6), y - 120 - 180 * jt, 22, C('#ff6b9d'),
                  alpha=clamp01((1.4 - jt) / 0.4))
    if 4.3 < fl < 5.0:
        q = fl - 4.3
        for j in range(8):
            ang = q * 5 + j * 2 * math.pi / 8
            rr = 280 * (1 - q / 0.9)
            sparkle(cv, EGG_CX + math.cos(ang) * rr, EGG_BASE - 150 + math.sin(ang) * rr * 0.6,
                    18, alpha=clamp01(q * 4))


def render_frame(i):
    t = i / FPS
    cv = background().copy()
    ambient(cv, t)
    if t < FIN0:
        ci = min(4, int(t // CYCLE))
        lt = t - ci * CYCLE
        for j in range(5):
            if j < ci or (j == ci and lt >= HOP1):
                draw_shelf_friend(cv, j, t, SLOTS[j], SHELF_Y - 135 * SHELF_S, SHELF_S)
        if lt < HOP1 + 0.2:
            draw_egg_stage(cv, ci, lt, t)
        if HOP0 <= lt < HOP1:
            draw_hopper(cv, ci, lt, t)
        if lt >= HOP1 and ci < 4:
            egg_drop(cv, ci + 1, lt - CYCLE)
    else:
        draw_finale(cv, t)
        if t >= DROP0:
            egg_drop(cv, 0, t - DUR)
    draw_particles(cv, t)
    return (np.clip(cv, 0, 1) * 255 + 0.5).astype(np.uint8)


# ----------------------------------------------------------------------------
# Sound design (synthesized SFX only)
# ----------------------------------------------------------------------------
SR = 44100


def _t(d):
    return np.arange(int(d * SR)) / SR


def lp(x, a):
    y = np.empty_like(x)
    acc = 0.0
    for i, v in enumerate(x):
        acc += a * (v - acc)
        y[i] = acc
    return y


def sfx_boing(f0=170, d=0.5):
    t = _t(d)
    f = f0 * (1 + 0.55 * np.exp(-5 * t) * np.sin(2 * np.pi * 11 * t)) * (1 + 0.4 * np.exp(-8 * t))
    ph = 2 * np.pi * np.cumsum(f) / SR
    return (np.sin(ph) + 0.3 * np.sin(2 * ph)) * np.exp(-5 * t) * np.minimum(1, t * 400) * 0.8


def sfx_pop(f0=900):
    t = _t(0.14)
    f = 180 + f0 * np.exp(-40 * t)
    ph = 2 * np.pi * np.cumsum(f) / SR
    rng = np.random.default_rng(1)
    n = lp(rng.normal(size=t.size), 0.25) * np.exp(-70 * t)
    return (np.sin(ph) * np.exp(-28 * t) + 0.6 * n) * np.minimum(1, t * 2000)


def sfx_tick(f=2300):
    t = _t(0.04)
    return (np.sin(2 * np.pi * f * t) + 0.5 * np.sin(2 * np.pi * f * 0.5 * t)) * np.exp(-110 * t) * 0.5


def sfx_crack(seed=0):
    rng = np.random.default_rng(seed)
    out = np.zeros(int(0.22 * SR))
    for _ in range(7):
        s = int(rng.uniform(0, 0.17) * SR)
        n = rng.normal(size=int(0.006 * SR))
        n = np.diff(n, prepend=0) * np.exp(-np.arange(n.size) / (0.0015 * SR))
        out[s:s + n.size] += n * rng.uniform(0.3, 0.7)
    return out


def sfx_sparkle(seed=0, n=7, d=0.7):
    rng = np.random.default_rng(seed)
    out = np.zeros(int((d + 0.5) * SR))
    for _ in range(n):
        s = int(rng.uniform(0, d) * SR)
        f = rng.choice([2093, 2349, 2637, 3136, 3520, 4186])
        t = _t(0.45)
        tone = (np.sin(2 * np.pi * f * t) + 0.25 * np.sin(2 * np.pi * f * 2.01 * t)) * np.exp(-9 * t)
        out[s:s + t.size] += tone * 0.22
    return out


def sfx_giggle(base=640, n=5, seed=0):
    rng = np.random.default_rng(seed)
    out = []
    for k in range(n):
        d = 0.075
        t = _t(d)
        f0 = base * (1 + 0.06 * k) * (1 + 0.04 * np.sin(2 * np.pi * 30 * t)) * rng.uniform(0.97, 1.03)
        ph = 2 * np.pi * np.cumsum(f0) / SR
        sig = np.zeros_like(t)
        for h in range(1, 9):
            fh = h * f0.mean()
            amp = math.exp(-((fh - 420) / 260) ** 2) + 0.7 * math.exp(-((fh - 2500) / 500) ** 2) + 0.08
            sig += amp * np.sin(h * ph) / h ** 0.3
        sig *= np.sin(np.pi * t / d) ** 1.5
        sig += rng.normal(size=t.size) * 0.03 * np.sin(np.pi * t / d)
        out.append(sig)
        out.append(np.zeros(int(0.04 * SR)))
    s = np.concatenate(out)
    return s / (np.abs(s).max() + 1e-9) * 0.45


def sfx_whoosh(d=0.45, up=True, seed=3):
    rng = np.random.default_rng(seed)
    t = _t(d)
    n = rng.normal(size=t.size)
    a = 0.04 + 0.25 * (t / d if up else 1 - t / d)
    y = np.empty_like(n)
    acc = 0.0
    acc2 = 0.0
    for i in range(n.size):
        acc += a[i] * (n[i] - acc)
        acc2 += a[i] * (acc - acc2)
        y[i] = acc - acc2 * 0.5
    return y * np.sin(np.pi * t / d) ** 2 * 1.4


def sfx_slide(f0=480, f1=1250, d=0.32):
    t = _t(d)
    f = f0 * (f1 / f0) ** (t / d)
    ph = 2 * np.pi * np.cumsum(f) / SR
    tri = 2 / np.pi * np.arcsin(np.sin(ph))
    return tri * np.sin(np.pi * t / d) * 0.35


def sfx_squeak():
    t = _t(0.28)
    f = 950 + 500 * (t / 0.28) + 60 * np.sin(2 * np.pi * 24 * t)
    ph = 2 * np.pi * np.cumsum(f) / SR
    return (np.sin(ph) + 0.2 * np.sin(2 * ph)) * np.sin(np.pi * t / 0.28) * 0.45


def sfx_blip(f0=320, f1=1100):
    t = _t(0.07)
    f = f0 * (f1 / f0) ** (t / 0.07)
    ph = 2 * np.pi * np.cumsum(f) / SR
    return np.sin(ph) * np.exp(-25 * t) * 0.5


def sfx_thud():
    t = _t(0.2)
    return (np.sin(2 * np.pi * 95 * t) + 0.5 * np.sin(2 * np.pi * 150 * t)) * np.exp(-22 * t) * 0.7


def sfx_whirr(d=0.7):
    t = _t(d)
    f = 400 + 900 * np.sin(np.pi * t / d) + 120 * np.sin(2 * np.pi * 18 * t)
    ph = 2 * np.pi * np.cumsum(f) / SR
    return np.sin(ph) * np.sin(np.pi * t / d) * 0.25


def sfx_chime_rise():
    out = np.zeros(int(0.9 * SR))
    for k, f in enumerate((1568, 2093, 2637, 3136)):
        t = _t(0.5)
        s = int(k * 0.08 * SR)
        out[s:s + t.size] += np.sin(2 * np.pi * f * t) * np.exp(-8 * t) * 0.18
    return out


def build_audio(path):
    n = int(DUR * SR)
    mix = np.zeros((n, 2))

    def add(tt, sig, gain=1.0, pan=0.0):
        tt = tt % DUR
        s = int(tt * SR)
        e = min(n, s + sig.size)
        l, r = math.cos((pan + 1) * math.pi / 4), math.sin((pan + 1) * math.pi / 4)
        mix[s:e, 0] += sig[:e - s] * gain * l * 1.41
        mix[s:e, 1] += sig[:e - s] * gain * r * 1.41
        rest = sig.size - (e - s)
        if rest > 0:  # wrap tails so the loop point is seamless
            mix[:rest, 0] += sig[e - s:] * gain * l * 1.41
            mix[:rest, 1] += sig[e - s:] * gain * r * 1.41

    boing = sfx_boing()
    for k in range(5):
        t0 = k * CYCLE
        # egg landing (egg 0 lands at the end of the loop)
        land = (t0 - 0.6 + 0.42) if k else (DROP0 + 0.42)
        add(land - 0.02, sfx_thud(), 0.7)
        add(land, sfx_boing(150 + 12 * k), 0.55)
        add(land - 0.45, sfx_whoosh(0.4, True, k), 0.25)
        # wiggles: clicks at each swing
        for (a, b) in ((0.0, 0.45), (0.55, 1.0), (1.1, 1.55)):
            for q in range(4):
                add(t0 + a + (b - a) * (q + 0.5) / 4, sfx_tick(2100 + 200 * q), 0.45, pan=(-0.4, 0.4)[q % 2])
        for ct in (0.47, 1.02, 1.52):
            add(t0 + ct, sfx_crack(k * 3 + int(ct * 10)), 0.6)
        add(t0 + 1.1, sfx_sparkle(k, 4, 0.4), 0.6)
        # pop!
        add(t0 + POP, sfx_pop(), 1.0)
        add(t0 + POP + 0.02, sfx_sparkle(k + 20, 9, 0.6), 0.9)
        add(t0 + POP + 0.05, sfx_boing(260, 0.4), 0.35)
        pt = t0 + POP
        if k == 0:
            add(pt + 0.05, sfx_slide(600, 1300, 0.3), 0.6)
            add(pt + 0.35, sfx_slide(1300, 500, 0.33), 0.6)
            add(pt + 0.7, sfx_pop(500), 0.8)
            add(pt + 0.72, sfx_boing(220, 0.45), 0.5)
            add(pt + 1.1, sfx_giggle(700, 5, 1), 0.75)
        elif k == 1:
            add(pt + 0.25, sfx_boing(200, 0.6), 0.8)
            add(pt + 1.0, sfx_slide(500, 1000, 0.25), 0.5)
            add(pt + 1.48, sfx_thud(), 0.5)
            for q in range(4):
                add(pt + 1.42 + q * 0.08, sfx_tick(3200), 0.35)
            add(pt + 0.9, sfx_giggle(760, 4, 2), 0.7)
        elif k == 2:
            add(pt + 0.45, sfx_whirr(0.7), 0.7)
            add(pt + 1.15, sfx_sparkle(55, 6, 0.6), 0.6)
            add(pt + 1.25, sfx_boing(120, 0.6), 0.45)
            add(pt + 1.85, sfx_giggle(600, 5, 3), 0.75)
        elif k == 3:
            for j in range(9):
                add(pt + 0.55 + j * 0.11, sfx_blip(300 + 40 * j, 900 + 60 * j), 0.5, pan=0.3)
                add(pt + 0.55 + j * 0.11 + 1.45, sfx_pop(1400), 0.25, pan=0.3)
            add(pt + 1.0, sfx_giggle(680, 5, 4), 0.65)
        elif k == 4:
            add(pt + 0.5, sfx_whoosh(0.3, True, 9), 0.2)
            add(pt + 0.75, sfx_squeak(), 0.8)
            add(pt + 1.0, sfx_chime_rise(), 0.7)
            add(pt + 1.25, sfx_giggle(560, 6, 5), 0.75)
        # hop to the shelf + shell poof
        add(t0 + HOP0, sfx_slide(450, 1200, 0.32), 0.45)
        add(t0 + 3.5, sfx_pop(700), 0.45)
        add(t0 + 3.5, sfx_sparkle(k + 40, 5, 0.3), 0.5)
        add(t0 + HOP1 - 0.04, sfx_boing(300, 0.3), 0.35)
    # finale
    for k in range(5):
        add(FIN0 + 0.3 + 0.25 * k, sfx_boing(180 + 40 * k, 0.4), 0.45, pan=(SLOTS[k] - 540) / 600)
    add(FIN0 + 2.0, sfx_pop(1100), 0.8)
    add(FIN0 + 2.0, sfx_sparkle(91, 14, 1.5), 0.8)
    for k in range(3):
        add(FIN0 + 2.1 + k * 0.12, sfx_giggle(560 + 90 * k, 4, 10 + k), 0.45, pan=(-0.5, 0, 0.5)[k])
    for k in range(5):
        add(FIN0 + 3.0 + 0.18 * (4 - k), sfx_slide(500 + 60 * k, 1100 + 60 * k, 0.3), 0.3, pan=0.6)
    add(FIN0 + 3.2, sfx_whoosh(0.6, True, 21), 0.35, pan=0.6)
    add(FIN0 + 4.3, sfx_sparkle(99, 8, 0.6), 0.6)
    # gentle limiter
    peak = np.abs(mix).max()
    mix = np.tanh(mix / peak * 1.3) / math.tanh(1.3) * 0.89
    pcm = (mix * 32767).astype('<i2')
    with wave.open(path, 'wb') as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm.tobytes())


def main():
    out = sys.argv[1] if len(sys.argv) > 1 else 'magical-surprise-eggs.mp4'
    if '--preview' in sys.argv:
        from PIL import Image
        ts = [float(x) for x in sys.argv[sys.argv.index('--preview') + 1].split(',')]
        for t in ts:
            Image.fromarray(render_frame(int(round(t * FPS)))).save(f'{out}_{t:05.2f}.png')
        return
    wav = out + '.wav'
    build_audio(wav)
    cmd = ['ffmpeg', '-y', '-loglevel', 'error', '-f', 'rawvideo', '-pix_fmt', 'rgb24',
           '-s', f'{W}x{H}', '-r', str(FPS), '-i', '-', '-i', wav,
           '-c:v', 'libx264', '-preset', 'slow', '-crf', '19', '-pix_fmt', 'yuv420p',
           '-profile:v', 'high', '-c:a', 'aac', '-b:a', '192k', '-shortest',
           '-movflags', '+faststart', out]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    with Pool(4) as pool:
        for k, fr in enumerate(pool.imap(render_frame, range(NFRAMES), chunksize=2)):
            proc.stdin.write(fr.tobytes())
            if k % 60 == 0:
                print(f'frame {k}/{NFRAMES}', flush=True)
    proc.stdin.close()
    proc.wait()


if __name__ == '__main__':
    main()

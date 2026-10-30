#!/usr/bin/env python3
"""Guess the Shadow! Magic Bubbles - YouTube Short #2 for "عالم المغامرات".

Giant magic bubbles float up, each hiding a dark silhouette. Three glowing
ticks count down, the bubble pops, and a friend appears in full colour. The
last bubble hides the mint egg from episode 1 (series teaser). 1080x1920,
30 fps, 26.4 s, synthesized SFX only, seamless loop.

Reuses the drawing engine and cast from ../magical-surprise-eggs/render.py.
Usage: python3 render.py out.mp4 [--preview t1,t2,...]
"""
import math
import os
import subprocess
import sys
import wave
from multiprocessing import Pool

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'magical-surprise-eggs'))
import render as E  # noqa: E402
from render import (C, W, H, FPS, ell, soft, sparkle, heart, bubble, Rig, ANIMALS,  # noqa: E402
                    egg_full, damp, ease_io, ease_out_back, clamp01, blink, CONF_COLS)

DUR = 26.4
NFRAMES = int(round(DUR * FPS))

ORDER = [1, 2, 0, 4, 3]           # bunny, panda, chick, dino, elephant
SLOTS = [140, 340, 540, 740, 940]  # cloud positions by reveal order
ROW_Y, ROW_S = 1712.0, 0.40
BX, BY, BR = 540.0, 900.0, 330.0
STEP = 3.4
RISE, GUESS, POP, HOP = 0.6, 2.0, 2.0, 2.8
TICKS = (0.85, 1.3, 1.75)
EGG_B = 5 * STEP - 0.6             # bubble #6 (the egg) base time = 16.4
EGG_CLOUD = (540.0, 1340.0)
FIN = EGG_B + POP + 0.6            # 19.0
SIL = C('#2a1d4f')


def base_time(k):
    return k * STEP - 0.6


def local(t, k):
    lt = t - base_time(k)
    if k == 0 and t > DUR - RISE:
        lt = t - DUR + 0.6           # bubble #1 rises at the very end (loop)
    return lt


# ----------------------------------------------------------------------------
# Background
# ----------------------------------------------------------------------------
_BG = None
RAINBOW = [C('#ff9aa2'), C('#ffc89a'), C('#fff0a0'), C('#b5f0b0'), C('#a0d8ff'), C('#cdb4ff')]


def cloud(cv, cx, cy, s, shade=0.4, alpha=1.0):
    for (dx, dy, r) in ((-110, 25, 70), (-50, -25, 95), (40, -40, 105), (120, 0, 80),
                        (0, 30, 95), (-150, 45, 50), (165, 40, 55)):
        ell(cv, cx + dx * s, cy + dy * s, r * s, r * s * 0.86, (1, 1, 1), shade=shade, spec=0.05,
            alpha=alpha)


def background():
    global _BG
    if _BG is not None:
        return _BG
    cv = np.zeros((H, W, 3), np.float32)
    y = np.linspace(0, 1, H, dtype=np.float32)
    stops = [(0.0, C('#6ec6ff')), (0.45, C('#c3b6ff')), (0.8, C('#ffc6e5')), (1.0, C('#ffe2c8'))]
    g = np.zeros((H, 3), np.float32)
    for (a, ca), (b, cb) in zip(stops, stops[1:]):
        m = (y >= a) & (y <= b)
        f = ((y[m] - a) / (b - a))[:, None]
        g[m] = ca + (cb - ca) * f
    cv[:] = g[:, None, :]
    # soft rainbow arc
    Y, X = np.mgrid[0:H, 0:W].astype(np.float32)
    d = np.hypot(X - 540, Y - 1600)
    for i, col in enumerate(RAINBOW):
        r0 = 1050 - i * 42
        a = (np.clip(21 - np.abs(d - r0), 0, 1) * 0.42)[..., None]
        cv[:] = cv * (1 - a) + col * a
    rng = np.random.default_rng(11)
    for _ in range(40):
        sparkle(cv, rng.uniform(0, W), rng.uniform(0, 700), rng.uniform(5, 10), col=(1, 1, 1),
                alpha=rng.uniform(0.4, 0.8))
    cloud(cv, 180, 330, 0.8, 0.3)
    cloud(cv, 900, 520, 0.6, 0.3)
    # cloud platform where the friends gather
    for i in range(14):
        x = -40 + i * 86
        ell(cv, x, 1790 + 25 * math.sin(i * 1.7), 120, 95, (1, 1, 1), shade=0.45, spec=0.05)
    for i in range(12):
        x = 0 + i * 98
        ell(cv, x, 1890 + 15 * math.sin(i * 2.3), 130, 90, C('#fff4fb'), shade=0.4, spec=0.0)
    yy = (np.arange(H, dtype=np.float32)[:, None] - H / 2) / H
    xx = (np.arange(W, dtype=np.float32)[None, :] - W / 2) / W
    cv *= (1 - 0.3 * (xx ** 2 + yy ** 2))[..., None]
    _BG = cv
    return cv


def ambient(cv, t):
    rng = np.random.default_rng(7)
    for j in range(10):
        x0, y0 = rng.uniform(0, W), rng.uniform(0, H)
        k = int(rng.integers(1, 3))
        y = (y0 - (t / DUR) * (H + 200) * k) % (H + 200) - 100
        x = x0 + 25 * math.sin(2 * math.pi * (t / DUR) * 5 + j)
        bubble(cv, x, y, rng.uniform(10, 22), alpha=0.7)


# ----------------------------------------------------------------------------
# Magic bubble
# ----------------------------------------------------------------------------

def big_bubble(cv, cx, cy, rx, ry, t, alpha=1.0):
    r = max(rx, ry)
    b = E._box(cx, cy, r + 2)
    if b is None:
        return
    x0, x1, y0, y1, X, Y = b
    u, v = (X - cx) / rx, (Y - cy) / ry
    d = np.sqrt(u * u + v * v)
    ang = np.arctan2(v, u)
    edge = np.clip((1 - d) * min(rx, ry) + 0.5, 0, 1)
    a = edge * (0.06 + 0.55 * np.clip(d, 0, 1) ** 10) * alpha
    ph = ang * 2 + t * 1.8 + d * 4
    hue = np.stack([0.65 + 0.35 * np.sin(ph), 0.65 + 0.35 * np.sin(ph + 2.1),
                    0.75 + 0.25 * np.sin(ph + 4.2)], -1).astype(np.float32)
    hue = hue * 0.6 + 0.4
    a3 = a[..., None]
    reg = cv[y0:y1, x0:x1]
    reg *= (1 - a3)
    reg += hue * a3
    ell(cv, cx - rx * 0.42, cy - ry * 0.5, rx * 0.28, ry * 0.13, (1, 1, 1), ang=-0.75, shade=0,
        alpha=0.75 * alpha)
    ell(cv, cx - rx * 0.62, cy - ry * 0.18, rx * 0.06, ry * 0.06, (1, 1, 1), shade=0, alpha=0.8 * alpha)
    ell(cv, cx + rx * 0.5, cy + ry * 0.55, rx * 0.2, ry * 0.07, (1, 1, 1), ang=-0.8, shade=0,
        alpha=0.35 * alpha)


def pop_burst(cv, cx, cy, dt, seed):
    if not 0 <= dt < 1.2:
        return
    p = dt / 0.35
    if p < 1:
        rr = BR * (1 + 0.5 * p)
        b = E._box(cx, cy, rr + 12)
        if b is not None:
            x0, x1, y0, y1, X, Y = b
            dd = np.hypot(X - cx, Y - cy)
            a = (np.clip(8 - np.abs(dd - rr), 0, 1) * 0.7 * (1 - p))[..., None]
            reg = cv[y0:y1, x0:x1]
            reg *= (1 - a)
            reg += np.array([1, 1, 1], np.float32) * a
    rng = np.random.default_rng(seed)
    for j in range(18):
        ang = j * 2 * math.pi / 18 + rng.uniform(-0.15, 0.15)
        sp = rng.uniform(500, 900)
        x = cx + math.cos(ang) * (BR * 0.9 + sp * dt)
        y = cy + math.sin(ang) * (BR * 0.9 + sp * dt) + 700 * dt * dt
        if dt < 0.9:
            bubble(cv, x, y, rng.uniform(10, 22) * (1 - dt), alpha=1.0)
    for j in range(10):
        ang = rng.uniform(0, 2 * math.pi)
        rr = 150 + 280 * (1 - math.exp(-4 * dt))
        sparkle(cv, cx + math.cos(ang) * rr, cy + math.sin(ang) * rr, rng.uniform(18, 32),
                alpha=clamp01(1 - dt / 1.0), ang=dt * 2)
    for j in range(24):
        ang = rng.uniform(-math.pi, 0)
        sp = rng.uniform(400, 1000)
        x = cx + math.cos(ang) * sp * dt * 0.9
        y = cy + math.sin(ang) * sp * dt + 0.5 * 1500 * dt * dt
        spin = rng.uniform(6, 12) * dt + j
        ell(cv, x, y, 12, 6 * abs(math.cos(spin)) + 1.5, CONF_COLS[j % 6], ang=spin * 0.7, spec=0.4,
            alpha=clamp01((1.2 - dt) / 0.4))


# ----------------------------------------------------------------------------
# Characters
# ----------------------------------------------------------------------------

def react_state(a, rt):
    """Celebration pose right after the reveal; rt = time since pop."""
    st = dict(blink=1.0, mouth='smile', mopen=0.8)
    if rt < 0.25:
        st.update(mouth='o', mopen=0.6)
    else:
        st['happy'] = True
    if a == 0:
        st['flap'] = 0.3 * math.sin(rt * 26)
    elif a == 1:
        st['ear'] = 0.8 * damp(rt, 2.6, 2.5)
    elif a == 2:
        st['wave'] = math.sin(rt * 14)
    elif a == 3:
        st['trunk'] = ease_io(rt / 0.25)
        st['flap'] = math.sin(rt * 16)
    elif a == 4:
        st['arms'] = 0.5 + 0.5 * math.sin(rt * 14)
    return st


def draw_friend(cv, a, x, y, s, st, sx=1.0, sy=1.0, rot=0.0):
    rg = Rig(cv, x, y + 135 * s * (1 - sy), s, sx, sy, rot)
    ANIMALS[a](rg, st)


def row_friend(cv, i, t, x, y, extra=None, jump=0.0):
    a = ORDER[i]
    st = dict(blink=blink(t, i + 2), mouth='smile', mopen=0.5)
    if extra:
        st.update(extra)
    bob = math.sin(2 * math.pi * (t / DUR) * 12 + i * 1.4)
    soft(cv, x, ROW_Y + 4, 70, 14, (0.45, 0.35, 0.6), 0.3 * (1 - min(1, -jump / 300)))
    draw_friend(cv, a, x, y + jump, ROW_S, st, 1 + 0.03 * bob, 1 - 0.03 * bob)


def silhouette_mix(cv, draw_fn, rev):
    """Draw with draw_fn as a silhouette, cross-fading to full colour by rev (0..1)."""
    if rev <= 0:
        E.SILHOUETTE = SIL
        draw_fn(cv)
        E.SILHOUETTE = None
        return
    if rev >= 1:
        draw_fn(cv)
        return
    sil = cv.copy()
    E.SILHOUETTE = SIL
    draw_fn(sil)
    E.SILHOUETTE = None
    draw_fn(cv)
    cv *= rev
    cv += sil * (1 - rev)


# ----------------------------------------------------------------------------
# Bubble scenes
# ----------------------------------------------------------------------------

def bubble_pos(lt):
    if lt < RISE:
        p = ease_out_back(lt / RISE, 1.4)
        y = H + 380 + (BY - H - 380) * p
    else:
        y = BY + 14 * math.sin((lt - RISE) * 3.2)
    x = BX + 18 * math.sin(lt * 2.1)
    return x, y


def tick_squish(lt):
    sq = 0.0
    for tk in TICKS:
        if lt >= tk:
            sq += 0.07 * damp(lt - tk, 3.5, 6)
    return sq


def draw_ticks(cv, lt):
    for j, tk in enumerate(TICKS):
        if lt >= tk:
            s = ease_out_back((lt - tk) / 0.2, 2.5)
            x = BX + (j - 1) * 95
            y = BY - BR - 95 - (12 if j == 1 else 0)
            col = [C('#ffe066'), C('#ffb3d9'), C('#9ff2d6')][j]
            soft(cv, x, y, 55 * s, 55 * s, col, 0.5)
            ell(cv, x, y, 26 * s, 26 * s, col, spec=0.7, gloss=20)


def draw_bubble_scene(cv, k, lt, t):
    """k = 0..4 friend bubbles, 5 = egg bubble. lt = local time."""
    x, y = bubble_pos(lt)
    sq = tick_squish(lt) + 0.025 * math.sin(lt * 9)
    rx, ry = BR * (1 + sq), BR * (1 - sq)

    if k < 5:
        a = ORDER[k]
        if lt < POP:
            st = dict(blink=blink(lt, k), mouth='smile', mopen=0.4)
            sway = 0.08 * math.sin(lt * 4)
            silhouette_mix(cv, lambda c: draw_friend(c, a, x, y - 20, 0.85, st, 1 + sq, 1 - sq, sway), 0.0)
        return rx, ry, x, y

    # egg bubble
    if lt < POP:
        wob = 0.12 * math.sin(lt * 7)
        def fn(c):
            egg_full(c, 0, x, y, sx=0.62, sy=0.62, ang=wob, spin=wob * 2)
        silhouette_mix(cv, fn, 0.0)
    return rx, ry, x, y


def friend_after_pop(cv, k, lt, t):
    """Reveal, celebration and hop to the cloud row."""
    a = ORDER[k]
    rt = lt - POP
    rev = clamp01(rt / 0.22)
    if lt < HOP:
        soft(cv, BX, BY, 300, 300, (1, 0.97, 0.85), 0.45 * clamp01(1 - rt / 0.8))
        st = react_state(a, rt)
        ts = 1 + 0.15 * damp(rt, 2.2, 4)
        jy = -60 * math.sin(math.pi * clamp01(rt / 0.45))
        x, y = BX, BY - 20 + jy
        silhouette_mix(cv, lambda c: draw_friend(c, a, x, y, 0.85, dict(st), 2 - ts, ts), rev)
        return
    p = (lt - HOP) / (STEP - HOP)
    if p > 1:
        return
    e = ease_io(p)
    x1, y1 = SLOTS[k], ROW_Y - 135 * ROW_S
    x = BX + (x1 - BX) * e
    y = BY - 20 + (y1 - BY + 20) * e - 360 * math.sin(math.pi * p)
    s = 0.85 + (ROW_S - 0.85) * e
    st = dict(blink=1.0, happy=True, mouth='smile', mopen=0.7)
    draw_friend(cv, a, x, y, s, st, 1 - 0.08 * math.sin(math.pi * p), 1 + 0.08 * math.sin(math.pi * p),
                0.3 * math.sin(2 * math.pi * p) * (1 if x1 >= BX else -1))


def egg_cloud(cv, t, dy=0.0):
    cx, cy = EGG_CLOUD
    bob = 8 * math.sin(2 * math.pi * (t / DUR) * 8)
    cloud(cv, cx, cy + 70 + bob + dy, 0.6, 0.35)
    return bob


def egg_after_pop(cv, lt, t, dy=0.0):
    rt = lt - POP
    rev = clamp01(rt / 0.22)
    cx, cy = EGG_CLOUD
    if rt < 0.6:
        soft(cv, BX, BY, 300, 300, (1, 0.97, 0.85), 0.45 * clamp01(1 - rt / 0.8))
        p = ease_io(rt / 0.6)
        x = BX + (cx - BX) * p
        y = BY + (cy - 70 - BY) * p - 200 * math.sin(math.pi * p)
        sc = 0.62 + (0.42 - 0.62) * p
        silhouette_mix(cv, lambda c: egg_full(c, 0, x, y, sx=sc, sy=sc, ang=p * 2 * math.pi), rev)
        return
    bob = egg_cloud(cv, t, dy)
    tt = rt - 0.6
    sx, sy = 1 + 0.12 * damp(tt, 3, 6), 1 - 0.12 * damp(tt, 3, 6)
    wig = 0.0
    fl = t - FIN
    for j in range(5):
        jt = fl - (0.3 + 0.25 * j)
        if 0 < jt < 0.4:
            wig = 0.18 * math.sin(jt / 0.4 * 2 * math.pi)
    if 3.4 < fl < 3.9:
        wig = 0.25 * math.sin((fl - 3.4) / 0.5 * 4 * math.pi)
    ry = 300 * 0.42 * sy
    base = cy - 6 + bob + dy
    soft(cv, cx, base + 6, 90, 14, (0.45, 0.35, 0.6), 0.3)
    egg_full(cv, 0, cx + ry * math.sin(wig), base - ry * math.cos(wig), sx=0.42 * sx, sy=0.42 * sy,
             ang=wig, spin=wig * 3)
    for j in range(3):
        ang = t * 2.5 + j * 2 * math.pi / 3
        sparkle(cv, cx + math.cos(ang) * 150, base - 130 + math.sin(ang) * 40, 14,
                alpha=0.6 + 0.4 * math.sin(t * 6 + j))


# Finale bubble shower (shared by video and audio)
_rng = np.random.default_rng(2024)
SHOWER = [(FIN + 1.6 + _rng.uniform(0, 1.6), _rng.uniform(60, W - 60), _rng.uniform(1.0, 1.8),
           _rng.uniform(16, 34)) for _ in range(34)]


def draw_finale(cv, t):
    fl = t - FIN
    leave0 = 4.2
    for i in range(5):
        x = SLOTS[i]
        y = ROW_Y - 135 * ROW_S
        extra, jump = {}, 0.0
        jt = fl - (0.3 + 0.25 * i)
        if 0 < jt < 0.45:
            jump = -150 * 4 * (jt / 0.45) * (1 - jt / 0.45)
            extra['happy'] = True
        if 1.6 < fl < 3.4:
            extra['happy'] = True
            jump = -40 * abs(math.sin((fl - 1.6) * 6 + i))
        lt = fl - (leave0 + 0.15 * abs(i - 2))
        if lt > 0:
            p = min(1.0, lt / 0.75)
            if p >= 1:
                continue
            dirn = -1 if i < 2 else (1 if i > 2 else 0)
            x = x + dirn * 760 * ease_io(p)
            jump = -380 * math.sin(math.pi * p) if dirn else -1500 * ease_io(p) ** 1.5
            extra['happy'] = True
        row_friend(cv, i, t, x, y, extra, jump)
        if 0.2 < jt < 1.4:
            heart(cv, x + 20 * math.sin(jt * 6), y - 110 - 170 * jt + jump * 0.2, 22, C('#ff6b9d'),
                  alpha=clamp01((1.4 - jt) / 0.4))
    for (tp, x, life, r) in SHOWER:
        dt = t - (tp - life)
        if 0 <= dt < life:
            yb = H + 40 - (H * 0.75) * (dt / life) ** 0.8
            bubble(cv, x + 25 * math.sin(dt * 5 + x), yb, r)
        elif 0 <= t - tp < 0.3:
            yb = H + 40 - H * 0.75
            sparkle(cv, x, yb, r * 0.9, col=(0.9, 0.97, 1), alpha=1 - (t - tp) / 0.3)


def render_frame(i):
    t = i / FPS
    cv = background().copy()
    ambient(cv, t)
    # egg on its little cloud (after reveal), floats away at the end
    if t >= EGG_B + POP and t < DUR - 0.9:
        dy = 0.0
        if t > FIN + 4.5:
            dy = -1700 * ease_io((t - FIN - 4.5) / 1.4)
        egg_after_pop(cv, t - EGG_B, t, dy)
    # friends already on the cloud row
    if t < FIN:
        for i in range(5):
            if local(t, i) >= STEP:
                row_friend(cv, i, t, SLOTS[i], ROW_Y - 135 * ROW_S)
    else:
        draw_finale(cv, t)
    # active bubble
    for k in range(6):
        lt = (t - EGG_B) if k == 5 else local(t, k)
        if lt < 0 or lt > STEP:
            continue
        if lt < POP:
            rx, ry, x, y = draw_bubble_scene(cv, k, lt, t)
            big_bubble(cv, x, y, rx, ry, t)
            if lt > RISE:
                draw_ticks(cv, lt)
        else:
            if k < 5:
                friend_after_pop(cv, k, lt, t)
            pop_burst(cv, BX, BY, lt - POP, 50 + k)
    return (np.clip(cv, 0, 1) * 255 + 0.5).astype(np.uint8)


# ----------------------------------------------------------------------------
# Audio
# ----------------------------------------------------------------------------
SR = E.SR


def sfx_bloop():
    t = E._t(0.35)
    f = 140 * (2.4 ** (t / 0.35))
    ph = 2 * np.pi * np.cumsum(f) / SR
    return np.sin(ph) * np.sin(np.pi * t / 0.35) * 0.45


def sfx_trumpet():
    t = E._t(0.4)
    f = 420 * (1 + 0.25 * np.minimum(1, t / 0.1)) * (1 + 0.02 * np.sin(2 * np.pi * 9 * t))
    ph = 2 * np.pi * np.cumsum(f) / SR
    s = sum(np.sin(h * ph) / h for h in range(1, 7))
    return s * np.sin(np.pi * t / 0.4) ** 0.7 * 0.3


def build_audio(path):
    n = int(DUR * SR)
    mix = np.zeros((n, 2))

    def add(tt, sig, gain=1.0, pan=0.0):
        tt = tt % DUR
        s = int(tt * SR)
        l, r = math.cos((pan + 1) * math.pi / 4) * 1.41, math.sin((pan + 1) * math.pi / 4) * 1.41
        e = min(n, s + sig.size)
        mix[s:e, 0] += sig[:e - s] * gain * l
        mix[s:e, 1] += sig[:e - s] * gain * r
        rest = sig.size - (e - s)
        if rest > 0:
            mix[:rest, 0] += sig[e - s:] * gain * l
            mix[:rest, 1] += sig[e - s:] * gain * r

    giggle_f = {0: 720, 1: 780, 2: 600, 3: 660, 4: 560}
    for k in range(6):
        b = EGG_B if k == 5 else base_time(k)
        add(b + 0.05, sfx_bloop(), 0.6)
        add(b + 0.1, E.sfx_whoosh(0.4, True, k), 0.2)
        for j, tk in enumerate(TICKS):
            add(b + tk, E.sfx_tick(1600 + 450 * j), 0.6)
            add(b + tk, E.sfx_boing(260 + 70 * j, 0.25), 0.25)
        add(b + POP, E.sfx_pop(1000), 1.0)
        add(b + POP + 0.02, E.sfx_sparkle(k + 7, 10, 0.6), 0.85)
        add(b + POP + 0.08, E.sfx_chime_rise(), 0.55)
        if k < 5:
            a = ORDER[k]
            add(b + POP + 0.3, E.sfx_giggle(giggle_f[a], 5, k), 0.75)
            if a == 1:
                add(b + POP + 0.05, E.sfx_boing(200, 0.6), 0.6)
            elif a == 3:
                add(b + POP + 0.15, sfx_trumpet(), 0.6)
            elif a == 4:
                add(b + POP + 0.2, E.sfx_squeak(), 0.5)
            elif a == 0:
                for q in range(5):
                    add(b + POP + 0.3 + q * 0.07, E.sfx_tick(3000), 0.3)
            add(b + HOP, E.sfx_slide(450, 1200, 0.32), 0.45, pan=(SLOTS[k] - 540) / 600)
            add(b + STEP - 0.05, E.sfx_boing(300, 0.3), 0.35, pan=(SLOTS[k] - 540) / 600)
        else:
            add(b + POP + 0.1, E.sfx_slide(1200, 500, 0.4), 0.4)
            add(b + POP + 0.6, E.sfx_thud(), 0.6)
            add(b + POP + 0.62, E.sfx_boing(180, 0.45), 0.5)
    for i in range(5):
        add(FIN + 0.3 + 0.25 * i, E.sfx_boing(180 + 40 * i, 0.4), 0.45, pan=(SLOTS[i] - 540) / 600)
    add(FIN + 3.4, E.sfx_crack(5), 0.4)
    add(FIN + 3.45, E.sfx_sparkle(77, 5, 0.3), 0.5)
    for (tp, x, life, r) in SHOWER:
        add(tp - life + 0.05, E.sfx_blip(260, 700), 0.12, pan=(x - 540) / 700)
        add(tp, E.sfx_pop(1300 + r * 20), 0.35, pan=(x - 540) / 700)
    add(FIN + 1.7, E.sfx_giggle(620, 4, 31), 0.45, pan=-0.4)
    add(FIN + 1.9, E.sfx_giggle(760, 4, 32), 0.45, pan=0.4)
    for i in range(5):
        add(FIN + 4.2 + 0.15 * abs(i - 2), E.sfx_slide(500 + 60 * i, 1150 + 60 * i, 0.3), 0.3,
            pan=(SLOTS[i] - 540) / 600)
    add(FIN + 4.4, E.sfx_whoosh(0.7, True, 41), 0.35)
    add(FIN + 4.6, E.sfx_slide(400, 1400, 0.8), 0.3)
    peak = np.abs(mix).max()
    mix = np.tanh(mix / peak * 1.3) / math.tanh(1.3) * 0.89
    with wave.open(path, 'wb') as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes((mix * 32767).astype('<i2').tobytes())


def main():
    out = sys.argv[1] if len(sys.argv) > 1 else 'guess-the-shadow-bubbles.mp4'
    if '--preview' in sys.argv:
        from PIL import Image
        for t in [float(x) for x in sys.argv[sys.argv.index('--preview') + 1].split(',')]:
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
            if k % 120 == 0:
                print(f'frame {k}/{NFRAMES}', flush=True)
    proc.stdin.close()
    proc.wait()
    os.remove(wav)


if __name__ == '__main__':
    main()

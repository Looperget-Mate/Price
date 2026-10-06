# -*- coding: utf-8 -*-
"""
looperget.design.branch — 가지관 열 ↔ 주배관 연결(탭점)과 사선 분기 곡선(규칙 14).

원천: `_설계/배추밭스프링클러_20260824/10_계산/_계산_주배관_숙진리.py` `main_dir_at` · `branch_path`
(대표 지시 2026-08-27 · 논산 생강 26.03.23 시공 사례). 헤드 배치는 바꾸지 않는다 — 곡선은 첫 헤드 앞에서 끝난다.
"""
from __future__ import annotations

import math
from typing import Dict, List, Optional, Sequence, Tuple

from . import geom as G

Pt = Tuple[float, float]

BRANCH_DEV = 20.0        # 직각에서 이만큼(도) 이상 벗어나면 곡선으로 잇는다
BRANCH_MAX = 6.0         # 곡선 구간 최대 길이(m)
BRANCH_GAP = 1.0         # 첫 헤드 앞에 남기는 여유(m)
TAP_BACK_MAX = 20.0      # 열 시작점 뒤쪽으로 이만큼 안에서 주배관을 찾는다(m)
TAP_AHEAD_MAX = 2.0      # 주배관이 밭 안쪽으로 살짝 들어와 있으면(02 = 1.1 m) 앞쪽 이만큼까지 허용
TAP_NEAR_MAX = 6.0       # 직선 교점이 없으면 가장 가까운 주배관 점(이 거리 안)을 탭점으로


def main_dir_at(p: Pt, routes: Sequence[Sequence[Pt]]) -> Optional[Pt]:
    """점 p에 가장 가까운 주배관 구간의 방향(단위벡터)."""
    best = None
    for rt in routes:
        for a, b in zip(rt, rt[1:]):
            dx, dy = b[0] - a[0], b[1] - a[1]
            L2 = dx * dx + dy * dy
            if L2 == 0:
                continue
            t = max(0.0, min(1.0, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / L2))
            d = math.dist(p, (a[0] + t * dx, a[1] + t * dy))
            if best is None or d < best[0]:
                L = math.sqrt(L2)
                best = (d, (dx / L, dy / L))
    return best[1] if best else None


def find_tap(p0: Pt, dir_: Pt, routes: Sequence[Sequence[Pt]]) -> Optional[Dict]:
    """열 시작점 p0에서 열 방향 반대쪽으로 주배관을 찾아 탭점을 정한다.
    1순위: 열 직선과 주배관의 교점 중 p0 뒤쪽(≤ TAP_BACK_MAX) 가장 가까운 것.
    2순위: 주배관 위 최근접점(≤ TAP_NEAR_MAX). 없으면 None(급수 안 되는 열 — 경고)."""
    best = None
    for i, rt in enumerate(routes):
        for s, pt in G.polyline_line_intersections(rt, p0, dir_):
            t = G.dot(G.sub(pt, p0), dir_)          # p0 기준 열 방향 좌표(뒤쪽이 음수)
            if -TAP_BACK_MAX <= t <= TAP_AHEAD_MAX:
                if best is None or abs(t) < best[0]:
                    best = (abs(t), i, s, pt, "교점")
    if best is None:
        for i, rt in enumerate(routes):
            s, pt, _ = G.nearest_on_polyline(rt, p0)
            d = G.dist(pt, p0)
            if d <= TAP_NEAR_MAX and (best is None or d < best[0]):
                best = (d, i, s, pt, "최근접")
    if best is None:
        return None
    _, i, s, pt, how = best
    return {"route": i, "s": round(s, 2), "pt": (pt[0], pt[1]), "how": how}


LEAD_MAX = 60.0          # [경계 연결] 주배관에서 이 길이 안이면 25 mm를 경계 따라 올려 잇는다(m)


def boundary_lead(p0: Pt, poly: Sequence[Pt], routes: Sequence[Sequence[Pt]],
                  max_m: float = LEAD_MAX) -> Optional[Dict]:
    """주배관과 만나지 않는 열 — 가장 가까운 주배관 점에서 H25로 따서 **25 mm를 밭 경계를 따라**
    열 시작점 p0까지 올린다(대표 지시 2026-10-06 군위 봉소리 97: 「주배관을 올리지 말고 25를 따서
    경계 따라 올라가다가 그 열을 연결하도록 안내」). 40 mm 주배관을 그 열까지 끌어올리지 않는다.

    → {"route": 주배관 index, "pt": 탭점, "pts": [탭점 … p0](경계 꼭짓점 경유), "len": m} · 없으면 None."""
    ring = [tuple(p) for p in poly]
    if len(ring) < 3 or not routes:
        return None
    if ring[0] != ring[-1]:
        ring = ring + [ring[0]]
    perim = G.polyline_len(ring)
    if perim <= 0:
        return None

    def arc_pos(q: Pt) -> Tuple[float, Pt]:
        s, pt, _ = G.nearest_on_polyline(ring, q)
        return s, pt

    def walk(s_a: float, s_b: float, forward: bool) -> List[Pt]:
        """경계 위 s_a → s_b 사이의 꼭짓점(끝점 제외) — forward 면 꼭짓점 순서대로."""
        acc, cum = [], [0.0]
        for a, b in zip(ring, ring[1:]):
            cum.append(cum[-1] + G.dist(a, b))
        verts = list(zip(cum[:-1], ring[:-1]))       # (호 위치, 꼭짓점) — 닫는 점 제외
        if forward:
            span = (s_b - s_a) % perim
            for c, v in sorted(verts, key=lambda cv: (cv[0] - s_a) % perim):
                if 1e-6 < (c - s_a) % perim < span - 1e-6:
                    acc.append(v)
        else:
            span = (s_a - s_b) % perim
            for c, v in sorted(verts, key=lambda cv: (s_a - cv[0]) % perim):
                if 1e-6 < (s_a - c) % perim < span - 1e-6:
                    acc.append(v)
        return acc

    s_p, q_p = arc_pos(p0)
    best = None
    for i, rt in enumerate(routes):
        if len(rt) < 2:
            continue
        _s, tap, _ = G.nearest_on_polyline(rt, p0)
        s_t, q_t = arc_pos(tap)
        for fwd in (True, False):
            mid = walk(s_t, s_p, fwd)
            pts = [tap]
            if G.dist(tap, q_t) > 0.3:
                pts.append(q_t)
            pts += mid
            if G.dist(pts[-1], p0) > 1e-6:
                pts.append(p0)
            L = G.polyline_len(pts)
            if best is None or L < best["len"]:
                best = {"route": i, "pt": tap, "pts": pts, "len": L}
    if best is None or best["len"] > max_m:
        return None
    return best


def branch_path(p0: Pt, p1: Pt, off: float, routes: Sequence[Sequence[Pt]], n_seg: int = 14
                ) -> Tuple[List[Pt], float, float, float]:
    """가지관 1열의 실제 경로. 직각에서 BRANCH_DEV 이상 벗어나면 분기부를 3차 베지어로 잇는다.
    → (경로 폴리라인, 총길이, 직선 대비 증가분, 직각 이탈각)."""
    L = G.dist(p0, p1)
    if L == 0:
        return [p0, p1], 0.0, 0.0, 0.0
    u = ((p1[0] - p0[0]) / L, (p1[1] - p0[1]) / L)
    m = main_dir_at(p0, routes)
    if m is None:
        return [p0, p1], L, 0.0, 0.0
    n = (-m[1], m[0])
    if G.dot(n, u) < 0:                              # 밭 안쪽을 향하도록
        n = (-n[0], -n[1])
    dev = math.degrees(math.acos(max(-1.0, min(1.0, G.dot(n, u)))))
    d = min(BRANCH_MAX, off - BRANCH_GAP)            # 첫 헤드 앞에서 곡선을 끝낸다
    if dev < BRANCH_DEV or d <= 0.5:
        return [p0, p1], L, 0.0, round(dev, 1)
    q = (p0[0] + u[0] * d, p0[1] + u[1] * d)         # 직선부 시작점(열 위)
    c1 = (p0[0] + n[0] * d * 0.70, p0[1] + n[1] * d * 0.70)
    c2 = (q[0] - u[0] * d * 0.70, q[1] - u[1] * d * 0.70)
    pts = [(round(x, 2), round(y, 2)) for x, y in G.bezier3(p0, c1, c2, q, n_seg)]
    pts.append((round(p1[0], 2), round(p1[1], 2)))
    Lp = G.polyline_len(pts)
    return pts, Lp, Lp - L, round(dev, 1)

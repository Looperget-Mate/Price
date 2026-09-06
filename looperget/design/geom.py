# -*- coding: utf-8 -*-
"""
looperget.design.geom — 평면 기하 원시 함수 (로컬 m 좌표계, y 아래 방향도 무방).

설계 엔진이 쓰는 것만 둔다: 벡터 · 폴리곤 면적/내부 판정 · 직선-폴리곤 교차 · 폴리라인 길이/보간 ·
3차 베지어 길이(규칙 14 곡선 분기). 외부 라이브러리 없음.
"""
from __future__ import annotations

import math
from typing import Iterable, List, Sequence, Tuple

Pt = Tuple[float, float]


# ── 벡터 ────────────────────────────────────────────────────────────────
def sub(a: Pt, b: Pt) -> Pt:
    return (a[0] - b[0], a[1] - b[1])


def add(a: Pt, b: Pt) -> Pt:
    return (a[0] + b[0], a[1] + b[1])


def mul(a: Pt, k: float) -> Pt:
    return (a[0] * k, a[1] * k)


def dot(a: Pt, b: Pt) -> float:
    return a[0] * b[0] + a[1] * b[1]


def cross(a: Pt, b: Pt) -> float:
    return a[0] * b[1] - a[1] * b[0]


def norm(a: Pt) -> float:
    return math.hypot(a[0], a[1])


def unit(a: Pt) -> Pt:
    n = norm(a)
    if n == 0:
        raise ValueError("영벡터")
    return (a[0] / n, a[1] / n)


def perp(u: Pt) -> Pt:
    """u를 +90° 돌린 단위 법선 (y 아래 좌표계에서는 시계 방향으로 보인다)."""
    return (-u[1], u[0])


def dist(a: Pt, b: Pt) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def deg(u: Pt) -> float:
    return math.degrees(math.atan2(u[1], u[0]))


def angle_between_deg(a: Pt, b: Pt) -> float:
    """두 방향 사이 각(0~180°)."""
    c = max(-1.0, min(1.0, dot(unit(a), unit(b))))
    return math.degrees(math.acos(c))


# ── 폴리곤 ──────────────────────────────────────────────────────────────
def area(poly: Sequence[Pt]) -> float:
    s = 0.0
    n = len(poly)
    for i in range(n):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % n]
        s += x1 * y2 - x2 * y1
    return abs(s) / 2.0


def centroid(poly: Sequence[Pt]) -> Pt:
    xs = sum(p[0] for p in poly) / len(poly)
    ys = sum(p[1] for p in poly) / len(poly)
    return (xs, ys)


def contains(poly: Sequence[Pt], p: Pt, eps: float = 1e-9) -> bool:
    """짝홀 규칙 내부 판정. 경계 위는 내부로 본다."""
    x, y = p
    inside = False
    n = len(poly)
    for i in range(n):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % n]
        # 경계 위
        if _on_segment(p, (x1, y1), (x2, y2), eps):
            return True
        if (y1 > y) != (y2 > y):
            xin = x1 + (y - y1) * (x2 - x1) / (y2 - y1)
            if x < xin:
                inside = not inside
    return inside


def _on_segment(p: Pt, a: Pt, b: Pt, eps: float) -> bool:
    if abs(cross(sub(b, a), sub(p, a))) > eps * max(1.0, norm(sub(b, a))):
        return False
    return (min(a[0], b[0]) - eps <= p[0] <= max(a[0], b[0]) + eps
            and min(a[1], b[1]) - eps <= p[1] <= max(a[1], b[1]) + eps)


def seg_dist(p: Pt, a: Pt, b: Pt) -> float:
    """점 p와 선분 ab 사이 거리."""
    dx, dy = b[0] - a[0], b[1] - a[1]
    L2 = dx * dx + dy * dy
    t = 0.0 if L2 == 0 else max(0.0, min(1.0, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / L2))
    return math.hypot(p[0] - (a[0] + t * dx), p[1] - (a[1] + t * dy))


def seg_seg_dist(a1: Pt, a2: Pt, b1: Pt, b2: Pt) -> float:
    """두 선분 사이 최소 거리 (교차하면 0)."""
    def ccw(p, q, r):
        return (q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0])
    if (ccw(a1, a2, b1) * ccw(a1, a2, b2) < 0) and (ccw(b1, b2, a1) * ccw(b1, b2, a2) < 0):
        return 0.0
    return min(seg_dist(a1, b1, b2), seg_dist(a2, b1, b2), seg_dist(b1, a1, a2), seg_dist(b2, a1, a2))


def edge_dist(p: Pt, poly: Sequence[Pt]) -> float:
    """점 p에서 폴리곤 경계까지 최소 거리."""
    n = len(poly)
    return min(seg_dist(p, poly[i], poly[(i + 1) % n]) for i in range(n))


def line_poly_crossings(p: Pt, u: Pt, poly: Sequence[Pt]) -> List[float]:
    """p + t·u 직선이 폴리곤 변과 만나는 t 값들(오름차순). 꼭짓점 중복은 걸러 낸다."""
    ts: List[float] = []
    n = len(poly)
    for i in range(n):
        a, b = poly[i], poly[(i + 1) % n]
        d = sub(b, a)
        den = cross(u, d)
        if abs(den) < 1e-12:
            continue  # 평행
        w = sub(a, p)
        t = cross(w, d) / den      # 직선 파라미터
        s = cross(w, u) / den      # 변 파라미터 0~1
        if -1e-9 <= s <= 1 + 1e-9:
            ts.append(t)
    ts.sort()
    out: List[float] = []
    for t in ts:
        if not out or abs(t - out[-1]) > 1e-6:
            out.append(t)
    return out


def inside_intervals(p: Pt, u: Pt, poly: Sequence[Pt]) -> List[Tuple[float, float]]:
    """p + t·u 직선이 폴리곤 안에 있는 t 구간들 [(t0,t1), ...]. 오목 폴리곤이면 여러 구간."""
    ts = line_poly_crossings(p, u, poly)
    out = []
    for t0, t1 in zip(ts, ts[1:]):
        mid = add(p, mul(u, (t0 + t1) / 2))
        if contains(poly, mid):
            out.append((t0, t1))
    return out


def extent(poly: Sequence[Pt], n: Pt) -> Tuple[float, float]:
    """폴리곤을 방향 n에 투영한 범위 (min, max)."""
    vals = [dot(p, n) for p in poly]
    return (min(vals), max(vals))


# ── 폴리라인 ─────────────────────────────────────────────────────────────
def polyline_len(pts: Sequence[Pt]) -> float:
    return sum(dist(a, b) for a, b in zip(pts, pts[1:]))


def point_at(pts: Sequence[Pt], s: float) -> Tuple[Pt, Pt]:
    """폴리라인 위 호장 s 지점의 (점, 진행 단위벡터). s가 길이를 넘으면 마지막 변을 연장한다."""
    acc = 0.0
    for a, b in zip(pts, pts[1:]):
        L = dist(a, b)
        if L == 0:
            continue
        d = unit(sub(b, a))
        if acc + L >= s or (a, b) == (pts[-2], pts[-1]):
            return (add(a, mul(d, s - acc)), d)
        acc += L
    raise ValueError("빈 폴리라인")


def cut(pts: Sequence[Pt], s_end: float) -> List[Pt]:
    """폴리라인의 처음부터 호장 s_end까지."""
    out = [tuple(pts[0])]
    acc = 0.0
    for a, b in zip(pts, pts[1:]):
        L = dist(a, b)
        if acc + L >= s_end:
            out.append(add(a, mul(unit(sub(b, a)), s_end - acc)))
            return out
        out.append(tuple(b))
        acc += L
    return out


def polyline_line_intersections(pts: Sequence[Pt], p: Pt, u: Pt) -> List[Tuple[float, Pt]]:
    """직선 p + t·u 와 폴리라인 변들의 교점 → [(폴리라인 호장 s, 교점), ...]."""
    out = []
    acc = 0.0
    for a, b in zip(pts, pts[1:]):
        d = sub(b, a)
        L = norm(d)
        den = cross(u, d)
        if L > 0 and abs(den) > 1e-12:
            w = sub(a, p)
            lam = cross(w, u) / den   # 변 파라미터
            if -1e-9 <= lam <= 1 + 1e-9:
                out.append((acc + lam * L, add(a, mul(d, lam))))
        acc += L
    return out


def nearest_on_polyline(pts: Sequence[Pt], q: Pt) -> Tuple[float, Pt, Pt]:
    """폴리라인에서 q에 가장 가까운 점 → (호장 s, 점, 그 변의 단위벡터)."""
    best = None
    acc = 0.0
    for a, b in zip(pts, pts[1:]):
        d = sub(b, a)
        L = norm(d)
        if L == 0:
            continue
        lam = max(0.0, min(1.0, dot(sub(q, a), d) / (L * L)))
        c = add(a, mul(d, lam))
        dd = dist(q, c)
        if best is None or dd < best[0]:
            best = (dd, acc + lam * L, c, unit(d))
        acc += L
    if best is None:
        raise ValueError("빈 폴리라인")
    return best[1], best[2], best[3]


# ── 3차 베지어 (규칙 14) ─────────────────────────────────────────────────
def bezier3(p0: Pt, c0: Pt, c1: Pt, p1: Pt, n: int = 40) -> List[Pt]:
    pts = []
    for i in range(n + 1):
        t = i / n
        mt = 1 - t
        x = mt**3 * p0[0] + 3 * mt**2 * t * c0[0] + 3 * mt * t**2 * c1[0] + t**3 * p1[0]
        y = mt**3 * p0[1] + 3 * mt**2 * t * c0[1] + 3 * mt * t**2 * c1[1] + t**3 * p1[1]
        pts.append((x, y))
    return pts


def round_pts(pts: Iterable[Pt], nd: int = 1) -> List[List[float]]:
    return [[round(p[0], nd), round(p[1], nd)] for p in pts]

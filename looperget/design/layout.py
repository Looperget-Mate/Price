# -*- coding: utf-8 -*-
"""
looperget.design.layout — 폴리곤 + 가지관 방향 → 가지관 열·헤드 배치 (`rows_from_polygon`).

승인본 5필지가 쓴 배치 규칙을 **하나의 엔진 + 정책(RowPolicy)** 으로 일반화한 것이다.
원천: `_설계/배추밭스프링클러_20260824/10_계산/_계산_배치_숙진리.py` Block(04·05 — 이격 2D·말단 보충·건너뜀·각도 미세조정),
`03_482-42_상도리/_계산_배치_v4.py`(03 — 앵커 스윕·첫 헤드 여백 스윕), `10_계산/_계산_배치_사선.py`(01)·`_계산_배치.py`(02 — 열 방향 끝 여유만, 1 m 격자 스캔).

좌표계: 로컬 m. u = 가지관 방향 단위벡터(주배관 쪽 → 밭 안쪽). n = perp(u) = 열 정렬축(앵커 a = p·n).
규칙 번호는 `.claude/agents/design-system.md` 설계 규칙.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional, Sequence, Tuple

from . import geom as G

Pt = Tuple[float, float]

# 🔴 대표가 **검토로 뺀 헤드**를 다시 찾을 때 쓰는 허용 오차(m). P3 표의 헤드 간격 하한이 4 m 라
#    그 절반보다 작게 잡는다 — 옆 헤드를 잘못 빼면 안 된다.
DROP_TOL = 1.5
ADD_MIN_SEP = 2.0    # 이미 놓인 헤드와 이만큼(m) 안이면 같은 자리로 본다 — 두 번 놓지 않는다
ADD_FAR = 0.75       # 누른 자리가 가지관에서 열 간격의 이 배보다 멀면 붙일 열을 못 고른다


# ── 헤드 모델별 배치 기본값 (설계 규칙 20 · 대표 2026-09-04) ──
# 기본은 **프로필**이 정한다. RowPolicy의 데이터클래스 기본값(10/10/5)은 배추밭 5필지의 「농가 요청 조정값」이고
# 승인본 재현이 거기에 기대고 있어 바꾸지 않는다. P3 입력 UI는 for_head()로 기본을 제시하고 조정을 받는다.
HEAD_PROFILES: Dict[str, Dict] = {
    "427B": {
        # 배치 기본값 — RowPolicy 필드(for_head가 이 키만 골라 쓴다)
        "S": 14.0, "lat_gap": 14.0, "std": 7.0, "maxm": 8.0,
        # 물리 정본 — hydro_zone이 쓴다. 값의 출처는 매뉴얼과 대표 실증뿐이고 여기서 만들지 않는다.
        "p_bar": (2.0, 3.0),        # 설계 수압대(말단압 기준)
        "p_end": 2.5,               # 설계 말단압 = 대역 중앙 → 반경 12 m (규칙 20 기본 격자의 근거)
        "p_min": 1.5,               # 최소 보증 말단압 → 반경 10 m (배추밭 10 m 격자의 근거 · 대표 08-26)
        "nozzle_lpm": 1030 / 60,    # 매뉴얼 1030 L/h
        "nozzle_bar": 3.0,          # 그때의 압력(노즐 K 산출점)
        "r_ref": (1.5, 10.0),       # 대표 실증 기준점: 1.5 bar = 반경 10 m
        "r_slope": 2.0,             # bar당 +2 m (2.5 bar = 12 m)
        # 🔵 안쪽 원 = **귀환 살수 7 m(고정)**. 임팩트 헤드는 조절 반경(바깥) 안쪽으로도 물이 돌아온다 —
        #    승인 제안서가 이미 두 겹으로 그린다(`tools/agri_overlay.spray_double` r_in=7 · 대표 교정 2026-08-26).
        #    지도에도 같은 원을 얹는다(대표 요청 2026-09-08) — 지면과 화면이 다른 그림이면 안 된다.
        "r_in": 7.0,
        "note": "360° 기준 첫 헤드 7 m · 이후 14 m (2~3 bar · 반경 12 m)"},
}


@dataclass
class RowPolicy:
    """열·헤드 배치 정책. 기본값 = 04·05 승인본(Block)."""
    S: float = 10.0                 # 헤드 간격(살수 반경)
    lat_gap: float = 10.0           # 열 간격(직각)
    std: float = 5.0                # 첫 헤드 여백 기준
    maxm: float = 6.0               # 첫 헤드 여백 최대
    floor: float = 4.0              # 경계 이격 하한(격자 헤드)
    lat_max: int = 7                # 열당 최대 두수(25 mm 한계) — 대표 확정으로만 넘긴다
    mode: str = "edge2d"            # "edge2d"(경계 2D 이격 · 03·04·05) | "along_row"(열 방향 끝 여유만 · 01·02)
    # ── 열 앵커 ──
    anchor_from: str = "lo"         # 앵커 진행 방향: "lo" = a_lo+c 부터 증가 · "hi" = a_hi−c 부터 감소
    anchor_fixed: Optional[float] = None          # 첫 열 이격 고정(01 = 9 · 02 = 5). None = 스윕
    anchor_sweep: Tuple[float, float, float] = (4.0, 9.0, 0.05)   # (from, to, step) — 두수 최대 · 남북 이격 균등
    anchor_ref_pt: Optional[Pt] = None            # 앵커 기준점(None = 폴리곤 extent). 01 = 좌상 정점 O
    anchor_end_pt: Optional[Pt] = None            # 마지막 열 한계 기준점(None = 폴리곤 extent)
    anchor_end_margin: Optional[float] = None     # 마지막 열 한계 이격(None = floor)
    anchor_max: Optional[float] = None            # 앵커 오프셋 상한(01 원본 `while s <= 75`)
    # ── 첫 헤드 여백 ──
    off_fixed: Optional[float] = None             # 고정(01 = 7 · 02 = 8/5). None = 스윕 floor..maxm 0.25
    # ── edge2d 세부 ──
    start_ref: str = "polygon"      # "polygon" = 폴리곤 진입점부터 · "main" = max(진입점, 주배관 교점) (03)
    skip: bool = True               # 규칙 5: 이격 미달 자리는 건너뛰고 계속(True) · 거기서 열 끝(False = 03 v4)
    tail_fill: bool = True          # 규칙 11: 말단 보충 헤드
    tail_floor: float = 2.0
    tail_gap: float = 7.0
    tail_near: float = 8.0          # 두둑에서 이 안쪽만(bars 있을 때)
    refine: bool = True             # 두수 모자란 열만 ±swing 각도 미세조정(평행이 기본)
    swing: float = 25.0
    min_sep: float = 6.0            # 이웃 열과 최소 이격(각도 조정 시)
    ext: float = 3.0                # 마지막 헤드 뒤 호스 여유(경계 안에서 0.5 단위로 줄임)
    # ── along_row 세부 ──
    end_margin: float = 5.0         # 열 끝(반대 경계) 여유
    tail: float = 5.0               # 마지막 헤드 뒤 호스 여유(고정)
    scan_m: Optional[float] = 1.0   # 진입·이탈을 이 격자로 스캔(원본 range 스캔). None = 정확값
    scan_origin: Pt = (0.0, 0.0)    # 격자 원점(01 = O · 02 = (0,0))

    manual_rows: Optional[List[Dict]] = None     # 지도에서 확정한 열별 {a, deg}; 자동 재정렬하지 않음
    # 🔴 대표가 지도에서 **빼기로 한 헤드 자리**(로컬 m). 배치를 다시 풀지 않고 **그 자리만 뺀다** —
    #    남은 헤드를 다시 벌리면 대표가 보고 결정한 그림이 바뀐다(대표 요청 2026-09-08).
    #    한 열의 헤드를 전부 빼면 **그 가지관도 없어진다**(헤드 없는 호스는 깔지 않는다).
    drop_heads: Optional[List[Pt]] = None
    # 🔵 대표가 지도에서 **더 놓은 헤드**(로컬 m). 가장 가까운 가지관에 **투영해서** 붙인다 —
    #    가지관에 붙지 않은 헤드는 물을 못 받는다(대표 요청 2026-09-08).
    add_heads: Optional[List[Pt]] = None
    # 🔵 **열 안 균등 정렬** — 첫 헤드와 마지막 헤드를 **그대로 두고** 사이를 고르게 나눈다.
    #    규칙 11 말단 보충이 끝을 좁히면 「6번과 7번 사이만 좁다」가 된다(대표 2026-09-08).
    #    두수는 바뀌지 않는다 — **자리만 고르게** 한다.
    even_spacing: bool = False

    def to_dict(self) -> Dict:
        return asdict(self)

    @classmethod
    def for_head(cls, model: str = "427B", **override) -> "RowPolicy":
        """헤드 모델의 기본 격자에서 시작해 현장 조정(override)을 얹는다 — 규칙 20.
        예: for_head("427B") = 14/14/7 · for_head("427B", S=10, lat_gap=10, std=5) = 배추밭(농가 요청)."""
        prof = {k: v for k, v in HEAD_PROFILES[model].items() if k in cls.__dataclass_fields__}
        prof.update(override)
        return cls(**prof)


@dataclass
class Row:
    a: float
    p0: Pt                          # 열 시작(폴리곤 진입점 또는 주배관 교점) — 탭점은 branch가 정한다
    p1: Pt                          # 호스 끝
    dir: Pt                         # 열 방향(각도 조정 반영)
    heads: List[Pt]
    off: float
    deg: float
    len: float                      # 호스 길이(p0→p1)

    def to_dict(self) -> Dict:
        return {"a": round(self.a, 2), "p0": [round(self.p0[0], 1), round(self.p0[1], 1)],
                "p1": [round(self.p1[0], 1), round(self.p1[1], 1)],
                "dir": [round(self.dir[0], 4), round(self.dir[1], 4)],
                "heads": [[round(h[0], 1), round(h[1], 1)] for h in self.heads],
                "off": round(self.off, 2), "deg": round(self.deg, 1), "len": round(self.len, 1),
                "n_heads": len(self.heads)}


class Block:
    """한 블록(폴리곤 1개)의 열 배치. `_계산_배치_숙진리.py` Block의 이식 + 정책화."""

    def __init__(self, poly: Sequence[Pt], u: Pt, policy: RowPolicy,
                 bars: Optional[Sequence[Tuple[Pt, Pt]]] = None,
                 mains: Optional[Sequence[Sequence[Pt]]] = None):
        self.poly = [tuple(p) for p in poly]
        self.u = G.unit(tuple(u))
        self.n = G.perp(self.u)
        self.P = policy
        self.bars = [(tuple(a), tuple(b)) for a, b in (bars or [])]
        self.mains = [[tuple(p) for p in m] for m in (mains or [])]
        self.rows: List[Row] = []

    # ── 좌표 ──
    def to_as(self, p: Pt) -> Tuple[float, float]:
        return (G.dot(p, self.n), G.dot(p, self.u))

    def to_xy(self, a: float, s: float) -> Pt:
        return (a * self.n[0] + s * self.u[0], a * self.n[1] + s * self.u[1])

    def cross(self, a: float) -> List[float]:
        """앵커 a 열 직선과 폴리곤 변의 교점 s(오름차순)."""
        out = []
        n = len(self.poly)
        for i in range(n):
            p, q = self.poly[i], self.poly[(i + 1) % n]
            ap, aq = self.to_as(p)[0], self.to_as(q)[0]
            if (ap > a) == (aq > a):
                continue
            t = (a - ap) / (aq - ap)
            pt = (p[0] + t * (q[0] - p[0]), p[1] + t * (q[1] - p[1]))
            out.append(self.to_as(pt)[1])
        return sorted(out)

    def main_cross(self, a: float) -> List[float]:
        """앵커 a 열 직선과 주배관 폴리라인들의 교점 s."""
        out = []
        for m in self.mains:
            for p, q in zip(m, m[1:]):
                ap, aq = self.to_as(p)[0], self.to_as(q)[0]
                if (ap > a) == (aq > a):
                    continue
                t = (a - ap) / (aq - ap)
                pt = (p[0] + t * (q[0] - p[0]), p[1] + t * (q[1] - p[1]))
                out.append(self.to_as(pt)[1])
        return sorted(out)

    def inside(self, p: Pt) -> bool:
        return G.contains(self.poly, p)

    def edge_dist(self, p: Pt) -> float:
        return G.edge_dist(p, self.poly)

    def tail_ok(self, p: Pt) -> bool:
        """말단 보충 헤드는 두둑(대표 작도 바)에서 tail_near 안쪽일 때만 (규칙 11)."""
        if not self.bars:
            return True
        return min(G.seg_dist(p, a, b) for a, b in self.bars) <= self.P.tail_near

    # ── 열 하나 ──
    def row(self, a: float, swing: float = None, placed: Optional[List[Row]] = None,
            angle_fixed: Optional[float] = None) -> Optional[Row]:
        P = self.P
        if P.mode == "along_row":
            return self._row_along(a)
        swing = P.swing if swing is None else swing
        xs = self.cross(a)
        if len(xs) < 2:
            return None
        s_lo, s_hi = xs[0], xs[-1]
        if P.start_ref == "main":
            mx = [s for s in self.main_cross(a) if s < s_hi]
            s0 = max(s_lo, max(mx)) if mx else s_lo
        else:
            s0 = s_lo
        p0 = self.to_xy(a, s0)
        best = None
        deg = -swing if angle_fixed is None else angle_fixed
        deg_end = swing if angle_fixed is None else angle_fixed
        while deg <= deg_end + 1e-9:
            t = math.radians(deg)
            ux = self.u[0] * math.cos(t) - self.u[1] * math.sin(t)
            uy = self.u[0] * math.sin(t) + self.u[1] * math.cos(t)
            offs = [P.off_fixed] if P.off_fixed is not None else _frange(P.floor, P.maxm, 0.25)
            for o in offs:
                hs: List[Pt] = []
                k = 0
                while True:
                    d = o + P.S * k
                    if d > 120:
                        break
                    p = (p0[0] + ux * d, p0[1] + uy * d)
                    if self.inside(p):
                        if self.edge_dist(p) >= P.floor:
                            hs.append((round(p[0], 1), round(p[1], 1)))
                        elif hs and not P.skip:
                            break                   # 03 v4: 이격 미달이면 열 끝
                        # 규칙 5(skip): 이격 미달 자리는 구멍으로 두고 계속
                    elif hs:
                        break                       # 폴리곤 밖 = 열 끝
                    k += 1
                    if k > 14:
                        break
                # 규칙 11 말단 보충 헤드
                if P.tail_fill and hs and len(hs) < P.lat_max:
                    last_t = G.dist(p0, hs[-1])
                    t_max = None
                    tt = last_t + P.tail_gap
                    while tt <= last_t + P.S + 1e-9:
                        q = (p0[0] + ux * tt, p0[1] + uy * tt)
                        if self.inside(q) and self.edge_dist(q) >= P.tail_floor and self.tail_ok(q):
                            t_max = tt
                        tt += 0.1
                    if t_max is not None:
                        q = (p0[0] + ux * t_max, p0[1] + uy * t_max)
                        hs.append((round(q[0], 1), round(q[1], 1)))
                hs = hs[:P.lat_max]
                if hs and placed:
                    last_d = G.dist(p0, hs[-1]) + 3.0
                    q1 = (p0[0] + ux * last_d, p0[1] + uy * last_d)
                    if any(G.seg_seg_dist(p0, q1, r.p0, r.p1) < P.min_sep for r in placed):
                        continue
                if hs:
                    sc = (len(hs), -abs(deg), -abs(o - P.std))
                    if best is None or sc > best[0]:
                        best = (sc, deg, o, hs, (ux, uy))
            deg += 1.0
        if best is None:
            return None
        _, deg, off, hs, uu = best
        p1, hose = self._hose_end(p0, uu, G.dist(p0, hs[-1]))
        return Row(a=a, p0=p0, p1=p1, dir=uu, heads=list(hs), off=off, deg=deg, len=hose)

    def _hose_end(self, p0: Pt, uu: Pt, last: float) -> Tuple[Pt, float]:
        """마지막 헤드 뒤 호스 여유(ext)를 경계 안에서 0.5 m씩 줄여 호스 끝과 길이를 정한다."""
        ext = self.P.ext
        while ext > 0 and not self.inside((p0[0] + uu[0] * (last + ext), p0[1] + uu[1] * (last + ext))):
            ext -= 0.5
        return (p0[0] + uu[0] * (last + ext), p0[1] + uu[1] * (last + ext)), round(last + ext, 1)

    def _row_along(self, a: float) -> Optional[Row]:
        """01·02 방식: 열 방향의 진입·이탈만 보고(경계 2D 이격 없음) 첫 헤드 여백 + 끝 여유."""
        P = self.P
        xs = self.cross(a)
        if len(xs) < 2:
            return None
        s_in, s_out = xs[0], xs[-1]
        if P.scan_m:
            t0 = G.dot(P.scan_origin, self.u)
            g = P.scan_m
            entry = t0 + math.ceil((s_in - t0) / g - 1e-9) * g
            exit_ = t0 + math.floor((s_out - t0) / g + 1e-9) * g
        else:
            entry, exit_ = s_in, s_out
        if exit_ - entry < P.S:
            return None
        off = P.off_fixed if P.off_fixed is not None else P.std
        a0, b0 = entry + off, exit_ - P.end_margin
        if b0 < a0:
            return None
        k = int((b0 - a0) // P.S) + 1
        k = min(k, P.lat_max)
        p0 = self.to_xy(a, entry)
        hs = [self.to_xy(a, a0 + i * P.S) for i in range(k)]
        hs = [(round(h[0], 1), round(h[1], 1)) for h in hs]
        L = off + (k - 1) * P.S + P.tail
        p1 = self.to_xy(a, entry + L)
        return Row(a=a, p0=p0, p1=p1, dir=self.u, heads=hs, off=off, deg=0.0, len=round(L, 1))

    # ── 열 앵커 ──
    def _anchor_bounds(self) -> Tuple[float, float]:
        av = [self.to_as(p)[0] for p in self.poly]
        a_lo, a_hi = min(av), max(av)
        P = self.P
        if P.anchor_ref_pt is not None:
            ref = self.to_as(tuple(P.anchor_ref_pt))[0]
            if P.anchor_from == "lo":
                a_lo = ref
            else:
                a_hi = ref
        if P.anchor_end_pt is not None:
            end = self.to_as(tuple(P.anchor_end_pt))[0]
            if P.anchor_from == "lo":
                a_hi = end
            else:
                a_lo = end
        return a_lo, a_hi

    def _anchors(self, c: float) -> List[float]:
        P = self.P
        a_lo, a_hi = self._anchor_bounds()
        em = P.floor if P.anchor_end_margin is None else P.anchor_end_margin
        out = []
        i = 0
        while True:
            off = c + P.lat_gap * i
            if P.anchor_max is not None and off > P.anchor_max + 1e-9:
                break
            a = a_lo + off if P.anchor_from == "lo" else a_hi - off
            if P.anchor_from == "lo" and a > a_hi - em + 1e-9:
                break
            if P.anchor_from == "hi" and a < a_lo + em - 1e-9:
                break
            out.append(a)
            i += 1
        return out

    def drop(self) -> "Block":
        """대표가 검토로 뺀 헤드를 배치에서 덜어낸다(`RowPolicy.drop_heads`).

        🔴 **배치를 다시 풀지 않는다.** 빼면 그 자리만 빈다 — 남은 헤드를 다시 벌리면
          대표가 지도에서 보고 결정한 그림이 바뀐다. 호스 끝(`p1`·`len`)만 다시 잡는다.
        """
        pts = [(float(q[0]), float(q[1])) for q in (self.P.drop_heads or [])
               if q is not None and len(q) >= 2]
        if not pts:
            return self
        kept: List[Row] = []
        for r in self.rows:
            hs = [h for h in r.heads if min(G.dist(h, q) for q in pts) > DROP_TOL]
            if len(hs) == len(r.heads):
                kept.append(r)
                continue
            if not hs:
                continue                       # 열의 헤드를 전부 빼면 그 가지관도 없어진다
            r.heads = hs
            last = G.dist(r.p0, hs[-1])
            if self.P.mode == "along_row":     # 01·02 방식은 마지막 헤드 뒤 여유가 고정이다
                hose = last + self.P.tail
                r.p1 = (r.p0[0] + r.dir[0] * hose, r.p0[1] + r.dir[1] * hose)
                r.len = round(hose, 1)
            else:
                r.p1, r.len = self._hose_end(r.p0, r.dir, last)
            kept.append(r)
        self.rows = kept
        return self

    def add(self) -> "Block":
        """대표가 지도에서 더 놓은 헤드(`RowPolicy.add_heads`)를 **가장 가까운 가지관에 투영해** 넣는다.

        🔴 가지관에 붙지 않은 헤드는 물을 못 받는다 — 그래서 누른 자리를 그대로 쓰지 않고
          그 열의 축 위로 옮긴다. 넣을 열을 못 고르면 그 점은 버린다(경고는 화면이 낸다).
        """
        pts = [(float(q[0]), float(q[1])) for q in (self.P.add_heads or [])
               if q is not None and len(q) >= 2]
        if not pts or not self.rows:
            return self
        far = max(self.P.lat_gap * ADD_FAR, 3.0)
        for q in pts:
            best = None
            for r in self.rows:
                t = G.dot(G.sub(q, r.p0), r.dir)              # 열 방향 거리
                if t <= 0:
                    continue                                  # 주배관 뒤쪽에는 놓지 않는다
                foot = (r.p0[0] + r.dir[0] * t, r.p0[1] + r.dir[1] * t)
                d = G.dist(q, foot)
                if d <= far and (best is None or d < best[0]):
                    best = (d, r, t, foot)
            if best is None:
                continue
            _, r, t, foot = best
            h = (round(foot[0], 1), round(foot[1], 1))
            if not self.inside(h) or self.edge_dist(h) < self.P.tail_floor:
                continue                                      # 밭 밖·경계에 너무 붙은 자리
            if any(G.dist(h, x) <= ADD_MIN_SEP for x in r.heads):
                continue                                      # 이미 그 자리에 있다
            hs = sorted(r.heads + [h], key=lambda x: G.dot(G.sub(x, r.p0), r.dir))
            r.heads = hs
            last = G.dist(r.p0, hs[-1])
            if self.P.mode == "along_row":
                hose = last + self.P.tail
                r.p1 = (r.p0[0] + r.dir[0] * hose, r.p0[1] + r.dir[1] * hose)
                r.len = round(hose, 1)
            else:
                r.p1, r.len = self._hose_end(r.p0, r.dir, last)
        return self

    def even(self) -> "Block":
        """열 안 헤드를 **고르게** 놓는다 — 첫·마지막은 그대로, 사이를 같은 간격으로(`even_spacing`).

        규칙 11 말단 보충 헤드가 끝을 좁히면 「6번과 7번 사이만 좁다」가 된다(대표 2026-09-08).
        🔴 **두수는 바뀌지 않는다.** 자리만 고른다. 옮긴 자리가 밭 밖이거나 경계에 너무 붙으면
          그 열은 **손대지 않는다** — 고르게 만들자고 밭을 벗어날 수는 없다.
        """
        if not self.P.even_spacing:
            return self
        for r in self.rows:
            n = len(r.heads)
            if n < 3:
                continue                                      # 사이가 없으면 고를 것도 없다
            a, b = r.heads[0], r.heads[-1]
            L = G.dist(a, b)
            if L <= 0:
                continue
            u = ((b[0] - a[0]) / L, (b[1] - a[1]) / L)
            gap = L / (n - 1)
            hs = [a] + [(round(a[0] + u[0] * gap * k, 1), round(a[1] + u[1] * gap * k, 1))
                        for k in range(1, n - 1)] + [b]
            if all(self.inside(h) and self.edge_dist(h) >= self.P.tail_floor for h in hs):
                r.heads = hs
        return self

    def solve(self) -> "Block":
        P = self.P
        if P.manual_rows is not None:
            self.rows = []
            for spec in P.manual_rows:
                a, deg = float(spec["a"]), float(spec.get("deg", 0))
                if not math.isfinite(a) or not math.isfinite(deg):
                    raise ValueError("가지관 위치·각도는 유한한 숫자여야 합니다")
                row = self.row(a, angle_fixed=deg)
                if row is None:
                    raise ValueError("옮긴 가지관에 헤드를 놓을 수 없습니다. 밭 안쪽으로 옮겨 주세요.")
                self.rows.append(row)
            return self.drop().add().even()
        cs = [P.anchor_fixed] if P.anchor_fixed is not None else _frange(*P.anchor_sweep)
        best = None
        for c in cs:
            rows = []
            for a in self._anchors(c):
                r = self.row(a, swing=0.0)
                if r:
                    rows.append(r)
            if rows:
                n = sum(len(r.heads) for r in rows)
                a_lo, a_hi = self._anchor_bounds()
                c2 = (a_hi - rows[-1].a) if P.anchor_from == "lo" else (rows[-1].a - a_lo)
                sc = (n, -abs(c - c2))
                if best is None or sc > best[0]:
                    best = (sc, c, c2, rows)
        if best is None:
            self.rows = []
            return self
        _, self.c1, self.c2, self.rows = best
        if P.refine and P.mode == "edge2d":
            self.refine()
        return self.drop().add().even()

    def refine(self, rounds: int = 2) -> "Block":
        """평행이 기본. 두수가 모자란 열부터 ±swing 각도를 훑어 더 들어가면 바꾼다(이웃 이격 min_sep)."""
        for _ in range(rounds):
            changed = False
            order = sorted(range(len(self.rows)), key=lambda i: len(self.rows[i].heads))
            for i in order:
                others = [r for j, r in enumerate(self.rows) if j != i]
                cur = self.rows[i]
                cand = self.row(cur.a, placed=others)
                if cand and len(cand.heads) > len(cur.heads):
                    self.rows[i] = cand
                    changed = True
            if not changed:
                break
        return self


def rows_from_polygon(poly: Sequence[Pt], u: Pt, policy: Optional[RowPolicy] = None,
                      bars: Optional[Sequence[Tuple[Pt, Pt]]] = None,
                      mains: Optional[Sequence[Sequence[Pt]]] = None) -> List[Row]:
    """폴리곤 + 가지관 방향 u(주배관 쪽 → 밭 안쪽) → 열 목록(주배관 쪽부터 순서대로)."""
    b = Block(poly, u, policy or RowPolicy(), bars=bars, mains=mains).solve()
    return b.rows


def _frange(a: float, b: float, step: float) -> List[float]:
    out = []
    x = a
    while x <= b + 1e-9:
        out.append(round(x, 6))
        x += step
    return out

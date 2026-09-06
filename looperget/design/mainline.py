# -*- coding: utf-8 -*-
"""
looperget.design.mainline — 주배관(40/50 mm 송수호스) 경로의 물량·연결부 산정.

경로 자체는 **대표 판단(규칙 13)** 이다 — 대표가 그린 폴리라인을 그대로 받아 길이·롤 수·T·말단·이음 수를 센다.
규칙 1(말단 = E호스밸브 마감세트) · 2(변형엘보 금지, 잇는 자리만 일자연결) · 3(45° 초과는 T 양쪽) 코드화.
경로 제안(규칙 3 자동 경로)은 P1 범위 밖 — `propose()`는 자리만 둔다.
"""
from __future__ import annotations

import math
from typing import Dict, List, Optional, Sequence, Tuple

from . import geom as G

Pt = Tuple[float, float]

ROLL_M = 50.0          # 40/50 mm 송수호스 1롤
SOURCE_NEAR = 4.0      # 같은 급수점에서 출발하는 경로들로 볼 거리(m)
END_NEAR = 2.0         # 다른 경로의 끝점에서 출발하면 그 끝점의 T
MID_NEAR = 2.0         # 다른 경로 중간에서 출발하면 그 자리의 T
ELBOW_DEG = 45.0       # 규칙 2·3: 45° 이내 현장 굽힘, 초과는 T 양쪽
TEE_NEAR = 2.0         # 꺾임점이 이 거리 안의 T와 같은 자리면 규칙 3(T 양쪽)이 이미 선 것으로 본다


def _bends(pts: Sequence[Pt]) -> List[Tuple[Pt, float]]:
    """폴리라인의 꺾임점과 편향각(도)."""
    out = []
    for a, b, c in zip(pts, pts[1:], pts[2:]):
        u1, u2 = G.sub(b, a), G.sub(c, b)
        if G.norm(u1) == 0 or G.norm(u2) == 0:
            continue
        out.append((b, G.angle_between_deg(u1, u2)))
    return out


def analyze(routes: Sequence[Dict], sources: Sequence[Dict]) -> Dict:
    """routes = [{"name","zone","pts"}], sources = [{"name","pt","tees_here"?}]
    → {"total_m","rolls","tees","ends","joints","elbows_over45","bends_at_tee","routes":[...],
       "tee_pts","end_pts","warnings"}"""
    R = [dict(r, pts=[tuple(p) for p in r["pts"]]) for r in routes]
    for r in R:
        r["len"] = G.polyline_len(r["pts"])
        r["joints"] = max(0, math.ceil(r["len"] / ROLL_M) - 1)        # 50 m 롤이 모자라 잇는 자리
        r["bends"] = _bends(r["pts"])
        r["over45"] = [b for b in r["bends"] if b[1] > ELBOW_DEG]
    total = sum(r["len"] for r in R)
    warnings: List[str] = []

    # ── 출발점 분류: 급수점 클러스터 / 다른 경로 끝 / 다른 경로 중간 ─────────
    tee_pts: List[Tuple[Pt, str]] = []
    src_groups: Dict[int, List[int]] = {}
    end_groups: Dict[int, List[int]] = {}
    for i, r in enumerate(R):
        p = r["pts"][0]
        near = [(G.dist(p, tuple(s["pt"])), k) for k, s in enumerate(sources)]
        dmin, si = min(near) if near else (None, None)
        if si is not None and dmin <= SOURCE_NEAR:
            src_groups.setdefault(si, []).append(i)
            r["from"] = ("source", si)
            continue
        ej = next((j for j, q in enumerate(R) if j != i and G.dist(p, q["pts"][-1]) <= END_NEAR), None)
        if ej is not None:
            end_groups.setdefault(ej, []).append(i)
            r["from"] = ("end", ej)
            continue
        mj = None
        for j, q in enumerate(R):
            if j == i:
                continue
            s, c, _ = G.nearest_on_polyline(q["pts"], p)
            if G.dist(c, p) <= MID_NEAR and s > END_NEAR and s < q["len"] - END_NEAR:
                mj = (j, s, c)
                break
        if mj is not None:
            r["from"] = ("mid", mj[0])
            tee_pts.append((mj[2], "분기 T"))
            continue
        r["from"] = ("free", None)
        warnings.append(f"주배관 '{r['name']}' 출발점 {p} 이 급수점·다른 경로에 닿지 않음")

    tees = 0
    for si, idx in src_groups.items():
        th = sources[si].get("tees_here")
        k = len(idx)
        n = th if th is not None else max(0, k - 1)
        tees += n
        if n:
            tee_pts.append((tuple(sources[si]["pt"]), f"급수점 T×{n}"))
    for ej, idx in end_groups.items():
        k = len(idx)
        n = max(0, k - 1)
        tees += n
        if n:
            tee_pts.append((R[ej]["pts"][-1], f"경로 끝 T×{n}"))
    tees += sum(1 for r in R if r["from"][0] == "mid")

    # 규칙 3 — T가 이미 놓인 자리의 꺾임은 「T 양쪽」으로 풀린 것이다. 경고에서 뺀다.
    # T 자리 = 기록된 T(급수점·경로 끝·분기) + **다른 경로가 갈라져 나가거나 들어오는 마디**.
    # (05 숙진리 154° = 갈래2가 갈라지는 (222.4, 100.2). 급수점 T는 마커가 급수점에 찍혀
    #  실제 분기 자리와 3 m 떨어져 있으므로 마디로 함께 본다.)
    for i, r in enumerate(R):
        nodes = [t for t, _ in tee_pts]
        nodes += [q["pts"][k] for j, q in enumerate(R) if j != i for k in (0, -1)]
        r["elbows_over45"], r["bends_at_tee"] = [], []
        for b in r["over45"]:
            at_tee = any(G.dist(b[0], t) <= TEE_NEAR for t in nodes)
            (r["bends_at_tee"] if at_tee else r["elbows_over45"]).append(b)

    # 말단 = 다른 경로가 이어 받지 않는 끝점 (규칙 1)
    end_pts = []
    for j, r in enumerate(R):
        if j in end_groups:
            continue
        end_pts.append(r["pts"][-1])
    ends = len(end_pts)
    joints = sum(r["joints"] for r in R)
    elbows = sum(len(r["elbows_over45"]) for r in R)
    at_tee_n = sum(len(r["bends_at_tee"]) for r in R)
    for r in R:
        for p, d in r["elbows_over45"]:
            warnings.append(f"'{r['name']}' 꺾임 {d:.0f}° > 45° @ {tuple(round(x, 1) for x in p)} — 규칙 3(T 양쪽) 검토")

    return {
        "total_m": round(total, 1),
        "rolls": math.ceil(total / ROLL_M),
        "tees": tees, "ends": ends, "joints": joints, "elbows_over45": elbows,
        "bends_at_tee": at_tee_n,
        "routes": [{"name": r["name"], "zone": r.get("zone"), "len_m": round(r["len"], 1),
                    "joints": r["joints"], "from": r["from"][0],
                    "bends": [[list(p), round(d, 1)] for p, d in r["bends"]]} for r in R],
        "tee_pts": [[list(p), tag] for p, tag in tee_pts],
        "end_pts": [list(p) for p in end_pts],
        "warnings": warnings,
    }


def propose(*_a, **_k):
    """규칙 3 자동 경로 제안 — P1 범위 밖. 경로가 없으면 설계를 진행하지 않는다(불변 원칙 1)."""
    raise NotImplementedError("주배관 경로는 대표 입력(규칙 13). 자동 제안은 P2 이후.")

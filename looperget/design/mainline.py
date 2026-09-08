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
HEADER_NEAR = 2.0      # 규칙 21 F3 — 주배관 출발점끼리 이 거리 안이면 **한 분배점**(매니폴드 세트 · 부속만).
                       # 넘으면 분배점을 나누고 그 사이는 인입관이다. 대표 확정 2026-09-08(#79) — T 합침 거리와 같게 시작.


def headers(routes: Sequence[Dict], near: float = HEADER_NEAR) -> List[Dict]:
    """분배점(규칙 21) — 주배관(role=main)의 출발점을 `near` 안에서 묶은 자리.

    → [{"pt", "routes": [이름], "zones": [구역], "outlets": 주배관 수, "valves": 구역 수}]
    구역 밸브는 **분배점마다 구역 수**만큼이다 — 같은 구역의 두 갈래는 밸브 하나 뒤에서 T 로 갈라진다
    (승인본 02: 한 입구에서 두 갈래 · 구역 1 · 밸브 1)."""
    from .site import route_role
    mains = [(i, r) for i, r in enumerate(routes) if route_role(r) == "main" and len(r.get("pts") or []) >= 2]
    parent = list(range(len(mains)))

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    pts = [tuple(r["pts"][0]) for _, r in mains]
    for a in range(len(mains)):
        for b in range(a + 1, len(mains)):
            if G.dist(pts[a], pts[b]) <= near:
                parent[find(a)] = find(b)
    groups: Dict[int, List[int]] = {}
    for a in range(len(mains)):
        groups.setdefault(find(a), []).append(a)
    out = []
    for idx in sorted(groups.values(), key=lambda g: min(g)):
        rs = [mains[k][1] for k in idx]
        cx = sum(pts[k][0] for k in idx) / len(idx)
        cy = sum(pts[k][1] for k in idx) / len(idx)
        zones = []
        for r in rs:
            if r.get("zone") not in zones:
                zones.append(r.get("zone"))
        out.append({"pt": [round(cx, 1), round(cy, 1)], "routes": [r["name"] for r in rs],
                    "zones": zones, "outlets": len(rs), "valves": len(zones)})
    return out


def header_valves(routes: Sequence[Dict], near: float = HEADER_NEAR) -> int:
    """구역 밸브 수 파생값 = Σ 분배점의 구역 수(규칙 21 · #79). 대표 입력이 있으면 bom 이 그것을 우선한다."""
    return sum(h["valves"] for h in headers(routes, near))


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
    from .site import route_role, feeder_d_mm, FEEDER_HOSE_NOMINAL
    R = [dict(r, pts=[tuple(p) for p in r["pts"]]) for r in routes]
    for r in R:
        r["role"] = route_role(r)
        r["material"] = (r.get("material") or "hose50") if r["role"] == "feeder" else None
        r["len"] = G.polyline_len(r["pts"])
        # 롤 이음은 송수호스에만 — 파이프·매설 인입관은 우리가 파는 자재가 아니다(규칙 7 계통도).
        r["is_hose"] = r["role"] == "main" or r["material"] in FEEDER_HOSE_NOMINAL
        r["joints"] = max(0, math.ceil(r["len"] / ROLL_M) - 1) if r["is_hose"] else 0
        r["bends"] = _bends(r["pts"])
        r["over45"] = [b for b in r["bends"] if b[1] > ELBOW_DEG]
    # 규칙 21 — 주배관과 **호스 인입관**만 송수호스 물량이다. 파이프·매설 인입관은 길이만 따로 적는다.
    main_m = sum(r["len"] for r in R if r["role"] == "main")
    feeder_m = sum(r["len"] for r in R if r["role"] == "feeder")
    feeder_hose_m: Dict[int, float] = {}
    feeder_other_m = 0.0
    for r in R:
        if r["role"] != "feeder":
            continue
        if r["is_hose"]:
            n = FEEDER_HOSE_NOMINAL[r["material"]]
            feeder_hose_m[n] = feeder_hose_m.get(n, 0.0) + r["len"]
        else:
            feeder_other_m += r["len"]
    total = main_m + sum(feeder_hose_m.values())
    warnings: List[str] = []
    if not any(r["role"] == "main" for r in R):
        warnings.append("주배관(role=main)이 하나도 없다 — 전부 인입관이면 가지관을 낼 곳이 없다(규칙 21)")

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

    hdrs = headers(routes)

    def _from_ref(r):
        """출발점이 닿은 상대의 이름 — 급수점 이름 또는 다른 경로 이름(화면 「🔗 연결」용 · V100)."""
        kind, v = r["from"]
        if kind == "source":
            return sources[v].get("name")
        if kind in ("end", "mid"):
            return R[v]["name"]
        return None

    return {
        "total_m": round(total, 1),                      # 송수호스 길이 = 주배관 + 호스 인입관
        "rolls": math.ceil(total / ROLL_M),
        "main_m": round(main_m, 1), "feeder_m": round(feeder_m, 1),          # 규칙 21
        "feeder_hose_m": {k: round(v, 1) for k, v in feeder_hose_m.items()},
        "feeder_other_m": round(feeder_other_m, 1),
        "headers": hdrs, "header_valves": sum(h["valves"] for h in hdrs),
        "tees": tees, "ends": ends, "joints": joints, "elbows_over45": elbows,
        "bends_at_tee": at_tee_n,
        "routes": [{"name": r["name"], "role": r["role"], "zone": r.get("zone"),
                    "material": r["material"],
                    "d_mm": (feeder_d_mm(r) if r["role"] == "feeder" else None),   # 계산 내경(규칙 21)
                    "len_m": round(r["len"], 1),
                    "joints": r["joints"], "from": r["from"][0], "from_ref": _from_ref(r),
                    "bends": [[list(p), round(d, 1)] for p, d in r["bends"]]} for r in R],
        "tee_pts": [[list(p), tag] for p, tag in tee_pts],
        "end_pts": [list(p) for p in end_pts],
        "warnings": warnings,
    }


def propose(*_a, **_k):
    """규칙 3 자동 경로 제안 — P1 범위 밖. 경로가 없으면 설계를 진행하지 않는다(불변 원칙 1)."""
    raise NotImplementedError("주배관 경로는 대표 입력(규칙 13). 자동 제안은 P2 이후.")

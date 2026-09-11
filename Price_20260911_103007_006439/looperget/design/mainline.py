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


def headers(routes: Sequence[Dict], near: float = HEADER_NEAR, feed: Optional[Dict] = None) -> List[Dict]:
    """분배점(규칙 21) — 주배관(role=main)이 **물을 받는 자리**를 `near` 안에서 묶은 자리.

    → [{"pt", "routes": [이름], "zones": [구역], "outlets": 주배관 수, "valves": 구역 수}]
    구역 밸브는 **분배점마다 구역 수**만큼이다 — 같은 구역의 두 갈래는 밸브 하나 뒤에서 T 로 갈라진다
    (승인본 02: 한 입구에서 두 갈래 · 구역 1 · 밸브 1).

    🔵 [V103] 받는 자리는 보통 그 관의 **첫 점**이지만, 인입관이 주배관 **중간**에 T 로 붙거나
      주배관을 접점 쪽으로 그려 **끝점**이 만나면 첫 점이 아니다(대표 2026-09-08).
      그 경우 `analyze()` 가 `feed`(경로 index → 좌표)로 실제 자리를 알려 준다."""
    from .site import route_role
    mains = [(i, r) for i, r in enumerate(routes) if route_role(r) == "main" and len(r.get("pts") or []) >= 2]
    parent = list(range(len(mains)))

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    feed = feed or {}
    pts = [tuple(feed.get(i, r["pts"][0])) for i, r in mains]
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


HOSE_MATERIALS = ("hose50", "hose40")     # 우리 송수호스 — 호스밴드로 문다


def is_hose(r: Dict) -> bool:
    """그 관이 **우리 송수호스**인가. 안 적었으면 송수호스 50(지금까지의 기본)."""
    return (r.get("material") or "hose50") in HOSE_MATERIALS


JOINT_KIND = {"straight": "일자", "elbow": "엘보", "tee": "T", "end": "말단", "source": "급수원"}


def _arm_dir(pts: Sequence[Pt], which: int) -> Pt:
    """관의 끝에서 **접점을 등지고 나가는** 방향(단위벡터). which = 0(첫 점) · -1(끝점)."""
    a, b = (pts[0], pts[1]) if which == 0 else (pts[-1], pts[-2])
    return G.unit(G.sub(b, a))


def junctions(routes: Sequence[Dict], sources: Sequence[Dict],
              analysis: Optional[Dict] = None, near: float = TEE_NEAR) -> List[Dict]:
    """**관이 만나는 자리마다 어떻게 잇는지**를 읽는다(대표 2026-09-09).

    대표 말 — 「**일자**로 연결할 수도 있고, **엘보**로 연결할 수도 있고, **티자**로 연결할 수도 있어.
    티자의 경우, 좌우로 나뉘는 것이 **구역을 안 나누고도 가동이 가능하면 밸브가 필요없고**,
    좌우 각각 **구역을 나눠서 관수를 해야 한다면 좌우에 밸브** 부속으로 나가면 되겠지.」

    판정 —
      · 모인 관 끝이 **1개** → 말단(규칙 1 마감세트) · 급수원이 같이 있으면 급수원 인터페이스
      · **2개** → 꺾임각 ≤ 45° 면 **일자**(호스는 현장 굽힘 · 규칙 2), 넘으면 **엘보**
        🔴 규칙 2 는 **호스** 꺾임에 대한 것이다. 나사·조임식으로 조립되는 **파이프** 자리의 엘보는
           규칙 7(대표 계통도)이 우선한다 — 그래서 재질을 함께 낸다.
        🔴 호스가 45° 를 넘으면 규칙 3 이 「T 양쪽」으로 풀라고 한다 — `rule3` 로 표시한다.
      · **3개 이상** → **T**
    밸브 — 그 자리에서 물을 받는 **주배관들의 서로 다른 구역 수**(규칙 21). 좌우가 같은 구역이면 1,
           좌우를 따로 여닫아야 하면 2. 대표 말과 같은 규칙이다.

    → [{"pt","kind","arms","ends","dev_deg","materials","mixed","zones","valves","routes","rule3","source"}]
    """
    from .site import route_role
    an = analysis or analyze(routes, sources)
    R = [dict(r, pts=[tuple(q) for q in r["pts"]]) for r in routes]
    feed = {}
    for i, rr in enumerate(an["routes"]):
        if rr.get("feed_pt"):
            feed[i] = tuple(rr["feed_pt"])
        elif rr["from"] == "source":
            feed[i] = tuple(R[i]["pts"][0])
        elif rr["from"] in ("end", "mid"):
            feed[i] = tuple(R[i]["pts"][0])

    arms = []
    for i, r in enumerate(R):
        if len(r["pts"]) < 2:
            continue
        for which in (0, -1):
            arms.append({"i": i, "which": which, "pt": r["pts"][which],
                         "dir": _arm_dir(r["pts"], which), "through": False})
    # 접점 묶기 — 가까운 관 끝끼리 한 자리로 본다
    groups: List[List[Dict]] = []
    for a in arms:
        for g in groups:
            if G.dist(a["pt"], g[0]["pt"]) <= near:
                g.append(a)
                break
        else:
            groups.append([a])

    out: List[Dict] = []
    for g in groups:
        cx = sum(a["pt"][0] for a in g) / len(g)
        cy = sum(a["pt"][1] for a in g) / len(g)
        pt = (round(cx, 1), round(cy, 1))
        legs = list(g)
        # 그 자리를 **지나가는** 관(끝이 아니라 몸통으로)은 팔 2개를 더한다 — 세 갈래가 된다
        for i, r in enumerate(R):
            if any(a["i"] == i for a in g):
                continue
            sj, cj, _ = G.nearest_on_polyline(r["pts"], pt)
            if G.dist(cj, pt) <= near and END_NEAR < sj < an["routes"][i]["len_m"] - END_NEAR:
                legs.append({"i": i, "which": None, "pt": pt, "dir": None, "through": True})
                legs.append({"i": i, "which": None, "pt": pt, "dir": None, "through": True})
        src = next((x for x in sources if G.dist(pt, tuple(x["pt"])) <= SOURCE_NEAR), None)
        ends = len(legs)
        dev = None
        rule3 = False
        if ends == 2 and all(a["dir"] for a in legs):
            u1, u2 = legs[0]["dir"], legs[1]["dir"]
            dev = round(180.0 - G.angle_between_deg(u1, u2), 1)     # 일직선이면 0
        mats = sorted({(R[a["i"]].get("material") or "hose50") for a in legs})
        hose_only = all(m in HOSE_MATERIALS for m in mats)
        if ends >= 3:
            kind = "tee"
        elif ends == 2:
            if dev is not None and dev > ELBOW_DEG:
                kind = "elbow"
                rule3 = hose_only          # 호스가 45°를 넘으면 규칙 3 — T 양쪽으로 푼다
            else:
                kind = "straight"
        else:
            kind = "source" if src is not None else "end"
        fed = [i for i in range(len(R)) if feed.get(i) and G.dist(feed[i], pt) <= near
               and route_role(R[i]) == "main"]
        zones = []
        for i in fed:
            z = R[i].get("zone")
            if z not in zones:
                zones.append(z)
        out.append({"pt": [pt[0], pt[1]], "kind": kind, "ends": ends, "dev_deg": dev,
                    "materials": mats, "mixed": len(mats) > 1, "hose_only": hose_only,
                    "zones": zones, "valves": len(zones), "rule3": rule3,
                    "source": (src or {}).get("name"),
                    "routes": sorted({R[a["i"]].get("name") for a in legs})})
    out.sort(key=lambda j: (j["pt"][0], j["pt"][1]))
    return out


def transitions(routes: Sequence[Dict], sources: Sequence[Dict], analysis: Optional[Dict] = None) -> List[Dict]:
    """**재질이 바뀌는 자리**를 찾아 세운다(대표 2026-09-09).

    대표 말 — 「펌프나 여과기에서 플라스틱 파이프로 구조화하고, 지면으로 내린 후, 주배관까지는 호스로
    연결할 수도 있고. 펌프 상단에 여과기를 직결하고, 여과기 나가는 부분에서 호스로 이어갈 수도 있고.
    **고려해야 할 사항들이 많아.**」

    🔴 그 자리에 무엇이 들어가는지(카플러·나사식·조임식…)는 **부속 정본이 정한다** — 엔진은 짓지 않는다.
      여기서는 **어디서 무엇이 무엇으로 바뀌는지**만 세워 대표가 채울 자리를 보여 준다(규칙 7 `water_items`).

    → [{"pt", "from", "to", "from_material", "to_material", "kind", "hose_ends"}]
      kind = "source"(급수원 인터페이스) · "material"(관↔관 재질 전환)
    """
    from .site import MATERIAL_LABEL, route_role
    an = analysis or analyze(routes, sources)
    R = list(routes)
    out: List[Dict] = []
    for i, rr in enumerate(an["routes"]):
        r = R[i]
        kind, ref = rr["from"], rr.get("from_ref")
        pt = rr.get("feed_pt") or (list(r["pts"][0]) if r.get("pts") else None)
        if kind == "source":
            out.append({"pt": pt, "from": ref, "to": r.get("name"),
                        "from_material": None, "to_material": r.get("material") or "hose50",
                        "kind": "source", "hose_ends": 1 if is_hose(r) else 0,
                        "note": "급수원 인터페이스 — 펌프·여과기·압력계·카플러는 계통 품목(규칙 7)으로 넣습니다"})
            continue
        if kind == "free" or ref is None:
            continue
        other = next((q for q in R if q.get("name") == ref), None)
        if other is None:
            continue
        m_from = other.get("material") or "hose50"
        m_to = r.get("material") or "hose50"
        if m_from == m_to:
            continue                       # 같은 재질끼리는 이음(일자연결)이고 이미 물량에 있다
        out.append({"pt": pt, "from": ref, "to": r.get("name"),
                    "from_material": m_from, "to_material": m_to, "kind": "material",
                    "hose_ends": (1 if is_hose(other) else 0) + (1 if is_hose(r) else 0),
                    "note": "%s → %s 로 바뀌는 자리 — 연결 부속 [미확정]"
                            % (MATERIAL_LABEL.get(m_from, m_from), MATERIAL_LABEL.get(m_to, m_to))})
    return out


def header_valves(routes: Sequence[Dict], near: float = HEADER_NEAR) -> int:
    """구역 밸브 수 파생값 = Σ 분배점의 구역 수(규칙 21 · #79). 대표 입력이 있으면 bom 이 그것을 우선한다."""
    return sum(h["valves"] for h in headers(routes, near))


def _new_tee(tee_pts, pt) -> bool:
    """그 자리에 T 를 **처음** 놓는가. 한 접점은 T 하나다.

    🔴 [V105] 같은 접점을 관 양쪽에서 각각 한 번씩 세던 결함 — 인입관은 「끝이 주배관 중간에」,
      주배관은 「인입관 끝이 내 중간에」로 읽혀 **T 가 2개**로 나왔다(대표 자재표 2026-09-09 「T 2 + 여분 1」).
      세 갈래가 만나는 자리는 물리적으로 **T 하나**다.
    """
    if any(G.dist(pt, t) <= TEE_NEAR for t, _ in tee_pts):
        return False
    tee_pts.append((pt, "분기 T"))
    return True


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
        r["material"] = r.get("material") or "hose50"     # [V105] 주배관 기본도 송수호스 50
        r["len"] = G.polyline_len(r["pts"])
        # 롤 이음은 송수호스에만 — 파이프·매설 인입관은 우리가 파는 자재가 아니다(규칙 7 계통도).
        # [V105] 주배관도 재질을 갖는다 — **우리 송수호스일 때만** 롤·이음을 센다.
        r["is_hose"] = r["material"] in FEEDER_HOSE_NOMINAL
        r["joints"] = max(0, math.ceil(r["len"] / ROLL_M) - 1) if r["is_hose"] else 0
        r["bends"] = _bends(r["pts"])
        r["over45"] = [b for b in r["bends"] if b[1] > ELBOW_DEG]
    # 규칙 21 — 주배관과 **호스 인입관**만 송수호스 물량이다. 파이프·매설 인입관은 길이만 따로 적는다.
    main_m = sum(r["len"] for r in R if r["role"] == "main")
    main_hose_m = sum(r["len"] for r in R if r["role"] == "main" and r["is_hose"])
    main_other_m = sum(r["len"] for r in R if r["role"] == "main" and not r["is_hose"])
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
    total = main_hose_m + sum(feeder_hose_m.values())      # [V105] 파이프·매설 주배관은 자재가 아니다
    warnings: List[str] = []
    if not any(r["role"] == "main" for r in R):
        warnings.append("주배관(role=main)이 하나도 없다 — 전부 인입관이면 가지관을 낼 곳이 없다(규칙 21)")

    # ── 출발점 분류: 급수점 클러스터 / 다른 경로 끝 / 다른 경로 중간 ─────────
    tee_pts: List[Tuple[Pt, str]] = []
    extra_tees = 0                       # [V103] 끝점 쪽 연결에서 생긴 T(중간 분기)
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

    # ── [V103] 연결은 **시작점에서만** 일어나지 않는다(대표 2026-09-08) ─────────
    # 「인입관과 주배관의 연결을 T자로 할 수도 있잖아. 꼭 주배관의 끝에서만 이루어지지 않아.」
    # 위 분류는 관의 **첫 점**만 봤다. 그래서 ① 주배관을 한 줄로 긋고 인입관을 그 **중간**에 T 로 붙이거나
    # ② 주배관을 접점 쪽으로 그려 **끝점**이 만나면, 멀쩡히 이어진 관이 「닿지 않음」으로 나왔다.
    # 여기서 **끝점 쪽 연결**을 마저 본다. 이미 분류된 관은 건드리지 않는다(승인본 5필지 무영향).
    end_junction = set()          # 그 관의 **끝**이 연결부라 말단(규칙 1)이 아닌 관
    for i, r in enumerate(R):
        if r["from"][0] != "free":
            continue
        q_end = r["pts"][-1]
        # ② 이 관의 끝이 다른 관의 끝점에 닿는다 — 거꾸로 그린 관(일자 연결)
        ej = next((j for j, q in enumerate(R)
                   if j != i and G.dist(q_end, q["pts"][-1]) <= END_NEAR), None)
        if ej is not None:
            end_groups.setdefault(ej, []).append(i)
            end_junction.add(i)
            r["from"] = ("tail", ej)
            r["feed_pt"] = [round(q_end[0], 1), round(q_end[1], 1)]
            continue
        # ②' 이 관의 끝이 다른 관의 **중간**에 닿는다 — 거꾸로 그렸고 T 로 붙었다
        hit = None
        for j, q in enumerate(R):
            if j == i:
                continue
            sj, cj, _ = G.nearest_on_polyline(q["pts"], q_end)
            if G.dist(cj, q_end) <= MID_NEAR and END_NEAR < sj < q["len"] - END_NEAR:
                hit = (j, cj)
                break
        if hit is not None:
            end_junction.add(i)
            r["from"] = ("tail", hit[0])
            r["feed_pt"] = [round(hit[1][0], 1), round(hit[1][1], 1)]
            if _new_tee(tee_pts, hit[1]):
                extra_tees += 1
            continue
        # ① 다른 관의 **끝점**이 이 관의 중간에 닿는다 — 인입관이 주배관 중간에 T 로(대표 그림)
        hit = None
        for j, q in enumerate(R):
            if j == i:
                continue
            sj, cj, _ = G.nearest_on_polyline(r["pts"], q["pts"][-1])
            if G.dist(cj, q["pts"][-1]) <= MID_NEAR and END_NEAR < sj < r["len"] - END_NEAR:
                hit = (j, cj)
                break
        if hit is not None:
            end_junction.add(hit[0])          # 붙은 쪽(인입관)의 끝은 말단이 아니다
            r["from"] = ("tap", hit[0])
            r["feed_pt"] = [round(hit[1][0], 1), round(hit[1][1], 1)]
            if _new_tee(tee_pts, hit[1]):
                extra_tees += 1

    # 그래도 남은 「닿지 않음」만 말한다 — **얼마나 떨어졌는지·무엇을 하면 되는지**와 함께
    # (대표 2026-09-08 「닿지 않았다는 게 뭐지?」).
    for i, r in enumerate(R):
        if r["from"][0] != "free":
            continue
        p = r["pts"][0]
        cand = []
        if sources:
            k = min(range(len(sources)), key=lambda j: G.dist(p, tuple(sources[j]["pt"])))
            cand.append((G.dist(p, tuple(sources[k]["pt"])),
                         "급수원 '%s'" % (sources[k].get("name") or "?"), SOURCE_NEAR))
        for j, q in enumerate(R):
            if j == i:
                continue
            cand.append((G.dist(p, q["pts"][-1]), "'%s' 끝점" % q["name"], END_NEAR))
            _s, _c, _ = G.nearest_on_polyline(q["pts"], p)
            cand.append((G.dist(_c, p), "'%s' 중간" % q["name"], MID_NEAR))
            _s2, _c2, _ = G.nearest_on_polyline(r["pts"], q["pts"][-1])
            cand.append((G.dist(_c2, q["pts"][-1]), "'%s' 끝점(이 관 중간에)" % q["name"], MID_NEAR))
        near_txt = ""
        if cand:
            d, what, lim = min(cand)
            r["from_gap"] = round(d, 1)
            r["from_near"] = what
            near_txt = " — 가장 가까운 것은 %s 이고 **%.1f m** 떨어져 있다(%.0f m 안이어야 이어진다)" % (what, d, lim)
        warnings.append("%s '%s' 이 급수원·다른 관 어디에도 닿지 않았다%s. "
                        "이 관의 **첫 점이나 끝점**을 그 자리로 옮기거나, 인입관을 이 관까지 늘려 주세요 "
                        "— 인입관 끝을 주배관 **중간**에 대면 그 자리가 분배점(T)이 됩니다"
                        % ("주배관" if r["role"] == "main" else "인입관", r["name"], near_txt))

    tees = extra_tees
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

    # 🔵 [V106] **파이프로 시작하면 호스밴드가 들어가지 않는다**(대표 2026-09-09).
    #    `start_bands` 는 그 급수점에서 **호스를 무는 밴드 수**다 — 승인본 실측이 0·2·4 로 제각각인 것은
    #    펌프·여과기·카플러가 몇 번 물리느냐에 달렸기 때문이다. 그래서 엔진이 값을 정하지 않고,
    #    **나가는 관이 전부 호스가 아닌데 밴드를 세고 있으면** 그 사실만 말한다.
    for si, idx in src_groups.items():
        if int(sources[si].get("start_bands", 0) or 0) > 0 and not any(R[k]["is_hose"] for k in idx):
            warnings.append("급수원 '%s' 에서 나가는 관이 %s 입니다 — 나사식·조임식 파이프 연결에는 "
                            "**호스밴드가 들어가지 않습니다**. 「시작부 호스밴드」 %d 개를 확인해 주세요"
                            % (sources[si].get("name") or "?",
                               " · ".join(sorted({R[k]["material"] for k in idx})),
                               int(sources[si].get("start_bands", 0) or 0)))

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
    # 말단(규칙 1 · E호스밸브 마감세트) = **물을 받는 자리가 아닌 열린 끝**.
    # [V103] 받는 자리가 첫 점이 아닐 수 있으므로 열린 끝이 어디인지 갈래마다 다르다 —
    #   첫 점에서 받으면 끝점이 열려 있고, 끝에서 받으면(tail) 첫 점이, 중간에서 받으면(tap) **양쪽**이 열려 있다.
    end_pts = []
    for j, r in enumerate(R):
        kind = r["from"][0]
        if kind == "tap":
            opens = [r["pts"][0], r["pts"][-1]]
        elif kind == "tail":
            opens = [r["pts"][0]]
        else:
            opens = [r["pts"][-1]]
        for q in opens:
            if tuple(q) == tuple(r["pts"][-1]) and (j in end_groups or j in end_junction):
                continue                              # 그 끝은 연결부다(다른 관이 출발하거나 붙었다)
            end_pts.append(q)
    ends = len(end_pts)
    joints = sum(r["joints"] for r in R)
    elbows = sum(len(r["elbows_over45"]) for r in R)
    at_tee_n = sum(len(r["bends_at_tee"]) for r in R)
    for r in R:
        for p, d in r["elbows_over45"]:
            warnings.append(f"'{r['name']}' 꺾임 {d:.0f}° > 45° @ {tuple(round(x, 1) for x in p)} — 규칙 3(T 양쪽) 검토")

    hdrs = headers(routes, feed={i: r["feed_pt"] for i, r in enumerate(R) if r.get("feed_pt")})

    # 🔵 [V103] 중간에서 받는 주배관은 **양쪽으로 갈라져** 흐른다. 수리 계산은 여전히
    #    「한쪽 끝에서 전 길이를 흐른다」로 잡는다 — 실제보다 손실을 **크게** 보는 쪽이라 안전하지만,
    #    그 사실을 숨기지 않는다(불변 원칙 1 — 모델을 임의로 바꾸지 않는다).
    for r in R:
        if r["from"][0] == "tap" and r["role"] == "main":
            warnings.append("주배관 '%s' 는 **중간에서 물을 받는다**(T 분배). 손실·양정은 여전히 "
                            "「한쪽 끝에서 전 길이」로 계산한다 — 실제보다 **크게** 잡는 쪽이라 "
                            "설계는 안전측이다. 정확히 나누려면 그 자리에서 선을 둘로 끊어 그리세요"
                            % r["name"])

    def _from_ref(r):
        """출발점이 닿은 상대의 이름 — 급수점 이름 또는 다른 경로 이름(화면 「🔗 연결」용 · V100)."""
        kind, v = r["from"]
        if kind == "source":
            return sources[v].get("name")
        if kind in ("end", "mid", "tap", "tail"):
            return R[v]["name"]
        return None

    return {
        "total_m": round(total, 1),                      # 송수호스 길이 = 주배관 + 호스 인입관
        "rolls": math.ceil(total / ROLL_M),
        "main_m": round(main_m, 1), "feeder_m": round(feeder_m, 1),          # 규칙 21
        "main_hose_m": round(main_hose_m, 1), "main_other_m": round(main_other_m, 1),   # [V105]
        "feeder_hose_m": {k: round(v, 1) for k, v in feeder_hose_m.items()},
        "feeder_other_m": round(feeder_other_m, 1),
        "headers": hdrs, "header_valves": sum(h["valves"] for h in hdrs),
        "tees": tees, "ends": ends, "joints": joints, "elbows_over45": elbows,
        "bends_at_tee": at_tee_n,
        "routes": [{"name": r["name"], "role": r["role"], "zone": r.get("zone"),
                    "material": r["material"],
                    "d_mm": feeder_d_mm(r),                # 계산 내경(규칙 21 · V105 주배관도)
                    "len_m": round(r["len"], 1),
                    "joints": r["joints"], "from": r["from"][0], "from_ref": _from_ref(r),
                    "from_gap": r.get("from_gap"), "from_near": r.get("from_near"),
                    "feed_pt": r.get("feed_pt"),          # [V103] 물을 받는 자리(첫 점이 아닐 수 있다)
                    "bends": [[list(p), round(d, 1)] for p, d in r["bends"]]} for r in R],
        "hose_bands_src": sum(int(sources[si].get("start_bands", 0) or 0)
                              for si, idx in src_groups.items() if any(R[k]["is_hose"] for k in idx)),
        "tee_pts": [[list(p), tag] for p, tag in tee_pts],
        "end_pts": [list(p) for p in end_pts],
        "warnings": warnings,
    }


def propose(*_a, **_k):
    """규칙 3 자동 경로 제안 — P1 범위 밖. 경로가 없으면 설계를 진행하지 않는다(불변 원칙 1)."""
    raise NotImplementedError("주배관 경로는 대표 입력(규칙 13). 자동 제안은 P2 이후.")

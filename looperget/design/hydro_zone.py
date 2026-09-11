# -*- coding: utf-8 -*-
"""
looperget.design.hydro_zone — 운전 구역별 수리 검증 (순수 함수 · 계산은 코드가 한다).

정본 이식 = `_설계/배추밭스프링클러_20260824/10_계산/_계산_펌프_통합.py`(sys_head · operating_point)
· `_계산_수리_숙진리.py`(solve_zone). 손실은 프로덕션 `looperget.hydro`가 계산한다.

    zone_point(n_heads, main_m, lat_n, lat_m, pump_curve)  → 펌프 곡선 ∩ 시스템 곡선 = 실제 운전점
    zone_demand(n_heads, main_m, lat_n, lat_m)             → 말단 1.5 bar를 지키는 펌프 요구 사양
    zones_report(design, site)                              → 구역별 표 (제안서 상호확인·급수 지면용)
    spacing_defaults(model, p_end)                          → 헤드 모델·수압 → 간격 기본값 제시 (규칙 20 · P3)

노즐·수압·반경의 정본은 **`layout.HEAD_PROFILES`**다(규칙 20) — 이 모듈은 값을 갖지 않고 프로필에서 받는다.
기준(대표 확정 · 08-26): 말단 헤드 1.5 bar = 살수 반경 10 m · 427B 노즐(매뉴얼 1030 L/h @ 3 bar) ·
주배관 **호칭** 50 mm(내경 50.8) · 가지관 **호칭** 25 mm(내경 25.4 · `pipes.py` 정본) · 여과기·부속 여유 2 m. 반경 보간 10 + 2·(bar − 1.5)는 대표 실증값.
펌프 곡선은 **입력**(site["pump"])이다 — 없으면 요구 사양만 내고 펌프는 `[미확정]`.
"""
from __future__ import annotations

import math
from typing import Dict, List, Optional, Sequence, Tuple

from .. import hydro as H
from . import pipes
from .layout import HEAD_PROFILES

DEFAULT_HEAD = "427B"


def head_profile(model: Optional[str] = None) -> Dict:
    """헤드 모델의 물리 정본(`layout.HEAD_PROFILES`) — 노즐·수압·반경은 전부 여기서 온다."""
    return HEAD_PROFILES[model or DEFAULT_HEAD]


def nozzle_k(model: Optional[str] = None) -> float:
    p = head_profile(model)
    return H.nozzle_k(p["nozzle_lpm"], p["nozzle_bar"])


NOZZLE_K = nozzle_k()                     # 427B 4.0 mm (프로필 파생 · 규칙 20)
P_END_TARGET = head_profile()["p_min"]    # 최소 보증 말단압 1.5 bar → 살수 반경 10 m
# 🔴 **연결부속 손실계수(K값)는 확보 불가다**(대표 확답 2026-09-07:
#    「부속의 손실계수 등은 확보가 불가능해. 농업용 부속들의 한계야. 나중에 차차 우리가 직접
#     사이즈를 측정하거나 개별 모델링을 해서 계산하던지 해야해」).
#    그래서 부속 손실은 **개별로 세지 않는다.** 지금 그 자리를 대신하는 것은 이 한 값 —
#    승인 시공 5필지를 재현하는 **일괄 여유 2 m**(여과기·부속·급수 인터페이스 전부 포함)다.
#    ⚠ 이 값은 **역산된 실측 보정**이지 물리 모델이 아니다. 부속 구성이 크게 달라지는 현장
#    (매니폴드가 길거나 밸브가 많은 관급 등)에서는 **이 여유가 충분하다는 근거가 없다.**
#    갈 길 = 자체 치수 실측 또는 개별 모델링(대표 방침) → 그때 이 상수를 K값 합으로 바꾼다.
SUCTION_MARGIN_M = 2.0                    # 여과기·부속 일괄 여유 (K값 대체 · 승인본 역산)
V50_LIMIT = 2.0                           # 권장 유속 상한(m/s)

# 🔴 **관경은 호칭이고 계산은 내경으로 한다** — 정본은 `pipes.py`(대표 확답 2026-09-06 · 인치 기반).
# 신규 설계는 **실물 내경**(호칭 50 = 50.8 · 25 = 25.4)으로 돈다.
MAIN_MM = pipes.by_nominal(pipes.APPROVED_MAIN_MM)["id_mm"]        # 50.8 (2″)
LAT_MM = pipes.by_nominal(pipes.APPROVED_LATERAL_MM)["id_mm"]      # 25.4 (1″)

# 🔴 **재현 전용 — 승인 정답지는 호칭 50/25 로 계산돼 있다.** 정답지는 승인본의 기록이라 재계산하지 않는다
# (불변 원칙 5·6). 재현 관문은 이 값을 `pipe_mm=REPRO_MM` 로 **명시해서** 돌린다.
REPRO_MM = (50.0, 25.0)

# 대표 확인(08-27) 농가 보유 펌프 — 곡선은 `_계산_PU3000.py` 디지타이즈(명판 일치)
PUMP_CURVES = {
    "PU-3000I/P": {
        "흡상 0.5 m": [(0, 44), (100, 41), (200, 36), (300, 29), (350, 24), (400, 19), (450, 12), (480, 5)],
        "흡상 6 m": [(0, 44), (100, 41), (200, 36), (300, 28), (330, 25), (350, 22), (365, 12), (375, 5)],
    },
}


def radius_m(p_end_bar: float, model: Optional[str] = None) -> float:
    """말단압 → 살수 반경 (프로필의 대표 실증 보간: 427B는 1.5 bar = 10 m · 2.5 bar = 12 m)."""
    p = head_profile(model)
    r0_bar, r0_m = p["r_ref"]
    return r0_m + p["r_slope"] * (p_end_bar - r0_bar)


def spacing_defaults(model: Optional[str] = None, p_end: Optional[float] = None) -> Dict:
    """설계 규칙 20 — 헤드 모델(+ 실제 말단압)에서 **간격 기본값을 제시**한다. P3 「설계」 탭의 입력 기본값.

    간격은 프로필의 정본값을 그대로 낸다 — **압력으로 보간해 만들지 않는다**(그 정본이 없다 · 원칙 1).
    압력이 하는 일은 ① 반경 계산 ② 그 간격이 설계 대역 안인지 판정 ③ 겹침 폭 보고까지다.
    대역을 벗어나면 사실만 알리고 **조정은 대표·농가가 정한다**(규칙 7).

    겹침 = 2·반경 − 헤드 간격. 427B 기본(2.5 bar · r 12 · S 14) = 10 m — 규칙 20의 근거 수치와 같다.
    """
    prof = head_profile(model)
    lo, hi = prof["p_bar"]
    pe = float(prof["p_end"] if p_end is None else p_end)
    r = radius_m(pe, model)
    overlap = 2 * r - prof["S"]
    if pe < prof["p_min"]:
        band = "보증압 미달"
    elif pe < lo:
        band = "설계 대역 아래"
    elif pe > hi:
        band = "설계 대역 위"
    else:
        band = "설계 대역"
    if overlap <= 0:
        verdict = "미커버 — 간격을 좁히거나 수압을 올려야 한다"
    elif band == "설계 대역":
        verdict = "기본값 그대로 제시"
    else:
        verdict = "기본값 제시 + 수압 확인 필요(조정은 규칙 7)"
    return {"model": model or DEFAULT_HEAD, "p_end": round(pe, 2), "p_bar": list(prof["p_bar"]),
            "p_min": prof["p_min"], "radius_m": round(r, 1),
            "S": prof["S"], "lat_gap": prof["lat_gap"], "std": prof["std"], "maxm": prof["maxm"],
            "overlap_m": round(overlap, 1), "band": band, "verdict": verdict,
            "note": prof["note"], "source": "설계 규칙 20 · layout.HEAD_PROFILES"}


def pump_head(curve: Sequence[Tuple[float, float]], q_lpm: float) -> float:
    if q_lpm <= 0:
        return curve[0][1]
    for (qa, ha), (qb, hb) in zip(curve, curve[1:]):
        if q_lpm <= qb:
            return ha + (hb - ha) * (q_lpm - qa) / (qb - qa)
    return 0.0


Feeders = Optional[Sequence[Tuple[float, float]]]   # 규칙 21 — 관경이 다른 인입관 [(길이 m, 내경 mm)]


def sys_head(n_heads: int, main_m: float, lat_n: int, lat_m: float, p_end: float,
             model: Optional[str] = None, pipe_mm: Optional[Tuple[float, float]] = None,
             feeders: Feeders = None) -> Dict:
    """말단압 p_end를 만들려면 펌프가 내야 하는 양정(m)과 그때의 유량(L/분).
    임계 열(두수·길이 최대)로 가지관 손실을, 열 수만큼의 분기로 주배관 손실(Christiansen)을 본다.

    `pipe_mm` = (주배관 내경, 가지관 내경). 기본은 실물 내경 `MAIN_MM/LAT_MM`.
    **승인 정답지를 재현할 때만** `REPRO_MM`(호칭 50/25)을 넘긴다."""
    main_mm, lat_mm = pipe_mm or (MAIN_MM, LAT_MM)
    k = nozzle_k(model)
    p_avg = p_end
    for _ in range(200):
        q1 = H.nozzle_flow_lpm(k, p_avg)
        hf_lat = H.lateral_loss_m(lat_n * q1, lat_mm, lat_m, lat_n)
        p_in_lat = p_end + H.head_m_to_bar(hf_lat)
        new = (p_in_lat + p_end) / 2
        if abs(new - p_avg) < 1e-7:
            break
        p_avg = new
    q1 = H.nozzle_flow_lpm(k, p_avg)
    Q = n_heads * q1
    n_branch = max(2, int(math.ceil(n_heads / max(1, lat_n))))
    hf_main = H.lateral_loss_m(Q, main_mm, main_m, n_branch)
    # 규칙 21 — 관경이 다른 인입관은 **분출구 없이 전 유량**이 지나므로 Christiansen 없이 그 관경으로 본다.
    hf_feed = sum(H.hazen_williams_loss_m(Q, d, L) for L, d in (feeders or []) if L > 0 and d)
    p_start = p_in_lat + H.head_m_to_bar(hf_main + hf_feed)
    return {"need_head_m": H.bar_to_head_m(p_start) + SUCTION_MARGIN_M, "Q": Q, "q_head": q1,
            "p_start": p_start, "p_in_lat": p_in_lat, "hf_lat": hf_lat, "hf_main": hf_main,
            "hf_feed": hf_feed,
            "v50": H.velocity_ms(Q, main_mm)}   # 열 이름은 「v50」 그대로 — 호칭 50 관의 유속이다


def zone_point(n_heads: int, main_m: float, lat_n: int, lat_m: float,
               curve: Sequence[Tuple[float, float]], model: Optional[str] = None,
               pipe_mm: Optional[Tuple[float, float]] = None, feeders: Feeders = None) -> Dict:
    """펌프 곡선 ∩ 시스템 곡선 — 실제 말단압을 이분법으로 찾는다."""
    lo, hi = 0.2, 4.0
    for _ in range(80):
        p_end = (lo + hi) / 2
        s = sys_head(n_heads, main_m, lat_n, lat_m, p_end, model, pipe_mm, feeders)
        if pump_head(curve, s["Q"]) >= s["need_head_m"]:
            lo = p_end
        else:
            hi = p_end
    p_end = lo
    s = sys_head(n_heads, main_m, lat_n, lat_m, p_end, model, pipe_mm, feeders)
    verdict = "OK" if p_end >= P_END_TARGET else ("주의" if p_end >= 1.2 else "부족")
    return {"heads": n_heads, "main_m": round(main_m, 1), "lat_n": lat_n, "lat_m": round(lat_m, 1),
            "Q": round(s["Q"]), "q_head": round(s["q_head"], 1),
            "p_start": round(s["p_start"], 2), "p_end": round(p_end, 2),
            "hf_lat": round(s["hf_lat"], 1), "hf_main": round(s["hf_main"], 1),
            "hf_feed": round(s["hf_feed"], 1),
            "need_head_m": round(s["need_head_m"]), "have_head_m": round(pump_head(curve, s["Q"]), 1),
            "radius_end": round(radius_m(p_end, model), 1), "v50": round(s["v50"], 2), "verdict": verdict}


def zone_demand(n_heads: int, main_m: float, lat_n: int, lat_m: float,
                model: Optional[str] = None, pipe_mm: Optional[Tuple[float, float]] = None,
                feeders: Feeders = None) -> Dict:
    """펌프가 없을 때 — 말단 1.5 bar를 지키는 요구 사양(유량·양정·축동력)."""
    s = sys_head(n_heads, main_m, lat_n, lat_m, P_END_TARGET, model, pipe_mm, feeders)
    return {"heads": n_heads, "main_m": round(main_m, 1), "lat_n": lat_n, "lat_m": round(lat_m, 1),
            "Q": round(s["Q"]), "q_head": round(s["q_head"], 1),
            "p_start": round(s["p_start"], 2), "p_end": P_END_TARGET,
            "hf_lat": round(s["hf_lat"], 1), "hf_main": round(s["hf_main"], 1),
            "hf_feed": round(s["hf_feed"], 1),
            "need_head_m": round(s["need_head_m"]), "need_hp": round(H.pump_shaft_hp(s["Q"], s["need_head_m"]), 1),
            "radius_end": radius_m(P_END_TARGET, model), "v50": round(s["v50"], 2), "verdict": "[미확정 펌프]"}


def cap_heads_15bar(main_m: float, lat_n: int, lat_m: float, curve, n_from: int,
                    model: Optional[str] = None,
                    pipe_mm: Optional[Tuple[float, float]] = None, feeders: Feeders = None) -> int:
    """말단 1.5 bar를 지키는 동시 두수 상한(미달 구역의 대안 수치)."""
    for n in range(n_from, 3, -1):
        if zone_point(n, main_m, lat_n, lat_m, curve, model, pipe_mm, feeders)["p_end"] >= P_END_TARGET:
            return n
    return 0


def _curve_of(site: Dict):
    """site → 펌프 곡선. 없으면 None (그러면 요구 사양만 낸다)."""
    pump = site.get("pump") or {}
    if pump.get("curve"):
        return [tuple(p) for p in pump["curve"]]
    if pump.get("model") in PUMP_CURVES:
        return PUMP_CURVES[pump["model"]][pump.get("case", "흡상 0.5 m")]
    return None


def _zone_inputs(design: Dict, main_id_mm: Optional[float] = None):
    """구역별 (구역, 두수, 주배관 길이, 임계 열 두수, 임계 열 길이, 인입관 [(길이, 내경)]).

    규칙 21 — 인입관(role=feeder)은 **모든 구역**의 손실에 들어간다.
    관경이 주배관과 같으면(또는 모르면) 승인본 보정 그대로 주배관 길이에 합산하고,
    다르면 (길이, 내경)을 따로 내어 `sys_head` 가 그 관경으로 본다."""
    routes = {r["name"]: r for r in design["mainline"]["routes"]}
    common_m, feeders = 0.0, []
    for r in routes.values():
        role = r.get("role") or ("feeder" if r.get("zone") is None else "main")
        if role != "feeder":
            continue
        d = r.get("d_mm")
        if main_id_mm is None or not d or abs(float(d) - float(main_id_mm)) < 0.05:
            common_m += r["len_m"]
        else:
            feeders.append((r["len_m"], float(d)))

    def _own_pipe(r):
        """[V105] 우리 송수호스가 아닌 주배관(수도 파이프·매설관)은 **제 관경**으로 손실을 본다.
        분기 없는 도관으로 보므로 실제보다 손실을 **크게** 잡는다 — 안전측이다(경고로 말한다)."""
        d = r.get("d_mm")
        return (r.get("material") in ("pipe", "buried") and d
                and (main_id_mm is None or abs(float(d) - float(main_id_mm)) >= 0.05))
    lats = {l["id"]: l for l in design["laterals"]}
    for z in design["zones"]:
        rows = [lats[i] for i in z["laterals"]]
        if not rows:
            continue
        crit = max(rows, key=lambda r: (r["n_heads"], r["len_m"]))
        zr = [routes[n] for n in z["routes"] if n in routes]
        zone_main = sum(r["len_m"] for r in zr if not _own_pipe(r))
        own = feeders + [(r["len_m"], float(r["d_mm"])) for r in zr if _own_pipe(r)]
        yield z, z["n_heads"], zone_main + common_m, crit["n_heads"], crit["len_m"], own


def _pipe_mm_of(site: Dict) -> Tuple[float, float]:
    """site 의 주배관 **호칭** → 계산에 쓸 (주배관 내경, 가지관 내경). 없으면 실물 기본값."""
    n = site.get("main_mm")
    if n in (None, "", "auto", 0):
        return (MAIN_MM, LAT_MM)
    item = pipes.by_nominal(n)
    return ((item["id_mm"] if item else MAIN_MM), LAT_MM)


def resolve_main_mm(design: Dict, site: Dict) -> Dict:
    """주배관 **호칭**을 정한다 — `site["main_mm"]` 이 있으면 그대로, 없으면 **엔진이 고른다.**

    🔴 **여유 하한은 두지 않는다**(대표 지시 2026-09-07 「엔진이 스스로 돌게」). 말단 1.5 bar 를
    지키는 **가장 가는 관**을 고르고, 여유가 얇으면 `select_main` 이 경고를 붙인다.

    후보는 **주배관 부속이 성립하는 관경만**이다(`pipes.main_candidates()` = 40·50).
    주배관은 현장에 **하나**다 — 그래서 구역별 요구 중 **가장 굵은 것**을 쓴다.
    관경이 바뀌면 운전점도 바뀌므로 **고정점까지 되돌려 계산한다**(최대 4회 · 진동하면 굵은 쪽).

    🔴 **펌프가 없으면 자동으로 정하지 않는다.** 관경 선정은 「이 입구압으로 말단을 지키는가」인데
    펌프가 [미확정]이면 입구압이 **선정 결과에 따라 달라지는 순환**이 된다 — 값을 지어내지 않고
    승인본 기본(호칭 50)으로 두고 말한다(불변 원칙 1).
    """
    given = site.get("main_mm")
    if given not in (None, "", "auto", 0):
        return {"main_mm": int(given), "source": "대표 지정", "auto": False, "warn": [], "picks": []}

    curve = _curve_of(site)
    if not curve:
        return {"main_mm": pipes.APPROVED_MAIN_MM, "source": "기본(승인본)", "auto": False, "picks": [],
                "warn": ["펌프가 [미확정]이라 주배관 관경을 자동으로 정하지 않았다 — "
                         "승인본과 같은 호칭 %d mm 로 두었다. 펌프 명판을 받으면 엔진이 고른다."
                         % pipes.APPROVED_MAIN_MM]}

    mm, warn, seen, picks = pipes.APPROVED_MAIN_MM, [], [], []
    for _ in range(4):
        seen.append(mm)
        d_main = pipes.by_nominal(mm)["id_mm"]
        picks, need = [], []
        for z, n_heads, main_m, lat_n, lat_m, fd in _zone_inputs(design, d_main):
            r = zone_point(n_heads, main_m, lat_n, lat_m, curve, pipe_mm=(d_main, LAT_MM), feeders=fd)
            # 🔴 이미 말단 1.5 bar 를 못 지키는 구역은 **관경으로 풀 문제가 아니다.**
            #    이런 구역의 운전점은 압력이 무너진 상태라 그대로 쓰면 오히려 가는 관을 고른다.
            #    관경을 내리지 않고 그대로 두고, 무엇을 해야 하는지 말한다(불변 원칙 1).
            if r["p_end"] < P_END_TARGET:
                picks.append({"zone": str(z["zone"]), "Q": r["Q"], "main_m": round(main_m, 1),
                              "p_start": r["p_start"], "p_end": r["p_end"], "d_mm": None,
                              "nominal_mm": pipes.APPROVED_MAIN_MM, "warn": [],
                              "reason": "말단 %.2f bar < %.1f — 관경 자동 선정 보류" % (r["p_end"], P_END_TARGET)})
                need.append(pipes.APPROVED_MAIN_MM)
                w = ("구역 %s: 말단 %.2f bar 로 보증 %.1f bar 에 못 미친다 — **관경으로 풀 문제가 아니다.** "
                     "구역을 나누거나 펌프를 키워야 한다(설계 판단). 관경은 호칭 %d mm 로 두었다."
                     % (z["zone"], r["p_end"], P_END_TARGET, pipes.APPROVED_MAIN_MM))
                if w not in warn:
                    warn.append(w)
                continue
            sel = pipes.select_main(r["Q"], main_m, r["p_start"],
                                    only_mm=pipes.main_candidates())
            picks.append({"zone": str(z["zone"]), "Q": r["Q"], "main_m": round(main_m, 1),
                          "p_start": r["p_start"], "p_end": r["p_end"], "d_mm": sel["d_mm"],
                          "nominal_mm": (pipes.by_diameter(sel["d_mm"]) or {}).get("nominal_mm"),
                          "warn": sel["warn"], "reason": sel.get("reason", "")})
            if sel["d_mm"] is None:
                warn.append("구역 %s: %s" % (z["zone"], sel.get("reason", "관경을 정할 수 없다")))
                need = None
                break
            need.append(pipes.by_diameter(sel["d_mm"])["nominal_mm"])
        if need is None:
            return {"main_mm": pipes.APPROVED_MAIN_MM, "source": "선정 실패", "auto": False,
                    "warn": warn, "picks": picks}
        new = max(need) if need else pipes.APPROVED_MAIN_MM
        if new == mm:
            break
        if new in seen:                      # 진동 — 굵은 쪽으로 확정한다(안전 측)
            mm = max(seen + [new])
            break
        mm = new
    for pk in picks:
        warn += [w for w in pk["warn"] if w not in warn]
    return {"main_mm": mm, "source": "엔진 선정", "auto": True, "warn": warn, "picks": picks}


def zones_report(design: Dict, site: Dict) -> List[Dict]:
    """엔진 출력(zones·laterals·mainline)과 site(routes·pump)로 구역별 운전점 표를 만든다.
    주배관 내경은 설계 결과의 확정 호칭을 따른다. 옛 출력에 없으면 site, 실물 기본 순서."""
    pump = site.get("pump") or {}
    curve = _curve_of(site)
    pipe_mm = _pipe_mm_of(dict(site, main_mm=design.get("main_mm") or site.get("main_mm")))
    out = []
    for z, n_heads, main_m, lat_n, lat_m, fd in _zone_inputs(design, pipe_mm[0]):
        if curve:
            r = zone_point(n_heads, main_m, lat_n, lat_m, curve, pipe_mm=pipe_mm, feeders=fd)
            if r["verdict"] != "OK":
                r["cap_15bar"] = cap_heads_15bar(main_m, lat_n, lat_m, curve, n_heads,
                                                 pipe_mm=pipe_mm, feeders=fd)
        else:
            r = zone_demand(n_heads, main_m, lat_n, lat_m, pipe_mm=pipe_mm, feeders=fd)
        if fd:
            r["feeder_m"] = round(sum(L for L, _ in fd), 1)     # 규칙 21 — 관경이 다른 인입관 길이
        r["zone"] = str(z["zone"])
        r["pump"] = pump.get("model", "[미확정]")
        out.append(r)
    return out


__all__ = ["zone_point", "zone_demand", "zones_report", "resolve_main_mm", "sys_head", "pump_head", "radius_m",
           "spacing_defaults", "head_profile", "nozzle_k", "cap_heads_15bar",
           "PUMP_CURVES", "P_END_TARGET", "DEFAULT_HEAD", "V50_LIMIT",
           "MAIN_MM", "LAT_MM", "REPRO_MM"]

# -*- coding: utf-8 -*-
"""
looperget.design.preview — **밭만 그려도 나오는 숫자**(#72).

대표 지적 2026-09-07 —
「내가 구역을 1개든 2개든으로 나눠야 한다면, **밭에 스프링클러가 몇 개 배치되는지, 유량은
 얼마나 필요한지 정보가 있어야** 구역을 나누고, 주배관을 어느 방향으로 깔고,
 1번과 2번의 경로를 각각 어떻게 가져갈지 판단할 수 있을 것 같은데.」

맞는 말이다. **구역·경로·밸브는 대표 판단**(설계 규칙 6·13)이지만, 그 판단에 필요한 숫자는
**엔진이 먼저 내야 한다.** 여기 있는 것은 전부 `blocks` 만으로 계산된다 — 주배관을 그리기 전에.

🔴 **한계를 함께 낸다.**
  · 주배관을 아직 안 그렸으므로 **주배관 길이는 밭 긴 변으로 잡은 추정**이다.
    실제 유량·양정은 경로를 그린 뒤 ④가 낸다.
  · 열 수·헤드 수는 **고랑 방향(`u`)에 따라 달라진다** — 방향을 바꾸면 이 숫자도 바뀐다.
  · 가용 유량을 **숫자로 읽지 못하면 구역 수를 말하지 않는다**(불변 원칙 1 — 추정 금지).
"""
from __future__ import annotations

import math
import re
from typing import Dict, List, Optional, Sequence, Tuple

from .. import hydro as H
from . import hydro_zone as HZ
from .layout import RowPolicy, rows_from_polygon

SCHEMA = "looperget.design.preview/1"

# 「분당 L」로 바꿀 수 있는 단위만 읽는다. 톤·㎥ 는 **부피**라 시간이 없으면 유량이 아니다.
_FLOW_PAT = [
    (r"(\d+(?:\.\d+)?)\s*(?:l|ℓ|리터)\s*/?\s*(?:min|m|분)", 1.0),          # L/분
    (r"(\d+(?:\.\d+)?)\s*(?:lpm|LPM)", 1.0),
    (r"분\s*당\s*(\d+(?:\.\d+)?)\s*(?:l|ℓ|리터)?", 1.0),                   # 분당 800(L)
    (r"(\d+(?:\.\d+)?)\s*(?:m3|㎥|루베)\s*/?\s*(?:h|hr|hour|시간)", 1000.0 / 60.0),
    (r"(\d+(?:\.\d+)?)\s*(?:t|톤)\s*/?\s*(?:h|hr|시간)", 1000.0 / 60.0),
]


def parse_flow_lpm(text) -> Optional[float]:
    """문진표의 자유 입력 → **분당 L**. 못 읽으면 None — 지어내지 않는다.

    🔴 「10톤 물탱크」는 **부피**다. 시간이 없으면 유량이 아니므로 None 을 낸다.
      (그 물탱크로 몇 분을 돌릴 수 있는지는 다른 이야기이고, 그건 대표가 정한다.)
    """
    s = str(text or "").strip().lower()
    if not s:
        return None
    for pat, mul in _FLOW_PAT:
        m = re.search(pat, s)
        if m:
            try:
                v = float(m.group(1)) * mul
            except ValueError:
                continue
            if v > 0:
                return round(v, 1)
    return None


def _long_side_m(poly: Sequence[Sequence[float]]) -> float:
    """폴리곤의 긴 변(주배관 길이의 **하한 추정**) — 최소외접 사각형 대신 extent 로 잡는다."""
    xs = [float(p[0]) for p in poly]
    ys = [float(p[1]) for p in poly]
    return max(max(xs) - min(xs), max(ys) - min(ys))


def _area_m2(poly: Sequence[Sequence[float]]) -> float:
    p = [q for q in poly if q is not None and len(q) >= 2]
    if len(p) < 3:
        return 0.0
    return abs(sum(p[i][0] * p[i - 1][1] - p[i - 1][0] * p[i][1]
                   for i in range(len(p)))) / 2.0


P_START_PRACTICAL = 5.0      # 현실적인 입구압 상한(bar). 그 위는 펌프가 감당 못 한다.


def zone_cap_by_pressure(main_m: float, lat_n: int, lat_m: float, n_max: int,
                         p_max: float = P_START_PRACTICAL, model=None) -> int:
    """말단 1.5 bar 를 지키면서 **입구압이 `p_max` 안에** 드는 동시 두수 상한. 이분 탐색.

    🔴 구역을 줄이면 **그 구역이 쓰는 주배관·가지관도 함께 준다** — 전체 열 수를 그대로 두고
      두수만 줄이면 「1두인데 82 bar」 같은 헛값이 나온다(2026-09-07 실측). 비례로 줄인다.
    🔵 가용 유량을 몰라도 나오는 답이다 — **관이 감당하는 한계**이기 때문이다.
      실측(50 mm 주배관 · 106두 밭): 10두 1.7 bar · 30두 2.5 · 45두 4.0 · 60두 7.5(불가).
    """
    n_max = max(1, int(n_max))
    lo, hi, best = 1, n_max, 0
    while lo <= hi:
        mid = (lo + hi) // 2
        f = mid / float(n_max)                       # 그 구역이 차지하는 몫
        try:
            p = HZ.zone_demand(mid, main_m * f, max(1, round(lat_n * f)), lat_m, model)["p_start"]
        except Exception:
            p = float("inf")
        if p <= p_max:
            best, lo = mid, mid + 1
        else:
            hi = mid - 1
    return best


def block_preview(blocks: Sequence[Dict], flow_lpm: Optional[float] = None,
                  model: Optional[str] = None) -> Dict:
    """밭 목록 → **열·헤드·요구 유량·권고 구역 수**. 주배관이 없어도 나온다.

    `blocks` = [{"name", "polygon"(로컬 m), "u"[, "policy"]}] · `flow_lpm` = 쓸 수 있는 분당 L.
    """
    prof = HZ.head_profile(model)
    rows_out: List[Dict] = []
    n_heads = n_rows = 0
    lat_total = 0.0
    main_est = 0.0
    area_all = 0.0

    for blk in blocks or []:
        poly = [tuple(p) for p in (blk.get("polygon") or [])]
        if len(poly) < 3:
            continue
        u = tuple(blk.get("u") or (1.0, 0.0))
        pol = RowPolicy(**(blk.get("policy") or {}))
        try:
            rows = rows_from_polygon(poly, u, pol)          # 🔴 mains 없이 — 주배관 전에도 나온다
        except Exception as e:                              # 기하가 이상하면 그 밭만 건너뛴다
            rows_out.append({"name": blk.get("name") or "?", "error": str(e)})
            continue
        heads = sum(len(r.heads) for r in rows)
        lat_m = sum(r.len for r in rows)
        area = _area_m2(poly)
        rows_out.append({"name": blk.get("name") or "?", "crop": blk.get("crop") or "",
                         "area_m2": round(area, 1), "rows": len(rows), "heads": heads,
                         "lat_m": round(lat_m, 1),
                         "u_deg": round(math.degrees(math.atan2(u[1], u[0])))})
        n_rows += len(rows)
        n_heads += heads
        lat_total += lat_m
        area_all += area
        main_est += _long_side_m(poly)

    out = {"schema": SCHEMA, "blocks": rows_out, "n_rows": n_rows, "n_heads": n_heads,
           "area_m2": round(area_all, 1), "lat_total_m": round(lat_total, 1),
           "main_est_m": round(main_est, 1),
           "spacing": {"head_m": prof.get("S"), "row_m": prof.get("lat_gap"),
                       "radius_m": HZ.radius_m(HZ.P_END_TARGET, model)},
           "flow_lpm": flow_lpm, "notes": []}
    if n_heads == 0:
        out["notes"].append("밭을 먼저 그려 주세요 — 열·헤드가 나오지 않습니다.")
        return out

    lat_avg = lat_total / max(1, n_rows)
    # 🔴 구역 수를 정하는 값은 **노즐 유량**이다 — `zone_demand` 는 「이 두수를 한 계통에 동시에」를
    #    푸는 함수라 두수가 많으면 입구압이 수십 bar 로 튄다. 그건 유량이 아니라 **불가 신호**다.
    q_min = H.nozzle_flow_lpm(HZ.NOZZLE_K, HZ.P_END_TARGET)          # 보증 말단압 1.5 bar
    q_ref = H.nozzle_flow_lpm(HZ.NOZZLE_K, prof["p_end"])            # 설계점(427B 2.5 bar)
    out["q_head_min"] = round(q_min, 1)
    out["q_head_ref"] = round(q_ref, 1)
    out["q_all_min"] = round(n_heads * q_min)
    out["q_all_ref"] = round(n_heads * q_ref)
    out["p_ref_bar"] = prof["p_end"]
    out["notes"].append("헤드 한 대가 **%.1f L/분**(보증 %.1f bar) ~ **%.1f L/분**(설계점 %.1f bar)입니다. "
                        "전부 한 번에 돌리면 **%s ~ %s L/분**이 듭니다."
                        % (q_min, HZ.P_END_TARGET, q_ref, prof["p_end"],
                           format(out["q_all_min"], ","), format(out["q_all_ref"], ",")))

    # 참고 — 전부 한 계통에 물렸을 때의 수리 해(불가면 그 사실이 여기서 드러난다)
    try:
        dem = HZ.zone_demand(n_heads, main_est, n_rows, lat_avg, model)
        out["demand_all"] = dem
        if dem["p_start"] > 6.0:
            out["notes"].append("🔴 **전부 한 번에는 관 손실 때문에 불가능합니다** — 한 계통으로 풀면 "
                                "입구압이 **%.0f bar** 로 튑니다(현실적인 펌프 범위 밖). "
                                "**나눠야 합니다.**" % dem["p_start"])
    except Exception:
        out["demand_all"] = None

    # 🔵 유량을 몰라도 나오는 답 — **관이 감당하는 한 구역 상한**
    cap_p = zone_cap_by_pressure(main_est, n_rows, lat_avg, n_heads, model=model)
    out["heads_cap_pressure"] = cap_p
    out["zones_by_pressure"] = max(1, math.ceil(n_heads / cap_p)) if cap_p > 0 else None
    if cap_p > 0 and out["zones_by_pressure"] > 1:
        out["notes"].append("🔵 **유량을 몰라도** 관이 감당하는 한계로 보면 한 구역에 **%d두**까지입니다 "
                            "→ **%d구역**(구역당 %d두쯤). 입구압 %.0f bar 안에서 말단 1.5 bar 를 지키는 선입니다."
                            % (cap_p, out["zones_by_pressure"],
                               math.ceil(n_heads / out["zones_by_pressure"]), P_START_PRACTICAL))
    elif cap_p >= n_heads:
        out["notes"].append("🔵 관이 감당하는 한계로는 **한 구역에 다 들어갑니다**(%d두)." % n_heads)

    out["notes"].append("주배관을 아직 안 그려서 **길이는 밭 긴 변으로 잡은 추정**입니다"
                        "(%.0f m). 실제 유량·양정·관경은 경로를 그린 뒤 ④가 냅니다." % main_est)
    out["notes"].append("열 수·헤드 수는 **고랑 방향에 따라 달라집니다** — 표에서 방향을 바꾸면 "
                        "이 숫자도 바뀝니다.")

    if flow_lpm and flow_lpm > 0:
        # 🔴 구역 수는 **권고**다 — 어디서 어떻게 나눌지는 대표 판단(설계 규칙 6).
        #    설계점 유량으로 잡는다(보수적). 최종 판정은 ④의 구역별 말단압이다.
        cap = int(flow_lpm // max(1e-6, q_ref))
        out["heads_cap"] = cap
        out["zones_min"] = max(1, math.ceil(n_heads / cap)) if cap > 0 else None
        if cap <= 0:
            out["notes"].append("🔴 쓸 수 있는 물이 헤드 한 대분(%.1f L/분)에도 못 미칩니다." % q_ref)
        elif out["zones_min"] > 1:
            out["notes"].append("쓸 수 있는 물 **%s L/분**으로는 한 번에 **%d두**까지입니다 → "
                                "**최소 %d구역**(구역당 %d두쯤)으로 나눠야 합니다."
                                % (format(round(flow_lpm), ","), cap, out["zones_min"],
                                   math.ceil(n_heads / out["zones_min"])))
        else:
            out["notes"].append("쓸 수 있는 물 **%s L/분**이면 유량만 보면 **한 번에 다 돌릴 수 있습니다** "
                                "(필요 %s L/분). 다만 **말단압**은 ④에서 확인합니다."
                                % (format(round(flow_lpm), ","), format(out["q_all_ref"], ",")))
    else:
        out["zones_min"] = None
        out["notes"].append("🔴 **쓸 수 있는 물을 분당 L 로 알려 주시면 구역 수를 계산합니다.** "
                            "「10톤 물탱크」는 부피라 유량이 아닙니다 — 관정 양수량·수도 계량기·"
                            "펌프 명판의 분당 L 을 문진표에 넣어 주세요.")
    return out

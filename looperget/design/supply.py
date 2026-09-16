"""급수원 정보와 구역 수요의 비교. 파일/전역 상태를 바꾸지 않는 순수 함수.

공개 입력 계약
-------------
``supply``: kind (pump/well/mains/unknown), curve ([[L/min, m], ...]) 또는
operating_point ({flow_lpm, pressure_bar}), conditions_confirmed (bool),
sustainable_flow_lpm (관정의 시험 지속유량). q_max_lpm/h_max_m 등 명판 극값은
참고 정보일 뿐 계산하지 않는다. curve와 operating_point를 함께 주면 오류다.

성능은 *설계 급수원 출구*에서 현재 설치 조건에 적용되는 가용 성능이어야 한다.
conditions_confirmed=True는 흡상/동수위 등 상류 손실이 성능에 반영되었고
지형고저를 확인해 기존 평탄 모델을 적용할 수 있음을 명시적으로 확인한 뜻이다.
미확인 양정은 0으로 가정하지 않는다. 관정은 지속유량도 있어야 비교 가능하다.

일점 측정은 곡선이 아니다. 그 점의 유량/잔압 이내 수요만 조건부 후보로 내며,
압력 조절과 실제 운전점 확인이 필요하다. 곡선도 입력 구간 밖으로 외삽하지 않는다.
최종 현장 충족 확정은 어떤 경로에서도 하지 않는다 (status=conditional).
수요압은 기존 sys_head의 need_head_m(여과기/부속 일괄 2m 포함)를 변환한다.
이는 기존 승인 모델의 요구치이며 추가 지형/관정 물리모델을 만들지 않는다.
"""
from __future__ import annotations

import math
from collections.abc import Mapping

from .. import hydro as H
from . import hydro_zone as HZ


def _number(value, label, *, zero=False):
    if isinstance(value, bool):
        raise ValueError(f"{label}: 유한한 숫자를 입력하세요")
    try:
        value = float(value)
    except (TypeError, ValueError, OverflowError):
        raise ValueError(f"{label}: 유한한 숫자를 입력하세요") from None
    if not math.isfinite(value) or value < 0 or (not zero and value == 0):
        raise ValueError(f"{label}: {'0 이상' if zero else '0 초과'} 유한값이 필요합니다")
    return value


def _count(value, label):
    result = _number(value, label)
    if not result.is_integer():
        raise ValueError(f"{label}: 정수가 필요합니다")
    return int(result)


def _source(supply):
    """부분 입력은 오류를 담아 반환한다. 입력 dict는 변경하지 않는다."""
    notes, errors = [], []
    out = {"curve": None, "point": None, "limit": None, "ready": False,
           "notes": notes, "errors": errors}
    if supply is None:
        supply = {}
    if not isinstance(supply, Mapping):
        errors.append("급수원 정보는 dict여야 합니다")
        return out
    try:
        if supply.get("sustainable_flow_lpm") not in (None, ""):
            out["limit"] = _number(supply["sustainable_flow_lpm"], "관정 지속유량")
        curve = supply.get("curve")
        point = supply.get("operating_point")
        if curve and point:
            raise ValueError("성능곡선 또는 동일조건 운전점 중 하나만 입력하세요")
        if curve:
            if not isinstance(curve, (list, tuple)) or len(curve) < 2:
                raise ValueError("성능곡선에는 최소 2개 유량·양정 점이 필요합니다")
            pairs = []
            for pair in curve:
                if not isinstance(pair, (list, tuple)) or len(pair) != 2:
                    raise ValueError("성능곡선은 [L/분, m] 쌍이어야 합니다")
                pairs.append((_number(pair[0], "곡선 유량", zero=True),
                              _number(pair[1], "곡선 양정", zero=True)))
            if any(qb <= qa or hb > ha for (qa, ha), (qb, hb) in zip(pairs, pairs[1:])):
                raise ValueError("곡선 유량은 엄격한 오름차순, 양정은 비증가 순서여야 합니다")
            out["curve"] = pairs
        elif point:
            if not isinstance(point, Mapping):
                raise ValueError("운전점은 flow_lpm·pressure_bar를 함께 가진 dict여야 합니다")
            out["point"] = (_number(point.get("flow_lpm"), "운전점 유량"),
                            _number(point.get("pressure_bar"), "운전점 잔압"))
            _number(H.bar_to_head_m(out["point"][1]), "운전점 양정 환산값")
        else:
            notes.append("성능곡선 또는 같은 조건에서 동시에 측정한 유량·잔압이 필요합니다. Qmax/Hmax는 운전점이 아닙니다.")
    except ValueError as exc:
        errors.append(str(exc))
    if supply.get("conditions_confirmed") is not True:
        notes.append("급수원 출구 성능의 설치조건·동수위/흡상 반영 및 평탄 지형 적용조건이 미확인입니다.")
    if supply.get("kind") == "well" and out["limit"] is None:
        notes.append("관정은 펌프 성능과 별도로 시험 지속유량을 확인해야 합니다.")
    out["ready"] = bool(not errors and (out["curve"] or out["point"])
                        and supply.get("conditions_confirmed") is True
                        and (supply.get("kind") != "well" or out["limit"] is not None))
    return out


def zone_demand(demand):
    """명시적 기하 입력 → 반올림하지 않은 설계점 수요 dict.

    demand: n_heads, main_m, lat_n(임계 가지관의 *헤드 수*), lat_m,
    model?, p_end?(프로필 설계압 기본), pipe_mm?((주관,가지관) 내경),
    feeders?([(길이m,내경mm)]). 잘못된 입력/발산은 ValueError.
    """
    if not isinstance(demand, Mapping):
        raise ValueError("구역 수요 입력은 dict여야 합니다")
    n = _count(demand.get("n_heads"), "헤드 수")
    ln = _count(demand.get("lat_n"), "임계 가지관 헤드 수")
    if ln > n:
        raise ValueError("임계 가지관 헤드 수는 전체 헤드 수보다 클 수 없습니다")
    model = demand.get("model") or HZ.DEFAULT_HEAD
    try:
        profile = HZ.head_profile(model)
    except (KeyError, TypeError):
        raise ValueError("확인되지 않은 헤드 모델입니다") from None
    pe = _number(demand.get("p_end", profile["p_end"]), "말단 설계압")
    if pe < profile["p_min"] or pe > profile["p_bar"][1]:
        raise ValueError("말단 설계압이 헤드 프로필의 보증/설계 상한 범위를 벗어났습니다")
    mm = demand.get("pipe_mm")
    if mm is not None:
        if not isinstance(mm, (list, tuple)) or len(mm) != 2:
            raise ValueError("pipe_mm에는 주관·가지관 내경 두 값이 필요합니다")
        mm = tuple(_number(v, "관 내경") for v in mm)
    fd = demand.get("feeders") or []
    if not isinstance(fd, (list, tuple)):
        raise ValueError("feeders는 길이·내경 쌍 목록이어야 합니다")
    feeds = []
    for pair in fd:
        if not isinstance(pair, (list, tuple)) or len(pair) != 2:
            raise ValueError("인입관은 [길이m, 내경mm] 쌍이어야 합니다")
        feeds.append((_number(pair[0], "인입관 길이", zero=True), _number(pair[1], "인입관 내경")))
    try:
        result = HZ.sys_head(n, _number(demand.get("main_m"), "주관 길이", zero=True), ln,
                             _number(demand.get("lat_m"), "가지관 길이", zero=True), pe,
                             model, mm, feeds)
    except (OverflowError, ZeroDivisionError) as exc:
        raise ValueError("수리 계산이 유한 범위에서 수렴하지 않았습니다") from exc
    for name in ("Q", "need_head_m", "p_start"):
        _number(result[name], name)
    return dict(result, zone=str(demand.get("zone", "")), heads=n, p_end=pe,
                required_flow_lpm=result["Q"], required_head_m=result["need_head_m"],
                required_pressure_bar=H.head_m_to_bar(result["need_head_m"]))


def _compare(source, demand):
    q = _number(demand.get("required_flow_lpm", demand.get("Q")), "구역 요구유량")
    # p_start는 일괄 여유를 제외한 관망 입구압이므로 펌프 요구압으로 쓰지 않는다.
    head = demand.get("required_head_m", demand.get("need_head_m"))
    if head is None:
        head = H.bar_to_head_m(_number(demand.get("required_pressure_bar"), "구역 요구압력"))
    head = _number(head, "구역 요구양정")
    out = {"zone": str(demand.get("zone", "")), "heads": demand.get("heads"),
           "required_flow_lpm": q, "required_head_m": head,
           "required_pressure_bar": H.head_m_to_bar(head), "status": "unverified", "notes": list(demand.get("notes") or [])}
    if source["limit"] is not None and q > source["limit"]:
        out["status"] = "insufficient"
        out["notes"].append("요구유량이 관정/급수원 지속유량을 초과합니다.")
        return out
    if not source["ready"]:
        return out
    if source["curve"]:
        curve = source["curve"]
        if not curve[0][0] <= q <= curve[-1][0]:
            out["notes"].append("요구유량이 성능곡선의 확인 구간 밖입니다. 외삽하지 않습니다.")
            return out
        available = HZ.pump_head(curve, q)
        passed = available >= head
    else:
        flow, pressure = source["point"]
        available = H.bar_to_head_m(pressure)
        passed = q <= flow and head <= available
        out["notes"].append("단일 측정점 이내의 조건부 후보 비교입니다. 실제 운전점 및 압력 조절을 확인해야 합니다.")
        if not passed:
            out["notes"].append("단일 측정점 밖의 성능은 알 수 없어 공급 부족으로 판정하지 않습니다. 요구유량에서 잔압을 추가 측정하거나 성능곡선을 확인하세요.")
            return out
    out["available_head_m"] = available
    out["status"] = "conditional" if passed else "insufficient"
    return out


def assess_supply(supply, zone_demands):
    """구역별 요구치와 급수원을 비교. 부분/잘못된 입력도 수요설계를 막지 않는다.

    zone_demands는 zone_demand/design_demands 출력 또는 HZ.zone_demand 출력이다.
    HZ.zone_point(실제 운전점) 출력은 설계 요구치가 아니므로 넘기지 않는다.
    원시 수요 수치를 보존하며 표시 반올림은 호출자 책임이다.
    """
    source = _source(supply)
    zones, errors = [], list(source["errors"])
    if not isinstance(zone_demands, (list, tuple)):
        errors.append("구역별 요구치는 목록이어야 합니다")
        zone_demands = []
    for demand in zone_demands:
        try:
            if not isinstance(demand, Mapping):
                raise ValueError("구역 요구치는 dict여야 합니다")
            if demand.get("have_head_m") is not None:
                raise ValueError("실제 운전점 대신 설계압 기준 수요를 전달하세요")
            zones.append(_compare(source, demand))
        except ValueError as exc:
            errors.append(str(exc))
            zones.append({"zone": str(demand.get("zone", "")) if isinstance(demand, Mapping) else "",
                          "status": "unverified", "notes": [str(exc)]})
    return {"mode": "capacity" if source["ready"] else "demand_only",
            "sufficient_information": source["ready"], "zones": zones, "errors": errors,
            "notes": source["notes"] + [
                "요구치는 기존 평탄 관망 모델과 부속·여과기 일괄 여유 2m를 따릅니다. 지형고저·동수위 미확인은 0m로 간주하지 않습니다.",
                "조건부 비교이며 급수원 성능 충족/현장 운전 확정이 아닙니다. 구역은 한 번에 하나씩 운전합니다."]}


def calculate_capacity(supply, demand):
    """주어진 관 경로와 입력 성능의 확인 범위에서 두수·구역수 후보를 계산.

    전체 주관/인입관/임계열 길이를 그대로 유지하고 임계열 두수만 전체 두수로
    제한한다. 임의 경로 축소/펌프 곡선 생성 없음. 구역 배치는 하지 않으므로
    zones_min은 후보이며, 실제 분할 후 design_demands로 다시 검증해야 한다.
    단일점의 heads_cap/zones_min은 측정점 이내 후보를 뜻하는 호환 필드이며
    급수원 전체의 최대 두수/최소 구역수가 아니다. candidate_label로 구분한다.
    단일점 이내 후보가 없으면 heads_cap=None(미확인)이며 불가 0두로 확정하지 않는다.
    """
    source = _source(supply)
    out = {"mode": "capacity" if source["ready"] else "demand_only",
           "heads_cap": None, "zones_min": None, "demand_all": None,
           "sufficient_information": source["ready"], "errors": list(source["errors"]),
           "notes": source["notes"] + ["두수·구역수는 입력 관 경로의 조건부 후보입니다. 실제 구역별 경로로 재검증해야 합니다."]}
    out["capacity_basis"] = "curve" if source["curve"] else ("operating_point" if source["point"] else None)
    out["candidate_label"] = ("성능곡선 확인구간의 동시두수·구역수 후보" if source["curve"]
                              else "단일 측정점 이내의 동시두수·구역수 후보" if source["point"]
                              else "급수원 미확인 — 설계 요구치")
    if source["point"]:
        out["notes"].append("단일 측정점 이내에서 계산한 후보입니다. 급수원 최대 동시두수나 최소 구역수로 확정할 수 없으며, 측정점 밖은 추가 확인이 필요합니다.")
    try:
        full = zone_demand(demand)
        out["demand_all"] = full
        if not source["ready"]:
            return out
        n = full["heads"]
        for count in range(n, 0, -1):
            candidate = full if count == n else zone_demand(dict(demand, n_heads=count, lat_n=min(_count(demand["lat_n"], "임계 가지관 헤드 수"), count)))
            if _compare(source, candidate)["status"] == "conditional":
                out.update(heads_cap=count, zones_min=math.ceil(n / count), demand_at_cap=candidate)
                break
        else:
            out["heads_cap"] = None if source["point"] else 0
            out["notes"].append("입력 성능의 확인 구간에서 조건부 두수 후보를 찾지 못했습니다. 확인 구간 밖의 성능은 추가 확인이 필요합니다.")
    except (ValueError, TypeError) as exc:
        out["errors"].append(str(exc))
    return out


def _design_geometry(design, site):
    """기존 경로 해석에 실물 호스 관경을 얹는 복사 어댑터 (입력 무변경)."""
    from .site import feeder_d_mm

    default_mm = HZ._pipe_mm_of(dict(site, main_mm=design.get("main_mm") or site.get("main_mm")))
    blocks = {b["name"]: b for b in site.get("blocks", [])}
    laterals = {row["id"]: row for row in design.get("laterals", [])}
    source_routes = design["mainline"]["routes"]
    for original_zone in design["zones"]:
        zone_routes = [r for r in source_routes if r["name"] in original_zone["routes"]]
        hose_routes = [r for r in zone_routes if r.get("material") in ("hose40", "hose50")]
        hose_diameters = {_number(feeder_d_mm(r), "실물 호스 내경") for r in hose_routes}
        mm = (next(iter(hose_diameters)), default_mm[1]) if len(hose_diameters) == 1 and len(hose_routes) == len(zone_routes) else default_mm
        routes, notes = [], []
        for route in source_routes:
            row = dict(route)
            if row.get("material") in ("hose40", "hose50"):
                row["d_mm"] = feeder_d_mm(row)
                if row["name"] in original_zone["routes"] and abs(row["d_mm"] - mm[0]) >= 0.05:
                    # 기존 HZ의 이경 주관 처리로 보낸다. BOM/원본 재질은 바꾸지 않는다.
                    row["material"] = "pipe"
                    notes.append("혼합 관경 주관 '%s'는 실제 내경 %.1fmm에서 전유량이 흐르는 기존 이경관 모델로 보수적으로 계산했습니다." % (row["name"], row["d_mm"]))
            routes.append(row)
        adapted = dict(design, zones=[original_zone], mainline=dict(design["mainline"], routes=routes))
        inputs = list(HZ._zone_inputs(adapted, mm[0]))
        if not inputs:
            continue
        z, n, main_m, lat_n, lat_m, feeders = inputs[0]
        models, pressures = set(), []
        for row_id in z["laterals"]:
            block = blocks.get(laterals[row_id].get("block"), {})
            model = block.get("model") or site.get("model") or HZ.DEFAULT_HEAD
            models.add(model)
            try:
                default_pressure = HZ.head_profile(model)["p_end"]
            except (KeyError, TypeError):
                raise ValueError("확인되지 않은 헤드 모델입니다") from None
            pressures.append(_number(block.get("p_end", site.get("p_end", default_pressure)), "말단 설계압"))
        if len(models) != 1:
            raise ValueError("구역 내 서로 다른 헤드 모델의 혼합 수리 계산은 지원하지 않습니다")
        yield {"zone": z["zone"], "n_heads": n, "main_m": main_m,
               "lat_n": lat_n, "lat_m": lat_m, "pipe_mm": mm,
               "feeders": feeders, "model": next(iter(models)), "p_end": max(pressures)}, notes


def design_demands(design, site):
    """실제 구역 경로와 실물 호스 관경 → 펌프와 무관한 설계압 수요 목록.

    HZ의 구역/인입관 해석과 sys_head 재사용. block.p_end 또는 site.p_end 중
    구역내 최대 목표(기본 프로필 설계압)를 적용한다. 혼합 헤드 모델은 거부한다.
    호스 재질에서 확인한 실물 내경은 design/site.main_mm 기본보다 우선한다.
    """
    return [dict(zone_demand(geometry), geometry=geometry, notes=notes)
            for geometry, notes in _design_geometry(design, site)]


def design_capacity(design, site):
    """현재 배치의 구역별 후보. supply=site['supply']; 입력을 변경하지 않는다.

    design_demands와 정확히 같은 기하·실물 내경으로 각 구역을 비교한다.
    전체 밭의 별도 두수 한계를 합산하지 않는다 (구역들은 순차 운전).
    """
    zones = []
    for geometry, notes in _design_geometry(design, site):
        result = calculate_capacity(site.get("supply"), geometry)
        result["zone"] = str(geometry["zone"])
        result["geometry"] = geometry
        result["notes"].extend(notes)
        zones.append(result)
    return {"zones": zones, "notes": ["현재 배치의 실제 구역별 경로·실물 관경 기준입니다. 구역은 순차 운전하며 분할 변경 후 재검증해야 합니다."]}


__all__ = ["zone_demand", "design_demands", "assess_supply", "calculate_capacity", "design_capacity"]

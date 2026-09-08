# -*- coding: utf-8 -*-
"""
looperget.design.site — 설계 입력(대상지) 스키마 `looperget.design.site/1` 와 검증.

대표 판단으로만 채워지는 항목(규칙 6·7·12·13)은 **입력**이다 — 엔진이 임의로 만들지 않는다:
  운전 구역(routes[].zone) · 주배관 경로(routes[].pts) · 급수 계통 공용(water_items) · 밸브 배치(valves_01403).

site = {
  "schema": "looperget.design.site/1", "name": str,
  "blocks":  [{"name", "polygon": [[x,y],...] (로컬 m), "u": [ux,uy] (열 방향),
               "bars": [[[x,y],[x,y]],...]? (두둑 선, 규칙 11), "policy": {RowPolicy 덮어쓰기}?,
               "crop": str? (작물 — 처음에 물어보고 알면 넣는다. 지역·작물별 데이터 축적용, 대표 지시 2026-09-05)}],
  "routes":  [{"name", "role": "feeder"|"main", "zone", "pts": [[x,y],...], "by_ceo": true,
               "material": "hose50"|"hose40"|"pipe"|"buried"?, "d_mm": float?}],   # 규칙 13 · 21
  "sources": [{"name", "pt": [x,y], "tees_here": int?, "start_bands": int}],  # 급수점·진입점
  "water_items": [{"code","qty","note"}],                                    # 규칙 7 계통도 통과 품목
  "valves_01403": {"start": 0|1, "zones": int | None},   # zones None = 분배점에서 엔진이 센다(규칙 21)
}

규칙 21(대표 확정 2026-09-08) — 다섯 단: 급수원 → **인입관(feeder)** → **분배점(header)** → 주배관(main) → 가지관.
  · 인입관 = 급수원에서 분배점까지 물을 옮기기만 하는 관. **가지관을 내지 않고 구역이 없다.**
    재질(material)을 갖는다 — hose50·hose40(송수호스) · pipe(수도 파이프) · buried(매설·기설).
    pipe·buried 는 **관경(d_mm)을 모르면 설계를 진행하지 않는다**(불변 원칙 1 · [미확정]).
  · 주배관 = 분배점에서 밭으로 들어가 가지관을 분기하는 관. 한 선 = 한 운전 구역(zone 필수).
  · **분배점은 주배관의 끝에만 있지 않다**(대표 2026-09-08). 인입관 끝이 주배관 **중간**에 T 로 붙어
    좌우로 갈라져도 되고, 주배관을 접점 쪽으로 그려 **끝점**이 만나도 된다.
    연결 판정은 `mainline.analyze` 가 **양쪽 끝 모두**를 보고, 분배점은 그 관이 **물을 받는 자리**다.
  · `role` 이 없는 옛 데이터는 **zone 이 None 이면 인입관, 있으면 주배관**으로 읽는다 — 승인본 03 무수정.
"""
from __future__ import annotations

import math
from typing import Dict, List

SCHEMA = "looperget.design.site/1"

ROLES = ("feeder", "main")
FEEDER_MATERIALS = ("hose50", "hose40", "pipe", "buried")
FEEDER_HOSE_NOMINAL = {"hose50": 50, "hose40": 40}       # 송수호스 재질 → 호칭(mm)
ROLE_LABEL = {"feeder": "인입관", "main": "주배관"}
MATERIAL_LABEL = {"hose50": "송수호스 50", "hose40": "송수호스 40", "pipe": "수도 파이프", "buried": "매설관(기설)"}


def route_role(r: Dict) -> str:
    """경로의 역할. `role` 이 없으면 zone 으로 읽는다(옛 데이터 호환)."""
    role = r.get("role")
    if role in ROLES:
        return role
    return "feeder" if r.get("zone") is None else "main"


def feeder_d_mm(r: Dict):
    """인입관의 계산 내경(mm). 호스는 카탈로그 실물 내경, pipe·buried 는 대표가 적은 d_mm. 모르면 None."""
    from . import pipes
    m = r.get("material") or "hose50"
    if m in FEEDER_HOSE_NOMINAL:
        item = pipes.by_nominal(FEEDER_HOSE_NOMINAL[m])
        return float(item["id_mm"]) if item else None
    d = r.get("d_mm")
    if isinstance(d, bool):
        return None
    try:
        d = float(d)
    except (TypeError, ValueError, OverflowError):
        return None
    return d if math.isfinite(d) and d > 0 else None


def validate(site: Dict) -> Dict:
    """필수 항목·형식 검사. 문제가 있으면 ValueError — 미확정 입력으로는 설계를 진행하지 않는다(불변 원칙 1)."""
    errs: List[str] = []
    if site.get("schema") != SCHEMA:
        errs.append(f"schema != {SCHEMA}")
    blocks = site.get("blocks") or []
    if not blocks:
        errs.append("blocks 비어 있음")
    for b in blocks:
        poly = b.get("polygon") or []
        if len(poly) < 3:
            errs.append(f"block '{b.get('name')}': polygon 점 3개 미만")
        u = b.get("u")
        if not u or len(u) != 2 or (u[0] == 0 and u[1] == 0):
            errs.append(f"block '{b.get('name')}': u(열 방향) 없음")
    routes = site.get("routes") or []
    if not routes:
        errs.append("routes 비어 있음 — 주배관 경로는 대표 입력(규칙 13)")
    for r in routes:
        if len(r.get("pts") or []) < 2:
            errs.append(f"route '{r.get('name')}': pts 2점 미만")
        if r.get("role") not in (None,) + ROLES:
            errs.append(f"route '{r.get('name')}': role '{r.get('role')}' — feeder/main 중 하나")
            continue
        if "zone" not in r and "role" not in r:  # 옛 데이터: zone 키 자체가 없으면 판단 불가
            errs.append(f"route '{r.get('name')}': zone 없음 — 운전 구역은 대표 판단(규칙 6)")
            continue
        role = route_role(r)
        r["role"] = role
        if role == "feeder":                     # 규칙 21 — 인입관은 구역이 없고 재질을 갖는다
            r["zone"] = None
            m = r.get("material") or "hose50"
            if m not in FEEDER_MATERIALS:
                errs.append(f"인입관 '{r.get('name')}': material '{m}' — {'/'.join(FEEDER_MATERIALS)} 중 하나")
            r["material"] = m
            if m in ("pipe", "buried"):
                d = feeder_d_mm(r)
                if d is None:
                    errs.append(f"인입관 '{r.get('name')}': {MATERIAL_LABEL[m]} 관경(d_mm) [미확정] — "
                                "유한한 양수 내경(mm)이 필요하다. 모르면 설계를 진행하지 않는다(불변 원칙 1)")
                else:
                    r["d_mm"] = d
        elif r.get("zone") is None:
            errs.append(f"주배관 '{r.get('name')}': 구역(zone) 없음 — 인입관이면 role='feeder'(규칙 21)")
    for b in blocks:                              # 작물은 선택 항목 — 모르면 비운다(대표 지시 2026-09-05)
        c = b.get("crop")
        if c is not None and (not isinstance(c, str) or not c.strip()):
            errs.append(f"block '{b.get('name')}': crop 은 비어 있지 않은 문자열이어야 한다")
    if not site.get("sources"):
        errs.append("sources 비어 있음")
    for w in site.get("water_items", []):
        if not w.get("code") or int(w.get("qty", 0)) <= 0:
            errs.append(f"water_items 항목 불량: {w}")
    if errs:
        raise ValueError("site 입력 오류: " + " / ".join(errs))
    # zones None = 대표가 적지 않았다 → 분배점에서 나가는 주배관의 구역 수로 엔진이 센다(규칙 21 · #79).
    # 대표가 적은 값(0 포함)은 그대로 우선한다.
    site.setdefault("valves_01403", {"start": 1, "zones": None})
    site.setdefault("water_items", [])
    crops = sorted({b["crop"].strip() for b in blocks if b.get("crop")})
    if crops:                                     # 지역·작물별 축적을 위해 한곳에 모아 둔다
        site["crops"] = crops
    return site

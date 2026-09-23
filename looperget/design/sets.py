# -*- coding: utf-8 -*-
"""
looperget.design.sets — 이 설계가 쓰는 **연결부 세트**를 세고, 시트에 없으면 **신설 후보**를 만든다.

대표 지시 2026-09-09 —
  「세트는 앞으로 내가 등록하지 않을거야. **엔진이 제안서를 만드는 것을 보고, 교정을 만들거나 할 때,
   세트화가 필요한 경우 엔진이 세트를 만들 수 있도록 해.**」

지금까지는 규칙 8 이 「없으면 `[세트 신설 제안]`으로 적고 **set-builder 에 올린다**」였다 — 사람이 올렸다.
이제 **엔진이 그 후보를 만들어 낸다.** 다만 두 가지는 여전히 사람 몫이고, 그 경계를 흐리지 않는다:

  🔴 **Sets 시트는 건드리지 않는다**(규칙 8 · set-builder 는 프로덕션 무반영). 여기서 나오는 것은 **제안**이다.
  🔴 **이름의 정본은 명명 규칙**(B안 · 결정 #35 · `tools/set_name.py`)이다. 그 규칙은 연결부 **사양**
     (다리마다의 재질·등급·밸브·성별)에서 이름을 만드는데, 배치 엔진은 그 사양을 다 알지 못한다.
     그래서 여기서는 **잠정 이름**을 내고 「규칙 미적용」이라고 밝힌다 — 틀린 이름을 확정처럼 내면
     「같은 이름 = 같은 물건」이 깨진다(그 사고가 정정을 두 번 냈다 · #33·#36).

조합(레시피)의 정본은 **`bom.py`(승인 견적 5필지 역산)** 이다. 여기서 새로 만들지 않고 그대로 읽는다.
"""
from __future__ import annotations

import json
from typing import Dict, List, Optional, Sequence

from . import pipes
from . import heads as _heads
from .summary import SETS

SCHEMA = "looperget.design.sets/1"
PROPOSE_MARK = "[세트 신설 제안]"

# 형상 — 명명 규칙 B안의 형상 기호와 같은 뜻으로 쓴다(1 직선 · L 90도 · T 3구).
SHAPE = {"straight": "1", "elbow": "L", "tee": "T", "end": "E", "head": "H", "branch": "B"}


def _recipe_of(db_entry: Dict) -> Dict[str, int]:
    """Sets 시트의 레시피를 {코드: 수량}으로 편다. 시트는 {코드: {name,spec,qty}} 형식이다."""
    out: Dict[str, int] = {}
    for code, v in (db_entry.get("recipe") or {}).items():
        c = str(code).strip().zfill(5)
        if isinstance(v, dict):
            out[c] = int(v.get("qty", 0) or 0)
        else:
            try:
                out[c] = int(v)
            except (TypeError, ValueError):
                continue
    return {c: q for c, q in out.items() if q > 0}


def index(sets_db: Optional[Dict]) -> Dict[str, List[Dict]]:
    """Sets 시트 → {레시피 서명: [{name, cat, gov}]}. 같은 조합이면 같은 서명이다.

    gov = 시트 「관급등록여부」 Y(조달용으로 만든 세트). 🔴 **조달 등록 완료가 아니다** — 등록 상태·물품식별번호는
    `관급_등록정보` 시트가 정본이고 이 앱은 그 시트를 읽지 않는다(2026-06 등록 진행 중 · 번호 일부 미확인).
    """
    idx: Dict[str, List[Dict]] = {}
    for cat, group in (sets_db or {}).items():
        if not isinstance(group, dict):
            continue
        for name, info in group.items():
            if not isinstance(info, dict):
                continue
            rcp = _recipe_of(info)
            if rcp:
                idx.setdefault(signature(rcp), []).append(
                    {"name": name, "cat": cat, "gov": str(info.get("gov_registered") or "").strip().upper() == "Y"})
    return idx


def is_gov(site: Optional[Dict]) -> bool:
    """관급(공공조달) 현장인가 — [V117 · 3차 검토 D4] 대상 종류 한 곳(segments.segment_of) 기준.
    site.segment 가 있으면 그것(농업 + 옛 channel 관급 → 농업) · 없으면 옛 job 규칙(channel 관급 → 관급). 모르면 일반."""
    from .segments import segment_of
    return segment_of(site) == "관급"


def rank(hits: List[Dict], site: Optional[Dict]) -> List[Dict]:
    """같은 조합의 시트 세트들 — 관급이면 조달용 세트(gov)를 앞에. 일반이면 시트 순서 그대로."""
    return sorted(hits, key=lambda h: 0 if h.get("gov") else 1) if is_gov(site) else list(hits)


GOV_STATUS = "조달용 세트(시트 관급등록여부 Y) — 조달 등록 상태·물품식별번호는 관급_등록정보 시트에서 확인"


def gov_pick(site: Optional[Dict], sets_db: Optional[Dict], kit: Optional[Dict] = None) -> Dict:
    """관급 현장의 헤드 세트 — 지금 헤드 구성과 **같은 조합**의 조달용 세트를 고른다. 없으면 사유와 대안.

    → {"channel", "picked": name|None, "why", "near": [같은 살수기종의 조달용 세트 이름]}.
    🔴 모델명·구성·가격을 만들지 않는다 — 시트에 있는 이름만 돌려준다. 조합이 다르면 고르지 않는다.
    [V117 · K-04] kit = BOM 이 실제로 쓰는 헤드 구성(summary.head_kit_used). 없으면 site.head_kit(예전 동작).
    """
    kit = kit or _heads.resolve(site)
    out = {"channel": "관급" if is_gov(site) else "일반", "picked": None, "why": "", "near": [], "kit": kit.get("key")}
    if not is_gov(site):
        return out
    if kit.get("key") in ("mixed", "unknown"):
        out["why"] = ("열별 헤드 구성이 섞여 있어 세트 하나로 고르지 않았습니다 — 열별 연결 구성표 참조"
                      if kit.get("key") == "mixed" else "헤드 구성 [미확정] — 조달용 세트를 대조하지 못했습니다")
        return out
    if not sets_db:
        out["why"] = "Sets 시트 미연결 — 조달용 세트를 대조하지 못했습니다"
        return out
    hits = [h for h in index(sets_db).get(signature(dict(kit["recipe"])), []) if h["gov"]]
    if hits:
        out.update(picked=hits[0]["name"], why=GOV_STATUS)
        return out
    model = str(kit.get("label") or "")
    for cat, group in sets_db.items():
        for name, info in (group or {}).items() if isinstance(group, dict) else ():
            hm = str((info or {}).get("head_model") or "").split()
            if (isinstance(info, dict) and str(info.get("gov_registered") or "").upper() == "Y"
                    and hm and hm[-1] in model):
                out["near"].append(name)
    out["why"] = ("지금 헤드 구성(%s)과 같은 조합의 조달용 세트가 시트에 없습니다%s"
                  % (kit.get("short") or kit.get("label"),
                     " — 같은 살수기종의 조달용 세트: " + " · ".join(out["near"]) if out["near"] else ""))
    return out


def signature(recipe: Dict[str, int]) -> str:
    """레시피의 서명 — 코드·수량이 같으면 같은 세트다(이름과 무관)."""
    return "+".join("%s×%d" % (c, q) for c, q in sorted(recipe.items()))


def used(design: Dict, site: Dict, kit: Optional[Dict] = None) -> List[Dict]:
    """이 설계가 쓰는 **연결부 묶음**과 개소. 조합은 `bom.py` 규칙 그대로다(새로 만들지 않는다).
    kit = BOM 이 쓰는 헤드 구성(V117 · K-04). 없으면 site.head_kit. 이름 정본(summary.SETS["head"])은 01998 조합일 때만."""
    hk = kit or _heads.resolve(site)
    main = design.get("mainline") or {}
    mm = int(site.get("main_mm") or pipes.APPROVED_MAIN_MM)
    F = pipes.main_fittings(mm)
    v = site.get("valves_01403") or {}
    zone_v = int(main.get("header_valves") or 0) if v.get("zones") is None else int(v.get("zones") or 0)
    start_v = int(v.get("start", 1) or 0)
    n_lat = int(design.get("n_laterals") or 0)
    # 🔴 [V114 · F01] summary.SETS 의 주배관 세트 이름은 **50 mm 조합의 이름**이다. 40 mm 에 그 이름을 붙이면
    #    다른 물건을 같은 이름으로 부르게 된다 — 50 이 아니면 이름 정본을 쓰지 않고 시트 대조·신설 후보로 보낸다.
    _k = lambda key: key if mm == pipes.APPROVED_MAIN_MM else None
    rows = [
        {"key": "head", "label": "스프링클러 헤드", "n": int(design.get("n_heads") or 0),
         "recipe": dict(hk["recipe"]), "shape": SHAPE["head"], "mm": None,
         "set_key": "head" if dict(hk["recipe"]) == dict(_heads.KITS["01998"]["recipe"]) else None,
         "where": "헤드마다"},
        {"key": "tee%d" % mm, "label": "주배관 T 분기 (나가는 쪽 2갈래)", "n": int(main.get("tees") or 0),
         "recipe": {"01201": 1, F["wf42"]: 2, "00278": 4}, "shape": SHAPE["tee"], "mm": mm, "set_key": _k("tee50"),
         "where": "관이 세 갈래로 만나는 자리"},
        {"key": "join%d" % mm, "label": "주배관 일자 연결 (롤 이음)", "n": int(main.get("joints") or 0),
         "recipe": {F["wf41"]: 1, F["wf42"]: 1, "00278": 4}, "shape": SHAPE["straight"], "mm": mm, "set_key": _k("join50"),
         "where": "50 m 롤이 끝나 잇는 자리"},
        {"key": "end%d" % mm, "label": "주배관 말단 마감", "n": int(main.get("ends") or 0),
         "recipe": {F["e_valve"]: 1, "00278": 2}, "shape": SHAPE["end"], "mm": mm, "set_key": _k("end50"),
         "where": "관이 끝나는 자리(규칙 1)"},
        {"key": "zonev%d" % mm, "label": "구역 밸브", "n": zone_v,
         "recipe": {F["e_valve"]: 1, "00278": 2}, "shape": SHAPE["end"], "mm": mm, "set_key": _k("end50"),
         "where": "분배점마다 구역 수(규칙 21)"},
        {"key": "start%d" % mm, "label": "시작부 밸브", "n": start_v,
         "recipe": {F["e_valve"]: 1, "00278": 2}, "shape": SHAPE["end"], "mm": mm, "set_key": _k("end50"),
         "where": "급수점 바로 뒤"},
        {"key": "branch25", "label": "가지관 분기 (타공 + 지관밸브)", "n": n_lat,
         "recipe": {"01924": 1, "01786": 1}, "shape": SHAPE["branch"], "mm": 25, "set_key": "branch25",
         "where": "가지관 열마다"},
        {"key": "end25", "label": "가지관 말단 마감", "n": n_lat,
         "recipe": {"02000": 1}, "shape": SHAPE["end"], "mm": 25, "set_key": "end25",
         "where": "가지관 열 끝마다"},
    ]
    return [r for r in rows if r["n"] > 0]


def provisional_name(row: Dict) -> str:
    """**잠정** 이름. 정본은 명명 규칙(B안 · #35)이고 이것은 그 자리를 채우는 임시 이름이다."""
    body = "+".join("%s×%d" % (c, q) for c, q in sorted(row["recipe"].items()))
    mm = ("-%d" % row["mm"]) if row.get("mm") else ""
    return "%s %s%s %s" % (PROPOSE_MARK, row["shape"], mm, body)


def propose(design: Dict, site: Dict, sets_db: Optional[Dict] = None) -> Dict:
    """이 설계의 연결부를 Sets 시트와 대조 → **쓰인 세트**와 **신설 후보**를 낸다.

    🔴 시트는 읽기만 한다. 등록은 사람이 한다(규칙 8).
    """
    idx = index(sets_db)
    hit, miss = [], []
    merged: Dict[str, Dict] = {}
    for row in used(design, site):
        sig = signature(row["recipe"])
        item = dict(row, signature=sig,
                    recipe_text=" + ".join("%s×%d" % (c, q) for c, q in sorted(row["recipe"].items())))
        known = SETS.get(row.get("set_key") or "")
        found = idx.get(sig) or []
        if known and known != PROPOSE_MARK:
            item.update(name=known, cat="세트 정본", status="이름 정본에 있음(summary.SETS)")
            hit.append(item)
        elif found:
            f0 = rank(found, site)[0]
            item.update(name=f0["name"], cat=f0["cat"], status="Sets 시트에 있음" + (" · 조달용" if f0.get("gov") else ""))
            hit.append(item)
        else:
            # 같은 조합은 **한 세트**다 — 말단·구역밸브·시작부처럼 쓰임새가 달라도 물건은 같다.
            m = merged.get(sig)
            if m:
                m["n"] += row["n"]
                if row["where"] not in m["where"]:
                    m["where"] += " · " + row["where"]
                if row["label"] not in m["label"]:
                    m["label"] += " · " + row["label"]
                continue
            item.update(name=provisional_name(row), cat="[제안]",
                        status="없음 — **신설 후보**",
                        name_rule="미적용 — 이름의 정본은 명명 규칙(B안 · 결정 #35)입니다")
            merged[sig] = item
            miss.append(item)
    # 부속을 아직 모르는 자리 — 레시피를 만들 수 없다. 지어내지 않고 그대로 세운다.
    unknown = []
    for j in (design.get("mainline") or {}).get("junctions") or []:
        if j["kind"] == "elbow":
            unknown.append({"why": "꺾임 %.0f° — %s" % (j.get("dev_deg") or 0,
                                                       "호스면 규칙 3(T 양쪽) · 파이프면 엘보"),
                            "pt": j["pt"], "routes": j["routes"], "materials": j["materials"]})
        elif j["mixed"]:
            unknown.append({"why": "재질이 바뀌는 자리 — " + " / ".join(j["materials"]),
                            "pt": j["pt"], "routes": j["routes"], "materials": j["materials"]})
    return {"schema": SCHEMA, "in_sheet": hit, "propose": miss, "unknown": unknown,
            "n_sheet": len(hit), "n_propose": len(miss), "n_unknown": len(unknown)}


def to_sheet_rows(result: Dict) -> List[Dict]:
    """신설 후보 → Sets 시트 열에 맞춘 줄(사람이 붙여 넣는다). **여기서 시트에 쓰지 않는다.**"""
    out = []
    for r in result.get("propose", []):
        out.append({"세트명": r["name"], "카테고리": "[제안]", "하위분류": r["label"],
                    "이미지파일명": "", "설명": "%s · %s (%d개소)" % (r["where"], r["recipe_text"], r["n"]),
                    "레시피JSON": json.dumps({c: {"qty": q} for c, q in r["recipe"].items()},
                                             ensure_ascii=False)})
    return out


__all__ = ["SCHEMA", "PROPOSE_MARK", "SETS", "GOV_STATUS", "index", "is_gov", "rank", "gov_pick", "signature", "used",
           "provisional_name", "propose", "to_sheet_rows"]

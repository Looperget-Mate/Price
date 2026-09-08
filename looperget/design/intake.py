# -*- coding: utf-8 -*-
"""
looperget.design.intake — 접수(문진표) → 설계 입력 `site` (§5 행 2 · P3 흐름의 첫 칸).

접수 방식은 **통화로 주소를 받아 우리가 그려서 확인받는다**(대표 확답 #43·#44). 그래서 흐름은
이렇게 돈다 — 이 모듈은 ①과 ④를 맡는다:

    ① 문진표      intake.QUESTIONS 를 순서대로 묻는다 (주소·급수·구역·작물…)
    ② 작도판      mapsrc.draft_from_address(주소) → 위성 위 판 PNG → 농민 확인
    ③ 블록        mapsrc.blocks_from_pixels(...) → blocks · 대표가 주배관·구역을 그린다
    ④ site 조립   intake.to_site(답변, 작도결과) → design.site.validate 통과 여부

🔴 **비어 있는 칸을 채우지 않는다.** 답이 없으면 `site` 를 불완전한 채로 내고
   `design.site.validate` 가 거부하게 둔다 — 그것이 맞는 동작이다(불변 원칙 1).
   추정으로 메운 급수 유량·구역 배치는 **땅에 묻힌 뒤에 드러난다.**

🟠 **가용 유량·수압은 필수이되 넘어갈 수 있다**(대표 지시 2026-09-07). 현장에서 못 재는 일이
   흔하기 때문이다. 다만 넘어가는 것은 **선택이 아니라 기록**이다 — `check(answers, waived=[...])`
   로 뜻을 밝혀야 하고, 무엇을 모른 채 설계했는지 `site["intake"]["waived"]` 에 남는다.

각 문항의 `왜` 는 **코드가 그 값을 어디서 쓰는지**다. 사람이 정한 항목(규칙 6·7·12·13)은
엔진이 만들지 않는 입력이라 문진표가 유일한 출처다.
"""
from __future__ import annotations

from typing import Dict, List, Optional, Sequence

from . import site as _site

SCHEMA = "looperget.design.intake/1"

# 🔴 `req` = 없으면 설계하지 않는다 · 🟠 `waivable` = 필수지만 **뜻을 밝히면 넘어갈 수 있다**.
# 나머지는 비어도 진행하되 `[미확정]` 으로 남는다.
QUESTIONS: List[Dict] = [
    # ── A. 접수 ──
    {"key": "address", "group": "접수", "req": True,
     "ask": "설치하실 밭 **지번**을 불러 주세요 (예: 논산시 상월면 상도리 482-42).",
     "why": "mapsrc.geocode → PNU → 필지 폴리곤·위성 프레임. 읍·면을 추측해 붙이지 않는다."},
    {"key": "customer", "group": "접수", "req": False,
     "ask": "성함과 연락처를 알려 주세요. 작도판을 보내 드리고 확인받겠습니다.",
     "why": "작도판 회신 경로. 설계에는 쓰이지 않는다."},

    # ── B. 대상지 ──
    {"key": "crop", "group": "대상지", "req": False,
     "ask": "무엇을 심으십니까? (작물 · 모르면 비워 둡니다)",
     "why": "site.blocks[].crop → 지역·작물별 축적(대표 지시 2026-09-05). 열 간격을 만들지는 않는다."},
    {"key": "n_blocks", "group": "대상지", "req": False,
     "ask": "밭이 몇 개로 나뉘어 있습니까? 사이에 **통로**가 있습니까?",
     "quick": ["나뉘지 않음", "통로 없음", "나뉘지 않음 · 통로 없음"],
     "why": "blocks 개수 · 통로는 주배관 공유로 표현한다(#42 — 스키마 무수정)."},
    {"key": "elev_note", "group": "대상지", "req": False,
     "ask": "밭 안에 **높낮이 차**가 있습니까? 있다면 어디가 몇 m쯤 높습니까?",
     "quick": ["없음"],
     "why": "hydro.select_diameter(elev_drop_m). 🔴 DEM 은 폐기했다 — **소비자 고지·실측만** 쓴다(#44)."},

    # ── C. 급수 — 여기가 설계의 전부를 결정한다 ──
    {"key": "source_kind", "group": "급수", "req": True,
     "ask": "물은 어디서 옵니까?",
     "choices": ["관정", "상수도", "하천·저수지", "물탱크", "기타"], "other": "기타",
     "why": "site.sources · water_items(규칙 7). 급수원이 정해져야 계통 부속 규격이 정해진다."},
    {"key": "source_where", "group": "급수", "req": True,
     "ask": "급수 지점이 밭의 **어느 쪽**입니까? 밭 가장 먼 끝까지 대략 몇 m입니까?",
     "why": "site.sources[].pt · 주배관 길이 → 마찰손실 → 관경 선정."},
    {"key": "pump", "group": "급수", "req": False,
     "ask": "펌프가 있습니까? 있다면 **명판의 모델명**을 읽어 주세요.",
     "why": "site.pump → hydro_zone.zone_point(실제 운전점). 없으면 요구 사양만 내고 펌프는 [미확정]."},
    {"key": "flow_lpm", "group": "급수", "req": True, "waivable": True,
     "ask": "쓸 수 있는 물의 양이 얼마입니까? (분당 L · 관정 양수량 · 수도 계량기)",
     "why": "동시 살수 두수의 상한. 이것이 없으면 「몇 두를 한 번에 돌릴 수 있는가」를 "
            "펌프 곡선만으로 짐작하게 된다 — 급수원이 펌프보다 약하면 그 짐작이 틀린다."},
    {"key": "pressure_bar", "group": "급수", "req": True, "waivable": True,
     "ask": "수압이 얼마입니까? (bar 또는 kgf/㎠)",
     "why": "hydro_zone 입구압. 펌프가 있으면 곡선이 대신하지만, 상수도·자연낙차처럼 "
            "펌프가 없는 급수원은 이 값이 유일한 입구압이다."},
    {"key": "supply_mm", "group": "급수", "req": False,
     "ask": "급수 배관 굵기가 몇 mm입니까? 노출된 관 끝이 있습니까?",
     "why": "급수 인터페이스 부속(WF 4-4 등) 규격. 확인 전에는 견적 비고로 남긴다."},

    # ── D. 운전 ──
    {"key": "zones_wish", "group": "운전", "req": False,
     "ask": "한 번에 밭 **전체**에 물을 주시겠습니까, **나눠서** 주시겠습니까?",
     "choices": ["한 번에", "되도록 한 번에", "나눠서", "기타"], "other": "기타",
     "why": "site.routes[].zone(운전 구역 · 규칙 6) — 대표 판단이고 엔진이 만들지 않는다."},
    {"key": "auto", "group": "운전", "req": False,
     "ask": "밸브를 사람이 여닫아도 됩니까, 자동이 필요하십니까?",
     "choices": ["수동", "자동"],
     # 🔴 대표 확답 2026-09-07 — 「자동은 우리가 현재로서는 대응이 잘 안 돼」.
     #    고른 자리에서 바로 말한다. 못 하는 것을 견적 뒤에 알리면 그건 사고다.
     "warn_if": {"자동": "🔴 **자동 제어는 현재 대응이 어렵습니다**(대표 확답 2026-09-07). "
                         "수동 밸브로 설계하고, 자동이 꼭 필요하시면 **별건으로 협의**합니다."},
     "why": "valves_01403 · 자동 밸브 품목. 구역이 여럿이면 사람이 매번 돌려야 한다."},

    # ── E. 기존 시설 ──
    {"key": "existing", "group": "기존", "req": False,
     "ask": "지금 쓰시는 관수 시설이 있습니까? (스프링클러 · 점적 · 살수차 · 매설관)",
     "why": "기존 매설관은 무절단 분기 대상이 될 수 있다. 활용 여부는 대표 판단."},
]

# 🔵 통화로 자주 나오는 답은 **버튼**으로 받는다(대표 지시 2026-09-07 · #61).
#    `choices` = 보기(고른 문자열이 그대로 답) · `other` = 직접 입력을 여는 보기 이름
#    `quick`   = 자유 입력 위의 한 번에 채우기 단추 · `warn_if` = 그 답을 고르면 그 자리에서 알릴 사실
#    🔴 **버튼은 문항을 바꾸지 않는다** — 답의 형식은 여전히 문자열이고 `to_site` 는 그대로 읽는다.
# 🔵 [V104] **유량은 숫자만으로는 유량이 아니다** — 시간 단위가 있어야 한다.
#    자유 입력에서 못 읽는 일이 잦다(대표 실사용 2026-09-08 — 「최대 양수량 340리터」를 적었는데
#    엔진이 못 읽고 「10톤 물탱크는 부피다」라는 **예시 문구**만 떠서 오해가 났다).
#    그래서 화면이 **숫자 + 단위**로도 받게 하고, 그 조합을 여기 적힌 틀로 문자열에 넣는다.
#    🔴 문항의 형식은 그대로 문자열이다 — `to_site` 도 `parse_flow_lpm` 도 손대지 않는다.
UNITS = {
    "flow_lpm": [("분당 L (L/min)", "%s L/분"),
                 ("시간당 m3 (루베)", "%s m3/h"),
                 ("시간당 톤", "%s t/h")],
}

CHOICES = {q["key"]: q["choices"] for q in QUESTIONS if q.get("choices")}
QUICK = {q["key"]: q["quick"] for q in QUESTIONS if q.get("quick")}
WARN_IF = {q["key"]: q["warn_if"] for q in QUESTIONS if q.get("warn_if")}

REQUIRED = [q["key"] for q in QUESTIONS if q["req"]]

# 🔴 **필수지만 뜻을 밝히면 넘어갈 수 있는 칸**(대표 지시 2026-09-07:
#    「가용유량과 수압을 필수로 올려. 그대신, 상황에 따라서 무시하고 진행할 수도 있게해줘」).
#    넘어가는 것은 **선택이 아니라 기록**이다 — 무엇을 모른 채 설계했는지 `site["intake"]` 에 남고
#    설계 경고로도 따라 나간다. 주소·급수원·급수 지점은 넘어갈 수 없다(엔진이 아예 못 돈다).
WAIVABLE = [q["key"] for q in QUESTIONS if q["req"] and q.get("waivable")]


def _blank(v) -> bool:
    return v is None or (isinstance(v, str) and (not v.strip() or v.strip() == "[미확정]"))


def check(answers: Dict, waived: Optional[Sequence[str]] = None) -> Dict:
    """문진표 진단 — 무엇이 비었는지 **먼저** 말한다. 채우지는 않는다.

    `waived` = **뜻을 밝히고 넘어가기로 한** 칸(`WAIVABLE` 안에서만). 넘어간 칸은 `ok` 를
    막지 않지만 `waived` 로 남고 `warn` 에 「모른 채 진행」이 붙는다.
    """
    w = [k for k in (waived or []) if k in WAIVABLE and _blank(answers.get(k))]
    bad_w = sorted({k for k in (waived or []) if k not in WAIVABLE})
    missing = [q for q in QUESTIONS
               if q["req"] and _blank(answers.get(q["key"])) and q["key"] not in w]
    optional = [q for q in QUESTIONS if not q["req"] and _blank(answers.get(q["key"]))]
    byk = {q["key"]: q for q in QUESTIONS}
    warn = ["%s — **모른 채 진행한다**(대표 판단). %s" % (byk[k]["ask"], byk[k]["why"]) for k in w]
    if bad_w:
        warn.append("넘어갈 수 없는 칸입니다: %s — 이 값이 없으면 엔진이 아예 돌지 않습니다."
                    % ", ".join(bad_w))
    if missing:
        verdict = "필수 %d칸이 비었다 — 채우기 전에는 설계하지 않는다(불변 원칙 1)" % len(missing)
    elif w:
        verdict = "설계 착수 가능 — 다만 %d칸을 **모른 채** 간다(%s)" % (len(w), ", ".join(w))
    else:
        verdict = "설계 착수 가능 — 다음은 작도판이다"
    return {
        "schema": SCHEMA,
        "ok": not missing,
        "missing": [q["key"] for q in missing],
        "waived": w,
        "waivable": list(WAIVABLE),
        "ask_next": missing[0]["ask"] if missing else None,
        "blank_optional": [q["key"] for q in optional],
        "warn": warn,
        "verdict": verdict,
    }


def to_site(answers: Dict, drawn: Optional[Dict] = None, name: Optional[str] = None,
            waived: Optional[Sequence[str]] = None) -> Dict:
    """문진표 답변 + 작도 결과 → `site`.

    `drawn` = {"blocks": [...], "routes": [...], "sources": [...], "water_items": [...]?}
    — ②③에서 나온다(작도판 화소 → `mapsrc.blocks_from_pixels`, 주배관·구역은 대표가 그린다).

    🔴 **없는 것은 비운 채로 낸다.** `validate=True` 로 부르면 `site.validate` 가 거부한다.
    """
    d = drawn or {}
    crop = answers.get("crop")
    blocks = []
    for b in (d.get("blocks") or []):
        b = dict(b)
        # 🔴 작물은 **모르면 비운다.** 빈 칸은 「모른다」의 표현이지 값이 아니다 — 화면이 빈 칸을
        #    ""로 넘기면 `site.validate` 가 「비어 있지 않은 문자열이어야 한다」로 설계를 막았다
        #    (대표 실사용 2026-09-08 · 지도로 그린 밭은 전부 crop="" 이었다).
        if _blank(b.get("crop")):
            b.pop("crop", None)
        if not _blank(crop) and b.get("crop") is None:
            b["crop"] = str(crop).strip()          # 작물은 문진표가 유일한 출처다
        blocks.append(b)
    site = {
        "schema": _site.SCHEMA,
        "name": name or answers.get("address") or "[미확정]",
        "blocks": blocks,
        "routes": list(d.get("routes") or []),
        "sources": list(d.get("sources") or []),
        "water_items": list(d.get("water_items") or []),
    }
    if d.get("valves_01403"):
        site["valves_01403"] = dict(d["valves_01403"])
    if not _blank(answers.get("pump")):
        site["pump"] = {"model": str(answers["pump"]).strip()}
    if d.get("main_mm"):                            # 주배관 호칭(#49) — 기본은 bom 이 50 을 쓴다
        site["main_mm"] = int(d["main_mm"])
    c = check(answers, waived)
    site["intake"] = {"schema": SCHEMA, "answers": dict(answers), "check": c,
                      "waived": c["waived"], "warn": c["warn"]}
    return site


def validate(answers: Dict, drawn: Optional[Dict] = None, name: Optional[str] = None,
             waived: Optional[Sequence[str]] = None) -> Dict:
    """`to_site` + `site.validate`. 통과하면 그대로 설계에 넣을 수 있다."""
    s = to_site(answers, drawn, name, waived)
    c = s["intake"]["check"]
    if not c["ok"]:
        raise ValueError("문진표 필수 칸이 비었다: %s — %s" % (", ".join(c["missing"]), c["verdict"]))
    return _site.validate(s)


def script() -> str:
    """통화용 대본 — 순서대로 읽으면 된다."""
    out, group = [], None
    for q in QUESTIONS:
        if q["group"] != group:
            group = q["group"]
            out.append("\n[%s]" % group)
        mark = "🔴" if q["req"] else "  "
        if q.get("waivable"):
            mark = "🟠"                      # 필수지만 뜻을 밝히면 넘어갈 수 있다
        out.append("%s %s" % (mark, q["ask"]))
    return "\n".join(out).strip()


__all__ = ["SCHEMA", "QUESTIONS", "REQUIRED", "WAIVABLE", "UNITS",
           "check", "to_site", "validate", "script"]

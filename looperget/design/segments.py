# -*- coding: utf-8 -*-
"""
looperget.design.segments — 대상 종류(🌾 농업 · 🏛️ 관급 · 🏗️ 건설·조경) 프로필 **한 곳** (V117 2단계 · 결정 #98).

🔴 세 종류는 **각각 따로 선다.** 한 창에서 하는 현장 작업(파크골프장 = 관급)의 규칙 — 당사 현장답사 화자 · 조달 세트 ·
   QC 연결 도해 · 네이비 표지 — 을 농업 경로나 공통 기본값으로 끌어오지 않는다. **농업은 지금 흐름이 기준**이다(프로필 = 전부 끔).
🔴 관급·건설 **전용 뼈대(표지·화자·원가계산서)는 없다**(3단계_확장_사양 S3-3 — 원본 수집 전). 지금은 농업 마스터 +
   머리글 라벨·기능 게이트만 다르다. 화면은 「전용 지면은 준비 중」 한 줄로 알린다.

순수 함수·상수만 — 파일·전역 상태 없음.
  segment_of(site)  → "농업" | "관급" | "건설·조경"   (옛 job: site.channel == "관급" → 관급, 없으면 농업)
  profile(x)        → 그 종류의 프로필(dict 복사본) — x = site dict 또는 종류 이름
  from_answer(s)    → 문진 보기 글자(「🏛️ 관급」 등) → 종류 이름 | None
"""
from __future__ import annotations

import copy
from typing import Dict, Optional, Union

DEFAULT = "농업"
ORDER = ("농업", "관급", "건설·조경")

# 관급·건설 머리글 — 09-18 설명서 §6 「관급·건설은 『농가 표기』 대신 『발주처 · 현장명 · 담당』으로 표지·견적 머리글이 바뀝니다」
HEAD_ORDERER = ("발주처", "현장명", "담당")
NOTICE = "전용 지면은 준비 중 — 지금은 농업 지면에 머리글만 바꿔 냅니다(표지·화자·원가계산서 없음)"

SEGMENTS: Dict[str, Dict] = {
    "농업": {
        "icon": "🌾", "choice": "🌾 농업(노지)",
        "channel": None,          # 조달 세트 우선 = 끔
        "photo_gate": False,      # 현장 사진 = 선택 · 없어도 아무 표시 없음
        "head": None,             # 표지·견적 머리글 = 현행 그대로(농가 표기)
        "quote_code": True,       # 고객본 견적서 품목 코드 칸 = 보임(현행)
        "notice": "",
    },
    "관급": {
        "icon": "🏛️", "choice": "🏛️ 관급",
        "channel": "관급",        # V116 조달 세트 우선 경로(sets.is_gov · summary.connections · sets.gov_pick)
        "photo_gate": True,       # 사진 0장 = 관문 확인 항목
        "head": HEAD_ORDERER,
        "quote_code": False,      # 고객본 견적서 품목 코드 칸 숨김(재검토 §3-2 「관급본은 XLSX 품목 코드도 제외」)
        "notice": NOTICE,
    },
    "건설·조경": {
        "icon": "🏗️", "choice": "🏗️ 건설·조경",
        "channel": None,
        "photo_gate": True,
        "head": HEAD_ORDERER,
        "quote_code": True,
        "notice": NOTICE,
    },
}

_ALIAS = {"농업": "농업", "노지": "농업", "농업(노지)": "농업", "일반": "농업",
          "관급": "관급", "공공": "관급", "건설·조경": "건설·조경", "건설": "건설·조경", "조경": "건설·조경",
          "건설·조경 현장": "건설·조경"}


def choices():
    """문진 보기(맨 위 「대상 종류」) — 순서 고정."""
    return [SEGMENTS[k]["choice"] for k in ORDER]


def from_answer(s) -> Optional[str]:
    """문진 답(보기 글자·이름·별칭) → 종류 이름. 모르면 None(= 기본을 쓰는 쪽이 정한다)."""
    t = str(s or "").strip()
    if not t:
        return None
    for k, v in SEGMENTS.items():
        if t == v["choice"]:
            return k
    t2 = t.lstrip("🌾🏛️🏗️️ ").strip()
    return _ALIAS.get(t2) or _ALIAS.get(t)


def segment_of(site: Optional[Dict]) -> str:
    """site → 대상 종류. site.segment 가 없으면 옛 job 규칙: channel 관급 → 관급 · 그 밖 → 농업."""
    s = site or {}
    k = from_answer(s.get("segment"))
    if k:
        return k
    return "관급" if str(s.get("channel") or "").strip() == "관급" else DEFAULT


def profile(x: Union[Dict, str, None]) -> Dict:
    """종류 프로필(복사본) + "key". x = site dict 또는 종류 이름(모르면 농업)."""
    k = segment_of(x) if isinstance(x, dict) or x is None else (from_answer(x) or DEFAULT)
    return dict(copy.deepcopy(SEGMENTS[k]), key=k)


def head_line(prof: Dict, orderer: str = "", site_name: str = "", manager: str = "", blank: str = "________") -> Optional[str]:
    """관급·건설 표지 한 줄 「발주처 … · 현장명 … · 담당 …」(값이 없으면 밑줄). 농업이면 None(현행 그대로)."""
    h = prof.get("head")
    if not h:
        return None
    vals = [orderer, site_name, manager]
    return " · ".join("%s %s" % (lab, (str(v).strip() or blank)) for lab, v in zip(h, vals))


__all__ = ["DEFAULT", "ORDER", "SEGMENTS", "HEAD_ORDERER", "NOTICE", "choices", "from_answer", "segment_of",
           "profile", "head_line"]

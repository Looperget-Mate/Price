# -*- coding: utf-8 -*-
"""
looperget.design.lines — 「줄」로 물을 주는 자재(점적테이프 · 점적호스)의 사양 정본과 줄 수리 (V113 · 결정 #93).

    from looperget.design import lines
    lines.line_flow_lpm("그린드립", length_m=100, spacing_cm=20)      # 8.33 L/분 (구멍 500 × 1 L/h)
    lines.line_check("블랙드립", length_m=100, spacing_cm=30)         # 줄 유량 · 마찰 손실 · 필요한 입구압

값의 출처는 **대표 확답 2026-09-22** 뿐이다(제조사 사양표는 없다) — 구멍당 토출 · 내경 16 mm · 기준 압력 1 bar.
조사 기록 = `10_프로매니저/작업/20260922_사양정본/사양정본_조사결과.md` §3.

🔴 이 모듈은 **줄 한 개의 유량과 손실**까지만 답한다. 밭에 줄을 까는 배치 엔진은 아직 없다 —
   그래서 `site.SYSTEM_READY` 에 drip 을 올리지 않았다(없는 엔진을 있는 척하지 않는다 · 불변 원칙 1).
🔴 **분수호스는 여기 없다.** 필름에 바늘구멍을 뚫는 제품이라 제조사(신농 포함)가 유량을 싣지 않는다 —
   유량 근거가 없는 자재는 수리 계산 대상이 아니다. 필요해지면 자체 실측값으로만 등록한다.
🔴 줄 **최대 길이**는 내지 않는다 — 균등도 기준(처음·끝 구멍의 토출 차 허용치)이 대표 결정 사항이다.
"""
from __future__ import annotations

from typing import Dict

from .. import hydro as H

SCHEMA = "looperget.design.lines/1"
SOURCE = "대표 확답 2026-09-22 (결정 #93)"

# q_lph = 구멍 한 개의 토출(L/h) @ p_ref_bar · id_mm = 내경 · compensated = 압력보상 여부(None = 모름)
LINE_PROFILES: Dict[str, Dict] = {
    "그린드립": {"kind": "tape", "label": "점적테이프 그린드립 (검정 필름)",
              "q_lph": 1.0, "p_ref_bar": 1.0, "id_mm": 16.0, "compensated": None, "source": SOURCE},
    "화이트드립": {"kind": "tape", "label": "점적테이프 화이트드립 (안 검정 · 밖 흰색)",
               "q_lph": 1.0, "p_ref_bar": 1.0, "id_mm": 16.0, "compensated": None, "source": SOURCE},
    "블랙드립": {"kind": "inline", "label": "인라인 점적호스 블랙드립",
              "q_lph": 2.0, "p_ref_bar": 1.0, "id_mm": 16.0, "compensated": None,
              "source": SOURCE + " — 「2 L/h 내외」 · 내경 16 mm(외경 아님)"},
}


def profile(name: str) -> Dict:
    if name not in LINE_PROFILES:
        raise ValueError("줄 자재 '%s' 의 사양이 등록되지 않았다 — %s 중 하나(불변 원칙 1·2)"
                         % (name, " · ".join(LINE_PROFILES)))
    return LINE_PROFILES[name]


def emitters(length_m: float, spacing_cm: float) -> int:
    """줄 길이와 구멍 간격 → 구멍 수."""
    if length_m <= 0 or spacing_cm <= 0:
        raise ValueError("줄 길이와 구멍 간격은 0보다 커야 한다")
    return int(length_m * 100.0 // spacing_cm)


def line_flow_lpm(name: str, length_m: float, spacing_cm: float) -> float:
    """줄 한 개의 유량(L/분) = 구멍 수 × 구멍당 토출 — 기준 압력에서."""
    return emitters(length_m, spacing_cm) * profile(name)["q_lph"] / 60.0


def line_check(name: str, length_m: float, spacing_cm: float) -> Dict:
    """줄 한 개 — 유량 · 마찰 손실(Christiansen) · 끝 구멍이 기준 압력을 받으려면 필요한 입구압."""
    p = profile(name)
    n = emitters(length_m, spacing_cm)
    q = n * p["q_lph"] / 60.0
    hf = H.lateral_loss_m(q, p["id_mm"], length_m, n) if n else 0.0
    return {"schema": SCHEMA, "name": name, "label": p["label"], "n_emitters": n,
            "q_lpm": round(q, 2), "q_lph": round(q * 60.0), "loss_m": round(hf, 2),
            "p_end_bar": p["p_ref_bar"], "p_in_bar": round(p["p_ref_bar"] + H.head_m_to_bar(hf), 3),
            "id_mm": p["id_mm"], "source": p["source"],
            "note": "토출은 기준 압력의 값이다 — 압력보상 여부를 몰라 압력에 따른 토출 변화는 계산하지 않는다 [미확정]"}


__all__ = ["LINE_PROFILES", "profile", "emitters", "line_flow_lpm", "line_check", "SCHEMA", "SOURCE"]

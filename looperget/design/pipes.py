# -*- coding: utf-8 -*-
"""
looperget.design.pipes — 취급 관(송수호스) 정본과 관경 선정 (§5 행 1 ⓑ · 프로덕션 무수정).

    from looperget.design import pipes
    r = pipes.select_main(q_lpm=301, length_m=54.7, p_in_bar=2.64, p_end_min_bar=1.5)
    r["d_mm"]        # 50
    r["item"]        # {"code": "02051", "roll_m": 50, ...}

**물리 판정은 프로덕션 `looperget.hydro.select_diameter`가 한다.** 이 모듈이 갖는 것은 제품 데이터뿐이다.

정본 = Google Sheets `Looperget_DB` · `Products` 시트 세부카테고리 **송수호스**(2026-09-05 실측).
취급 관경은 **정확히 3종**이다 — 25 · 40 · 50 mm. 그보다 굵은 관은 **없다.**

🔴 **내경 — 25·40·50 은 전부 「호칭」이고 실물은 인치다.** 대표 확답 2026-09-06 (「25,50 모두 호칭이야.
   실제로는 인치 기준이야. 한국에서 인치가 익숙치 않아서야」). 이 제품군은 **인치 기반 레이플랫**이고
   (자사 공개 페이지: 「내면과 외면 사이에 고강력 폴리에스터사를 투입/융착」) 호칭 mm는 인치를 반올림한 이름이다.
   · 호칭 25 = **1″ = 25.4** · 호칭 40 = **1½″ = 38** · 호칭 50 = **2″ = 50.8** mm.
   · 40 은 대표 확답값 38.0 을 쓴다 — 인치 정확값 38.1 과 **11구역 선정 결과가 같다**(시험 4-2).
   · 25·50 은 호칭을 내경으로 쓰던 종전 값보다 **굵어 손실이 준다.** 11구역 말단압이 +0.03~0.09 bar
     오르지만 **관경 선정은 11/11 불변**이고 40 mm 로 내려가는 구역도 1개 그대로다(시험 2·4).

⚠ **`hydro_zone` 은 이 모듈에서 내경을 받는다**(2026-09-06 · #48). 신규 설계 = **실물 내경**
   (`MAIN_MM/LAT_MM` = 50.8/25.4) · 승인 정답지 재현 = **호칭**(`REPRO_MM` = 50/25)으로 갈라 뒀다.
   **정답지 JSON 은 재계산하지 않는다** — 승인본의 기록이자 재현 관문의 기준점이다(불변 원칙 5·6).

✅ **부속 연동 완료**(2026-09-06 · #49 · 별건 처리). `bom.py` 가 주배관 호칭에 따라 `MAIN_FITTINGS`
   4자리(송수호스·E호스밸브·WF 4-1·WF 4-2)를 골라 쓴다 → **40 mm 도 `fittings_ready=True`.**
   가지관은 25 mm 고정 그대로다(`02044`·`20916`).
"""
from __future__ import annotations

from typing import Dict, List, Optional, Sequence

from .. import hydro as H

SCHEMA = "looperget.design.pipes/1"
SOURCE = "Products 시트 · 세부카테고리 송수호스 · 2026-09-05 실측"

# 규격 · 1롤길이 · 소비자가 = 시트 원문. id_mm 은 위 docstring의 가정.
PIPES: List[Dict] = [
    {"code": "02044", "name": "송수호스, 루퍼젯+", "spec": "25mm*100M",
     "nominal_mm": 25, "id_mm": 25.4, "roll_m": 100.0, "price": 125000, "verified": True,
     "id_source": "대표 확답 2026-09-06 — 호칭이다 · 1″ = 25.4 mm", "fittings_ready": True},
    {"code": "02070", "name": "송수호스, 루퍼젯+", "spec": "40mm*50M",
     "nominal_mm": 40, "id_mm": 38.0, "roll_m": 50.0, "price": 108000, "verified": True,
     "id_source": "대표 확답 2026-09-06 — 1½″ = 38 mm (정확값 38.1 과 결과 동일)", "fittings_ready": True},
    {"code": "02051", "name": "송수호스, 루퍼젯+", "spec": "50mm*50M",
     "nominal_mm": 50, "id_mm": 50.8, "roll_m": 50.0, "price": 133000, "verified": True,
     "id_source": "대표 확답 2026-09-06 — 호칭이다 · 2″ = 50.8 mm", "fittings_ready": True},
]

# 승인본이 실제로 쓴 조합(2026-09-05 정답지) — 재현 기준이다. **호칭**이다(내경은 50.8 · 25.4).
APPROVED_MAIN_MM = 50
APPROVED_LATERAL_MM = 25

# 🔴 **주배관 관경에 묶인 부속 — 이 4자리만 호칭을 따라간다**(2026-09-06 · #49 · 별건 처리 완료).
# 근거 = `_세트재생성/S1_사양표_v1.json` 의 `관경A/관경B` + Products 시트 규격. 이름·형태가 같고
# 규격만 40/50 으로 갈리는 1:1 대응이다(WF 4-1 · WF 4-2 · E호스밸브 · 송수호스).
#
# **관경에 묶이지 않는 것**(그래서 여기에 없다 · #41 대표 확답 「루퍼젯 기술가이드를 확인해」):
#   · `01924` 루퍼젯 H25 — 기술가이드 **H시리즈 20~75 mm 커버**. 감기는 관 굵기는 부속 사양이 아니다.
#   · `02038`·`20916` 케이블타이 — **설치단계(용도)**가 정한다(주배관·분기·수원부 vs 살수·가지관).
#   · `01201` CCCT 中 — 규격이 **16~50** 범위다.   · `00278` 호스밴드 — **2¼″(33~57)** 범위다.
MAIN_FITTINGS = {
    40: {"hose": "02070", "e_valve": "01402", "wf41": "00824", "wf42": "00826"},
    50: {"hose": "02051", "e_valve": "01403", "wf41": "00825", "wf42": "00827"},
}


def main_candidates() -> List[float]:
    """**주배관**으로 쓸 수 있는 내경 목록 — 부속이 성립하는 관경만이다(40·50 → 38.0 · 50.8).

    가지관 최소인 25 mm 는 여기 없다. 카탈로그에 25 mm 주배관 부속이 있기는 하지만
    (`01206` E호스밸브 · `01733` WF 4-1 · `01727` WF 4-2 — 전부 「25mm 소」) **승인 사례가 없어**
    대응을 확정하지 않았다. 필요해지면 `MAIN_FITTINGS` 에 한 줄 더하면 된다(데이터 확인 후).
    """
    return sorted(p["id_mm"] for p in PIPES if int(p["nominal_mm"]) in MAIN_FITTINGS)


def main_fittings(nominal_mm: int) -> Dict[str, str]:
    """주배관 **호칭** → 그 관경에 묶인 부속 4자리. 취급하지 않는 관경이면 멈춘다(불변 원칙 1)."""
    n = int(round(float(nominal_mm)))
    if n not in MAIN_FITTINGS:
        raise ValueError(
            "주배관 호칭 %s mm 의 부속 대응이 없다 — 취급은 40·50 뿐이다. "
            "25 mm 를 주배관으로 쓴 승인 사례가 없어 값을 지어내지 않는다(불변 원칙 1)." % nominal_mm)
    return dict(MAIN_FITTINGS[n])

# 유속 권장 상한. **탈락선이 아니라 경고선**이다 — hydro.select_diameter docstring 참조.
V_WARN = 2.0


def by_diameter(d_mm: Optional[float]) -> Optional[Dict]:
    """내경 → 품목. 없으면 None."""
    if d_mm is None:
        return None
    for p in PIPES:
        if abs(p["id_mm"] - float(d_mm)) < 1e-9:
            return p
    return None


def by_nominal(n_mm: Optional[float]) -> Optional[Dict]:
    """**호칭** → 품목. 사람과 시트는 호칭(25·40·50)으로 부르고 계산은 내경으로 한다."""
    if n_mm is None:
        return None
    for p in PIPES:
        if int(p["nominal_mm"]) == int(round(float(n_mm))):
            return p
    return None


def price_per_m(p: Dict) -> float:
    """m당 소비자가 — 관경을 낮췄을 때 얼마가 주는지를 말할 수 있어야 한다."""
    return p["price"] / p["roll_m"]


def candidates(fittings_ready_only: bool = True) -> List[float]:
    """고를 수 있는 내경 목록.

    **세 관경 모두 부속 연동이 끝났다**(#49) — 기본 후보 = 25·40·50 전부.
    `fittings_ready` 플래그와 이 인자는 **새 관경을 들일 때 다시 쓰기 위해 남겨 둔다.**
    """
    return [p["id_mm"] for p in PIPES if (p.get("fittings_ready", True) or not fittings_ready_only)]


def _select(q_lpm: float, length_m: float, p_in_bar: float, p_end_min_bar: float,
            n_outlets: int, elev_drop_m: float, fittings_ready_only: bool,
            only_mm: Optional[Sequence[float]] = None) -> Dict:
    cands = list(only_mm) if only_mm else candidates(fittings_ready_only)
    r = H.select_diameter(q_lpm, length_m, cands, p_in_bar, p_end_min_bar,
                          n_outlets=n_outlets, elev_drop_m=elev_drop_m, v_warn=V_WARN)
    item = by_diameter(r["d_mm"])
    r["schema"] = SCHEMA
    r["item"] = item
    r["source"] = SOURCE
    if item is not None:
        r["price_per_m"] = round(price_per_m(item), 1)
        r["rolls"] = -(-length_m // item["roll_m"]) if length_m else 0
        if not item["verified"]:
            r["warn"] = list(r["warn"]) + [
                "%d mm 는 내경이 확인되지 않았다 — 확인 전에는 채택하지 않는다(불변 원칙 2)"
                % item["nominal_mm"]]
        if not item.get("fittings_ready", True):
            r["warn"] = list(r["warn"]) + [
                "%d mm 는 **부속 연동이 아직 열리지 않았다** — BOM 처리 전에는 채택하지 않는다"
                % item["nominal_mm"]]
        if item["nominal_mm"] != APPROVED_MAIN_MM and n_outlets == 0:
            r["warn"] = list(r["warn"]) + [
                "주배관 %d mm 는 **승인 시공 사례가 없다**(승인본은 전부 호칭 %d) — "
                "`site[\"main_mm\"]=%d` 로 넣어야 BOM 부속이 따라간다(#49). 채택은 설계 판단이다."
                % (item["nominal_mm"], APPROVED_MAIN_MM, item["nominal_mm"])]
    return r


def select_main(q_lpm: float, length_m: float, p_in_bar: float,
                p_end_min_bar: float = 1.5, elev_drop_m: float = 0.0,
                fittings_ready_only: bool = True,
                only_mm: Optional[Sequence[float]] = None) -> Dict:
    """주배관 관경 — 중간 분출이 없는 단일 관로.

    `only_mm` 으로 후보를 좁힐 수 있다 — **승인본이 실제로 검토한 관경만 놓고 재현**할 때 쓴다."""
    return _select(q_lpm, length_m, p_in_bar, p_end_min_bar, 0, elev_drop_m,
                   fittings_ready_only, only_mm)


def select_lateral(q_lpm: float, length_m: float, n_heads: int, p_in_bar: float,
                   p_end_min_bar: float = 1.5, elev_drop_m: float = 0.0,
                   fittings_ready_only: bool = True,
                   only_mm: Optional[Sequence[float]] = None) -> Dict:
    """가지관 관경 — 헤드가 균등 분출하므로 Christiansen F 가 걸린다."""
    if n_heads < 1:
        raise ValueError("n_heads 는 1 이상이어야 한다")
    return _select(q_lpm, length_m, p_in_bar, p_end_min_bar, n_heads, elev_drop_m,
                   fittings_ready_only, only_mm)


def id_note(d_mm: float) -> Optional[str]:
    """그 관경의 내경 근거 한 줄 — 값이 어디서 왔는지 말할 수 있어야 한다."""
    p = by_diameter(d_mm)
    return None if p is None else "%d mm 호칭 → 내경 %.1f mm (%s)" % (
        p["nominal_mm"], p["id_mm"], p.get("id_source", "출처 미기재"))


def savings_per_m(from_mm: float, to_mm: float) -> Optional[float]:
    """관경을 낮췄을 때 m당 절감액(원). 품목이 없으면 None."""
    a, b = by_diameter(from_mm), by_diameter(to_mm)
    return None if (a is None or b is None) else round(price_per_m(a) - price_per_m(b), 1)


__all__ = ["SCHEMA", "SOURCE", "PIPES", "V_WARN",
           "APPROVED_MAIN_MM", "APPROVED_LATERAL_MM",
           "by_diameter", "by_nominal", "price_per_m", "candidates", "id_note",
           "MAIN_FITTINGS", "main_fittings", "main_candidates",
           "select_main", "select_lateral", "savings_per_m"]

# -*- coding: utf-8 -*-
"""
looperget.design.bom — 설계 결과 → 자재 목록(코드·수량). 가격은 quote.py.

수량 규칙(정본 = `_설계/배추밭스프링클러_20260824/설계규칙` design-system.md 1~18 · 승인 견적 5필지 역산):
  · 헤드 01998 = 두수 → 여분 3 %          · 가지관 25 mm 02044 = 절단 계획 롤 수(100 m, 여분 없음)
  · 25 mm 일자 01999 = 절단 계획 이음 수  · 열마다 01924(피팅)·01786(밸브)·02000(마감) = 열 수 → 여분 5 %
  · 주배관 = ceil(총길이/50)               · E호스밸브 = 시작 + 구역밸브 + 말단(규칙 1) → 여분
  · 🔴 **주배관 관경에 묶인 부속 4자리**(송수호스·E호스밸브·WF 4-1·WF 4-2)는 `pipes.MAIN_FITTINGS`
    가 호칭(`site["main_mm"]` · 기본 50)으로 고른다(#49). 나머지는 관경에 묶이지 않는다 —
    `01924`(H시리즈 20~75 커버) · `02038`·`20916`(설치단계) · `01201`(16~50) · `00278`(2¼″ 33~57).
  · T세트(규칙 8) = 01201 + 00827×2 + 00278×4 — **나가는 쪽 2갈래만** 센다(대표 실물 확인 2026-09-04).
    들어오는 쪽은 WF 4-4(00969) 1 + 밴드 2인데 규격이 급수원 인터페이스에서 정해지므로 `water_items`(규칙 7)에 둔다.
  · 일자연결 = 00825 + 00827 + 00278×4 · 말단·구역밸브 = 00278×2
  · `site["spare_field"] = {코드: 수량}` = **현장 예비**(대표 판단 입력 · 규칙 19의 여분과 별개)
  · 케이블타이(규칙 17) 02038 = (열 + 게이지 새들)·2·1.5 → 10단위, 20916 = (두수+2)·2·1.5 → 10단위 (규칙 18: 견적 포함)
  · 테프론 00955 = 열·2 → 10단위           · 여분(_spare): 수량 < 2 · 여분 제외 코드는 그대로, 아니면 ceil(·1.05)
  · 여분 산정 정본 = 규칙 19 (헤드 3 % · 부속 5 % · 롤 여유 12 % · 케이블타이 ×1.5 10단위 · 테프론 열×2)
  · 대표 계통도 품목(규칙 7: 펌프측 커플러·여과기·압력계·매니폴드)은 site["water_items"]를 그대로 통과
  · 변형엘보 00190 은 만들지 않는다(규칙 2).
"""
from __future__ import annotations

import math
from typing import Dict, List, Sequence

from . import pipes
from .mainline import ROLL_M

NO_SPARE = {"20002", "01909", "00527", "01870"}      # 펌프·여과기·압력계 — 여분 없음
SPARE_RATE = {"01998": 1.03}                          # 헤드는 3 %
LAT_ROLL_M = 100.0
ROLL_SLACK = 0.12    # 규칙 19 — 롤 절단 계획의 남는 길이가 롤의 12 % 이하(25 mm 12 m · 50 mm 6 m)면 여분 1롤.
                     # 승인 견적 03(50 mm 남는 4 m)·04(25 mm 남는 10 m) 역산. 5필지 열 번의 판정 중
                     # 이 두 번만 발동하고 둘 다 정답과 일치(오발동 0). 대표 확정 2026-09-03.


def _spare(code: str, qty: int) -> int:
    if code in NO_SPARE or qty < 2:
        return qty
    return math.ceil(qty * SPARE_RATE.get(code, 1.05) - 1e-9)


def _up10(n: float) -> int:
    return int(math.ceil(n / 10.0 - 1e-9) * 10)


def lat_rolls_and_joints(lengths: Sequence[float], roll: float = LAT_ROLL_M):
    """25 mm 100 m 롤 절단 계획: 긴 열부터, 남은 토막이 0.5 m 넘으면 이어 쓴다(이음 1)."""
    rolls, joints, rem = 1, 0, roll
    for L in sorted(lengths, reverse=True):
        if L <= rem + 1e-9:
            rem -= L
        elif rem > 0.5:
            rolls += 1
            joints += 1
            rem = roll - (L - rem)
        else:
            rolls += 1
            rem = roll - L
    return rolls, joints


def build(n_heads: int, lat_lengths: Sequence[float], main: Dict, site: Dict) -> List[Dict]:
    """→ [{"code","qty","base","note"}] (같은 코드는 합산).

    주배관 호칭은 `site["main_mm"]`(기본 **50** — 승인본과 같다). 40 을 주면 그 관경에 묶인
    부속 4자리가 40 mm 품목으로 바뀐다(#49)."""
    n_lat = len(lat_lengths)
    main_mm = int(site.get("main_mm") or pipes.APPROVED_MAIN_MM)
    F = pipes.main_fittings(main_mm)
    v = site.get("valves_01403", {})
    start_v = int(v.get("start", 1))
    # 규칙 21(#79) — 구역 밸브 수: 대표가 적었으면 그 값(0 포함), 아니면 **분배점에서 엔진이 센다**.
    if v.get("zones") is None:
        zone_v, zone_v_src = int(main.get("header_valves") or 0), "분배점 파생"
    else:
        zone_v, zone_v_src = int(v["zones"]), "대표 입력"
    src_bands = sum(int(s.get("start_bands", 0)) for s in site.get("sources", []))
    tees, ends, joints = main["tees"], main["ends"], main["joints"]
    water = list(site.get("water_items", []))
    gauge_saddles = sum(int(w["qty"]) for w in water if w["code"] in ("01920", "01919"))

    rolls25, joints25 = lat_rolls_and_joints(lat_lengths)
    lat_total = sum(lat_lengths)
    slack25 = rolls25 * LAT_ROLL_M - lat_total
    extra25 = 1 if slack25 <= ROLL_SLACK * LAT_ROLL_M else 0
    # 규칙 21 — 호칭이 다른 **호스 인입관**은 제 호칭 롤로 따로 산다. 파이프·매설 인입관은 자재가 아니다.
    other_hose = {int(n): m for n, m in (main.get("feeder_hose_m") or {}).items() if int(n) != main_mm}
    # 다른 호칭의 인입관 롤 이음도 그 호칭 부속으로 산출한다. 밴드 총수는 그대로다.
    from .site import FEEDER_HOSE_NOMINAL
    other_joints: Dict[int, int] = {}
    for r in main.get("routes", []):
        n = FEEDER_HOSE_NOMINAL.get(r.get("material")) if r.get("role") == "feeder" else None
        if n is not None and n != main_mm:
            other_joints[n] = other_joints.get(n, 0) + int(r.get("joints") or 0)
    main_joints = joints - sum(other_joints.values())
    same_m = main["total_m"] - sum(other_hose.values())
    rolls50 = math.ceil(same_m / ROLL_M - 1e-9) if same_m > 0 else 0
    slack50 = rolls50 * ROLL_M - same_m
    extra50 = 1 if (rolls50 and slack50 <= ROLL_SLACK * ROLL_M) else 0
    rows: List[Dict] = []

    def put(code, base, note, spare=True):
        qty = _spare(code, base) if spare else base
        if qty > base:
            note = f"{note} + 여분 {qty - base}"
        rows.append({"code": code, "qty": qty, "base": base, "note": note})

    put("01998", n_heads, f"헤드 {n_heads}두")
    put("02044", rolls25 + extra25, f"25 mm 가지관 {lat_total:.0f} m → 100 m 롤 절단 계획 {rolls25}"
        + (f" + 여분 1(남는 길이 {slack25:.0f} m)" if extra25 else ""), spare=False)
    put("01999", joints25, "25 mm 롤 잇는 자리(절단 계획)", spare=False)
    put("01924", n_lat, f"가지관 {n_lat}열 — 주배관 20 mm 타공 분기")
    put("01786", n_lat, f"가지관 {n_lat}열 — 열마다 밸브")
    put("02000", n_lat, f"가지관 {n_lat}열 말단 마감")
    feed_note = (f"(주배관 {main.get('main_m', main['total_m'])} m + 호스 인입관 {main['feeder_hose_m'][main_mm]} m)"
                 if (main.get("feeder_hose_m") or {}).get(main_mm) else "")
    if rolls50:
        put(F["hose"], rolls50 + extra50, f"주배관 {main_mm} mm {same_m:.1f} m{feed_note} → 50 m 롤 {rolls50}"
            + (f" + 여분 1(남는 길이 {slack50:.0f} m)" if extra50 else ""), spare=False)
    for n, m in sorted(other_hose.items()):
        rolls = math.ceil(m / ROLL_M - 1e-9)
        slack = rolls * ROLL_M - m
        extra = 1 if rolls and slack <= ROLL_SLACK * ROLL_M else 0
        put(pipes.main_fittings(n)["hose"], rolls + extra,
            f"인입관 송수호스 {n} mm {m:.1f} m → 50 m 롤 {rolls}(규칙 21)"
            + (f" + 여분 1(남는 길이 {slack:.0f} m)" if extra else ""), spare=False)
    put(F["e_valve"], start_v + zone_v + ends,
        f"시작 {start_v} + 구역밸브 {zone_v}({zone_v_src}) + 말단 마감 {ends}")
    if tees:
        put("01201", tees, f"T {tees}")
    if 2 * tees + main_joints:
        put(F["wf42"], 2 * tees + main_joints, f"T 나가는 쪽 2×{tees} + 일자 {main_joints}")
    if main_joints:
        put(F["wf41"], main_joints, f"주배관·동일 호칭 인입관 잇는 자리 {main_joints} — 일자연결 세트")
    for n, count in sorted(other_joints.items()):
        if count:
            fittings = pipes.main_fittings(n)
            put(fittings["wf41"], count, f"인입관 {n} mm 잇는 자리 {count} — 일자연결 세트")
            put(fittings["wf42"], count, f"인입관 {n} mm 일자 {count}")
    put("00278", src_bands + 2 * ends + 4 * tees + 4 * joints + 2 * zone_v,
        f"시작 {src_bands} + 말단 2×{ends} + T 4×{tees} + 일자 4×{joints} + 구역밸브 2×{zone_v}")
    put("02038", _up10((n_lat + gauge_saddles) * 2 * 1.5), "주배관·분기 고정 — 루퍼젯 H25·H20 부속마다 2개 (여유 1.5배)", spare=False)
    put("20916", _up10((n_heads + 2) * 2 * 1.5), "25 mm 가지관 고정 — 헤드마다 2개 (여유 1.5배)", spare=False)
    put("00955", _up10(n_lat * 2), "나사 연결부 — 열마다 2", spare=False)
    for w in water:
        rows.append({"code": w["code"], "qty": int(w["qty"]), "base": int(w["qty"]),
                     "note": w.get("note", "급수 계통 부속 — 대표 계통도 그대로")})

    # ── 현장 예비(규칙 7 계열 · 대표 판단 입력) ──
    # 규칙 19의 「여분」과 다르다. 여분은 자재 성질에서 나오는 계산이고,
    # 이것은 **그 현장에서 대표가 더 넣기로 한 수량**이다 — 산식이 없으므로 코드가 만들지 않고 입력으로 받는다.
    # 근거: 승인 5필지의 01999 예비가 0·0·2·1·4로 규칙을 이루지 않는다(2026-09-04 실측).
    for code, n in (site.get("spare_field") or {}).items():
        n = int(n)
        if n <= 0:
            continue
        rows.append({"code": str(code).zfill(5), "qty": n, "base": 0,
                     "note": "현장 예비 %d (대표 판단 · 산식 아님)" % n})

    merged: Dict[str, Dict] = {}
    for r in rows:
        if r["code"] in merged:
            m = merged[r["code"]]
            m["qty"] += r["qty"]; m["base"] += r["base"]; m["note"] += " · " + r["note"]
        else:
            merged[r["code"]] = dict(r)
    return list(merged.values())

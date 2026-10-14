# -*- coding: utf-8 -*-
"""
looperget.design.fountain — 스프링클러 설계에 붙는 「분수 라인」(2026-10-08 · 정창주 남해 765 · 대표 A안).

    site["fountain_lines"] = [{"name": "분수 1", "pts": [[x,y], ...]}, ...]      # 로컬 m · 첫 점 = 주배관에서 따는 자리
    (줄마다 품목을 바꾸려면 "tap"/"valve"/"hose"/"end" 에 코드를 준다 — 없으면 아래 기본 구성)

구성(대표 2026-10-08): 송수호스에 **루퍼젯 H25(01924)** 체결 → **분수숫싱글밸브 25mm*6~7cm(00771)**
→ **분수호스 저설용(신농) 7cm*200M(00834)** → 끝 **분수 회전마감꽂이(00939)**. 줄마다 H25·밸브·마감꽂이 1,
호스 = ⌈전체 길이 ÷ 200 m⌉ 롤. **여분 없음**(대표 2026-10-08 「여분은 빼」).

🔴 **물 계산은 하지 않는다.** 분수호스는 제조사(신농 포함)가 유량을 싣지 않는다(lines.py · 사양정본 조사 09-22 §3-2).
   길이·수량만 코드가 세고 유량·압력은 [미확정]으로 둔다(불변 원칙 1). 스프링클러 수리(hydro_zone)에 섞지 않는다.
   그래서 운전 조건이 붙는다 — 분수를 열 때는 스프링클러를 잠그고, 분수숫싱글밸브를 조금 열고 시작해 높이를 맞춘다
   (대표 통화 2026-10-08: 스프링클러 2 bar 넘어야 · 분수 1 bar 넘으면 안 됨 · 신농 저설 적정압 0.4 kgf/cm²).
"""
from __future__ import annotations

import math
from typing import Dict, List

from . import geom

DEFAULT = {"tap": "01924", "valve": "00771", "hose": "00834", "end": "00939"}
HOSE_ROLL_M = {"00834": 200.0}          # 분수호스 롤 길이(품목 규격 「7cm*200M」)
TAP_NEAR_M = 3.0                        # 첫 점이 주배관에서 이보다 멀면 경고(따는 자리 확인)
P_MAX_BAR = 1.0                         # 대표 통화 2026-10-08 「분수호스는 1바가 넘으면 안 돼요」
SOURCE = "대표 2026-10-08 (정창주 남해 765 · A안)"

OPERATING = [
    "분수호스는 제조사가 유량을 싣지 않아 물 계산(유량·압력)은 하지 않았습니다 — [미확정]",
    "분수와 스프링클러는 따로 엽니다 — 분수를 열 때는 스프링클러 밸브를 잠급니다",
    "분수숫싱글밸브를 조금 열고 시작해 물 높이를 맞춥니다 (분수호스 1 bar 이하 · 스프링클러는 2 bar 이상)",
]


def lines(site: Dict) -> List[Dict]:
    return list(site.get("fountain_lines") or [])


def validate(site: Dict) -> List[str]:
    """형식 오류 목록(빈 목록 = 통과). site.validate 가 부른다."""
    errs = []
    fl = site.get("fountain_lines")
    if fl is None:
        return errs
    if not isinstance(fl, list):
        return ["fountain_lines 는 목록이어야 한다"]
    for i, f in enumerate(fl, 1):
        nm = f.get("name") or "분수 %d" % i
        pts = f.get("pts") or []
        if len(pts) < 2:
            errs.append("분수 라인 '%s': pts 2점 미만" % nm)
        for k in ("tap", "valve", "hose", "end"):
            if k in f and not str(f[k]).strip():
                errs.append("분수 라인 '%s': %s 코드 비어 있음" % (nm, k))
        hose = str(f.get("hose") or DEFAULT["hose"]).zfill(5)
        if hose not in HOSE_ROLL_M:
            errs.append("분수 라인 '%s': 호스 %s 의 롤 길이가 등록되지 않았다(HOSE_ROLL_M)" % (nm, hose))
    return errs


def _route_dist(p, routes) -> float:
    best = float("inf")
    for r in routes:
        if r.get("role") != "main":
            continue
        pts = [tuple(q) for q in r.get("pts") or []]
        for a, b in zip(pts, pts[1:]):
            best = min(best, geom.seg_dist(tuple(p), a, b))
    return best


def analyze(site: Dict) -> Dict:
    """→ {"lines": [{name, pts, len_m, tap_gap_m, parts}], "total_m", "rolls": {hose: n}, "warnings", "operating"}."""
    out, warns = [], []
    for i, f in enumerate(lines(site), 1):
        pts = [tuple(map(float, q)) for q in f["pts"]]
        L = sum(geom.dist(a, b) for a, b in zip(pts, pts[1:]))
        parts = {k: str(f.get(k) or DEFAULT[k]).zfill(5) for k in DEFAULT}
        gap = _route_dist(pts[0], site.get("routes") or [])
        nm = f.get("name") or "분수 %d" % i
        if gap > TAP_NEAR_M:
            warns.append("분수 라인 '%s': 시작점이 주배관에서 %.1f m — H25 로 따는 자리를 확인하세요" % (nm, gap))
        out.append({"id": i, "name": nm, "pts": [list(p) for p in pts], "len_m": round(L, 1),
                    "tap_gap_m": None if gap == float("inf") else round(gap, 1), "parts": parts})
    by_hose: Dict[str, float] = {}
    for l in out:
        by_hose[l["parts"]["hose"]] = by_hose.get(l["parts"]["hose"], 0.0) + l["len_m"]
    rolls = {h: math.ceil(m / HOSE_ROLL_M[h] - 1e-9) for h, m in by_hose.items()}
    return {"lines": out, "total_m": round(sum(l["len_m"] for l in out), 1), "length_by_hose": by_hose,
            "rolls": rolls, "warnings": warns, "operating": list(OPERATING) if out else [], "source": SOURCE}


def bom_rows(fa: Dict) -> List[Dict]:
    """분수 라인 → BOM 행(여분 없음 · base = qty)."""
    rows = []
    ls = fa.get("lines") or []
    if not ls:
        return rows
    n = len(ls)
    for k, what in (("tap", "분수 라인 %d줄 — 송수호스 20 mm 타공 분기"), ("valve", "분수 라인 %d줄 — 줄마다 밸브"),
                    ("end", "분수 라인 %d줄 말단 마감")):
        cnt: Dict[str, int] = {}
        for l in ls:
            cnt[l["parts"][k]] = cnt.get(l["parts"][k], 0) + 1
        for code, q in cnt.items():
            rows.append({"code": code, "qty": q, "base": q, "note": what % q})
    for h, r in fa["rolls"].items():
        m = fa["length_by_hose"][h]
        rows.append({"code": h, "qty": r, "base": r,
                     "note": "분수호스 %.0f m(%d줄) → %.0f m 롤 %d (남는 길이 %.0f m)"
                     % (m, n, HOSE_ROLL_M[h], r, r * HOSE_ROLL_M[h] - m)})
    return rows

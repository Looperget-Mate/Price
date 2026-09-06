# -*- coding: utf-8 -*-
"""
looperget.design.quote — BOM에 단가를 붙여 견적 초안을 만든다 (금액 = Σ 수량·단가, 코드가 계산).

단가 정본은 프로덕션 `Looperget_DB` Products 시트. 여기서는 호출자가 넘긴 price_db
(`{code: {"name","spec","unit","소비자가",...}}`, 예: `10_계산/_단가_DB.json`)를 쓴다.
고객 대면 발행은 대표 전담 — 이 결과는 초안이다.
"""
from __future__ import annotations

from typing import Dict, List, Sequence


def price(bom: Sequence[Dict], price_db: Dict[str, Dict], tier: str = "소비자가") -> Dict:
    rows: List[Dict] = []
    missing: List[str] = []
    total = 0
    for b in bom:
        info = price_db.get(b["code"])
        if info is None or info.get(tier) is None:
            missing.append(b["code"])
            rows.append(dict(b, name="[미확정]", spec="", unit="", price=None, amount=None))
            continue
        unit_price = int(info[tier])
        amt = unit_price * int(b["qty"])
        total += amt
        rows.append(dict(b, name=info.get("name", ""), spec=info.get("spec", ""),
                         unit=info.get("unit", "EA"), price=unit_price, amount=amt,
                         cat=info.get("카테고리", ""), subcat=info.get("세부카테고리", "")))
    return {"tier": tier, "rows": rows, "mat": total, "svc": 0, "total": total, "missing": missing}

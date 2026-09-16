# -*- coding: utf-8 -*-
"""
looperget.design.heads — 스프링클러 **헤드 구성**(한 두에 무엇이 들어가는가).

지금까지 엔진은 헤드를 `01998`(루퍼젯+ 스프링클러 세트 · 뽁뽁이연결) 하나로 고정했다.
2026-09-15 용산리 932-2 변경(B안)에서 대표가 **이동식 구성**(H20 + 물호스 밸브소켓 + 427B + 물호스용 h지주대)을
지정했는데 엔진에 입력 칸이 없어 `01998` 행을 빼고 `water_items`로 4품목을 손으로 넣었다(log 09-15 (3)).
그 자리를 만든다 — **값은 만들지 않는다.** 구성은 대표가 고르고, 수량은 두수 × 두당 개수(+ 헤드 여분 3 %)로 코드가 센다.

  site["head_kit"] = "01998"(기본 · 없으면 이것) | "mobile_hose" | {"label", "recipe": {코드: 두당 개수}, "set"?}

품목 코드는 Products 시트가 정본이다(불변 원칙 2). 여기 적힌 코드는 **대표 지시(2026-09-15)** 그대로다 —
  H20 = 01920 · 물호스 밸브소켓 = 01902 · 스프링클러 헤드 427B = 00459 · 스프링클러 h 조립(물호스 연결) = 01889.
"""
from __future__ import annotations

from typing import Dict, Optional
import hashlib
import json

DEFAULT = "01998"

KITS: Dict[str, Dict] = {
    "01998": {
        "label": "루퍼젯+ 스프링클러 세트 — H20 + 뽁뽁이 + 지주대 + 427B",
        "short": "01998 세트",
        "recipe": {"01998": 1},
        "set": "[LSS]S-H20N427b",              # Sets 시트 등재 세트명(summary.SETS["head"])
        "hose_note": "지관 15 mm 타공 · 케이블타이 140 mm 헤드당 2개",
    },
    "mobile_hose": {
        "label": "이동식 — H20 + 물호스 밸브소켓 + 427B + h지주대(물호스용)",
        "short": "이동식 헤드",
        "recipe": {"01920": 1, "01902": 1, "00459": 1, "01889": 1},
        "set": "[세트 미등재]",                 # Sets 시트에 없다 — set-builder 제기 후보
        "hose_note": "밸브소켓–지주대 사이 물호스 없음 · 농가가 지주대를 옮겨 씀(열마다 몇 개만 둔다)",
    },
}


def resolve(site: Optional[Dict]) -> Dict:
    """site["head_kit"] → {"key","label","short","recipe","set","hose_note"}. 없거나 모르면 기본(01998)."""
    v = (site or {}).get("head_kit")
    if isinstance(v, dict) and v.get("recipe"):
        rcp = {str(c).zfill(5): int(n) for c, n in v["recipe"].items() if int(n) > 0}
        if not rcp:
            return dict(KITS[DEFAULT], key=DEFAULT)
        return {"key": str(v.get("key") or "custom"), "label": str(v.get("label") or "직접 구성"),
                "short": str(v.get("short") or v.get("label") or "직접 구성"), "recipe": rcp,
                "set": str(v.get("set") or "[세트 미등재]"), "hose_note": str(v.get("hose_note") or "")}
    key = str(v or DEFAULT)
    if key not in KITS:
        key = DEFAULT
    return dict(KITS[key], key=key)


def codes(site: Optional[Dict]) -> list:
    return list(resolve(site)["recipe"].keys())


def row_key(row: Dict) -> str:
    """Geometry identity, not array index. Changed layout requires an explicit remap."""
    value = [row.get("block"), *[[round(float(v), 1) for v in row[k]] for k in ("p0", "p1")]]
    return hashlib.sha256(json.dumps(value, ensure_ascii=False).encode()).hexdigest()[:20]


def row_groups(site: Dict, laterals: list) -> list:
    choices = site.get("row_kits") or {}
    valid = {row_key(row) for row in laterals}
    if set(choices) - valid:
        raise ValueError("열 배치가 바뀌었습니다. 열별 살수 세트를 다시 지정하세요")
    groups = {}
    for row in laterals:
        key = row_key(row)
        choice = choices.get(key, site.get("head_kit", DEFAULT))
        if isinstance(choice, str) and choice not in KITS:
            raise ValueError("알 수 없는 열별 살수 세트: " + choice)
        kit = resolve({"head_kit": choice})
        signature = json.dumps(kit, sort_keys=True, ensure_ascii=False)
        group = groups.setdefault(signature, {"kit": kit, "heads": 0, "rows": []})
        group["heads"] += row["n_heads"]
        group["rows"].append(row["id"])
        row["row_key"] = key
        row["head_kit"] = kit["key"]
    return list(groups.values())


__all__ = ["DEFAULT", "KITS", "resolve", "codes", "row_key", "row_groups"]

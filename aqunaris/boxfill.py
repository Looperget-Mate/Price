"""상자 채움 그림 — 기록된 수량만큼 부속을 상자 안에 그린다 (2026-10-04 · 대표 A안).

🔴 수량은 언제나 AQ_ItemBox 기록값이다. 이 모듈은 수량을 정하지 않는다 — 그 수량이
   상자 바닥에 어떻게 깔리는지 「참고 그림」과 격자 기준 넉넉함만 보여 준다.
부속 외형 = part_dims.json (tools/cad_sync.py · 설계 CAD 대표형 · 실측 아님 — 대표 결정 2026-10-04:
   부속은 공급사·생산 시기·제조사 개선으로 같은 코드도 형상이 달라 실측하지 않는다).
상자 안치수 = 한얼플라스틱 상품 상세 「사이즈 안내」(확인 2026-10-04 · 오차 ±5 mm) — 바닥(하) 기준으로 계산.
설계 개념(유량·헤드)과 무관 — looperget.design 을 import 하지 않는다.
"""
from __future__ import annotations

import json
import math
import os
from html import escape

_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "part_dims.json")
_DIMS = None

# 상자명: (외부 W·D·H, 안치수 상(폭·깊이), 안치수 하(폭·깊이), 안높이, 용량 L, 상품번호)
HE_BOXES = {
    "3호":     ((340, 210, 155), (320, 175), (280, 170), 150, 8, 167),
    "431-1호": ((480, 380, 150), (440, 340), (425, 325), 145, 20, 58),
    "432호":   ((480, 380, 200), (440, 335), (440, 335), 190, 27, 60),
    "6호":     ((500, 300, 200), (470, 260), (425, 255), 190, 20, 164),
}
HE_URL = "https://heplastic.co.kr/product/detail.html?product_no={}"
GROUP_FILL = {"스마트카플러": "#F3DC18", "조임식": "#3A3D44", "나사식": "#8A8F99",
              "점적": "#2F6FB3", "물호스": "#3C9A6B", "송수호스": "#C46A1A"}


def _dims():
    global _DIMS
    if _DIMS is None:
        try:
            with open(_PATH, encoding="utf-8") as fh:
                _DIMS = json.load(fh)
        except (OSError, ValueError):
            _DIMS = {"meta": {}, "parts": {}, "sku": {}}
    return _DIMS


def box_key(name):
    """앱 상자명 → HE_BOXES 키. '부품3호'·'431-1'·' 432 호' 모두 받는다. 모르면 None."""
    s = str(name or "").replace(" ", "").replace("부품", "")
    if s and not s.endswith("호"):
        s += "호"
    return s if s in HE_BOXES else None


def part_dims(code):
    """판매 코드 → {LWH_mm, name, group, label, basis}. CAD 에 없으면 None."""
    d = _dims()
    code = str(code or "").strip().zfill(5)
    sku = d["sku"].get(code)
    fam = (sku or {}).get("family", code)
    part = d["parts"].get(fam)
    if not part:
        return None
    lwh = (sku or {}).get("LWH_mm") or part["LWH_mm"]
    scaled = bool(sku and sku.get("scale") not in (None, 1, 1.0))
    return {"LWH_mm": lwh, "name": part.get("name"), "group": part.get("group"), "label": (sku or {}).get("label"),
            "basis": "설계 CAD 대표형" + (" · 규격 환산" if scaled else "")}


def fill_plan(lwh, box, qty):
    """눕혀 담기 격자 계획. 반환 per_layer·layers·cap·level(넉넉/빠듯/확인 필요)·눕힘 (a, b, h)."""
    key = box_key(box)
    if not key or not lwh or qty <= 0:
        return None
    _, _, (bw, bd), bh, _, _ = HE_BOXES[key]
    L, W, H = sorted(lwh, reverse=True)
    best = None
    for a, b, h in ((L, W, H), (L, H, W), (W, H, L)):            # 바닥에 닿는 두 변 + 높이
        for x, y in ((a, b), (b, a)):
            n = int(bw // x) * int(bd // y)
            lay = int(bh // h)
            if n and lay and (best is None or (n * lay, n) > (best["cap"], best["per_layer"])):
                best = {"per_layer": n, "max_layers": lay, "cap": n * lay, "foot": (x, y), "h": h, "nx": int(bw // x)}
    if not best:
        return {"box": key, "per_layer": 0, "layers": 0, "cap": 0, "level": "확인 필요", "qty": qty}
    layers = math.ceil(qty / best["per_layer"])
    level = "넉넉" if qty <= best["cap"] else "빠듯" if qty <= best["cap"] * 2 else "확인 필요"   # 막 담기면 격자보다 더 들어간다 — 경고가 아니라 참고
    return {**best, "box": key, "layers": layers, "level": level, "qty": qty, "inner": (bw, bd, bh)}


def fill_svg(code, box, qty, scale=1.3):
    """위에서 본 상자 바닥 그림(SVG 문자열)과 계획. CAD 외형이 없거나 상자를 모르면 (None, 사유)."""
    pdim = part_dims(code)
    if not pdim:
        return None, "설계 CAD 에 이 품목 모델이 없습니다 — 그림 없이 기록 수량만 씁니다."
    plan = fill_plan(pdim["LWH_mm"], box, int(qty or 0))
    if not plan:
        return None, "상자 안치수를 모르는 상자이거나 수량이 0입니다 (한얼 3호·6호·431-1호·432호만)."
    if not plan["per_layer"]:
        return None, f"이 부속({'×'.join(f'{v:.0f}' for v in pdim['LWH_mm'])} mm)은 {plan['box']}에 눕혀 담을 수 없습니다 — 상자 배정을 확인하세요."
    bw, bd, bh = plan["inner"]
    x0, y0 = 12, 12
    fx, fy = plan["foot"]
    color = GROUP_FILL.get(pdim["group"], "#0C3B81")
    shown_layers = min(plan["layers"], 3)
    els = []
    for k in range(min(plan["qty"], plan["per_layer"] * shown_layers)):
        layer, idx = divmod(k, plan["per_layer"])
        i, j = idx % plan["nx"], idx // plan["nx"]
        off = layer * 5
        x = x0 + (i * fx + 2) * scale + off
        y = y0 + (j * fy + 2) * scale + off
        w, h = (fx - 4) * scale, (fy - 4) * scale
        op = 0.55 + 0.2 * layer
        els.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" rx="{min(w, h) / 4:.1f}" '
                   f'fill="{color}" fill-opacity="{op:.2f}" stroke="#062557" stroke-width="0.8"/>')
    W, Hh = bw * scale + 2 * x0 + 12, bd * scale + 2 * y0 + 40
    note = (f"{plan['box']} 바닥 {bw}×{bd} · 한 층 {plan['per_layer']}개 × {plan['layers']}층"
            f"{' (그림은 3층까지)' if plan['layers'] > 3 else ''} = 기록 {plan['qty']}개 · 격자 기준 최대 {plan['cap']}개 → {plan['level']}")
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W:.0f} {Hh:.0f}" style="max-width:100%;height:auto" '
           f'role="img" aria-label="{escape(note)}">'
           f'<rect x="{x0}" y="{y0}" width="{bw * scale:.1f}" height="{bd * scale:.1f}" rx="6" fill="#FFF6B8" stroke="#B9A30F" stroke-width="2"/>'
           + "".join(els) +
           f'<text x="{x0}" y="{bd * scale + y0 + 24:.0f}" font-size="13" fill="#3A3D44">{escape(note)}</text></svg>')
    return svg, {**plan, "part": pdim, "note": note}


def source_note():
    m = _dims().get("meta") or {}
    return (f"부속 외형 = 설계 CAD 대표형({m.get('catalog_date', '?')}, 실측 아님) · "
            f"상자 안치수 = 한얼플라스틱 상품 안내(2026-10-04 확인, ±5 mm) · 수량 = 기록값")

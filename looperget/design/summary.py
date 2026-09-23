# -*- coding: utf-8 -*-
"""
looperget.design.summary — 설계 결과(job) → 지면·견적이 읽는 요약 (순수 함수).

job = `looperget.design.job/1` = {"site", "design", "meta"} (publish.py 참조).
여기서 나오는 숫자만 지면에 찍는다 — 렌더러는 값을 만들지 않는다(불변 원칙 1).

  build(job) → {
    area_m2, area_py, n_heads, n_lats, lat_total_m, main_total_m, rolls50, rolls25,
    off_min, off_max, edge_min_m, cover, lat_max_heads, curved_n, dev_max,
    zones: [{zone, n_heads, lat_ids, routes, how}], hydro: zones_report 행,
    joints: [{pt, route}], ends: [pt], tees: [pt, tag], sources: [{name, pt}],
    bom: money.rows(+note) , total, tier, sets: 세트명 매핑, warnings }
"""
from __future__ import annotations

import hashlib
import json
import math
from typing import Dict, List, Optional, Sequence, Tuple

from . import geom as G
from . import heads as _heads
from . import hydro_zone as HZ
from . import layout as _layout
from . import pipes

PY = 3.3058                      # ㎡ → 평
SPRAY_R = 10.0                   # 살수 반경(말단 1.5 bar)

# 연결부 → 세트명 (규칙 8 · Sets 시트 정본. 랭킹 엔진 = tools/set_match.py — P3에서 연동)
SETS = {
    "head": "[LSS]S-H20N427b",            # 01998 헤드 세트
    "tee50": "[LHC]T-He2Ne-50",           # CCCT 1 + 나가는 쪽 WF 4-2 2 + 들어오는 쪽 WF 4-4 1 + 밴드 4.
                                          # 엔진은 나가는 쪽(00827×2 + 00278×4)만 세고 들어오는 쪽은 water_items.
                                          # ⚠ 2026-09-05 — 여기 있던 `[LHC]T-1-505050`은 **다른 세트**였다.
                                          #   대표 확답: 「호스밴드 6개야. CCCT에 **4-2가 3개** 물리는 거야.
                                          #   숙진리에서는 CCCT에서 들어오는 쪽은 **4-4**인데 T-1-505050으로 인식했던 거야.」
                                          #   → T-1-505050 = {01201:1, 00827:3, 00278:6} (세 다리 전부 송수호스 · 29,700원).
                                          #   숙진리 조합은 시트에 없어서 **신설했다**(2026-09-05 · 결정 #33·#36 · 30,900원).
                                          #   이름은 S2 명명 규칙(B안)이 사양에서 만든 것이다 — `tools/set_name.py`.
    "join50": "[LHC]1-1-5050",            # 00825 + 00827 + 00278×4
    "inlet50": "[LHC]1-3-5050",           # 00970 + 01403 + 00278×2
    "end50": "[세트 신설 제안]",           # 01403 + 00278×2 — Sets 미등재(set-builder 제기 중)
    "branch25": "[LHC]B-50LV25",          # 01924 + 01786 — 주배관 20 mm 타공 분기 + 지관 밸브
    "end25": "[LHC]E-25",                 # 02000 지관 말단
    "join25": "[LHC]1-25",                # 01999 25 mm 일자
}


# 총 소요 내역·견적 정렬 (대표 지시 2026-09-03): 분류 → 명칭 → 규격 → 우선순위(루퍼젯·주력 제품 먼저, 가격순).
# 분류 = Products 시트 「세부카테고리」(정본). 순서는 루퍼젯 브랜드 → 연결 부속 → 밸브 → 조임식 → 소모품·계측 → 장비.
GROUP_ORDER = ["루퍼젯+", "루퍼젯+,송수호스", "루퍼젯", "스마트카플러", "노지스프링클러용부속",
               "조임식부속", "기타부속", "여과기", "공구"]
GROUP_LABEL = {"루퍼젯+": "루퍼젯+ 스프링클러 세트", "루퍼젯+,송수호스": "루퍼젯+ 송수호스",
               "루퍼젯": "루퍼젯 H시리즈", "스마트카플러": "스마트카플러", "노지스프링클러용부속": "밸브",
               "조임식부속": "조임식 부속", "기타부속": "고정 · 소모품 · 계측", "여과기": "여과기", "공구": "공구"}


def _group_of(row: Dict) -> str:
    sc = row.get("subcat") or ""
    if sc in GROUP_ORDER:
        return sc
    n = row.get("name", "")
    if "루퍼젯+" in n:
        return "루퍼젯+,송수호스" if "호스" in n else "루퍼젯+"
    if "루퍼젯" in n:
        return "루퍼젯"
    if "카플러" in n:
        return "스마트카플러"
    return "기타부속"


def sort_bom(rows: List[Dict]) -> List[Dict]:
    """분류 순서 → 루퍼젯 브랜드 먼저 → 가격 내림 → 명칭 → 규격. 각 행에 group·group_label을 붙인다."""
    out = []
    for r in rows:
        g = _group_of(r)
        out.append(dict(r, group=g, group_label=GROUP_LABEL.get(g, g)))
    return sorted(out, key=lambda r: (GROUP_ORDER.index(r["group"]) if r["group"] in GROUP_ORDER else 99,
                                      0 if "루퍼젯" in r["name"] else 1, -(r["price"] or 0), r["name"], str(r["spec"])))


def _polys(site: Dict) -> List[List[Tuple[float, float]]]:
    return [[tuple(p) for p in b["polygon"]] for b in site["blocks"]]


def coverage(polys: Sequence[Sequence[Tuple[float, float]]], heads: Sequence[Tuple[float, float]],
             r: float = SPRAY_R, step: float = 1.0) -> float:
    """밭 안 1 m 격자점 중 헤드 반경 r 안에 드는 비율 (0~1)."""
    inside = covered = 0
    r2 = r * r
    for poly in polys:
        xs = [p[0] for p in poly]
        ys = [p[1] for p in poly]
        x = math.floor(min(xs))
        while x <= max(xs):
            y = math.floor(min(ys))
            while y <= max(ys):
                q = (x + 0.5, y + 0.5)
                if G.contains(poly, q):
                    inside += 1
                    for h in heads:
                        if (h[0] - q[0]) ** 2 + (h[1] - q[1]) ** 2 <= r2:
                            covered += 1
                            break
                y += step
            x += step
    return covered / inside if inside else 0.0


def edge_min(polys, heads) -> float:
    best = None
    for h in heads:
        for poly in polys:
            if G.contains(poly, h):
                d = G.edge_dist(h, poly)
                best = d if best is None else min(best, d)
    return best if best is not None else 0.0


def main_mm_of(site: Dict, design: Dict) -> int:
    """확정된 주배관 호칭 — 엔진이 고른 값(design.main_mm)이 먼저다. BOM 과 같은 출처."""
    return int(design.get("main_mm") or site.get("main_mm") or pipes.APPROVED_MAIN_MM)


# 🔴 [V114 · F01] 연결부의 **부속·세트 이름은 확정된 관경의 BOM 규칙**에서 온다(`sets.used` = `bom.py` 조합).
#    예전에는 SETS(50 mm 조합의 이름)를 복사하고 지면이 50 mm 부속 코드를 고정으로 그렸다 — 40 mm 설계에
#    50 mm 세트·부속 사진이 나갔다(감사 F01). 50 이 아닌 조합은 Sets 시트 대조 → 없으면 **미등록**으로 둔다.
UNREGISTERED = "[세트 미등록]"


def connections(design: Dict, site: Dict, sets_db: Optional[Dict] = None, kit: Optional[Dict] = None) -> List[Dict]:
    """→ [{key, label, n, recipe, name, registered, status, mm, where}] — 이 설계가 실제로 쓰는 연결부.
    kit = BOM 이 쓰는 헤드 구성(head_kit_used · V117 K-04). 없으면 site.head_kit."""
    from . import sets as _sets                    # 지연 import — sets 가 이 모듈의 SETS 를 읽는다
    s2 = dict(site, main_mm=main_mm_of(site, design))
    idx = _sets.index(sets_db) if sets_db else {}
    out = []
    for row in _sets.used(design, s2, kit=kit):
        known = SETS.get(row.get("set_key") or "")
        hit = _sets.rank(idx.get(_sets.signature(row["recipe"])) or [], site)
        gov = [h for h in hit if h.get("gov")] if _sets.is_gov(site) else []
        if gov:                                       # [V116] 관급 — 같은 조합의 조달용 세트가 일반 세트·이름 정본보다 먼저
            name, reg, st = gov[0]["name"], True, "Sets 시트 · 조달용"
        elif known and known != _sets.PROPOSE_MARK:
            name, reg, st = known, True, "이름 정본(summary.SETS)"
        elif hit:
            name, reg, st = hit[0]["name"], True, "Sets 시트"
        else:
            name, reg, st = (known or (("%s %d mm" % (UNREGISTERED, row["mm"])) if row.get("mm") else UNREGISTERED)), False, "미등록 — 신설 후보"
        out.append({"key": row["key"], "label": row["label"], "n": row["n"], "recipe": dict(row["recipe"]),
                    "name": name, "registered": reg, "status": st, "mm": row.get("mm"), "where": row["where"]})
    return out


def _sets_view(conn: List[Dict], mm: int, kit_set: str) -> Dict[str, str]:
    """지면이 읽는 옛 키(tee50·join50…)에 **이 관경의** 이름을 넣는다. 키 이름은 호환용이고 값이 정본이다."""
    by = {c["key"]: c["name"] for c in conn}
    ok50 = mm == pipes.APPROVED_MAIN_MM
    unreg = "%s %d mm" % (UNREGISTERED, mm)
    return {
        "head": kit_set,
        "tee50": by.get("tee%d" % mm, SETS["tee50"] if ok50 else unreg),
        "join50": by.get("join%d" % mm, SETS["join50"] if ok50 else unreg),
        # [R05] 시작부 = BOM 의 실제 조합(E호스밸브 1 + 밴드 2 · sets.used 「start」). 예전 이름 [LHC]1-3-5050 은
        #       WF 4-10(00970)이 든 다른 조합이라 BOM 과 어긋났다. 급수 쪽 카플러는 계통 품목(규칙 7)이다.
        "inlet50": by.get("start%d" % mm, unreg),
        "end50": by.get("end%d" % mm, SETS["end50"] if ok50 else unreg),
        "branch25": by.get("branch25", SETS["branch25"]),   # 01924 + 01786 — 관경에 묶이지 않는 같은 물건
        "end25": by.get("end25", SETS["end25"]),
        "join25": SETS["join25"],
    }


def spray_basis(site: Dict) -> Dict:
    """[V114 · F02] 살수원·커버율이 쓰는 반경 — **설계 말단압**에서 헤드 프로필로 계산한다(고정 10/7 m 폐기).

    설계 말단압 = site.p_end → 없으면 프로필 설계압(427B 2.5 bar → 12 m). 수요표(supply.zone_demand)와 같은 값이다.
    이것은 **설계 조건이 충족될 때의 기하학적 범위**다 — 급수원이 그 압력을 낸다는 뜻이 아니다."""
    model = site.get("model") or HZ.DEFAULT_HEAD
    prof = HZ.head_profile(model)
    pe = float(site.get("p_end") or prof["p_end"])
    r = float(HZ.radius_m(pe, model))
    return {"model": model, "p_bar": pe, "r_out": round(r, 1), "r_in": round(min(float(prof.get("r_in", 7.0)), r), 1),
            "basis": "설계 말단압 %.1f bar 기준(%s 제조사 성능표·대표 실증 직선)" % (pe, model),
            # [V116] 안쪽 원의 근거 — 프로필 r_in(427B = 귀환 살수 7 m · 대표 교정 2026-08-26). 값은 반경(R)이다.
            "r_in_basis": "귀환 살수(프로필 %s · 대표 교정 2026-08-26)" % model if "r_in" in prof else "[미확정] 프로필에 안쪽 원 근거 없음"}


def m1(v) -> str:
    """[V117 · K-07] 거리 표기 규칙 하나 — 소수 1자리, 끝의 .0 은 뗀다(11.4 · 12 · 22.8). 반경·지름·간격이 같이 쓴다."""
    return ("%.1f" % float(v)).rstrip("0").rstrip(".")


def spray_labels(spray: Optional[Dict]) -> Dict[str, str]:
    """[V117 · K-07] 살수 원 R·Ø 글자 — **한 값(R)에서 둘 다** 계산한다. 예전엔 R 11.4 를 따로 반올림해 「R 11 · Ø 23」이 나갔다."""
    sp = spray or {}
    ro, ri = float(sp.get("r_out") or 0.0), float(sp.get("r_in") or 0.0)
    return {"r_out": m1(ro), "d_out": m1(2 * round(ro, 1)), "r_in": m1(ri), "d_in": m1(2 * round(ri, 1))}


def head_kit_used(site: Dict, design: Dict) -> Tuple[Dict, str]:
    """[V117 · K-04] 지면·관문이 말하는 헤드 구성 = **BOM 이 실제로 쓰는 kit 하나** → (kit, 근거).

    열별 그룹(design.head_groups)이 하나면 그 kit. 없으면 site.head_kit — 단 그 품목이 BOM 에 없으면 BOM 에 든 구성을
    찾는다(예전 job 은 01998 행을 빼고 이동식 4품목을 water_items 로 넣었다 · 용산리 09-15 — 11면은 01998 세트,
    견적은 이동식이었다). 어느 구성도 BOM 에 없으면 [미확정]으로 둔다(지어내지 않는다)."""
    groups = design.get("head_groups") or []
    if len(groups) == 1:
        return groups[0]["kit"], "열별 연결 구성(엔진)"
    kit = _heads.resolve(site)
    codes = {str(b.get("code")) for b in design.get("bom") or []}
    if len(groups) > 1 or not codes or set(kit["recipe"]) <= codes:
        return kit, "site.head_kit"
    for key in _heads.KITS:
        k2 = _heads.resolve({"head_kit": key})
        if set(k2["recipe"]) <= codes:
            return k2, "BOM 구성(%s) — site.head_kit(%s) 품목이 BOM 에 없음" % (k2["short"], kit["short"])
    return (dict(kit, key="unknown", short="[미확정] 헤드 구성", label="[미확정] 헤드 구성 — BOM 에 헤드 품목이 없습니다",
                 set="[미확정]", hose_note=""), "BOM 에 헤드 구성 품목이 없습니다(site.head_kit %s)" % kit["short"])


def _cost(money: Optional[Dict], meta: Dict, area: float) -> Dict:
    """[V114 · F03] 비용 구조 하나 — 지면·견적서·요약이 **같은 합계**를 쓴다(자재 + 수기 비용 줄)."""
    q = meta.get("quote") or {}
    svc = [{"항목": str(s.get("항목", "")), "금액": int(s.get("금액", 0) or 0)} for s in (q.get("svc") or [])]
    # [V115 · C02] 행이 있다고 가격이 확정된 것이 아니다 — 단가가 **하나라도** 붙어야 합계가 숫자다(전부 없으면 미확정).
    priced = bool(money) and any(r.get("price") is not None for r in money.get("rows") or [])
    material = int(money.get("total", 0)) if priced else None
    svc_total = sum(s["금액"] for s in svc)
    grand = (material + svc_total) if material is not None else None
    names = [s["항목"] for s in svc if s["금액"]]
    excl = ["설치 인건비"] + ([] if any("배송" in n for n in names) else ["배송비"])
    incl = ["자재"] + names
    return {"material": material, "svc": svc, "svc_total": svc_total, "grand": grand, "priced": priced,
            "missing": list((money or {}).get("missing") or []), "includes": incl, "excludes": excl,
            "vat": "영세율" if q.get("vat_zero") else "부가세 별도",
            "won_per_py": (round(grand / (area / PY)) if (grand and area) else None),
            "basis_note": "%s 포함 · %s 별도" % (" · ".join(incl), " · ".join(excl))}


def _bom_rows(design: Dict, money: Optional[Dict]) -> List[Dict]:
    """[V114 · F08] 물량과 가격을 떼어 둔다 — 단가가 없어도 **물량은 design.bom 그대로** 남는다(가격 = 미확정)."""
    if money and money.get("rows"):
        src = money["rows"]
    else:
        src = [dict(b, name="", spec="", unit=b.get("unit") or "미확정", price=None, amount=None)
               for b in design.get("bom") or []]            # [R03] 단위도 DB 에서 온다 — 모르면 EA 가 아니라 미확정
    return [{"code": r["code"], "name": r.get("name", "") or "품목 %s (단가 DB 미연결)" % r["code"],
             "spec": r.get("spec", ""), "unit": r.get("unit", ""), "qty": r["qty"], "price": r.get("price"),
             "amount": r.get("amount"), "note": r.get("note", ""),
             "cat": r.get("cat", ""), "subcat": r.get("subcat", "")} for r in src]


# ── [V114 · F04] 공급 범위 · 기설 · 설치 지원 — **입력된 사실만** 문장으로 옮긴다 ──
OWNERSHIP = ("고객 보유", "당사 공급", "별도 업체", "미확정")


def scope(site: Dict, design: Dict, meta: Dict) -> Dict:
    ans = ((site.get("intake") or {}).get("answers") or {})
    water = meta.get("water") or {}
    kinds = [s.get("name") for s in site.get("sources") or [] if s.get("name")]
    kind = (str(ans.get("source_kind") or "").strip() or " · ".join(dict.fromkeys(kinds)) or "[미확정]")
    own = water.get("ownership") if water.get("ownership") in OWNERSHIP else "미확정"
    if own == "미확정" and water.get("start_line"):
        own = "대표 문안"             # 예전 job — 대표가 급수 범위를 문장으로 적었다(그 문장이 정본)
    pump = (site.get("pump") or {}).get("model")
    items = {w["code"] for w in site.get("water_items") or []}
    feeders = [r for r in design.get("mainline", {}).get("routes", []) if r.get("role") == "feeder"]
    other = [r for r in feeders if r.get("material") not in (None, "", "hose40", "hose50")]
    if water.get("buried"):
        buried = "기설 매설 배관 %.0f m (농가 기설 · 본 제안 범위 밖)" % float(water.get("buried_len_m") or 0)
    elif other:
        buried = "수도 파이프·매설 인입관 %.0f m — 당사 자재가 아닙니다(고객 확인)" % sum(float(r.get("len_m") or 0) for r in other)
    elif str(ans.get("existing") or "").strip():
        buried = "기존 시설(문진): %s — 연결 여부 현장 확인" % str(ans["existing"]).strip()
    else:
        buried = "매설·기설 배관 — 입력 없음 [현장 확인]"
    start = water.get("start_line") or (
        "급수원 %s%s — 보유·공급 범위 %s. 본 제안은 지도에 표시한 급수 지점부터 밭 안 배관·스프링클러까지입니다"
        % (kind, (" · 펌프 %s" % pump) if pump else "", "[확인 필요]" if own == "미확정" else own))
    # [R01] 여과기(00527 · 이름에 「여과기」)와 압력계(01870 · 「압력계」)를 **따로** 본다. 01909 는 펀치(공구)다.
    #       대표 문안(meta.texts.filter_note)이 있으면 그 문장이 정본이다(승인본 05 — 여과기는 212-31 견적에).
    _wn = {w["code"]: str(w.get("note", "")) for w in site.get("water_items") or []}
    has_f = bool(items & {"00527"}) or any("여과기" in n for c, n in _wn.items() if c not in ("01909", "20002"))
    has_g = bool(items & {"01870"}) or any("압력계 20" in n or "압력계 세트" in n for n in _wn.values())
    fnote = ((meta.get("texts") or {}).get("filter_note") or [])
    if fnote:
        filt = str(fnote[0])
    elif has_f and has_g:
        filt = "여과기·압력계는 견적에 포함했습니다"
    elif has_g:
        filt = "압력계는 견적에 포함했습니다 · 여과기는 넣지 않았습니다 — 설치 여부를 확인해 주세요"
    elif has_f:
        filt = "여과기는 견적에 포함했습니다 · 압력계는 넣지 않았습니다"
    else:
        filt = "여과기·압력계는 이 견적에 넣지 않았습니다 — 설치 여부를 확인해 주세요"
    sup = (meta.get("quote") or {}).get("install_support")
    install = {True: "설치 지원 — 약정됨", False: "설치 — 농가 자가 시공"}.get(sup, "설치 방법(자가 시공·설치 지원) — 협의 필요")
    return {"source_kind": kind, "ownership": own, "pump": pump, "start_line": start, "buried": buried,
            "filter": filt, "install": install, "install_support": sup,
            "start_kind": water.get("start_kind") or ("급수 지점 — %s" % kind)}


LINK_INTENTS = {"separate": "따로 깐 관(잇지 않음)", "joined": "잇는 자리"}


def link_key(a: str, b: str) -> str:
    """접점 이름 — 두 관 이름을 정렬해 「A↔B」. 그리는 순서가 바뀌어도 같은 접점이다."""
    return "↔".join(sorted((str(a), str(b))))


def _c1(v) -> float:
    """0.1 m 반올림 · -0.0 → 0.0 (지문 문자열이 부호 0 때문에 갈리지 않게)."""
    r = round(float(v), 1)
    return r if r else 0.0


def link_stamp(site: Optional[Dict], a: str, b: str) -> Optional[Dict]:
    """[V117 · K-03] 접점 도장 — 두 관의 **지금 모양**과 닿은 자리. → {"pair", "at", "fp"} (관이 없으면 None).

    의도(따로 깐 관·잇는 자리)는 이 도장과 함께 저장한다. 관을 다시 그려 도장이 달라지면 그 의도는 쓰지 않는다
    (V116 은 이름 쌍만 키라 낡은 「따로 깐 관」이 다른 모양의 결합에도 붙어 차단이 풀렸다 · 재검토 K-03).
    지문(fp)은 y 부호에 무관하다 — 앱(P3 · 북쪽 +y)에서 적고 지면 job(아래쪽 +y · publish.flip_y)에서 대조하기 때문이다.
    a == b 면 한 관이 제 출발 자리로 되돌아온 고리(R5-3)다."""
    from . import mainline as _ml
    R: Dict[str, List] = {}
    for r in (site or {}).get("routes") or []:
        R.setdefault(str(r.get("name")), []).append([(float(q[0]), float(q[1])) for q in r.get("pts") or []])
    a, b = str(a), str(b)
    if len(R.get(a) or []) != 1 or len(R.get(b) or []) != 1:
        return None                                     # 없거나 이름이 겹친 관 — 도장을 찍지 않는다(이름 중복은 관문이 막는다)
    A, B = R[a][0], R[b][0]
    if len(A) < 2 or len(B) < 2:
        return None
    near = max(_ml.END_NEAR, _ml.MID_NEAR)
    at = []
    if a == b:
        if G.dist(A[0], A[-1]) <= near:
            at.append(A[-1])
    else:
        for X, Y in ((A, B), (B, A)):
            for e in (X[0], X[-1]):
                if G.dist(G.nearest_on_polyline(Y, e)[1], e) <= near:
                    at.append(e)
    pair = sorted((a, b))
    geo = {a: A, b: B}

    def h(sy):
        body = json.dumps([pair, [[[_c1(q[0]), _c1(sy * q[1])] for q in geo[n]] for n in pair]], ensure_ascii=False)
        return hashlib.sha256(body.encode("utf-8")).hexdigest()[:16]
    return {"pair": pair, "at": [[_c1(p[0]), _c1(p[1])] for p in at], "fp": min(h(1.0), h(-1.0))}


def intent_entry(site: Optional[Dict], a: str, b: str, intent: str) -> Dict:
    """의도 한 칸(저장 형식) — {"pair", "intent", "at", "fp"}. 화면(editor_ui)과 재현 입력이 이것으로 적는다."""
    st_ = link_stamp(site, a, b) or {"pair": sorted((str(a), str(b))), "at": [], "fp": None}
    return dict(st_, intent=intent)


def _intent_items(site: Optional[Dict]) -> List[Tuple[Tuple[str, str], str, Optional[Dict]]]:
    """site.link_intent → [((관a, 관b) 정렬, 의도, 저장 칸 | None=옛 형식)]. 모르는 값은 버린다(지어내지 않는다).

    [V117 · K-08] 쌍은 저장된 목록(pair)을 먼저 쓴다 — 관 이름에 「↔」가 들어 있어도 쪼개지 않는다.
    옛 형식(V116 · {"A↔B": "separate"})은 이름을 「↔」로 갈라 읽는다(도장 없음)."""
    raw = (site or {}).get("link_intent") or {}
    out = []
    for k, v in raw.items() if isinstance(raw, dict) else ():
        if isinstance(v, dict):
            pair, it = v.get("pair"), v.get("intent")
            if not (isinstance(pair, (list, tuple)) and len(pair) == 2):
                parts = str(k).split("↔")
                pair = parts if len(parts) == 2 else None
            if pair and it in LINK_INTENTS:
                out.append((tuple(sorted(str(p) for p in pair)), it, v))
        else:
            parts = str(k).split("↔")
            if len(parts) == 2 and v in LINK_INTENTS:
                out.append((tuple(sorted(parts)), v, None))
    return out


def link_intents(site: Optional[Dict]) -> Dict[str, str]:
    """site.link_intent → {접점 이름: separate|joined} (도장 확인 전 · 화면 표시용). 판정은 intent_status 가 한다."""
    return {link_key(*p): it for p, it, _e in _intent_items(site)}


def intent_status(site: Optional[Dict], a: str, b: str) -> Tuple[Optional[str], str]:
    """[V117 · K-03] 접점 (a, b)의 의도와 그 효력 → (의도|None, 상태).

    상태 = "none" 적은 것 없음 · "ok" 도장이 지금 모양과 같다(효력 있음) · "stale" 관을 다시 그려 도장이 달라졌다 ·
    "legacy" 도장 없이 저장된 옛 의도(V116). 🔴 효력은 "ok" 일 때만 — 모양을 확인할 수 없는 의도로 차단을 풀지 않는다."""
    key = tuple(sorted((str(a), str(b))))
    hit = [x for x in _intent_items(site) if x[0] == key]
    if not hit:
        return None, "none"
    _p, it, entry = hit[-1]
    if entry is None or not entry.get("fp"):
        return it, "legacy"
    cur = link_stamp(site, a, b)
    return it, ("ok" if cur and cur["fp"] == entry["fp"] else "stale")


def gate(S: Dict, design: Dict, site: Dict) -> Dict:
    """[V114 · F06] 발행 관문 — 정상 초안 / 조건부 초안 / 차단(내부 검토용).

    🔴 공급 정보가 없다는 이유만으로 막지 않는다(수요 설계 초안은 허용 — 기존 계약). 차단은 **구조 결함·필수 정보 손실**뿐이다.
    이 판정은 **발행 허가가 아니다** — 고객 발행은 대표 전담(불변 원칙 3)."""
    block, cond = [], []
    if not S["n_heads"]:
        block.append("스프링클러 0두 — 배치가 없습니다")
    un = S["unconnected"]
    if un["rows"]:
        block.append("주배관에 닿지 않는 가지관 %d열 · %d두(급수 불가) — 경로를 고치기 전에는 설계가 성립하지 않습니다"
                     % (un["rows"], un["heads"]))
    if S.get("dead_routes"):
        block.append("급수원까지 관으로 이어지지 않은 관 %d개(%s) — 이 관의 구역은 물을 받지 못합니다"
                     % (len(S["dead_routes"]), " · ".join(S["dead_routes"])))
    # [V115 · N03·N04] 좌표로는 닿는데 엔진이 연결로 계산하지 않은 자리 — 그 자리 T·부속·수리가 견적·계산에 없다.
    #   끊긴 관을 산 관에 잇는 자리(링 T 등)면 **차단**. 둘 다 물을 받는 관이면 「겹쳐 깐 관」(승인본 01·03)과
    #   「잇는 자리」를 좌표로 가를 수 없어 **확인 항목**으로 드러낸다(조용히 정상 처리하지 않는다).
    _dead = set(S.get("dead_routes") or [])
    _ul = [(x[0], x[1], bool(x[2]) if len(x) > 2 else False) for x in S.get("unmodeled_links") or []]
    # [V116] 대표가 접점마다 적은 연결 의도(site.link_intent) — 「separate」 따로 깐 관 · 「joined」 잇는 자리.
    #   따로 깐 관이면 그 접점은 계산할 연결이 없다 → 관문에서 뺀다(끊긴 관은 dead_routes 가 그대로 막는다).
    #   잇는 자리면 그 T·수리를 엔진이 아직 계산하지 못한다 → 좌표 모양과 상관없이 **차단**.
    # 🔴 [V117 · K-03] 의도는 **도장(접점 좌표·관 모양 지문)이 지금 모양과 같을 때만** 효력이 있다. 관을 다시 그려
    #    도장이 달라졌거나(stale) 도장 없이 저장된 옛 의도(legacy · V116)는 쓰지 않고 차단 + 재확인으로 올린다 —
    #    그 접점은 의도가 없는 것처럼 아래에서 다시 판정된다(두 급수원이면 차단 · 물 받는 관끼리면 확인 항목).
    _ist = {x[:2]: intent_status(site, x[0], x[1]) for x in _ul}
    _it = {k: v[0] for k, v in _ist.items() if v[1] == "ok"}
    _stale = [k for k, v in _ist.items() if v[1] in ("stale", "legacy")]
    if _stale:
        block.append("관 모양을 확인할 수 없는 접점 의도 %d곳(%s) — 관을 다시 그렸거나 좌표 없이 저장된 옛 의도라 쓰지 "
                     "않았습니다. 「🔗 관 접점 확인」에서 다시 골라 주세요"
                     % (len(_stale), " · ".join("%s↔%s" % k for k in _stale)))
    _joined = [x[:2] for x in _ul if _it.get(x[:2]) == "joined"]
    _ul = [x for x in _ul if _it.get(x[:2]) not in ("separate", "joined")]
    if _joined:
        block.append("대표가 「잇는 자리」로 적은 접점 %d곳(%s) — 그 자리 T·부속·수리가 계산에 없습니다. "
                     "한 관을 그 자리에서 끊어 그리면 엔진이 T 로 셉니다(두 급수원이면 한 계통으로)"
                     % (len(_joined), " · ".join("%s↔%s" % x for x in _joined)))
    _bridge = [x[:2] for x in _ul if (x[0] in _dead) != (x[1] in _dead)]
    # [V115 · R-a] 서로 다른 급수원 계통의 관이 엔진 모르게 닿은 자리 — 두 급수원이 섞이는데 수리·역류·T 가 계산에 없다 → 차단
    _cross = [x[:2] for x in _ul if x[2] and x[:2] not in _bridge]
    _other = [x[:2] for x in _ul if x[:2] not in _bridge and x[:2] not in _cross]
    if _bridge:
        block.append("엔진이 계산하지 않은 관 연결 %d곳(%s) — 물을 받는 관에 다른 관을 잇는 모양입니다. 그 자리 T·부속·수리가 "
                     "견적·계산에 없습니다. 선을 그 자리에서 끊어 그려 주세요"
                     % (len(_bridge), " · ".join("%s↔%s" % x for x in _bridge)))
    if _cross:
        block.append("서로 다른 급수원 계통의 관이 닿은 자리 %d곳(%s) — 두 급수원을 잇는 T·수리·역류가 계산에 없습니다. "
                     "잇지 않는 관이면 떨어뜨려 그리고, 잇는 자리면 한 계통으로 다시 그려 주세요"
                     % (len(_cross), " · ".join("%s↔%s" % x for x in _cross)))
    if _other:
        cond.append("엔진이 연결로 보지 않은 접점 %d곳(%s) — 같은 길로 나란히 깐 관이면 그대로, 실제로 잇는 자리면 "
                    "T·부속·수리가 빠져 있습니다(선을 끊어 다시 그리기 · 「🔗 관 접점 확인」에서 골라 주세요)"
                    % (len(_other), " · ".join("%s↔%s" % x for x in _other)))
    _nm = [r.get("name") for r in site.get("routes") or []]
    _dup = sorted({x for x in _nm if _nm.count(x) > 1})
    if _dup:                                            # [V115 · N01] 열·구역은 관 이름으로 붙는다 — 겹치면 어느 관인지 모른다
        block.append("관 이름 중복 %s — 경로 표에서 이름을 서로 다르게 고쳐 주세요" % " · ".join(map(str, _dup)))
    zh = sum(z["n_heads"] for z in S["zones"])
    un_zoned = sum(l["n_heads"] for l in design.get("laterals") or []
                   if l["id"] in set(un.get("ids") or []) and l.get("zone") is not None)
    if S["n_heads"] and zh + un["heads"] - un_zoned != S["n_heads"]:
        block.append("구역 두수 합 %d ≠ 전체 %d두 — 구역에 속하지 않은 헤드가 있습니다" % (zh + un["heads"], S["n_heads"]))
    if not S["bom"]:
        block.append("자재 목록 0행")
    sup = S.get("supply") or {}
    bad = [z for z in sup.get("zones") or [] if z.get("status") == "insufficient"]
    if bad:
        block.append("공급 부족 판정 구역 %s — 이 급수원으로는 설계 압력·유량이 나오지 않습니다"
                     % ", ".join(str(z.get("zone")) for z in bad))
    if sup.get("mode") == "demand_only" or any(z.get("status") in ("unverified", "미확정") for z in sup.get("zones") or []):
        cond.append("급수원 성능 미확정 — 구역별 필요 유량·압력(요구조건)만 제시합니다")
    pr = S.get("procurement") or {}
    if pr.get("channel") == "관급":                  # [V116] 조달 세트 — 적용이든 없음이든 담당자 확인 항목으로 드러낸다
        # [V117 · K-05] 조달용추가BOM 은 견적에 넣지 않는다(대표 열린 결정) — 이름만 조달 세트라는 사실을 함께 적는다.
        cond.append((("관급 — 헤드 세트 %s 적용 · %s" % (pr["picked"], pr["why"])) if pr.get("picked")
                     else ("관급 — 조달용 세트 미적용: %s" % pr.get("why")))
                    + " · 견적은 일반 묶음 코드 기준 · 조달 추가 구성 미반영")
    if (S.get("head_kit") or {}).get("key") == "unknown":   # [V117 · K-04] BOM 에 헤드 구성 품목이 없다
        cond.append("헤드 구성 [미확정] — %s" % S.get("head_kit_basis", "BOM 에 헤드 품목이 없습니다"))
    if S.get("tee_inlet") == "missing":              # [V117 · C] T 들어오는 쪽(규칙 8-1)은 급수 계통 품목 — 없으면 견적에 없다
        cond.append("T분기 들어오는 쪽 부속 [미확정] %d곳 — 견적에 없습니다(WF 4-4 등 급수 계통 품목 · 규칙 8-1)"
                    % int(S.get("n_tees") or 0))
    _ans = ((site.get("intake") or {}).get("answers") or {})
    _pump = str(_ans.get("pump") or (site.get("pump") or {}).get("model") or "").strip()
    _hint = [k for k in ("flow_lpm", "pressure_bar") if any(w in str(_ans.get(k) or "") for w in ("펌프", "마력", "HP", "hp"))]
    if _pump in ("없음", "없다", "무", "없어요") and _hint:   # [V117 · C] 문진 모순 — 4·5면 「펌프 없음」 vs 유량 칸 「1마력펌프」
        cond.append("문진 입력 모순 — 펌프 「%s」인데 %s 칸에 「%s」 — 급수원·펌프를 확인해 주세요"
                    % (_pump, "·".join({"flow_lpm": "유량", "pressure_bar": "수압"}[k] for k in _hint),
                       " / ".join(str(_ans[k]) for k in _hint)))
    for m in S.get("photo_missing") or []:           # [V117 · K-10] 사진 누락은 **렌더 전에** 관문에 — 표지 수 = 앱 수
        cond.append("현장 " + m)
    # [V117 · 2단계] 관급·건설 = 현장 사진 0장이면 확인 항목 · 농업 = 선택(없어도 아무 표시 없음) — design.segments 프로필
    if (S.get("segment_profile") or {}).get("photo_gate") and not S.get("n_photos") and not S.get("photo_missing"):
        cond.append("현장 사진 0장 — %s 현장은 사진이 확인 항목입니다" % S.get("segment"))
    c = S["cost"]
    if not c["priced"]:
        cond.append("단가 DB 미연결 — 물량만 있고 금액은 미확정입니다(재계산 필요)" if not c["missing"] else
                    "전 품목 단가 없음(%d개) — 물량만 있고 금액은 미확정입니다" % len(c["missing"]))
    elif c["missing"]:
        cond.append("단가 없는 품목 %d개 — 합계는 가격 확정 품목 소계입니다" % len(c["missing"]))
    unreg: Dict[str, List[str]] = {}                  # 같은 조합 = 같은 물건(말단·구역밸브·시작부)
    for x in S.get("connections") or []:
        if not x["registered"]:
            unreg.setdefault(json.dumps(x["recipe"], sort_keys=True), []).append(x["label"])
    if unreg:
        cond.append("미등록 세트 %d종(%s) — 구성은 BOM 기준, 이름·사진은 확인 필요"
                    % (len(unreg), " / ".join("·".join(v) for v in unreg.values())))
    _jx = [j for j in (design.get("mainline") or {}).get("junctions") or [] if j.get("kind") == "elbow" or j.get("mixed")]
    if _jx:
        cond.append("부속 [미확정] 자리 %d곳(45° 넘는 꺾임·재질 전환) — 계통 품목으로 넣어야 합니다" % len(_jx))
    _vel = [w for w in S.get("warnings") or [] if w.startswith("유속")]
    if _vel:
        cond.append("주배관 %s — 권장 2.0 m/s 초과 · 급수·정지는 밸브를 천천히(수격 방지)"
                    % " · ".join(w.split(" —")[0] for w in _vel))
    if any("펌프가 [미확정]" in w for w in S.get("warnings") or []):
        cond.append("펌프 [미확정] — 주배관 관경을 승인본 기본(50 mm)으로 두었습니다")
    if S["scope"]["ownership"] == "미확정":
        cond.append("급수원 보유·공급 범위 미확정")
    waived = ((site.get("intake") or {}).get("waived") or [])
    if waived:
        cond.append("문진에서 모른 채 진행한 항목 %d개" % len(waived))
    level = "blocked" if block else ("conditional" if cond else "ok")
    label = {"ok": "초안 — 대표 검토 후 발행", "conditional": "조건부 초안 — 확인 항목 %d건" % len(cond),
             "blocked": "내부 검토용 — 결함 %d건 · 발송 불가" % len(block)}[level]
    return {"level": level, "label": label, "block": block, "conditional": cond}


def joint_points(site: Dict, design: Dict, roll_m: float = 50.0) -> List[Dict]:
    """주배관 경로마다 50 m 롤이 끝나는 자리(일자연결 세트 위치)."""
    out = []
    for r_site, r_out in zip(site["routes"], design["mainline"]["routes"]):
        pts = [tuple(p) for p in r_site["pts"]]
        for k in range(1, r_out["joints"] + 1):
            p, _ = G.point_at(pts, roll_m * k)
            out.append({"pt": [round(p[0], 1), round(p[1], 1)], "route": r_site["name"]})
    return out


def _unfed_routes(design: Dict, site: Optional[Dict] = None, out: Optional[List] = None) -> set:
    """[V115 · C01] 급수원에서 **엔진이 계산한 연결을 따라** 닿지 못하는 관 이름 전부.

    mainline 경고는 첫 점·끝점이 아무 데도 안 닿은 관(free)만 잡는다. 서로는 이어졌지만(폐회로 포함) 그 묶음이
    급수원에 닿지 않으면 묶음 전체가 물을 못 받는다.
    🔴 도달성은 **엔진 연결(from · from_ref)** 로만 본다 — 수리·BOM 이 쓰는 바로 그 연결이다. 좌표로만 닿은 자리는
    엔진이 T·부속·수리를 세지 않았다(독립검토 N03·N04). 승인본 01·03 처럼 구역선을 **같은 길로 겹쳐** 그리면
    끝점이 남의 관 위에 놓여도 연결이 아니다 — 좌표만으로는 「겹쳐 깐 관」과 「잇는 자리」를 가를 수 없다.
    [N01] 관은 순서 번호로 본다 — from_ref(이름)가 여럿이면 **그 자리에 실제로 닿은** 관을 고른다.

    out(주면) ← 엔진이 세지 않은 좌표 접점 [(관 a, 관 b)] — 관문이 판정한다(끊긴 관을 잇는 자리면 차단, 아니면 확인 항목)."""
    from . import mainline as _ml
    rs = (design.get("mainline") or {}).get("routes") or []
    sr = (site or {}).get("routes") or []
    if not rs or any("from" not in r for r in rs) or len(sr) != len(rs):
        return set()                                    # 연결 정보 없는 옛 형식 — 기존 경고 판정만 쓴다
    P = [[tuple(q) for q in r["pts"]] for r in sr]
    near = max(_ml.END_NEAR, _ml.MID_NEAR)
    n = len(rs)

    def gap(i, pt):                                     # 관 i 까지 거리
        return G.dist(G.nearest_on_polyline(P[i], pt)[1], pt)

    def at(x):                                          # 엔진이 x 가 물을 받는다고 본 자리(저장 job 의 feed_pt 는 쓰지 않는다 — flip 전 좌표)
        k = rs[x]["from"]
        return P[x][-1] if k == "tail" else P[x][0]

    # ① 엔진 연결 — from_ref 이름이 가리키는 관(같은 이름이면 그 자리에 닿은 관)
    link: Dict[int, int] = {}
    for x, r in enumerate(rs):
        if r["from"] not in ("end", "mid", "tap", "tail"):
            continue
        cand = [j for j in range(n) if j != x and rs[j]["name"] == r.get("from_ref")]
        if r["from"] == "tap":                          # 상대(인입관)의 끝이 x 의 중간에 닿았다
            cand.sort(key=lambda j: gap(x, P[j][-1]))
        else:
            cand.sort(key=lambda j: gap(j, at(x)))
        if cand:
            link[x] = cand[0]
    adj = [set() for _ in range(n)]
    for x, y in link.items():
        adj[x].add(y)
        adj[y].add(x)
    seen = {i for i, r in enumerate(rs) if r["from"] == "source"}
    todo = list(seen)
    while todo:
        for m in adj[todo.pop()] - seen:
            seen.add(m)
            todo.append(m)

    # ② 엔진이 세지 않은 좌표 접점 — 한 관의 끝점이 다른 관(끝점·중간)에 닿았는데 아래 어느 것도 아닌 자리
    #    (a) 엔진 연결 자리 (b) 같은 출발(같은 from·상대)의 첫 점끼리
    #    (c) 급수원이 **다른 관의 중간**에 놓인 분기점(급수점 T — tees_here · 승인본 04·05·숙진리)
    #    🔴 [V115 · Codex 재검토] (c)는 예전에 「첫 점이 자기 급수원 자리」면 무엇이 닿든 인정해, 다른 급수원에서 온 관의
    #       **끝**이 이 급수원 자리에 닿아도(두 계통 결합) 접점 알림이 빠졌다 → 상대 관의 **중간**일 때만 인정.
    SRC = [tuple(s["pt"]) for s in (site or {}).get("sources") or []]
    TH = [s.get("tees_here") for s in (site or {}).get("sources") or []]

    def src_of(i):                                      # 급수원 출발 관의 급수원 = 첫 점에 가장 가까운 급수원(이름은 겹칠 수 있다)
        if rs[i]["from"] != "source" or not SRC:
            return None
        k = min(range(len(SRC)), key=lambda j: G.dist(SRC[j], P[i][0]))
        return k if G.dist(SRC[k], P[i][0]) <= _ml.SOURCE_NEAR + near else None

    def mid_of(y, pt):
        s_, c_, _ = G.nearest_on_polyline(P[y], pt)
        return G.dist(c_, pt) <= near and _ml.END_NEAR < s_ < G.polyline_len(P[y]) - _ml.END_NEAR

    def counted(a, b, pt, head=True):
        # head = 이 접점을 만든 끝이 그 관의 **첫 점**인가. [V117 · R5-3] 끝점(꼬리)이 급수원 자리로 되돌아온 고리는
        #   「같은 출발의 첫 점끼리」(b)·「분기점 급수원」(c)가 아니다 — 첫 점과 좌표가 같아도 꼬리가 만든 접점이다.
        for x, y in ((a, b), (b, a)):
            if link.get(x) == y:
                if rs[x]["from"] == "tap" and G.dist(P[y][-1], pt) <= near:
                    return True
                if rs[x]["from"] != "tap" and G.dist(at(x), pt) <= near:
                    return True
            k = src_of(x)
            # [R5-1] 분기점 급수원은 그 자리 T 를 스스로 센다(tees_here ≥ 1 — 승인본 04·05·숙진리). 0 이면 진짜 다른 급수원이다.
            if (head and k is not None and G.dist(P[x][0], pt) <= near and G.dist(SRC[k], pt) <= _ml.SOURCE_NEAR + near
                    and mid_of(y, P[x][0]) and int(TH[k] or 0) >= 1):
                return True
        ra, rb = rs[a], rs[b]
        if ra["from"] == "source" or rb["from"] == "source":      # [R5-2] 급수원은 이름이 아니라 자리로 같다
            same = src_of(a) is not None and src_of(a) == src_of(b)
        else:
            same = ra["from"] != "free" and (ra["from"], ra.get("from_ref")) == (rb["from"], rb.get("from_ref"))
        return head and same and G.dist(P[a][0], pt) <= near and G.dist(P[b][0], pt) <= near

    # 관마다 물이 오는 급수원(엔진 연결 묶음 안의 급수원 출발 관들) — 계통이 다른 두 관이 닿으면 두 급수원이 섞인다.
    root = [set() for _ in range(n)]
    done = set()
    for i in range(n):
        if i in done:
            continue
        comp, st_ = {i}, [i]
        while st_:
            for m in adj[st_.pop()] - comp:
                comp.add(m)
                st_.append(m)
        srcs = {src_of(j) for j in comp} - {None}
        for j in comp:
            root[j] = srcs
        done |= comp

    if out is not None:
        for a in range(n):
            # [V117 · R5-3] 한 관이 제 첫 점(급수원 자리)으로 되돌아온 고리 — 엔진은 그 자리 T·수리를 세지 않는다.
            #   물 받는 관 한 계통 안이라 확인 항목이다(V115 원칙 ②). 이름 = 「관↔관」(같은 이름 두 번).
            if len(P[a]) > 2 and G.dist(P[a][0], P[a][-1]) <= near:
                out.append((rs[a]["name"], rs[a]["name"], False))
            for b in range(a + 1, n):
                cs = [(e, e_i == 0) for x, y in ((a, b), (b, a)) for e_i, e in ((0, P[x][0]), (1, P[x][-1]))
                      if gap(y, e) <= near]
                bad = [pt for pt, hd in cs if not counted(a, b, pt, hd)]
                if bad:
                    # [V116 · R5-1] 두 급수원 계통이 닿은 자리는 좌표만으로 「따로 깐 관」과 「결합」을 가를 수 없다.
                    #   예전(V115)엔 급수원 첫 점이 남의 관 중간이면 확인 항목으로 내렸다(X1 — T·수리 없이 통과).
                    #   이제 언제나 cross 로 올리고, **대표가 「따로 깐 관」이라고 적은 자리만** 관문에서 푼다(site.link_intent).
                    cross = bool(root[a] and root[b] and not (root[a] & root[b]))
                    out.append((rs[a]["name"], rs[b]["name"], cross))
    return {rs[i]["name"] for i in range(n) if i not in seen}


def build(job: Dict) -> Dict:
    site, design, meta = job["site"], job["design"], job.get("meta", {})
    polys = _polys(site)
    area = sum(G.area(p) for p in polys)
    lats = design["laterals"]
    heads = [tuple(h["pt"]) for h in design["heads"]]
    zones = []
    for z in design["zones"]:
        zones.append({"zone": str(z["zone"]), "n_heads": z["n_heads"], "lat_ids": list(z["laterals"]),
                      "routes": list(z["routes"]),
                      "how": (meta.get("texts", {}).get("zone_how", {}) or {}).get(str(z["zone"]), "")})
    money = design.get("money")
    bom = sort_bom(_bom_rows(design, money))
    money = money or {"rows": [], "total": 0, "tier": "소비자가",
                      "missing": sorted({b["code"] for b in design.get("bom") or []})}
    off = [l["off"] for l in lats]
    # 🔵 [V109] 지면 문구가 「10 m」·「01998 세트」로 **고정**돼 있었다(용산리 변경 B안 2026-09-15 — 열 간격 12.5·이동식 헤드).
    #    간격은 블록 정책(S·lat_gap)에서, 헤드 구성은 site["head_kit"] 에서 읽는다. 값은 여기서 만들지 않는다.
    _pd = _layout.RowPolicy()
    _pols = [(b.get("policy") or {}) for b in site.get("blocks") or []]

    def _rng(key, dflt):
        vs = sorted({float(p.get(key, dflt)) for p in _pols} or {float(dflt)})
        f = lambda v: ("%.1f" % v).rstrip("0").rstrip(".")
        return f(vs[0]) if len(vs) == 1 else "%s~%s" % (f(vs[0]), f(vs[-1]))
    kit, kit_basis = head_kit_used(site, design)       # [V117 · K-04] BOM 이 실제로 쓰는 kit 하나 — 캡션·12면·관급·연결부 공통
    from . import supply
    supply_report = design.get("supply") or supply.assess_supply(site.get("supply") or {}, supply.design_demands(design, site))
    groups = design.get("head_groups") or []
    if len(groups) > 1:
        kit = dict(kit, key="mixed", short="열별 연결 구성", label="열별 연결 구성 — 상세표 참조", set="열별 세트 상세 참조",
                   hose_note="열별 연결 구성표를 확인하세요. 같은 살수기종을 사용합니다.")
    mm = main_mm_of(site, design)
    conn = connections(design, site, meta.get("sets_db"), kit=(None if kit.get("key") in ("mixed", "unknown") else kit))
    # [V114 · F02·F09] 커버율 = **주배관에 닿은 열의 헤드만**, 반경 = 설계 말단압의 헤드 반경.
    #    닿지 않은 열(급수 불가)의 헤드로 밭을 덮었다고 쓰지 않는다.
    spray = spray_basis(site)
    # [R02] 급수원·다른 관 어디에도 닿지 않은 관(mainline 경고) — 그 관에 붙은 열도 급수 불가다.
    import re as _re
    dead = {m.group(1) for w in design.get("warnings") or []
            for m in _re.finditer(r"'([^']+)' 이 급수원·다른 관 어디에도 닿지 않았다", w)}
    _unmod: List = []
    dead = sorted(dead | _unfed_routes(design, site, _unmod))
    tapped = {l["id"] for l in lats if l.get("tap") is not None and l.get("zone") is not None
              and l.get("route") not in dead}
    live = [tuple(h["pt"]) for h in design["heads"] if h.get("lat") in tapped]
    un_rows = [l for l in lats if l["id"] not in tapped]
    cost = _cost(design.get("money"), meta, area)
    S = {
        "name": meta.get("name") or design.get("name"),
        "parcel": meta.get("parcel", ""), "site_label": meta.get("site_label", ""),
        "area_m2": round(area), "area_py": round(area / PY),
        "n_heads": design["n_heads"], "n_lats": design["n_laterals"],
        "lat_total_m": round(sum(l["len_m"] for l in lats)),
        "main_total_m": round(design["mainline"]["total_m"]),
        "rolls50": next((b["qty"] for b in design["bom"]
                         if b["code"] in {f["hose"] for f in pipes.MAIN_FITTINGS.values()}), None),
        "rolls25": next((b["qty"] for b in design["bom"] if b["code"] == "02044"), None),
        "off_min": round(min(off), 1) if off else None, "off_max": round(max(off), 1) if off else None,
        "edge_min_m": round(edge_min(polys, heads), 1),
        "cover": round(coverage(polys, live, spray["r_out"]), 3),
        "cover_layout": round(coverage(polys, heads, spray["r_out"]), 3),
        "spray": spray,
        "cover_basis": "주배관에 연결된 헤드 · %s · 급수 조건 충족 시의 배치상 범위(실측 아님)" % spray["basis"],
        "unconnected": {"rows": len(un_rows), "heads": sum(l["n_heads"] for l in un_rows),
                        "ids": [l["id"] for l in un_rows]},
        "dead_routes": dead,
        "unmodeled_links": [list(x) for x in _unmod],
        "dead_zones": sorted({str(r["zone"]) for r in site.get("routes") or [] if r.get("name") in dead
                              and r.get("zone") is not None}),
        "main_mm": mm, "fittings": pipes.main_fittings(mm), "connections": conn,
        "lat_max_heads": max((l["n_heads"] for l in lats), default=0),
        "curved_n": sum(1 for l in lats if l.get("path")),
        "dev_max": max((l.get("dev_deg") or 0 for l in lats), default=0),
        "zones": zones,
        "hydro": HZ.zones_report(design, site),
        "hydro_basis": "기존 승인본 재현/운전점 참고. 신규 공급조건 권장은 supply 필드 기준",
        "supply": supply_report, "chains": site.get("chains") or [],
        "connection_examples": site.get("connection_examples") or [],   # [V116] 도해만 · BOM 미포함
        "head_groups": groups, "excluded_tools": design.get("excluded_tools") or [],
        "joints": joint_points(site, design),
        "ends": [list(p) for p in design["mainline"]["end_pts"]],
        "tees": [[list(p), tag] for p, tag in design["mainline"]["tee_pts"]],
        "n_tees": design["mainline"]["tees"], "n_ends": design["mainline"]["ends"],
        "n_joints": design["mainline"]["joints"],
        "sources": [{"name": s["name"], "pt": list(s["pt"])} for s in site["sources"]],
        "bom": bom, "total": money.get("total", 0), "tier": money.get("tier", "소비자가"),
        # [V114 · F03] 평당가 = **비용 구조의 합계**(자재 + 수기 비용 줄) 기준 — 포함 범위는 cost.basis_note.
        "won_per_py": cost["won_per_py"], "cost": cost, "grand_total": cost["grand"],
        "missing": money.get("missing", []),
        "sets": _sets_view(conn, mm, kit["set"]), "warnings": list(design.get("warnings", [])),
        "head_gap": _rng("S", _pd.S), "lat_gap": _rng("lat_gap", _pd.lat_gap), "head_kit": kit,
        "headers": [dict(h) for h in (design.get("mainline") or {}).get("headers") or []],
        "intake_waived": list(((site.get("intake") or {}).get("waived") or [])),
        "head_kit_basis": kit_basis,
        # [V117 · C] T 들어오는 쪽(WF 4-4 · 규칙 8-1) — 견적(water_items)에 있나 · 매니폴드 면에 있나 · 없나
        "tee_inlet": ("none" if not design["mainline"]["tees"] else
                      "manifold" if meta.get("manifold") else
                      "quote" if "00969" in {str(w.get("code")) for w in site.get("water_items") or []} else "missing"),
        # [V117 · K-10] 사진 누락은 관문 계산에 넣는다(publish 가 렌더 **전에** 확정한 목록)
        "photo_missing": list(meta.get("photo_missing") or []),
        "spray_labels": spray_labels(spray),
    }
    from . import segments as _seg                     # [V117 · 2단계] 대상 종류(농업·관급·건설·조경) — 프로필 한 곳
    S["segment_profile"] = _seg.profile(site)
    S["segment"] = S["segment_profile"]["key"]
    S["n_photos"] = len(meta.get("photos") or [])
    S["scope"] = scope(site, design, meta)
    # [V116] 관급 — 헤드 구성과 같은 조합의 조달용 세트를 앞세운다(없으면 사유·같은 기종 후보). 열별 혼합이면 상세표가 정본.
    # [V117 · K-04] 고르는 기준 = BOM 이 실제로 쓰는 kit(예전엔 site.head_kit 이라 열별로 바꾼 구성과 어긋났다).
    from . import sets as _sets
    S["procurement"] = _sets.gov_pick(site, meta.get("sets_db"), kit=kit)
    if S["procurement"]["picked"] and kit.get("key") != "mixed":
        S["sets"]["head"] = S["procurement"]["picked"]
    S["gate"] = gate(S, design, site)
    return S


__all__ = ["build", "link_key", "link_intents", "link_stamp", "intent_entry", "intent_status", "head_kit_used",
           "spray_labels", "m1", "LINK_INTENTS", "coverage", "edge_min", "joint_points", "sort_bom", "SETS", "PY", "SPRAY_R", "GROUP_ORDER", "GROUP_LABEL"]

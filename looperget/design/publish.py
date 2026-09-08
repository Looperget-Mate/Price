# -*- coding: utf-8 -*-
"""
looperget.design.publish — P2 원버튼: job(design.json) → 제안서 pptx(+pdf/png) + 견적 xlsx.

    python -m looperget.design.publish <job.json> [--out DIR] [--pdf] [--png] [--no-xlsx]
    python -m looperget.design.publish --demo 05 [--pdf] [--png]     # 승인 정답지 05로 job을 조립해 실행

job = `looperget.design.job/1`
  {"schema": "looperget.design.job/1",
   "site":   looperget.design.site/1 (+ "pump": {"model","case"}),
   "design": looperget.design.design(site) 출력 (없으면 여기서 계산한다),
   "meta":   {"name","parcel","site_label","site_short","date",
              "map": {"png","pic","m_per_in","crop_m","wide_m"},          # 위성 프레임 (승인본 좌표 계약)
              "water": {"start_kind","start_line","a_name","buried","buried_len_m","pipes"},
              "texts": {"topo","filter_note","size_txt","wide_note","zone_how","start_on_prev","main_cap"},
              "sketch_pages": [...], "manifold": {...}, "tee_panel": bool,          # 대표 작도(규칙 7)
              "quote": {"label","recipient","manager","remarks","svc"},
              "part_img_dir", "price_db", "out_dir"}}

산출 = {out_dir}/30_제안서_{name}_{date}.pptx (+.pdf, _png/) · 40_견적서_{name}_{date}.xlsx · _job.json · _summary.json
프로덕션 app.py 무수정. 대표 대면 발행은 대표 전담(원칙 3) — 이 산출물은 초안이다.
"""
from __future__ import annotations

import json
import os
import re
import sys
from datetime import date as _date
from typing import Dict, Optional

from . import design as _design
from . import summary as _summary
from . import render_xlsx
# 🔴 [V104] `render_pptx` 는 **여기서 import 하지 않는다.** 그 모듈은 작도 도구(`tools/agri_overlay`)·
#    디자인 정본(`_디자인정본/표준_pptx`)·**61 MB 마스터 지면**에 기댄다 — 셋 다 배포 묶음에 없다
#    (배포 단위 = app.py + aquanaris_layout.py + looperget/ · 마스터는 GitHub 브라우저 한도 25 MB 초과).
#    맨 위에서 부르면 **배포 서버에서 publish 를 여는 순간** ModuleNotFoundError 로 죽는다
#    (대표 실사용 2026-09-08 「No module named 'agri_overlay'」). 그래서 **쓸 때 부른다.**

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SCHEMA_JOB = "looperget.design.job/1"


def _slug(s: str) -> str:
    return re.sub(r"[^\w가-힣\-]+", "_", s).strip("_")


def _price_db(meta: Dict) -> Dict:
    """단가 DB — **경로**(P2 파일)와 **값**(P3 앱이 시트에서 읽은 dict) 둘 다 받는다."""
    pdb = meta.get("price_db")
    if isinstance(pdb, dict):
        return pdb
    if isinstance(pdb, str) and pdb:
        try:
            with open(pdb, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


# ══════════════ P3(지도) → job ══════════════
# 🔴 좌표계가 다르다. P3 는 **북쪽이 +y**(지도), 제안서 지면은 **아래쪽이 +y**(승인본 작도 · MapFrame).
#    그래서 지면으로 넘길 때 y 의 부호를 뒤집는다 — **배치를 다시 풀지 않는다.**
#    (밭을 뒤집어 다시 계산하면 앵커가 반대 변에서 시작해 열이 달라진다 — ②에서 본 그림과 달라진다.)
def _fy(q):
    return [float(q[0]), -float(q[1])]


def _fpts(seq):
    return [_fy(q) for q in (seq or [])]


def flip_y(site: Dict, design: Dict):
    """P3(북쪽 +y) → 지면(아래쪽 +y). 좌표를 담은 칸만 골라서 뒤집는다(순수 · 복사본)."""
    import copy as _c
    site, design = _c.deepcopy(site), _c.deepcopy(design)
    for b in site.get("blocks") or []:
        b["polygon"] = _fpts(b.get("polygon"))
        if b.get("polygon_raw"):
            b["polygon_raw"] = _fpts(b["polygon_raw"])
        if b.get("u"):
            b["u"] = _fy(b["u"])
        if b.get("bars"):
            b["bars"] = [[_fy(a), _fy(c)] for a, c in b["bars"]]
    for r in site.get("routes") or []:
        r["pts"] = _fpts(r.get("pts"))
    for x in site.get("sources") or []:
        x["pt"] = _fy(x["pt"])
    for l in design.get("laterals") or []:
        for k in ("p0", "p1", "dir", "tap"):
            if l.get(k):
                l[k] = _fy(l[k])
        l["heads"] = _fpts(l.get("heads"))
        if l.get("path"):
            l["path"] = _fpts(l["path"])
    for h in design.get("heads") or []:
        h["pt"] = _fy(h["pt"])
    m = design.get("mainline") or {}
    for hd in m.get("headers") or []:
        hd["pt"] = _fy(hd["pt"])
    for r in m.get("routes") or []:
        if r.get("bends"):
            r["bends"] = [[_fy(q), d] for q, d in r["bends"]]
    m["tee_pts"] = [[_fy(q), tag] for q, tag in (m.get("tee_pts") or [])]
    m["end_pts"] = _fpts(m.get("end_pts"))
    return site, design


def map_contract(frame: Dict, origin, png_path: str, site: Dict, pad_m: float = 12.0) -> Dict:
    """`meta["map"]` — 지면이 읽는 **좌표 계약**(render_pptx.Map). 좌표는 이미 뒤집힌 것을 넣는다.

    `frame` = mapsrc 프레임(작도판과 같은 것) · `origin` = 그 좌표들의 기준 원점.
    """
    from . import mapsrc as _ms
    W, H = frame["size"]
    mpp = float(frame["m_per_px"])
    xs, ys = [], []
    for b in site.get("blocks") or []:
        for q in b.get("polygon") or []:
            xs.append(q[0])
            ys.append(q[1])
    for r in site.get("routes") or []:
        for q in r.get("pts") or []:
            xs.append(q[0])
            ys.append(q[1])
    for x in site.get("sources") or []:
        xs.append(x["pt"][0])
        ys.append(x["pt"][1])
    if not xs:
        raise ValueError("지면에 얹을 좌표가 없다")
    crop = [min(xs) - pad_m, min(ys) - pad_m, max(xs) + pad_m, max(ys) + pad_m]
    wide = [min(xs) - pad_m * 2.2, min(ys) - pad_m * 2.2, max(xs) + pad_m * 2.2, max(ys) + pad_m * 2.2]
    # 🔵 계약은 **선형**이고 지도 화소는 메르카토르라 조금 휜다. 그래서 상수(중심 m/px)로 잡지 않고
    #    **대상지 두 모서리에서 정확히 맞도록** 눈금을 뽑는다 — 밭 안에서는 오차가 사실상 0 이 된다.
    #    (300×120 m 실측: 중심 상수 0.81 m → 두 모서리 맞춤 0.0x m.)
    ax, ay = min(xs), min(ys)                      # 뒤집힌 좌표(아래쪽 +y)
    bx, by = max(xs), max(ys)
    pa = _ms.to_px(frame, *_ms.from_local_m([[ax, -ay]], origin)[0])
    pb = _ms.to_px(frame, *_ms.from_local_m([[bx, -by]], origin)[0])
    sx = (pb[0] - pa[0]) / (bx - ax) if abs(bx - ax) > 1e-6 else 1.0 / mpp
    sy = (pb[1] - pa[1]) / (by - ay) if abs(by - ay) > 1e-6 else 1.0 / mpp
    if not (sx > 0 and sy > 0):                    # 뒤집힌 좌표에서 두 눈금은 모두 양수여야 한다
        sx = sy = 1.0 / mpp
    px0 = pa[0] - ax * sx
    py0 = pa[1] - ay * sy
    return {"png": png_path, "m_per_in": 1.0,
            "pic": {"left_in": -px0 / sx, "top_in": -py0 / sy,
                    "w_in": W / sx, "h_in": H / sy, "src": [0, 0, W, H]},
            "crop_m": [round(v, 1) for v in crop], "wide_m": [round(v, 1) for v in wide]}


def job_from_p3(site: Dict, design: Dict, *, frame: Dict, origin, png_path: str,
                meta: Optional[Dict] = None) -> Dict:
    """지도로 그린 설계(P3) → 제안서·견적서 job. **값은 만들지 않는다** — 나온 설계를 옮길 뿐이다."""
    fsite, fdesign = flip_y(site, design)
    m = dict(meta or {})
    m.setdefault("name", site.get("name") or "대상지")
    m.setdefault("parcel", site.get("name") or "")
    m.setdefault("site_label", site.get("name") or "")
    m.setdefault("site_short", "관수 설계")
    m["map"] = map_contract(frame, origin, png_path, fsite)
    return {"schema": SCHEMA_JOB, "site": fsite, "design": fdesign, "meta": m}


def pptx_ready() -> tuple:
    """이 환경에서 **제안서 지면을 그릴 수 있는가** — (가능?, 못 그리는 이유).

    견적서(XLSX)는 패키지 안에서 끝나지만, 제안서(PPTX)는 마스터 지면과 작도 도구가 있어야 한다.
    """
    try:
        from . import render_pptx as _rp
    except Exception as e:
        return False, ("제안서 지면 도구가 이 환경에 없습니다(%s). 작도 도구·디자인 정본이 있는 "
                       "**작업 PC**에서만 지면을 그립니다." % e)
    if not os.path.exists(_rp.MASTER):
        return False, ("마스터 지면 파일이 없습니다 — %s. 61 MB 라 배포 묶음에 넣지 않았습니다."
                       % os.path.basename(_rp.MASTER))
    return True, ""


def run(job: Dict, out_dir: Optional[str] = None, *, pdf: bool = False, png: bool = False,
        xlsx: bool = True, pptx: bool = True, verbose: bool = True) -> Dict:
    assert job.get("schema") == SCHEMA_JOB, "job schema != %s" % SCHEMA_JOB
    meta = job.setdefault("meta", {})
    if "design" not in job or not job["design"]:
        job["design"] = _design(job["site"], _price_db(meta) or None)
    S = _summary.build(job)
    date = meta.get("date") or _date.today().isoformat()
    out_dir = out_dir or meta.get("out_dir") or os.path.join(ROOT, "_제안", "P2_" + _slug(S["name"]))
    os.makedirs(out_dir, exist_ok=True)
    tag = "%s_%s" % (_slug(S["name"]), date.replace("-", ""))
    res: Dict = {"out_dir": out_dir, "summary": S}

    with open(os.path.join(out_dir, "_job.json"), "w", encoding="utf-8") as f:
        json.dump(job, f, ensure_ascii=False, indent=1)
    with open(os.path.join(out_dir, "_summary.json"), "w", encoding="utf-8") as f:
        json.dump(S, f, ensure_ascii=False, indent=1)

    ok_pptx, why = pptx_ready() if pptx else (False, "제안서 생성을 끄고 실행했습니다")
    res["pptx"], res["pptx_skip"], res["render_log"], res["page_check"] = None, why, [], {}
    if ok_pptx:
        from . import render_pptx
        pptx_path = os.path.join(out_dir, "30_제안서_%s.pptx" % tag)
        r = render_pptx.Renderer(job, S, pptx_path, work_dir=os.path.join(out_dir, "_작업"))
        r.build()
        res["pptx"], res["pptx_skip"] = pptx_path, ""
        res["render_log"] = r.log
        res["page_check"] = render_pptx.check_pages(pptx_path)
        if pdf:
            res["pdf"] = render_pptx.export_pdf(pptx_path)
        if png:
            res["png"] = render_pptx.export_png(pptx_path, os.path.join(out_dir, "_png"))

    if xlsx:
        q = meta.get("quote", {})
        price_db = _price_db(meta)
        remarks = q.get("remarks")
        if isinstance(remarks, list):
            remarks = "\n".join(remarks)
        xr = render_xlsx.build(
            S, os.path.join(out_dir, "40_견적서_%s.xlsx" % tag), date=date,
            label=q.get("label", S["parcel"] or S["name"]),
            buyer={"recipient": q.get("recipient", ""), "manager": q.get("manager", "박형석"),
                   "serial": q.get("serial", "P2-%s" % tag)},
            remarks=remarks or ("1. 견적 유효기간: 견적일로부터 15일 이내\n"
                                + ("2. 영세율(부가세 0 %) 적용 — 농업경영체 등록확인서(농업회사법인은 사업자등록증) 사본 제출"
                                   if q.get("vat_zero") else "2. 부가가치세 별도")),
            svc=q.get("svc") or [], price_db=price_db, img_dir=meta.get("part_img_dir"), root=ROOT)
        res["xlsx"] = xr

    if verbose:
        if res["pptx"]:
            from pptx import Presentation
            n = len(Presentation(res["pptx"]).slides)
            print("제안서 %s · %d면" % (os.path.basename(res["pptx"]), n))
        else:
            print("제안서 지면 건너뜀 — " + res["pptx_skip"])
        print("  %s · %s ㎡(%s평) · 헤드 %d · 가지관 %d열 %d m · 주배관 %d m · 커버 %.0f %% · 합계 %s원"
              % (S["name"], format(S["area_m2"], ","), format(S["area_py"], ","), S["n_heads"], S["n_lats"],
                 S["lat_total_m"], S["main_total_m"], S["cover"] * 100, format(S["total"], ",")))
        for h in S["hydro"]:
            print("  구역 %-10s %2d두 · %d L/분 · 말단 %.2f bar · 반경 %.1f m · v50 %.2f · %s"
                  % (h["zone"], h["heads"], h["Q"], h["p_end"], h["radius_end"], h["v50"], h["verdict"]))
        if S["warnings"]:
            for w in S["warnings"]:
                print("  ⚠ " + w)
        if res["page_check"]:
            for i, bad in res["page_check"].items():
                print("  §9 점검 면%d: %s" % (i, " / ".join(bad)))
        if res["render_log"]:
            print("  렌더 메모: " + " · ".join(sorted(set(res["render_log"]))))
        if xlsx:
            print("견적서 %s · %d품목 · 이미지 %d(로컬 %d·드라이브 %d) · 합계 %s원 (F%d)"
                  % (os.path.basename(xr["path"]), xr["n_items"], xr["n_img"], xr["img_local"], xr["img_drive"],
                     format(xr["total"], ","), xr["total_row"]))
        if pdf:
            print("PDF " + res["pdf"])
        if png:
            print("PNG %d장 → %s" % (len(res["png"]), os.path.dirname(res["png"][0])))
    return res


# ══════════════ 데모 job — 승인 정답지 05 숙진리 211-1 ══════════════
def demo_job_05() -> Dict:
    """reproduce.site_05()의 site + 승인 지면의 메타(위성 프레임·대표 작도·문구)를 job으로 조립한다.
    대표 판단 문구(topo·filter_note·zone_how 등)는 승인 제안서(20260827)의 것을 그대로 인용한다."""
    from . import reproduce as R
    D = R.D
    CALC = os.path.join(D, "10_계산")
    ans, site = R.site_05()
    site["pump"] = {"model": "PU-3000I/P", "case": "흡상 0.5 m"}
    C = json.load(open(os.path.join(CALC, "_계산결과_숙진리.json"), encoding="utf-8"))
    W = ans["water"]
    WSUP = os.path.join(D, "숙진리 물공급.pptx")
    SKETCH = os.path.join(D, "05_211-1_숙진리", "30_제안서_배추밭_211-1_20260826_교정3.pptx")
    zones = ans["zones"]
    meta = {
        "name": "숙진리 211-1", "parcel": ans["parcel"]["label"], "site_label": ans["parcel"]["site"],
        "site_short": "논산 배추밭", "date": "2026-09-03",
        "map": {"png": os.path.join(CALC, "_숙진리_위성.png"), "pic": C["pic"], "m_per_in": C["m_per_in"],
                "crop_m": [196, 32, 306, 158], "wide_m": [150, 24, 312, 168]},
        "water": {"start_kind": "밭 입구 노출 파이프 3구(2구 사용)", "a_name": "밭 입구",
                  "start_line": "펌프·여과기는 급수원 쪽에 이미 설치돼 있습니다 — 본 제안은 밭 입구 노출 파이프부터입니다",
                  "buried": W["buried"], "buried_len_m": W["buried_len_m"], "pipes": W["pipes"]},
        "texts": {
            "topo": ["급수는 212-31 물탱크·펌프 1대에서 옵니다 — 기설 매설관이 그 펌프에 물려 있습니다",
                     "기설 매설관이 밭 입구에서 3구로 노출됩니다 — 그중 2구를 씁니다 (③은 예비)",
                     "파이프①은 곧장 줄1로, 파이프②(하단)는 꺾어 내려 T로 양쪽으로 갈라집니다"],
            "filter_note": ["여과기·압력계·시작부 밸브는 212-31 급수원의 것을 함께 씁니다 — 이 밭 견적에는 넣지 않았습니다 (212-31 견적에 있습니다)",
                            "여과기 미설치·미청소로 인한 피해에 대해 당사에게 책임을 물을 수 없음"],
            "size_txt": "3블록 — ①상단 1,030 · ②중앙 2,276 · ③우측 1,044 ㎡",
            "wide_note": "회색 점선 = 기설 매설 배관 — 212-31 급수원(물탱크·펌프)에서 옵니다",
            "zone_how": {z["name"]: z["how"] for z in zones},
            "start_on_prev": "a  시작부·T분기는 앞 면「밭 입구 매니폴드」 참조 — 이 밭은 펌프·여과기가 212-31 급수원 쪽에 이미 있습니다 (펌프단은 「물 공급 계통」 면 참조)",
        },
        "tee_panel": False,          # 매니폴드 면에 T 조립이 통째로 있다(규칙 10)
        "sketch_pages": [
            {"pptx": WSUP, "slide": 2, "title": "물 공급 계통 — 물탱크·펌프 1대로 212-31 · 211-1 함께",
             "cap_title": "급수원 계통 (공용)",
             "cap_lines": ["물탱크 → 펌프 (농가 보유)", "→ 여과기 120메쉬 → E호스밸브", "→ 압력계 H20 → 송수호스 50 mm",
                           "→ T분기에서 212-31 / 211-1 갈림", "이 밭 급수는 212-31 급수원에서 옵니다",
                           "여과기·압력계·밸브는 212-31 견적에", "이 밭 제안은 밭 입구 파이프부터입니다"],
             "cap_xy": [5.90, 1.05, 3.30], "cap_size": [15, 10.5],
             "replace": [["커플러", "카플러"]]},          # 대표 작도의 품목명 표기만 정본으로(규칙 7 — 그림은 그대로)
            {"pptx": WSUP, "slide": 3, "title": "매설관 분기 — 211-1 1구역 / 2구역",
             "cap_title": "매설관 분기 (농가 기설)",
             "cap_lines": ["매설 T에서 두 갈래로 나뉩니다", "곧장 내려가는 쪽 → 2구역 (%d두)" % zones[1]["heads"],
                           "엘보로 꺾는 쪽 → 1구역 (%d두)" % zones[0]["heads"], "이 구간은 농가 기설 — 본 제안 범위 밖입니다",
                           "밭 입구에서 3구로 노출됩니다 (다음 면)"],
             "cap_xy": [0.70, 1.35, 3.55], "cap_size": [16, 11.5]},
        ],
        "manifold": {"pptx": SKETCH, "slide": 6, "groups_only": True, "dx_in": -1.50,
                     "title": "주배관 연결부 상세 — 밭 입구 매니폴드 (노출 파이프 3구 중 2구 사용)",
                     "cap_title": "밭 입구 매니폴드",
                     "cap_lines": ["기설 매설관 %.0f m가 입구에서 3구로 노출됩니다" % W["buried_len_m"],
                                   "파이프① — 카플러 WF 4-3 → E호스밸브 → 송수호스 50",
                                   "파이프②(하단) — 숫엘보 90° → 암나사싱글밸브 → 파이프(수도관) → 카플러 WF 4-4 → T → 좌우",
                                   "T분기 세트 %s — CCCT 中 1 + 나가는 쪽 WF 4-2 2 + 들어오는 쪽 WF 4-4 1" % _summary.SETS["tee50"],
                                   "밸브 2개 = 구역 2개. 구역 전환이 밸브로 끝납니다",
                                   "파이프③은 예비 — 연결하지 않습니다",
                                   "매설관 구경 확인 후 카플러·엘보 규격 확정"],
                     "labels": [[4.30, 1.72, "카플러 WF 4-3", 1.3],
                                [5.30, 3.30, "숫엘보 90°", 1.2],
                                [3.30, 4.68, "파이프(수도관 · 농가 기설)", 1.55, "r"],
                                [5.38, 5.42, "카플러 WF 4-4", 1.3]],
                     "replace": [["위+우측 17두", "위+우측 %d두" % zones[0]["heads"]],
                                 ["하단 20두", "하단 %d두" % zones[1]["heads"]]]},
        "quote": {"label": "논산 배추밭 · 숙진리 211-1 (3블록)", "recipient": "논산 배추밭 (농업회사법인 새동네)",
                  "manager": "박형석",
                  # 영세율 안내는 기본 off(대표 결정 2026-09-04 · 건별 판단).
                  # 05는 실제로 영세율로 나간 승인 견적이라 재현상 on으로 둔다.
                  "vat_zero": True,
                  "remarks": ["1. 견적 유효기간: 견적일로부터 15일 이내",
                              "2. 영세율(부가세 0 %) 적용 — 농업경영체 등록확인서(농업회사법인은 사업자등록증) 사본 제출",
                              "3. 급수 — 212-31 물탱크·펌프 1대에서 매설관 71 m로 옵니다. 급수원 일체는 212-31(물공급부) 견적에 있습니다",
                              "4. 본 견적은 밭 입구에 노출된 매설 파이프 3구 중 2구부터입니다(③은 예비)",
                              "5. 매설관 구경 확인 후 카플러 WF 4-10 · 숫엘보 90° · 암나사싱글밸브 규격을 확정합니다",
                              "※ 배송비·설치 인건비 별도 · 단가 층위 = 소비자가 · 여분(세트 3 %·자재 5 %·롤 여유 12 %) 포함"]},
        "part_img_dir": os.path.join(D, "90_작업파일", "부속이미지"),
        "price_db": os.path.join(CALC, "_단가_DB.json"),
        "out_dir": os.path.join(ROOT, "_제안", "P2_숙진리_211-1"),
    }
    return {"schema": SCHEMA_JOB, "site": site, "meta": meta}


DEMOS = {"05": demo_job_05}


if __name__ == "__main__":
    args = sys.argv[1:]
    flags = {a for a in args if a.startswith("--")}
    pos = [a for a in args if not a.startswith("--")]
    if "--demo" in flags:
        key = pos[0] if pos else "05"
        job = DEMOS[key]()
    else:
        job = json.load(open(pos[0], encoding="utf-8"))
    out = None
    if "--out" in flags:
        out = pos[-1]
    run(job, out, pdf="--pdf" in flags, png="--png" in flags, xlsx="--no-xlsx" not in flags)

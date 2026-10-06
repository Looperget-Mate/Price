# -*- coding: utf-8 -*-
"""
looperget.design.publish — P2 원버튼: job(design.json) → 제안서 pptx(+pdf/png) + 견적 xlsx.

    python -m looperget.design.publish <job.json> [--out DIR] [--pdf] [--png] [--no-xlsx] [--reprice]
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

import base64
import json
import os
import re
import sys
from datetime import date as _date
from typing import Dict, List, Optional

from . import design as _design
from . import summary as _summary
from . import render_xlsx
# 🔴 [V104] `render_pptx` 는 **여기서 import 하지 않는다.** 그 모듈은 작도 도구(`tools/agri_overlay`)·
#    디자인 정본(`_디자인정본/표준_pptx`)·**61 MB 마스터 지면**에 기댄다 — 셋 다 배포 묶음에 없다
#    (배포 단위 = app.py + common/ + looperget/ · 마스터는 GitHub 브라우저 한도 25 MB 초과).
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
    for v in (site.get("link_intent") or {}).values():   # [V117 · K-03] 접점 도장의 좌표(지문 fp 는 y 부호 무관)
        if isinstance(v, dict) and v.get("at"):
            v["at"] = _fpts(v["at"])
    for l in design.get("laterals") or []:
        for k in ("p0", "p1", "dir", "tap"):
            if l.get(k):
                l[k] = _fy(l[k])
        if l.get("a") is not None:            # [V109] 열 위치 a = p·perp(u). y 를 뒤집으면 부호가 뒤집힌다(면8 사고의 뿌리)
            l["a"] = -float(l["a"])
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
    if site.get("contact") and not m.get("contact"):   # [V117 · 2-C] 연락처·회신 기한 — 저장된 site → 발행 meta
        m["contact"] = dict(site["contact"])
    if site.get("photos"):                   # [V116] 현장 사진 — 실제 파일만 · 자리는 뒤집힌 site 좌표로
        from . import photos as _ph
        m["photos"], m["photo_missing"] = _ph.resolve(site["photos"], m.get("photo_dir"), fsite)
        _ph.embed(m["photos"])               # [V117 · K-01] 축소본을 job 에 싣는다 — 서버 job 을 작업 PC 에서 발행해도 사진이 있다
    job = {"schema": SCHEMA_JOB, "site": fsite, "design": fdesign, "meta": m}
    embed_map_png(job)                       # [V109] 서버 job 을 내려받아 작업 PC 에서 돌릴 수 있게 그림을 품는다
    return job


# ══════════════ [V109] 서버 job → 작업 PC ══════════════
# 2026-09-14·15 유촌리·용산리: 서버 ④에서 받은 job 은 서버 경로(위성 png · out_dir · part_img_dir)를 품고 있어
# 앱이 안내한 한 줄(`python -m looperget.design.publish job.json`)이 이 PC 에서 그대로 실패했다.
# → job 에 위성 그림을 base64 로 넣고, 돌릴 때 경로를 이 PC 에 맞춘다. **값은 손대지 않는다.**
DEFAULT_IMG_DIR = os.path.join(ROOT, "_설계", "배추밭스프링클러_20260824", "90_작업파일", "부속이미지")


def embed_map_png(job: Dict) -> bool:
    m = (job.get("meta") or {}).get("map") or {}
    p = m.get("png")
    if p and os.path.exists(p) and not m.get("png_b64"):
        with open(p, "rb") as f:
            m["png_b64"] = base64.b64encode(f.read()).decode("ascii")
        return True
    return False


def _writable(d: str) -> bool:
    try:
        os.makedirs(d, exist_ok=True)
        t = os.path.join(d, "_쓰기시험")
        with open(t, "w") as f:
            f.write("ok")
        os.remove(t)
        return True
    except Exception:
        return False


def localize(job: Dict, job_path: Optional[str] = None) -> List[str]:
    """다른 PC(서버)에서 만든 job 의 **경로**를 이 PC 에 맞춘다. → 손본 내역(없으면 [])."""
    meta = job.setdefault("meta", {})
    notes: List[str] = []
    od = meta.get("out_dir")
    if od and not _writable(od):
        nm = os.path.basename(str(od).replace("\\", "/").rstrip("/")) or "P3_대상지"
        meta["out_dir"] = os.path.join(ROOT, "_제안", nm)
        notes.append("산출 폴더 %s → %s" % (od, meta["out_dir"]))
    m = meta.get("map") or {}
    png = m.get("png")
    if m and (not png or not os.path.exists(png)):
        base = meta.get("out_dir") or (os.path.dirname(os.path.abspath(job_path)) if job_path else None)
        beside = os.path.join(os.path.dirname(os.path.abspath(job_path)), "_위성.png") if job_path else None
        if m.get("png_b64"):
            base = base or os.path.join(ROOT, "_제안")
            os.makedirs(base, exist_ok=True)
            target = os.path.join(base, "_위성.png")
            with open(target, "wb") as f:
                f.write(base64.b64decode(m["png_b64"]))
            m["png"] = target
            notes.append("위성 그림을 job 에서 꺼내 %s 에 씀" % target)
        elif beside and os.path.exists(beside):
            m["png"] = beside
            notes.append("위성 그림 = job 옆 %s" % beside)
        else:
            raise FileNotFoundError(
                "위성 그림이 없습니다 — job 의 png 경로(%s)가 이 PC 에 없고 job 안에 png_b64 도 없습니다. "
                "V109 이후 서버 ④에서 내려받은 job 은 그림을 품고 있습니다 — 다시 내려받으세요." % png)
    imgd = meta.get("part_img_dir")
    if imgd and not os.path.isdir(imgd):
        meta["part_img_dir"] = DEFAULT_IMG_DIR if os.path.isdir(DEFAULT_IMG_DIR) else None
        notes.append("부속 사진 폴더 %s → %s" % (imgd, meta["part_img_dir"]))
    elif not imgd and os.path.isdir(DEFAULT_IMG_DIR):
        meta["part_img_dir"] = DEFAULT_IMG_DIR
    return notes


def pptx_ready() -> tuple:
    """이 환경에서 **제안서 지면을 그릴 수 있는가** — (가능?, 못 그리는 이유).

    견적서(XLSX)는 패키지 안에서 끝나지만, 제안서(PPTX)는 마스터 지면과 작도 도구가 있어야 한다.
    """
    try:
        from . import render_pptx as _rp
    except Exception as e:
        return False, ("제안서 지면 도구가 이 환경에 없습니다(%s). 배포 묶음에 `tools/agri_overlay.py`·"
                       "`_디자인정본/표준_pptx.py` 가 있어야 서버에서도 지면을 그립니다 — 견적서(XLSX)는 그대로 나옵니다." % e)
    if not os.path.exists(_rp.MASTER):
        # [V117 · 3단계(b)] 원본(61 MB · 작업 PC)이 없으면 경량 사본(16.5 MB · 배포 묶음)을 쓴다 — 둘 다 없을 때만 끈다.
        return False, ("마스터 지면 파일이 없습니다 — 원본(%s)도 경량본(%s)도 없습니다. 배포 묶음에 경량본을 넣으세요"
                       "(tools/prepare_github_upload.py)." % (os.path.basename(_rp.MASTER_FULL), os.path.basename(_rp.MASTER_SLIM)))
    return True, ""


def master_status() -> Dict:
    """[V117 · 3단계(b)] 지금 쓰는 마스터(원본/경량본)와 경고(경량본이 옛 원본에서 나왔으면) — 도구가 없으면 kind=없음."""
    try:
        from . import render_pptx as _rp
    except Exception:
        return {"path": None, "kind": "없음", "warn": ""}
    return _rp.master_status()


def reprice(job: Dict, price_db: Optional[Dict] = None, tier: str = "소비자가") -> Dict:
    """[V114 · F08] 저장된 job 의 물량(design.bom)에 단가를 **명시적으로** 다시 붙인다 → 새 money.

    물량은 바꾸지 않는다. 예전 money 가 있으면 `money_prev` 로 남겨 무엇이 바뀌었는지 볼 수 있게 한다 —
    옛 가격이 조용히 바뀌거나, 단가가 없는데 0원으로 보이는 일을 막는다. run() 은 이 함수를 스스로 부르지 않는다."""
    from . import quote as _quote
    meta = job.setdefault("meta", {})
    pdb = price_db if price_db is not None else _price_db(meta)
    if not pdb:
        raise ValueError("단가 DB 가 없습니다 — meta.price_db(경로 또는 dict)를 주세요")
    d = job["design"]
    if d.get("money"):
        d["money_prev"] = d["money"]
    d["money"] = _quote.price(d["bom"], pdb, tier)
    d["money"]["priced_on"] = _date.today().isoformat()
    return d["money"]


def consistency(pptx_path: Optional[str], S: Dict, xr: Optional[Dict], xr2: Optional[Dict] = None,
                customer: bool = False) -> Dict:
    """[V114 · F06] 생성물 대조 — 지면 합계 · 견적서 합계 · 구역 면 수 · 관경별 부속 코드 · 표지 관문 표시.

    기계 검사다(6축 채점 아님). 어긋나면 run() 이 관문을 **차단**으로 올린다.
    [V115 · C03] 시공업체용 두 단가 견적(xr2)도 같은 합계 칸(소비자가 열)을 대조한다.
    [V117 · 2단계] customer=True(고객 전달본) — 표지 관문 도장이 **없어야** 한다(내부본은 있어야 한다)."""
    issues, checked = [], []
    C = S.get("cost") or {}
    grand = C.get("grand") if C.get("priced") else None
    for nm, x in (("견적서", xr), ("시공업체용 견적서", xr2)):
        if x is None:
            continue
        if grand is not None:
            checked.append("%s 합계" % nm)
            if x.get("total_text") is not None:        # [V115 · C02] 지면은 숫자인데 견적서 칸은 글자
                issues.append("%s 합계 칸이 「%s」 ≠ 지면 합계 %s" % (nm, x["total_text"], format(grand, ",")))
            elif int(x["total"]) != int(grand):
                issues.append("%s 합계 %s ≠ 지면 합계 %s" % (nm, format(x["total"], ","), format(grand, ",")))
        else:
            checked.append("%s 합계(미확정)" % nm)       # [R03] 무단가면 견적서 합계 칸도 「미확정」이어야 한다
            if x.get("total_text") != "미확정":
                issues.append("단가 미확정인데 %s 합계 칸이 %s" % (nm, x.get("total")))
    if pptx_path:
        from pptx import Presentation
        prs = Presentation(pptx_path)
        texts = []
        for sl in prs.slides:
            buf = []
            for sh in sl.shapes:
                if sh.has_text_frame:
                    buf.append(sh.text_frame.text)
                if getattr(sh, "has_table", False) and sh.has_table:
                    buf += [c.text for r in sh.table.rows for c in r.cells]
            texts.append("\n".join(buf))
        allt = "\n".join(texts).replace(" ", "")
        checked.append("지면 합계")
        want = format(grand, ",") if grand is not None else "미확정"
        if ("합계:" + want) not in allt:                # [R10] 「₩ … 원」 겹침 제거 후 형식 = 「합계: 1,698,500 원」
            issues.append("지면 합계 칸에 %s 이 없습니다" % want)
        nz = len(S["zones"]) if len(S["zones"]) > 1 else 0
        got = sum(1 for t in texts if "살수 예시 (" in t and "전체 살수" not in t)
        checked.append("구역 면 수")
        if got != nz:
            issues.append("구역 살수 면 %d장 ≠ 구역 %d개" % (got, nz))
        mm = int(S.get("main_mm") or 50)
        if mm != 50:
            checked.append("관경별 부속 코드")
            for code in ("02051", "01403", "00825", "00827", "5050"):
                if any(code in t for t in texts if "연결부 상세" in t or "연결부 요약" in t):
                    issues.append("%d mm 설계의 연결부 면에 50 mm 부속·세트 「%s」" % (mm, code))
        if customer:
            checked.append("표지 관문 표시 없음(고객본)")
            if S["gate"]["level"] != "ok" and S["gate"]["label"] in texts[0]:   # [D8] 도장 라벨만 남아도(「● 」 없이) 잡는다
                issues.append("고객 전달본 표지에 관문 표시(%s)가 남았습니다" % S["gate"]["label"])
        else:
            checked.append("표지 관문 표시")
            if S["gate"]["level"] != "ok" and S["gate"]["label"] not in texts[0]:
                issues.append("표지에 관문 표시(%s)가 없습니다" % S["gate"]["label"])
    return {"ok": not issues, "issues": issues, "checked": checked}


def _customer_set(job: Dict, S: Dict, res: Dict, out_dir: str, tag: str, date: str, image_fetch=None) -> Dict:
    """[V117 · 2단계] 고객 전달본 한 벌 — PPTX(내부본 손질) · 40(요약 사본 손질로 다시 굽기) · 41(태그만) + 기계 검사.

    수량·단가·합계는 내부본과 **같은 summary** 에서 온다 — 손질은 이름·규격·비고·특약 글자만(두 벌 합계 동일)."""
    from . import customer as CU
    from . import segments as SG
    meta = job.get("meta") or {}
    q = meta.get("quote") or {}
    prof = SG.profile(job.get("site") or {})
    pdb = _price_db(meta)
    names = CU.name_map(pdb, S.get("bom") or [])
    sets = CU.set_map(S, meta.get("sets_db"))
    R = CU.load_rules()
    out: Dict = {"segment": prof["key"], "pptx": None, "xlsx": None, "xlsx2": None, "report": None}
    remarks = q.get("remarks")
    if isinstance(remarks, list):
        remarks = "\n".join(remarks)
    remarks = remarks or ("1. 견적 유효기간: 견적일로부터 15일 이내\n"
                          + ("2. 영세율(부가세 0 %) 적용 — 농업경영체 등록확인서(농업회사법인은 사업자등록증) 사본 제출"
                             if q.get("vat_zero") else "2. 부가가치세 별도"))
    S_c, rem_c, cx = CU.xlsx_summary(S, remarks, R=R, names=names, sets=sets)
    moved = list(cx.moved)
    if res.get("pptx"):
        out["pptx"] = os.path.join(out_dir, "30_제안서_%s.pptx" % tag)
        out["report"] = CU.pptx(res["pptx"], out["pptx"], S, meta, R=R, extra_moved=moved, names=names, sets=sets)
    head = prof.get("head")
    label = q.get("label", S["parcel"] or S["name"])
    buyer = {"recipient": q.get("recipient", ""), "manager": CU.contact_manager(CU.contact_of(meta), q.get("manager", "박형석")),
             "serial": q.get("serial", "P2-%s" % tag)}
    if res.get("xlsx"):
        out["xlsx"] = render_xlsx.build(
            S_c, os.path.join(out_dir, "40_견적서_%s.xlsx" % tag), date=date, label=label, buyer=buyer, remarks=rem_c,
            svc=q.get("svc") or [], price_db=pdb, img_dir=meta.get("part_img_dir"), root=ROOT, fetch=image_fetch,
            head_labels=head, site_name=S["name"], hide_code=not prof.get("quote_code", True))
    if res.get("xlsx2"):
        S_t, rem_t, _cx2 = CU.xlsx_summary(S, (q.get("remarks") and remarks) or "1. 견적 유효기간: 견적일로부터 15일 이내\n2. 부가가치세 별도",
                                           mode="tags", R=R, names=names, sets=sets)
        out["xlsx2"] = render_xlsx.build(
            S_t, os.path.join(out_dir, "41_견적서_시공업체용_%s.xlsx" % tag), date=date, label=label + " (시공업체용)",
            buyer=buyer, remarks=rem_t, svc=q.get("svc") or [], price_db=pdb, img_dir=meta.get("part_img_dir"), root=ROOT,
            fetch=image_fetch, tier2=q["tier2"], head_labels=head, site_name=S["name"])
    out["consistency"] = consistency(out["pptx"], S, out["xlsx"], out["xlsx2"], customer=True)
    # 기계 검사 — 고객본 PPTX·40 전 글자에 태그·규칙 번호·품목 코드·세트 코드·금지어 0건(40 품목 코드 칸은 프로필이 보이게 둔 것만 예외)
    codes = set(names) | {str(b.get("code")) for b in S.get("bom") or []}
    items = (CU.pptx_items(out["pptx"]) if out["pptx"] else []) + (CU.xlsx_items(out["xlsx"]["path"], keep_code_col=prof.get("quote_code", True)) if out["xlsx"] else [])
    out["scan"] = CU.scan_text(items, codes, R)
    tags41 = []
    if out["xlsx2"]:
        tags41 = [h for h in CU.scan_text(CU.xlsx_items(out["xlsx2"]["path"]), codes, R) if h["kind"] == "태그"]
    out["scan"] += tags41
    tot = [x["total"] for x in (res.get("xlsx"), out["xlsx"]) if x]
    out["totals_equal"] = len(set(tot)) <= 1
    if not out["totals_equal"]:
        out["consistency"]["ok"] = False
        out["consistency"]["issues"].append("두 벌 합계 다름 %s" % tot)
    out["needs_copy"] = [r["id"] for r in R.get("rules") or [] if r.get("needs_copy") and not r.get("value")]
    return out


INTERNAL_SUFFIX = "_내부검토"        # [V117 · 2단계] 내부 검토본 파일명 접미 — 고객 전달본이 기존 파일명을 쓴다
BLOCKED_SUFFIX = "_차단"             # [V117 · 3차 검토 D1] 최종 관문 차단이면 고객본 파일명 끝에 붙여 내보내지 않는다


def _withhold_customer(out_dir: str, tag: str) -> List[str]:
    """[D1] 고객 전달본 이름(기존 파일명)의 파일을 `…_차단` 으로 옮긴다 — 이번 실행분이든 지난 실행이 남긴 것이든.
    최종 관문이 차단(고객본 검사 실패 포함)이거나 내부본 대조가 어긋나면 고객본이라는 이름의 파일을 남기지 않는다."""
    moved = []
    for nm in ("30_제안서_%s.pptx" % tag, "30_제안서_%s.pdf" % tag, "40_견적서_%s.xlsx" % tag,
               "41_견적서_시공업체용_%s.xlsx" % tag):
        src = os.path.join(out_dir, nm)
        if os.path.exists(src):
            base, ext = os.path.splitext(src)
            dst = base + BLOCKED_SUFFIX + ext
            os.replace(src, dst)
            moved.append(dst)
    return moved


def run(job: Dict, out_dir: Optional[str] = None, *, pdf: bool = False, png: bool = False,
        xlsx: bool = True, pptx: bool = True, verbose: bool = True,
        job_path: Optional[str] = None, image_fetch=None, customer: bool = True) -> Dict:
    """`image_fetch(code) -> data-URI|None` = 앱이 주는 사진 공급자(서버에는 서비스계정 파일이 없다 · V109).

    [V117 · 2단계] 한 번에 두 벌 — 내부 검토본(`…_내부검토` · 지금 출력 그대로 · res["pptx"]·res["xlsx"]) +
    고객 전달본(기존 파일명 · res["customer"] · design.customer 가 내부본을 손질). 관문 차단이면 고객본은 만들지 않는다."""
    assert job.get("schema") == SCHEMA_JOB, "job schema != %s" % SCHEMA_JOB
    meta = job.setdefault("meta", {})
    notes = localize(job, job_path)          # [V109] 서버 job 이면 경로를 이 PC 에 맞춘다(값 무변경)
    if meta.get("photos"):
        # 🔴 [V117 · K-01·K-10] 현장 사진은 **렌더 전에** 이 PC 에서 열리는지 확정한다 — 서버 경로면 job 에 실린 축소본을
        #    풀고, 그것도 없으면 누락(대체 없음). 누락은 summary 관문에 들어가 표지 수 = 앱 수가 된다(예전엔 렌더에서
        #    FileNotFoundError 로 발행 전체가 멈췄고, 누락은 렌더 뒤에 더해져 표지와 앱의 확인 항목 수가 달랐다).
        from . import photos as _ph
        _pw = os.path.join(out_dir or meta.get("out_dir") or os.path.join(ROOT, "_제안"), "_작업", "사진_job")
        meta["photos"], _miss = _ph.localize(meta["photos"], _pw)
        meta["photo_missing"] = list(dict.fromkeys(list(meta.get("photo_missing") or []) + _miss))
    if "design" not in job or not job["design"]:
        job["design"] = _design(job["site"], _price_db(meta) or None)
    S = _summary.build(job)
    if not job["design"].get("money") and _price_db(meta):
        notes.append("단가 DB 가 있지만 이 job 은 단가 없이 저장됐습니다 — 금액을 붙이려면 reprice(job) 를 먼저 부르세요(--reprice)")
    date = meta.get("date") or _date.today().isoformat()
    out_dir = out_dir or meta.get("out_dir") or os.path.join(ROOT, "_제안", "P2_" + _slug(S["name"]))
    os.makedirs(out_dir, exist_ok=True)
    tag = "%s_%s" % (_slug(S["name"]), date.replace("-", ""))
    res: Dict = {"out_dir": out_dir, "summary": S, "localized": notes, "gate": S["gate"]}

    with open(os.path.join(out_dir, "_job.json"), "w", encoding="utf-8") as f:
        json.dump(job, f, ensure_ascii=False, indent=1)
    with open(os.path.join(out_dir, "_summary.json"), "w", encoding="utf-8") as f:
        json.dump(S, f, ensure_ascii=False, indent=1)
    from .supply_docs import html_document
    res["supply_html"] = os.path.join(out_dir, "42_급수연결조건_%s.html" % tag)
    with open(res["supply_html"], "w", encoding="utf-8") as f:
        f.write(html_document(S))

    ok_pptx, why = pptx_ready() if pptx else (False, "제안서 생성을 끄고 실행했습니다")
    res["pptx"], res["pptx_skip"], res["render_log"], res["page_check"] = None, why, [], {}
    IS = INTERNAL_SUFFIX if customer else ""
    if ok_pptx:
        from . import render_pptx
        pptx_path = os.path.join(out_dir, "30_제안서_%s%s.pptx" % (tag, IS))
        r = render_pptx.Renderer(job, S, pptx_path, work_dir=os.path.join(out_dir, "_작업"), image_fetch=image_fetch)
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
        _stamp = " (내부 검토용 — 발송 불가)" if S["gate"]["level"] == "blocked" else ""
        from . import customer as _cu
        _mgr = _cu.contact_manager(_cu.contact_of(meta), q.get("manager", "박형석"))   # [V117 · 2-C] 기존 담당자 칸
        from . import segments as _sg
        _head = _sg.profile(job.get("site") or {}).get("head")          # [V117 · 2-A] 관급·건설 머리글(농업 = None · 현행)
        xr = render_xlsx.build(
            S, os.path.join(out_dir, "40_견적서_%s%s.xlsx" % (tag, IS)), date=date,
            label=q.get("label", S["parcel"] or S["name"]) + _stamp,
            buyer={"recipient": q.get("recipient", ""), "manager": _mgr,
                   "serial": q.get("serial", "P2-%s" % tag)},
            remarks=remarks or ("1. 견적 유효기간: 견적일로부터 15일 이내\n"
                                + ("2. 영세율(부가세 0 %) 적용 — 농업경영체 등록확인서(농업회사법인은 사업자등록증) 사본 제출"
                                   if q.get("vat_zero") else "2. 부가가치세 별도")),
            svc=q.get("svc") or [], price_db=price_db, img_dir=meta.get("part_img_dir"), root=ROOT,
            fetch=image_fetch, head_labels=_head, site_name=S["name"])
        res["xlsx"] = xr
        # [V109] 시공업체용 두 단가 견적(대리점가1 | 소비자가 | 이익율) — 09-15 용산리에서 손으로 만들던 41_ 파일.
        if q.get("tier2"):
            res["xlsx2"] = render_xlsx.build(
                S, os.path.join(out_dir, "41_견적서_시공업체용_%s%s.xlsx" % (tag, IS)), date=date,
                label=q.get("label", S["parcel"] or S["name"]) + " (시공업체용)" + _stamp,
                buyer={"recipient": q.get("recipient", ""), "manager": _mgr,
                       "serial": q.get("serial", "P2-%s" % tag)},
                remarks=remarks or "1. 견적 유효기간: 견적일로부터 15일 이내\n2. 부가가치세 별도",
                svc=q.get("svc") or [], price_db=price_db, img_dir=meta.get("part_img_dir"), root=ROOT,
                fetch=image_fetch, tier2=q["tier2"], head_labels=_head, site_name=S["name"])
        # [2026-10-07 대표] 내부 검토 세 단가(매입가 | 중간업체가 | 소비자가 | 이익율) — 고객 전달본으로는 만들지 않는다.
        if q.get("tier3"):
            res["xlsx3"] = render_xlsx.build(
                S, os.path.join(out_dir, "40_견적서_원가세단가_%s%s.xlsx" % (tag, IS)), date=date,
                label=q.get("label", S["parcel"] or S["name"]) + " (내부 검토 · 원가 포함 · 외부 발송 금지)",
                buyer={"recipient": q.get("recipient", ""), "manager": _mgr,
                       "serial": q.get("serial", "P2-%s" % tag)},
                remarks=remarks or "내부 검토용 — 매입가 포함. 고객·중간업체에 보내지 않습니다.",
                svc=q.get("svc") or [], price_db=price_db, img_dir=meta.get("part_img_dir"), root=ROOT,
                fetch=image_fetch, tier3=list(q["tier3"]), head_labels=_head, site_name=S["name"])

    # [V114 · F06] 생성물 대조 — 어긋나면 **차단**으로 올린다(정상 완료로 표시하지 않는다).
    res["consistency"] = consistency(res.get("pptx"), S, res.get("xlsx"), res.get("xlsx2"))
    # [V117 · 2단계] 고객 전달본 — 내부본을 손질한 사본(삭제·이동·치환만 · customer_text.json). 차단이면 만들지 않는다.
    res["customer"] = None
    if customer and S["gate"]["level"] == "blocked":
        res["customer"] = {"skip": "관문 차단 — 고객 전달본을 만들지 않았습니다(내부 검토본만)"}
    elif customer:
        res["customer"] = _customer_set(job, S, res, out_dir, tag, date, image_fetch)
        if pdf and res["customer"].get("pptx"):          # PDF 는 PowerPoint 전용(작업 PC)
            from . import render_pptx
            res["customer"]["pdf"] = render_pptx.export_pdf(res["customer"]["pptx"])
        cc = res["customer"]["consistency"]
        if not cc["ok"] or res["customer"]["scan"]:
            g = dict(res["gate"])
            g["block"] = list(g["block"]) + ["고객본 불일치: " + x for x in cc["issues"]] + \
                (["고객본에 내부 표기 %d건 남음(%s)" % (len(res["customer"]["scan"]),
                                                   " · ".join(sorted({h["hit"] for h in res["customer"]["scan"]}))[:120])]
                 if res["customer"]["scan"] else [])
            g["level"], g["label"] = "blocked", "내부 검토용 — 결함 %d건 · 발송 불가" % len(g["block"])
            res["gate"] = g
    if not res["consistency"]["ok"]:
        g = dict(S["gate"])
        g["block"] = list(g["block"]) + ["생성물 불일치: " + x for x in res["consistency"]["issues"]]
        g["level"], g["label"] = "blocked", "내부 검토용 — 결함 %d건 · 발송 불가" % len(g["block"])
        res["gate"] = g
    # [V117 · 3차 검토 D1] 최종 관문이 차단이거나 내부본 대조가 어긋나면 **고객 전달본 파일을 남기지 않는다**(`_차단` 접미 ·
    #    앱은 내려받기 단추를 숨긴다). 앞 실행이 같은 폴더에 남긴 고객본도 함께 옮긴다.
    if customer and (res["gate"]["level"] == "blocked" or not res["consistency"]["ok"]):
        _held = _withhold_customer(out_dir, tag)
        cu = res.get("customer") or {}
        why = "관문 차단(%s) — 고객 전달본을 내보내지 않습니다(내부 검토본만)" % res["gate"]["label"]
        if cu and not cu.get("skip"):
            cu["withheld"] = why
            cu["withheld_files"] = _held
            for k in ("pptx", "pdf", "xlsx", "xlsx2"):
                cu[k] = None
        elif cu:
            cu["withheld_files"] = _held
    # [V116] 현장 사진 누락 — 다른 사진으로 채우지 않았다 · 담당자가 확인할 항목.
    # [V117 · K-10] 관문에는 summary.build 가 **렌더 전에** 넣었다(표지·견적서·앱이 같은 수). 여기서 다시 더하지 않는다.
    res["photo_missing"] = list(meta.get("photo_missing") or [])
    with open(os.path.join(out_dir, "_gate.json"), "w", encoding="utf-8") as f:
        json.dump({"gate": res["gate"], "consistency": res["consistency"],
                   "customer": {k: v for k, v in (res.get("customer") or {}).items() if k not in ("xlsx", "xlsx2")}},
                  f, ensure_ascii=False, indent=1, default=str)

    if verbose:
        print("관문: %s" % res["gate"]["label"])
        for x in res["gate"]["block"] + res["gate"]["conditional"]:
            print("  · " + x)
        for n in notes:
            print("  ↪ 경로 보정: " + n)
        if res["pptx"]:
            from pptx import Presentation
            n = len(Presentation(res["pptx"]).slides)
            print("제안서 %s · %d면" % (os.path.basename(res["pptx"]), n))
        else:
            print("제안서 지면 건너뜀 — " + res["pptx_skip"])
        print("  %s · %s ㎡(%s평) · 헤드 %d · 가지관 %d열 %d m · 주배관 %d m · 커버 %.0f %% · 합계 %s원"
              % (S["name"], format(S["area_m2"], ","), format(S["area_py"], ","), S["n_heads"], S["n_lats"],
                 S["lat_total_m"], S["main_total_m"], S["cover"] * 100,
                 format(S["cost"]["grand"], ",") if S["cost"]["grand"] is not None else "미확정"))
        from .supply_docs import zone_line
        for row in S.get("supply", {}).get("zones", []):
            print("  " + zone_line(row))
        for h in ([] if S.get("supply") else S["hydro"]):
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
            if res.get("xlsx2"):
                x2 = res["xlsx2"]
                print("시공업체용 %s · %s 합계 %s원 / %s 합계 %s원"
                      % (os.path.basename(x2["path"]), x2["tier2"], format(x2["total2"], ","),
                         x2["tier"], format(x2["total"], ",")))
        cu = res.get("customer") or {}
        if cu.get("skip"):
            print("고객 전달본 — " + cu["skip"])
        elif cu.get("withheld"):
            print("고객 전달본 — %s · %s" % (cu["withheld"], " · ".join(os.path.basename(x) for x in cu.get("withheld_files") or [])))
        elif cu:
            print("고객 전달본 %s · %s · 내부 표기 남음 %d건 · 확인 목록 +%d · 두 벌 합계 %s"
                  % (os.path.basename(cu["pptx"] or "-"), os.path.basename((cu.get("xlsx") or {}).get("path", "-")),
                     len(cu["scan"]), len(((cu.get("report") or {}).get("ask") or {}).get("added") or []),
                     "같음" if cu["totals_equal"] else "다름"))
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
    if "--reprice" in flags:
        reprice(job)
    out = None
    if "--out" in flags:
        out = pos[-1]
    run(job, out, pdf="--pdf" in flags, png="--png" in flags, xlsx="--no-xlsx" not in flags,
        job_path=(None if "--demo" in flags else pos[0]))

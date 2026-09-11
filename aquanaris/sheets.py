# -*- coding: utf-8 -*-
"""[아쿠나리스] AQ_Items · AQ_Sites · AQ_Boxes · AQ_ItemBox 시트 — app.py(V107) L812-851 · L872-1050 그대로.
문서 핸들 _aq_sh·AQ_SHEET_ID 는 common/db.py(Users 와 공용).
"""
import json
import gspread
import streamlit as st
from common.db import *


# ==========================================
# [V41] 아쿠나리스(농협 관수코너) — 시트 로드
#  - 단가 정본은 Products. AQ_Items는 진열 속성만 담는다(단가 컬럼 없음).
#  [V46] 읽기쿼터 보호: 4개 시트를 일괄 1회 로드(open_by_key — 이름검색 제거) + 429 친화 안내.
#        구글 무료 한도 = 분당 읽기 60회/사용자(서비스계정 공유) — 개별 open×4가 세션시작 읽기와
#        겹치며 429 유발(2026-07-18 배포 실증) → 열기 1회+읽기 4회로 축소.
# ==========================================

@st.cache_data(ttl=600, show_spinner="아쿠나리스 데이터 로드 중…")
def aq_load_all():
    """AQ 4개 시트 일괄 로드. 반환 (dict|None, 오류문자열)."""
    if not gc: return None, "구글 서비스 미연결"
    try:
        sh = _aq_sh()
        data = {}
        for ws_name in ("AQ_Items", "AQ_Sites", "AQ_Boxes", "AQ_ItemBox"):
            try:
                data[ws_name] = sh.worksheet(ws_name).get_all_records()
            except gspread.exceptions.WorksheetNotFound:
                data[ws_name] = []
        return data, ""
    except Exception as e:
        return None, str(e)

def aq_err_str(e):
    """[V46] 오류를 사용자 친화 문구로 (429 쿼터 안내 포함)."""
    s = str(e)
    if "429" in s or "Quota exceeded" in s or "RATE_LIMIT" in s:
        return "구글 시트 분당 요청 한도 초과 — 약 1분 후 다시 시도해주세요. (데이터는 안전합니다)"
    return s

def aq_load_items():
    """AQ_Items → list[dict]. 품목코드 zfill(5)·섹션 zfill(2) 정규화."""
    data, err = aq_load_all()
    st.session_state["_aq_read_err"] = err
    if not data: return []
    out = []
    for r in data["AQ_Items"]:
        code = str(r.get("품목코드", "")).strip()
        if not code: continue
        r["품목코드"] = code.zfill(5)
        sec = str(r.get("섹션", "")).strip()
        r["섹션"] = sec.zfill(2) if sec else ""
        out.append(r)
    return out

def aq_load_sites():
    """AQ_Sites → list[dict] (농협명 있는 행만)."""
    data, err = aq_load_all()
    if not data: return []
    return [r for r in data["AQ_Sites"] if str(r.get("농협명", "")).strip()]

# [V42] 유연 상자 모델 — 품목↔상자 매핑은 고정이 아니라 축적 데이터.
#  AQ_Boxes = 상자 마스터(농협별 새 상자 추가 가능) / AQ_ItemBox = 품목×상자 수용량 기록(계속 축적).
#  AQ_Items의 기본상자/기본수량은 폴백 기본값일 뿐이다.
def aq_load_boxes():
    """AQ_Boxes → list[dict] (상자종류 있는 행만)."""
    data, err = aq_load_all()
    if not data: return []
    return [r for r in data["AQ_Boxes"] if str(r.get("상자종류", "")).strip()]

def aq_load_itembox():
    """AQ_ItemBox → list[dict]. 품목코드 zfill(5)."""
    data, err = aq_load_all()
    if not data: return []
    out = []
    for r in data["AQ_ItemBox"]:
        code = str(r.get("품목코드", "")).strip()
        if not code or not str(r.get("상자종류", "")).strip(): continue
        r["품목코드"] = code.zfill(5)
        out.append(r)
    return out

def aq_capacity_map(itembox_recs):
    """수용량 레코드 → {품목코드: {상자종류: (수용수량, 근거)}}. 나중 레코드가 우선(최신 축적 반영)."""
    m = {}
    for r in itembox_recs:
        try: q = int(float(str(r.get("수용수량") or 0)))
        except Exception: continue
        if q <= 0: continue
        m.setdefault(r["품목코드"], {})[str(r.get("상자종류", "")).strip()] = (q, str(r.get("근거", "")).strip())
    return m

def aq_append_row(ws_name, row_vals):
    """축적형 시트(AQ_ItemBox·AQ_Boxes·AQ_Sites 신규행)에 1행 추가.
    ※ 추가 전용 로그 시트라 append_row가 안전(§2-2 clear+update는 기존 전체재기록 시트용)."""
    _aq_sh().worksheet(ws_name).append_row(
        [str(v) for v in row_vals], value_input_option='RAW')

def aq_update_item_cell(code, col_name, value):
    """[V48] AQ_Items에서 품목코드 행을 찾아 1셀 갱신 (컬럼 없으면 헤더에 추가). 이미지ISO 등록에 사용."""
    ws = _aq_sh().worksheet("AQ_Items")
    vals = ws.get_all_values()
    hdr = vals[0]
    if col_name not in hdr:
        if ws.col_count <= len(hdr):
            ws.add_cols(1)
        ws.update_cell(1, len(hdr) + 1, col_name)
        hdr.append(col_name)
    ci = hdr.index(col_name) + 1
    code = str(code).strip().zfill(5)
    for i, row in enumerate(vals[1:], start=2):
        if row and str(row[0]).strip().zfill(5) == code:
            ws.update_cell(i, ci, str(value))
            return True
    return False

def aq_sync_item_names(pairs):
    """[V78] AQ_Items.품목명_AQ ← Products.제품명 일괄 동기화. pairs=[(품목코드, 정본명)].
    품목명_AQ는 Products 제품명의 **복사본**이라 정본이 바뀌면 어긋난다 — 2026-08-28 실측 33건
    (2026-07-21 NAS 동기화가 남긴 `퀸-유니온밸브` 등). 아쿠나리스 화면·스티커·가이드북·진열도면이
    모두 이 컬럼을 쓰므로, 맞춰 두지 않으면 옛 이름이 그대로 인쇄된다. 품목 정본 = Looperget_DB(Products).
    ※ 대상 셀만 batch_update — 전체 재기록(§2-2 clear+update)이 아니다. 반환: 반영 셀 수."""
    ws = _aq_sh().worksheet("AQ_Items")
    vals = ws.get_all_values()
    hdr = vals[0] if vals else []
    if "품목명_AQ" not in hdr:
        return 0
    ci, col, n = hdr.index("품목명_AQ"), "", hdr.index("품목명_AQ") + 1
    while n:                                   # 0기반 열 인덱스 → A1 열 문자
        n, rmd = divmod(n - 1, 26)
        col = chr(65 + rmd) + col
    rowof = {}
    for i, row in enumerate(vals[1:], start=2):
        c = str(row[0]).strip().zfill(5) if row and str(row[0]).strip() else ""
        if c and c not in rowof:
            rowof[c] = i
    reqs = [{"range": f"{col}{rowof[c]}", "values": [[nm]]}
            for c, nm in pairs if c in rowof and nm]
    if not reqs:
        return 0
    ws.batch_update(reqs, value_input_option="RAW")
    return len(reqs)

def _aq_grid_precheck(grid, ws_name):
    """[V68] clear() 前 사전 검증 — 구글시트 한도(셀 50,000자)를 넘는 셀이 있으면 시트를 건드리기 전에
    차단한다. 2026-07-24 실사고: clear 성공 후 update가 400으로 거부되어 AQ_Sites가 통째로 지워짐
    (리비전에서 복구). clear+update 패턴(§2-2)은 유지하되, 실패가 예정된 쓰기는 시작하지 않는다."""
    for ri, row in enumerate(grid):
        for ci, cell in enumerate(row):
            if len(str(cell)) > 50000:
                raise ValueError(
                    f"{ws_name} 저장 중단(시트 무손상): {ri + 1}행 {ci + 1}열 셀이 "
                    f"{len(str(cell)):,}자로 구글시트 한도(50,000자)를 초과합니다. 데이터를 줄인 뒤 다시 저장하세요.")

def aq_save_sites(sites_rows):
    """AQ_Sites 전체 재기록 (§2-2 clear+update 패턴). 헤더는 시트 현재 헤더 유지.
    [V68] clear 前 셀 크기 사전 검증 — 한도 초과 시 시트 무손상 중단."""
    ws = _aq_sh().worksheet("AQ_Sites")
    cur = ws.get_all_values()
    hdrs = cur[0] if cur and any(cur[0]) else \
        ["농협ID", "농협명", "지역", "상태", "설치일", "랙구성JSON", "배치JSON", "견적ID", "담당자", "비고"]
    grid = [hdrs] + [[str(s.get(h, "")) for h in hdrs] for s in sites_rows]
    _aq_grid_precheck(grid, "AQ_Sites")   # [V68] 검증 통과 후에만 clear
    ws.clear(); ws.update(grid, value_input_option='RAW')

# ── [V50] 등록된 상자·수용량 기록 수정 — 축적 데이터도 고칠 수 있어야 한다(박 대표님 2026-07-21) ──
def aq_save_ws(ws_name, rows):
    """[V50] AQ 시트 전체 재기록 (§2-2 clear+update). rows=list[dict] · 헤더는 시트 현재 헤더 유지.
    ※ 편집 저장 전용 — 축적 로그의 '행 추가'는 기존대로 aq_append_row 사용.
    [V68] clear 前 셀 크기 사전 검증 — 한도 초과 시 시트 무손상 중단."""
    ws = _aq_sh().worksheet(ws_name)
    cur = ws.get_all_values()
    hdrs = cur[0] if cur and any(cur[0]) else (list(rows[0].keys()) if rows else [])
    grid = [hdrs] + [[str(r.get(h, "")) for h in hdrs] for r in rows]
    _aq_grid_precheck(grid, ws_name)   # [V68] 검증 통과 후에만 clear
    ws.clear(); ws.update(grid, value_input_option='RAW')
    return len(rows)

def aq_rename_box(old, new):
    """[V50] 상자 이름 변경 — 참조하는 곳 전부에 연쇄 반영.
    AQ_Boxes(상자종류)·AQ_Items(기본상자)·AQ_ItemBox(상자종류)·AQ_Sites(배치JSON items.box).
    반환: {대상: 변경건수}"""
    sh = _aq_sh()
    cnt = {}
    for label, ws_name, col in (("상자 마스터", "AQ_Boxes", "상자종류"),
                                ("품목 기본상자", "AQ_Items", "기본상자"),
                                ("수용량 기록", "AQ_ItemBox", "상자종류")):
        try:
            ws = sh.worksheet(ws_name)
            vals = ws.get_all_values()
        except Exception:
            cnt[label] = 0; continue
        if not vals or col not in vals[0]:
            cnt[label] = 0; continue
        hdr = vals[0]; ci = hdr.index(col)
        grid, n = [hdr], 0
        for r in vals[1:]:
            row = (list(r) + [""] * len(hdr))[:len(hdr)]
            if row[ci].strip() == old:
                row[ci] = new; n += 1
            grid.append(row)
        if n:
            ws.clear(); ws.update(grid, value_input_option='RAW')
        cnt[label] = n
    n_site, sites = 0, aq_load_sites()
    for s in sites:
        try: plan = json.loads(str(s.get("배치JSON") or "{}"))
        except Exception: continue
        items = plan.get("items", {}) if isinstance(plan, dict) else {}
        hit = False
        if isinstance(items, dict):
            for v in items.values():
                if isinstance(v, dict) and str(v.get("box", "")).strip() == old:
                    v["box"] = new; hit = True; n_site += 1
        if hit:
            s["배치JSON"] = json.dumps(plan, ensure_ascii=False)
    if n_site: aq_save_sites(sites)
    cnt["사이트 배치"] = n_site
    return cnt

__all__ = [n for n in list(globals()) if not n.startswith("__")]   # star import 로 밑줄 이름까지 넘긴다

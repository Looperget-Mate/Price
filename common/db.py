# -*- coding: utf-8 -*-
"""[공용] Looperget_DB 시트 — 제품·세트·설정·견적 로드/저장 + 문서 핸들. app.py(V107) L91-98 · L489-641 · L820-828.
단가 정본 = Products 시트(두 앱 공통). 시트 저장은 clear()+update() 전체 덮어쓰기(V15 §2-2).
"""
import json
import datetime
import pandas as pd
import gspread
import streamlit as st
from common.google import *

# 비상용 기본 데이터 글로벌 선언 (NameError 방지)
DEFAULT_DATA = {
    "config": {"password": "1234"}, 
    "products": [], 
    "sets": {}, 
    "jp_quotes": [], 
    "kr_quotes": []
}

SHEET_NAME = "Looperget_DB"
COL_MAP = {
    "순번": "seq_no",
    "품목코드": "code", "카테고리": "category", "제품명": "name", "규격": "spec", "단위": "unit", 
    "1롤길이(m)": "len_per_unit", "매입단가": "price_buy", 
    "총판가1": "price_d1", "총판가2": "price_d2", 
    "대리점가1": "price_agy1", "대리점가2": "price_agy2", 
    "계통농협": "price_nh_sys", "지역농협": "price_nh_loc", 
    "소비자가": "price_cons", "단가(현장)": "price_site", 
    "이미지데이터": "image",
    "신정공급가": "price_supply_jp",
    "최근수정일": "last_updated",
    "가격정책": "price_policy",  # [V39] 고정=정책 고정가(재계산 불허, 직접입력만), 빈값=자동
    "세부카테고리": "subcategory"  # [V40] 가격결정용 세분류(쉼표 구분 다중 허용), 기존 '카테고리'와 별개
}
REV_COL_MAP = {v: k for k, v in COL_MAP.items()}

# ── [V11] 일본용 컬럼맵 및 카테고리 매핑 ──────────────────────────
COL_MAP_JP = {
    "순번": "seq_no",
    "품목코드": "code",
    "카테고리": "category",
    "일본용 제품명": "name",
    "규격": "spec",
    "단위": "unit",
    "1롤길이(m)": "len_per_unit",
    "매입가(별도가,원)": "price_buy_krw",
    "매입가(별도가,엔)": "price_buy",
    "대리점가(별도가,엔)": "price_d1",
    "소비자가(포함가,엔)": "price_cons",
    "이미지데이터": "image"
}
REV_COL_MAP_JP = {v: k for k, v in COL_MAP_JP.items()}

JP_CAT_MAP = {
    "주배관": "メイン配管", "주배관세트": "メイン配管",
    "가지관": "分岐配管",  "가지관세트": "分岐配管",
    "살수": "散水",      "살수세트": "散水セット",
    "부속": "付属",
    "기타": "その他資材",  "기타자재": "その他資材",
    "관급비용": "管給費用"
}

def init_db():
    if not gc: return None, None
    try: sh = gc.open(SHEET_NAME)
    except:
        try:
            sh = gc.create(SHEET_NAME)
            sh.add_worksheet(title="Products", rows=100, cols=20)
            sh.add_worksheet(title="Sets", rows=100, cols=10)
            sh.worksheet("Products").append_row(list(COL_MAP.keys()))
            sh.worksheet("Sets").append_row(["세트명", "카테고리", "하위분류", "이미지파일명", "레시피JSON"])
        except: return None, None
    try: ws_prod = sh.worksheet("Products")
    except: ws_prod = sh.add_worksheet(title="Products", rows=100, cols=20)
    try: ws_sets = sh.worksheet("Sets")
    except: ws_sets = sh.add_worksheet(title="Sets", rows=100, cols=10)
    try: ws_jp = sh.worksheet("Quotes_JP")
    except: 
        try: ws_jp = sh.add_worksheet(title="Quotes_JP", rows=100, cols=10); ws_jp.append_row(["견적명", "날짜", "항목JSON"])
        except: pass
    
    try: ws_kr = sh.worksheet("Quotes_KR")
    except:
        try: ws_kr = sh.add_worksheet(title="Quotes_KR", rows=100, cols=10); ws_kr.append_row(['날짜', '현장명', '담당자', '총액', '데이터JSON'])
        except: pass
        
    try: ws_config = sh.worksheet("Config")
    except:
        try: 
            ws_config = sh.add_worksheet(title="Config", rows=10, cols=2)
            ws_config.append_row(["항목", "비밀번호"])
            ws_config.append_row(["app_pwd", "1234"])
            ws_config.append_row(["admin_pwd", "1234"])
        except: pass
        
    return ws_prod, ws_sets

def load_data_from_sheet():
    ws_prod, ws_sets = init_db()
    if not ws_prod: return DEFAULT_DATA
    data = {"config": {"app_pwd": "1234", "admin_pwd": "1234"}, "products": [], "sets": {}, "jp_quotes": [], "kr_quotes": []}
    
    try:
        sh = gc.open(SHEET_NAME)
        ws_config = sh.worksheet("Config")
        for rec in ws_config.get_all_records():
            if rec.get("항목") == "app_pwd": data["config"]["app_pwd"] = str(rec.get("비밀번호"))
            if rec.get("항목") == "admin_pwd": data["config"]["admin_pwd"] = str(rec.get("비밀번호"))
    except: pass
    
    try:
        prod_records = ws_prod.get_all_records()
        for rec in prod_records:
            new_rec = {}
            for k, v in rec.items():
                if k in COL_MAP:
                    if k == "품목코드": new_rec[COL_MAP[k]] = str(v).zfill(5)
                    else: new_rec[COL_MAP[k]] = v
            if "seq_no" not in new_rec: new_rec["seq_no"] = ""
            data["products"].append(new_rec)
    except: pass
    try:
        set_records = ws_sets.get_all_records()
        for rec in set_records:
            if not rec.get("세트명"): continue
            cat = rec.get("카테고리", "기타"); name = rec.get("세트명")
            if cat not in data["sets"]: data["sets"][cat] = {}
            try: rcp = json.loads(str(rec.get("레시피JSON", "{}")))
            except: rcp = {}
            data["sets"][cat][name] = {"recipe": rcp, "image": rec.get("이미지파일명"), "sub_cat": rec.get("하위분류"), "desc": rec.get("설명", ""), "canvas": rec.get("캔버스파일", "")}
            # [V21, 2026-06-25] Track A-2 Phase 1A — Sets 시트 13컬럼 확장. 시트에 없으면 빈값(후방호환).
            # [V24, 2026-06-29] 메타값 문자열 정규화 — gspread가 숫자 셀(관경 50 등)을 int로 반환 → 빌더 _mget .strip() 크래시 방지.
            def _ms(v): return str(v).strip() if v not in (None, "") else ""
            _ic = _ms(rec.get("자사품목코드", ""))
            data["sets"][cat][name].update({
                "gauge": _ms(rec.get("관경", "")), "install_phase": _ms(rec.get("설치단계", "")), "func_type": _ms(rec.get("기능타입", "")),
                "head_model": _ms(rec.get("헤드모델", "")), "flow_lh": _ms(rec.get("유량(L/h)", "")), "pressure_bar": _ms(rec.get("권장수압(bar)", "")),
                "spray_radius_m": _ms(rec.get("최대살수반경(m)", "")), "install_env": _ms(rec.get("설치환경", "")), "set_grade": _ms(rec.get("세트등급", "")),
                "compat_sets": _ms(rec.get("호환필수세트", "")), "price_consumer": _ms(rec.get("소비자가", "")),
                "item_code": (_ic.zfill(5) if _ic else ""),  # 묶음코드 01998 등 선행0 복원
                "gov_registered": _ms(rec.get("관급등록여부", "")) or "N",
                # [V22, 2026-06-26] Track A-2 D안 — 조달용 부속 추가 BOM. 프로그램은 무시, 관급모드만 (레시피JSON ∪ 조달용추가BOM) 사용.
                "gov_extra_bom": _ms(rec.get("조달용추가BOM", "")),
            })
    except: pass
    try:
        sh = gc.open(SHEET_NAME)
        ws_jp = sh.worksheet("Quotes_JP")
        data["jp_quotes"] = ws_jp.get_all_records()
    except: pass
    try:
        sh = gc.open(SHEET_NAME)
        ws_kr = sh.worksheet("Quotes_KR")
        data["kr_quotes"] = ws_kr.get_all_records()
    except: pass
    
    return data

def save_products_to_sheet(products_list):
    ws_prod, _ = init_db()
    if not ws_prod: return
    df = pd.DataFrame(products_list)
    if "code" in df.columns: df["code"] = df["code"].astype(str).apply(lambda x: x.zfill(5))
    if "seq_no" not in df.columns:
        df["seq_no"] = [f"{i+1:03d}" for i in range(len(df))]
    
    df_up = df.rename(columns=REV_COL_MAP).fillna("")
    cols_order = [c for c in COL_MAP.keys() if c in df_up.columns]
    df_up = df_up[cols_order]
    
    ws_prod.clear(); ws_prod.update([df_up.columns.values.tolist()] + df_up.values.tolist())


# ── 문서 핸들(ID 직접 열기) — 아쿠나리스 시트(AQ_*)와 Users 가 쓴다 ──
AQ_SHEET_ID = "1oKtEJ47qOyrNS1JrIQT5dIuXs8MiiXkDeDsRNQdymFM"   # Looperget_DB (tools/gs.py와 동일 문서)

@st.cache_resource(ttl=600, show_spinner=False)
def _aq_sh():
    """아쿠나리스용 스프레드시트 핸들(캐시). ID 직접 열기 — 이름검색(Drive API) 생략."""
    try:
        return gc.open_by_key(AQ_SHEET_ID)
    except Exception:
        return gc.open(SHEET_NAME)

__all__ = [n for n in list(globals()) if not n.startswith("__")]   # star import 로 밑줄 이름까지 넘긴다

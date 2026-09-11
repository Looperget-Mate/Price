import os
import streamlit as st
try:
    from streamlit_js_eval import streamlit_js_eval
    _HAS_JS_EVAL = True
except Exception:
    _HAS_JS_EVAL = False
import pandas as pd
import math
import io
import base64
import tempfile
import json
import datetime
import time
import xlsxwriter 
from PIL import Image
from fpdf import FPDF

# [V108 · 2026-09-11] 브랜드 UI·구글 연동·DB·로그인 → common/ (🏪 아쿠나리스 빌더와 공용).
#   🏪 아쿠나리스 모드는 별도 앱 aqunaris_app.py 로 분리 — 이 파일은 루퍼젯 프로매니저(견적·설계·제안서)만 담는다.

# 구글 연동 라이브러리
import gspread
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload

# ==========================================
# [중요] 0. 페이지 설정을 최상단으로 유지
# ==========================================
from common.ui import *   # 브랜드 CSS·헤더·푸터·앱 전환 단추 (LOGO_YELLOW_B64 포함)
apply_page("Looperget 프로 매니저", "🟡")

# ==========================================
# 1. 설정 및 구글 연동 → common/google.py · 시트 DB → common/db.py · 로그인·권한 → common/auth.py [V108]
# ==========================================
from common.google import *
from common.db import *
from common.auth import *
try:
    import common as _cm
    _CM_VER = int(getattr(_cm, "COMMON_VER", 0) or 0)
except Exception:
    _CM_VER = 0
if _CM_VER < 1:
    st.error("🚨 **`common/` 폴더가 없거나 구버전입니다** — app.py(V108)와 짝이 맞지 않습니다.\n\n"
             "GitHub `Looperget-Mate/Price`에 **`common/` 폴더를 통째로** 올린 뒤 재배포하세요.")
    st.stop()


# ── [V11] 핵심 엔진 함수 ─────────────────────────────────────────

KR_PRICE_FIELDS = [
    "price_buy", "price_d1", "price_d2",
    "price_agy1", "price_agy2",
    "price_nh_sys", "price_nh_loc",
    "price_cons", "price_site", "price_supply_jp"
]
KR_PRICE_LABELS = {
    "price_buy": "매입단가", "price_d1": "총판가1", "price_d2": "총판가2",
    "price_agy1": "대리점가1", "price_agy2": "대리점가2",
    "price_nh_sys": "계통농협", "price_nh_loc": "지역농협",
    "price_cons": "소비자가", "price_site": "단가(현장)",
    "price_supply_jp": "신정공급가"
}

def smart_roundup(value: float, apply_vat_fit: bool = True) -> float:
    """
    가격 규모별 올림 단위 + 부가세 역산(÷1.1) 정수 조건:
      ~999원    → 0.1원 단위, ÷1.1이 소수점 없이 떨어지는 최소값으로 올림
      1000~9999 → 10원 단위, ÷1.1 조건 적용 (11의 배수)
      10000~    → 100원 단위, ÷1.1 조건 적용 (11의 배수 × 10)
    apply_vat_fit=False 이면 단순 올림만 수행 (신정공급가 등에 사용)
    """
    v = float(value)

    if v < 1000:
        # 0.1원 단위 올림 후, v/1.1이 소수점 1자리 이하로 떨어지는 최솟값 탐색
        # 조건: v * 10이 11의 배수 → v = 11k/10 (k는 양의 정수)
        base = math.ceil(v * 10) / 10  # 0.1원 올림
        if not apply_vat_fit:
            return round(base, 1)
        # v * 10 이 11의 배수가 되는 최소 k 탐색
        k = math.ceil(v * 10 / 11)  # v*10 >= 11k → k = ceil(v*10/11)
        result = round(k * 11 / 10, 1)
        return result

    elif v < 10000:
        # 10원 단위 올림 후 11의 배수
        if not apply_vat_fit:
            return int(math.ceil(v / 10) * 10)
        k = math.ceil(v / 11)
        result = k * 11
        # 10원 단위가 아니면 다음 11의 배수로
        while result % 10 != 0:
            k += 1
            result = k * 11
        return result

    else:
        # 100원 단위 올림 후 110의 배수 (11의 배수이면서 100원 단위)
        if not apply_vat_fit:
            return int(math.ceil(v / 100) * 100)
        k = math.ceil(v / 110)
        return k * 110

def recalc_prices_from_buy(old_prod: dict, new_buy: int) -> dict:
    """매입단가 변동 시 기존 비율 유지하며 전체 단가 재계산."""
    old_buy = float(old_prod.get("price_buy", 0) or 0)
    if old_buy == 0:
        result = {f: int(old_prod.get(f, 0) or 0) for f in KR_PRICE_FIELDS}
        result["price_buy"] = new_buy
        return result
    ratio = float(new_buy) / old_buy
    result = {}
    for f in KR_PRICE_FIELDS:
        old_val = float(old_prod.get(f, 0) or 0)
        if f == "price_buy":
            result[f] = new_buy
        elif old_val == 0:
            result[f] = 0
        elif f == "price_supply_jp":
            # 신정공급가는 부가세 역산 조건 제외, 단순 올림만
            result[f] = smart_roundup(old_val * ratio, apply_vat_fit=False)
        else:
            result[f] = smart_roundup(old_val * ratio, apply_vat_fit=True)
    return result

# ── [V39] 매입단가 변동 시뮬레이터 엔진 (박 대표님 승인 규칙, 2026-07-11) ──
def snap_band_price(v) -> int:
    """가격대별 단위 스냅(반올림). ~1천=10원 / 1천~1만=100원 / 1만~10만=100원 / 10만~=1,000원."""
    try: v = float(v)
    except (TypeError, ValueError): return 0
    if v <= 0: return 0
    unit = 10 if v < 1000 else (100 if v < 100000 else 1000)
    return int(round(v / unit) * unit)

def margin_pct(sell, buy):
    """이익율% = (판매-매입)/판매. 기존 이익분석과 동일 기준(VAT포함가 대 VAT포함가)."""
    try:
        sell = float(sell or 0); buy = float(buy or 0)
        if sell <= 0: return None
        return (sell - buy) / sell * 100.0
    except (TypeError, ValueError): return None

def price_segment(prod) -> str:
    """추천 이익율 산출용 세그먼트: [V40] 세부카테고리 우선(첫 태그), 없으면 구 로직(매입가 밴드)."""
    sub = str(prod.get("subcategory", "")).split(",")[0].strip()
    if sub: return sub
    cat = str(prod.get("category", "")).strip() or "기타"
    if cat != "부속": return cat
    try: buy = float(prod.get("price_buy", 0) or 0)
    except (TypeError, ValueError): buy = 0
    if buy < 3000: return "부속·소형"
    if buy < 20000: return "부속·중형"
    if buy < 100000: return "부속·대형"
    return "부속·고가(펌프류)"

def recommend_tier_margins(products: list) -> dict:
    """세그먼트×단가필드별 권장 이익율%(중앙값) — 데이터가 쌓일수록 추천이 진화."""
    import statistics
    pool = {}
    for p in products:
        try: buy = float(p.get("price_buy", 0) or 0)
        except (TypeError, ValueError): buy = 0
        if buy <= 0: continue
        seg = price_segment(p)
        for f in KR_PRICE_FIELDS:
            if f == "price_buy": continue
            m = margin_pct(p.get(f), buy)
            if m is not None and -50 < m < 99:
                pool.setdefault(seg, {}).setdefault(f, []).append(m)
    return {seg: {f: statistics.median(v) for f, v in fields.items() if v}
            for seg, fields in pool.items()}

def load_price_policy():
    """[V40] PricePolicy 시트 → {세부카테고리: {티어라벨: 목표이익%}}. 실패/부재 시 빈 dict."""
    try:
        sh = gc.open(SHEET_NAME)
        out = {}
        for r in sh.worksheet("PricePolicy").get_all_records():
            sub = str(r.get("세부카테고리", "")).strip()
            if not sub: continue
            d = {}
            for k, v in r.items():
                if k == "세부카테고리": continue
                s = str(v).strip()
                if s:
                    try: d[k] = float(s)
                    except ValueError: pass
            out[sub] = d
        return out
    except Exception:
        return {}

def save_price_policy(policy_rows: list):
    """[V40] 지침 편집 저장: [{세부카테고리, 티어라벨:%...}] → PricePolicy 시트 재기록."""
    sh = gc.open(SHEET_NAME)
    try: ws = sh.worksheet("PricePolicy")
    except Exception: ws = sh.add_worksheet(title="PricePolicy", rows=40, cols=12)
    tiers = [lb for fk, lb in KR_PRICE_LABELS.items() if fk != "price_buy"]
    grid = [["세부카테고리"] + tiers]
    for r in policy_rows:
        grid.append([r.get("세부카테고리", "")] + [r.get(t, "") if r.get(t) is not None else "" for t in tiers])
    ws.clear(); ws.update(grid)

def recalc_keep_margin(prod: dict, new_buy: int) -> dict:
    """기존 이익율 유지 재계산 + 단위 스냅. 이익율 산출 불가(기존가 0 등)면 0 유지."""
    old_buy = float(prod.get("price_buy", 0) or 0)
    out = {"price_buy": int(new_buy)}
    for f in KR_PRICE_FIELDS:
        if f == "price_buy": continue
        old_v = float(prod.get(f, 0) or 0)
        if old_v <= 0: out[f] = 0; continue
        m = margin_pct(old_v, old_buy)
        if m is None or m >= 100: out[f] = int(old_v); continue
        raw = new_buy / (1 - m / 100.0) if m < 100 else old_v
        out[f] = snap_band_price(raw)
    return out
# ══ [V108] 프로매니저 전용 모듈 짝 검증 — looperget/ 폴더가 없거나 구버전이면 크래시 대신 한국어로 안내하고 정지 ══
#  🏪 아쿠나리스(시트 함수·배치 엔진·인쇄물)는 aqunaris_app.py · aqunaris/ 로 분리(2026-09-11).
try:
    import looperget as _lg
    _LG_VER = int(getattr(_lg, "PKG_VER", 0) or 0)
except Exception:
    _LG_VER = 0
if _LG_VER < 100:
    st.error("🚨 **`looperget/` 폴더가 없거나 구버전입니다** — app.py(V108)와 짝이 맞지 않습니다.\n\n"
             "GitHub `Looperget-Mate/Price`에 **`looperget/`·`common/` 폴더를 통째로** "
             "`app.py`와 함께 올린 뒤 재배포하세요.")
    st.stop()

def sync_products_jp_to_sheet(kr_products: list, exchange_rate: float):
    """한국 Products → Products_JP 자동 동기화. 기존 JP 단가 비율 유지."""
    if not gc:
        return False, "구글 서비스 미연결"
    try:
        sh = gc.open(SHEET_NAME)
        try:
            ws_prod_jp = sh.worksheet("Products_JP")
            jp_records = ws_prod_jp.get_all_records()
        except:
            ws_prod_jp = sh.add_worksheet(title="Products_JP", rows=300, cols=12)
            jp_records = []

        jp_dict = {str(r.get("품목코드", "")).zfill(5): r for r in jp_records if r.get("품목코드")}
        rows = [list(COL_MAP_JP.keys())]
        synced = 0
        for i, p in enumerate(kr_products):
            code = str(p.get("code", "")).strip().zfill(5)
            if not code or code == "00000":
                continue
            kr_supply = float(p.get("price_supply_jp", 0) or 0)
            buy_krw = int(round(kr_supply / 1.1)) if kr_supply else 0
            buy_jpy = int(round(buy_krw / exchange_rate)) if (exchange_rate and buy_krw) else 0

            jp_row = jp_dict.get(code, {})
            old_buy_jpy = float(jp_row.get("매입가(별도가,엔)", 0) or 0)
            old_d1      = float(jp_row.get("대리점가(별도가,엔)", 0) or 0)
            old_cons    = float(jp_row.get("소비자가(포함가,엔)", 0) or 0)

            if old_buy_jpy > 0 and buy_jpy > 0:
                jp_ratio = buy_jpy / old_buy_jpy
                new_d1   = smart_roundup(old_d1   * jp_ratio) if old_d1   > 0 else smart_roundup(buy_jpy * 1.3)
                new_cons = smart_roundup(old_cons  * jp_ratio) if old_cons > 0 else smart_roundup(buy_jpy * 1.65)
            else:
                new_d1   = smart_roundup(buy_jpy * 1.3)
                new_cons = smart_roundup(buy_jpy * 1.65)

            cat_jp = JP_CAT_MAP.get(p.get("category", ""), p.get("category", ""))
            rows.append([
                f"{i+1:03d}", code, cat_jp,
                jp_row.get("일본용 제품명", p.get("name", "")),
                p.get("spec", ""), p.get("unit", "EA"), p.get("len_per_unit", ""),
                buy_krw, buy_jpy, new_d1, new_cons, p.get("image", "")
            ])
            synced += 1

        ws_prod_jp.clear()
        ws_prod_jp.update(rows)
        return True, f"Products_JP 동기화 완료 ({synced}개 품목, 환율 {exchange_rate})"
    except Exception as e:
        return False, str(e)

def load_jp_merged_products(kr_products: list, exchange_rate: float) -> list:
    """KR Products + Products_JP 병합 → JP 모드 제품 리스트 반환."""
    if not gc:
        return []
    try:
        sh = gc.open(SHEET_NAME)
        ws_prod_jp = sh.worksheet("Products_JP")
        jp_records = ws_prod_jp.get_all_records()
    except:
        jp_records = []
    jp_dict = {str(r.get("품목코드", "")).zfill(5): r for r in jp_records if r.get("품목코드")}
    merged = []
    for p in kr_products:
        code = str(p.get("code", "")).strip().zfill(5)
        if not code or code == "00000":
            continue
        jp_row = jp_dict.get(code, {})
        kr_supply = float(p.get("price_supply_jp", 0) or 0)
        buy_krw = int(round(kr_supply / 1.1)) if kr_supply else 0
        buy_jpy = int(round(buy_krw / exchange_rate)) if (exchange_rate and buy_krw) else 0
        existing_d1   = int(jp_row.get("대리점가(별도가,엔)", 0) or 0)
        existing_cons = int(jp_row.get("소비자가(포함가,엔)", 0) or 0)
        merged.append({
            "seq_no": p.get("seq_no", ""),
            "code": code,
            "category": JP_CAT_MAP.get(p.get("category", ""), p.get("category", "")),
            "name": jp_row.get("일본용 제품명", p.get("name", "")),
            "spec": p.get("spec", ""),
            "unit": p.get("unit", "EA"),
            "len_per_unit": p.get("len_per_unit", ""),
            "price_buy_krw": buy_krw,
            "price_buy": buy_jpy,
            "price_d1":   existing_d1   if existing_d1   > 0 else smart_roundup(buy_jpy * 1.3),
            "price_cons": existing_cons if existing_cons > 0 else smart_roundup(buy_jpy * 1.65),
            "image": p.get("image", "")
        })
    return merged

# ─────────────────────────────────────────────────────────────────

# 구글 API 호출 최소화를 위해 init_db() 호출 없이 바로 업데이트 수행
def save_sets_to_sheet(sets_dict):
    if not gc: return
    # [V21, 2026-06-25] Track A-2 Phase 1A — 헤더·데이터 20컬럼 확장 (기존7 + 신규13). V15 §2-2 clear()+update() 패턴 유지.
    # [V22, 2026-06-26] Track A-2 D안 — 21번째 컬럼 "조달용추가BOM" 추가. 프로그램은 무시, 관급모드는 합산.
    rows = [["세트명", "카테고리", "하위분류", "이미지파일명", "레시피JSON", "설명", "캔버스파일",
             "관경", "설치단계", "기능타입", "헤드모델", "유량(L/h)", "권장수압(bar)",
             "최대살수반경(m)", "설치환경", "세트등급", "호환필수세트", "소비자가",
             "자사품목코드", "관급등록여부", "조달용추가BOM"]]
    for cat, items in sets_dict.items():
        for name, info in items.items():
            rows.append([name, cat, info.get("sub_cat", ""), info.get("image", ""), json.dumps(info.get("recipe", {}), ensure_ascii=False), info.get("desc", ""), info.get("canvas", ""),
                         info.get("gauge", ""), info.get("install_phase", ""), info.get("func_type", ""), info.get("head_model", ""), info.get("flow_lh", ""), info.get("pressure_bar", ""),
                         info.get("spray_radius_m", ""), info.get("install_env", ""), info.get("set_grade", ""), info.get("compat_sets", ""), info.get("price_consumer", ""),
                         info.get("item_code", ""), info.get("gov_registered", "N"), info.get("gov_extra_bom", "")])
    def _do(client):
        sh = client.open(SHEET_NAME)
        ws_sets = sh.worksheet("Sets")
        ws_sets.clear()
        ws_sets.update(rows)
    try:
        _do(gc)
    except Exception as e:
        # [V32/V33] 소켓 끊김이면 재인증 후 새 클라이언트로 1회 재시도 (시트 저장도 업로드처럼 유휴 끊김에 취약)
        if any(k in str(e) for k in _SOCKET_ERRS):
            try:
                get_google_services.clear()
                gc2 = get_google_services()[0]
                if gc2:
                    _do(gc2)
                    return
            except Exception as e2:
                st.error(f"세트 저장 오류(재연결 후에도): {e2}")
                return
        st.error(f"세트 저장 오류: {e}")

# [V23, 2026-06-28] Track A-2 Phase 1B — 세트명/분류 기반 메타데이터 자동 추론 (빌더 저장 폼 기본값)
META_FUNC_TYPES = ["", "Filter", "Mix", "Branch", "Branch-Base", "Joint", "Pump", "Spray", "End-Cap", "Punch", "Gauge", "Drip"]
META_PHASES = ["", "수원부", "주배관", "가지관분기", "가지관연결", "살수", "마감", "특수"]
META_HEADS = ["(없음)", "Rivulis 427B", "Netafim 메가넷 200L"]
META_ENVS = ["노지", "하우스", "벽부", "지붕", "조경", "관급", "산업분진"]
META_GRADES = ["S", "M", "C", "D"]
# 헤드모델 → (유량 L/h, 권장수압 bar, 최대살수반경 m). 메가넷은 박 대표님 기준 6m.
META_HEAD_PERF = {"Rivulis 427B": ("850", "2-4", "12"), "Netafim 메가넷 200L": ("200", "2-3", "6")}

def infer_set_meta(name, cat="", sub_cat=""):
    """세트명·분류에서 메타데이터 기본값 추론 (룰 v1.3 반영). 빈 문자열이면 미상."""
    import re
    n = name or ""
    sc = sub_cat or ""
    # 관경
    if sc in ("50mm", "40mm", "25mm"): gauge = sc.replace("mm", "")
    elif "505050" in n or "5050" in n: gauge = "50"
    elif "404040" in n or "4040" in n: gauge = "40"
    elif "H20" in n or "P20" in n: gauge = "20"
    elif "H25" in n or "P25" in n or n.endswith("-25"): gauge = "25"
    elif "-50" in n: gauge = "50"
    elif "-40" in n: gauge = "40"
    else: gauge = ""
    # 기능타입
    if "Filter" in n or "Nomal-" in n: func = "Filter"
    elif "Pump" in n: func = "Pump"
    elif "Mix-" in n: func = "Mix"
    elif "[LSS]" in n: func = "Spray"
    elif "Cap-" in n: func = "Branch-Base"
    elif "P-H20NP" in n or "P-P20NP" in n: func = "Gauge"
    elif re.search(r'\bE-[0-9]', n): func = "End-Cap"
    elif re.search(r'\bB-', n): func = "Branch"
    elif re.search(r'\bT-[0-9]', n): func = "Branch"
    elif re.search(r'\bL-[0-9]', n): func = "Joint"
    elif re.search(r'\b1-[0-9]', n): func = "Joint"
    else: func = ""
    # 설치단계
    if cat == "살수세트" or "[LSS]" in n: phase = "살수"
    elif "Filter" in n or "Nomal-" in n or "Pump" in n: phase = "수원부"
    elif re.search(r'\bE-[0-9]', n): phase = "마감"
    elif cat == "가지관세트": phase = "가지관분기" if re.search(r'\bB-', n) else "가지관연결"
    elif "Cap-" in n or "P-H" in n or "P-P" in n: phase = "특수"
    else: phase = "주배관"
    # 헤드모델
    if "427b" in n or "427B" in n: head = "Rivulis 427B"
    elif "Mega" in n: head = "Netafim 메가넷 200L"
    else: head = "(없음)"
    env = "벽부" if "Wall" in n else "노지"
    return {"gauge": gauge, "func_type": func, "install_phase": phase, "head_model": head, "install_env": env}

def format_prod_label(option):
    if isinstance(option, dict): return f"[{option.get('code','00000')}] {option.get('name','')} ({option.get('spec','-')})"
    return str(option)

def save_quote_to_sheet(timestamp, q_name, manager, total, json_data):
    if not gc: return False
    try:
        sh = gc.open(SHEET_NAME)
        ws_kr = sh.worksheet("Quotes_KR")
        ws_kr.append_row([str(timestamp), str(q_name), str(manager), int(total), json_data])
        return True
    except Exception as e:
        return False

# ==========================================
# 2-PRE. 세트 이미지 빌더 (Fabric.js / V12)
# ==========================================
def build_set_image_editor(db_sets, db_products, drive_file_map):
    """
    Fabric.js 기반 세트 이미지 빌더.
    - 검색/이미지로드/수량입력: Streamlit 네이티브 (iframe 왼쪽 칼럼)
    - 캔버스 조립/저장: Fabric.js HTML (iframe)
    """
    import streamlit.components.v1 as components

    if "_img_cache" not in st.session_state:
        st.session_state._img_cache = {}
    if "builder_recipe" not in st.session_state:
        st.session_state.builder_recipe = {}          # {code: {name,spec,qty}} — 레시피 집계
    if "builder_canvas_items" not in st.session_state:
        # [V16] 캔버스에 올라간 부속 전체 누적 (rerun에도 유지).
        #  b64는 저장 안 함(용량) → 매 렌더에 캐시/드라이브에서 채움.
        st.session_state.builder_canvas_items = []    # [{code,name,spec,qty,img_id}]

    # ── 전체 품목 메타 (코드/이름/규격) ─────────────────────────────────
    all_meta = []
    for p in db_products:
        code = str(p.get("code", "")).strip().zfill(5)
        name = p.get("name", "") or ""
        spec = p.get("spec", "") or ""
        cat  = p.get("category", "") or ""
        img_id = drive_file_map.get(code) or (
            p.get("image") if len(str(p.get("image", "") or "")) > 10 else None
        )
        all_meta.append({"code": code, "name": name, "spec": spec,
                         "cat": cat, "img_id": img_id or ""})

    # ── 레이아웃: 왼쪽(검색) | 오른쪽(캔버스) ───────────────────────────
    col_search, col_canvas = st.columns([1, 3])

    with col_search:
        st.markdown("#### 🔍 부속 검색")
        q = st.text_input("이름 / 규격 / 코드", placeholder="예: 카플러, 25mm, 01733",
                          key="builder_q")

        matched = []
        if q and q.strip():
            ql = q.strip().lower()
            matched = [m for m in all_meta
                       if ql in m["name"].lower()
                       or ql in m["spec"].lower()
                       or ql in m["code"]
                       or ql in m["cat"].lower()][:16]

        if matched:
            st.caption(f"{len(matched)}개 검색됨")
            for m in matched:
                code = m["code"]
                # 캐시 우선, 없으면 드라이브 로드
                if code not in st.session_state._img_cache and m["img_id"]:
                    st.session_state._img_cache[code] = get_image_from_drive(m["img_id"])
                b64 = st.session_state._img_cache.get(code)

                with st.container(border=True):
                    if b64:
                        st.image(b64, use_container_width=True)
                    else:
                        st.markdown(
                            '<div style="height:60px;background:#1a1a2e;border-radius:4px;'
                            'display:flex;align-items:center;justify-content:center;'
                            'color:#555;font-size:10px;">이미지 없음</div>',
                            unsafe_allow_html=True)
                    st.caption(f"[{code}] {m['name']} / {m['spec'] or '-'}")

                    c1, c2 = st.columns([2, 1])
                    with c1:
                        qty = st.number_input("수량", min_value=1, value=1, step=1,
                                              key=f"bq_{code}")
                    with c2:
                        st.write("")
                        if st.button("➕ 추가", key=f"badd_{code}", use_container_width=True):
                            # 레시피 집계
                            if code in st.session_state.builder_recipe:
                                st.session_state.builder_recipe[code]["qty"] += qty
                            else:
                                st.session_state.builder_recipe[code] = {
                                    "name": m["name"], "spec": m["spec"], "qty": qty
                                }
                            # [V16] 캔버스 누적 아이템에 등록 (rerun에도 유지)
                            # [V33] uid = 항목 삭제에도 흔들리지 않는 고유키 (부속 위치보존 _pendKey의 기반)
                            st.session_state["builder_uid_seq"] = st.session_state.get("builder_uid_seq", 0) + 1
                            st.session_state.builder_canvas_items.append({
                                "uid": st.session_state["builder_uid_seq"],
                                "code": code, "name": m["name"],
                                "spec": m["spec"] or "-",
                                "qty": qty,
                                "img_id": m["img_id"] or ""
                            })
                            st.success(f"'{m['name']}' {qty}개 추가됨")
                            st.rerun()
        elif q and q.strip():
            st.caption("검색 결과 없음")
        else:
            st.caption("품목명, 규격, 코드로 검색하세요.")

        # ── 현재 레시피 집계 표시 ─────────────────────────────────────
        if st.session_state.builder_recipe:
            st.markdown("---")
            st.markdown("**📋 구성 집계**")
            for c, info in st.session_state.builder_recipe.items():
                st.markdown(f"- [{c}] {info['name']} × **{info['qty']}**")

            # [V33] 부속 빼기 — 캔버스 항목별 −1/전체빼기 (구성·캔버스 동시 반영).
            #  3개 넣고 1개만 빼기 = 해당 줄의 [−1]. 남은 부속 배치는 uid 키로 보존됨.
            # [V34] 👁 이미지 숨김 토글 — 구성(레시피)엔 남기고 캔버스·저장 PNG에서만 제외.
            #  용도: 재단 배관을 구성에 넣되, 그림은 '배관 그리기'로 대체할 때.
            if st.session_state.builder_canvas_items:
                with st.expander("🧺 캔버스 부속 관리 (빼기·이미지 숨김)", expanded=False):
                    st.caption("👁=이미지 숨김/표시(구성엔 유지) · −1=하나 빼기 · ✕=전체 빼기")
                    def _remove_canvas_qty(idx, n):
                        it = st.session_state.builder_canvas_items[idx]
                        n = min(n, it["qty"])
                        it["qty"] -= n
                        _rc = st.session_state.builder_recipe.get(it["code"])
                        if _rc:
                            _rc["qty"] -= n
                            if _rc["qty"] <= 0:
                                st.session_state.builder_recipe.pop(it["code"], None)
                        if it["qty"] <= 0:
                            st.session_state.builder_canvas_items.pop(idx)
                    for _i, _it in enumerate(st.session_state.builder_canvas_items):
                        _hid = bool(_it.get("hidden"))
                        _rc1, _rc0, _rc2, _rc3 = st.columns([2.6, 1, 1, 1])
                        with _rc1:
                            _lbl = f"[{_it['code']}] {_it['name']} ×{_it['qty']}"
                            st.caption(("🚫 " + _lbl) if _hid else _lbl)
                        with _rc0:
                            if st.button("👁" if _hid else "🙈", key=f"bhide_{_it.get('uid', _i)}", use_container_width=True,
                                         help=("이미지 다시 표시" if _hid else "이미지 숨김 (구성엔 유지 — 배관그리기 대체용)")):
                                _it["hidden"] = not _hid
                                st.rerun()
                        with _rc2:
                            if st.button("−1", key=f"bdel1_{_it.get('uid', _i)}", use_container_width=True):
                                _remove_canvas_qty(_i, 1)
                                st.rerun()
                        with _rc3:
                            if st.button("✕", key=f"bdelall_{_it.get('uid', _i)}", use_container_width=True,
                                         help="이 항목 전체 빼기"):
                                _remove_canvas_qty(_i, _it["qty"])
                                st.rerun()

            if st.button("🗑 집계 초기화", key="builder_clear_recipe"):
                st.session_state.builder_recipe = {}
                st.session_state.builder_canvas_items = []
                st.rerun()

        # ── [V19] 이미지 없는 항목(관급/포장/검수 등)을 '구성에만' 직접 추가 ──
        with st.expander("➕ 구성에만 추가 (관급/포장/검수 등 이미지 없는 항목)", expanded=False):
            st.caption("캔버스에 올리지 않고 세트 구성(레시피)에만 넣습니다. 관급자재·포장비·검수비처럼 그림이 필요 없는 비용/자재 항목용.")
            _extra_opts = [f"[{m['code']}] {m['name']} / {m['spec'] or '-'}" for m in all_meta]
            if _extra_opts:
                _esel = st.selectbox("항목 선택 (코드/이름으로 검색)", _extra_opts, key="builder_extra_sel")
                _eqty = st.number_input("수량", min_value=1, value=1, step=1, key="builder_extra_qty")
                if st.button("구성에만 추가", key="builder_extra_add", use_container_width=True):
                    _m = all_meta[_extra_opts.index(_esel)]
                    _ec = _m["code"]
                    if _ec in st.session_state.builder_recipe:
                        st.session_state.builder_recipe[_ec]["qty"] += int(_eqty)
                    else:
                        st.session_state.builder_recipe[_ec] = {"name": _m["name"], "spec": _m["spec"], "qty": int(_eqty)}
                    st.success(f"구성에 '{_m['name']}' {int(_eqty)}개 추가 (캔버스 미표시)")
                    st.rerun()
            else:
                st.caption("제품 DB가 비어 있습니다.")

    # ── [V16] 캔버스 누적 아이템 전체를 JS에 전달 (rerun에도 유지) ──────
    # b64는 세션에 저장하지 않으므로, 매 렌더에 캐시 우선·없으면 드라이브에서 채움.
    _canvas_payload = []
    for it in st.session_state.builder_canvas_items:
        code = it.get("code", "")
        b64 = st.session_state._img_cache.get(code)
        if b64 is None and it.get("img_id"):
            b64 = get_image_from_drive(it["img_id"])
            if b64:
                st.session_state._img_cache[code] = b64
        _canvas_payload.append({
            "uid": it.get("uid", 0),   # [V33] 삭제에도 안정적인 위치보존 키
            "hidden": bool(it.get("hidden")),   # [V34] 이미지 숨김(구성 유지, PNG 제외)
            "code": code, "name": it.get("name", ""),
            "spec": it.get("spec", "-"), "qty": it.get("qty", 1),
            "b64": b64 or ""
        })
    # [V37] 세션 토큰 — 부속 위치 저장소(LOOPER_WORK_PARTS)를 이 세션의 부속 목록과만 결부
    #        (이전 세션 잔재·다른 탭의 uid 충돌 무시). 보간 필드는 5개 유지, payload 내부만 확장.
    if "builder_ws_token" not in st.session_state:
        st.session_state.builder_ws_token = str(int(time.time() * 1000))
    pending_json = json.dumps({"token": st.session_state.builder_ws_token, "items": _canvas_payload}, ensure_ascii=False)

    with col_canvas:
        # ── 모드 선택 ──────────────────────────────────────────────────
        # [V31] 기본값=새 세트 만들기. [V38] index+key 동시지정 제거 — 위젯 리셋 시 화면·상태
        #  어긋남(라디오는 편집인데 로직은 새세트) 원인 후보 차단. 세션상태 초기화 방식이 정석.
        if "builder_mode" not in st.session_state:
            st.session_state.builder_mode = "✨ 새 세트 만들기"
        builder_mode = st.radio("빌더 작업 모드",
                                ["🖼️ 기존 세트 이미지 편집", "✨ 새 세트 만들기"],
                                horizontal=True, key="builder_mode")

        target_set_name = ""
        if builder_mode == "🖼️ 기존 세트 이미지 편집":
            all_set_names = []
            for cat_items in db_sets.values():
                all_set_names.extend(cat_items.keys())
            if not all_set_names:
                st.info("등록된 세트가 없습니다.")
                return
            target_set_name = st.selectbox("편집할 세트 선택", all_set_names,
                                           key="builder_target_set")

        # [V17] 배경 표시 여부 — key 기반 세션상태만 사용 (value+key 동시지정 충돌 제거)
        if "builder_show_bg" not in st.session_state:
            st.session_state.builder_show_bg = False  # 기본: 배경 끄기(요청 반영)
        show_bg = st.checkbox(
            "기존 세트 이미지를 배경으로 표시",
            key="builder_show_bg",
            help="체크 시 기존 세트 이미지가 반투명 배경으로 깔립니다. 새로 만들려면 체크 해제."
        )

        # 기존 세트 이미지 b64 (배경 표시가 켜져 있을 때만 전달)
        target_set_img_b64 = "null"
        if st.session_state.get("builder_show_bg", False) and builder_mode == "🖼️ 기존 세트 이미지 편집" and target_set_name:
            for cat_items in db_sets.values():
                if target_set_name in cat_items:
                    img_ref = cat_items[target_set_name].get("image")
                    if img_ref and len(str(img_ref)) > 10:
                        b64 = get_image_from_drive(img_ref)
                        if b64:
                            target_set_img_b64 = json.dumps(b64)
                    break

        # [재편집] 편집 대상 세트에 캔버스 데이터(JSON)가 저장돼 있으면 객체 복원용으로 주입
        target_set_canvas_json = "null"
        if builder_mode == "🖼️ 기존 세트 이미지 편집" and target_set_name:
            for cat_items in db_sets.values():
                if target_set_name in cat_items:
                    canvas_ref = cat_items[target_set_name].get("canvas")
                    if canvas_ref and len(str(canvas_ref)) > 10:
                        cjson = download_text_from_drive(canvas_ref)
                        if cjson:
                            # 이미 JSON 문자열 → JS 변수에 객체로 직접 삽입
                            # </script> 등으로 인한 스크립트 조기 종료 방지
                            target_set_canvas_json = cjson.replace("</", "<\\/")
                    break
        if builder_mode == "🖼️ 기존 세트 이미지 편집" and target_set_name and target_set_canvas_json != "null":
            st.success("🧩 이 세트는 빌더 데이터가 있어 부속·배관·텍스트를 그대로 불러와 수정할 수 있습니다.")
        elif builder_mode == "🖼️ 기존 세트 이미지 편집" and target_set_name:
            st.caption("ℹ️ 이 세트는 외부 업로드 이미지라 개별 부속 편집은 불가합니다. '배경으로 표시' 후 새로 배치하거나, 새 캔버스 데이터를 저장하면 다음부터 재편집됩니다.")

        mode_new        = "true" if builder_mode == "✨ 새 세트 만들기" else "false"
        target_set_json = json.dumps(target_set_name)

        html_code = f"""
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<script src="https://cdnjs.cloudflare.com/ajax/libs/fabric.js/5.3.1/fabric.min.js"></script>
<style>
* {{ box-sizing: border-box; margin: 0; padding: 0; }}
body {{ background: #1a1a2e; color: #e0e0e0; font-family: 'Segoe UI', sans-serif; font-size:13px; }}
#app {{ display:flex; flex-direction:column; height:100vh; }}
#toolbar {{ display:flex; align-items:center; gap:6px; padding:6px 10px; background:#16213e; flex-wrap:wrap; border-bottom:1px solid #0f3460; }}
#toolbar button {{ padding:4px 10px; border-radius:4px; border:1px solid #444; background:#2d2d4e; color:#eee; cursor:pointer; font-size:12px; }}
#toolbar button:hover {{ background:#0f3460; }}
#toolbar button.active {{ background:#e94560; border-color:#e94560; color:#fff; }}
.sep {{ width:1px; height:20px; background:#444; margin:0 4px; }}
#main {{ display:flex; flex:1; overflow:hidden; }}
#canvas-area {{ flex:1; padding:10px; overflow:hidden; background:#0d1b2a; position:relative; text-align:center; }}
#canvas-inner {{ display:inline-block; }}
#canvas-wrap {{ position:relative; display:inline-block; overflow:hidden; }}
#fabric-canvas {{ border:2px solid #0f3460; border-radius:4px; background:#fff; display:block; }}
#ctx-menu {{ position:absolute; background:#2d2d4e; border:1px solid #444; border-radius:4px; padding:4px 0; display:none; z-index:999; min-width:130px; box-shadow:0 4px 12px rgba(0,0,0,.5); }}
#ctx-menu div {{ padding:5px 14px; cursor:pointer; font-size:12px; color:#eee; }}
#ctx-menu div:hover {{ background:#e94560; }}
#props-panel {{ width:180px; background:#16213e; border-left:1px solid #0f3460; padding:8px; overflow-y:auto; flex-shrink:0; }}
#props-panel h4 {{ font-size:11px; color:#aaa; margin-bottom:8px; }}
.prop-row {{ margin-bottom:8px; }}
.prop-row label {{ display:block; font-size:10px; color:#aaa; margin-bottom:2px; }}
.prop-row input, .prop-row select {{ width:100%; background:#0d1b2a; border:1px solid #333; color:#eee; border-radius:3px; padding:3px 5px; font-size:12px; }}
#recipe-box {{ margin-top:10px; border-top:1px solid #333; padding-top:8px; }}
#recipe-box h4 {{ font-size:11px; color:#aaa; margin-bottom:6px; }}
#recipe-list {{ font-size:11px; color:#ccc; line-height:1.8; }}
#save-area {{ padding:8px; background:#16213e; border-top:1px solid #0f3460; }}
#save-area input {{ width:100%; background:#0d1b2a; border:1px solid #333; color:#eee; border-radius:4px; padding:5px; font-size:12px; margin-bottom:6px; }}
#save-area button {{ width:100%; padding:6px; border-radius:4px; border:none; font-size:12px; cursor:pointer; margin-bottom:4px; }}
.btn-primary {{ background:#e94560; color:#fff; }}
.btn-secondary {{ background:#0f3460; color:#eee; }}
#status {{ font-size:11px; color:#88f; padding:4px 0; text-align:center; }}
#pipe-props {{ display:none; }}
</style>
</head>
<body>
<div id="app">
  <!-- 상단 툴바 -->
  <div id="toolbar">
    <button id="btn-select" class="active" onclick="setMode('select')">↖ 선택</button>
    <button id="btn-pipe" onclick="setMode('pipe')">✏ 배관 그리기</button>
    <div class="sep"></div>
    <button onclick="flipX()">↔ 좌우반전</button>
    <button onclick="flipY()">↕ 상하반전</button>
    <div class="sep"></div>
    <button onclick="bringFwd()">▲ 앞으로</button>
    <button onclick="sendBck()">▼ 뒤로</button>
    <button onclick="bringFront()">⬆ 맨앞</button>
    <button onclick="sendBack()">⬇ 맨뒤</button>
    <div class="sep"></div>
    <button onclick="duplicateObj()" title="선택 복제 (배관·텍스트)">📋 복제</button>
    <button onclick="deleteObj()" style="color:#f99;" title="선택 삭제 (Delete 키도 동일)">🗑 삭제</button>
    <button onclick="gatherObjects()" style="color:#9cf;" title="캔버스 밖으로 나간 오브젝트를 전부 안으로 끌어옵니다">🧲 화면 안으로</button>
    <div class="sep"></div>
    <button onclick="addText()" title="설명·중요사항 텍스트 추가">🅣 텍스트</button>
    <div class="sep"></div>
    <button onclick="autoTrimSelected()" title="선택 이미지의 투명 여백을 잘라 누끼 영역만 남김">✂ 여백자르기</button>
    <button id="btn-crop" onclick="toggleCropMode()" title="원하는 영역을 드래그해 잘라내기">⛶ 영역자르기</button>
    <div class="sep"></div>
    <button onclick="doUndo()">↩ 실행취소</button>
    <button onclick="doRedo()">↪ 다시실행</button>
    <div class="sep"></div>
    <button onclick="clearCanvas()" style="color:#f88;">🗑 캔버스비우기</button>
    <button onclick="removeBgOnly()" style="color:#fb8;">🖼 배경만제거</button>
    <div class="sep"></div>
    <label style="font-size:11px;color:#aaa;">캔버스</label>
    <select id="canvas-size" onchange="resizeCanvas(this.value)"
      style="background:#2d2d4e;color:#eee;border:1px solid #444;border-radius:4px;padding:3px 6px;font-size:12px;">
      <option value="720,540">4:3 기본</option>
      <option value="720,720">1:1 정방형</option>
      <option value="960,540">16:9 와이드</option>
      <option value="540,720">3:4 세로형</option>
    </select>
    <div class="sep"></div>
    <label style="font-size:11px;color:#aaa;">화면</label>
    <button onclick="zoomOut()" title="축소">➖</button>
    <span id="zoom-val" style="font-size:11px;color:#aaa;min-width:36px;text-align:center;">100%</span>
    <button onclick="zoomIn()" title="확대">➕</button>
    <button onclick="zoomFit()" title="영역에 맞춤">⤢ 맞춤</button>
    <div id="pipe-props" style="display:flex;align-items:center;gap:6px;flex-wrap:wrap;">
      <label style="font-size:11px;color:#aaa;">색상</label>
      <input type="color" id="pipe-color" value="#2b2b2b" style="width:30px;height:22px;padding:0;border:none;background:none;cursor:pointer;">
      <span id="pipe-chips" style="display:inline-flex;gap:3px;align-items:center;"></span>
      <label style="font-size:11px;color:#aaa;margin-left:6px;">굵기</label>
      <input type="range" id="pipe-width" min="1" max="40" value="14" style="width:60px;">
      <span id="pipe-width-val" style="font-size:11px;color:#aaa;">14px</span>
    </div>
  </div>
  <div id="main">
    <!-- 캔버스 (Streamlit 왼쪽 칼럼에서 검색/추가, 여기서는 캔버스만) -->
    <!-- 캔버스 -->
    <div id="canvas-area">
      <div id="canvas-wrap">
        <canvas id="fabric-canvas" width="720" height="540"></canvas>
        <div id="ctx-menu">
          <div onclick="ctxBringFront()">⬆ 맨 앞으로</div>
          <div onclick="ctxBringFwd()">▲ 한 단계 앞</div>
          <div onclick="ctxSendBck()">▼ 한 단계 뒤</div>
          <div onclick="ctxSendBack()">⬇ 맨 뒤로</div>
          <div style="border-top:1px solid #444;margin:3px 0;"></div>
          <div onclick="ctxDelete()" style="color:#f88;">🗑 삭제</div>
        </div>
      </div>
      <div id="status" style="margin-top:6px;">선택 모드 — 위 검색창에서 부속 검색 후 클릭하여 캔버스에 추가</div>
    </div>
    <!-- 오른쪽 속성 패널 -->
    <div id="props-panel">
      <h4>선택 오브젝트</h4>
      <div id="obj-props">
        <div class="prop-row">
          <label>X 위치</label>
          <input type="number" id="prop-x" step="1" onchange="applyProp()">
        </div>
        <div class="prop-row">
          <label>Y 위치</label>
          <input type="number" id="prop-y" step="1" onchange="applyProp()">
        </div>
        <div class="prop-row">
          <label>너비(W)</label>
          <input type="number" id="prop-w" step="1" min="10" onchange="applyProp()">
        </div>
        <div class="prop-row">
          <label>높이(H)</label>
          <input type="number" id="prop-h" step="1" min="10" onchange="applyProp()">
        </div>
        <div class="prop-row">
          <label>각도(°)</label>
          <input type="number" id="prop-angle" step="1" onchange="applyProp()">
        </div>
        <div id="pipe-extra-props" style="display:none;">
          <div class="prop-row">
            <label>배관 색상</label>
            <input type="color" id="prop-pipe-color" onchange="applyLineProp()">
          </div>
          <div class="prop-row">
            <label>색상 견본 (클릭하여 적용)</label>
            <div id="prop-pipe-chips" style="display:flex;flex-wrap:wrap;gap:5px;margin-top:2px;"></div>
          </div>
          <div class="prop-row">
            <label>배관 굵기</label>
            <input type="number" id="prop-pipe-width" min="1" max="50" step="1" onchange="applyLineProp()">
          </div>
          <div class="prop-row">
            <label>투명도</label>
            <input type="range" id="prop-opacity" min="0" max="1" step="0.05" onchange="applyLineProp()">
          </div>
        </div>
        <div id="text-extra-props" style="display:none;">
          <div class="prop-row">
            <label>글자 크기</label>
            <input type="number" id="prop-font-size" min="6" max="200" step="1" onchange="applyTextProp()">
          </div>
          <div class="prop-row">
            <label>글자 색상</label>
            <input type="color" id="prop-font-color" onchange="applyTextProp()">
          </div>
        </div>
      </div>
      <div id="recipe-box">
        <h4>📋 구성 집계</h4>
        <div id="recipe-list">캔버스에 부속 추가 시<br>자동으로 집계됩니다.</div>
      </div>
    </div>
  </div>
  <!-- 하단 저장 영역 -->
  <div id="save-area">
    <button class="btn-primary" onclick="sendToApp()">💾 저장 (이미지+구성 자동 등록)</button>
    <button class="btn-secondary" onclick="downloadPng()">📥 PNG만 내려받기 (백업용)</button>
    <button class="btn-secondary" onclick="downloadCanvasJson()">🧩 캔버스 데이터(.json) 내려받기 (백업용)</button>
    <div id="status2"></div>
  </div>
</div>

<script>
const MODE_NEW = {mode_new};
const TARGET_SET = {target_set_json};
const TARGET_SET_IMG_B64 = {target_set_img_b64};
const TARGET_SET_CANVAS_JSON = {target_set_canvas_json};  // 빌더로 만든 세트의 편집용 캔버스 데이터
const PENDING_WRAP = {pending_json};  // [V37] {{token, items}}
const PENDING_ITEMS = (PENDING_WRAP && PENDING_WRAP.items) ? PENDING_WRAP.items : [];
const WS_TOKEN = (PENDING_WRAP && PENDING_WRAP.token) ? String(PENDING_WRAP.token) : '';
let CW = 720, CH = 540;

let canvas, curMode = 'select';
let pipeStart = null, isPiping = false;
let undoStack = [], redoStack = [];
let objRecipe = {{}};   // objId -> {{code, name, qty}}
let lastObjId = 0;
let bgImageRef = null;  // [V14] 현재 배경 이미지 객체 참조
let zoomLevel = 1;      // [V15] 화면 표시 배율 (저장 품질과 무관)

// ── [V26] 작업중 배관·텍스트 영속화 (Streamlit 리런 견딤) ────────────────
// 신규/빌드 모드는 리런마다 부속(PENDING_ITEMS)만 재주입되어 그린 배관(_isPipe)·
// 텍스트(_isUserText)가 사라졌다. → 캔버스 변경마다 부모 localStorage에 저장하고
// 초기화 직후 복원한다. 부속은 기존 방식 유지(서로 겹치지 않아 안전).
const WORK_SIG = MODE_NEW ? 'NEW' : ('EDIT:' + (TARGET_SET || ''));
const WORK_KEY = 'LOOPER_WORK';
const PARTS_KEY = 'LOOPER_WORK_PARTS';   // [V37] 부속 위치 저장소 — 모드(sig) 전환에도 유지, 세션 토큰으로 보호
let _initializing = true;   // 초기화 중 저장 억제(빈 상태로 덮어쓰기 방지)
let _initDone = false;      // finishInit 1회 보장
let _workTimer = null;
function _lstore() {{
    try {{ return (window.parent && window.parent.localStorage) ? window.parent.localStorage : window.localStorage; }}
    catch (e) {{ return window.localStorage; }}
}}
function saveWorkState() {{
    if (_initializing) return;
    try {{
        const items = [];
        const curParts = {{}};
        canvas.getObjects().forEach(function(o, idx) {{
            if (o._isPipe || o._isUserText) {{
                const j = o.toObject(['_isPipe','_isUserText','_objId']);
                j.__z = idx;   // [V26.1] 전체 스택 인덱스 보존(맨앞/맨뒤 순서 복원용)
                items.push(j);
            }} else if (o._looperCode && o._pendKey) {{
                curParts[o._pendKey] = {{left:o.left, top:o.top, scaleX:o.scaleX, scaleY:o.scaleY, angle:(o.angle||0), flipX:!!o.flipX, flipY:!!o.flipY}};
            }}
        }});
        _lstore().setItem(WORK_KEY, JSON.stringify({{sig: WORK_SIG, items: items}}));
        // [V37] 부속 위치는 모드와 무관한 별도 키에 '병합' 저장 — ①이미지 로딩 중의 부분 저장이
        //        아직 안 뜬 부속의 위치를 지우지 않게(리셋 원인) ②신규↔편집 전환에도 배치 유지.
        const merged = Object.assign({{}}, _loadSavedParts(), curParts);
        _lstore().setItem(PARTS_KEY, JSON.stringify({{token: WS_TOKEN, parts: merged}}));
    }} catch (e) {{}}
}}
function _loadSavedParts() {{
    // [V37] 부속 위치는 PARTS_KEY(토큰 검증)에서 — 모드·세트 전환에도 유지, 이전 세션 잔재는 무시
    try {{
        const raw = _lstore().getItem(PARTS_KEY);
        if (!raw) return {{}};
        const d = JSON.parse(raw);
        if (d && String(d.token) === WS_TOKEN && d.parts) return d.parts;
    }} catch (e) {{}}
    return {{}};
}}
function saveWorkStateDebounced() {{
    if (_workTimer) clearTimeout(_workTimer);
    _workTimer = setTimeout(saveWorkState, 200);
}}
function clearWorkState() {{
    try {{ _lstore().removeItem(WORK_KEY); _lstore().removeItem(PARTS_KEY); }} catch (e) {{}}
}}
function restoreWorkPipes(done) {{
    try {{
        const raw = _lstore().getItem(WORK_KEY);
        if (!raw) {{ if (done) done(); return; }}
        const data = JSON.parse(raw);
        if (!data || data.sig !== WORK_SIG || !data.items || !data.items.length) {{ if (done) done(); return; }}
        canvas.getObjects().filter(o => o._isPipe || o._isUserText).forEach(o => canvas.remove(o));
        fabric.util.enlivenObjects(data.items, function(objs) {{
            // [V26.1] 저장된 스택 인덱스(__z) 오름차순으로 제자리 이동 → 맨뒤/맨앞 순서 복원
            const withZ = objs.map((o, i) => ({{o: o, z: (data.items[i] && data.items[i].__z != null) ? data.items[i].__z : 99999}}));
            withZ.sort((a, b) => a.z - b.z);
            withZ.forEach(x => canvas.add(x.o));
            withZ.forEach(x => {{ try {{ canvas.moveTo(x.o, x.z); }} catch (e2) {{}} }});
            canvas.renderAll();
            if (done) done();
        }});
    }} catch (e) {{ if (done) done(); }}
}}
function finishInit() {{
    if (_initDone) return;
    _initDone = true;
    restoreWorkPipes(function() {{ _initializing = false; }});
}}

// ── Fabric 초기화 ───────────────────────────────────────────────────
window.onload = function() {{
    canvas = new fabric.Canvas('fabric-canvas', {{
        selection: true,
        preserveObjectStacking: true,
    }});
    canvas.setWidth(CW); canvas.setHeight(CH);

    // 대기열에 품목이 있으면 캔버스에 자동 추가
    // [V26.2] 편집(캔버스복원)모드에선 loadFromJSON이 캔버스를 clear→교체하므로 경쟁 방지 위해
    //          여기서 즉시 추가하지 않고 loadFromJSON 완료 콜백에서 얹는다(아래). 그 외엔 즉시.
    if (PENDING_ITEMS && PENDING_ITEMS.length > 0 && (MODE_NEW || !TARGET_SET_CANVAS_JSON)) {{
        applyPendingItems();
    }}

    // 이벤트
    canvas.on('mouse:down', onMouseDown);
    canvas.on('mouse:move', onMouseMove);
    canvas.on('mouse:up', onMouseUp);
    canvas.on('selection:created', onSelect);
    canvas.on('selection:updated', onSelect);
    canvas.on('selection:cleared', onDeselect);
    canvas.on('object:modified', () => {{ pushUndo(); saveWorkStateDebounced(); }});
    canvas.on('object:added', () => {{ pushUndo(); updateRecipe(); saveWorkStateDebounced(); }});
    canvas.on('object:removed', () => {{ pushUndo(); updateRecipe(); saveWorkStateDebounced(); }});
    canvas.on('contextmenu', onContextMenu);

    // 배관 굵기 슬라이더
    document.getElementById('pipe-width').addEventListener('input', function() {{
        document.getElementById('pipe-width-val').textContent = this.value + 'px';
    }});

    // [V19] 배관 색상 칩 — 호스/농수관/기본색
    const PIPE_CHIPS = [
        {{c:'#f4d624', t:'호스 (244/214/36)'}},
        {{c:'#2b2b2b', t:'농수관 (짙은 회색)'}},
        {{c:'#ffffff', t:'흰색'}},
        {{c:'#e23b3b', t:'빨강'}},
        {{c:'#2b6fe2', t:'파랑'}},
        {{c:'#2eaa4a', t:'녹색'}},
        {{c:'#7b3fe4', t:'보라'}},
        {{c:'#ff7ab8', t:'핑크'}},
        {{c:'#ffe600', t:'노랑'}},
        {{c:'#ff8c1a', t:'주황'}},
        {{c:'#000000', t:'검정'}},
    ];
    // 칩 클릭 → 현재 색상 입력 동기화 + 선택된 배관 즉시 적용
    function applyPipeColor(c) {{
        const tc = document.getElementById('pipe-color');     if (tc) tc.value = c;
        const pc = document.getElementById('prop-pipe-color'); if (pc) pc.value = c;
        const o = canvas.getActiveObject();
        if (o && (o._isPipe || o.type === 'line' || o.type === 'rect')) {{
            if (o.type === 'rect') o.set('fill', c); else o.set('stroke', c);
            canvas.renderAll(); pushUndo();
        }}
    }}
    // 동일 칩을 (1)상단 배관모드 팔레트, (2)우측 속성패널 두 곳에 생성
    function buildChips(containerId, sz) {{
        const box = document.getElementById(containerId);
        if (!box) return;
        PIPE_CHIPS.forEach(ch => {{
            const b = document.createElement('span');
            b.title = ch.t;
            b.style.cssText = 'width:'+sz+'px;height:'+sz+'px;border-radius:3px;cursor:pointer;border:1px solid #777;background:'+ch.c+';display:inline-block;';
            b.onclick = function() {{ applyPipeColor(ch.c); }};
            box.appendChild(b);
        }});
    }}
    buildChips('pipe-chips', 18);        // 상단 배관 그리기 모드 팔레트
    buildChips('prop-pipe-chips', 20);   // 우측 속성 패널 (선택 모드에서 재색칠)

    // 캔버스 우클릭 메뉴 닫기
    document.addEventListener('click', () => {{ document.getElementById('ctx-menu').style.display='none'; }});

    // ── [추가] 단축키: Ctrl+Z(취소) / Ctrl+Shift+Z·Ctrl+Y(다시) / Del(삭제) ──
    function isTextEditing() {{
        const ao = canvas.getActiveObject();
        if (ao && ao.isEditing) return true;                 // 텍스트 편집 중엔 무시
        const t = document.activeElement;
        return t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.tagName === 'SELECT');
    }}
    document.addEventListener('keydown', function(e) {{
        const key = (e.key || '').toLowerCase();
        const ctrl = e.ctrlKey || e.metaKey;                 // Windows Ctrl / Mac Cmd
        if (ctrl && key === 'z' && !e.shiftKey) {{ if(isTextEditing()) return; e.preventDefault(); doUndo(); }}
        else if (ctrl && (key === 'y' || (key === 'z' && e.shiftKey))) {{ if(isTextEditing()) return; e.preventDefault(); doRedo(); }}
        else if (key === 'delete' || key === 'backspace') {{ if(isTextEditing()) return; if(canvas.getActiveObject()){{ e.preventDefault(); deleteObj(); }} }}
    }});
    // iframe이 포커스를 받아야 단축키가 동작 → 진입/클릭 시 자동 포커스
    try {{ window.focus(); }} catch(_){{}}
    document.body.setAttribute('tabindex','0');
    document.body.addEventListener('mousedown', () => {{ try {{ window.focus(); }} catch(_){{}} }});

    pushUndo();
    setMode('select');
    setTimeout(zoomFit, 80);   // [V15] 레이아웃 확정 후 영역 맞춤
    // [V36] 2초 주기 자동저장(안전망) — 개별 훅이 놓친 변경도 리런 전에 보존
    setInterval(function() {{ if (!_initializing) saveWorkState(); }}, 2000);

    // ── 기존 세트 이미지 캔버스 로드 (편집 모드) ─────────────────────
    // [재편집] 빌더로 만든 세트는 캔버스 데이터(JSON)가 있으면 객체를 그대로 복원
    //          → 부속·배관·텍스트를 개별 수정 가능. 외부 업로드 세트는 기존 PNG 배경 방식.
    if (!MODE_NEW && TARGET_SET_CANVAS_JSON) {{
        canvas.loadFromJSON(TARGET_SET_CANVAS_JSON, function() {{
            // objId 충돌 방지 + 집계 복원
            objRecipe = {{}};
            let maxId = 0;
            canvas.getObjects().forEach(o => {{
                o.setCoords();
                if (o._objId && o._objId > maxId) maxId = o._objId;
                if (o._looperCode) {{
                    if (!o._objId) o._objId = ++maxId;
                    objRecipe[o._objId] = {{code:o._looperCode, name:o._looperName, qty:1}};
                }}
            }});
            lastObjId = maxId;
            canvas.renderAll();
            updateRecipe();
            undoStack = []; redoStack = []; pushUndo();
            setTimeout(zoomFit, 30);
            setStatus('빌더 데이터 복원됨 — 부속·배관·텍스트를 자유롭게 수정하세요.');
            // [V26.2] 저장본 복원 완료 후에 새로 추가한 부속(PENDING)을 위에 얹음 → 기존 배치 보존
            if (PENDING_ITEMS && PENDING_ITEMS.length > 0) applyPendingItems();
            finishInit();   // [V26] 작업중 배관·텍스트 복원
        }});
    }}
    // [V15] 배경 표시 여부는 Python(show_bg 체크박스)이 결정.
    //  TARGET_SET_IMG_B64가 null이면 애초에 전달 안 됨 → 배경 없음.
    else if (!MODE_NEW && TARGET_SET_IMG_B64) {{
        fabric.Image.fromURL(TARGET_SET_IMG_B64, function(img) {{
            const scale = Math.min(CW / img.width, CH / img.height);
            img.set({{
                left: 0, top: 0,
                scaleX: scale, scaleY: scale,
                selectable: false,
                evented: false,
                opacity: 0.82,
                _isBgImage: true,
            }});
            bgImageRef = img;
            canvas.add(img);
            canvas.sendToBack(img);
            canvas.renderAll();
            setTimeout(zoomFit, 30);
            setStatus('기존 이미지 로드됨 — 위에 부속을 배치하거나 PNG로 교체하세요.');
            finishInit();   // [V26] 작업중 배관·텍스트 복원
        }});
    }}
    // [V26] 위 편집(캔버스/배경) 분기가 안 도는 신규모드 등은 여기서 직접 복원
    if (MODE_NEW || (!TARGET_SET_CANVAS_JSON && !TARGET_SET_IMG_B64)) finishInit();
}};

// ── [V14] 흰배경 자동 누끼 ───────────────────────────────────────────
// 흰색~연회색 배경 픽셀을 투명화한 dataURL을 콜백으로 반환.
// 원본(드라이브 JPG)은 건드리지 않고, 캔버스 표시용으로만 변환.
// THRESH 이상 밝고 채도 낮은 픽셀 → 투명. 가장자리 부드럽게 알파 처리.
function makeTransparentBg(srcUrl, cb) {{
    const im = new Image();
    im.crossOrigin = 'anonymous';
    im.onload = function() {{
        const cv = document.createElement('canvas');
        cv.width = im.naturalWidth; cv.height = im.naturalHeight;
        const cx = cv.getContext('2d');
        cx.drawImage(im, 0, 0);
        let data;
        try {{ data = cx.getImageData(0, 0, cv.width, cv.height); }}
        catch(e) {{ cb(srcUrl); return; }}  // CORS 등 실패 시 원본 그대로
        const d = data.data;
        // [V37] 테두리 연결 플러드필 — 배경(흰~밝은 회색·그라데이션·JPEG 이음새)만 투명화.
        //  전역 임계(구 238)와 달리 회색 배경도 제거하고 제품 내부의 밝은 픽셀(금속 광택 등)은 보존.
        //  임계는 테두리 밝기 중앙값 기반 적응. (00278·01513 실측: 배경 제거 OK, 제품 침식 0)
        const W = cv.width, H = cv.height;
        const samp = [];
        const stepX = Math.max(1, (W / 80) | 0);
        for (let x = 0; x < W; x += stepX) {{
            samp.push(Math.min(d[x*4], d[x*4+1], d[x*4+2]));
            const bIdx = ((H-1)*W + x) * 4;
            samp.push(Math.min(d[bIdx], d[bIdx+1], d[bIdx+2]));
        }}
        samp.sort(function(a, b) {{ return a - b; }});
        const med = samp.length ? samp[(samp.length / 2) | 0] : 255;
        const TH = Math.max(200, Math.min(238, med - 18));
        const SATMAX = 26;
        function _isBg(p) {{
            const r = d[p*4], g = d[p*4+1], b = d[p*4+2];
            const mn = Math.min(r, g, b), mx = Math.max(r, g, b);
            return mn >= TH && (mx - mn) <= SATMAX;
        }}
        const visited = new Uint8Array(W * H);
        const stack = [];
        for (let x = 0; x < W; x++) {{
            const t = x, bt = (H-1)*W + x;
            if (!visited[t] && _isBg(t)) {{ visited[t] = 1; stack.push(t); }}
            if (!visited[bt] && _isBg(bt)) {{ visited[bt] = 1; stack.push(bt); }}
        }}
        for (let y = 0; y < H; y++) {{
            const l = y*W, rr = y*W + W - 1;
            if (!visited[l] && _isBg(l)) {{ visited[l] = 1; stack.push(l); }}
            if (!visited[rr] && _isBg(rr)) {{ visited[rr] = 1; stack.push(rr); }}
        }}
        while (stack.length) {{
            const p = stack.pop();
            d[p*4 + 3] = 0;
            const x = p % W, y = (p / W) | 0;
            if (x > 0)     {{ const q = p - 1; if (!visited[q] && _isBg(q)) {{ visited[q] = 1; stack.push(q); }} }}
            if (x < W - 1) {{ const q = p + 1; if (!visited[q] && _isBg(q)) {{ visited[q] = 1; stack.push(q); }} }}
            if (y > 0)     {{ const q = p - W; if (!visited[q] && _isBg(q)) {{ visited[q] = 1; stack.push(q); }} }}
            if (y < H - 1) {{ const q = p + W; if (!visited[q] && _isBg(q)) {{ visited[q] = 1; stack.push(q); }} }}
        }}
        cx.putImageData(data, 0, 0);
        cb(cv.toDataURL('image/png'));
    }};
    im.onerror = function() {{ cb(srcUrl); }};
    im.src = srcUrl;
}}

// ── 대기열 품목 캔버스 자동 추가 ────────────────────────────────────
// PENDING_ITEMS: [code, name, spec, qty, b64 ...]
// qty만큼 이미지를 격자 배치, b64 없으면 텍스트 라벨로 대체
function applyPendingItems() {{
    const savedParts = _loadSavedParts();   // [V31] 저장된 부속 위치/크기 복원용
    const COLS = 5;
    const _tot = PENDING_ITEMS.reduce((s, x) => s + (x.qty || 1), 0);
    const _rows = Math.max(1, Math.ceil(_tot / COLS));
    const STEP_X = 135;
    // [V31] 캔버스 높이에 맞춰 세로 간격 축소 → 부속이 16개 넘어도 전부 캔버스 안에 보이게(밖으로 나가던 문제 해결)
    const STEP_Y = Math.min(98, Math.max(46, Math.floor((CH - 60) / _rows)));
    const OFFSET_X = 24, OFFSET_Y = 24;
    let col = 0, row = 0;

    PENDING_ITEMS.forEach((item, itemIdx) => {{
        for (let i = 0; i < item.qty; i++) {{
            const lx = OFFSET_X + (col % COLS) * STEP_X;
            const ly = OFFSET_Y + row * STEP_Y;
            col++;
            if (col % COLS === 0) row++;
            // [V33] uid 기반 키 — 항목을 빼도 다른 부속의 저장 위치가 안 흔들림 (uid 없으면 구키 폴백)
            const partKey = (item.uid ? 'u' + item.uid : String(itemIdx)) + '_' + i;
            const savedT = savedParts[partKey];

            if (item.b64) {{
                makeTransparentBg(item.b64, function(cleanUrl) {{
                    fabric.Image.fromURL(cleanUrl, function(img) {{
                        img.set({{
                            left: lx, top: ly,
                            scaleX: 0.45, scaleY: 0.45,
                            cornerSize: 8, hasRotatingPoint: true,
                        }});
                        img._looperCode = item.code;
                        img._looperName = item.name;
                        img._looperSpec = item.spec;
                        img._objId = ++lastObjId;
                        img._pendKey = partKey;
                        if (savedT) {{ img.set(savedT); }}   // [V31] 저장된 위치/크기 복원
                        if (item.hidden) {{ img.visible = false; }}   // [V34] 이미지 숨김(구성·집계엔 포함, 렌더·PNG 제외)
                        img.setCoords();
                        objRecipe[img._objId] = {{code: item.code, name: item.name, qty: 1}};
                        canvas.add(img);
                        canvas.renderAll();
                        updateRecipe();
                    }});
                }});
            }} else {{
                // 이미지 없으면 텍스트 라벨
                const txt = new fabric.IText(`[${{item.code}}]\n${{item.name}}`, {{
                    left: lx, top: ly,
                    fontSize: 11, fill: '#333',
                    fontFamily: 'sans-serif',
                    selectable: true, editable: false,
                }});
                txt._looperCode = item.code;
                txt._looperName = item.name;
                txt._looperSpec = item.spec;
                txt._objId = ++lastObjId;
                txt._pendKey = partKey;
                if (savedT) {{ txt.set(savedT); }}   // [V31] 저장된 위치/크기 복원
                if (item.hidden) {{ txt.visible = false; }}   // [V34] 이미지 숨김
                txt.setCoords();
                objRecipe[txt._objId] = {{code: item.code, name: item.name, qty: 1}};
                canvas.add(txt);
                canvas.renderAll();
                updateRecipe();
            }}
        }}
    }});

    if (PENDING_ITEMS.length > 0) {{
        const total = PENDING_ITEMS.reduce((s, x) => s + x.qty, 0);
        setStatus(`${{total}}개 품목이 캔버스에 추가되었습니다.`);
    }}
}}

// ── 모드 전환 ────────────────────────────────────────────────────────
function setMode(m) {{
    curMode = m;
    isPiping = false; pipeStart = null;
    document.getElementById('btn-select').classList.toggle('active', m==='select');
    document.getElementById('btn-pipe').classList.toggle('active', m==='pipe');
    document.getElementById('pipe-props').style.display = m==='pipe' ? 'flex' : 'none';
    canvas.selection = m === 'select';
    canvas.forEachObject(o => {{ o.selectable = m === 'select'; }});
    canvas.defaultCursor = m === 'pipe' ? 'crosshair' : 'default';
    setStatus(m==='select' ? '선택 모드 — 오브젝트를 클릭하여 선택/이동' : '배관 모드 — 클릭해서 시작점, 다시 클릭해서 끝점 확정');
}}

// ── 배관 그리기 (사각형 Rect 기반) ──────────────────────────────────
// 드래그 시작→끝: 길이=거리, 두께=굵기, 각도=방향. 평면 배치에 적합한 사각 끝.
let tempLine = null;
function onMouseDown(opt) {{
    if (curMode === 'crop') {{
        const p = canvas.getPointer(opt.e);
        cropStart = {{x:p.x, y:p.y}};
        if (cropRect) canvas.remove(cropRect);
        cropRect = new fabric.Rect({{
            left:p.x, top:p.y, width:1, height:1,
            fill:'rgba(233,69,96,0.15)', stroke:'#e94560',
            strokeDashArray:[5,3], strokeWidth:1.5,
            selectable:false, evented:false,
        }});
        canvas.add(cropRect); canvas.renderAll();
        return;
    }}
    if (curMode !== 'pipe') return;
    const p = canvas.getPointer(opt.e);
    if (!isPiping) {{
        isPiping = true; pipeStart = {{x:p.x, y:p.y}};
        const w = parseInt(document.getElementById('pipe-width').value);
        tempLine = new fabric.Rect({{
            left: p.x, top: p.y - w/2, width: 1, height: w,
            fill: document.getElementById('pipe-color').value,
            selectable: false, evented: false,
            originX: 'left', originY: 'top',
        }});
        canvas.add(tempLine);
    }} else {{
        finalizePipe(p);
    }}
}}
function finalizePipe(p) {{
    if (tempLine) {{ canvas.remove(tempLine); tempLine = null; }}
    const w = parseInt(document.getElementById('pipe-width').value);
    const dx = p.x - pipeStart.x, dy = p.y - pipeStart.y;
    const len = Math.max(2, Math.sqrt(dx*dx + dy*dy));
    const angle = Math.atan2(dy, dx) * 180 / Math.PI;
    const rect = new fabric.Rect({{
        left: pipeStart.x, top: pipeStart.y,
        width: len, height: w,
        fill: document.getElementById('pipe-color').value,
        originX: 'left', originY: 'center',
        angle: angle,
        selectable: true, evented: true,
        cornerSize: 8, hasRotatingPoint: true,
        rx: 0, ry: 0,   // 사각 끝 (둥글게 하려면 rx,ry 값 부여)
    }});
    rect._isPipe = true;
    canvas.add(rect);
    canvas.setActiveObject(rect);
    canvas.renderAll();
    isPiping = false; pipeStart = null;
    pushUndo();
    saveWorkState();   // [V26] 배관 생성 즉시 영속화 (리런 전에 확실히 저장)
}}
function onMouseMove(opt) {{
    if (curMode === 'crop' && cropStart && cropRect) {{
        const p = canvas.getPointer(opt.e);
        cropRect.set({{
            left: Math.min(cropStart.x, p.x), top: Math.min(cropStart.y, p.y),
            width: Math.abs(p.x - cropStart.x), height: Math.abs(p.y - cropStart.y),
        }});
        canvas.renderAll();
        return;
    }}
    if (!isPiping || !tempLine) return;
    const p = canvas.getPointer(opt.e);
    const dx = p.x - pipeStart.x, dy = p.y - pipeStart.y;
    const len = Math.max(1, Math.sqrt(dx*dx + dy*dy));
    const angle = Math.atan2(dy, dx) * 180 / Math.PI;
    const w = parseInt(document.getElementById('pipe-width').value);
    tempLine.set({{
        left: pipeStart.x, top: pipeStart.y,
        width: len, height: w,
        originX: 'left', originY: 'center', angle: angle,
    }});
    canvas.renderAll();
}}
function onMouseUp(opt) {{
    // [V37] 영역자르기: 드래그를 놓는 순간 바로 적용 (두 번째 버튼 클릭 불필요)
    if (curMode === 'crop' && cropStart && cropRect) {{
        applyCrop();
        return;
    }}
    // 드래그식(누른 채 이동 후 떼기)도 지원: 충분히 움직였으면 확정
    if (curMode === 'pipe' && isPiping && tempLine) {{
        const p = canvas.getPointer(opt.e);
        const dx = p.x - pipeStart.x, dy = p.y - pipeStart.y;
        if (Math.sqrt(dx*dx + dy*dy) > 8) {{ finalizePipe(p); }}
    }}
}}

// ── 선택 이벤트 ─────────────────────────────────────────────────────
function onSelect(opt) {{
    const obj = canvas.getActiveObject();
    if (!obj) return;
    document.getElementById('prop-x').value = Math.round(obj.left);
    document.getElementById('prop-y').value = Math.round(obj.top);
    document.getElementById('prop-w').value = Math.round(obj.getScaledWidth());
    document.getElementById('prop-h').value = Math.round(obj.getScaledHeight());
    document.getElementById('prop-angle').value = Math.round(obj.angle);
    const isPipe = obj._isPipe || obj.type === 'line' || obj.type === 'rect';
    document.getElementById('pipe-extra-props').style.display = isPipe ? 'block' : 'none';
    if (isPipe) {{
        // Rect 배관은 fill, Line 배관은 stroke
        const col = (obj.type === 'rect') ? (obj.fill || '#2b2b2b') : (obj.stroke || '#2b2b2b');
        document.getElementById('prop-pipe-color').value = col;
        const wdt = (obj.type === 'rect') ? Math.round(obj.getScaledHeight()) : (obj.strokeWidth || 8);
        document.getElementById('prop-pipe-width').value = wdt;
        document.getElementById('prop-opacity').value = obj.opacity !== undefined ? obj.opacity : 1;
    }}
    // [추가] 텍스트 오브젝트 선택 시 글자 크기/색상 패널 표시
    const isText = (obj.type === 'i-text' || obj.type === 'text' || obj.type === 'textbox');
    document.getElementById('text-extra-props').style.display = isText ? 'block' : 'none';
    if (isText) {{
        document.getElementById('prop-font-size').value = Math.round(obj.fontSize || 28);
        const fc = (typeof obj.fill === 'string' && obj.fill[0] === '#') ? obj.fill : '#222222';
        document.getElementById('prop-font-color').value = fc;
    }}
}}
function onDeselect() {{
    document.getElementById('pipe-extra-props').style.display='none';
    document.getElementById('text-extra-props').style.display='none';
}}

// ── 속성 패널 적용 ───────────────────────────────────────────────────
function applyProp() {{
    const obj = canvas.getActiveObject();
    if (!obj) return;
    const x = parseFloat(document.getElementById('prop-x').value);
    const y = parseFloat(document.getElementById('prop-y').value);
    const w = parseFloat(document.getElementById('prop-w').value);
    const h = parseFloat(document.getElementById('prop-h').value);
    const a = parseFloat(document.getElementById('prop-angle').value);
    obj.set({{left:x, top:y, angle:a}});
    if (obj.type === 'image') {{
        obj.scaleX = w / obj.width;
        obj.scaleY = h / obj.height;
    }} else if (obj.type === 'rect') {{
        // 배관: 스케일 초기화 후 실제 width/height로 길이·두께 설정
        obj.set({{scaleX:1, scaleY:1, width: Math.max(2,w), height: Math.max(1,h)}});
    }}
    obj.setCoords();
    canvas.renderAll();
    pushUndo();
    saveWorkStateDebounced();   // [V36] 패널(X/Y/W/H/각도) 조정 영속화 — 프로그램적 set은 object:modified 미발화
}}
function applyLineProp() {{
    const obj = canvas.getActiveObject();
    if (!obj) return;
    const col = document.getElementById('prop-pipe-color').value;
    const wd  = parseInt(document.getElementById('prop-pipe-width').value);
    const op  = parseFloat(document.getElementById('prop-opacity').value);
    if (obj.type === 'rect') {{
        obj.set({{fill: col, scaleY: 1, height: Math.max(1, wd), opacity: op}});
    }} else {{
        obj.set({{stroke: col, strokeWidth: wd, opacity: op}});
    }}
    obj.setCoords();
    canvas.renderAll();
    pushUndo();
    saveWorkStateDebounced();   // [V36] 배관 속성 패널 조정 영속화
}}

// ── 변환 버튼들 ─────────────────────────────────────────────────────
function flipX() {{ const o=canvas.getActiveObject(); if(o){{ o.set('flipX',!o.flipX); canvas.renderAll(); pushUndo(); saveWorkStateDebounced(); }} }}
function flipY() {{ const o=canvas.getActiveObject(); if(o){{ o.set('flipY',!o.flipY); canvas.renderAll(); pushUndo(); saveWorkStateDebounced(); }} }}
function bringFwd()   {{ const o=canvas.getActiveObject(); if(o){{ canvas.bringForward(o); pushUndo(); saveWorkState(); }} }}
function sendBck()    {{ const o=canvas.getActiveObject(); if(o){{ canvas.sendBackwards(o); pushUndo(); saveWorkState(); }} }}
function bringFront() {{ const o=canvas.getActiveObject(); if(o){{ canvas.bringToFront(o); pushUndo(); saveWorkState(); }} }}
function sendBack()   {{ const o=canvas.getActiveObject(); if(o){{ canvas.sendToBack(o); pushUndo(); saveWorkState(); }} }}
function deleteObj()  {{
    const o = canvas.getActiveObject();
    if (!o) return;
    // [V33] 부속(제품 이미지)은 여기서 지워도 리런 때 되살아나고 구성(레시피)과 어긋남 →
    //        왼쪽 '➖ 부속 빼기'로 유도. 배관·텍스트는 그대로 삭제 가능(작업상태에 반영).
    if (o._looperCode) {{
        setStatus('부속은 왼쪽 \\'➖ 부속 빼기\\' 목록에서 빼주세요. (캔버스에서 지우면 구성과 어긋나고 다시 나타납니다)');
        return;
    }}
    if (o._objId) delete objRecipe[o._objId];
    canvas.remove(o); pushUndo(); updateRecipe();
    saveWorkState();   // [V33] 배관·텍스트 삭제 즉시 영속화
}}
// [V75] 캔버스 밖으로 나간 오브젝트 회수 — 드래그로 못 잡는 상태를 푼다.
//       (누끼 여백이 큰 이미지를 확대하거나, 배치 격자가 밀리면 밖으로 나가서 클릭이 안 됨)
function gatherObjects() {{
    const M = 8;                       // 캔버스 안쪽 여백(px)
    let moved = 0;
    canvas.getObjects().forEach(function(o) {{
        if (o._isBgImage) return;
        const b = o.getBoundingRect(true, true);
        let dx = 0, dy = 0;
        if (b.left < M) dx = M - b.left;
        else if (b.left + b.width > CW - M) dx = (CW - M) - (b.left + b.width);
        if (b.top < M) dy = M - b.top;
        else if (b.top + b.height > CH - M) dy = (CH - M) - (b.top + b.height);
        // 캔버스보다 큰 오브젝트는 좌상단에 맞춰 붙인다(잘려도 잡을 수는 있게)
        if (b.width  > CW - 2*M) dx = M - b.left;
        if (b.height > CH - 2*M) dy = M - b.top;
        if (dx || dy) {{ o.set({{ left: o.left + dx, top: o.top + dy }}); o.setCoords(); moved++; }}
    }});
    canvas.renderAll();
    if (moved) {{ pushUndo(); saveWorkState(); }}
    setStatus(moved ? moved + '개를 캔버스 안으로 끌어왔습니다. 이제 선택·이동할 수 있습니다.'
                    : '캔버스 밖으로 나간 오브젝트가 없습니다.');
}}
function duplicateObj() {{
    const o = canvas.getActiveObject();
    if (!o) {{ setStatus('복사할 오브젝트를 먼저 선택하세요.'); return; }}
    // [V36] 부속 복사는 차단 — 복사본은 파이썬 구성에 없어서 리런 때 사라지고 집계와 어긋남.
    //        수량을 늘리려면 왼쪽 검색에서 추가(구성·캔버스 동시 반영).
    if (o._looperCode) {{
        setStatus('부속 수량 추가는 왼쪽 검색에서 [➕ 추가]를 사용하세요. (여기서 복사하면 저장 시 구성과 어긋나고 사라집니다)');
        return;
    }}
    o.clone(function(cl) {{
        cl.set({{ left: o.left + 24, top: o.top + 24 }});
        if (o._isPipe) cl._isPipe = true;
        if (o._isUserText) cl._isUserText = true;
        canvas.add(cl);
        canvas.setActiveObject(cl);
        canvas.renderAll();
        pushUndo(); updateRecipe();
        saveWorkState();   // [V36] 배관·텍스트 복사 즉시 영속화
    }});
}}

// ── [추가] 텍스트 ───────────────────────────────────────────────────
function addText() {{
    const t = new fabric.IText('내용을 입력하세요', {{
        left: CW/2 - 90, top: CH/2 - 16,
        fontSize: 28, fill: '#222222', fontFamily: 'sans-serif',
        editable: true, selectable: true,
        cornerSize: 8, hasRotatingPoint: true,
    }});
    t._isUserText = true;
    canvas.add(t);
    canvas.setActiveObject(t);
    t.enterEditing(); t.selectAll();
    canvas.renderAll();
    pushUndo();
    saveWorkState();   // [V26] 텍스트 생성 즉시 영속화
    setStatus('텍스트 추가됨 — 더블클릭으로 재편집, 우측 패널에서 크기·색상 변경.');
}}
function applyTextProp() {{
    const o = canvas.getActiveObject();
    if (!o || (o.type !== 'i-text' && o.type !== 'text' && o.type !== 'textbox')) return;
    const fs = parseInt(document.getElementById('prop-font-size').value);
    const fc = document.getElementById('prop-font-color').value;
    o.set({{ fontSize: isNaN(fs) ? o.fontSize : fs, fill: fc }});
    o.setCoords(); canvas.renderAll(); pushUndo();
    saveWorkStateDebounced();   // [V36] 텍스트 속성 조정 영속화
}}

// ── [추가] 누끼 여백 자동 자르기 (선택 이미지의 투명 테두리 제거) ──────
// 누끼는 잘 됐지만 투명 여백이 커서 확대 시 캔버스 밖으로 나가는 문제 해결.
function autoTrimSelected() {{
    const o = canvas.getActiveObject();
    if (!o || o.type !== 'image') {{ setStatus('자를 이미지를 먼저 선택하세요.'); return; }}
    const el = o._element;
    if (!el) {{ setStatus('이미지 데이터를 읽을 수 없습니다.'); return; }}
    const nw = el.naturalWidth || el.width, nh = el.naturalHeight || el.height;
    const cv = document.createElement('canvas');
    cv.width = nw; cv.height = nh;
    const cx = cv.getContext('2d');
    cx.drawImage(el, 0, 0, nw, nh);
    let data;
    try {{ data = cx.getImageData(0, 0, nw, nh).data; }}
    catch(err) {{ setStatus('이미지 분석 실패(보안 제한). 영역자르기를 사용하세요.'); return; }}
    let minX = nw, minY = nh, maxX = 0, maxY = 0, found = false;
    const A = 12;  // 알파 임계값(이 이상이면 내용으로 판정)
    for (let y = 0; y < nh; y++) {{
        for (let x = 0; x < nw; x++) {{
            if (data[(y*nw + x)*4 + 3] > A) {{
                if (x < minX) minX = x; if (x > maxX) maxX = x;
                if (y < minY) minY = y; if (y > maxY) maxY = y;
                found = true;
            }}
        }}
    }}
    if (!found) {{ setStatus('투명 여백이 없습니다(배경 미제거 이미지일 수 있음) → ⛶ 영역자르기 사용.'); return; }}
    const bw = (maxX - minX + 1), bh = (maxY - minY + 1);
    // 화면상 위치 유지: 잘린 만큼 left/top 보정
    const newLeft = o.left + (minX - (o.cropX || 0)) * o.scaleX;
    const newTop  = o.top  + (minY - (o.cropY || 0)) * o.scaleY;
    o.set({{ cropX: minX, cropY: minY, width: bw, height: bh, left: newLeft, top: newTop }});
    o.setCoords(); canvas.renderAll(); pushUndo();
    setStatus('여백 제거 완료 — 이제 확대해도 캔버스를 벗어나지 않습니다.');
}}

// ── [추가] 영역 드래그 자르기 ───────────────────────────────────────
let cropTarget = null, cropRect = null, cropStart = null;
function toggleCropMode() {{
    if (curMode === 'crop') {{ applyCrop(); return; }}  // 두 번째 클릭 → 적용
    const o = canvas.getActiveObject();
    if (!o || o.type !== 'image') {{ setStatus('자를 이미지를 먼저 선택하세요.'); return; }}
    curMode = 'crop';
    cropTarget = o;
    canvas.discardActiveObject();
    canvas.selection = false;
    canvas.forEachObject(ob => {{ ob.selectable = false; }});
    canvas.defaultCursor = 'crosshair';
    document.getElementById('btn-crop').classList.add('active');
    canvas.renderAll();
    setStatus('자를 영역을 드래그한 뒤, 다시 [⛶ 영역자르기]를 누르면 적용됩니다.');
}}
function applyCrop() {{
    document.getElementById('btn-crop').classList.remove('active');
    if (cropRect && cropTarget && cropRect.width > 3 && cropRect.height > 3) {{
        const o = cropTarget;
        // 캔버스 좌표 → 이미지 원본 픽셀 좌표로 변환 (기존 crop 누적 반영)
        const relLeft = (cropRect.left - o.left) / o.scaleX + (o.cropX || 0);
        const relTop  = (cropRect.top  - o.top ) / o.scaleY + (o.cropY || 0);
        const relW = cropRect.getScaledWidth()  / o.scaleX;
        const relH = cropRect.getScaledHeight() / o.scaleY;
        const nw = (o._element.naturalWidth || o.width), nh = (o._element.naturalHeight || o.height);
        const cX = Math.max(0, Math.round(relLeft));
        const cY = Math.max(0, Math.round(relTop));
        const cW = Math.max(4, Math.min(Math.round(relW), nw - cX));
        const cH = Math.max(4, Math.min(Math.round(relH), nh - cY));
        const newLeft = o.left + (cX - (o.cropX || 0)) * o.scaleX;
        const newTop  = o.top  + (cY - (o.cropY || 0)) * o.scaleY;
        o.set({{ cropX: cX, cropY: cY, width: cW, height: cH, left: newLeft, top: newTop }});
        o.setCoords();
        canvas.remove(cropRect);
        setStatus('선택 영역으로 잘랐습니다.');
    }} else {{
        if (cropRect) canvas.remove(cropRect);
        setStatus('자르기 취소(영역이 너무 작음).');
    }}
    cropRect = null; cropStart = null;
    const t = cropTarget; cropTarget = null;
    canvas.forEachObject(ob => {{ ob.selectable = true; }});
    canvas.selection = true;
    canvas.defaultCursor = 'default';
    curMode = 'select';
    if (t) canvas.setActiveObject(t);
    canvas.renderAll();
    pushUndo();
}}

function clearCanvas() {{ if(!confirm('캔버스의 부속을 모두 비울까요?')) return; bgImageRef = null; canvas.clear(); objRecipe={{}}; undoStack=[]; redoStack=[]; pushUndo(); updateRecipe(); clearWorkState(); setStatus('캔버스를 비웠습니다. (배경은 좌측 \\'기존 세트 이미지를 배경으로 표시\\' 체크 해제로 제거)'); }}
function removeBgOnly() {{ let removed=false; canvas.getObjects().forEach(o=>{{ if(o._isBgImage){{ canvas.remove(o); removed=true; }} }}); bgImageRef=null; canvas.renderAll(); pushUndo(); setStatus(removed ? '배경 제거됨 — 영구 적용하려면 좌측 \\'배경으로 표시\\' 체크를 해제하세요.' : '제거할 배경이 없습니다.'); }}

// ── 우클릭 컨텍스트 메뉴 ────────────────────────────────────────────
function onContextMenu(opt) {{
    opt.e.preventDefault();
    const obj = canvas.findTarget(opt.e);
    if (!obj) return;
    canvas.setActiveObject(obj);
    const menu = document.getElementById('ctx-menu');
    const rect = document.getElementById('canvas-wrap').getBoundingClientRect();
    menu.style.left = (opt.e.clientX - rect.left) + 'px';
    menu.style.top  = (opt.e.clientY - rect.top)  + 'px';
    menu.style.display = 'block';
    opt.e.stopPropagation();
}}
function ctxBringFront() {{ bringFront(); document.getElementById('ctx-menu').style.display='none'; }}
function ctxBringFwd()   {{ bringFwd();   document.getElementById('ctx-menu').style.display='none'; }}
function ctxSendBck()    {{ sendBck();    document.getElementById('ctx-menu').style.display='none'; }}
function ctxSendBack()   {{ sendBack();   document.getElementById('ctx-menu').style.display='none'; }}
function ctxDelete()     {{ deleteObj();  document.getElementById('ctx-menu').style.display='none'; }}

// ── Undo / Redo ──────────────────────────────────────────────────────
function pushUndo() {{
    const state = JSON.stringify(canvas.toJSON(['_looperCode','_looperName','_looperSpec','_objId','_isPipe','_isBgImage','_isUserText','_pendKey']));
    if (undoStack[undoStack.length-1] === state) return;
    undoStack.push(state);
    if (undoStack.length > 50) undoStack.shift();
    redoStack = [];
}}
function doUndo() {{
    if (undoStack.length <= 1) return;
    redoStack.push(undoStack.pop());
    const state = undoStack[undoStack.length-1];
    canvas.loadFromJSON(state, () => {{ canvas.renderAll(); updateRecipe(); saveWorkStateDebounced(); }});   // [V36] 언두 후 상태 영속화
}}
function doRedo() {{
    if (!redoStack.length) return;
    const state = redoStack.pop();
    undoStack.push(state);
    canvas.loadFromJSON(state, () => {{ canvas.renderAll(); updateRecipe(); saveWorkStateDebounced(); }});   // [V36] 리두 후 상태 영속화
}}

// ── 레시피 집계 ─────────────────────────────────────────────────────
function updateRecipe() {{
    const tally = {{}};
    canvas.getObjects().forEach(obj => {{
        if (obj._looperCode) {{
            const k = obj._looperCode;
            if (!tally[k]) tally[k] = {{name: obj._looperName, qty: 0}};
            tally[k].qty++;
        }}
    }});
    const box = document.getElementById('recipe-list');
    if (!Object.keys(tally).length) {{
        box.innerHTML = '캔버스에 부속 추가 시<br>자동으로 집계됩니다.';
        return;
    }}
    box.innerHTML = Object.entries(tally).map(([c,v]) => `· [${{c}}] ${{v.name}} ×${{v.qty}}`).join('<br>');
}}

// ── PNG 로컬 저장 ───────────────────────────────────────────────────
function downloadPng() {{
    const link = document.createElement('a');
    link.href = exportWhiteBgDataUrl(2);
    const base = (TARGET_SET && TARGET_SET.length) ? TARGET_SET : 'new_set';
    link.download = base + '.png';
    link.click();
    setStatus2('PNG를 내려받았습니다. 아래 "PNG 드라이브 저장"에 업로드하세요.');
}}

// ── [재편집] 캔버스 데이터(.json) 내려받기 ───────────────────────────
// 부속 위치/배관/텍스트를 그대로 담은 JSON. 나중에 편집 모드로 불러오면 복원됨.
function downloadCanvasJson() {{
    const data = JSON.stringify(canvas.toJSON(['_looperCode','_looperName','_looperSpec','_objId','_isPipe','_isUserText','_pendKey']));
    const blob = new Blob([data], {{type:'application/json'}});
    const link = document.createElement('a');
    link.href = URL.createObjectURL(blob);
    const base = (TARGET_SET && TARGET_SET.length) ? TARGET_SET : 'new_set';
    link.download = base + '.canvas.json';
    link.click();
    setTimeout(() => URL.revokeObjectURL(link.href), 1000);
    setStatus2('캔버스 데이터(.json)를 내려받았습니다. 저장 시 함께 업로드하면 재편집이 가능합니다.');
}}

// ── [원클릭 저장] 부모(Streamlit) localStorage로 PNG+캔버스데이터 전송 ──
// components.html iframe은 단방향이므로, 부모창 localStorage를 다리로 사용.
// 파이썬이 js-eval로 플래그를 읽고 → localStorage에서 데이터를 꺼내 자동 저장한다.
function sendToApp() {{
    try {{
        const png = exportWhiteBgDataUrl(2);   // 흰배경 합성 PNG dataURL
        const cjson = JSON.stringify(canvas.toJSON(['_looperCode','_looperName','_looperSpec','_objId','_isPipe','_isUserText','_pendKey']));
        const store = window.parent && window.parent.localStorage ? window.parent.localStorage : window.localStorage;
        store.setItem('LOOPER_SET_PNG', png);
        store.setItem('LOOPER_SET_JSON', cjson);
        store.setItem('LOOPER_SET_TS', String(Date.now()));   // 변경 감지용 타임스탬프
        store.setItem('LOOPER_SET_READY', '1');                // 처리 대기 플래그
        setStatus2('✅ 앱으로 전송했습니다. 아래에서 세트명·분류를 확인하고 저장을 마무리하세요.');
    }} catch (err) {{
        setStatus2('⚠ 자동 전송 실패(브라우저 보안). 아래 백업 버튼으로 다운로드 후 업로드하세요. ' + err);
    }}
}}

// ── [V14] 흰 배경 합성 PNG dataURL 생성 ──────────────────────────────
// 누끼(투명) 부속들을 흰 배경 위에 얹어 저장 → 견적서 PDF에서 깨짐 방지.
function exportWhiteBgDataUrl(mult) {{
    mult = mult || 2;
    const prevBg = canvas.backgroundColor;
    canvas.backgroundColor = '#ffffff';
    canvas.renderAll();
    const whiteUrl = canvas.toDataURL({{'format':'png','multiplier':mult}});
    canvas.backgroundColor = prevBg;
    canvas.renderAll();
    return whiteUrl;
}}

function setStatus(msg) {{ document.getElementById('status').textContent = msg; }}
function setStatus2(msg) {{ document.getElementById('status2').textContent = msg; }}

// ── 캔버스 크기 변경 ────────────────────────────────────────────────
function resizeCanvas(val) {{
    const parts = val.split(',');
    CW = parseInt(parts[0]); CH = parseInt(parts[1]);
    canvas.setWidth(CW); canvas.setHeight(CH);
    canvas.renderAll();
    zoomFit();
    setStatus(`캔버스 크기: ${{CW}}×${{CH}}`);
}}

// ── [V15] 화면 줌 (저장 품질과 무관, 표시 배율만 조정) ───────────────
// transform:scale은 레이아웃 공간을 안 줄여 스크롤바가 남으므로,
// wrapper의 실제 width/height를 배율만큼 줄이고 fabric 래퍼를 scale.
// [V16] 영역에 딱 맞는 배율 계산 (스크롤 판단 기준)
function getFitZoom() {{
    const area = document.getElementById('canvas-area');
    if (!area) return 1;
    const availW = area.clientWidth  - 24;
    const availH = area.clientHeight - 24;
    if (availW <= 0) return 1;
    let z = Math.min(availW / CW, (availH > 0 ? availH / CH : 1), 1);
    if (!isFinite(z) || z <= 0) z = 1;
    return z;
}}
function applyZoom() {{
    const wrap = document.getElementById('canvas-wrap');
    const area = document.getElementById('canvas-area');
    if (!wrap) return;
    const fc = canvas ? canvas.wrapperEl : null;
    const W = CW * zoomLevel, H = CH * zoomLevel;
    wrap.style.width  = W + 'px';
    wrap.style.height = H + 'px';
    if (fc) {{
        fc.style.transform = 'scale(' + zoomLevel + ')';
        fc.style.transformOrigin = 'top left';
    }}
    // 가로/세로 각각 넘치면 해당 방향 스크롤 표시
    if (area) {{
        const availW = area.clientWidth  - 20;
        const availH = area.clientHeight - 20;
        area.style.overflowX = (W > availW + 1) ? 'auto' : 'hidden';
        area.style.overflowY = (H > availH + 1) ? 'auto' : 'hidden';
    }}
    const zv = document.getElementById('zoom-val');
    if (zv) zv.textContent = Math.round(zoomLevel * 100) + '%';
}}
function zoomFit() {{
    zoomLevel = getFitZoom();
    applyZoom();
}}
function zoomIn()  {{ zoomLevel = Math.min(zoomLevel + 0.1, 3.0); applyZoom(); }}
function zoomOut() {{ zoomLevel = Math.max(zoomLevel - 0.1, 0.2); applyZoom(); }}
window.addEventListener('resize', zoomFit);
</script>
</body>
</html>
"""
        components.html(html_code, height=680, scrolling=False)

        # ── [원클릭 저장] 브리지: 빌더의 💾 저장 → localStorage → 여기서 수신 ──
        st.markdown("---")
        st.markdown("#### 💾 세트 이미지 + 구성 저장")

        # 빌더에서 전송된 데이터를 localStorage에서 읽어옴 (js-eval 브리지)
        bridge_png, bridge_json, bridge_ts = None, None, None
        if _HAS_JS_EVAL:
            try:
                bridge_ts = streamlit_js_eval(
                    js_expressions="window.parent.localStorage.getItem('LOOPER_SET_TS')",
                    key="get_set_ts")
            except Exception:
                bridge_ts = None

        # 새 전송이 감지되면(타임스탬프 변경) PNG/JSON 본문을 가져와 세션에 저장
        if bridge_ts and bridge_ts != st.session_state.get("_last_set_ts"):
            try:
                bridge_png = streamlit_js_eval(
                    js_expressions="window.parent.localStorage.getItem('LOOPER_SET_PNG')",
                    key=f"get_set_png_{bridge_ts}")
                bridge_json = streamlit_js_eval(
                    js_expressions="window.parent.localStorage.getItem('LOOPER_SET_JSON')",
                    key=f"get_set_json_{bridge_ts}")
                if bridge_png:
                    st.session_state["_bridge_png"] = bridge_png
                    st.session_state["_bridge_json"] = bridge_json or ""
                    st.session_state["_last_set_ts"] = bridge_ts
            except Exception:
                pass

        has_bridge = bool(st.session_state.get("_bridge_png"))
        if has_bridge:
            st.session_state["_bridge_retry"] = 0   # [V30] 감지 성공 → 재시도 카운터 리셋
            st.success("✅ 빌더에서 전송된 이미지가 준비됐습니다. 아래에서 세트명·분류만 확인하고 저장하세요.")
        else:
            st.warning("빌더에서 **💾 저장 (이미지+구성 자동 등록)** 을 누른 뒤, 이 자리가 초록색 **'전송된 이미지가 준비됐습니다'** 로 바뀌어야 저장됩니다.\n\n바로 안 바뀌면 아래 **🔄 전송 확인**을 한 번 누르세요. (전송 감지는 약간의 지연이 있을 수 있습니다.)")
            if _HAS_JS_EVAL:
                st.button("🔄 전송 확인 / 새로고침", key="bridge_refresh", use_container_width=True,
                          help="빌더에서 '💾 저장'을 눌렀는데 위가 초록색으로 안 바뀌면 클릭하세요.")

        # 현재 구성 집계(레시피) 미리보기
        cur_recipe = {c: info["qty"] for c, info in st.session_state.builder_recipe.items()}
        if cur_recipe:
            _rl = ", ".join([f"[{c}]×{q}" for c, q in cur_recipe.items()])
            st.caption(f"📋 저장될 구성: {_rl}")
        else:
            st.caption("📋 저장될 구성: (비어 있음 — 부속을 추가하면 자동 집계됩니다)")

        with st.form("builder_save_form"):
            # 백업 업로더 — 브리지 전송이 실패한 경우에만 사용 (평소엔 접어둠)
            with st.expander("⬆️ 자동 전송이 안 될 때만: 파일 직접 업로드 (백업)", expanded=not has_bridge):
                uploaded_png = st.file_uploader("완성 PNG 파일 업로드", type=["png"], key="builder_upload_png")
                uploaded_json = st.file_uploader(
                    "캔버스 데이터(.json) 업로드 — 재편집용", type=["json"], key="builder_upload_json")

            # 기존 세트의 레시피/설명/분류 조회 (편집 모드 비교·프리필용)
            _existing_recipe, _existing_desc, _existing_cat, _existing_sc = {}, "", "", ""
            _existing_meta = {}  # [V23] Phase 1B — 편집 시 기존 메타데이터 프리필용
            if builder_mode != "✨ 새 세트 만들기" and target_set_name:
                for _c, _items in st.session_state.db.get("sets", {}).items():
                    if target_set_name in _items:
                        _ti = _items[target_set_name]
                        _existing_recipe = {str(k): v for k, v in _ti.get("recipe", {}).items()}
                        _existing_desc = _ti.get("desc", "")
                        _existing_cat = _c
                        _existing_sc = _ti.get("sub_cat") or "-"
                        _existing_meta = {k: _ti.get(k, "") for k in ("gauge", "func_type", "install_phase", "head_model", "install_env", "set_grade", "gov_registered")}
                        break

            # 분류·하위분류 옵션 (신규·편집 공통 — 편집 시 기존값이 기본 선택)
            _CATS = ["주배관세트", "가지관세트", "살수세트", "기타자재"]
            if _existing_cat and _existing_cat not in _CATS:
                _CATS = [_existing_cat] + _CATS
            _SCS = ["50mm", "40mm", "기타", "-"]
            if _existing_sc and _existing_sc not in _SCS:
                _SCS = [_existing_sc] + _SCS

            if builder_mode == "✨ 새 세트 만들기":
                st.caption("✨ 새 세트 모드입니다 — 기존 세트를 고치려면 상단 '빌더 작업 모드'에서 **기존 세트 이미지 편집**을 선택하세요. (모드를 바꿔도 캔버스 부속·배치는 유지됩니다)")
                new_sname = st.text_input("세트명 (예: [LHC]1-1-5050)", key="builder_new_name2")
            else:
                new_sname = target_set_name
                st.info(f"편집 대상 세트: **{target_set_name}**  ·  현재 분류: {_existing_cat or '미지정'}")

            cc1, cc2 = st.columns(2)
            with cc1:
                _cat_idx = _CATS.index(_existing_cat) if _existing_cat in _CATS else 0
                new_scat = st.selectbox("분류 (주배관/가지관 등 — 변경 가능)", _CATS, index=_cat_idx, key="builder_cat_sel")
            with cc2:
                _sc_idx = _SCS.index(_existing_sc) if _existing_sc in _SCS else (len(_SCS) - 1)
                new_ssc = st.selectbox("하위분류", _SCS, index=_sc_idx, key="builder_sc_sel")

            # 세트 설명 (견적서 툴팁용)
            new_sdesc = st.text_area(
                "세트 설명 (선택)", value=_existing_desc, height=70, key="builder_set_desc",
                help="견적서에서 세트 이미지 위에 마우스를 올리면 구성품 목록 아래에 함께 표시됩니다.",
                placeholder="예: 50mm 주배관 표준 세트. 무절삭 시공으로 누수 위험 최소화.")

            # [V23, 2026-06-28] Track A-2 Phase 1B — 세트 메타데이터 (선택, 세트명에서 자동 추론)
            _md = infer_set_meta(new_sname, new_scat, (new_ssc if new_ssc != "-" else ""))
            def _mget(key, fb):  # 편집 기존값 우선 → 추론 → fb. [V24] 숫자형 방어
                raw = _existing_meta.get(key) if isinstance(_existing_meta, dict) else None
                v = str(raw).strip() if raw not in (None, "") else ""
                return v or (_md.get(key) if isinstance(_md, dict) else "") or fb
            def _midx(opts, val):
                return opts.index(val) if val in opts else 0
            with st.expander("🏷️ 세트 메타데이터 (분류·검색·관급용 — 선택, 자동 추론됨)", expanded=False):
                _mc1, _mc2, _mc3 = st.columns(3)
                with _mc1:
                    meta_gauge = st.text_input("관경(mm)", value=_mget("gauge", ""), help="예: 50 또는 50,25")
                    meta_env = st.selectbox("설치환경", META_ENVS, index=_midx(META_ENVS, _mget("install_env", "노지")))
                with _mc2:
                    meta_phase = st.selectbox("설치단계", META_PHASES, index=_midx(META_PHASES, _mget("install_phase", "")))
                    meta_grade = st.selectbox("세트등급", META_GRADES, index=_midx(META_GRADES, ((_existing_meta.get("set_grade") if _existing_meta else "") or "S")))
                with _mc3:
                    meta_func = st.selectbox("기능타입", META_FUNC_TYPES, index=_midx(META_FUNC_TYPES, _mget("func_type", "")))
                    meta_gov = st.selectbox("관급등록여부", ["N", "Y"], index=_midx(["N", "Y"], ((_existing_meta.get("gov_registered") if _existing_meta else "") or "N")))
                meta_head = st.selectbox("헤드모델", META_HEADS, index=_midx(META_HEADS, _mget("head_model", "(없음)")))
                _hf, _hp, _hr = META_HEAD_PERF.get(meta_head, ("", "", ""))
                if meta_head != "(없음)":
                    st.caption(f"↳ 헤드 사양 자동 반영: 유량 {_hf}L/h · 권장수압 {_hp}bar · 최대반경 {_hr}m")

            # [요청2] 저장 동작 미리보기 — 캔버스 집계 vs 기존 구성 자동 비교
            _cur_norm = {str(k): v for k, v in cur_recipe.items()}
            recipe_changed = (_cur_norm != _existing_recipe)
            if builder_mode == "✨ 새 세트 만들기":
                st.markdown(f"**저장 시:** 신규 세트 `{new_sname or '(이름 미입력)'}` 가 구성 **{len(cur_recipe)}종**과 함께 새로 생성됩니다.")
            else:
                if not cur_recipe:
                    st.markdown("**저장 시:** 구성 집계가 비어 있어 **이미지·설명만 교체**됩니다. (기존 구성 유지)")
                elif recipe_changed:
                    _old = ", ".join([f"[{c}]×{q}" for c, q in _existing_recipe.items()]) or "(없음)"
                    _new = ", ".join([f"[{c}]×{q}" for c, q in _cur_norm.items()])
                    st.warning(f"**구성이 기존과 다릅니다.** 저장 시 이미지 교체 + 구성이 캔버스대로 갱신됩니다.\n\n- 기존: {_old}\n- 변경: {_new}")
                else:
                    st.markdown("**저장 시:** 구성이 기존과 동일 → **이미지·설명만 교체**됩니다.")

            # [V38] 새세트 모드에서 기존 세트명과 일치하면 미리 경고 (저장은 업데이트로 안전 처리됨)
            if builder_mode == "✨ 새 세트 만들기" and new_sname and any(
                    new_sname in _its for _its in st.session_state.db.get("sets", {}).values()):
                st.warning(f"⚠ '{new_sname}' 는 이미 등록된 세트입니다 — 저장 시 새로 만들지 않고 **기존 세트 업데이트**로 처리됩니다(메타데이터·기존 필드 보존).")

            submitted = st.form_submit_button("💾 세트로 저장/등록", type="primary", use_container_width=True)

            if submitted:
                # PNG 소스 결정: 브리지(자동) 우선, 없으면 업로더(백업)
                png_bytes, json_text = None, None
                if st.session_state.get("_bridge_png"):
                    try:
                        b64 = st.session_state["_bridge_png"].split(",", 1)[-1]
                        png_bytes = base64.b64decode(b64)
                        json_text = st.session_state.get("_bridge_json") or None
                    except Exception:
                        png_bytes = None
                if png_bytes is None and uploaded_png is not None:
                    png_bytes = uploaded_png.getvalue()
                    json_text = uploaded_json.getvalue().decode("utf-8") if uploaded_json is not None else None

                if png_bytes is None:
                    # [V30] 브리지 전송이 아직 감지 안 됨(js_eval 비동기 지연). 백업 업로드도 없으면
                    #  빨간 에러 대신 '확인 중' 안내 + 자동 재감지 리런으로 초록 상태를 앞당김.
                    #  (제출 1회당 1리런; submitted는 클릭한 run에서만 True라 무한루프 없음. has_bridge 시 카운터 리셋.)
                    _br = st.session_state.get("_bridge_retry", 0)
                    if _HAS_JS_EVAL and uploaded_png is None and _br < 4:
                        st.session_state["_bridge_retry"] = _br + 1
                        st.info("⏳ 전송 확인 중… 위 안내가 초록색 '준비됐습니다'로 바뀌면 **[세트로 저장/등록]**을 한 번 더 눌러주세요.")
                        time.sleep(0.7)
                        st.rerun()
                    else:
                        st.error("아직 전송이 확인되지 않았습니다. 빌더에서 **💾 저장**을 누른 뒤, 아래 안내가 **초록색**으로 바뀐 것을 확인하고 다시 시도하세요. (안 바뀌면 **🔄 전송 확인** 클릭, 그래도 안 되면 백업 업로드 사용)")
                elif not new_sname:
                    st.error("세트명을 입력/선택하세요.")
                else:
                    with st.spinner("저장 중..."):
                        fname = f"{new_sname}.png"
                        # 기존 동일 파일명 정리(중복 방지)
                        # [V36-실측] 서비스계정=공유드라이브 '콘텐츠 관리자' → files().delete(영구삭제)는 404로 항상 실패(관리자 전용).
                        #  → update(trashed=True) 휴지통 이동으로 교체(canTrash=True 실측 확인). 옛 PNG·canvas.json 누적 방지.
                        try:
                            fmap = get_drive_file_map_deep()
                            for _old_key in (new_sname, f"{new_sname}.canvas"):
                                _old_id = fmap.get(_old_key)
                                if _old_id:
                                    _get_ds().files().update(fileId=_old_id, body={"trashed": True}, supportsAllDrives=True).execute(num_retries=3)
                        except Exception:
                            pass
                        new_id = upload_bytes_to_drive(png_bytes, fname, "image/png")
                        # 캔버스 데이터(.json) 업로드 → 재편집용 (브리지/업로더 공통)
                        canvas_id = None
                        if json_text:
                            try:
                                canvas_id = upload_bytes_to_drive(json_text.encode("utf-8"), f"{new_sname}.canvas.json", "application/json")
                            except Exception:
                                canvas_id = None

                        # [작업 손실 방지] 이미지 업로드가 실패(네트워크·소켓끊김 등)해도
                        #  구성·분류·설명은 시트에 저장한다. 이미지 참조는 파일명으로 기록 →
                        #  나중에 같은 이름 PNG를 폴더에 올리면 코드/이름으로 자동 연결된다.
                        upload_failed = not new_id
                        image_ref = new_id or fname
                        if upload_failed:
                            # [V32] 공유드라이브 전환 완료 상태 → 대부분 일시적 네트워크(Broken pipe) 문제. 재시도 우선 안내.
                            st.warning(
                                f"⚠️ 이미지 자동 업로드가 일시적으로 실패했습니다(대개 네트워크 끊김). "
                                f"**구성·분류·설명은 저장**됐습니다.\n\n"
                                f"👉 **먼저 [세트로 저장/등록]을 한 번 더 눌러보세요** — 새 연결로 대개 성공합니다.\n\n"
                                f"그래도 안 되면(백업 경로):\n"
                                f"1. 빌더에서 **📥 PNG만 내려받기** → 파일명을 **`{fname}`** 로 변경\n"
                                f"2. 구글 드라이브 세트 이미지 폴더에 그 PNG 직접 업로드 → 견적서에서 코드/이름으로 자동 연결")

                        get_drive_file_map.clear()
                        get_drive_file_map_deep.clear()
                        try: download_text_from_drive.clear()
                        except Exception: pass

                        sc_val = new_ssc if new_ssc != "-" else None
                        # [V38] 업서트 방어: 신규 모드라도 같은 이름의 세트가 이미 있으면 아래 '기존 세트 변경'
                        #  경로로 처리 — 모드 혼선 시 기존 세트의 메타데이터·구성·캔버스가 통째로 초기화되는 사고 차단.
                        _name_exists = any(new_sname in _its for _its in st.session_state.db.get("sets", {}).values())
                        if builder_mode == "✨ 새 세트 만들기" and not _name_exists:
                            # ㄴ. 신규 세트 생성 완료
                            if new_scat not in st.session_state.db["sets"]:
                                st.session_state.db["sets"][new_scat] = {}
                            st.session_state.db["sets"][new_scat][new_sname] = {
                                "recipe": _cur_norm,
                                "image": image_ref, "sub_cat": sc_val,
                                "desc": new_sdesc.strip(),
                                "canvas": canvas_id or "",
                                # [V23] Phase 1B — 메타데이터 수집
                                "gauge": meta_gauge.strip(), "func_type": meta_func, "install_phase": meta_phase,
                                "head_model": meta_head, "flow_lh": _hf, "pressure_bar": _hp, "spray_radius_m": _hr,
                                "install_env": meta_env, "set_grade": meta_grade, "gov_registered": meta_gov,
                            }
                            save_sets_to_sheet(st.session_state.db["sets"])
                            if not upload_failed:
                                msg = f"✅ 신규 세트 '{new_sname}' 생성 완료! (분류: {new_scat}, 구성 {len(cur_recipe)}종"
                                msg += ", 재편집 데이터 포함)" if canvas_id else ")"
                                st.success(msg)
                        else:
                            # ㄱ. 기존 세트 변경: 분류가 바뀌면 해당 분류로 '이동', 구성은 캔버스대로 갱신
                            old_info = None
                            for cat_key in list(st.session_state.db["sets"].keys()):
                                if new_sname in st.session_state.db["sets"][cat_key]:
                                    old_info = st.session_state.db["sets"][cat_key].pop(new_sname)
                                    break
                            if old_info is None:
                                old_info = {"recipe": {}, "image": "", "sub_cat": None, "desc": "", "canvas": ""}
                            old_info["image"] = image_ref
                            # [V38] 새세트 모드發 업서트에서 빈 설명이 기존 설명을 지우지 않게
                            if new_sdesc.strip() or builder_mode != "✨ 새 세트 만들기":
                                old_info["desc"] = new_sdesc.strip()
                            old_info["sub_cat"] = sc_val
                            if canvas_id:
                                old_info["canvas"] = canvas_id
                            if cur_recipe and recipe_changed:
                                old_info["recipe"] = _cur_norm
                            # [V23] Phase 1B — 메타데이터 갱신 (기존 dict의 나머지 키는 보존)
                            old_info["gauge"] = meta_gauge.strip(); old_info["func_type"] = meta_func
                            old_info["install_phase"] = meta_phase; old_info["head_model"] = meta_head
                            old_info["flow_lh"] = _hf; old_info["pressure_bar"] = _hp; old_info["spray_radius_m"] = _hr
                            old_info["install_env"] = meta_env; old_info["set_grade"] = meta_grade
                            old_info["gov_registered"] = meta_gov
                            if new_scat not in st.session_state.db["sets"]:
                                st.session_state.db["sets"][new_scat] = {}
                            st.session_state.db["sets"][new_scat][new_sname] = old_info
                            save_sets_to_sheet(st.session_state.db["sets"])
                            if not upload_failed:
                                _moved = (_existing_cat and _existing_cat != new_scat)
                                _parts = []
                                if _moved: _parts.append(f"분류 {_existing_cat}→{new_scat} 이동")
                                if cur_recipe and recipe_changed: _parts.append(f"구성 갱신 {len(cur_recipe)}종")
                                _parts.append("이미지·설명 교체")
                                st.success("✅ '" + new_sname + "' 저장 완료! (" + ", ".join(_parts) + ")")

                        # 성공 시에만 브리지·집계 정리 + 새로고침. (실패 시엔 안내가 사라지지 않도록 유지)
                        if not upload_failed:
                            if _HAS_JS_EVAL:
                                try:
                                    streamlit_js_eval(
                                        js_expressions="window.parent.localStorage.removeItem('LOOPER_SET_PNG');window.parent.localStorage.removeItem('LOOPER_SET_JSON');window.parent.localStorage.removeItem('LOOPER_SET_TS');window.parent.localStorage.removeItem('LOOPER_SET_READY');window.parent.localStorage.removeItem('LOOPER_WORK');window.parent.localStorage.removeItem('LOOPER_WORK_PARTS');",
                                        key=f"clear_bridge_{int(time.time())}")
                                except Exception:
                                    pass
                            for _k in ("_bridge_png", "_bridge_json"):
                                st.session_state.pop(_k, None)
                            st.session_state._img_cache = {}
                            st.session_state.builder_recipe = {}
                            st.session_state.builder_canvas_items = []
                            st.session_state.db = load_data_from_sheet()
                            time.sleep(1)
                            st.rerun()


# ==========================================
# 2. PDF 및 Excel 생성 엔진 → `looperget/quote_docs.py` 분리 [V72]
# ==========================================
# 원본 L3852-5048(1,197줄)을 기계적 추출. 로직 무변경.
from looperget import quote_docs as _qd
_qd.bind(FONT_REGULAR=FONT_REGULAR, FONT_BOLD=FONT_BOLD,
         get_drive_file_map_deep=get_drive_file_map_deep,
         get_best_image_id=get_best_image_id,
         download_image_by_id=download_image_by_id)
from looperget.quote_docs import *
# ==========================================
# 3. 메인 로직 (DB Init & 2FA Lockout)
# ==========================================
if "db" not in st.session_state:
    with st.spinner("DB 연동 중..."): 
        st.session_state.db = load_data_from_sheet()
gc, drive_service = refresh_services()   # [V108] 원본과 같이 매 실행 서비스 확인(캐시 TTL 재인증)
login_gate("PRO MANAGER")   # [V108] 로그인 화면 → common/auth.py (아쿠나리스 빌더와 같은 화면)

# --- Authenticated App Start ---

if "quote_step" not in st.session_state: st.session_state.quote_step = 1
if "quote_items" not in st.session_state: st.session_state.quote_items = {}
if "services" not in st.session_state: st.session_state.services = []
if "pipe_cart" not in st.session_state: st.session_state.pipe_cart = [] 
if "set_cart" not in st.session_state: st.session_state.set_cart = [] 
if "temp_set_recipe" not in st.session_state: st.session_state.temp_set_recipe = {}
if "current_quote_name" not in st.session_state: st.session_state.current_quote_name = ""
if "buyer_info" not in st.session_state: st.session_state.buyer_info = {"manager": "", "phone": "", "addr": "", "serial": "", "recipient": "", "ref": "", "pay_cond": "/", "valid_period": "견적 후 15일 이내"}
if "auth_admin" not in st.session_state: st.session_state.auth_admin = False
if "auth_price" not in st.session_state: st.session_state.auth_price = False
if "final_edit_df" not in st.session_state: st.session_state.final_edit_df = None
if "step3_ready" not in st.session_state: st.session_state.step3_ready = False

if "custom_prices" not in st.session_state: st.session_state.custom_prices = []
# ── [V11] 통합 앱 신규 세션 변수 ──
if "app_lang" not in st.session_state: st.session_state.app_lang = "KR"
if "exchange_rate" not in st.session_state: st.session_state.exchange_rate = 10.0
if "pending_jp_sync" not in st.session_state: st.session_state.pending_jp_sync = False

if "files_ready" not in st.session_state: st.session_state.files_ready = False
if "gen_pdf" not in st.session_state: st.session_state.gen_pdf = None
if "gen_excel" not in st.session_state: st.session_state.gen_excel = None
if "gen_comp_pdf" not in st.session_state: st.session_state.gen_comp_pdf = None
if "gen_comp_excel" not in st.session_state: st.session_state.gen_comp_excel = None

if "ui_state" not in st.session_state:
    st.session_state.ui_state = {
        "form_type": "기본 양식",
        "print_mode": "개별 품목 나열 (기존)",
        "vat_mode": "포함 (기본)",
        "sel": ["소비자가"]
    }

if "quote_remarks" not in st.session_state: 
    st.session_state.quote_remarks = "1. 견적 유효기간: 견적일로부터 15일 이내\n2. 출고: 결재 완료 후 즉시 또는 7일 이내"

render_brand_header("프로 매니저")

# ── V12 글로벌 CSS (카드 + 툴팁) ─────────────────────────────────────
st.markdown("""
<style>
/* 세트 카드 래퍼 */
.set-card-wrap {
    position: relative;
    display: block;
    margin-bottom: 2px;
    border-radius: 6px;
    overflow: visible;
    cursor: default;
}
.set-card-wrap img {
    width: 100%;
    border-radius: 6px 6px 0 0;
    display: block;
}
/* 툴팁 — 호버 시 위에 말풍선 */
.set-card-tooltip {
    display: none;
    position: absolute;
    bottom: calc(100% + 6px);
    left: 50%;
    transform: translateX(-50%);
    background: rgba(30,30,50,0.97);
    color: #e0e0e0;
    font-size: 11px;
    line-height: 1.7;
    padding: 6px 10px;
    border-radius: 6px;
    border: 1px solid #444;
    white-space: normal;
    max-width: 240px;
    width: max-content;
    text-align: left;
    z-index: 9999;
    box-shadow: 0 4px 14px rgba(0,0,0,.6);
    pointer-events: none;
}
.set-card-desc {
    margin-top: 5px;
    padding-top: 5px;
    border-top: 1px solid #555;
    color: #ffd479;
    font-size: 10.5px;
    line-height: 1.5;
    white-space: normal;
}
.set-card-tooltip::after {
    content: '';
    position: absolute;
    top: 100%;
    left: 50%;
    transform: translateX(-50%);
    border: 6px solid transparent;
    border-top-color: rgba(30,30,50,0.97);
}
.set-card-wrap:hover .set-card-tooltip {
    display: block;
}
</style>
""", unsafe_allow_html=True)

# ── [V11] JP 모드 진입 시 jp_products 병합 로드 ──────────────────
if st.session_state.app_lang == "JP":
    if "jp_products_loaded" not in st.session_state or not st.session_state.get("jp_products_loaded"):
        st.session_state.db["jp_products"] = load_jp_merged_products(
            st.session_state.db["products"],
            st.session_state.exchange_rate
        )
        st.session_state.jp_products_loaded = True
else:
    st.session_state.jp_products_loaded = False

with st.sidebar:
    st.header("🗂️ 견적 보관함")
    q_name = st.text_input("현장명 (저장용)", value=st.session_state.current_quote_name)
    
    # [V28] 3열 압착 → 2열+전폭 (좁은 사이드바에서 버튼 글자 세로 꺾임 방지)
    col_s1, col_s2 = st.columns(2)
    with col_s1: btn_save_temp = st.button("💾 임시저장", use_container_width=True)
    with col_s2: btn_save_off = st.button("✅ 정식저장", use_container_width=True)
    btn_init = st.button("✨ 견적 초기화", use_container_width=True)
    
    if btn_save_temp or btn_save_off:
        save_type = "정식" if btn_save_off else "임시"
        if not q_name:
            st.error("현장명을 입력해주세요.")
        else:
            timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            current_custom_prices = st.session_state.final_edit_df.to_dict('records') if st.session_state.final_edit_df is not None else []
            
            form_type_val = st.session_state.get("step3_form_type", st.session_state.ui_state.get("form_type", "기본 양식"))
            print_mode_val = st.session_state.get("step3_print_mode", st.session_state.ui_state.get("print_mode", "개별 품목 나열 (기존)"))
            vat_mode_val = st.session_state.get("step3_vat_mode", st.session_state.ui_state.get("vat_mode", "포함 (기본)"))
            
            if form_type_val == "기본 양식":
                sel_val = st.session_state.get("step3_sel_basic", st.session_state.ui_state.get("sel", ["소비자가"]))
            else:
                sel_val = st.session_state.get("step3_sel_profit", st.session_state.ui_state.get("sel", ["소비자가"]))

            ui_state_to_save = {
                "form_type": form_type_val,
                "print_mode": print_mode_val,
                "vat_mode": vat_mode_val,
                "sel": sel_val
            }

            save_data = {
                "items": st.session_state.quote_items,
                "services": st.session_state.services,
                "pipe_cart": st.session_state.pipe_cart,
                "set_cart": st.session_state.set_cart,
                "step": st.session_state.quote_step,
                "buyer": st.session_state.buyer_info,
                "remarks": st.session_state.quote_remarks,
                "custom_prices": current_custom_prices,
                "ui_state": ui_state_to_save,
                "save_type": save_type
            }
            
            est_total = 0
            pdb = {str(p.get("code")).strip(): p for p in st.session_state.db["products"]}
            for code, qty in st.session_state.quote_items.items():
                prod = pdb.get(str(code).strip())
                if prod:
                    est_total += int(prod.get("price_cons", 0) or 0) * int(qty)
            
            json_str = json.dumps(save_data, ensure_ascii=False)
            
            if save_quote_to_sheet(timestamp, q_name, st.session_state.buyer_info.get("manager", ""), est_total, json_str):
                st.session_state.db = load_data_from_sheet()
                st.session_state.current_quote_name = q_name
                st.success(f"구글 시트에 '{save_type}'로 저장되었습니다.")
            else:
                st.error("저장 실패 (네트워크 오류)")

    if btn_init:
        st.session_state.quote_items = {}; st.session_state.services = []; st.session_state.pipe_cart = []; st.session_state.set_cart = []; st.session_state.quote_step = 1
        st.session_state.current_quote_name = ""; st.session_state.buyer_info = {"manager": "", "phone": "", "addr": "", "serial": "", "recipient": "", "ref": "", "pay_cond": "/", "valid_period": "견적 후 15일 이내"}; st.session_state.step3_ready=False; st.session_state.files_ready = False
        st.session_state.quote_remarks = "1. 견적 유효기간: 견적일로부터 15일 이내\n2. 출고: 결재 완료 후 즉시 또는 7일 이내"
        st.session_state.custom_prices = []
        st.session_state._img_cache = {}  # V12: 이미지 캐시 초기화
        st.session_state.ui_state = {
            "form_type": "기본 양식",
            "print_mode": "개별 품목 나열 (기존)",
            "vat_mode": "포함 (기본)",
            "sel": ["소비자가"]
        }
        st.session_state.last_sel = []
        for k in ["step3_form_type", "step3_print_mode", "step3_vat_mode", "step3_sel_basic", "step3_sel_profit"]:
            if k in st.session_state:
                del st.session_state[k]
        st.rerun()
        
    st.divider()
    
    # ── [V11] KR / JP 언어 토글 ──────────────────────────────────
    st.markdown("**🌐 앱 모드 선택**")
    col_lang1, col_lang2 = st.columns(2)
    with col_lang1:
        kr_type = "primary" if st.session_state.app_lang == "KR" else "secondary"
        if st.button("🇰🇷 한국용", use_container_width=True, type=kr_type, key="btn_lang_kr"):
            st.session_state.app_lang = "KR"
            st.session_state.jp_products_loaded = False
            st.rerun()
    with col_lang2:
        jp_type = "primary" if st.session_state.app_lang == "JP" else "secondary"
        if st.button("🇯🇵 일본용", use_container_width=True, type=jp_type, key="btn_lang_jp"):
            st.session_state.app_lang = "JP"
            st.session_state.jp_products_loaded = False
            st.rerun()

    if st.session_state.app_lang == "JP":
        new_rate = st.number_input(
            "환율 설정 (₩/¥)", value=st.session_state.exchange_rate,
            step=0.1, min_value=1.0, max_value=50.0, key="sidebar_exchange_rate"
        )
        if new_rate != st.session_state.exchange_rate:
            st.session_state.exchange_rate = new_rate
            st.session_state.jp_products_loaded = False
            st.rerun()

    st.divider()

    if st.session_state.app_lang == "KR":
        # [V48] 권한 필터: 계정 로그인 시 권한 있는 모드만 노출 (공용 로그인 = 전체, 기존 동작)
        _mode_opts = [m for m, p in [("견적 작성", "quote"), ("🗺️ 설계(P3)", "quote"),
                                     ("관리자 모드", "admin"), ("🇯🇵 일본 수출 분석", "jp")] if aq_can(p)]
        if not _mode_opts: _mode_opts = ["견적 작성"]
        if st.session_state.get("main_sidebar_mode") not in _mode_opts:
            st.session_state["main_sidebar_mode"] = _mode_opts[0]
        mode = st.radio("모드", _mode_opts, key="main_sidebar_mode")  # [V41] 아쿠나리스 추가
    else:
        mode = st.radio("モード", ["見積作成", "管理者モード"], key="main_sidebar_mode")

    render_app_switch("promanager")   # [V108] 🏪 아쿠나리스는 별도 앱 — 주소 = secrets AQUNARIS_URL
    kr_quotes = st.session_state.db.get("kr_quotes", [])
    if kr_quotes:
        df_kr = pd.DataFrame(kr_quotes).iloc[::-1]
        
        def format_quote_label(i):
            r = df_kr.iloc[i]
            d_json_str = str(r.get("데이터JSON", "{}"))
            try: 
                d_json = json.loads(d_json_str)
                s_type = d_json.get("save_type", "임시")
            except: s_type = "임시"
            return f"[{r.get('날짜','')}] [{s_type}] {r.get('현장명','')} ({r.get('담당자','')})"
            
        sel_idx = st.selectbox("불러오기 (구글 시트)", range(len(df_kr)), format_func=format_quote_label)
        
        btn_load = st.button("📂 불러오기", use_container_width=True)
        c_l2, c_l3 = st.columns(2)
        with c_l2: btn_copy = st.button("📝 복사/수정", use_container_width=True)
        with c_l3: btn_del = st.button("🗑️ 삭제", use_container_width=True)
        
        if btn_load or btn_copy:
            try:
                target_row = df_kr.iloc[sel_idx]
                json_str = target_row.get("데이터JSON", "{}")
                d = json.loads(json_str)
                
                st.session_state.quote_items = d.get("items", {})
                st.session_state.services = d.get("services", [])
                st.session_state.pipe_cart = d.get("pipe_cart", [])
                st.session_state.set_cart = d.get("set_cart", [])
                st.session_state.quote_step = d.get("step", 2)
                st.session_state.buyer_info = d.get("buyer", {"manager": "", "phone": "", "addr": ""})
                st.session_state.quote_remarks = d.get("remarks", "1. 견적 유효기간: 견적일로부터 15일 이내\n2. 출고: 결재 완료 후 즉시 또는 7일 이내")
                st.session_state.custom_prices = d.get("custom_prices", [])
                
                st.session_state.ui_state = d.get("ui_state", {
                    "form_type": "기본 양식",
                    "print_mode": "개별 품목 나열 (기존)",
                    "vat_mode": "포함 (기본)",
                    "sel": ["소비자가"]
                })
                st.session_state.last_sel = st.session_state.ui_state.get("sel", ["소비자가"])
                
                for k in ["step3_form_type", "step3_print_mode", "step3_vat_mode", "step3_sel_basic", "step3_sel_profit"]:
                    if k in st.session_state:
                        del st.session_state[k]

                if btn_copy:
                    st.session_state.quote_step = 1
                    st.session_state.current_quote_name = ""
                    st.success("데이터를 복사하여 새로운 견적을 시작합니다!")
                else:
                    st.session_state.current_quote_name = target_row.get("현장명", "")
                    st.success(f"'{st.session_state.current_quote_name}' 불러오기 완료!")
                    
                st.session_state.step3_ready = False
                st.session_state.files_ready = False
                time.sleep(0.5)
                st.rerun()
            except Exception as e:
                st.error(f"불러오기 실패: {e}")
                
        if btn_del:
            try:
                real_idx = len(kr_quotes) - sel_idx - 1
                kr_quotes.pop(real_idx)
                sh = gc.open(SHEET_NAME)
                ws_kr = sh.worksheet("Quotes_KR")
                ws_kr.clear()
                if kr_quotes:
                    header = list(kr_quotes[0].keys())
                    rows = [header] + [[str(r.get(k, "")) for k in header] for r in kr_quotes]
                    ws_kr.update(rows)
                else:
                    ws_kr.update([['날짜', '현장명', '담당자', '총액', '데이터JSON']])
                st.session_state.db = load_data_from_sheet()
                st.success("삭제되었습니다.")
                time.sleep(0.5)
                st.rerun()
            except Exception as e:
                st.error(f"삭제 실패: {e}")
    else:
        st.info("저장된 견적이 없습니다.")
        
    st.divider()

# [V79] 「설계(P3)」 ③ 작도 결과 JSON 견본 — 화면에 그대로 보여 준다
# [V87] 지도가 **본 자리를 브라우저 안에서** 기억한다(#66).
#   🔴 `center`·`zoom` 을 파이썬으로 되받으면 **확대·이동할 때마다 다시 그려져** 화면이 깜빡이고
#      그리던 것이 끊긴다(대표 실사용 2026-09-07). 그래서 서버를 타지 않고 sessionStorage 에 둔다.
#      `__NONCE__` 는 **파이썬이 일부러 자리를 옮겼을 때**만 바뀐다 — 그때는 저장분을 버린다.
P3_VIEW_JS = """
{% macro script(this, kwargs) %}
(function(){
  var map = {{this._parent.get_name()}};
  var K = 'p3_view_v1', N = '__NONCE__';
  try {
    var v = JSON.parse(sessionStorage.getItem(K) || 'null');
    if (v && v.n === N && v.z) { map.setView([v.lat, v.lng], v.z, {animate: false}); }
  } catch (e) {}
  function save(){
    try {
      var c = map.getCenter();
      sessionStorage.setItem(K, JSON.stringify({lat: c.lat, lng: c.lng, z: map.getZoom(), n: N}));
    } catch (e) {}
  }
  map.on('moveend', save);
  map.on('zoomend', save);
})();
{% endmacro %}
"""

# [V86] 지도 왼쪽 그리기 단추를 **한국어로** 바꾼다(#65).
#   🔴 Leaflet.Draw 는 컨트롤을 만들 때 `L.drawLocal` 을 읽는다 — 그래서 이 조각은
#      **Draw 보다 먼저** 지도에 붙여야 한다. 순서가 바뀌면 영어 그대로 나온다.
P3_DRAW_LOCALE_JS = """
{% macro script(this, kwargs) %}
try {
  L.drawLocal.draw.toolbar.buttons.marker   = '\uae09\uc218\uc6d0 \ucc0d\uae30 (\ubb3c\ud0f1\ud06c\u00b7\ud38c\ud504)';
  L.drawLocal.draw.handlers.marker.tooltip.start = '\uc9c0\ub3c4\ub97c \ub20c\ub7ec \uae09\uc218\uc6d0\uc744 \ucc0d\uc2b5\ub2c8\ub2e4';
  L.drawLocal.draw.toolbar.buttons.polyline = '\uc8fc\ubc30\uad00 \uadf8\ub9ac\uae30 (\uc120)';
  L.drawLocal.draw.toolbar.buttons.polygon  = '\ubc2d \uadf8\ub9ac\uae30 (\uba74)';
  L.drawLocal.draw.toolbar.actions.title = '\uadf8\ub9ac\uae30 \ucde8\uc18c';
  L.drawLocal.draw.toolbar.actions.text  = '\ucde8\uc18c';
  L.drawLocal.draw.toolbar.finish.title = '\uadf8\ub9ac\uae30 \ub05d\ub0b4\uae30';
  L.drawLocal.draw.toolbar.finish.text  = '\ub05d';
  L.drawLocal.draw.toolbar.undo.title = '\ub9c8\uc9c0\ub9c9 \uc810 \uc9c0\uc6b0\uae30';
  L.drawLocal.draw.toolbar.undo.text  = '\ud55c \uc810 \uc9c0\uc6b0\uae30';
  L.drawLocal.draw.handlers.polyline.tooltip.start = '\ub20c\ub7ec\uc11c \uad00 \uacbd\ub85c\ub97c \uc2dc\uc791\ud569\ub2c8\ub2e4';
  L.drawLocal.draw.handlers.polyline.tooltip.cont  = '\uacc4\uc18d \ub20c\ub7ec \uc774\uc5b4 \uadf8\ub9bd\ub2c8\ub2e4';
  L.drawLocal.draw.handlers.polyline.tooltip.end   = '\ub9c8\uc9c0\ub9c9 \uc810\uc744 \ub450 \ubc88 \ub20c\ub7ec \ub05d\ub0c5\ub2c8\ub2e4';
  L.drawLocal.draw.handlers.polygon.tooltip.start = '\ub20c\ub7ec\uc11c \ubc2d \ubaa8\uc11c\ub9ac\ub97c \ucc0d\uae30 \uc2dc\uc791\ud569\ub2c8\ub2e4';
  L.drawLocal.draw.handlers.polygon.tooltip.cont  = '\ubaa8\uc11c\ub9ac\ub97c \uacc4\uc18d \ucc0d\uc2b5\ub2c8\ub2e4';
  L.drawLocal.draw.handlers.polygon.tooltip.end   = '\uccab \uc810\uc744 \ub2e4\uc2dc \ub20c\ub7ec \ub2eb\uc2b5\ub2c8\ub2e4';
  L.drawLocal.edit.toolbar.buttons.edit = '\uadf8\ub9b0 \uac83 \uace0\uce58\uae30';
  L.drawLocal.edit.toolbar.buttons.editDisabled = '\uace0\uce60 \uac83\uc774 \uc5c6\uc2b5\ub2c8\ub2e4';
  L.drawLocal.edit.toolbar.buttons.remove = '\uadf8\ub9b0 \uac83 \uc9c0\uc6b0\uae30';
  L.drawLocal.edit.toolbar.buttons.removeDisabled = '\uc9c0\uc6b8 \uac83\uc774 \uc5c6\uc2b5\ub2c8\ub2e4';
  L.drawLocal.edit.toolbar.actions.save.title = '\uace0\uce5c \uac83 \uc800\uc7a5';
  L.drawLocal.edit.toolbar.actions.save.text  = '\uc800\uc7a5';
  L.drawLocal.edit.toolbar.actions.cancel.title = '\ub418\ub3cc\ub9ac\uae30';
  L.drawLocal.edit.toolbar.actions.cancel.text  = '\ucde8\uc18c';
  L.drawLocal.edit.toolbar.actions.clearAll.title = '\uc804\ubd80 \uc9c0\uc6b0\uae30';
  L.drawLocal.edit.toolbar.actions.clearAll.text  = '\uc804\ubd80 \uc9c0\uc6c0';
} catch (e) {}
try {
  // 🔴 아이콘만 있으면 못 찾는다(대표 2026-09-07 「연필 모양을 찾을 수 없어」).
  //    마우스를 올려야 보이는 툴팁으로는 부족하다 — **늘 보이는 이름표**를 옆에 붙인다.
  //    ⚠ `background-size` 는 건드리지 않는다: leaflet.draw 의 스프라이트를 깨뜨릴 수 있다.
  var L1 = '\uc8fc\ubc30\uad00 (\uc120)';        // 주배관 (선)
  var L2 = '\ubc2d (\uba74)';                      // 밭 (면)
  var L3 = '\uae09\uc218\uc6d0 (\ud540)';        // 급수원 (핀)
  var L4 = '\uc810 \ud3b8\uc9d1';                 // 점 편집
  var L5 = '\uc9c0\uc6b0\uae30';                  // 지우기
  var chip =
    'position:absolute;left:36px;top:5px;white-space:nowrap;' +
    'background:rgba(17,17,17,.86);color:#fff;font:600 12px/20px sans-serif;' +
    'padding:0 8px;border-radius:4px;pointer-events:none;box-shadow:0 1px 4px rgba(0,0,0,.4);';
  var st = document.createElement('style');
  st.textContent =
    '.leaflet-draw-tooltip{font-size:13px;padding:6px 9px;background:rgba(0,0,0,.82);' +
    'border-left-color:#78dcff;color:#fff}' +
    '.leaflet-container.leaflet-crosshair,.leaflet-container.leaflet-crosshair *{cursor:crosshair!important}' +
    '.leaflet-draw-section,.leaflet-draw-toolbar,.leaflet-draw-toolbar a{overflow:visible}' +
    '.leaflet-draw-toolbar a{position:relative}' +
    '.leaflet-draw-draw-polyline::after{content:"' + L1 + '";' + chip + '}' +
    '.leaflet-draw-draw-polygon::after{content:"'  + L2 + '";' + chip + '}' +
    '.leaflet-draw-draw-marker::after{content:"'   + L3 + '";' + chip + '}' +
    '.leaflet-draw-edit-edit::after{content:"'     + L4 + '";' + chip + '}' +
    '.leaflet-draw-edit-remove::after{content:"'   + L5 + '";' + chip + '}' +
    // 못 쓰는 상태(그린 것이 없을 때)는 흐리게 — 왜 안 눌리는지 보이게.
    '.leaflet-disabled::after{opacity:.45}' +
    // 🔴 꼭짓점 손잡이가 너무 작아 못 잡는다(대표 2026-09-07) — 8 px → 15 px.
    //    흰 네모 = 꼭짓점(끌어 옮김) · 회색 네모 = 변 가운데(끌면 점이 새로 생김).
    '.leaflet-editing-icon{width:15px!important;height:15px!important;' +
    'margin-left:-7px!important;margin-top:-7px!important;' +
    'border:2px solid #111!important;border-radius:3px!important;' +
    'box-shadow:0 0 0 1px rgba(255,255,255,.7)}';
  document.head.appendChild(st);
} catch (e) {}
{% endmacro %}
"""

# [V85] 지도 첫 화면 기준점. **어디여도 된다** — 좌표계의 원점일 뿐이고 대상지는 지도에서 찾는다.
#   작도판은 `fit_frame()` 이 **그린 것**에 맞춰 다시 잡으므로 이 값이 결과를 바꾸지 않는다(#62).
P3_MAP_HOME = (127.17736, 36.32167)      # 논산시 상월면 상도리 482-42 일대

# [V84] 지도 안 「지번 검색」 — **브라우저가 직접 브이월드에 묻는다**(JSONP · #62).
#   🔴 배포 서버는 브이월드에 못 닿지만(#58) 대표님 브라우저는 한국에서 나가므로 통한다.
#      브이월드가 `callback=` 을 지원해서(2026-09-07 실측) CORS 없이 <script> 로 부를 수 있다.
#   ⚠ 클라이언트 지도는 키가 페이지에 실린다 — **도메인 제한이 걸린 키만** 여기에 쓴다(원칙 4).
P3_SEARCH_JS = """
{% macro script(this, kwargs) %}
(function(){
  var map = {{this._parent.get_name()}};
  var KEY = "__KEY__";
  var mark = null;
  var Box = L.Control.extend({
    options: {position: 'topright'},
    onAdd: function(){
      var d = L.DomUtil.create('div', 'leaflet-bar');
      d.style.cssText = 'background:#fff;padding:6px 8px;box-shadow:0 1px 5px rgba(0,0,0,.4);border-radius:4px';
      d.innerHTML =
        '<input id="p3vwq" placeholder="\uc9c0\ubc88 \uac80\uc0c9 \u2014 \uc608: \uc0c1\uc6d4\uba74 \uc0c1\ub3c4\ub9ac 482-42" ' +
        'style="width:270px;border:1px solid #ccc;border-radius:3px;padding:4px 7px;font-size:13px">' +
        '<div id="p3vwm" style="font:11px sans-serif;color:#666;margin-top:3px">' +
        '\uc5d4\ud130\ub85c \uac80\uc0c9 (\ube0c\uc774\uc6d4\ub4dc)</div>';
      L.DomEvent.disableClickPropagation(d);
      L.DomEvent.disableScrollPropagation(d);
      return d;
    }
  });
  map.addControl(new Box());
  function say(t){ var m = document.getElementById('p3vwm'); if (m) m.textContent = t; }
  function go(q){
    say('\ucc3e\ub294 \uc911...');
    var cb = 'p3vw' + Math.random().toString(36).slice(2);
    var sc = document.createElement('script');
    window[cb] = function(r){
      try {
        var res = r && r.response;
        var items = res && res.result && res.result.items;
        if (!res || res.status !== 'OK' || !items || !items.length) {
          say('\ubabb \ucc3e\uc558\uc2b5\ub2c8\ub2e4 \u2014 \uc74d\u00b7\uba74\uc744 \ubd99\uc5ec \ubcf4\uc138\uc694');
        } else {
          var it = items[0], ll = [parseFloat(it.point.y), parseFloat(it.point.x)];
          map.setView(ll, 18);
          if (mark) { map.removeLayer(mark); }
          mark = L.circleMarker(ll, {radius: 10, color: '#00e5ff', weight: 3, fill: false}).addTo(map);
          say((it.address && it.address.parcel) ? it.address.parcel : '\ucc3e\uc558\uc2b5\ub2c8\ub2e4');
        }
      } catch (e) { say('\uac80\uc0c9 \uc624\ub958'); }
      try { delete window[cb]; } catch (e) { window[cb] = undefined; }
      if (sc.parentNode) { sc.parentNode.removeChild(sc); }
    };
    sc.src = 'https://api.vworld.kr/req/search?service=search&request=search&version=2.0' +
             '&crs=EPSG:4326&size=5&page=1&type=address&category=parcel&format=json' +
             '&query=' + encodeURIComponent(q) + '&key=' + encodeURIComponent(KEY) +
             '&callback=' + cb;
    sc.onerror = function(){ say('\ube0c\uc774\uc6d4\ub4dc\uc5d0 \ub2ff\uc9c0 \ubabb\ud588\uc2b5\ub2c8\ub2e4'); };
    document.head.appendChild(sc);
  }
  setTimeout(function(){
    var el = document.getElementById('p3vwq');
    if (!el) { return; }
    el.addEventListener('keydown', function(e){
      if (e.key === 'Enter') { e.preventDefault(); var v = el.value.trim(); if (v) { go(v); } }
    });
  }, 400);
})();
{% endmacro %}
"""

P3_DRAWN_SAMPLE = '{\n "blocks": [\n  {\n   "name": "A",\n   "polygon": [\n    [\n     0,\n     0\n    ],\n    [\n     40,\n     0\n    ],\n    [\n     40,\n     30\n    ],\n    [\n     0,\n     30\n    ]\n   ],\n   "u": [\n    1,\n    0\n   ]\n  }\n ],\n "routes": [\n  {\n   "name": "R1",\n   "zone": 1,\n   "pts": [\n    [\n     0,\n     0\n    ],\n    [\n     40,\n     0\n    ]\n   ],\n   "by_ceo": true\n  }\n ],\n "sources": [\n  {\n   "name": "관정",\n   "pt": [\n    0,\n    0\n   ],\n   "start_bands": 1\n  }\n ],\n "valves_01403": {\n  "start": 1,\n  "zones": 1\n },\n "water_items": []\n}'

if mode == "관리자 모드" or mode == "管理者モード":
    st.header("🛠 관리자 모드")
    if st.button("🔄 구글시트 데이터 새로고침"): st.session_state.db = load_data_from_sheet(); st.session_state._img_cache = {}; st.success("완료"); st.rerun()
    if not st.session_state.auth_admin:
        # [V34] form: 비밀번호 입력 후 Enter로도 로그인
        with st.form("admin_login_form"):
            pw = st.text_input("관리자 비밀번호", type="password")
            if st.form_submit_button("로그인", type="primary"):
                admin_pwd_db = str(st.session_state.db.get("config", {}).get("admin_pwd", "1234"))
                if pw == admin_pwd_db: st.session_state.auth_admin = True; st.rerun()
                else: st.error("비밀번호 불일치")
    else:
        if st.button("로그아웃"): st.session_state.auth_admin = False; st.rerun()
        t1, t2, t3 = st.tabs(["부품 관리", "세트 관리", "설정"])
        with t1:
            st.markdown("##### 🔍 제품 및 엑셀 관리")
            with st.expander("📂 부품 데이터 직접 수정 (수정/추가/삭제)", expanded=True):
                st.info("💡 팁: 표 안에서 직접 내용을 수정하거나, 맨 아래 행에 추가하거나, 행을 선택해 삭제(Del키)할 수 있습니다.")
                
                df = pd.DataFrame(st.session_state.db["products"])
                for key_val in COL_MAP.values():
                    if key_val not in df.columns:
                        df[key_val] = 0 if "price" in key_val or "len" in key_val else ""
                df = df.rename(columns=REV_COL_MAP)
                if "이미지데이터" in df.columns: df["이미지데이터"] = df["이미지데이터"].apply(lambda x: x if x else "")
                df["순번"] = [f"{i+1:03d}" for i in range(len(df))]
                desired_order = list(COL_MAP.keys())
                final_cols = [c for c in desired_order if c in df.columns]
                df = df[final_cols]

                # [V20] data_editor 타입 충돌 방지:
                #  NumberColumn 대상 컬럼은 숫자로 강제(빈값→0), 나머지는 문자열로 강제.
                num_cols = ["매입단가","총판가1","총판가2","대리점가1","대리점가2",
                            "계통농협","지역농협","소비자가","단가(현장)","신정공급가"]
                for _nc in num_cols:
                    if _nc in df.columns:
                        df[_nc] = pd.to_numeric(df[_nc], errors="coerce").fillna(0).astype(int)
                if "1롤길이(m)" in df.columns:
                    df["1롤길이(m)"] = pd.to_numeric(df["1롤길이(m)"], errors="coerce").fillna(0)
                text_cols = ["순번","품목코드","카테고리","제품명","규격","단위","이미지데이터","최근수정일"]
                for _tc in text_cols:
                    if _tc in df.columns:
                        df[_tc] = df[_tc].fillna("").astype(str)

                edited_df = st.data_editor(
                    df, 
                    num_rows="dynamic", 
                    width="stretch", 
                    key="product_editor",
                    column_config={
                        "순번": st.column_config.TextColumn(disabled=False, width="small"),
                        "품목코드": st.column_config.TextColumn(help="5자리 코드로 입력하세요 (예: 00100)"),
                        "매입단가": st.column_config.NumberColumn(format="%d"),
                        "총판가1": st.column_config.NumberColumn(format="%d"),
                        "총판가2": st.column_config.NumberColumn(format="%d"),
                        "대리점가1": st.column_config.NumberColumn(format="%d"),
                        "대리점가2": st.column_config.NumberColumn(format="%d"),
                        "계통농협": st.column_config.NumberColumn(format="%d"),
                        "지역농협": st.column_config.NumberColumn(format="%d"),
                        "소비자가": st.column_config.NumberColumn(format="%d"),
                        "단가(현장)": st.column_config.NumberColumn(format="%d"),
                        "신정공급가": st.column_config.NumberColumn(format="%d", help="일본 수출용 공급가"),
                    }
                )
                if st.button("💾 변경사항 구글시트에 반영"):
                    st.session_state.confirming_product_save = True
                if st.session_state.get("confirming_product_save"):
                    st.warning("⚠️ 정말로 구글 시트에 이 내용을 반영하시겠습니까? (되돌릴 수 없습니다)")
                    col_yes, col_no = st.columns(2)
                    with col_yes:
                        if st.button("✅ 네, 반영합니다"):
                            try:
                                edited_df = edited_df.fillna("")
                                edited_df.reset_index(drop=True, inplace=True)
                                edited_df["순번"] = [f"{i+1:03d}" for i in range(len(edited_df))]
                                new_products_list = edited_df.rename(columns=COL_MAP).to_dict('records')
                                save_products_to_sheet(new_products_list)
                                st.session_state.db = load_data_from_sheet()
                                st.success("구글 시트에 성공적으로 반영되었습니다!")
                                st.session_state.confirming_product_save = False
                                time.sleep(1)
                                st.rerun()
                            except Exception as e:
                                st.error(f"저장 중 오류 발생: {e}")
                    with col_no:
                        if st.button("❌ 아니오 (취소)"):
                            st.session_state.confirming_product_save = False
                            st.rerun()
            st.divider()
            ec1, ec2 = st.columns([1, 1])
            with ec1:
                buf = io.BytesIO()
                org_df = pd.DataFrame(st.session_state.db["products"])
                for eng_key in COL_MAP.values():
                    if eng_key not in org_df.columns:
                        val = 0 if ("price" in eng_key or "len" in eng_key) else ""
                        org_df[eng_key] = val
                org_df = org_df.rename(columns=REV_COL_MAP)
                final_cols = [k for k in COL_MAP.keys() if k in org_df.columns]
                org_df = org_df[final_cols]
                with pd.ExcelWriter(buf, engine='xlsxwriter') as w: org_df.to_excel(w, index=False)
                st.download_button("엑셀 다운로드", buf.getvalue(), "products.xlsx")
            with ec2:
                uf = st.file_uploader("엑셀 파일 선택 (일괄 덮어쓰기)", ["xlsx"], label_visibility="collapsed")
                if uf and st.button("시트에 덮어쓰기"):
                    try:
                        ndf = pd.read_excel(uf, dtype={'품목코드': str}).rename(columns=COL_MAP).fillna(0)
                        save_products_to_sheet(ndf.to_dict('records')); st.session_state.db = load_data_from_sheet(); st.success("완료"); st.rerun()
                    except Exception as e: st.error(e)
            st.divider()
            st.markdown("##### 🔄 드라이브 이미지 일괄 동기화")
            with st.expander("구글 드라이브 폴더의 이미지와 자동 연결하기", expanded=False):
                st.info("💡 파일명을 '품목코드.jpg'(예: 01513.jpg)로 저장해 'Looperget_Images' 폴더(또는 그 하위 products 폴더)에 올리세요. 하위 폴더까지 자동 검색합니다.")
                if st.button("🔄 드라이브 이미지 자동 연결 실행", key="btn_sync_images"):
                    with st.spinner("드라이브 폴더(하위 포함)를 검색하는 중..."):
                        get_drive_file_map.clear()
                        get_drive_file_map_deep.clear()
                        file_map = get_drive_file_map_deep()
                        if not file_map:
                            st.warning("폴더가 비어있거나 찾을 수 없습니다.")
                        else:
                            updated_count = 0
                            products = st.session_state.db["products"]
                            unmatched = []
                            for p in products:
                                raw = str(p.get("code", "")).strip()
                                code5 = raw.zfill(5)
                                # 코드(zfill) 또는 원본 코드로 매칭
                                fid = file_map.get(code5) or file_map.get(raw)
                                if fid:
                                    p["image"] = fid
                                    updated_count += 1
                                else:
                                    unmatched.append(code5)
                            if updated_count > 0:
                                save_products_to_sheet(products)
                                st.success(f"✅ 총 {updated_count}개의 제품 이미지를 연결했습니다!")
                                st.session_state.db = load_data_from_sheet()
                                st.rerun()
                            else:
                                st.warning("매칭되는 이미지가 없습니다.")
                                # [V18] 진단정보: 드라이브에 실제 어떤 파일명이 있는지 보여줌
                                drive_keys = sorted([k for k in file_map.keys() if k.isdigit()])
                                st.caption(f"🔍 진단: 드라이브에서 찾은 숫자 파일명 {len(drive_keys)}개")
                                if drive_keys:
                                    st.code(", ".join(drive_keys[:50]) + (" ..." if len(drive_keys) > 50 else ""))
                                else:
                                    st.caption("드라이브에 '숫자.확장자' 형식 파일이 없습니다. 파일명을 품목코드(예: 01513.jpg)로 바꿔주세요.")
                                prod_codes = sorted({str(p.get("code","")).strip().zfill(5) for p in st.session_state.db["products"] if p.get("code")})
                                st.caption(f"📋 시트의 품목코드 예시 {min(len(prod_codes),10)}개")
                                st.code(", ".join(prod_codes[:10]))
            st.divider()
            c1, c2, c3 = st.columns([2, 2, 1])
            pn = [p["name"] for p in st.session_state.db["products"]]
            with c1: tp = st.selectbox("대상 품목", pn)
            with c2: ifile = st.file_uploader("이미지 파일", ["png", "jpg"], key="pimg")
            with c3:
                st.write(""); st.write("")
                if st.button("저장", key="btn_save_img"):
                    if ifile:
                        fname = f"{tp}_{ifile.name}"
                        fid = upload_image_to_drive(ifile, fname)
                        if fid:
                            for p in st.session_state.db["products"]:
                                if p["name"] == tp: p["image"] = fid
                            save_products_to_sheet(st.session_state.db["products"]); st.success("완료")

            # ── [V40] 매입단가 변동 시뮬레이터 v2 (카테고리·지침% 통합) ────────────
            st.divider()
            st.markdown("##### 💹 매입단가 변동 시뮬레이터")
            with st.expander("매입단가 변경 → 이익구조 검토(기존·추천·지침) → 확정 저장", expanded=False):
                if "price_policy_map" not in st.session_state:
                    st.session_state.price_policy_map = load_price_policy()
                _policy = st.session_state.price_policy_map

                products_for_recalc = st.session_state.db["products"]
                _subcats = sorted({s.strip() for p in products_for_recalc
                                   for s in str(p.get("subcategory", "")).split(",")
                                   if s.strip() and s.strip() != "관급비용"})
                col_cat, col_item = st.columns([1, 2])
                with col_cat:
                    _sel_cat = st.selectbox("📂 카테고리", ["전체"] + _subcats, key="sim_cat_sel")
                _pool = [p for p in products_for_recalc
                         if str(p.get("subcategory", "")).strip() != "관급비용"
                         and (_sel_cat == "전체"
                              or _sel_cat in [s.strip() for s in str(p.get("subcategory", "")).split(",")])]
                with col_item:
                    recalc_target = st.selectbox(
                        "🔍 품목", _pool,
                        format_func=lambda p: (
                            f"[{p.get('code','?')}] {p.get('name','')} ({p.get('spec','-')}) "
                            f"| 매입 {int(p.get('price_buy', 0) or 0):,}원"
                            + (" 🔒" if str(p.get('price_policy','')).strip() == "고정" else "")
                        ),
                        key="recalc_product_sel"
                    ) if _pool else None

                if recalc_target:
                    old_buy = int(recalc_target.get("price_buy", 0) or 0)
                    _is_fixed = str(recalc_target.get("price_policy", "")).strip() == "고정"
                    _seg = price_segment(recalc_target)
                    # 선택 품목 헤드라인 카드 — 결정권자가 지금 무엇을 다루는지 크게 표시
                    st.markdown(
                        f'<div style="background:#241F1F;border-left:6px solid #F4D624;border-radius:8px;'
                        f'padding:14px 18px;margin:6px 0 10px 0;">'
                        f'<span style="font-size:1.45em;font-weight:800;color:#F4D624;">'
                        f'{"🔒 " if _is_fixed else ""}{recalc_target.get("name","")}</span>'
                        f'<span style="font-size:1.05em;opacity:.85;"> &nbsp;[{recalc_target.get("code","")}] '
                        f'{recalc_target.get("spec","")}</span><br>'
                        f'<span style="font-size:1.1em;">{_seg}'
                        f'{" · <b>정책 고정가 — 재계산 없음, 직접 입력만</b>" if _is_fixed else ""}'
                        f' · 현재 매입단가 <b style="font-size:1.25em;color:#F4D624;">{old_buy:,}원</b></span></div>',
                        unsafe_allow_html=True)

                    new_buy_input = st.number_input(
                        "🟡 새 매입단가 (원)", min_value=0, value=old_buy, step=10, key="new_buy_input"
                    )

                    if new_buy_input > 0:
                        # 이 카테고리의 실제 이익율 현황(중앙값) — 실시간 계산
                        _rec = recommend_tier_margins(products_for_recalc).get(_seg, {})
                        if _rec:
                            _cur_row = {KR_PRICE_LABELS[fk]: f"{v:.0f}%" for fk, v in _rec.items() if fk in KR_PRICE_LABELS}
                            st.caption(f"📊 **{_seg}** 카테고리의 현재 이익율 분포(중앙값) — 이 품목이 속한 시장의 실제 위치")
                            st.dataframe(pd.DataFrame([_cur_row]), hide_index=True, use_container_width=True)

                        _prop = ({f: int(recalc_target.get(f, 0) or 0) for f in KR_PRICE_FIELDS}
                                 if _is_fixed else recalc_keep_margin(recalc_target, new_buy_input))
                        _prop["price_buy"] = int(new_buy_input)
                        _g_of = _policy.get(_seg, {})  # 회사 지침(티어별 목표 이익%)

                        preview_rows = []
                        for fk, label in KR_PRICE_LABELS.items():
                            if fk == "price_buy": continue
                            old_v = int(float(recalc_target.get(fk, 0) or 0))
                            m_old = margin_pct(old_v, old_buy)
                            g_pct = _g_of.get(label)
                            g_price = (snap_band_price(new_buy_input / (1 - g_pct / 100.0))
                                       if (g_pct is not None and g_pct < 100 and not _is_fixed) else None)
                            preview_rows.append({
                                "_field": fk, "항목": label, "기존가": old_v,
                                "기존%": round(m_old, 1) if m_old is not None else None,
                                "추천가": int(_prop.get(fk, 0)),
                                "지침%": g_pct,
                                "지침가": g_price,
                                "변경후": int(_prop.get(fk, 0)),
                            })
                        st.markdown("**세 가지 기준을 놓고 결정하세요** — ①기존 이익율 유지 시 **추천가** ②회사 **지침%** 적용 시 **지침가** ③판단 반영한 **변경후✏️**")
                        edited_preview = st.data_editor(
                            pd.DataFrame(preview_rows),
                            column_config={
                                "_field": None,
                                "항목": st.column_config.TextColumn("항목", disabled=True, width="small"),
                                "기존가": st.column_config.NumberColumn("기존가", disabled=True, format="%d", width="small"),
                                "기존%": st.column_config.NumberColumn("기존%", disabled=True, format="%.1f", width="small"),
                                "추천가": st.column_config.NumberColumn("추천가(기존%유지)", disabled=True, format="%d", width="small"),
                                "지침%": st.column_config.NumberColumn("지침%", disabled=True, format="%.0f", width="small",
                                                                      help="회사가 정한 티어별 목표 이익율(PricePolicy). 아래 '가격 지침 관리'에서 수정"),
                                "지침가": st.column_config.NumberColumn("지침가", disabled=True, format="%d", width="small"),
                                "변경후": st.column_config.NumberColumn("변경후 ✏️", format="%d", width="medium"),
                            },
                            hide_index=True, use_container_width=True,
                            key=f"preview_editor_{new_buy_input}_{recalc_target.get('code','')}"
                        )

                        # 검증표: 편집값 → 스냅 결과 + 새 이익율 + 지침 대비 편차 즉시 재계산
                        final_prices = {"price_buy": int(new_buy_input)}
                        check_rows = []
                        for _, row in edited_preview.iterrows():
                            fk = row["_field"]
                            raw_v = float(row["변경후"] or 0)
                            snapped = raw_v if _is_fixed else snap_band_price(raw_v)
                            final_prices[fk] = int(snapped)
                            m_new = margin_pct(snapped, new_buy_input)
                            g_pct = row["지침%"]
                            gap = (round(m_new - float(g_pct), 1) if (m_new is not None and g_pct is not None and not pd.isna(g_pct)) else None)
                            check_rows.append({
                                "항목": row["항목"], "저장될 가격": int(snapped),
                                "새 이익율%": round(m_new, 1) if m_new is not None else None,
                                "지침 대비(%p)": (f"{gap:+.1f}" if gap is not None else ""),
                                "스냅조정": "→" + format(int(snapped), ",") if int(snapped) != int(raw_v) else "",
                            })
                        st.markdown("**✅ 저장 전 검증 — 새 이익 구조** (지침 대비 +면 지침보다 이익 높음)")
                        st.dataframe(pd.DataFrame(check_rows), hide_index=True, use_container_width=True)

                        if new_buy_input != old_buy:
                            st.warning(f"⚠️ [{recalc_target.get('code')}] {recalc_target.get('name')} 의 단가를 위 검증표대로 변경합니다.")
                        else:
                            st.info("ℹ️ 매입가 동일 — 변경후 열을 직접 수정한 항목만 반영됩니다.")
                        col_ok, col_cancel = st.columns(2)
                        with col_ok:
                            if st.button("✅ 확정 — 단가 반영 및 저장", key="btn_recalc_confirm", type="primary"):
                                target_code = str(recalc_target.get("code", "")).strip()
                                today_str = datetime.datetime.now().strftime("%Y-%m-%d")
                                updated_products = []
                                for p in st.session_state.db["products"]:
                                    if str(p.get("code", "")).strip() == target_code:
                                        p.update(final_prices)
                                        p["last_updated"] = today_str  # 수정일 기록
                                    updated_products.append(p)
                                save_products_to_sheet(updated_products)
                                st.session_state.db["products"] = updated_products
                                st.session_state.pending_jp_sync = True
                                st.success("✅ 한국 단가 저장 완료!")
                                st.rerun()
                        with col_cancel:
                            if st.button("❌ 취소", key="btn_recalc_cancel"):
                                st.rerun()

                # JP 동기화 확인 팝업
                if st.session_state.get("pending_jp_sync"):
                    st.divider()
                    st.markdown("### 🇯🇵 일본 Products_JP 자동 동기화")
                    st.info("한국 단가가 변경되었습니다. 일본 시트(Products_JP)도 환율 기준으로 자동 업데이트하시겠습니까?")
                    rate_for_sync = st.number_input("적용 환율 (₩/¥)", value=st.session_state.get("exchange_rate", 10.0), step=0.1, key="sync_rate_popup")
                    c_yes, c_no = st.columns(2)
                    with c_yes:
                        if st.button("🇯🇵 네, Products_JP 업데이트", type="primary", key="btn_jp_sync_yes"):
                            with st.spinner("Products_JP 동기화 중..."):
                                ok, msg = sync_products_jp_to_sheet(st.session_state.db["products"], rate_for_sync)
                            st.session_state.pending_jp_sync = False
                            st.session_state.jp_products_loaded = False
                            if ok: st.success(f"✅ {msg}")
                            else: st.error(f"동기화 실패: {msg}")
                            st.rerun()
                    with c_no:
                        if st.button("나중에", key="btn_jp_sync_no"):
                            st.session_state.pending_jp_sync = False
                            st.rerun()

            # ── [V40] 가격 지침(티어별 목표 이익%) 관리 ────────────
            with st.expander("📐 가격 지침 관리 — 카테고리×티어별 목표 이익% (시뮬레이터의 '지침%' 원본)", expanded=False):
                st.caption("여기 값이 시뮬레이터의 지침%·지침가로 표시됩니다. 초기값은 기존 데이터의 이익율 중앙값 — 회사 방침에 맞게 다듬어 저장하세요.")
                if "price_policy_map" not in st.session_state:
                    st.session_state.price_policy_map = load_price_policy()
                _pol_rows = []
                _tier_labels = [lb for fk, lb in KR_PRICE_LABELS.items() if fk != "price_buy"]
                for _sub, _d in sorted(st.session_state.price_policy_map.items()):
                    _pol_rows.append({"세부카테고리": _sub, **{t: _d.get(t) for t in _tier_labels}})
                if _pol_rows:
                    _pol_edit = st.data_editor(
                        pd.DataFrame(_pol_rows),
                        column_config={"세부카테고리": st.column_config.TextColumn("세부카테고리", disabled=True)},
                        hide_index=True, use_container_width=True, key="policy_editor")
                    c_ps, c_pr = st.columns(2)
                    with c_ps:
                        if st.button("💾 지침 저장", key="btn_policy_save", type="primary"):
                            try:
                                save_price_policy(_pol_edit.to_dict("records"))
                                st.session_state.price_policy_map = load_price_policy()
                                st.success("✅ 가격 지침 저장 완료"); st.rerun()
                            except Exception as _pe:
                                st.error(f"저장 실패: {_pe}")
                    with c_pr:
                        if st.button("🔄 시트에서 다시 불러오기", key="btn_policy_reload"):
                            st.session_state.price_policy_map = load_price_policy(); st.rerun()
                else:
                    st.info("PricePolicy 시트가 비어있습니다. 시트에 지침을 입력하거나 관리자에게 문의하세요.")

            # ── [V11] 일본 Products_JP 일괄 동기화 ──────────────────────
            st.divider()
            st.markdown("##### 🇯🇵 일본 Products_JP 일괄 동기화")
            with st.expander("한국 DB 전체를 기준으로 Products_JP를 재생성합니다.", expanded=False):
                st.info("신정공급가 기준으로 엔화 매입가를 재산출하고, 기존 대리점가/소비자가 비율을 유지합니다.\n신규 품목은 매입가 × 1.3(대리점), × 1.65(소비자 포함가) 기본 배수 적용.")
                rate_bulk = st.number_input("환율 설정 (₩/¥)", value=st.session_state.get("exchange_rate", 10.0), step=0.1, key="bulk_sync_rate")
                if st.button("🔄 일본 시트 전체 동기화 실행", key="btn_bulk_jp_sync"):
                    with st.spinner("Products_JP 동기화 중..."):
                        ok, msg = sync_products_jp_to_sheet(st.session_state.db["products"], rate_bulk)
                    st.session_state.jp_products_loaded = False
                    if ok: st.success(f"✅ {msg}")
                    else: st.error(f"실패: {msg}")
        with t2:
            st.subheader("세트 관리")
            # [V28] PPT 일람표는 구(PPT 기반) 워크플로 유물 — 파일이 있을 때만 버튼 표시, 없으면 조용히 숨김(상시 경고 제거)
            ppt_data = get_admin_ppt_content()
            if ppt_data:
                st.download_button(label="📥 세트 구성 일람표(PPT) 다운로드", data=ppt_data, file_name="Set_Composition_Master.pptx", mime="application/vnd.openxmlformats-officedocument.presentationml.presentation", use_container_width=True)
                st.divider()
            cat = st.selectbox("분류", ["주배관세트", "가지관세트", "살수세트", "기타자재"])
            cset = st.session_state.db["sets"].get(cat, {})
            if cset:
                sl = [{"세트명": k, "부품수": len(v.get("recipe", {}))} for k,v in cset.items()]
                st.dataframe(pd.DataFrame(sl), width="stretch", on_select="rerun", selection_mode="multi-row", key="set_table")
                sel_rows = st.session_state.set_table.get("selection", {}).get("rows", [])
                if sel_rows:
                    if len(sel_rows) == 1:
                        tg = sl[sel_rows[0]]["세트명"]
                        st.markdown(f"#### 🔧 세트 관리: {tg}")
                        col_edit, col_img = st.columns([1, 1])
                        with col_edit:
                            if st.button(f"✏️ '{tg}' 구성품 수정하기", use_container_width=True):
                                st.session_state.temp_set_recipe = cset[tg].get("recipe", {}).copy()
                                st.session_state.target_set_edit = tg
                                st.rerun()
                        with col_img:
                            with st.expander("🖼️ 세트 이미지 관리", expanded=True):
                                current_set_data = st.session_state.db["sets"][cat][tg]
                                current_img_id = current_set_data.get("image", "")
                                if current_img_id:
                                    st.image(get_image_from_drive(current_img_id), caption="현재 등록된 이미지", use_container_width=True)
                                    if st.button("🗑️ 이미지 삭제", key=f"del_img_{tg}"):
                                        st.session_state.db["sets"][cat][tg]["image"] = ""
                                        save_sets_to_sheet(st.session_state.db["sets"])
                                        if "_img_cache" in st.session_state:
                                            st.session_state._img_cache.pop(tg, None)
                                        st.success("이미지가 삭제되었습니다.")
                                        st.rerun()
                                else:
                                    st.info("등록된 이미지가 없습니다.")
                                set_img_file = st.file_uploader("이미지 업로드/변경", type=["png", "jpg", "jpeg"], key=f"uploader_{tg}")
                                if set_img_file:
                                    if st.button("💾 이미지 저장", key=f"save_img_{tg}"):
                                        with st.spinner("이미지 업로드 중..."):
                                            file_ext = set_img_file.name.split('.')[-1]
                                            new_filename = f"{tg}_image.{file_ext}"
                                            new_img_id = upload_set_image_to_drive(set_img_file, new_filename)
                                            if new_img_id:
                                                st.session_state.db["sets"][cat][tg]["image"] = new_img_id
                                                save_sets_to_sheet(st.session_state.db["sets"])
                                                if "_img_cache" in st.session_state:
                                                    st.session_state._img_cache.pop(tg, None)
                                                st.success("이미지가 등록되었습니다!")
                                                time.sleep(1)
                                                st.rerun()
                    else:
                        st.caption("💡 수정 또는 이미지 관리를 하려면 1개만 선택해주세요.")
                    st.markdown("---")
                    with st.expander(f"🗑️ 선택된 {len(sel_rows)}개 세트 일괄 삭제", expanded=True):
                        st.warning(f"선택한 {len(sel_rows)}개의 세트를 정말로 삭제하시겠습니까?")
                        del_pw = st.text_input("관리자 비밀번호 확인", type="password", key="bulk_del_pw")
                        if st.button("🚫 일괄 삭제 실행", type="primary"):
                            admin_pwd_db = str(st.session_state.db.get("config", {}).get("admin_pwd", "1234"))
                            if del_pw == admin_pwd_db:
                                del_count = 0
                                target_names = [sl[i]["세트명"] for i in sel_rows]
                                for name in target_names:
                                    if name in st.session_state.db["sets"][cat]:
                                        del st.session_state.db["sets"][cat][name]
                                        del_count += 1
                                save_sets_to_sheet(st.session_state.db["sets"])
                                st.success(f"{del_count}개 세트가 삭제되었습니다.")
                                time.sleep(1)
                                st.rerun()
                            else:
                                st.error("비밀번호가 일치하지 않습니다.")
            st.divider()
            st.markdown("##### 🔄 세트 이미지 일괄 동기화 (수동 업로드 후 연결)")
            with st.expander("📂 드라이브에 올린 파일과 세트 자동 연결하기", expanded=False):
                st.info(f"💡 봇 업로드가 실패할 경우 사용하세요.\n1. 구글 드라이브 '{DRIVE_FOLDER_NAME}' 폴더에 이미지 파일을 직접 업로드하세요.\n2. 파일명은 반드시 '세트명'과 같아야 합니다 (예: {list(cset.keys())[0]}.png)")
                if st.button("🔄 드라이브 세트 이미지 자동 동기화", key="btn_sync_set_images"):
                    with st.spinner("드라이브 폴더를 검색하는 중..."):
                        file_map = get_drive_file_map()
                        if not file_map:
                            st.warning("폴더를 찾을 수 없거나 비어있습니다.")
                        else:
                            updated_count = 0
                            all_sets = st.session_state.db["sets"]
                            for cat_key, cat_items in all_sets.items():
                                for s_name, s_data in cat_items.items():
                                    if s_name in file_map:
                                        s_data["image"] = file_map[s_name]
                                        updated_count += 1
                                    elif f"{s_name}_image" in file_map:
                                        s_data["image"] = file_map[f"{s_name}_image"]
                                        updated_count += 1
                            if updated_count > 0:
                                save_sets_to_sheet(all_sets)
                                st.session_state._img_cache = {}  # V12 전체 캐시 무효화
                                st.success(f"✅ 총 {updated_count}개의 세트 이미지를 연결했습니다!")
                                st.session_state.db = load_data_from_sheet()
                            else:
                                st.warning("매칭되는 이미지가 없습니다. (파일명이 세트명과 같은지 확인하세요)")
            st.divider()
            # ── V12: 세트 이미지 빌더 (Fabric.js) ─────────────────────────
            st.markdown("##### 🎨 세트 이미지 빌더 (Fabric.js)")
            with st.expander("캔버스에서 부속 배치 → 세트 이미지 생성 / 신규 세트 통합 등록", expanded=False):
                build_set_image_editor(st.session_state.db.get("sets", {}), st.session_state.db.get("products", []), get_drive_file_map_deep())
            # [V28] 구(舊) '신규 세트' 수동 생성 UI 제거 — 세트 생성·이미지·메타데이터는 위의
            #  🎨 세트 이미지 빌더로 일원화. (구 UI는 동일 세트명으로 저장 시 이미지·캔버스·메타데이터를
            #  통째로 비우던 사고 경로. 롤백: app.py.bak_pre_v28)
            products_obj = st.session_state.db["products"]
            code_name_map = {str(p.get("code")): f"[{p.get('code')}] {p.get('name')} ({p.get('spec')})" for p in products_obj}
            if not st.session_state.get("target_set_edit"):
                st.caption("💡 세트 생성·이미지·메타데이터는 위의 🎨 세트 이미지 빌더에서. 구성품만 빠르게 고치려면 상단 표에서 세트 선택 → ✏️ 버튼.")
            else:
                if "target_set_edit" in st.session_state and st.session_state.target_set_edit:
                    tg = st.session_state.target_set_edit
                    st.info(f"편집: {tg}")
                    st.markdown("###### 구성 품목 수정 (수량 변경 및 삭제)")
                    
                    if st.session_state.temp_set_recipe:
                        recipe_list = []
                        for k, v in st.session_state.temp_set_recipe.items():
                            recipe_list.append({"품목코드": str(k), "품목명": code_name_map.get(str(k), str(k)), "수량": int(v), "삭제": False})
                        
                        edited_recipe = st.data_editor(
                            pd.DataFrame(recipe_list),
                            num_rows="dynamic",
                            width="stretch",
                            hide_index=True,
                            disabled=["품목코드", "품목명"],
                            column_config={
                                "삭제": st.column_config.CheckboxColumn(label="삭제?", default=False)
                            },
                            key="recipe_editor_edit"
                        )
                        
                        new_recipe = {}
                        for _, row in edited_recipe.iterrows():
                            if row.get("삭제"): continue
                            c = str(row.get("품목코드", "")).strip()
                            try: q = int(row.get("수량", 0))
                            except: q = 0
                            if c and q > 0:
                                new_recipe[c] = q
                        st.session_state.temp_set_recipe = new_recipe
                    else:
                        st.info("담긴 품목이 없습니다.")
                    
                    st.divider()
                    st.markdown("###### ➕ 품목 추가")
                    c1, c2, c3 = st.columns([3,2,1])
                    with c1: ap_obj = st.selectbox("추가할 부품", products_obj, format_func=format_prod_label, key="esp")
                    with c2: aq = st.number_input("추가 수량", 1, key="esq")
                    with c3: 
                        st.write("")
                        if st.button("담기", key="esa"): 
                            st.session_state.temp_set_recipe[str(ap_obj['code'])] = aq
                            st.rerun()
                    if st.button("수정 내용 저장", type="primary"):
                        st.session_state.db["sets"][cat][tg]["recipe"] = st.session_state.temp_set_recipe
                        save_sets_to_sheet(st.session_state.db["sets"])
                        st.success("수정되었습니다.")
                    st.write("")
                    if st.button(f"🗑️ '{tg}' 세트 영구 삭제", key="btn_del_set"):
                        del st.session_state.db["sets"][cat][tg]
                        save_sets_to_sheet(st.session_state.db["sets"])
                        if "_img_cache" in st.session_state:
                            st.session_state._img_cache.pop(tg, None)
                        st.session_state.target_set_edit = None
                        st.success("삭제되었습니다."); time.sleep(1); st.rerun()
        with t3: 
            st.markdown("##### ⚙️ 비밀번호 설정")
            app_pwd_input = st.text_input("앱 접속 비밀번호", value=st.session_state.db.get("config", {}).get("app_pwd", "1234"), key="cfg_app")
            admin_pwd_input = st.text_input("관리자/원가조회 비밀번호", value=st.session_state.db.get("config", {}).get("admin_pwd", "1234"), key="cfg_admin")
            if st.button("💾 비밀번호 변경 저장"):
                try:
                    sh = gc.open(SHEET_NAME)
                    ws_config = sh.worksheet("Config")
                    ws_config.clear()
                    ws_config.update([["항목", "비밀번호"], ["app_pwd", app_pwd_input], ["admin_pwd", admin_pwd_input]])
                    st.session_state.db["config"]["app_pwd"] = app_pwd_input
                    st.session_state.db["config"]["admin_pwd"] = admin_pwd_input
                    st.success("비밀번호가 성공적으로 변경되었습니다!")
                except Exception as e:
                    st.error(f"비밀번호 저장 실패: {e}")

# ══════════════════════════════════════════════════════════════════════════
# [V79] 🗺️ 설계(P3) — 접수 → 작도판 → 지도에서 찍기 → 설계·견적
#   [V80] 관경 자동 선정(#52) · 유량·수압 필수화 + 넘기기(#53)
#   [V81] 작도판 502 방어(#56) · ④ 지도에서 찍기(#57 · 대표 지시 2026-09-07)
#   [V82] 점검이 접혀서 안 보이던 것 수정 · 망 도달 점검(#58) · ④를 작도판 없이도 연다
#   [V83] 문진표 안내 · **지도가 입구가 된다**(#59 · 대표 지시 2026-09-07) · 배경 정본 Esri
#   [V84] 문진표 보기 버튼(#61) · 지도가 본 자리를 지킨다 · 작도판이 그린 것에 맞춰 잡힌다
#   [V85] **지도는 늘 열린다**(#64) — 주소 이동이 막혀도 작업이 멈추지 않는다
#   [V86] **그리는 법을 화면이 말한다**(#65) · 그리기 단추 한국어화 · 다음 한 걸음 안내
#   [V87] **급수원도 왼쪽 도구로**(#66) — 지도 클릭 처리 제거 · 깜빡임 제거 · 줄 지우기
#   [V88] **밭 모서리 둥글게**(#67) — 그린 그대로를 남기고 표에서 0~3 · 점 편집 안내
#   [V89] 왼쪽 도구에 **한국어 이름표**(#68) — 아이콘만으로는 못 찾는다
#   [V90] **점 편집이 폴리곤에 안 되던 것 수정**(#69) — edit_options 가 잘못이었다
#   [V91] 둥글게 **기본 0**(#70) · 운전 구역·밸브를 지도 화면에서(#71)
#   [V92] 밭만 그려도 **열·헤드·유량·권고 구역**이 나온다(#72)
#   [V93] 간격을 고른다 · **예상 살수를 지도에** · 구역 자동 매김(#73)
#   [V94] **고랑 방향을 지도에서**(#74) · 각도 수정이 먹게 · 간격 기본 14/14/7
#   [V95] 첫 여백 **7 m 고정**(#77) · 미리보기가 ④와 같은 경로(가지관 곡선 포함 · #78)
#   [V96] 규칙 21(#79) — **인입관 · 분배점**: 선마다 역할(인입관/주배관) · 인입관 재질·관경 ·
#         구역 밸브는 분배점에서 엔진이 센다(대표 입력 우선) · 지도에 인입관 점선 · 분배점 표시
#   [V97] 검토 패치 — 역할·이름 변경 즉시 반영 · 빈 밭 합계 · 계산 관경/자재 일치 · 입력 검증
#   [V98] 가지관 지도 손잡이 · 주배관 기준 첫 여백 · 그리기 전 인입관/주배관 선택
#   [V99] 지도 재생성 때 복원 도형의 집계·목록 반영 유지(None과 명시적 삭제 [] 구별)
#   [V100] ②탭 🔗 연결 판정(④와 같은 `mainline.analyze`) · 새 밭 고랑 방향 = 긴 변 · 표 각도 부호 자동(`_p3_orient`) ·
#          가지관 이동 거부 이유를 지도 아래에(대표 2026-09-08 「깜빡이고 원상복구」)
#   [V101] 🚫 **스프링클러 빼기** — 지도에서 눌러 그 자리만 뺀다(되살리기 · 회색 ✕) ·
#          작물 빈 칸을 None 으로(""가 ④ 설계를 막고 있었다 · 대표 2026-09-08)
#   [V102] ➕ **스프링클러 추가**(가장 가까운 가지관에 투영) · 📏 **열 안 균등 정렬**(첫·마지막 고정)과 열별 간격표 ·
#          살수원 **안쪽 7 m**(귀환 살수) · 「닿지 않음」의 뜻·거리·고치는 법 · 작도판을 대상지에 맞춰 꽉 ·
#          ④에서 **제안서 PPTX · 견적서 XLSX 초안** 생성(대표 2026-09-08)
#   [V103] 🔀 **인입관↔주배관 연결은 여러 가지다** — 시작점만 보던 판정을 **양쪽 끝**으로 넓혔다.
#          주배관 중간에 T(tap) · 끝점끼리(tail) · 분배점 = **물을 받는 자리** · 말단 = **열린 끝**(대표 2026-09-08)
#   [V104] 배포 서버에서 **견적서는 나오게** — 제안서 지면(59 MB 마스터·작도 도구)은 지연 임포트로 분리하고
#          없으면 이유·job JSON·한 줄 명령을 준다 · 유량을 **숫자+단위**로도 받고 못 읽으면 **적으신 말**을 되짚는다
#   [V107] 🔧 **접점 유형**(일자·엘보·T)과 그 자리 밸브 · 🧩 **엔진이 세트 신설 후보를 만든다**(대표 2026-09-09)
#   [V106] 🚰 **급수 계통 품목 입력**(규칙 7 — 지금까지 화면에 입구가 없었다) · 🔩 **재질이 바뀌는 자리**를 세운다 ·
#          파이프로 시작하면 **호스밴드를 세지 않는다**(대표 2026-09-09)
#   [V105] ④ NameError 로 스크립트가 죽어 ②지도가 되돌아가던 것 · **원점이 바뀌면 찍어 둔 좌표도 함께 옮긴다** ·
#          같은 접점을 두 번 T 로 세던 것 · 작물 채움 · 급수원 용어 · **관수 방식**(노지 3종 · 스프링클러만) ·
#          **인입관·주배관 둘 다 재질·관경**(대표 2026-09-09)
#   흐름 정본 = `_설계/_문진표/문진표_v1_농지.md` · 대표 확답 #43·#44
#   🔴 캔버스를 새로 만들지 않는다(파일 기반 1안 · 대표 선택 2026-09-06).
#      작도판 PNG를 내려받아 농민 확인 → 확인된 blocks/routes JSON을 올린다.
#   🔴 계산은 전부 `looperget/design` 이 한다 — 이 화면은 입력을 받고 결과를 보여줄 뿐이다.
# ══════════════════════════════════════════════════════════════════════════
elif mode == "🗺️ 설계(P3)":
    from looperget.design import intake as _p3i, mapsrc as _p3m
    from looperget.design import design as _p3_design, hydro_zone as _p3hz, pipes as _p3p
    from looperget.design import mainline as _p3ml, site as _p3s      # [V96] 규칙 21 인입관·분배점
    from looperget.design import preview as _p3v, mapedit as _p3edit
    from looperget.design import publish as _p3pub    # [V105] ④ 발행부가 화면 밖에서도 쓴다
    from looperget.design import sets as _p3set       # [V107] 세트 대조·신설 후보
    #  🔴 `publish` 는 제안서 지면 모듈을 **지연 임포트**한다(V104) — 배포 서버에서도 여기서 죽지 않는다.

    def _p3_crop():
        """①문진표에 적은 작물. 밭 표가 비어 있으면 이 값을 넣는다(대표 2026-09-09)."""
        return str((st.session_state.get("p3_answers") or {}).get("crop") or "").strip()

    def _p3_rebase(_o_old, _o_new):
        """지도 **원점이 바뀌면 이미 찍어 둔 좌표도 함께 옮긴다**.

        🔴 로컬 미터는 원점 기준 상대 좌표다. 원점만 갈아 끼우면 옛 좌표가 **엉뚱한 곳**을 가리킨다
          — 대표 실사용 2026-09-09: 급수원이 밭에서 **158 km** 떨어진 자리에 적혀 있었고,
          그 탓에 연결 판정·T 수량이 전부 어긋났다(급수원 표 x −31,871 · y 155,481).
        옮길 수 없는 것(수동 열 위치 `manual_rows`)은 푼다 — 앵커도 원점 기준이기 때문이다.
        """
        if not _o_old or not _o_new or [round(v, 9) for v in _o_old] == [round(v, 9) for v in _o_new]:
            return False
        def _mv(_pts):
            return _p3m.to_local_m(_p3m.from_local_m(_pts, _o_old), _o_new)
        for _key in ("p3_pins", "p3_drawn"):
            _d = st.session_state.get(_key)
            if not isinstance(_d, dict):
                continue
            for _b in (_d.get("blocks") or []):
                for _k in ("polygon", "polygon_raw"):
                    if _b.get(_k):
                        _b[_k] = _mv(_b[_k])
                _pol = _b.get("policy") or {}
                for _k in ("drop_heads", "add_heads"):
                    if _pol.get(_k):
                        _pol[_k] = _mv(_pol[_k])
                _pol.pop("manual_rows", None)
                if _b.get("bars"):
                    _b["bars"] = [_mv(_seg) for _seg in _b["bars"]]
            for _r in (_d.get("routes") or []):
                if _r.get("pts"):
                    _r["pts"] = _mv(_r["pts"])
            for _x in (_d.get("sources") or []):
                if _x.get("pt"):
                    _x["pt"] = _mv([_x["pt"]])[0]
        for _k in ("p3_result", "p3_site", "p3_preview", "p3_prev_sig", "p3_pub"):
            st.session_state.pop(_k, None)      # 옛 원점으로 낸 결과는 버린다
        return True

    def _p3_move_frame(_new_fr):
        """지도 판을 옮긴다 — **좌표 재기준화까지 한 번에**. 판을 바꾸는 곳은 전부 이 문을 지난다."""
        _old = (st.session_state.get("p3_map_frame") or {}).get("origin")
        st.session_state.p3_map_frame = _new_fr
        if _p3_rebase(_old, _new_fr.get("origin")):
            st.session_state.p3_map_epoch = st.session_state.get("p3_map_epoch", 0) + 1
            st.toast("지도 기준점이 바뀌어 **찍어 둔 좌표를 함께 옮겼습니다.**")
        return True

    def _p3_headers(_pins_):
        """🔀 분배점 — **물을 받는 자리** 기준(V103). 인입관이 주배관 중간에 T 로 붙으면
        그 관의 첫 점이 아니라 **붙은 자리**가 분배점이다(대표 2026-09-08).
        급수원이 있으면 ④와 같은 연결 판정(`analyze`)을 태워 그 자리를 쓴다."""
        _rt = _pins_.get("routes") or []
        if not _rt:
            return []
        if _pins_.get("sources"):
            try:
                return _p3ml.analyze(_rt, _pins_["sources"])["headers"]
            except Exception:
                pass
        return _p3ml.headers(_rt)

    def _p3_orient(_uu, _blk, _pins_):
        """[V100] 밭 `_blk` 의 고랑 방향 `_uu` 를 **급수원(없으면 관)에서 멀어지는 쪽**으로 맞춘다.
        표의 각도·🧭·새 밭 기본값 셋이 같은 규칙을 탄다(`preview.orient_u`)."""
        _pg = _blk.get("polygon") or []
        if not _pg:
            return [round(float(_uu[0]), 6), round(float(_uu[1]), 6)]
        _c = [sum(q[0] for q in _pg) / len(_pg), sum(q[1] for q in _pg) / len(_pg)]
        _cands = [_x["pt"] for _x in (_pins_.get("sources") or []) if _x.get("pt")]
        if not _cands:
            _cands = [q for _r2 in (_pins_.get("routes") or []) for q in (_r2.get("pts") or [])]
        _ref = min(_cands, key=lambda q: (q[0] - _c[0]) ** 2 + (q[1] - _c[1]) ** 2) if _cands else None
        return _p3v.orient_u(_uu, _c, _ref)

    def _p3_keys():
        """지도 키 주입 — 배포 환경엔 `.secrets/` 가 없다(불변 원칙 4)."""
        try:
            _p3m.set_keys(dict(st.secrets["map_keys"]) if "map_keys" in st.secrets else None)
        except Exception:
            _p3m.set_keys(None)

    st.title("🗺️ 설계 (P3)")
    st.caption("문진표 → **지도에서 그리기** → 작도판 → 설계·견적.  **계산은 엔진이 한다** — 이 화면은 값을 만들지 않는다.")

    _p3_steps = st.tabs(["① 문진표", "② 지도에서 그리기", "③ 작도판", "④ 설계·견적"])

    # ── ① 문진표 ──────────────────────────────────────────────────────
    with _p3_steps[0]:
        st.markdown("**통화로 물어보고 그대로 채웁니다.** 🔴 표시는 없으면 설계하지 않습니다.")
        st.caption("🔴 없으면 설계하지 않습니다 · 🟠 필수지만 **모르면 뜻을 밝히고 넘어갈 수 있습니다**.")
        _ans = dict(st.session_state.get("p3_answers", {}))
        _waived = []
        _grp = None
        # [V84] 통화로 자주 나오는 답은 **버튼**으로 받는다(대표 지시 2026-09-07 · #61).
        #   🔴 문항·보기의 정본은 `intake.QUESTIONS` 다 — 이 화면은 거기 적힌 대로 그릴 뿐이다.
        for _q in _p3i.QUESTIONS:
            if _q["group"] != _grp:
                _grp = _q["group"]
                st.markdown("##### " + _grp)
            _mark = "🟠 " if _q.get("waivable") else ("🔴 " if _q["req"] else "")
            _qk, _cur = _q["key"], str(_ans.get(_q["key"], "") or "")
            _ch = _q.get("choices")
            if _ch:
                _other = _q.get("other")
                # 이미 있는 답이 보기에 없으면 「기타」로 본다 — 예전 자유 입력을 잃지 않는다.
                if _cur in _ch:
                    _ix = _ch.index(_cur)
                elif _cur and _other:
                    _ix = _ch.index(_other)
                else:
                    _ix = None
                _sel = st.radio(_mark + _q["ask"], _ch, index=_ix, horizontal=True,
                                key="p3_c_" + _qk, help=_q["why"])
                if _other and _sel == _other:
                    _ans[_qk] = st.text_input("어떤 것인지 적어 주세요",
                                              value=("" if _cur in _ch else _cur),
                                              key="p3_o_" + _qk).strip()
                else:
                    _ans[_qk] = _sel or ""
            else:
                if _p3i.UNITS.get(_qk):
                    # 🔵 [V104] **숫자 + 단위**로도 받는다 — 「340리터」처럼 시간이 빠지면 유량이 아니다
                    #    (대표 2026-09-08). 단추는 **입력칸보다 먼저** 그린다(위젯 상태는 나중에 못 바꾼다).
                    _uu1, _uu2, _uu3 = st.columns([2, 2, 1])
                    _uv = _uu1.number_input("숫자", min_value=0.0, step=10.0, value=0.0,
                                            key="p3_uv_" + _qk, label_visibility="collapsed")
                    _ul = [_x[0] for _x in _p3i.UNITS[_qk]]
                    _us = _uu2.selectbox("단위", _ul, key="p3_us_" + _qk, label_visibility="collapsed")
                    if _uu3.button("넣기", key="p3_ub_" + _qk, disabled=not _uv):
                        _fmt = dict(_p3i.UNITS[_qk])[_us]
                        _num = ("%d" % _uv) if float(_uv).is_integer() else ("%g" % _uv)
                        st.session_state["p3_q_" + _qk] = _fmt % _num
                        st.rerun()
                if _q.get("quick"):
                    # 🔴 단추는 **입력칸보다 먼저** 그린다 — 이미 만들어진 위젯의 상태는 못 바꾼다.
                    _qc = st.columns(len(_q["quick"]) + 2)
                    for _i, _qq in enumerate(_q["quick"]):
                        if _qc[_i].button(_qq, key="p3_qk_%s_%d" % (_qk, _i)):
                            st.session_state["p3_q_" + _qk] = _qq
                            st.rerun()
                _ans[_qk] = st.text_input(_mark + _q["ask"], value=_cur,
                                          key="p3_q_" + _qk, help=_q["why"])
            for _cond, _msg in (_q.get("warn_if") or {}).items():
                if str(_ans.get(_qk, "")).strip() == _cond:
                    st.warning(_msg)
            if _qk in _p3i.WAIVABLE and not str(_ans[_qk] or "").strip():
                if st.checkbox("↑ 이 값 없이 진행합니다 — 모르는 채로 설계 (기록에 남습니다)",
                               key="p3_w_" + _qk):
                    _waived.append(_qk)
        st.session_state.p3_answers = _ans
        st.session_state.p3_waived = _waived
        _chk = _p3i.check(_ans, _waived)
        # 🔴 [V83] 「필수 1칸이 비었다」만으로는 **어느 칸인지도, 어떻게 넘어가는지도** 알 수 없었다
        #    (대표 실사용 2026-09-07 — 「필수는 모두 채웠는데 한 칸 비었다고 나오네」).
        #    비운 칸이 🟠(넘어갈 수 있는 칸)뿐이면 **그 사실과 체크박스 자리**를 말한다.
        _byk = {_q["key"]: _q for _q in _p3i.QUESTIONS}
        _miss = _chk["missing"]
        if _chk["ok"]:
            st.success("✅ " + _chk["verdict"])
        else:
            _names = " · ".join("「%s」" % _byk[_k]["ask"] for _k in _miss)
            if all(_k in _p3i.WAIVABLE for _k in _miss):
                st.warning("🟠 **%s** 가 비었습니다 — 값을 넣으시거나, **그 칸 바로 아래 "
                           "「이 값 없이 진행합니다」를 체크**하시면 넘어갑니다." % _names)
                st.caption("체크하면 「모른 채 진행한다」가 기록에 남고 설계 화면에 경고로 다시 나옵니다. "
                           "그냥 비워 두면 막힙니다(불변 원칙 1).")
            else:
                st.error("🔴 %s 가 비었습니다 — 채우기 전에는 설계하지 않습니다(불변 원칙 1)."
                         % _names)
                st.info("다음에 물을 것 — " + str(_chk["ask_next"]))
        for _w in _chk["warn"]:
            st.warning(_w)
        with st.expander("통화 대본 (그대로 읽으시면 됩니다)"):
            st.code(_p3i.script(), language=None)

    # ── ② 작도판 ──────────────────────────────────────────────────────
    # ── ② 지도에서 그리기 ─────────────────────────────────────────────
    #   [V83] 대표 확답 2026-09-07 — 「농민들은 **대표지번이나 일부지번**을 알려주고 통화·미팅으로
    #   대상지를 알려주는 경우가 대부분이다. **지번으로 특정하기 애매한 경우가 많다.**」
    #   그래서 **입구가 지번이 아니라 지도**가 됐다. 지적 필지는 대상지가 아니다(#43).
    #   🔴 이 화면이 만드는 것은 **좌표뿐**이다. 계산은 엔진이 한다(불변 원칙 1).
    with _p3_steps[1]:
        st.markdown("**지도에서 대상지를 직접 그립니다.** 지번은 참고일 뿐입니다.")
        st.caption("밭 구역은 폴리곤으로, 주배관은 선으로 그리고, 급수원·급수 지점은 눌러서 찍습니다. "
                   "타일은 **브라우저가 직접** 받으므로 서버가 막혀도 지도는 뜹니다.")
        try:
            import folium as _fo
            from folium.plugins import Draw as _FoDraw, Geocoder as _FoGeo
            from branca.element import Template as _BrancaTemplate
            _mapmod = True
        except Exception as _e:
            _mapmod, _map_err = False, str(_e)
        try:
            from streamlit_folium import st_folium as _st_folium
        except Exception as _e:
            _mapmod, _map_err = False, str(_e)

        if not _mapmod:
            st.error("🚨 지도 부품이 없습니다 — `folium` · `streamlit-folium` 이 필요합니다 (" + _map_err + ").")
            st.caption("`requirements.txt` 에 들어 있습니다. 배포 후에도 이 문구가 보이면 재배포가 필요합니다.")
        else:
            # 🔴 [V85] 지도를 열기 전에 관문을 세웠던 것이 잘못이었다 — 주소 이동이 막히면
            #    (브이월드 차단 #58 · Nominatim 이 클라우드 공용 IP 에 429) **아무것도 못 했다.**
            #    기준점은 어디여도 된다: 좌표계의 원점일 뿐이고 대상지는 **지도에서 눈으로 찾는다.**
            # 🔴 [V85] 지도 안 「지번 검색」은 키가 있어야 뜬다 — 배포 환경엔 `.secrets/` 가 없으므로
            #    **지도를 그리기 전에** 주입해야 한다(안 하면 검색창이 조용히 사라진다).
            _p3_keys()
            _fr = st.session_state.get("p3_map_frame")
            if not _fr:
                _fr = _p3m.frame(P3_MAP_HOME, zoom=18, size=(1024, 1024))
                st.session_state.p3_map_frame = _fr
            _addr = (st.session_state.get("p3_answers", {}) or {}).get("address", "").strip()

            with st.expander("📍 다른 곳으로 옮기기 (지도 안 「지번 검색」이 더 빠릅니다)"):
                st.caption("① 주소로 대략 이동 → ② 지도 안 검색창·손으로 밭까지 이동 → ③ 그리기. "
                           "지번이 애매해도 **눈으로 찾으면 됩니다**.")
                _l1, _l2 = st.columns([3, 2])
                if _l1.button("문진표 주소로 이동" + (" — " + _addr if _addr else " (주소 없음)"),
                              key="p3_go_addr", disabled=not _addr):
                    _p3_keys()
                    _hit, _how = None, ""
                    try:
                        _g = _p3m.geocode(_addr)
                        if _g:
                            _hit, _how = _g[0]["center"], "브이월드 지번"
                    except Exception:
                        pass
                    if _hit is None:
                        try:
                            _g = _p3m.geocode_osm(_addr) or _p3m.geocode_osm(
                                " ".join(_addr.split()[:2]))
                            if _g:
                                _hit, _how = _g[0]["center"], "OSM(면 단위 — 밭까지는 손으로)"
                        except Exception as _e:
                            # 🔵 이 경로는 **원래 잘 안 된다** — 브이월드는 서버를 거르고(#58),
                            #    OSM 은 클라우드 공용 IP 라 429 를 준다. 겁주지 않고 갈 길을 말한다.
                            st.caption("서버 쪽 주소 검색은 막혀 있습니다 (%s)." % str(_e)[:60])
                    if _hit:
                        _p3_move_frame(_p3m.frame(_hit, zoom=18, size=(1024, 1024)))
                        st.session_state.p3_move_nonce = st.session_state.get("p3_move_nonce", 0) + 1
                        st.session_state.p3_map_how = _how
                        st.rerun()
                    else:
                        st.info("🔵 **지도 안 오른쪽 위 「지번 검색」을 쓰세요** — 그건 대표님 브라우저가 "
                                "직접 브이월드에 묻기 때문에 **서버가 막혀 있어도 됩니다.** "
                                "지도는 이미 아래에 열려 있습니다.")
                _q1, _q2 = st.columns([3, 1])
                _pst = _q1.text_input("좌표 붙여넣기 (위도, 경도)", value="",
                                      placeholder="36.32167, 127.17736", key="p3_mc_paste",
                                      help="다른 지도에서 찍은 좌표를 그대로 붙이면 됩니다.")
                if _q2.button("이 좌표로", key="p3_map_open"):
                    # 🔴 [V85] 회색 글씨는 **예시**다 — 비운 채 누르면 「못 읽었습니다」가 떴다.
                    #    빈칸과 형식 오류를 갈라서 말하고, 쉼표·공백·괄호를 모두 받는다.
                    _raw = "".join(_c if (_c.isdigit() or _c in ".-") else " " for _c in _pst)
                    _nums = [_v for _v in _raw.split() if _v not in (".", "-", "-.")]
                    if not _pst.strip():
                        st.warning("좌표 칸이 비어 있습니다 — 회색 글씨는 **예시**입니다. "
                                   "값을 직접 넣으시거나 지도 안 「지번 검색」을 쓰세요.")
                    elif len(_nums) < 2:
                        st.error("좌표를 못 읽었습니다 — 「36.32167, 127.17736」 처럼 **숫자 두 개**를 넣어 주세요.")
                    else:
                        try:
                            _a, _b = float(_nums[0]), float(_nums[1])
                            # 위도·경도를 바꿔 넣어도 바로잡는다(한국은 위도 33~39 · 경도 124~132).
                            _lat, _lon = (_a, _b) if _a < _b else (_b, _a)
                            if not (32.0 <= _lat <= 40.0 and 123.0 <= _lon <= 133.0):
                                st.error("한국 밖의 좌표입니다 (위도 %.4f · 경도 %.4f) — 다시 확인해 주세요."
                                         % (_lat, _lon))
                            else:
                                _p3_move_frame(_p3m.frame((_lon, _lat), zoom=18, size=(1024, 1024)))
                                st.session_state.p3_move_nonce = (
                                    st.session_state.get("p3_move_nonce", 0) + 1)
                                st.session_state.p3_map_how = "좌표 직접 입력"
                                st.rerun()
                        except ValueError:
                            st.error("좌표를 못 읽었습니다 — 「36.32167, 127.17736」 처럼 넣어 주세요.")
                st.caption("🔵 **지도 안 오른쪽 위 「지번 검색」이 가장 빠릅니다** — 그 검색은 "
                           "대표님 **브라우저가 직접** 브이월드에 묻기 때문에 서버가 막혀 있어도 됩니다.")
                if st.session_state.get("p3_map_how"):
                    st.caption("현재 중심 출처 — " + st.session_state.p3_map_how)

            _org = _fr["origin"]
            _pins = st.session_state.setdefault("p3_pins",
                                                {"sources": [], "routes": [], "blocks": []})
            _pins.setdefault("blocks", [])

            # 🔴 [V87] 대표 실사용 2건이 같은 뿌리였다:
            #    ⓐ 「지도 위에서 클릭해야 하는지 마는지를 몰라」
            #    ⓑ 「밭 모서리를 찍으면 거기에 물탱크 2,3… 이 생기고 화면이 깜빡거린다」
            #    원인 = **지도를 누르면 급수점이 찍히게** 해 둔 것. 밭·주배관을 그릴 때 찍는
            #    모든 점이 급수점이 됐고, 급수점이 늘 때마다 지도가 다시 그려져 **그리기가 끊겼다.**
            #    → 급수원도 **왼쪽 도구**로 찍는다. 도구를 켜야만 찍히고, 켜면 커서가 십자로 바뀌며
            #      「지도를 눌러 급수원을 찍습니다」가 따라다닌다. 지도 클릭 처리는 **없앴다.**
            st.markdown(
                "##### 그리는 법 — 지도 **왼쪽 세로 단추**를 씁니다\n"
                "단추마다 **이름표가 붙어 있습니다.** 확대(＋/－) 아래로 **위에서부터** 이 순서입니다 — "
                "**관(선) · 밭(면) · 급수원(핀)**, 한 칸 띄고 **점 편집 · 지우기**.\n\n"
                "1. **💧 급수원(물탱크·펌프·관정·급수 지점)** — **「급수원 (핀)」** 을 누르면 커서가 십자로 바뀌고 "
                "안내말이 따라다닙니다. 그때 **자리를 한 번 누르면** 찍힙니다.\n"
                "2. **🟨 밭** — **「밭 (면)」** → 모서리를 차례로 찍고 **첫 점을 다시 눌러 닫습니다.**\n"
                "3. **📐 관** — 아래에서 **인입관 / 주배관**을 먼저 고른 뒤 **「관 (선)」** → 물길을 따라 찍고 "
                "**마지막 점을 두 번 눌러** 끝냅니다. 인입관은 **급수원→분배점**, 주배관은 **가지관이 붙는 관**입니다.")
            st.info("🔵 **도구를 켜지 않으면 지도를 눌러도 아무 일도 일어나지 않습니다.** "
                    "확대·이동은 마음껏 하셔도 됩니다. 잘못 그린 것은 왼쪽 **🗑(지우기)** 로 지웁니다.\n\n"
                    "✏ **점 편집** — 왼쪽 아래 **「점 편집」**(지우기 바로 위)을 누르면 밭 테두리가 "
                    "**점선으로 바뀌고 네모 손잡이**가 생깁니다. **흰 네모 = 꼭짓점**(끌어 옮김) · "
                    "**회색 네모 = 변 가운데**(끌면 점이 새로 생김) — 파워포인트 점편집과 같습니다. "
                    "끝나면 **저장**을 누릅니다. 밭 표의 **「둥글게 0~3」** 으로도 모서리를 깎을 수 있습니다.\n\n"
                    "🔴 다 그린 뒤 **아래 「반영」 단추**를 눌러야 목록으로 들어갑니다.")

            # 🔴 [V93] 미리보기를 **지도보다 먼저** 계산한다 — 예상 살수(헤드·반경)를 지도에 얹으려면
            #    값이 있어야 한다. 밭·간격·고랑 방향이 바뀔 때만 다시 돈다(4~5초 · 캐시).
            # 🔴 [V95] 표는 14/14/7 을 보여 주는데 **밭에 policy 가 없으면 엔진은 10/10/5** 로 돌았다
            #    — 그래서 「첫 시작 7 m 를 안 띄운다」가 나왔다(대표 2026-09-08 · 첫 여백 5 m 로 계산됨).
            #    표시와 계산이 갈리지 않게, 없거나 빠진 키를 **여기서 채워 넣는다.**
            #    `off_fixed` 를 함께 준다 — 대표 확답은 「첫 시작은 7 m 를 **띄어야 한다**」이므로
            #    스윕(floor..maxm)에 맡기지 않고 **규칙으로 고정**한다.
            _POL_DEF = {"S": 14.0, "lat_gap": 14.0, "std": 7.0, "maxm": 8.0}
            for _b in _pins["blocks"]:
                _pol = dict(_b.get("policy") or {})
                _fix = _p3edit.map_policy(_pol)
                if _fix != _pol:
                    _b["policy"] = _fix
                # 🔵 [V105] 이미 만들어 둔 밭도 **비어 있으면 문진표 작물로 채운다.**
                if not (_b.get("crop") or "").strip() and _p3_crop():
                    _b["crop"] = _p3_crop()
            if _pins["blocks"]:
                _flow_raw = (st.session_state.get("p3_answers") or {}).get("flow_lpm")
                _flow = _p3v.parse_flow_lpm(_flow_raw)
                _sig = json.dumps([[_b.get("polygon"), _b.get("u"), _b.get("policy"),
                                    _b.get("bars"), _b.get("name"), _b.get("crop")]
                                   for _b in _pins["blocks"]]
                                  + [[_r.get("pts"), _r.get("role"), _r.get("zone")]
                                     for _r in _pins["routes"]],
                                  sort_keys=True) + "|V104|%s|%s" % (_flow, _flow_raw)
                if st.session_state.get("p3_prev_sig") != _sig:
                    with st.spinner("열·헤드·유량 계산 중… (몇 초 걸립니다)"):
                        try:
                            # 🔵 주배관을 그렸으면 **④와 같은 기준**으로 돈다 —
                            #    열이 주배관에서 시작하고, 직각에서 20° 이상 벗어나면
                            #    분기부가 **곡선으로 꺾인다**(규칙 14 · `branch_path`).
                            st.session_state.p3_preview = _p3v.block_preview(
                                _pins["blocks"], flow_lpm=_flow, flow_text=_flow_raw,
                                routes=_pins["routes"] or None)
                        except Exception as _e:
                            st.session_state.p3_preview = {"error": str(_e)}
                    st.session_state.p3_prev_sig = _sig
            else:
                st.session_state.p3_preview = None

            _shw = st.checkbox("💦 예상 살수 보기 (헤드 자리와 반경)", value=True, key="p3_show_heads",
                               help="계산된 스프링클러 자리와 살수 반경을 지도에 겹쳐 봅니다.")
            _draw_role_label = st.radio("새로 그릴 관", ["주배관 (가지관이 붙는 관)", "인입관 (급수원→분배점)"],
                                       horizontal=True, key="p3_draw_role")
            _draw_role = "feeder" if _draw_role_label.startswith("인입관") else "main"
            _edit_rows = st.checkbox("↔ 가지관 위치 조정", value=True, key="p3_edit_rows")
            st.caption("가지관 가운데 **초록 ↔ 손잡이**를 잡고 옆으로 옮기세요. 놓으면 바로 반영됩니다. "
                       "**노란 점선**은 가지관 시작→첫 헤드 거리입니다. 주배관과 교차하지 않는 열은 밭 경계 기준입니다.")
            # 🚫 [V101] 스프링클러 빼기 — 「표시한 곳의 스프링클러를 검토에 따라 뺄 수도 있어야
            #    한다」(대표 2026-09-08). 밭 밖으로 살수가 새는 자리·길 쪽 자리를 **대표가 보고 뺀다.**
            #    🔴 빼도 **남은 배치는 그대로 둔다** — 다시 풀어 벌리면 대표가 보고 결정한 그림이 바뀐다.
            _hm1, _hm2 = st.columns([3, 2])
            _mm = _hm1.radio("지도에서 스프링클러 손보기", ["보기만", "🚫 빼기", "➕ 추가"],
                             horizontal=True, key="p3_head_mode", disabled=not _shw,
                             help="「💦 예상 살수 보기」가 켜져 있어야 합니다.")
            _pick_heads = _shw and _mm.startswith("🚫")
            _add_heads = _shw and _mm.startswith("➕")
            # 📏 [V102] 열 안 균등 정렬 — 「6번째와 7번째 간격이 좁다」(대표 2026-09-08).
            #    규칙 11 말단 보충이 끝 칸을 좁힌다. 첫·마지막을 고정하고 사이를 고르게 놓는다.
            _even_now = bool(_pins["blocks"]) and all((_b.get("policy") or {}).get("even_spacing")
                                                      for _b in _pins["blocks"])
            _even = _hm2.checkbox("📏 열 안 균등 정렬 (첫·마지막 고정)", value=_even_now,
                                  key="p3_even", disabled=not _pins["blocks"],
                                  help="두수는 그대로 두고 **자리만** 고르게 합니다. 간격은 아래 표에 나옵니다.")
            if _even != _even_now and _pins["blocks"]:
                for _b in _pins["blocks"]:
                    _pol2 = dict(_b.get("policy") or {})
                    if _even:
                        _pol2["even_spacing"] = True
                    else:
                        _pol2.pop("even_spacing", None)
                    _b["policy"] = _pol2
                st.session_state.pop("p3_result", None)
                st.session_state.pop("p3_site", None)
                st.rerun()
            if _pick_heads:
                st.caption("🚫 지도에서 **파란 ● 를 누르면 그 스프링클러가 빠집니다**. "
                           "**회색 ✕** 를 누르면 되살아납니다. 두수·가지관 길이·자재·유량이 바로 다시 계산됩니다. "
                           "한 열의 스프링클러를 **전부** 빼면 그 가지관도 없어집니다. "
                           "**간격·고랑 방향·밭 모양을 바꾸면** 헤드 자리가 통째로 옮겨지므로 "
                           "빼 놓은 것은 풀립니다 — 그때는 다시 보고 빼시면 됩니다.")
            if _add_heads:
                st.caption("➕ 지도에서 **놓고 싶은 자리를 누르세요**. **가장 가까운 가지관 위로 붙여** 놓습니다 "
                           "— 가지관에 붙지 않은 스프링클러는 물을 못 받기 때문입니다. "
                           "밭 밖이거나 가지관에서 멀면 놓지 않고 이유를 알려 드립니다. "
                           "🔴 이 모드에서는 **지도 클릭이 스프링클러 추가**입니다 — 선·면을 그리시려면 "
                           "「보기만」으로 돌려 두세요.")
            _ndrop = sum(len((_b.get("policy") or {}).get("drop_heads") or [])
                         for _b in _pins["blocks"])
            _nadd = sum(len((_b.get("policy") or {}).get("add_heads") or [])
                        for _b in _pins["blocks"])
            if _ndrop or _nadd:
                _dc1, _dc2 = st.columns([3, 1])
                _dc1.caption("손본 스프링클러 — 🚫 뺀 것 **%d두** · ➕ 더한 것 **%d두**. "
                             "두수·자재·유량에 이미 반영된 값입니다." % (_ndrop, _nadd))
                if _dc2.button("손본 것 전부 되돌리기", key="p3_drop_reset"):
                    for _b in _pins["blocks"]:
                        (_b.get("policy") or {}).pop("drop_heads", None)
                        (_b.get("policy") or {}).pop("add_heads", None)
                    st.session_state.pop("p3_result", None)
                    st.session_state.pop("p3_site", None)
                    st.rerun()
            if any((_b.get("policy") or {}).get("manual_rows") is not None for _b in _pins["blocks"]):
                st.caption("수동으로 옮긴 열 위치를 유지 중입니다. 열 간격·고랑 방향·밭 모양을 바꾸면 자동배치로 돌아갑니다.")
                if st.button("가지관 자동배치로 되돌리기", key="p3_reset_rows"):
                    for _b in _pins["blocks"]:
                        (_b.get("policy") or {}).pop("manual_rows", None)
                    st.rerun()
            _rev = _p3edit.revision(_pins["blocks"], _pins["routes"]) + "|%s|%s" % (
                _org, st.session_state.get("p3_map_epoch", 0))
            try:
                _sat, _hyb = _p3m.wmts_url("Satellite"), _p3m.wmts_url("Hybrid")
            except Exception:
                _sat = _hyb = ""
            _M = _fo.Map(location=[_org[1], _org[0]], zoom_start=18, max_zoom=21,
                         tiles=None, control_scale=True)
            if _sat:
                _fo.TileLayer(tiles=_sat, attr="VWorld", name="위성 (브이월드)",
                              max_native_zoom=19, max_zoom=21).add_to(_M)
            _fo.TileLayer(tiles=_p3m.ESRI_TILES, attr=_p3m.ESRI_ATTR,
                          name="위성 (Esri)", max_native_zoom=19, max_zoom=21,
                          show=(not _sat)).add_to(_M)
            if _hyb:
                _fo.TileLayer(tiles=_hyb, attr="VWorld", name="주기 (지번·도로)",
                              overlay=True, show=True, max_native_zoom=19, max_zoom=21).add_to(_M)

            # 이미 「반영」된 것 — 지도에 얹되 **손대지 않는다**(고치려면 아래 표에서 지운다).
            for _i, _bk in enumerate(_pins["blocks"]):
                _ll = _p3m.from_local_m(_bk.get("polygon") or [], _org)   # 이미 둥글게 반영된 값
                if len(_ll) >= 3:
                    _fo.Polygon([[_q[1], _q[0]] for _q in _ll], color="#ffd600", weight=4,
                                fill=True, fill_opacity=0.18,
                                tooltip="밭 %s · %s m²" % (_bk.get("name") or _i + 1,
                                                           format(round(_bk.get("area_m2", 0)), ","))
                                ).add_to(_M)
            for _bk in ((st.session_state.get("p3_drawn") or {}).get("blocks") or []):
                _ll = _p3m.from_local_m(_bk.get("polygon") or [], _org)
                if len(_ll) >= 3:
                    _fo.Polygon([[_q[1], _q[0]] for _q in _ll], color="#c46eff", weight=3,
                                fill=False, tooltip="올린 밭 " + str(_bk.get("name") or "")).add_to(_M)
            for _i, _sc in enumerate(_pins["sources"]):
                _lo, _la = _p3m.from_local_m([_sc["pt"]], _org)[0]
                _fo.Marker([_la, _lo], tooltip="%d. %s" % (_i + 1, _sc["name"]),
                           icon=_fo.Icon(color="red", icon="tint", prefix="fa")).add_to(_M)
            for _rt in _pins["routes"]:
                _ll = _p3m.from_local_m(_rt.get("pts") or [], _org)
                if len(_ll) >= 2:
                    # [V96] 규칙 21 — 인입관은 **주황 점선**, 주배관은 빨간 실선. 역할이 눈에 보여야 한다.
                    _isf = _p3s.route_role(_rt) == "feeder"
                    _fo.PolyLine([[_q[1], _q[0]] for _q in _ll],
                                 color="#ffa040" if _isf else "#ff4b4b", weight=5,
                                 dash_array="12,8" if _isf else None,
                                 tooltip=("인입관 %s (%s)" % (_rt.get("name") or "",
                                                            _p3s.MATERIAL_LABEL.get(_rt.get("material") or "hose50"))
                                          if _isf else "주배관 %s · 구역 %s" % (_rt.get("name") or "", _rt.get("zone")))
                                 ).add_to(_M)
            for _h in _p3_headers(_pins):
                _lo, _la = _p3m.from_local_m([_h["pt"]], _org)[0]
                _fo.CircleMarker([_la, _lo], radius=7, color="#0C3B81", weight=2, fill=True,
                                 fill_color="#F3DC18", fill_opacity=1,
                                 tooltip="분배점 — 주배관 %d갈래 · 밸브 %d" % (_h["outlets"], _h["valves"])).add_to(_M)

            # 💦 예상 살수 — 헤드 자리와 반경. 그린 것과 겹쳐 보아야 「이렇게 젖는다」가 보인다.
            _pvm = st.session_state.get("p3_preview") or {}
            if _shw and (_pvm.get("n_heads") or _pvm.get("n_dropped")):
                _rad = float((_pvm.get("spacing") or {}).get("radius_m") or 10.0)
                # 🔵 [V102] 안쪽 원 = **귀환 살수 7 m**(427B 고정). 승인 제안서 지면이 이미 두 겹으로
                #    그린다(`agri_overlay.spray_double`) — 화면과 지면이 다른 그림이면 안 된다(대표 2026-09-08).
                _rin = (_pvm.get("spacing") or {}).get("radius_in_m")
                _fgh = _fo.FeatureGroup(name="💦 예상 살수 (%d두)" % _pvm["n_heads"], show=True)
                for _bp in (_pvm.get("blocks") or []):
                    for _hp in (_bp.get("head_pts") or []):
                        _lo, _la = _p3m.from_local_m([_hp], _org)[0]
                        _fo.Circle([_la, _lo], radius=_rad, color="#78dcff", weight=1,
                                   opacity=0.55, fill=True, fill_color="#78dcff",
                                   fill_opacity=0.10,
                                   tooltip="살수 반경 %.0f m (말단 1.5 bar)" % _rad).add_to(_fgh)
                        if _rin:
                            _fo.Circle([_la, _lo], radius=float(_rin), color="#0c3b81", weight=1,
                                       opacity=0.85, fill=False, dash_array="5,5",
                                       tooltip="귀환 살수 %.0f m (427B 고정)" % float(_rin)).add_to(_fgh)
                        _fo.CircleMarker([_la, _lo], radius=2, color="#00e5ff", weight=2,
                                         fill=True, fill_opacity=1).add_to(_fgh)
                    # 🚫 [V101] 뺀 자리는 **지워 없애지 않고 회색 ✕ 로 남긴다** — 되살릴 수 있어야 한다.
                    for _dp in (_bp.get("drop_pts") or []):
                        _lo, _la = _p3m.from_local_m([_dp], _org)[0]
                        _fo.CircleMarker([_la, _lo], radius=5, color="#9aa4ae", weight=2,
                                         fill=True, fill_color="#3c4248", fill_opacity=0.85,
                                         tooltip="뺀 스프링클러 — 「🚫 스프링클러 빼기」를 켜고 누르면 되살아납니다"
                                         ).add_to(_fgh)
                    # 가지관 — **실제 경로**다. 주배관과 직각이 아니면 분기부가 곡선으로 꺾인다(규칙 14).
                    for _rl in (_bp.get("row_lines") or []):
                        _ll = _p3m.from_local_m(_rl, _org)
                        _bent = len(_rl) > 2
                        _fo.PolyLine([[_q[1], _q[0]] for _q in _ll],
                                     color="#7ee8c8" if _bent else "#9fe8ff",
                                     weight=3 if _bent else 2, opacity=0.75 if _bent else 0.5,
                                     dash_array=None if _bent else "4,6",
                                     tooltip="가지관 — 분기부 곡선" if _bent else "가지관").add_to(_fgh)
                    for _rd in _bp.get("row_details", []):
                        _ll = _p3m.from_local_m([_rd["p0"], _rd["first"]], _org)
                        _gap_text = "첫 헤드까지 %.1f m (직선 거리)" % _rd["first_m"]
                        _fo.PolyLine([[_q[1], _q[0]] for _q in _ll], color="#ffe36e", weight=3,
                                     dash_array="3,5", tooltip=_gap_text).add_to(_fgh)
                        _fo.CircleMarker([_ll[1][1], _ll[1][0]], radius=4, color="#ffe36e", fill=True,
                                         tooltip=_gap_text).add_to(_fgh)
                _fgh.add_to(_M)

            # 📏 [V102] 열별 헤드 간격 — 좁은 칸이 **숫자로** 보여야 고칠지 말지 정할 수 있다.
            if _pvm.get("blocks"):
                _grows = []
                for _bp in (_pvm.get("blocks") or []):
                    for _i2, _rd in enumerate(_bp.get("row_details") or [], 1):
                        _gp = _rd.get("gaps") or []
                        _grows.append({"밭": _bp.get("name") or "?", "가지관": _i2,
                                       "두수": _rd.get("n_heads"),
                                       "첫 헤드까지(m)": _rd.get("first_m"),
                                       "간격(m)": " · ".join("%.1f" % g for g in _gp) or "-",
                                       "가장 좁은 칸(m)": _rd.get("gap_min"),
                                       "가장 넓은 칸(m)": _rd.get("gap_max")})
                if _grows:
                    with st.expander("📏 열별 스프링클러 간격 (%d열)" % len(_grows),
                                     expanded=bool(_pvm.get("gap_max", 0) and
                                                   (_pvm.get("gap_max") - _pvm.get("gap_min", 0)) >= 1.0)):
                        st.caption("한 열 안에서 헤드 사이 거리입니다. **끝 칸이 좁으면** 규칙 11(말단 보충)로 "
                                   "헤드를 하나 더 넣은 것입니다 — 위 **「📏 열 안 균등 정렬」**을 켜면 "
                                   "**첫·마지막을 그대로 두고** 사이를 고르게 놓습니다(두수는 그대로).")
                        st.dataframe(pd.DataFrame(_grows), width="stretch", hide_index=True)

            # 🧭 고랑 방향 — 밭마다 가운데를 지나는 선으로 그려 **눈으로 확인**하게 한다(#74).
            for _bk in _pins["blocks"]:
                _pg = _bk.get("polygon") or []
                if len(_pg) < 3:
                    continue
                _uu = _bk.get("u") or [1.0, 0.0]
                _cx = sum(q[0] for q in _pg) / len(_pg)
                _cy = sum(q[1] for q in _pg) / len(_pg)
                _ext = max(max(q[0] for q in _pg) - min(q[0] for q in _pg),
                           max(q[1] for q in _pg) - min(q[1] for q in _pg)) * 0.42
                _seg = [[_cx - _uu[0] * _ext, _cy - _uu[1] * _ext],
                        [_cx + _uu[0] * _ext, _cy + _uu[1] * _ext]]
                _ll = _p3m.from_local_m(_seg, _org)
                _fo.PolyLine([[_q[1], _q[0]] for _q in _ll], color="#b6ff5c", weight=3,
                             opacity=0.95, dash_array="14,7",
                             tooltip="가지관(고랑) 방향 %d° · %s"
                                     % (round(math.degrees(math.atan2(_uu[1], _uu[0]))),
                                        _bk.get("name") or "")).add_to(_M)

            # 🔴 한국어 이름표는 **Draw 보다 먼저** 붙는다(상수 주석 참조).
            _lc = _fo.MacroElement()
            _lc._template = _BrancaTemplate(P3_DRAW_LOCALE_JS.replace("주배관", "관"))
            _M.add_child(_lc)
            _draw = _FoDraw(export=False, position="topleft",
                    draw_options={"polyline": {"shapeOptions": {"color": "#ffa040" if _draw_role == "feeder" else "#ff4b4b", "weight": 5}},
                                  "polygon": {"shapeOptions": {"color": "#ffd600", "weight": 4}},
                                  "marker": True,          # 급수원 — 도구를 켜야만 찍힌다(#66)
                                  "rectangle": False, "circle": False, "circlemarker": False},
                    # 🔴 [V90] `edit_options={"edit": True, ...}` 가 **점 편집을 죽이고 있었다**.
                    #    leaflet.draw 의 EditToolbar 는 `options.edit` 를 **객체로** 받아
                    #    거기 있는 `selectedPathOptions` 로 `layer.options.editing` 을 채운다.
                    #    `True` 를 주면 그 객체가 사라져 `options.editing.className` 에서 TypeError 가 나고
                    #    **꼭짓점 손잡이가 하나도 안 생긴다**(마커는 이 경로를 안 타서 혼자만 됐다).
                    #    2026-09-07 브라우저 재현 — A(지금) 0개 · B(옵션 없음) 8개 · C(제대로된 객체) 8개.
                    edit_options={
                        "poly": {"allowIntersection": False},
                        "selectedPathOptions": {"dashArray": "10, 10", "fill": True,
                                                "fillColor": "#78dcff", "fillOpacity": 0.12,
                                                "maintainColor": False}}).add_to(_M)
            _p3edit.draw_bridge(_draw, _p3edit.handles(_pvm, _org, _rev) if _edit_rows else [],
                                role=_draw_role, drafts=st.session_state.get("p3_map_drafts") or [],
                                head_features=(_p3edit.head_marks(_pvm, _org, _rev)
                                               if _pick_heads else []),
                                mode=("add" if _add_heads else
                                      "drop" if _pick_heads else "none"),
                                rev=_rev).add_to(_M)
            _FoGeo(collapsed=True, position="topright", add_marker=False, zoom=18).add_to(_M)
            try:
                _vkey = (_p3m._keys().get("vworld") or {}).get("key", "")
            except Exception:
                _vkey = ""
            if not _vkey:
                st.caption("🔵 지도 안 「지번 검색」이 없습니다 — Streamlit `secrets` 에 "
                           "`[map_keys.vworld]` 가 있어야 뜹니다. 검색 없이도 지도는 씁니다.")
            if _vkey:
                _sr = _fo.MacroElement()
                _sr._template = _BrancaTemplate(P3_SEARCH_JS.replace("__KEY__", _vkey))
                _M.add_child(_sr)
            # 본 자리를 **브라우저 안에서** 기억한다 — 서버를 안 타므로 깜빡임이 없다(#66).
            _vjs = _fo.MacroElement()
            _vjs._template = _BrancaTemplate(
                P3_VIEW_JS.replace("__NONCE__", str(st.session_state.get("p3_move_nonce", 0))))
            _M.add_child(_vjs)
            _fo.LayerControl(collapsed=True).add_to(_M)

            # 🔴 `center`·`zoom` 을 되받지 않는다 — 되받으면 **확대·이동할 때마다 다시 그려져**
            #    화면이 깜빡이고 그리던 것이 끊긴다(대표 실사용 2026-09-07). 자리는 위 JS 가 지킨다.
            _out = _st_folium(_M, height=600, width=None, key="p3_map",
                              returned_objects=["all_drawings", "last_active_drawing"])
            # 🔴 [V100] 가지관 이동이 거부되면 **지도 바로 아래**에 이유를 적는다 — 위쪽에 띄우니 못 보고
            #    「깜빡이고 원상복구된다」로 보였다(대표 2026-09-08). 되돌린 것은 엔진이고 이유가 있다.
            if st.session_state.get("p3_row_message"):
                st.error("↔ " + st.session_state.pop("p3_row_message")
                         + "  \n옮길 수 있는 범위 — **이웃 가지관과 6 m 이상** · **밭 안쪽**. "
                         "가지관을 **돌리려면** 손잡이가 아니라 위 표의 **고랑 방향(도)** 또는 🧭 를 쓰세요.")

            # [V99] 지도 재생성 초기값 None은 '도형 없음'이 아니다. 화면에 복원한 도형으로 집계/반영.
            _dws = _p3edit.drawing_snapshot(_out, st.session_state.get("p3_map_drafts"))
            _moved, _move_error = _p3edit.move_rows(_pins["blocks"], _pins["routes"], _pvm,
                                                  [(_out or {}).get("last_active_drawing") or {}], _org, _rev)
            st.session_state.p3_map_drafts = _dws
            # 🚫 [V101] 스프링클러 빼기·되살리기. 손잡이와 **같은 통로**(draw:edited)로 오고
            #    표식의 `kind` 로 갈린다. 지난 클릭은 `revision` 이 달라 다시 적용되지 않는다.
            _dropped, _drop_error = _p3edit.toggle_heads(
                _pins["blocks"], [(_out or {}).get("last_active_drawing") or {}], _rev)
            if _drop_error:
                st.session_state.p3_row_message = "스프링클러를 빼지 못했습니다: " + _drop_error
                st.session_state.p3_map_epoch = st.session_state.get("p3_map_epoch", 0) + 1
                st.rerun()
            if _dropped is not None:
                _pins["blocks"] = _dropped
                st.session_state.pop("p3_result", None)
                st.session_state.pop("p3_site", None)
                st.rerun()
            # ➕ [V102] 빈 자리를 누르면 가장 가까운 가지관에 한 두 더(대표 요청 2026-09-08).
            _added, _add_error = _p3edit.add_head(
                _pins["blocks"], _pins["routes"],
                [(_out or {}).get("last_active_drawing") or {}], _org, _rev)
            if _add_error:
                st.session_state.p3_row_message = "스프링클러를 놓지 못했습니다: " + _add_error
                st.session_state.p3_map_epoch = st.session_state.get("p3_map_epoch", 0) + 1
                st.rerun()
            if _added is not None:
                _pins["blocks"] = _added
                st.session_state.pop("p3_result", None)
                st.session_state.pop("p3_site", None)
                st.rerun()
            if _move_error:
                st.session_state.p3_row_message = "가지관 이동을 적용하지 못했습니다: " + _move_error
                st.session_state.p3_map_epoch = st.session_state.get("p3_map_epoch", 0) + 1
                st.rerun()
            if _moved is not None:
                _pins["blocks"] = _moved
                st.session_state.pop("p3_result", None)
                st.session_state.pop("p3_site", None)
                st.rerun()
            _gt = lambda f: ((f or {}).get("geometry") or {}).get("type")
            _polys = [_f for _f in _dws if _gt(_f) == "Polygon"]
            _lines = [_f for _f in _dws if _gt(_f) == "LineString"]
            _points = [_f for _f in _dws if _gt(_f) == "Point"]

            st.caption("지금 지도에 **그려 놓은 것** — 💧급수원 %d · 🟨밭 %d · 📐관 %d. "
                       "아래 단추를 눌러야 목록으로 들어갑니다."
                       % (len(_points), len(_polys), len(_lines)))
            _ca, _cb = st.columns([2, 1])
            if _ca.button("✅ 그린 것을 목록에 넣기 (급수원 %d · 밭 %d · 관 %d)"
                          % (len(_points), len(_polys), len(_lines)),
                          type="primary", key="p3_take_all",
                          disabled=not (_points or _polys or _lines)):
                if _polys:
                    # 🔴 **그린 그대로**(`polygon_raw`)를 남긴다 — 둥글게는 언제든 되돌릴 수 있어야 한다.
                    _old_blocks = _pins["blocks"]
                    _pins["blocks"] = []
                    for _i, _f in enumerate(_polys):
                        _raw = _p3m.to_local_m(_f["geometry"]["coordinates"][0], _org)
                        _same = next((_b for _b in _old_blocks if (_b.get("polygon_raw") or _b.get("polygon")) == _raw), None)
                        if _same is not None:
                            _pins["blocks"].append(_same)
                            continue
                        # 🔴 [V91] 기본은 **0 = 그린 그대로**다. 1 로 두었더니 점이 적은 밭이
                        #    「계란 모양」이 됐다(대표 2026-09-07). 둥글게는 **골라서 쓰는 것**이다.
                        _sm = 0
                        _pg = _p3m.smooth_ring(_raw, _sm)
                        # 🔵 [V100] 고랑 방향 기본 = **밭의 긴 변**(동쪽 고정이 기울어진 밭에서 사선을 만들었다 ·
                        #    대표 2026-09-08). 부호는 같은 단추로 찍은 급수원까지 보고 밭 안쪽으로 맞춘다.
                        _src_pts = [_x["pt"] for _x in _pins["sources"] if _x.get("pt")] + [
                            _p3m.to_local_m([_f2["geometry"]["coordinates"]], _org)[0] for _f2 in _points]
                        _u0 = _p3_orient(_p3v.long_axis_u(_pg), {"polygon": _pg}, {"sources": [{"pt": q} for q in _src_pts]})
                        _pins["blocks"].append(
                            {"id": "B%d" % (_i + 1), "name": chr(65 + _i),
                             "polygon_raw": _raw, "smooth": _sm, "polygon": _pg,
                             "area_m2": round(_p3m.polygon_area_m2(_pg), 1),
                             # 🔴 [V101] 작물은 **모르면 None**. ""로 두었더니 ④에서
                             #    「crop 은 비어 있지 않은 문자열이어야 한다」로 설계가 멈췄다.
                             # 🔵 [V105] ①에 적은 작물을 **새 밭에 바로 넣는다** — 적었는데 표가 비어
                             #    있으면 안 들어간 줄 아신다(대표 2026-09-09).
                             "u": _u0, "crop": _p3_crop() or None,
                             # 🔴 대표 확답 2026-09-08 — 「설치간격은 가지관이나 스프링클러나 14 m,
                             #    첫 시작은 7 m」. 427B 권장값이고 **신규 현장의 기본**이다.
                             #    (승인본 재현은 `reproduce.py` 가 자기 policy 를 주므로 무영향.)
                             "policy": {"S": 14.0, "lat_gap": 14.0, "std": 7.0, "maxm": 8.0}})
                if _lines:
                    # 🔵 [V93] 구역을 **그린 순서대로 1·2…** 로 매겨 둔다 — 표에서 고칠 수 있다.
                    #    비워 두면 「공통 구간(펌프→매니폴드)」이라 구역이 하나도 안 생기고,
                    #    그 상태를 대표가 알아채기 어려웠다(2026-09-07 실사용).
                    #    [V96] 규칙 21 — 선마다 **역할**이 있다: 주배관(main) 기본. 급수원에서 분배점까지의
                    #    선은 표에서 「인입관」으로 바꾼다(구역 없음 · 재질 있음).
                    _pins["routes"] = _p3edit.merge_routes(_pins["routes"], _lines, _org, _draw_role)
                if _points:
                    _pins["sources"] = [
                        {"id": "S%d" % (_i + 1),
                         "name": "물탱크" if _i == 0 else "급수점 %d" % (_i + 1),
                         "pt": _p3m.to_local_m([_f["geometry"]["coordinates"]], _org)[0],
                         "start_bands": 4 if _i == 0 else 0, "tees_here": 0}
                        for _i, _f in enumerate(_points)]
                st.session_state.p3_pins = _pins
                st.rerun()
            if _cb.button("🗑 목록 전부 비우기", key="p3_clear_all",
                          disabled=not (_pins["blocks"] or _pins["sources"] or _pins["routes"])):
                st.session_state.p3_pins = {"sources": [], "routes": [], "blocks": []}
                st.session_state.p3_map_drafts = []
                st.rerun()

            # ── 목록 — 여기서 이름·종류를 정하고, 줄을 지워 없앤다 ──
            _KINDS = ["물탱크", "관정", "펌프", "상수도 인입", "급수 지점"]
            if _pins["sources"]:
                st.markdown("##### 💧 급수원")
                st.caption("**종류**를 골라 주세요 — 지도에 찍은 순서대로입니다. 줄을 지우면 없어집니다.\n\n"
                           "· **시작부 호스밴드** = 그 급수점에서 **호스를 무는** 밴드 개수"
                           "(자재의 「시작 4 + …」가 이 값입니다).  🔴 **파이프(나사식·조임식)로 시작하면 "
                           "밴드가 들어가지 않습니다**(대표 2026-09-09) — 그 자리 부속은 아래 **급수 계통 품목**으로 넣습니다. "
                           "승인 시공 실측은 **0·2·4** 로 제각각입니다 — 펌프·여과기·카플러가 몇 번 물리느냐에 달렸기 때문이라 "
                           "엔진이 정하지 않고 대표가 적습니다.\n"
                           "· **이 자리 T** = 급수점 **그 지점에서 갈라지는 T 개수**를 대표가 못 박는 칸입니다. "
                           "비워 두면(0) **엔진이 셉니다** — 한 점에서 만나는 관의 끝이 **2개면 일자 연결(T 0)**, "
                           "**3개면 T 1개**입니다. 인입관 하나에 주배관 하나가 이어지면 T 가 아니라 **일자 연결**이고, "
                           "인입관 하나에서 주배관이 **좌우 둘**로 갈라지면 그 자리가 **T 1개**입니다.")
                _sdf = pd.DataFrame([{"id": _s.get("id") or "S%d" % (_i + 1), "종류": _s["name"],
                                      "x(동,m)": round(_s["pt"][0], 1), "y(북,m)": round(_s["pt"][1], 1),
                                      "시작부 호스밴드(개)": int(_s.get("start_bands", 0)),
                                      "이 자리 T(개)": int(_s.get("tees_here", 0))}
                                     for _i, _s in enumerate(_pins["sources"])])
                _sed = st.data_editor(
                    _sdf, width="stretch", hide_index=True, num_rows="dynamic", key="p3_src_ed",
                    disabled=["id", "x(동,m)", "y(북,m)"],
                    column_config={"종류": st.column_config.SelectboxColumn(options=_KINDS,
                                                                            required=False),
                                   "시작부 호스밴드(개)": st.column_config.NumberColumn(
                                       min_value=0, max_value=12,
                                       help="그 급수점에서 **호스를 무는** 밴드 개수. 파이프(나사식·조임식) "
                                            "연결에는 들어가지 않습니다. 승인 시공 실측 0·2·4 — 계통 구성에 달렸습니다."),
                                   "이 자리 T(개)": st.column_config.NumberColumn(
                                       min_value=0, max_value=8,
                                       help="0 = 엔진이 센다. 한 점에 관 끝이 2개면 일자 연결, 3개면 T 1개.")})
                _byid = {_s.get("id"): _s for _s in _pins["sources"]}
                _new = []
                for _, _r in _sed.iterrows():
                    _s = _byid.get(_r["id"])
                    if not _s:
                        continue
                    _s["name"] = "급수점" if pd.isna(_r["종류"]) else str(_r["종류"])
                    _s["start_bands"] = (0 if pd.isna(_r["시작부 호스밴드(개)"])
                                         else int(_r["시작부 호스밴드(개)"]))
                    _s["tees_here"] = 0 if pd.isna(_r["이 자리 T(개)"]) else int(_r["이 자리 T(개)"])
                    _new.append(_s)
                if len(_new) != len(_pins["sources"]):
                    _pins["sources"] = _new
                    st.session_state.p3_pins = _pins
                    st.rerun()
                _pins["sources"] = _new
                _qs = [_q for _b in _pins["blocks"] for _q in (_b.get("polygon") or [])]
                if _qs and _pins["sources"]:
                    st.caption("가장 가까운 밭까지 — " + " · ".join(
                        "%s %.0f m" % (_s["name"], min(
                            ((_s["pt"][0] - _q[0]) ** 2 + (_s["pt"][1] - _q[1]) ** 2) ** 0.5
                            for _q in _qs)) for _s in _pins["sources"]))

            if _pins["blocks"]:
                st.markdown("##### 🟨 밭 구역")
                st.caption("**간격** — 기본은 **헤드 14 · 열 14 · 첫 여백 7 m**"
                           "(427B 권장 · 대표 확답 2026-09-08). 좁히면 두수가 늘고 촘촘해집니다. "
                           "바꾸면 위 지도의 **💦 예상 살수**와 아래 숫자가 다시 계산됩니다.")
                st.caption("**둥글게 0~3** — 기본은 **0(그린 그대로)** 입니다. 올리면 모서리가 깎여 "
                           "부드러워지지만 **점이 적으면 계란처럼 됩니다** — 면적을 보고 정하세요. "
                           "🔴 **고랑(열) 방향은 대표 입력입니다** — 0°=동 · 90°=북. "
                           "**새 밭은 긴 변 방향이 기본**이고, 앞뒤 부호는 엔진이 **급수원에서 밭 안쪽으로** 맞춥니다"
                           "(-25° 를 적으면 155° 로 보일 수 있습니다 — 같은 고랑입니다). "
                           "작물은 알면 넣습니다. 줄을 지우면 없어집니다.")
                _bdf = pd.DataFrame([{"id": _b.get("id") or "B%d" % (_i + 1), "이름": _b["name"],
                                      "둥글게": int(_b.get("smooth", 0)),
                                      "면적(m²)": _b["area_m2"],
                                      "평": round(_b["area_m2"] / 3.3058),
                                      "작물": _b.get("crop") or "",
                                      "고랑 방향(도)": round(math.degrees(
                                          math.atan2(_b["u"][1], _b["u"][0]))),
                                      "헤드 간격(m)": float((_b.get("policy") or {}).get("S", 14.0)),
                                      "열 간격(m)": float((_b.get("policy") or {}).get("lat_gap", 14.0)),
                                      "첫 여백(m)": float((_b.get("policy") or {}).get("std", 7.0))}
                                     for _i, _b in enumerate(_pins["blocks"])])
                _bed = st.data_editor(
                    _bdf, width="stretch", hide_index=True, num_rows="dynamic",
                    disabled=["id", "면적(m²)", "평"], key="p3_bl_ed",
                    column_config={
                        "둥글게": st.column_config.NumberColumn(
                            min_value=0, max_value=_p3m.SMOOTH_MAX, step=1,
                            help="0 = 그린 그대로 · 1~3 = 모서리를 점점 더 둥글게"),
                        "헤드 간격(m)": st.column_config.NumberColumn(
                            min_value=4.0, max_value=20.0, step=0.5,
                            help="한 줄 안에서 헤드 사이 거리. 427B 권장 14 · 승인 배추밭 10."),
                        "열 간격(m)": st.column_config.NumberColumn(
                            min_value=4.0, max_value=20.0, step=0.5,
                            help="줄과 줄 사이 거리. 427B 권장 14 · 승인 배추밭 10."),
                        "첫 여백(m)": st.column_config.NumberColumn(
                            min_value=2.0, max_value=12.0, step=0.5,
                            help="주배관에서 첫 헤드까지. 427B 권장 7 · 승인 배추밭 5.")})
                _byid = {_b.get("id"): _b for _b in _pins["blocks"]}
                _new, _chg = [], False
                for _, _r in _bed.iterrows():
                    _b = _byid.get(_r["id"])
                    if not _b:
                        continue
                    _old_labels = (_b.get("name"), _b.get("crop") or "")
                    _b["name"] = ("" if pd.isna(_r["이름"]) else str(_r["이름"])) or _b["id"]
                    # 🔴 [V101] 빈 칸 = 「모른다」 = None. ""는 값이 아니라서 설계가 거부한다.
                    _b["crop"] = ("" if pd.isna(_r["작물"]) else str(_r["작물"]).strip()) or None
                    if _old_labels != (_b["name"], _b["crop"] or ""):
                        _chg = True
                    # 🔴 [V94] 각도를 바꿔도 **다시 계산하라는 신호를 안 보내고 있었다** —
                    #    값은 들어갔는데 미리보기·지도가 그대로라 「안 먹힌다」로 보였다(대표 2026-09-08).
                    _dg = _r["고랑 방향(도)"]
                    _th = math.radians(0.0 if pd.isna(_dg) else float(_dg))
                    _u_new = [round(math.cos(_th), 6), round(math.sin(_th), 6)]
                    # 🔴 [V100] 표에 적은 각도도 **부호를 엔진이 맞춘다** — -25° 를 적으면 주배관 쪽을 향해
                    #    열이 주배관에 안 닿았다(대표 2026-09-08 「-25도를 적용하니까 가지관이 한 줄만」).
                    #    🧭 만 뒤집던 것을 표·새 밭 기본값과 한 규칙으로(`_p3_orient`). 표에는 맞춘 각도가 보인다.
                    _u_new = _p3_orient(_u_new, _b, _pins)
                    # 표는 정수 각도라 🧭·긴 변으로 잡은 소수 각도가 매번 재양자화되면 수동 열이 풀린다 — 1° 안이면 같은 값.
                    _u_old = list(_b.get("u") or [])
                    if _u_old:
                        _dd = (math.degrees(math.atan2(_u_new[1], _u_new[0]) - math.atan2(_u_old[1], _u_old[0]))
                               + 180.0) % 360.0 - 180.0
                        if abs(_dd) < 1.0:
                            _u_new = _u_old
                    if _u_new != _u_old:
                        _b["u"] = _u_new
                        (_b.get("policy") or {}).pop("manual_rows", None)
                        (_b.get("policy") or {}).pop("drop_heads", None)
                        _chg = True
                    # 둥글게는 **매번 그린 그대로에서 다시 만든다** — 깎은 것을 또 깎지 않는다.
                    # 간격 — 바뀌면 미리보기가 다시 돈다(캐시 서명에 policy 가 들어 있다).
                    _pol = dict(_b.get("policy") or {})
                    for _key, _col, _dflt in (("S", "헤드 간격(m)", 14.0),
                                              ("lat_gap", "열 간격(m)", 14.0),
                                              ("std", "첫 여백(m)", 7.0)):
                        _val = _dflt if pd.isna(_r[_col]) else float(_r[_col])
                        if _val != _pol.get(_key):
                            # 🚫 [V101] 간격이 바뀌면 헤드 자리가 통째로 옮겨진다 —
                            #    빼 놓은 자리는 뜻을 잃으므로 함께 푼다(다시 보고 빼신다).
                            _pol.pop("drop_heads", None)
                        if _key == "lat_gap" and _val != _pol.get(_key):
                            _pol.pop("manual_rows", None)
                        _pol[_key] = _val
                    _pol["maxm"] = max(float(_pol.get("maxm") or 0), float(_pol["std"]) + 1.0)
                    # 🔴 첫 여백은 **규칙으로 고정**한다(대표 확답 「7 m 를 띄어야 한다」).
                    #    안 고정하면 배치기가 floor~maxm 을 훑어 두수가 많은 쪽을 골라 버린다.
                    _pol["off_fixed"] = float(_pol["std"])
                    if _pol != (_b.get("policy") or {}):
                        _b["policy"] = _pol
                        _chg = True
                    _sm = 0 if pd.isna(_r["둥글게"]) else int(_r["둥글게"])
                    if _sm != int(_b.get("smooth", -1)) or not _b.get("polygon"):
                        (_b.get("policy") or {}).pop("manual_rows", None)
                        (_b.get("policy") or {}).pop("drop_heads", None)
                        _b["smooth"] = _sm
                        _b["polygon"] = _p3m.smooth_ring(_b.get("polygon_raw") or _b["polygon"], _sm)
                        _b["area_m2"] = round(_p3m.polygon_area_m2(_b["polygon"]), 1)
                        _chg = True
                    _new.append(_b)
                if _chg or len(_new) != len(_pins["blocks"]):
                    _pins["blocks"] = _new
                    st.session_state.p3_pins = _pins
                    st.rerun()
                _pins["blocks"] = _new
                _tot = sum(_b["area_m2"] for _b in _pins["blocks"])
                # 🧭 [V94] 고랑 방향을 **지도에서** 잡는다 — 각도를 숫자로 넣는 건 감이 안 온다.
                #    ╱(선)으로 고랑을 하나 그어 두고 이 단추를 누르면 그 선의 방향이 들어간다.
                st.caption("🧭 **가지관(고랑) 방향을 지도에서 잡으려면** — 왼쪽 **╱(선)** 으로 "
                           "고랑을 따라 선을 하나 긋고 아래 단추를 누르세요. "
                           "**어느 쪽으로 그으셔도 됩니다** — 급수원에서 밭 안쪽으로 향하게 알아서 돌려 놓습니다. "
                           "그 뒤 그 선은 **🗑 로 지우고** 주배관을 그리시면 됩니다.\n\n"
                           "🔵 **가지관은 필요하면 엔진이 둥글게 꺾습니다** — 주배관과 직각에서 "
                           "**20° 이상** 벗어나면 분기부를 곡선으로 잇습니다(설계 규칙 14). "
                           "그 곡선은 위 지도에 **연한 초록 실선**으로 나옵니다.")
                if st.button("🧭 그린 선 %d개로 가지관 방향 잡기" % len(_lines),
                             key="p3_furrow", disabled=not _lines):
                    _fur = []
                    for _f in _lines:
                        _pp = _p3m.to_local_m(_f["geometry"]["coordinates"], _org)
                        if len(_pp) >= 2:
                            _dx = _pp[-1][0] - _pp[0][0]
                            _dy = _pp[-1][1] - _pp[0][1]
                            _n = math.hypot(_dx, _dy)
                            if _n > 1e-6:
                                _mid = [(_pp[0][0] + _pp[-1][0]) / 2, (_pp[0][1] + _pp[-1][1]) / 2]
                                _fur.append((_mid, [_dx / _n, _dy / _n]))
                    if _fur:
                        for _b in _pins["blocks"]:
                            _pg = _b.get("polygon") or []
                            _c = [sum(q[0] for q in _pg) / len(_pg),
                                  sum(q[1] for q in _pg) / len(_pg)] if _pg else [0, 0]
                            # 밭마다 **가장 가까운 선**의 방향을 쓴다(선이 하나면 전부 같은 방향).
                            _mid, _uu = min(_fur, key=lambda t: (t[0][0] - _c[0]) ** 2
                                            + (t[0][1] - _c[1]) ** 2)
                            # 🔴 `u` 는 **주배관 쪽 → 밭 안쪽**이다(`layout.py`) — 부호가 뒤집히면
                            #    열이 주배관에 안 닿아 「급수 불가」가 뜬다(2026-09-08 실측).
                            #    그린 선의 방향이 어느 쪽이든, **급수원에서 멀어지는 쪽**으로 돌려 놓는다(V100: `_p3_orient`).
                            _b["u"] = _p3_orient(_uu, _b, _pins)
                            (_b.get("policy") or {}).pop("manual_rows", None)
                            (_b.get("policy") or {}).pop("drop_heads", None)
                        st.session_state.p3_pins = _pins
                        st.rerun()
                st.caption("합계 **%s m² (%s 평)** · %d구역"
                               % (format(round(_tot), ","), format(round(_tot / 3.3058), ","),
                                  len(_pins["blocks"])))

            # ── 🚰 [V106] 급수 계통 품목(규칙 7) — 지금까지 **화면에 입구가 없었다**.
            #    대표 2026-09-09 「펌프나 여과기에서 플라스틱 파이프로 구조화하고 지면으로 내린 후 호스로…
            #    펌프 상단에 여과기를 직결하고 여과기 나가는 부분에서 호스로… 고려해야 할 사항들이 많아.」
            #    🔴 그 구성은 **대표 판단**이다(규칙 7). 엔진은 짓지 않고 **적을 자리**를 낸다.
            with st.expander("🚰 급수 계통 품목 — 펌프·여과기·압력계·카플러 (규칙 7 · 대표 입력) %s"
                             % (("· **%d품목**" % len(_pins.get("water_items") or []))
                                if _pins.get("water_items") else "· 아직 없음"),
                             expanded=bool(_pins.get("water_items"))):
                st.caption("급수원에서 첫 관까지 사이에 들어가는 것들입니다 — **펌프 토출측 카플러 · 여과기 · "
                           "압력계 · 매니폴드 · 나사/조임식 부속**. 이 자리는 현장마다 달라 **엔진이 만들지 않습니다**"
                           "(불변 원칙 1). 여기 적은 것은 자재 목록에 **그대로** 들어갑니다.\n\n"
                           "예 — ⓐ 펌프 → 플라스틱 파이프로 구조화 → 지면 → 호스로 주배관 "
                           "ⓑ 펌프 상단에 여과기 직결 → 여과기 출구에서 호스로 주배관. "
                           "둘은 **부속이 다릅니다** — 실제 구성대로 적어 주세요.")
                _wl = _pins.setdefault("water_items", [])
                _prods = st.session_state.db.get("products", [])
                _pmap = {}
                for _pr in _prods:
                    _cd = str(_pr.get("code", "")).strip().zfill(5)
                    if _cd:
                        _pmap[_cd] = "%s · %s %s" % (_cd, _pr.get("name", ""), _pr.get("spec", ""))
                _wq = st.text_input("품목 찾기 (이름·규격·코드)", key="p3_wi_q").strip()
                _opts = [c for c, lbl in sorted(_pmap.items())
                         if not _wq or _wq.lower() in lbl.lower()][:60]
                _c1, _c2, _c3 = st.columns([4, 1, 1])
                _pick = _c1.selectbox("품목", _opts, key="p3_wi_pick",
                                      format_func=lambda c: _pmap.get(c, c),
                                      index=0 if _opts else None,
                                      help="Products 시트가 정본입니다. 못 찾으면 검색어를 바꿔 보세요.")
                _qty = _c2.number_input("수량", min_value=1, max_value=99, value=1, step=1, key="p3_wi_qty")
                if _c3.button("추가", key="p3_wi_add", disabled=not _opts):
                    _hit = next((w for w in _wl if w["code"] == _pick), None)
                    if _hit:
                        _hit["qty"] = int(_hit.get("qty", 0)) + int(_qty)
                    else:
                        _wl.append({"code": _pick, "qty": int(_qty), "note": "급수 계통(규칙 7) — 대표 입력"})
                    st.session_state.p3_pins = _pins
                    st.session_state.pop("p3_result", None)
                    st.rerun()
                if _wl:
                    _wdf = pd.DataFrame([{"코드": w["code"], "품목": _pmap.get(w["code"], "(시트에 없음)"),
                                          "수량": int(w.get("qty", 1)), "비고": w.get("note", "")}
                                         for w in _wl])
                    _wed = st.data_editor(_wdf, width="stretch", hide_index=True, num_rows="dynamic",
                                          disabled=["코드", "품목"], key="p3_wi_ed")
                    _new_w = []
                    for _, _r in _wed.iterrows():
                        _cd = str(_r["코드"]).strip()
                        if not _cd or _cd == "nan":
                            continue
                        _new_w.append({"code": _cd,
                                       "qty": 1 if pd.isna(_r["수량"]) else max(1, int(_r["수량"])),
                                       "note": "" if pd.isna(_r["비고"]) else str(_r["비고"])})
                    if _new_w != _wl:
                        _pins["water_items"] = _new_w
                        st.session_state.p3_pins = _pins
                        st.session_state.pop("p3_result", None)
                        st.rerun()
                    _miss = [w["code"] for w in _wl if w["code"] not in _pmap]
                    if _miss:
                        st.warning("시트에서 못 찾은 코드 — %s. 단가가 없으면 견적에서 빠집니다."
                                   % ", ".join(_miss))
                else:
                    st.caption("🔵 비워 두셔도 설계는 돕니다 — 다만 **급수원 쪽 부속은 견적에 빠집니다.**")

            if _pins["routes"]:
                st.markdown("##### 📐 인입관 · 주배관")
                # 🔵 [V96] 규칙 21(#79) — 선마다 **역할**을 고른다. 「구역을 비우세요」 안내는 없앴다.
                #    인입관 = 급수원 → 분배점(물을 옮기기만 · 가지관 없음 · 구역 없음 · 재질 있음).
                #    주배관 = 분배점 → 밭(가지관 분기 · 한 선 = 한 구역).
                st.caption("**역할**: 급수원에서 밭 입구(분배점)까지의 선은 **인입관**, 밭 안에서 가지관을 내는 선은 "
                           "**주배관**입니다. 주배관은 **그린 순서대로 1·2… 구역**을 매겨 두었습니다(대표 입력).\n\n"
                           "🔵 **재질·관경은 인입관과 주배관 둘 다** 고릅니다(대표 2026-09-09 — 같을 수도, 다를 수도 있습니다). "
                           "비우면 **송수호스 50**입니다. **수도 파이프·매설관**을 고르면 그 관은 **우리 자재가 아니므로** "
                           "롤·이음에서 빠지고, **관경(mm)** 을 적어야 합니다 — 모르면 설계가 멈춥니다(불변 원칙 1). "
                           "송수호스 주배관의 호칭은 **엔진이 말단 1.5 bar 로 고릅니다**(④ 「구역별 관경 선정 근거」).")
                _mat_lbl = {None: "", **_p3s.MATERIAL_LABEL}
                _lbl_mat = {_v: _k for _k, _v in _p3s.MATERIAL_LABEL.items()}
                _rdf = pd.DataFrame([{"id": _r.get("id") or "R%d" % (_i + 1), "이름": _r["name"],
                                      "역할": _p3s.ROLE_LABEL[_p3s.route_role(_r)],
                                      "구역": _r.get("zone"),
                                      "재질": _mat_lbl.get(_r.get("material")) or "",
                                      "관경(mm)": _r.get("d_mm"),
                                      "점": len(_r["pts"]),
                                      "길이(m)": round(sum(
                                          ((_r["pts"][_j][0] - _r["pts"][_j - 1][0]) ** 2 +
                                           (_r["pts"][_j][1] - _r["pts"][_j - 1][1]) ** 2) ** 0.5
                                          for _j in range(1, len(_r["pts"]))), 1)}
                                     for _i, _r in enumerate(_pins["routes"])])
                _red = st.data_editor(
                    _rdf, width="stretch", hide_index=True, num_rows="dynamic",
                    disabled=["id", "점", "길이(m)"], key="p3_rt_ed",
                    column_config={
                        "역할": st.column_config.SelectboxColumn(
                            "역할", options=["주배관", "인입관"], required=True,
                            help="인입관 = 급수원→분배점(가지관 없음) · 주배관 = 가지관 분기(구역 필수)"),
                        "재질": st.column_config.SelectboxColumn(
                            "재질", options=[""] + list(_p3s.MATERIAL_LABEL.values()),
                            help="인입관·주배관 둘 다. 비우면 송수호스 50."),
                        "관경(mm)": st.column_config.NumberColumn(
                            "관경(mm · 파이프·매설)", min_value=0, max_value=300, step=1,
                            help="수도 파이프·매설관의 **내경**. 송수호스는 비워 둡니다(호칭은 엔진이 고릅니다)."),
                    })
                _byid = {_r.get("id"): _r for _r in _pins["routes"]}
                _new = []
                for _, _r in _red.iterrows():
                    _o = _byid.get(_r["id"])
                    if not _o:
                        continue
                    _o = dict(_o)  # 변경 전 목록을 보존해야 역할·구역 수정도 감지한다.
                    _o["name"] = ("" if pd.isna(_r["이름"]) else str(_r["이름"])) or _o["id"]
                    _o["role"] = "feeder" if str(_r["역할"]) == "인입관" else "main"
                    # 🔵 [V105] 재질·관경은 **역할과 무관하게** 받는다(대표 2026-09-09).
                    _o["material"] = _lbl_mat.get(str(_r["재질"])) or "hose50"
                    _o["d_mm"] = (None if pd.isna(_r["관경(mm)"]) or not _r["관경(mm)"]
                                  else float(_r["관경(mm)"]))
                    if _o["role"] == "feeder":
                        _o["zone"] = None
                    else:
                        _o["zone"] = None if pd.isna(_r["구역"]) else int(_r["구역"])
                    _new.append(_o)
                _nfeed = sum(1 for _r in _new if _r.get("role") == "feeder")
                for _r in _new:
                    if _r.get("role") == "main" and _r.get("zone") is None:
                        st.warning("주배관 **%s** 에 구역 번호가 없습니다 — 인입관이면 역할을 「인입관」으로, "
                                   "아니면 구역을 넣으세요(규칙 21)." % _r["name"])
                    if _r.get("material") in ("pipe", "buried") and not _r.get("d_mm"):
                        st.error("%s **%s** (%s) 의 **관경을 모릅니다** — [미확정]이라 설계가 멈춥니다."
                                 % (_p3s.ROLE_LABEL[_p3s.route_role(_r)], _r["name"],
                                    _p3s.MATERIAL_LABEL[_r["material"]]))
                # 🔗 [V100] 연결 판정을 **여기서** 낸다 — 지금까지는 ④에 가야 「출발점이 닿지 않음」이 나왔다
                #    (대표 2026-09-08 「연결이 제대로 반영된 건가? 다음으로 넘어가야 알 수 있는 건가?」).
                #    ④와 같은 함수(`mainline.analyze`)라 여기서 ✅ 면 ④에서도 같다.
                if _new and _pins.get("sources"):
                    try:
                        _an = _p3ml.analyze(_new, _pins["sources"])
                    except Exception:
                        _an = None
                    if _an:
                        # [V103] 연결은 **시작점에서만** 일어나지 않는다(대표 2026-09-08).
                        #   tap  = 이 관 **중간**에 상대 끝이 붙었다(T 분배점)
                        #   tail = 이 관 **끝**에서 받는다(관을 접점 쪽으로 그린 경우)
                        _how = {"source": "급수원 「%s」", "end": "「%s」 끝", "mid": "「%s」 중간(T 분기)",
                                "tap": "「%s」 — 이 관 **중간**에 T 로 붙음", "tail": "「%s」 — 이 관 **끝**에서 받음"}
                        _ln, _bad = [], 0
                        for _rr in _an["routes"]:
                            _lab = _p3s.ROLE_LABEL.get(_rr["role"], _rr["role"])
                            if _rr["from"] == "free":
                                _bad += 1
                                # 🔴 [V102] **얼마나 떨어졌는지**를 말한다 — 「닿지 않았다」만으로는
                                #    무엇을 고쳐야 할지 알 수 없다(대표 2026-09-08 「닿지 않았다는 게 뭐지?」).
                                _gap = _rr.get("from_gap")
                                _ln.append("🔴 %s **%s** — 물을 어디서 받는지 **끊겨 있습니다**%s"
                                           % (_lab, _rr["name"],
                                              ("(가장 가까운 %s 에서 **%.1f m**)"
                                               % (_rr.get("from_near") or "것", _gap))
                                              if _gap is not None else ""))
                            else:
                                _ln.append("✅ %s **%s** ← %s" % (_lab, _rr["name"], _how[_rr["from"]] % _rr["from_ref"]))
                        if _bad:
                            st.error("🔗 **연결** — " + " · ".join(_ln))
                            st.caption("**「닿지 않았다」는 뜻** — 그 관의 **첫 점**이 급수원에서 **4 m** 안에도, "
                                       "다른 관의 끝·중간에서 **2 m** 안에도 없다는 말입니다. 그러면 엔진은 그 관에 "
                                       "**물이 어디서 오는지 모릅니다** — 분배점·T·인입관 손실을 셀 수 없고, "
                                       "그 관은 급수 계통에서 떨어져 나갑니다(설계는 돌지만 경고가 붙습니다)."
                                       "\n\n"
                                       "**고치는 법** — 지도 왼쪽 ✏️ **점 편집**으로 그 관의 **시작점**을 "
                                       "급수원 핀이나 앞 관의 **끝점 위로** 끌어다 놓으세요. "
                                       "인입관 끝에서 주배관이 시작하면 그 자리가 **분배점**이 됩니다.")
                        else:
                            st.success("🔗 **연결** — " + " · ".join(_ln)
                                       + "  \n④에서도 같은 판정입니다. **분배점 = 주배관이 물을 받는 자리**입니다 — "
                                       "인입관 끝에서 주배관이 시작해도 되고, 주배관을 한 줄로 긋고 "
                                       "인입관을 그 **중간에 T 로** 붙여도 됩니다.")
                # 🔧 [V107] 접점마다 **어떻게 잇는지** — 일자 · 엘보 · T, 그리고 그 자리 밸브
                #    대표 2026-09-09 「일자로 연결할 수도, 엘보로, 티자로. 티자는 좌우가 구역을 안 나누고도
                #    가동되면 밸브가 필요없고, 좌우 각각 구역을 나눠야 하면 좌우에 밸브로 나가면 되겠지.」
                if _new and _pins.get("sources"):
                    try:
                        _jc = _p3ml.junctions(_new, _pins["sources"])
                    except Exception:
                        _jc = []
                    _jshow = [j for j in _jc if j["kind"] in ("straight", "elbow", "tee")]
                    if _jshow:
                        st.markdown("###### 🔧 관이 만나는 자리")
                        st.caption("**일자** = 꺾임 45° 이내(호스는 현장에서 굽힙니다 · 규칙 2) · "
                                   "**엘보** = 45° 초과 — 호스면 규칙 3(T 양쪽), **나사·조임식 파이프면 엘보**(규칙 7) · "
                                   "**T** = 관 끝 3갈래.  밸브는 **그 자리에서 물을 받는 주배관의 서로 다른 구역 수**입니다 "
                                   "— 좌우가 **같은 구역이면 1**(따로 여닫을 필요가 없습니다), **다른 구역이면 2**.")
                        st.dataframe(pd.DataFrame([
                            {"자리": "·".join(j["routes"]), "잇는 법": _p3ml.JOINT_KIND[j["kind"]],
                             "갈래": j["ends"],
                             "꺾임(도)": ("%.0f" % j["dev_deg"]) if j["dev_deg"] is not None else "-",
                             "재질": " / ".join(_p3s.MATERIAL_LABEL.get(m, m) for m in j["materials"]),
                             "구역": "·".join(str(z) for z in j["zones"]) or "-",
                             "밸브": j["valves"],
                             "x(동,m)": j["pt"][0], "y(북,m)": j["pt"][1]} for j in _jshow]),
                            width="stretch", hide_index=True)
                        _elb = [j for j in _jshow if j["kind"] == "elbow"]
                        if _elb:
                            st.warning("🔧 **45°를 넘는 꺾임 %d 곳** — 호스면 **규칙 3(T 양쪽)**으로, "
                                       "나사·조임식 파이프면 **엘보**로 풉니다. 그 부속은 **[미확정]**이니 "
                                       "위 **🚰 급수 계통 품목**에 넣어 주세요." % len(_elb))

                # 🔩 [V106] 재질이 바뀌는 자리 — 대표가 「고려해야 할 사항들이 많아」라고 한 그 자리들이다.
                #    엔진은 **어디서 무엇이 무엇으로 바뀌는지**만 세운다. 부속은 계통 품목(규칙 7)으로 넣는다.
                if _new and _pins.get("sources"):
                    try:
                        _trs = _p3ml.transitions(_new, _pins["sources"])
                    except Exception:
                        _trs = []
                    _mt = [t for t in _trs if t["kind"] == "material"]
                    if _mt:
                        st.warning("🔩 **재질이 바뀌는 자리 %d 곳** — %s. 그 자리 연결 부속은 **[미확정]** 입니다: "
                                   "위 **🚰 급수 계통 품목**에 넣어 주세요(규칙 7)."
                                   % (len(_mt), " · ".join("%s→%s" % (t["from"], t["to"]) for t in _mt)))
                        st.dataframe(pd.DataFrame([
                            {"자리": "%s → %s" % (t["from"], t["to"]),
                             "바뀜": "%s → %s" % (_p3s.MATERIAL_LABEL.get(t["from_material"], "-"),
                                                _p3s.MATERIAL_LABEL.get(t["to_material"], "-")),
                             "호스 끝(밴드 2개씩)": t["hose_ends"],
                             "x(동,m)": round((t["pt"] or [0, 0])[0], 1),
                             "y(북,m)": round((t["pt"] or [0, 0])[1], 1)} for t in _mt]),
                            width="stretch", hide_index=True)
                if _new != _pins["routes"]:
                    _pins["routes"] = _new
                    st.session_state.p3_pins = _pins
                    st.rerun()
                _pins["routes"] = _new
            # ── 이 밭에 무엇이 들어가는가 (밭만 그려도 나온다 · #72) ──────
            # 🔴 구역·경로·밸브는 대표 판단이지만, **그 판단에 필요한 숫자는 엔진이 먼저 낸다.**
            #    주배관을 그리기 전에도 열·헤드·요구 유량·권고 구역 수가 나온다.
            #    ⚠ 열 배치 계산이 몇 초 걸린다 — **밭이 바뀔 때만** 다시 계산한다(그대로면 캐시).
            if _pins["blocks"]:
                st.markdown("##### 📊 이 밭에 무엇이 들어가는가")
                _pv = st.session_state.get("p3_preview") or {}
                if _pv.get("error"):
                    st.error("미리보기 실패: " + _pv["error"])
                elif _pv.get("n_heads"):
                    _m1, _m2, _m3, _m4 = st.columns(4)
                    _m1.metric("스프링클러", "%d 두" % _pv["n_heads"])
                    _m2.metric("가지관 열", "%d 열" % _pv["n_rows"])
                    _m3.metric("전부 한 번에", "%s L/분" % format(_pv["q_all_ref"], ","),
                               help="설계점 %.1f bar 기준. 보증 1.5 bar 로는 %s L/분."
                                    % (_pv["p_ref_bar"], format(_pv["q_all_min"], ",")))
                    _zb = _pv.get("zones_min") or _pv.get("zones_by_pressure")
                    _m4.metric("권고 구역", ("%d 구역" % _zb) if _zb else "—",
                               help="유량을 알면 유량 기준, 모르면 **관이 감당하는 한계**로 냅니다. "
                                    "확정은 ④의 구역별 말단압입니다.")
                    _sp = _pv["spacing"]
                    st.caption("지금 간격 — 헤드 **%s m** · 열 **%s m** · 첫 여백 **%s m** "
                               "(427B 권장 %.0f / %.0f / %.0f) · 살수 반경 %.0f m(보증 1.5 bar) · "
                               "가지관 합계 %s m"
                               % (_sp.get("head_m") or "?", _sp.get("row_m") or "?",
                                  _sp.get("first_m") or "?", _sp["profile_head_m"],
                                  _sp["profile_row_m"], _sp["profile_first_m"],
                                  _sp["radius_m"], format(round(_pv["lat_total_m"]), ",")))
                    if len(_pv.get("blocks") or []) > 1:
                        st.dataframe(pd.DataFrame(
                            [{"밭": _x.get("name"), "작물": _x.get("crop") or "",
                              "면적(m²)": _x.get("area_m2"), "열": _x.get("rows"),
                              "헤드(두)": _x.get("heads"), "가지관(m)": _x.get("lat_m"),
                              "고랑(도)": _x.get("u_deg")} for _x in _pv["blocks"]]),
                            width="stretch", hide_index=True)
                    for _n in _pv.get("notes", []):
                        (st.error if _n.startswith("🔴") else
                         st.info if _n.startswith("🔵") else st.caption)(_n)
                    _zdrawn = sorted({_r.get("zone") for _r in _pins["routes"]
                                      if _r.get("zone") is not None})
                    if _zdrawn:
                        _per = math.ceil(_pv["n_heads"] / len(_zdrawn))
                        _cap = _pv.get("heads_cap_pressure") or 0
                        _msg = ("지금 **%d구역**으로 그리셨습니다 — 구역당 평균 **%d두**."
                                % (len(_zdrawn), _per))
                        if _cap and _per <= _cap:
                            st.success("✅ " + _msg + " 한 구역 상한 %d두 안에 듭니다. "
                                       "확정은 ④의 구역별 말단압입니다." % _cap)
                        elif _cap:
                            st.warning("🟠 " + _msg + " 한 구역 상한이 **%d두**라 "
                                       "**%d구역**이 필요해 보입니다 — 주배관을 더 나누거나 "
                                       "간격을 넓혀 두수를 줄이는 방법이 있습니다."
                                       % (_cap, _pv.get("zones_by_pressure") or 0))
                        else:
                            st.info(_msg)
                    st.caption("🔴 **구역을 어디서 어떻게 나눌지는 대표 판단입니다**(설계 규칙 6) — "
                               "위 숫자는 그 판단의 근거이고, 되는지는 ④가 판정합니다.")

            # ── 운전 구역 · 밸브 ──────────────────────────────────────────
            # 🔴 [V91] 구역·경로·밸브는 **대표 입력**이다(설계 규칙 6·13 · `site.py`) —
            #    엔진은 주배관을 스스로 나누지 않는다. 대신 그 구성이 **되는지**(말단 1.5 bar)를
            #    계산하고, 안 되면 「구역을 나누거나 펌프를 키워야 한다」고 말한다.
            #    그런데 밸브 칸이 JSON 업로드에만 있어 지도에서 넣을 수 없었다 — 그 자리를 만든다.
            if _pins["routes"] or _pins["blocks"]:
                st.markdown("##### 🚰 운전 구역 · 밸브")
                _zs = sorted({_r.get("zone") for _r in _pins["routes"]
                              if _r.get("zone") is not None})
                _nz = len(_zs)
                st.caption("그린 주배관의 구역 — %s. **한 번에 다 주면 1구역**이고, 나눠 주시려면 "
                           "주배관을 **여러 선으로 그려** 위 표에서 구역 번호를 1·2… 로 넣으세요. "
                           "🔴 **엔진은 스스로 나누지 않습니다**(설계 규칙 6) — 나눠야 하는지는 "
                           "④에서 구역별 말단압으로 알려 드립니다."
                           % ("· ".join(str(_z) + "구역" for _z in _zs) if _zs
                              else "**지정 없음**(전부 공통 구간)"))
                # 🔵 [V96] 규칙 21(#79) — 구역 밸브는 **분배점**(주배관이 갈라지는 자리)마다 구역 수만큼.
                #    엔진이 그린 선에서 분배점을 찾아 센다. 대표가 직접 적으면 그 값이 우선한다.
                _hdrs = _p3_headers(_pins)
                _hv = sum(_h["valves"] for _h in _hdrs)
                if _hdrs:
                    st.caption("🔀 **분배점 %d곳** — %s" % (len(_hdrs), " · ".join(
                        "주배관 %d갈래(구역 %s) → 밸브 %d" % (_h["outlets"], "·".join(str(_z) for _z in _h["zones"]), _h["valves"])
                        for _h in _hdrs)) + ("  (분배점끼리 %.0f m 안이면 한 매니폴드로 봅니다)" % _p3ml.HEADER_NEAR))
                _vv = _pins.setdefault("valves", {"start": 1, "zones": None})
                _v1, _v2 = st.columns(2)
                _vv["start"] = int(_v1.number_input(
                    "시작부 밸브 (급수점)", 0, 1, int(_vv.get("start", 1)), key="p3_v_start",
                    help="급수점 바로 뒤에 여닫는 밸브를 두면 1."))
                _auto_v = _v2.checkbox("구역 밸브는 엔진이 셉니다 — 분배점 기준 **%d개**" % _hv,
                                       value=_vv.get("zones") is None, key="p3_v_auto",
                                       help="끄면 직접 적습니다. 직접 적은 값이 우선합니다(규칙 21).")
                if _auto_v:
                    _vv["zones"] = None
                else:
                    _vv["zones"] = int(_v2.number_input(
                        "구역 밸브 개수", 0, 12, int(_vv.get("zones") if _vv.get("zones") is not None else _hv),
                        key="p3_v_zones", help="자재(BOM)에 그대로 들어갑니다."))
                    if int(_vv["zones"]) != _hv:
                        st.warning("분배점 기준은 **%d개**인데 **%d개**로 적으셨습니다 — 뜻이 있으면 그대로 두세요."
                                   % (_hv, int(_vv["zones"])))
                st.session_state.p3_pins = _pins

            st.divider()
            # 다음 한 걸음만 말한다 — 목록을 늘어놓지 않는다.
            _nb, _ns, _nr = len(_pins["blocks"]), len(_pins["sources"]), len(_pins["routes"])
            _nf = sum(1 for _r in _pins["routes"] if _p3s.route_role(_r) == "feeder")
            st.markdown("**지금까지 — 밭 %d · 급수점 %d · 인입관 %d · 주배관 %d**" % (_nb, _ns, _nf, _nr - _nf))
            if not _nb:
                st.warning("다음 → 지도 왼쪽 **⬟(면)** 으로 밭을 그린 뒤 **「그린 것을 목록에 넣기」**.")
            elif not _ns:
                st.warning("다음 → 지도 왼쪽 **📍(핀)** 을 누르고 물탱크 자리를 찍은 뒤 "
                           "**「그린 것을 목록에 넣기」**.")
            elif not _nr:
                st.warning("다음 → 지도 왼쪽 **╱(선)** 으로 급수원에서 밭까지 주배관을 그리세요.")
            else:
                st.success("다 모였습니다 → 아래 단추를 누르고 **③ 작도판**으로 가세요.")
            if st.button("✅ 이 좌표를 설계에 씁니다", type="primary", key="p3_pin_apply",
                         disabled=not (_nb and _ns and _nr)):
                _dw = dict(st.session_state.get("p3_drawn") or {})
                if _pins["blocks"]:
                    _dw["blocks"] = _p3edit.design_blocks(_pins["blocks"])
                if _pins["sources"]:
                    # `id` 는 화면 안에서만 쓰는 손잡이다 — 엔진에는 넘기지 않는다.
                    _dw["sources"] = [{_k: _v for _k, _v in _x.items() if _k != "id"}
                                      for _x in _pins["sources"]]
                if _pins["routes"]:
                    _dw["routes"] = [{_k: _v for _k, _v in _x.items() if _k != "id"}
                                     for _x in _pins["routes"]]
                _dw["water_items"] = list(_pins.get("water_items") or [])   # [V106] 규칙 7
                if _pins.get("valves"):
                    # zones None = 엔진이 분배점에서 센다(규칙 21 · #79). 대표가 적은 값은 그대로.
                    _zv = _pins["valves"].get("zones")
                    _dw["valves_01403"] = {"start": int(_pins["valves"].get("start", 1)),
                                           "zones": None if _zv is None else int(_zv)}
                st.session_state.p3_drawn = _dw
                st.success("넣었습니다 — 밭 %d · 급수점 %d · 주배관 %d · 밸브 시작 %s · 구역 %s."
                           % (len(_dw.get("blocks") or []), len(_dw.get("sources") or []),
                              len(_dw.get("routes") or []),
                              (_dw.get("valves_01403") or {}).get("start", "-"),
                              (_dw.get("valves_01403") or {}).get("zones", "-")))
            st.caption("🔴 좌표만 만듭니다 — 관경·유량·수량은 **엔진이 정합니다**(불변 원칙 1).")

            with st.expander("보조 — 작도 결과 JSON 올리기 (예전 방식)"):
                st.caption("밸브·물탱크 자재(`valves_01403`·`water_items`)처럼 지도로 못 그리는 값은 "
                           "여기로 올립니다. 같은 키는 지도에서 그린 것이 덮어씁니다.")
                st.code(P3_DRAWN_SAMPLE, language="json")
                _up = st.file_uploader("작도 결과 JSON", type=["json"], key="p3_drawn_up")
                if _up is not None:
                    try:
                        _j = json.loads(_up.getvalue().decode("utf-8"))
                        _dw = dict(st.session_state.get("p3_drawn") or {})
                        _dw.update(_j)
                        st.session_state.p3_drawn = _dw
                        st.success("올렸습니다.")
                    except Exception as _e:
                        st.error("JSON 읽기 실패: " + str(_e))
            _dw = st.session_state.get("p3_drawn")
            if _dw:
                st.info("설계에 들어갈 것 — 밭 %d · 급수점 %d · 주배관 %d · 주배관 호칭 %s"
                        % (len(_dw.get("blocks") or []), len(_dw.get("sources") or []),
                           len(_dw.get("routes") or []), _dw.get("main_mm") or "엔진 선정"))

    # ── ③ 작도판 (농민 확인용) ─────────────────────────────────────────
    #   [V83] 배경 정본이 **Esri** 로 옮겨졌다(#59) — 브이월드가 배포 서버를 거르기 때문이다.
    with _p3_steps[2]:
        st.markdown("**농민에게 보낼 판을 만듭니다.** 그린 것을 위성 위에 얹어 PNG 한 장으로 냅니다.")
        _fr = st.session_state.get("p3_map_frame")
        _pins = st.session_state.get("p3_pins") or {}
        _dw = st.session_state.get("p3_drawn") or {}
        _bl = _pins.get("blocks") or _dw.get("blocks") or []
        _sc = _pins.get("sources") or _dw.get("sources") or []
        _rt = _pins.get("routes") or _dw.get("routes") or []
        if not _fr:
            # 지도가 아직 안 열렸으면(folium 부재 등) 기준점만 세워 둔다 — 판은 그린 것에 맞춰 잡힌다.
            _fr = _p3m.frame(P3_MAP_HOME, zoom=18, size=(1024, 1024))
        if not (_bl or _sc or _rt):
            st.warning("②에서 **먼저 그려 주세요** — 밭·급수원·주배관 중 하나는 있어야 판이 나옵니다.")
        else:
            _t1, _t2 = st.columns([2, 3])
            _bg = _t1.selectbox("배경", ["자동 (브이월드 → 막히면 Esri)", "Esri 고정", "브이월드 고정"],
                                index=0, key="p3_bg")
            _ttl = _t2.text_input("판 제목", value=((st.session_state.get("p3_answers") or {})
                                                    .get("address", "") + " 일대  ·  확인 부탁드립니다").strip(),
                                  key="p3_sheet_title")
            st.caption("밭 %d · 급수점 %d · 주배관 %d 를 얹습니다. 배경 출처는 판 아래에 적힙니다."
                       % (len(_bl), len(_sc), len(_rt)))
            if st.button("작도판 만들기", type="primary", key="p3_sheet_btn"):
                _p3_keys()
                _prefer = {"자동 (브이월드 → 막히면 Esri)": "auto", "Esri 고정": "esri",
                           "브이월드 고정": "vworld"}[_bg]
                with st.spinner("위성 받는 중…"):
                    try:
                        # 🔴 판의 중심은 **원점이 아니라 그린 것**이다 — 지도를 옮겨 가며
                        #    그렸으면 원점은 엉뚱한 데 있다(대표 2026-09-07 「애매한 곳으로 나오네」).
                        #    좌표는 원점 기준 미터라 판이 옮겨지면 **새 원점 기준으로 옮겨** 넘긴다.
                        _all = ([_q for _b in _bl for _q in (_b.get("polygon") or [])]
                                + [_x["pt"] for _x in _sc]
                                + [_q for _r in _rt for _q in (_r.get("pts") or [])])
                        _o0 = _fr["origin"]
                        if _all:
                            _ffr = _p3m.fit_frame(_all, _o0, size=_fr["size"][0])
                        else:
                            _ffr = _fr

                        def _mv(_pts):
                            return _p3m.to_local_m(_p3m.from_local_m(_pts, _o0), _ffr["origin"])

                        _d = _p3m.draft_from_center(
                            _ffr["center"], zoom=_ffr["zoom"], size=_ffr["size"][0],
                            blocks_m=[dict(_b, polygon=_mv(_b["polygon"])) for _b in _bl],
                            sources_m=[dict(_x, pt=_mv([_x["pt"]])[0]) for _x in _sc],
                            routes_m=[dict(_r, pts=_mv(_r["pts"])) for _r in _rt],
                            title=_ttl, prefer=_prefer)
                        st.session_state.p3_sheet = _d
                    except Exception as _e:
                        st.session_state.p3_sheet = None
                        st.error("작도판 실패: " + str(_e))
            _sh = st.session_state.get("p3_sheet")
            if _sh:
                st.success("배경 = " + ("브이월드 위성" if _sh["basemap"] == "vworld"
                                        else _p3m.ESRI_ATTR))
                st.image(_sh["png"], caption="작도판 — 농민 확인용", width="stretch")
                st.download_button("작도판 PNG 내려받기", _sh["png"],
                                   file_name="작도판.png", mime="image/png", key="p3_dl_sheet")
                st.info("🔴 **경작 구역은 지적 경계가 대신하지 못합니다.** 이 판으로 확인받은 뒤 "
                        "④에서 설계를 실행하세요.")

            with st.expander("지번으로 만들기 (브이월드 · 지적 참고선·지번 라벨이 필요할 때)"):
                st.caption("브이월드가 배포 서버의 요청을 거르면 실패합니다 — 그때는 위 「자동/Esri」를 쓰세요.")
                _a2 = (st.session_state.get("p3_answers", {}) or {}).get("address", "").strip()
                if st.button("지번으로 작도판", key="p3_draft_btn", disabled=not _a2):
                    _p3_keys()
                    with st.spinner("필지·위성 받는 중…"):
                        try:
                            _d = _p3m.draft_from_address(_a2)
                            st.session_state.p3_draft = {
                                "png": _d["png"], "address": _d["parcel"]["address"],
                                "pnu": _d["parcel"]["pnu"], "area_m2": _d["parcel"]["area_m2"],
                                "seed": _d["seed"], "frame": _d["frame"]}
                            _p3_move_frame(_d["frame"])
                        except Exception as _e:
                            st.session_state.p3_draft = None
                            st.error("지번 작도판 실패: " + str(_e))
                _dr = st.session_state.get("p3_draft")
                if _dr:
                    st.success("%s · PNU %s · 지적 %s m² (%s 평)"
                               % (_dr["address"], _dr["pnu"], format(round(_dr["area_m2"]), ","),
                                  format(round(_dr["area_m2"] / 3.3058), ",")))
                    st.image(_dr["png"], width="stretch")
                    st.download_button("PNG 내려받기", _dr["png"],
                                       file_name=(_dr["pnu"] or "site") + "_작도판.png",
                                       mime="image/png", key="p3_dl_png")

            # 🩺 지도 연결 점검 — expander 밖에 둔다(V82: 접히면 결과가 안 보인다).
            st.markdown("---")
            st.markdown("##### 🩺 지도 연결 점검")
            st.caption("망 도달(DNS·TCP·가짜 키·Esri·대조군) → 지번 검색 → 필지 → 주변 필지 → 위성 을 "
                       "**따로따로** 찔러 봅니다.")
            if st.button("점검 실행", key="p3_probe_btn"):
                _p3_keys()
                with st.spinner("찔러 보는 중… (최대 1분)"):
                    try:
                        _pb = _p3m.probe((st.session_state.get("p3_answers", {}) or {}).get(
                            "address", "").strip() or "논산시 상월면 상도리 482-42")
                    except Exception as _e:
                        _pb = [{"step": "점검 자체가 실패", "ok": False, "ms": 0,
                                "detail": "%s: %s" % (type(_e).__name__, _e)}]
                st.session_state.p3_probe = _pb
            _pb = st.session_state.get("p3_probe")
            if _pb:
                st.dataframe(pd.DataFrame([{"단계": r["step"], "결과": "✅" if r["ok"] else "🔴",
                                            "ms": r["ms"], "내용": str(r["detail"])} for r in _pb]),
                             width="stretch", hide_index=True)
                _esri_ok = any(r["step"].startswith("ⓔ") and r["ok"] for r in _pb)
                _bad = [r for r in _pb if not r["ok"]]
                if not _bad:
                    st.success("✅ 전부 통과 — 브이월드까지 됩니다.")
                elif _esri_ok:
                    st.info("🟠 브이월드는 막혔지만 **Esri 배경은 됩니다** — 배경을 「자동/Esri」로 두면 "
                            "작도판은 그대로 나옵니다. 잃는 것은 지적 참고선·지번 라벨뿐입니다.")
                else:
                    st.error("🔴 **배경까지 막혔습니다.** 배포 환경의 바깥 연결 문제입니다 — 이 표를 알려 주세요.")

    # ── ④ 설계·견적 ───────────────────────────────────────────────────
    with _p3_steps[3]:
        _ans = st.session_state.get("p3_answers", {}) or {}
        _dw = st.session_state.get("p3_drawn")
        if not _p3i.check(_ans, st.session_state.get("p3_waived") or [])["ok"]:
            st.warning("①의 필수 칸을 먼저 채워 주세요.")
        elif not _dw:
            st.warning("③에서 작도 결과를 올려 주세요.")
        elif st.button("설계 실행", type="primary", key="p3_run"):
            # 새 입력이 실패했을 때 이전 설계가 이번 결과처럼 남지 않게 한다.
            st.session_state.pop("p3_result", None)
            st.session_state.pop("p3_site", None)
            _site = None
            try:
                _site = _p3i.validate(_ans, _dw, name=_ans.get("address"),
                                      waived=st.session_state.get("p3_waived") or [])
            except ValueError as _e:
                st.error("🔴 입력이 부족합니다 — " + str(_e))
            if _site:
                _pdb = {}
                for _pr in st.session_state.db.get("products", []):
                    _cd = str(_pr.get("code", "")).strip().zfill(5)
                    if _cd:
                        _pdb[_cd] = {"name": _pr.get("name", ""), "spec": _pr.get("spec", ""),
                                     "unit": _pr.get("unit", "EA"),
                                     "소비자가": int(_pr.get("price_cons", 0) or 0)}
                try:
                    _res = _p3_design(_site, _pdb)
                    st.session_state.p3_result = _res
                    st.session_state.p3_site = _site
                except Exception as _e:
                    st.error("설계 실패: " + str(_e))
        _res = st.session_state.get("p3_result")
        if _res:
            _site = st.session_state.get("p3_site") or {}
            _m1, _m2, _m3, _m4 = st.columns(4)
            _m1.metric("헤드", "%d 두" % _res["n_heads"])
            _m2.metric("가지관 열", "%d 열" % _res["n_laterals"])
            _m3.metric("주배관", "%.0f m" % _res["mainline"]["total_m"])
            _m4.metric("자재 합계", format((_res["money"] or {}).get("total", 0), ",") + " 원")
            st.caption("관수 방식 — **%s** (노지 기준 · 시설하우스·과수는 범위 밖)"
                       % _p3s.SYSTEM_LABEL.get(_p3s.system_of(_site), "스프링클러(노지)"))
            _nd4 = sum(len((_b.get("policy") or {}).get("drop_heads") or [])
                       for _b in (_site.get("blocks") or []))
            if _nd4:
                st.caption("🚫 ②에서 **검토로 빼신 스프링클러 %d두**가 빠진 결과입니다." % _nd4)
            _mm = int(_res.get("main_mm") or _p3p.APPROVED_MAIN_MM)
            st.caption("주배관 %s — **%s**. 여유 하한은 두지 않습니다: 말단 1.5 bar 를 지키는 "
                       "가장 가는 관을 고릅니다."
                       % (_p3p.id_note(_p3p.by_nominal(_mm)["id_mm"]), _res.get("main_mm_source", "-")))
            if _res.get("main_mm_picks"):
                with st.expander("구역별 관경 선정 근거"):
                    st.dataframe(pd.DataFrame(_res["main_mm_picks"]), width="stretch", hide_index=True)
            for _w in ((_site.get("intake") or {}).get("warn") or []):
                st.warning("문진표 — " + _w)
            for _w in _res.get("warnings", []):
                st.warning(_w)
            try:
                _zr = _p3hz.zones_report(_res, _site)
            except Exception as _e:
                st.error("구역별 운전점 계산 실패 — 결과를 확인할 수 없습니다: " + str(_e))
                _zr = []
            if _zr:
                st.markdown("##### 구역별 운전점")
                st.dataframe(pd.DataFrame(_zr), width="stretch", hide_index=True)
            st.markdown("##### 자재 목록")
            _rows = (_res.get("money") or {}).get("rows") or _res["bom"]
            st.dataframe(pd.DataFrame(_rows), width="stretch", hide_index=True)
            # 🧩 [V107] 세트 — 대표 2026-09-09 「세트는 앞으로 내가 등록하지 않을거야.
            #    엔진이 제안서를 만드는 것을 보고, 세트화가 필요한 경우 **엔진이 세트를 만들 수 있도록** 해.」
            #    🔴 Sets 시트는 **읽기만** 한다(규칙 8 · 프로덕션 무반영). 여기 나오는 것은 **제안**이다.
            st.markdown("##### 🧩 세트 — 쓰인 것과 신설 후보")
            try:
                _sp = _p3set.propose(_res, _site, st.session_state.db.get("sets"))
            except Exception as _e:
                _sp = None
                st.error("세트 대조 실패 — " + str(_e))
            if _sp:
                st.caption("연결부 묶음을 **이름 정본(설계 규칙 8)** → **Sets 시트** 순으로 찾고, "
                           "없으면 **신설 후보**를 만듭니다. 조합(레시피)의 정본은 `bom.py`(승인 견적 역산)입니다. "
                           "🔴 **시트는 건드리지 않습니다** — 등록은 사람이 합니다.")
                st.dataframe(pd.DataFrame([
                    {"상태": x["status"], "세트명": x["name"], "쓰임새": x["label"],
                     "개소": x["n"], "레시피": x["recipe_text"]}
                    for x in (_sp["in_sheet"] + _sp["propose"])]),
                    width="stretch", hide_index=True)
                if _sp["n_propose"]:
                    st.info("🧩 **신설 후보 %d 건** — 이름은 **잠정**입니다. 이름의 정본은 명명 규칙"
                            "(B안 · 결정 #35)이라 작업 PC의 `tools/set_name.py` 로 확정합니다. "
                            "아래 줄을 Sets 시트에 붙여 넣으시면 등록됩니다." % _sp["n_propose"])
                    st.download_button("🧩 세트 신설 후보 JSON (시트 열 그대로)",
                                       json.dumps(_p3set.to_sheet_rows(_sp), ensure_ascii=False,
                                                  indent=1).encode("utf-8"),
                                       file_name="세트신설후보.json", mime="application/json",
                                       key="p3_dl_sets")
                if _sp["n_unknown"]:
                    st.warning("🔧 **부속을 아직 모르는 자리 %d 곳** — 레시피를 만들 수 없어 세트로 묶지 못합니다. "
                               "지어내지 않습니다(불변 원칙 1)." % _sp["n_unknown"])
                    st.dataframe(pd.DataFrame([
                        {"자리": "·".join(u["routes"]), "왜": u["why"],
                         "x(동,m)": u["pt"][0], "y(북,m)": u["pt"][1]} for u in _sp["unknown"]]),
                        width="stretch", hide_index=True)

            _c1, _c2 = st.columns(2)
            _c1.download_button("설계 결과 JSON",
                                json.dumps(_res, ensure_ascii=False, indent=1).encode("utf-8"),
                                file_name="설계결과.json", mime="application/json", key="p3_dl_res")
            _c2.download_button("site JSON",
                                json.dumps(_site, ensure_ascii=False, indent=1).encode("utf-8"),
                                file_name="site.json", mime="application/json", key="p3_dl_site")

            # ── 📑 [V102] 제안서(PPTX) · 견적서(XLSX) 초안 ────────────────────
            #    대표 지시 2026-09-08 — 「마지막에 설계를 누르면 ppt 제안서와 엑셀 견적서를 각각
            #    생성하는 기능을 넣어줘. 그렇게 되면 사람의 수정을 거쳐서 소비자에게 나갈 수 있어.」
            #    🔴 값은 여기서 만들지 않는다 — 위에 나온 설계를 P2 발행 엔진(`design.publish`)에 그대로 넘긴다.
            #    🔴 발행은 대표 전담(불변 원칙 3). 이것은 **초안 파일**이다.
            st.divider()
            st.markdown("##### 📑 제안서 · 견적서 (초안 파일)")
            _fr4 = st.session_state.get("p3_map_frame")
            if not _fr4:
                st.warning("②지도를 한 번 열어야 좌표 기준이 잡힙니다 — ②에 들렀다 오세요.")
            else:
                _q1, _q2, _q3 = st.columns([2, 2, 1])
                _q_to = _q1.text_input("받는 분(농가·법인명)", value=(_ans.get("customer") or ""),
                                       key="p3_q_to")
                _q_mgr = _q2.text_input("담당자", value="박형석", key="p3_q_mgr")
                _q_vat = _q3.checkbox("영세율", value=False, key="p3_q_vat",
                                      help="농업경영체 등록확인서 제출 건에만 켭니다(건별 판단).")
                _pptx_ok, _pptx_why = _p3pub.pptx_ready()
                st.caption("표지·수량·금액은 **위 설계 그대로** 들어갑니다. 대표 작도가 필요한 지면"
                           "(물 공급 계통·매니폴드)은 **비어 있는 채로** 나옵니다 — 그 자리를 채우고 문안을 "
                           "다듬는 것이 사람의 몫입니다."
                           + ("" if _pptx_ok else
                              "  \n🔴 **이 서버에서는 견적서(XLSX)만** 나옵니다 — " + _pptx_why))
                if st.button("📑 제안서·견적서 만들기", type="primary", key="p3_pub_btn"):
                    st.session_state.pop("p3_pub", None)
                    with st.spinner("위성 받고 지면 그리는 중… (20~40초)"):
                        try:
                            from looperget.design import publish as _p3pub
                            _o4 = _fr4["origin"]
                            _all4 = ([_q for _b in (_site.get("blocks") or []) for _q in (_b.get("polygon") or [])]
                                     + [_x["pt"] for _x in (_site.get("sources") or [])]
                                     + [_q for _r in (_site.get("routes") or []) for _q in (_r.get("pts") or [])])
                            _ff4 = _p3m.fit_frame(_all4, _o4, size=1024)
                            _p3_keys()
                            _bg4, _src4 = _p3m.basemap_image(_ff4, prefer="auto")
                            _nm4 = "P3_" + _p3pub._slug(str(_site.get("name") or "대상지"))
                            _dir4 = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_제안", _nm4)
                            try:                       # 배포 서버는 저장소 폴더가 막혀 있을 수 있다
                                os.makedirs(_dir4, exist_ok=True)
                                _tf4 = os.path.join(_dir4, "_쓰기시험")
                                with open(_tf4, "w") as _t4:
                                    _t4.write("ok")
                                os.remove(_tf4)
                            except Exception:
                                _dir4 = os.path.join(tempfile.gettempdir(), _nm4)
                                os.makedirs(_dir4, exist_ok=True)
                            _png4 = os.path.join(_dir4, "_위성.png")
                            with open(_png4, "wb") as _f4:
                                _f4.write(_bg4)
                            _pdb4 = {}
                            for _pr in st.session_state.db.get("products", []):
                                _cd = str(_pr.get("code", "")).strip().zfill(5)
                                if _cd:
                                    _pdb4[_cd] = {"name": _pr.get("name", ""), "spec": _pr.get("spec", ""),
                                                  "unit": _pr.get("unit", "EA"),
                                                  "소비자가": int(_pr.get("price_cons", 0) or 0)}
                            # 부속 사진 — 승인 제안서가 쓰는 폴더를 그대로 쓴다(있으면).
                            _imgd = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                                 "_설계", "배추밭스프링클러_20260824", "90_작업파일", "부속이미지")
                            _job4 = _p3pub.job_from_p3(
                                _site, _res, frame=_ff4, origin=_o4, png_path=_png4,
                                meta={"out_dir": _dir4, "price_db": _pdb4,
                                      "part_img_dir": _imgd if os.path.isdir(_imgd) else None,
                                      "site_short": (_ans.get("crop") or "관수 설계"),
                                      "quote": {"label": str(_site.get("name") or ""),
                                                "recipient": _q_to, "manager": _q_mgr or "박형석",
                                                "vat_zero": bool(_q_vat)}})
                            _out4 = _p3pub.run(_job4, verbose=False)
                            st.session_state.p3_pub = {
                                "pptx": _out4.get("pptx"), "xlsx": _out4["xlsx"]["path"],
                                "skip": _out4.get("pptx_skip") or "",
                                "job": os.path.join(_dir4, "_job.json"),
                                "dir": _dir4, "basemap": _src4,
                                "n_items": _out4["xlsx"]["n_items"], "total": _out4["xlsx"]["total"],
                                "pages": sorted((_out4.get("page_check") or {}).keys())}
                        except Exception as _e:
                            st.error("제안서·견적서 생성 실패 — " + str(_e))
                _pub = st.session_state.get("p3_pub")
                if _pub:
                    st.success("만들었습니다 — %s · 배경 %s · 견적 **%d품목 · %s원**. 폴더 `%s`"
                               % ("제안서 + 견적서" if _pub.get("pptx") else "**견적서**",
                                  "브이월드 위성" if _pub["basemap"] == "vworld" else "Esri 위성",
                                  _pub["n_items"], format(_pub["total"], ","), _pub["dir"]))
                    _d1, _d2 = st.columns(2)
                    try:
                        with open(_pub["xlsx"], "rb") as _f:
                            _d1.download_button("📗 견적서 XLSX 내려받기", _f.read(),
                                                file_name=os.path.basename(_pub["xlsx"]),
                                                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                                                key="p3_dl_xlsx")
                        if _pub.get("pptx"):
                            with open(_pub["pptx"], "rb") as _f:
                                _d2.download_button("📊 제안서 PPTX 내려받기", _f.read(),
                                                    file_name=os.path.basename(_pub["pptx"]),
                                                    mime="application/vnd.openxmlformats-officedocument.presentationml.presentation",
                                                    key="p3_dl_pptx")
                        elif os.path.exists(_pub.get("job") or ""):
                            with open(_pub["job"], "rb") as _f:
                                _d2.download_button("🧾 설계 job JSON 내려받기", _f.read(),
                                                    file_name="job_" + _p3pub._slug(str(_site.get("name") or "대상지")) + ".json",
                                                    mime="application/json", key="p3_dl_job")
                    except Exception as _e:
                        st.error("파일을 여는 중 오류 — " + str(_e))
                    if not _pub.get("pptx"):
                        # 🔴 [V104] 제안서 지면은 **마스터 지면(59 MB)** 과 작도 도구가 있어야 그린다.
                        #    배포 묶음(app.py + common/ + looperget/)에는 넣을 수 없다 —
                        #    GitHub 브라우저 업로드 한도가 25 MB 다. 그러니 여기서는 **견적서까지**가 정직하다.
                        st.warning("📊 **제안서 PPTX 는 이 서버에서 만들 수 없습니다** — " + _pub["skip"]
                                   + "  \n견적서는 위에서 받으시고, 제안서는 **작업 PC**에서 아래 한 줄로 "
                                     "만드십시오. 위 「🧾 설계 job JSON」을 내려받아 프로젝트 폴더에 두고 —")
                        st.code("python -m looperget.design.publish job_대상지.json", language="bash")
                    if _pub["pages"]:
                        st.caption("§9 기계 점검이 지적한 지면 — %s 면. 대개 **대표 작도가 없어 비어 있는 지면**입니다."
                                   % ", ".join(str(_x) for _x in _pub["pages"]))
            st.info("제안서·견적서 **발행은 대표 전담**입니다(불변 원칙 3). 여기서 나오는 것은 "
                    "사람이 고쳐 쓰는 **초안 파일**입니다.")

elif mode == "🇯🇵 일본 수출 분석":
    st.header("🇯🇵 일본 수출 이익 분석 (HQ Profit Analysis)")
    st.info("일본 현지 앱의 견적 데이터와 한국 본사 DB(신정공급가, 매입가)를 매칭하여 순이익을 분석합니다.")
    
    if st.button("🔄 데이터 새로고침"):
        st.session_state.db = load_data_from_sheet()
        st.rerun()

    jp_quotes = st.session_state.db.get("jp_quotes", [])
    if not jp_quotes:
        st.warning("분석할 일본 견적 데이터가 없습니다. (Quotes_JP 시트 확인)")
    else:
        df_quotes = pd.DataFrame(jp_quotes)
        selected_quote_idx = st.selectbox(
            "분석 대상 견적 선택", 
            range(len(df_quotes)), 
            format_func=lambda i: f"[{df_quotes.iloc[i].get('날짜','')}] {df_quotes.iloc[i].get('현장명','')}"
        )
        
        target_quote = df_quotes.iloc[selected_quote_idx]
        items_json = str(target_quote.get("데이터JSON", "{}"))
        try:
            full_dict = json.loads(items_json)
            items_dict = full_dict.get("items", {}) if isinstance(full_dict, dict) and "items" in full_dict else full_dict
        except:
            items_dict = {}
            st.error("JSON 데이터 파싱 실패")

        if items_dict:
            pdb_map = {str(p.get("code")).strip().zfill(5): p for p in st.session_state.db["products"]}
            analysis_data = []
            
            for code, qty in items_dict.items():
                clean_code = str(code).strip().zfill(5)
                qty = int(qty)
                prod = pdb_map.get(clean_code)
                
                if prod:
                    p_buy = int(prod.get("price_buy", 0))
                    p_supply = int(prod.get("price_supply_jp", 0))
                    total_rev = p_supply * qty
                    total_cost = p_buy * qty
                    profit = total_rev - total_cost
                    
                    analysis_data.append({
                        "품목코드": clean_code,
                        "품목명": prod.get("name", ""),
                        "규격": prod.get("spec", "-"),
                        "수량": qty,
                        "매입단가(원)": p_buy,
                        "신정공급가(원)": p_supply,
                        "합계매출": total_rev,
                        "합계원가": total_cost,
                        "순이익": profit
                    })
                else:
                    analysis_data.append({
                        "품목코드": clean_code, "품목명": "미등록 품목", "규격": "-", "수량": qty,
                        "매입단가(원)": 0, "신정공급가(원)": 0, "합계매출": 0, "합계원가": 0, "순이익": 0
                    })

            def sort_analysis(item):
                p1 = item.get("신정공급가(원)", 0)
                if p1 >= 20000: return (0, -p1)
                return (1, item.get("품목명", ""))
            
            analysis_data.sort(key=sort_analysis)
            df_analysis = pd.DataFrame(analysis_data)
            
            t_rev = df_analysis["합계매출"].sum()
            t_cost = df_analysis["합계원가"].sum()
            t_profit = df_analysis["순이익"].sum()
            margin = (t_profit / t_rev * 100) if t_rev > 0 else 0

            st.divider()
            m1, m2, m3, m4 = st.columns(4)
            m1.metric("총 수출 매출 (HQ Revenue)", f"{t_rev:,} 원")
            m2.metric("총 본사 원가 (HQ Cost)", f"{t_cost:,} 원")
            m3.metric("총 순이익 (Net Profit)", f"{t_profit:,} 원")
            m4.metric("수익률 (Margin)", f"{margin:.1f}%")

            st.dataframe(df_analysis, width="stretch", hide_index=True)

            if st.button("📄 수출 이익 분석서 생성"):
                with st.spinner("보고서를 생성하고 있습니다..."):
                    excel_buf = io.BytesIO()
                    with pd.ExcelWriter(excel_buf, engine='xlsxwriter') as writer:
                        df_analysis.to_excel(writer, index=False, sheet_name='Profit_Analysis')
                    
                    pdf = PDF(orientation='L')
                    pdf.title_text = "輸出利益分析書 (Export Profit Analysis)"
                    pdf.add_page()
                    # [V28] 버그수정: set_font에는 파일명이 아닌 등록된 패밀리명('NanumGothic')을 써야 함 (아니면 FPDF 예외)
                    _jf = 'NanumGothic' if os.path.exists(FONT_REGULAR) else 'Helvetica'
                    _jb = 'B' if os.path.exists(FONT_BOLD) else ''
                    pdf.set_font(_jf, '', 10)
                    
                    pdf.cell(0, 10, f"Analysis Date: {datetime.datetime.now().strftime('%Y-%m-%d')}", ln=True, align='R')
                    pdf.cell(0, 10, f"Quote Name: {target_quote.get('현장명')}", ln=True)
                    pdf.ln(5)
                    
                    pdf.set_fill_color(220, 220, 220)
                    cols = ["Code", "Item Name", "Spec", "Qty", "Buy Price", "Supply Price", "Sum Revenue", "Sum Cost", "Profit"]
                    widths = [20, 50, 40, 15, 30, 30, 35, 35, 30]
                    for head, w in zip(cols, widths):
                        pdf.cell(w, 10, head, border=1, align='C', fill=True)
                    pdf.ln()
                    
                    pdf.set_font(_jf, '', 8)
                    for _, row in df_analysis.iterrows():
                        pdf.cell(widths[0], 8, str(row['품목코드']), border=1, align='C')
                        pdf.cell(widths[1], 8, str(row['품목명']), border=1)
                        pdf.cell(widths[2], 8, str(row['규격']), border=1)
                        pdf.cell(widths[3], 8, str(row['수량']), border=1, align='C')
                        pdf.cell(widths[4], 8, f"{int(row['매입단가(원)']):,}", border=1, align='R')
                        pdf.cell(widths[5], 8, f"{int(row['신정공급가(원)']):,}", border=1, align='R')
                        pdf.cell(widths[6], 8, f"{int(row['합계매출']):,}", border=1, align='R')
                        pdf.cell(widths[7], 8, f"{int(row['합계원가']):,}", border=1, align='R')
                        pdf.cell(widths[8], 8, f"{int(row['순이익']):,}", border=1, align='R')
                        pdf.ln()
                    
                    pdf.set_font(_jf, _jb, 10)
                    total_w = sum(widths[:6])
                    pdf.cell(total_w, 10, "TOTAL (KRW)", border=1, align='C', fill=True)
                    pdf.cell(widths[6], 10, f"{t_rev:,}", border=1, align='R')
                    pdf.cell(widths[7], 10, f"{t_cost:,}", border=1, align='R')
                    pdf.cell(widths[8], 10, f"{t_profit:,}", border=1, align='R')
                    
                    pdf_bytes = bytes(pdf.output())
                    
                    st.success("보고서 생성 완료")
                    c1, c2 = st.columns(2)
                    c1.download_button("📥 분석서 PDF 다운로드", pdf_bytes, f"Export_Analysis_{target_quote.get('현장명')}.pdf", "application/pdf", use_container_width=True)
                    c2.download_button("📥 분석서 Excel 다운로드", excel_buf.getvalue(), f"Export_Analysis_{target_quote.get('현장명')}.xlsx", use_container_width=True)

else:
    # ── [V11] JP 모드 견적 작성 ──────────────────────────────────
    if st.session_state.app_lang == "JP" and mode == "見積作成":
        st.markdown(f"### 📝 現場名: **{st.session_state.current_quote_name if st.session_state.current_quote_name else '(タイトルなし)'}**")
        jp_products = st.session_state.db.get("jp_products", [])
        if not jp_products:
            st.warning("⚠️ 일본용 제품 데이터가 없습니다. 먼저 관리자 모드에서 Products_JP를 동기화해주세요.")
        else:
            # JP 모드 STEP 1: 세트 선택 (KR과 동일 구조, 언어만 일본어)
            if st.session_state.quote_step == 1:
                st.subheader("STEP 1. 数量・情報入力")
                with st.expander("👤 お客様情報", expanded=True):
                    c1, c2 = st.columns(2)
                    with c1:
                        new_q_name = st.text_input("現場名", value=st.session_state.current_quote_name)
                        if new_q_name != st.session_state.current_quote_name: st.session_state.current_quote_name = new_q_name
                        manager = st.text_input("担当者", value=st.session_state.buyer_info.get("manager",""))
                    with c2:
                        phone = st.text_input("電話番号", value=st.session_state.buyer_info.get("phone",""))
                        addr = st.text_input("住所", value=st.session_state.buyer_info.get("addr",""))
                    st.session_state.buyer_info.update({"manager": manager, "phone": phone, "addr": addr})
                st.divider()
                sets = st.session_state.db.get("sets", {})
                with st.expander("セット選択", True):
                    m_sets = sets.get("주배관세트", {})
                    grouped = {"50mm":{}, "40mm":{}, "その他":{}, "未分類":{}}
                    for k, v in m_sets.items():
                        sc = v.get("sub_cat", "미분류") if isinstance(v, dict) else "미분류"
                        sc_jp = {"50mm":"50mm","40mm":"40mm","기타":"その他","미분류":"未分類"}.get(sc, sc)
                        if sc_jp not in grouped: grouped[sc_jp] = {}
                        grouped[sc_jp][k] = v
                    mt1, mt2, mt3, mt4 = st.tabs(["50mm", "40mm", "その他", "全体"])
                    def render_inputs_jp(d, pf):
                        # V12: 세션캐시 + 카드 + 툴팁
                        if "_img_cache" not in st.session_state:
                            st.session_state._img_cache = {}
                        cols = st.columns(4); res = {}
                        for i, (n, v) in enumerate(d.items()):
                            with cols[i%4]:
                                img_name = v.get("image") if isinstance(v, dict) else None
                                recipe = v.get("recipe", {}) if isinstance(v, dict) else {}
                                if recipe:
                                    pdb_local = {str(p.get("code","")): p.get("name","") for p in st.session_state.db.get("products", [])}
                                    tip_lines = [f"· {pdb_local.get(str(c), c)} ×{q}" for c, q in recipe.items()]
                                    tooltip_html = "<br>".join(tip_lines)
                                else:
                                    tooltip_html = ""
                                if img_name:
                                    if n not in st.session_state._img_cache:
                                        st.session_state._img_cache[n] = get_image_from_drive(img_name)
                                    b64 = st.session_state._img_cache.get(n)
                                else:
                                    b64 = None
                                img_html = f'<img src="{b64}" style="width:100%;border-radius:6px 6px 0 0;">' if b64 else '<div style="width:100%;height:110px;background:#2a2a2a;border-radius:6px 6px 0 0;display:flex;align-items:center;justify-content:center;color:#666;font-size:12px;">No Image</div>'
                                set_desc = v.get("desc", "") if isinstance(v, dict) else ""
                                desc_html = f'<div class="set-card-desc">{set_desc}</div>' if set_desc else ""
                                tooltip_block = f'<div class="set-card-tooltip">{tooltip_html}{desc_html}</div>' if (tooltip_html or desc_html) else ""
                                st.markdown(f'<div class="set-card-wrap">{img_html}{tooltip_block}</div>', unsafe_allow_html=True)
                                res[n] = st.number_input(n, 0, key=f"{pf}_{n}_input")
                        return res
                    with mt1: inp_m_50 = render_inputs_jp(grouped.get("50mm",{}), "jp_m50")
                    with mt2: inp_m_40 = render_inputs_jp(grouped.get("40mm",{}), "jp_m40")
                    with mt3: inp_m_etc = render_inputs_jp(grouped.get("その他",{}), "jp_metc")
                    with mt4: inp_m_all = render_inputs_jp(m_sets, "jp_mall")
                    if st.button("➕ セットリストに追加"):
                        all_inp = {}
                        for d in [inp_m_50, inp_m_40, inp_m_etc, inp_m_all]:
                            for k, v in d.items(): all_inp[k] = all_inp.get(k,0) + v
                        for k, v in all_inp.items():
                            if v > 0:
                                st.session_state.set_cart.append({"name": k, "qty": v, "type": "メイン管"})
                        st.rerun()
                with st.expander("配管数量入力"):
                    ptype = st.radio("配管区分", ["주배관","가지관"], horizontal=True, key="jp_pipe_radio",
                                     format_func=lambda x: "メイン配管" if x=="주배관" else "分岐配管")
                    filtered_pipes = [p for p in jp_products if p.get("category") in (["メイン配管"] if ptype=="주배관" else ["分岐配管"])]
                    c1, c2, c3 = st.columns([3,2,1])
                    with c1: sel_pipe = st.selectbox("配管選択", filtered_pipes, format_func=lambda p: f"[{p.get('code')}] {p.get('name')} ({p.get('spec','-')})", key="jp_pipe_sel")
                    with c2: len_pipe = st.number_input("長さ(m)", min_value=1, step=1, key="jp_pipe_len")
                    with c3:
                        st.write(""); st.write("")
                        if st.button("➕ 追加", key="jp_add_pipe"):
                            if sel_pipe: st.session_state.pipe_cart.append({"type":ptype,"name":sel_pipe["name"],"spec":sel_pipe.get("spec",""),"code":sel_pipe.get("code",""),"len":len_pipe})
                if st.session_state.pipe_cart:
                    st.dataframe(pd.DataFrame(st.session_state.pipe_cart), hide_index=True, use_container_width=True)
                    if st.button("🗑️ クリア", key="jp_clear_pipe"): st.session_state.pipe_cart = []; st.rerun()
                st.divider()
                if st.button("計算する (STEP 2)", type="primary"):
                    if not st.session_state.current_quote_name: st.error("現場名を入力してください。")
                    else:
                        res = {}
                        all_sets_db = {}
                        for cat, val in st.session_state.db.get("sets",{}).items(): all_sets_db.update(val)
                        for item in st.session_state.set_cart:
                            recipe = all_sets_db.get(item["name"],{}).get("recipe",{})
                            for pc, pq in recipe.items(): res[str(pc)] = res.get(str(pc),0) + pq*item["qty"]
                        code_sums = {}
                        for pi in st.session_state.pipe_cart:
                            c = pi.get("code")
                            if c: code_sums[c] = code_sums.get(c,0) + pi["len"]
                        for pc, tl in code_sums.items():
                            prod_info = next((p for p in jp_products if str(p.get("code",""))==str(pc)), None)
                            if prod_info:
                                ul = prod_info.get("len_per_unit",4) or 4
                                res[str(pc)] = res.get(str(pc),0) + math.ceil(tl/ul)
                        st.session_state.quote_items = res; st.session_state.quote_step = 2; st.rerun()

            elif st.session_state.quote_step == 2:
                st.subheader("STEP 2. 内容確認")
                if st.button("⬅️ STEP 1に戻る"): st.session_state.quote_step = 1; st.rerun()
                pdb_jp = {str(p.get("code","")).strip(): p for p in jp_products}
                rows = []
                for n, q in st.session_state.quote_items.items():
                    inf = pdb_jp.get(str(n), {})
                    if not inf: continue
                    cpr = int(inf.get("price_cons", 0) or 0)
                    rows.append({"品目": inf.get("name",n), "規格": inf.get("spec",""), "数量": q, "消費者価格(¥)": cpr, "合計(¥)": cpr*q})
                if rows:
                    df_jp = pd.DataFrame(rows)
                    st.dataframe(df_jp, hide_index=True, use_container_width=True)
                    st.metric("合計金額", f"¥{df_jp['合計(¥)'].sum():,}")
                st.divider()
                if st.button("最終確定 (STEP 3)", type="primary"):
                    fdata = []
                    for n, q in st.session_state.quote_items.items():
                        inf = pdb_jp.get(str(n), {})
                        if not inf: continue
                        fdata.append({"品目": inf.get("name",n), "規格": inf.get("spec",""), "コード": inf.get("code",""), "単位": inf.get("unit","EA"), "数量": int(q), "price_1": int(inf.get("price_cons",0) or 0), "price_2": int(inf.get("price_d1",0) or 0), "image_data": inf.get("image","")})
                    st.session_state.final_edit_df = pd.DataFrame(fdata)
                    st.session_state.quote_step = 3; st.rerun()

            elif st.session_state.quote_step == 3:
                st.header("🏁 最終見積")
                q_date = st.date_input("見積日", datetime.datetime.now())
                if st.session_state.final_edit_df is not None:
                    # [V13] 規格/コード/品目/単位 강제 문자열화 — Arrow 직렬화 에러 방지
                    for _c in ["規格", "コード", "品目", "単位"]:
                        if _c in st.session_state.final_edit_df.columns:
                            st.session_state.final_edit_df[_c] = st.session_state.final_edit_df[_c].astype(str)
                    edited_jp = st.data_editor(st.session_state.final_edit_df[["品目","規格","コード","単位","数量","price_1"]], num_rows="dynamic", hide_index=True, column_config={"price_1": st.column_config.NumberColumn("消費者価格(¥)", format="%d")}, use_container_width=True, key="jp_final_editor")
                    st.session_state.final_edit_df = edited_jp
                    total_jpy = (edited_jp["数量"] * edited_jp["price_1"]).sum()
                    st.metric("合計金額 (税込)", f"¥{int(total_jpy):,}")
                    if st.button("💾 見積保存 (Quotes_JPシート)"):
                        ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        items_dict = {row["コード"] if row["コード"] else row["品目"]: row["数量"] for _, row in edited_jp.iterrows()}
                        jdata = {"items": items_dict, "pipe_cart": st.session_state.pipe_cart, "set_cart": st.session_state.set_cart, "buyer": st.session_state.buyer_info}
                        if save_quote_to_sheet(ts, st.session_state.current_quote_name, st.session_state.buyer_info.get("manager",""), int(total_jpy), json.dumps(jdata, ensure_ascii=False)):
                            st.success("✅ Quotes_JPシートに保存しました。")
                        else: st.error("保存失敗")
                c1, c2 = st.columns(2)
                with c1:
                    if st.button("⬅️ STEP 2に戻る"): st.session_state.quote_step = 2; st.rerun()
                with c2:
                    if st.button("🔄 最初から"):
                        st.session_state.quote_step = 1; st.session_state.quote_items = {}
                        st.session_state.pipe_cart = []; st.session_state.set_cart = []
                        st.session_state.current_quote_name = ""; st.rerun()
        st.stop()

    # ── KR 모드 견적 작성 (기존 코드) ────────────────────────────
    st.markdown(f"### 📝 현장명: **{st.session_state.current_quote_name if st.session_state.current_quote_name else '(제목 없음)'}**")
    if st.session_state.quote_step == 1:
        st.subheader("STEP 1. 물량 및 정보 입력")
        with st.expander("👤 구매자(현장) 정보 입력", expanded=True):
            c_info1, c_info2 = st.columns(2)
            with c_info1:
                new_q_name = st.text_input("현장명(거래처명)", value=st.session_state.current_quote_name)
                if new_q_name != st.session_state.current_quote_name: st.session_state.current_quote_name = new_q_name
                manager = st.text_input("담당자", value=st.session_state.buyer_info.get("manager",""))
                recipient = st.text_input("수신", value=st.session_state.buyer_info.get("recipient",""), placeholder="예: 9878부대")
                pay_cond = st.text_input("결재조건", value=st.session_state.buyer_info.get("pay_cond","/"))
            with c_info2:
                phone = st.text_input("전화번호", value=st.session_state.buyer_info.get("phone",""))
                addr = st.text_input("주소", value=st.session_state.buyer_info.get("addr",""))
                ref = st.text_input("참조", value=st.session_state.buyer_info.get("ref",""), placeholder="예: /")
                valid_period = st.text_input("유효기간", value=st.session_state.buyer_info.get("valid_period","견적 후 15일 이내"))
            st.session_state.buyer_info.update({"manager": manager, "phone": phone, "addr": addr,
                "recipient": recipient, "ref": ref, "pay_cond": pay_cond, "valid_period": valid_period})
        st.divider()
        sets = st.session_state.db.get("sets", {})
        with st.expander("1. 주배관 및 가지관 세트 선택", True):
            m_sets = sets.get("주배관세트", {})
            grouped = {"50mm":{}, "40mm":{}, "기타":{}, "미분류":{}}
            for k, v in m_sets.items():
                sc = v.get("sub_cat", "미분류") if isinstance(v, dict) else "미분류"
                if sc not in grouped: grouped[sc] = {}
                grouped[sc][k] = v
            # ── V12: 세션 캐시 + 카드 + 툴팁 렌더 ──────────────────────────
            def get_cached_set_image(set_name, img_ref):
                if "_img_cache" not in st.session_state:
                    st.session_state._img_cache = {}
                if set_name not in st.session_state._img_cache:
                    st.session_state._img_cache[set_name] = get_image_from_drive(img_ref)
                return st.session_state._img_cache.get(set_name)

            def render_inputs_with_key(d, pf):
                # [V35] 코드→이름 맵 1회만 생성 (기존엔 카드마다 재생성 → 세트 많을수록 급격히 느려짐)
                pdb_local = {str(p.get("code","")): p.get("name","") for p in st.session_state.db.get("products", [])}
                cols = st.columns(4); res = {}
                for i, (n, v) in enumerate(d.items()):
                    with cols[i % 4]:
                        img_name = v.get("image") if isinstance(v, dict) else None
                        recipe = v.get("recipe", {}) if isinstance(v, dict) else {}
                        if recipe:
                            tip_lines = [f"· {pdb_local.get(str(c), c)} ×{q}" for c, q in recipe.items()]
                            tooltip_html = "<br>".join(tip_lines)
                        else:
                            tooltip_html = ""
                        if img_name:
                            b64 = get_cached_set_image(n, img_name)
                        else:
                            b64 = None
                        img_html = f'<img src="{b64}" style="width:100%;border-radius:6px 6px 0 0;">' if b64 else '<div style="width:100%;height:110px;background:#2a2a2a;border-radius:6px 6px 0 0;display:flex;align-items:center;justify-content:center;color:#666;font-size:12px;">No Image</div>'
                        set_desc = v.get("desc", "") if isinstance(v, dict) else ""
                        desc_html = f'<div class="set-card-desc">{set_desc}</div>' if set_desc else ""
                        tooltip_block = f'<div class="set-card-tooltip">{tooltip_html}{desc_html}</div>' if (tooltip_html or desc_html) else ""
                        st.markdown(f'<div class="set-card-wrap">{img_html}{tooltip_block}</div>', unsafe_allow_html=True)
                        res[n] = st.number_input(n, 0, key=f"{pf}_{n}_input")
                return res

            # [V35] '전체' 탭은 모든 카드를 한 번 더 렌더(2배 부하) → 기본 꺼두고 필요할 때만 사용
            _show_all = st.checkbox("'전체' 탭 사용 (모든 세트 한눈에 · 미분류 포함 — 로딩 느려짐)",
                                    value=False, key="step1_show_all_tab")
            # [V35] form — 수량 입력 중엔 리런 없음(세트 카드 전체 재전송 방지), '추가' 클릭 때 한 번만 반영
            with st.form("step1_main_sets_form", border=False):
                mt1, mt2, mt3, mt4 = st.tabs(["50mm", "40mm", "기타", "전체"])
                with mt1: inp_m_50 = render_inputs_with_key(grouped.get("50mm", {}), "m50")
                with mt2: inp_m_40 = render_inputs_with_key(grouped.get("40mm", {}), "m40")
                with mt3: inp_m_etc = render_inputs_with_key(grouped.get("기타", {}), "metc")
                with mt4:
                    if _show_all:
                        inp_m_all = render_inputs_with_key(m_sets, "mall")
                    else:
                        inp_m_all = {}
                        st.caption("바로 위 \"'전체' 탭 사용\"을 켜면 모든 세트(미분류 포함)가 여기 표시됩니다.")

                st.write("")
                submitted_main_sets = st.form_submit_button("➕ 입력한 수량 세트 목록에 추가")
            if submitted_main_sets:
                def sum_dictionaries(*dicts):
                    result = {}
                    for d in dicts:
                        for k, v in d.items():
                            result[k] = result.get(k, 0) + v
                    return result
                
                # [V28] 버그수정: 미분류 그룹은 '수량 dict'가 아닌 '세트정보 dict'라 합산 시 TypeError.
                #        미분류 세트는 '전체' 탭(inp_m_all)에 이미 포함되므로 그것으로 충분.
                all_inputs = sum_dictionaries(inp_m_50, inp_m_40, inp_m_etc, inp_m_all)
                
                added_count = 0
                for set_name, qty in all_inputs.items():
                    if qty > 0:
                        st.session_state.set_cart.append({"name": set_name, "qty": qty, "type": "주배관"})
                        added_count += 1
                if added_count > 0:
                    st.success(f"{added_count}개 항목이 목록에 추가되었습니다.")
                else:
                    st.warning("수량을 입력해주세요.")
        with st.expander("2. 가지관 및 기타 세트"):
            # [V35] form — 수량 입력 중 리런 방지 (위와 동일)
            with st.form("step1_sub_sets_form", border=False):
                c1, c2, c3 = st.tabs(["가지관", "살수", "기타자재"])
                with c1: inp_b = render_inputs_with_key(sets.get("가지관세트", {}), "b_set")
                with c2: inp_s = render_inputs_with_key(sets.get("살수세트", {}), "s_set")
                with c3: inp_e = render_inputs_with_key(sets.get("기타자재", {}), "e_set")
                submitted_sub_sets = st.form_submit_button("➕ 가지관/살수/기타 목록 추가")
            if submitted_sub_sets:
                all_inputs = {**inp_b, **inp_s, **inp_e}
                added_count = 0
                for set_name, qty in all_inputs.items():
                    if qty > 0:
                        st.session_state.set_cart.append({"name": set_name, "qty": qty, "type": "기타"})
                        added_count += 1
                if added_count > 0: st.success("추가됨")
                
        if st.session_state.set_cart:
            st.info("📋 선택된 세트 목록 (합산 예정)")
            
            cart_df = pd.DataFrame(st.session_state.set_cart)
            cart_df["삭제"] = False
            
            edited_cart = st.data_editor(
                cart_df,
                width="stretch",
                hide_index=True,
                disabled=["name", "type"],
                column_config={
                    "name": st.column_config.TextColumn("세트명"),
                    "qty": st.column_config.NumberColumn("수량", min_value=1, step=1),
                    "type": st.column_config.TextColumn("구분"),
                    "삭제": st.column_config.CheckboxColumn("삭제?", default=False)
                },
                key="set_cart_editor"
            )
            
            c_btn1, c_btn2 = st.columns(2)
            with c_btn1:
                if st.button("💾 세트 목록 변경사항 적용", use_container_width=True):
                    new_cart = []
                    for _, row in edited_cart.iterrows():
                        if not row.get("삭제"):
                            new_cart.append({
                                "name": row["name"],
                                "qty": int(row["qty"]),
                                "type": row["type"]
                            })
                    st.session_state.set_cart = new_cart
                    st.rerun()
            with c_btn2:
                if st.button("🗑️ 세트 목록 전체 비우기", use_container_width=True):
                    st.session_state.set_cart = []
                    st.rerun()
                    
        st.divider()
        st.markdown("#### 📏 배관 물량 산출 (장바구니)")
        all_products = st.session_state.db["products"]
        
        pipe_type_sel = st.radio("배관 구분", ["주배관", "가지관"], horizontal=True, key="pipe_type_radio")
        filtered_pipes = [p for p in all_products if p["category"] == pipe_type_sel]
        c1, c2, c3 = st.columns([3, 2, 1])
        with c1: sel_pipe = st.selectbox(f"{pipe_type_sel} 선택", filtered_pipes, format_func=format_prod_label, key="pipe_sel")
        with c2: len_pipe = st.number_input("길이(m)", min_value=1, step=1, format="%d", key="pipe_len")
        with c3:
            st.write(""); st.write("")
            if st.button("➕ 목록 추가"):
                if sel_pipe: st.session_state.pipe_cart.append({"type": pipe_type_sel, "name": sel_pipe['name'], "spec": sel_pipe.get("spec", ""), "code": sel_pipe.get("code", ""), "len": len_pipe})
        if st.session_state.pipe_cart:
            st.caption("📋 입력된 배관 목록")
            st.dataframe(pd.DataFrame(st.session_state.pipe_cart), width="stretch", hide_index=True)
            if st.button("🗑️ 비우기"): st.session_state.pipe_cart = []; st.rerun()
        st.divider()
        if st.button("계산하기 (STEP 2)"):
            if not st.session_state.current_quote_name: st.error("현장명을 입력해주세요.")
            else:
                res = {}
                all_sets_db = {}
                for cat, val in sets.items():
                    all_sets_db.update(val)
                for item in st.session_state.set_cart:
                    s_name = item['name']
                    s_qty = item['qty']
                    if s_name in all_sets_db:
                        recipe = all_sets_db[s_name].get("recipe", {})
                        for p_code_or_name, p_qty in recipe.items():
                            res[str(p_code_or_name)] = res.get(str(p_code_or_name), 0) + (p_qty * s_qty)
                code_sums = {}
                for p_item in st.session_state.pipe_cart:
                    c = p_item.get('code')
                    if c: code_sums[c] = code_sums.get(c, 0) + p_item['len']
                for p_code, total_len in code_sums.items():
                    prod_info = next((item for item in all_products if str(item["code"]) == str(p_code)), None)
                    if prod_info:
                        unit_len = prod_info.get("len_per_unit", 4)
                        if unit_len <= 0: unit_len = 4
                        qty = math.ceil(total_len / unit_len)
                        res[str(p_code)] = res.get(str(p_code), 0) + qty
                st.session_state.quote_items = res; st.session_state.quote_step = 2; st.session_state.step3_ready=False; st.session_state.files_ready = False; st.rerun()

    elif st.session_state.quote_step == 2:
        st.subheader("STEP 2. 내용 검토")
        if st.button("⬅️ 1단계(물량수정)로 돌아가기"):
            st.session_state.quote_step = 1
            st.rerun()
        view_opts = ["소비자가"]
        if st.session_state.auth_price: view_opts += ["단가(현장)", "매입가", "총판1", "총판2", "대리점1", "대리점2", "계통농협", "지역농협"]
        c_lock, c_view = st.columns([1, 2])
        with c_lock:
            if not st.session_state.auth_price:
                # [V34] form: Enter로도 해제
                with st.form("step2_price_form"):
                    pw = st.text_input("원가 조회 비번", type="password")
                    if st.form_submit_button("해제"):
                        admin_pwd_db = str(st.session_state.db.get("config", {}).get("admin_pwd", "1234"))
                        if pw == admin_pwd_db: st.session_state.auth_price = True; st.rerun()
                        else: st.error("오류")
            else: st.success("🔓 원가 조회 가능")
        
        with c_view: view = st.radio("단가 보기", view_opts, horizontal=True, key="step2_price_view")
        
        key_map = {
            "매입가":("price_buy","매입"), 
            "총판1":("price_d1","총판1"), "총판2":("price_d2","총판2"), 
            "대리점1":("price_agy1","대리점1"), "대리점2":("price_agy2","대리점2"),
            "계통농협":("price_nh_sys","계통"), "지역농협":("price_nh_loc","지역"),
            "단가(현장)":("price_site", "현장")
        }
        rows = []
        pdb = {}
        for p in st.session_state.db["products"]:
            pdb[p["name"]] = p
            if p.get("code"): pdb[str(p["code"])] = p
        pk = [key_map[view][0]] if view != "소비자가" else ["price_cons"]
        for n, q in st.session_state.quote_items.items():
            inf = pdb.get(str(n), {})
            if not inf: continue
            
            if view == "소비자가" and inf.get("category", "") == "관급비용":
                continue
                
            cpr = inf.get("price_cons", 0)
            row = {"품목": inf.get("name", n), "규격": inf.get("spec", ""), "수량": q, "소비자가": cpr, "합계": cpr*q}
            if view != "소비자가":
                k, l = key_map[view]
                pr = inf.get(k, 0)
                row[f"{l}단가"] = pr; row[f"{l}합계"] = pr*q
                row["이익"] = row["합계"] - row[f"{l}합계"]
                row["율(%)"] = (row["이익"]/row["합계"]*100) if row["합계"] else 0
            rows.append(row)
        
        disp = ["품목", "규격", "수량"]
        if view == "소비자가": disp += ["소비자가", "합계"]
        else: 
            l = key_map[view][1]
            disp += [f"{l}단가", f"{l}합계", "소비자가", "합계", "이익", "율(%)"]
            
        if rows:
            df = pd.DataFrame(rows)
        else:
            df = pd.DataFrame(columns=disp)
            
        st.dataframe(df[disp], width="stretch", hide_index=True)
        
        st.divider()
        with st.expander("🛒 추가된 부품 수정 및 삭제", expanded=False):
            parts_list = []
            for k, v in st.session_state.quote_items.items():
                inf = pdb.get(str(k), {})
                p_code = inf.get("code", str(k))
                p_name = inf.get("name", str(k))
                parts_list.append({
                    "품목코드": p_code,
                    "품목명": p_name,
                    "수량": int(v),
                    "삭제": False,
                    "_orig_key": str(k)
                })
            
            if parts_list:
                parts_df = pd.DataFrame(parts_list)
                edited_parts = st.data_editor(
                    parts_df,
                    width="stretch",
                    hide_index=True,
                    disabled=["품목코드", "품목명"],
                    column_config={
                        "삭제": st.column_config.CheckboxColumn("삭제?", default=False),
                        "수량": st.column_config.NumberColumn("수량", min_value=1, step=1),
                        "_orig_key": None
                    },
                    key="parts_cart_editor"
                )
                
                if st.button("💾 부품 변경사항 적용", use_container_width=True):
                    new_quote_items = {}
                    for _, row in edited_parts.iterrows():
                        if not row.get("삭제"):
                            new_quote_items[row["_orig_key"]] = int(row["수량"])
                    st.session_state.quote_items = new_quote_items
                    st.rerun()
            else:
                st.info("장바구니에 담긴 부품이 없습니다.")

        st.divider()
        col_add_part, col_add_cost = st.columns([1, 1])
        with col_add_part:
            st.markdown("##### ➕ 부품 추가")
            with st.container(border=True):
                all_products = st.session_state.db["products"]
                ap_obj = st.selectbox("품목 선택", all_products, format_func=format_prod_label, key="step2_add_part")
                c_qty, c_btn = st.columns([2, 1])
                with c_qty: aq = st.number_input("수량", 1, key="step2_add_qty")
                with c_btn:
                    st.write("")
                    if st.button("추가", use_container_width=True): st.session_state.quote_items[str(ap_obj['code'])] = st.session_state.quote_items.get(str(ap_obj['code']), 0) + aq; st.rerun()
        with col_add_cost:
            st.markdown("##### 💰 비용 추가")
            with st.container(border=True):
                c_type, c_amt = st.columns([1, 1])
                with c_type: stype = st.selectbox("항목", ["배송비", "용역비", "기타"], key="step2_cost_type")
                with c_amt: sp = st.number_input("금액", 0, step=1000, key="step2_cost_amt")
                sn = stype
                if stype == "기타": sn = st.text_input("내용 입력", key="step2_cost_desc")
                if st.button("비용 리스트에 추가", use_container_width=True): st.session_state.services.append({"항목": sn, "금액": sp}); st.rerun()
        if st.session_state.services:
            st.caption("추가된 비용 목록"); st.table(st.session_state.services)
        st.divider()
        if st.button("최종 확정 (STEP 3)", type="primary", use_container_width=True): 
            st.session_state.quote_step = 3
            st.session_state.step3_ready = False
            st.session_state.files_ready = False
            st.rerun()

    elif st.session_state.quote_step == 3:
        st.header("🏁 최종 견적")
        if not st.session_state.get("files_ready"):
            st.info("💡 불러온 견적(또는 수정 중인 견적)입니다. 내용을 확인하신 후 하단의 **[📄 견적서 파일 생성하기]** 버튼을 눌러야 명세서가 나타납니다.")
        if not st.session_state.current_quote_name: st.warning("현장명(저장)을 확인해주세요!")
        st.markdown("##### 🖨️ 출력 옵션")
        c_date, c_opt1, c_opt2 = st.columns([1, 1, 1])
        
        with c_date: 
            q_date = st.date_input("견적일", datetime.datetime.now())
            
        with c_opt1: 
            idx_form = 0 if st.session_state.ui_state.get("form_type", "기본 양식") == "기본 양식" else 1
            form_type = st.radio("양식", ["기본 양식", "이익 분석 양식"], index=idx_form, key="step3_form_type")
            
            current_pm = st.session_state.ui_state.get("print_mode", "개별 품목 나열 (기존)")
            idx_print = 0
            if current_pm == "세트 단위 묶음 (신규)": idx_print = 1
            elif current_pm == "세트별 부품 분해 (납품 패킹용)": idx_print = 2
            print_mode = st.radio("출력 형태", ["개별 품목 나열 (기존)", "세트 단위 묶음 (신규)", "세트별 부품 분해 (납품 패킹용)"], index=idx_print, key="step3_print_mode")
            
            idx_vat = 0 if st.session_state.ui_state.get("vat_mode", "포함 (기본)") == "포함 (기본)" else 1
            vat_mode = st.radio("부가세", ["포함 (기본)", "별도"], index=idx_vat, key="step3_vat_mode")
            
        with c_opt2:
            basic_opts = ["소비자가", "단가(현장)"]
            admin_opts = ["매입단가", "총판가1", "총판가2", "대리점가1", "대리점가2", "계통농협", "지역농협"]
            opts = basic_opts + (admin_opts if st.session_state.auth_price else [])
            
            if "이익" in form_type and not st.session_state.auth_price:
                st.warning("🔒 원가 정보를 보려면 비밀번호를 입력하세요.")
                # [V34] form: Enter로도 해제
                with st.form("step3_pw_form"):
                    c_pw, c_btn = st.columns([2,1])
                    with c_pw: input_pw = st.text_input("비밀번호", type="password", key="step3_pw")
                    with c_btn:
                        st.write("")
                        submitted_pw = st.form_submit_button("해제", use_container_width=True)
                    if submitted_pw:
                        admin_pwd_db = str(st.session_state.db.get("config", {}).get("admin_pwd", "1234"))
                        if input_pw == admin_pwd_db: st.session_state.auth_price = True; st.rerun()
                        else: st.error("불일치")
                st.stop()
                
            saved_sel = st.session_state.ui_state.get("sel", ["소비자가"])
            valid_sel = [s for s in saved_sel if s in opts]
            if not valid_sel: valid_sel = ["소비자가"]

            if "기본" in form_type: 
                sel = st.multiselect("출력 단가 (1개 선택)", opts, default=valid_sel[:1], max_selections=1, key="step3_sel_basic")
            else: 
                sel = st.multiselect("비교 단가 (2개)", opts, default=valid_sel[:2], max_selections=2, key="step3_sel_profit")

        st.session_state.ui_state["form_type"] = form_type
        st.session_state.ui_state["print_mode"] = print_mode
        st.session_state.ui_state["vat_mode"] = vat_mode
        st.session_state.ui_state["sel"] = sel

        if "기본" in form_type and len(sel) != 1: st.warning("출력할 단가를 1개 선택해주세요."); st.stop()
        if "이익" in form_type and len(sel) < 2: st.warning("비교할 단가를 2개 선택해주세요."); st.stop()

        price_rank = {"매입단가": 0, "총판가1": 1, "총판가2": 2, "대리점가1": 3, "대리점가2": 4, "계통농협": 5, "지역농협": 6, "단가(현장)": 7, "소비자가": 8}
        if sel: sel = sorted(sel, key=lambda x: price_rank.get(x, 9))
        pkey = {
            "매입단가":"price_buy", "총판가1":"price_d1", "총판가2":"price_d2", 
            "대리점가1":"price_agy1", "대리점가2":"price_agy2",
            "계통농협":"price_nh_sys", "지역농협":"price_nh_loc",
            "소비자가":"price_cons", "단가(현장)":"price_site"
        }
        
        if "last_sel" not in st.session_state: st.session_state.last_sel = []
        selectors_changed = (st.session_state.last_sel != sel)
        
        cp_map = {}
        if st.session_state.get("custom_prices"):
            for cp in st.session_state.custom_prices:
                k = str(cp.get("코드", "")).strip().zfill(5) if str(cp.get("코드", "")).strip() else str(cp.get("품목", "")).strip()
                cp_map[k] = cp

        if not st.session_state.step3_ready or selectors_changed:
            pdb = {}
            for p in st.session_state.db["products"]:
                pdb[p["name"]] = p
                if p.get("code"): pdb[str(p["code"])] = p
            
            pk = [pkey[l] for l in sel] if sel else ["price_cons"]
            
            fdata = []
            processed_keys = set()
            
            for n, q in st.session_state.quote_items.items():
                inf = pdb.get(str(n), {})
                if not inf: continue
                
                if "소비자가" in sel and inf.get("category", "") == "관급비용":
                    continue
                
                code_val = str(inf.get("code", "")).strip().zfill(5)
                name_val = str(inf.get("name", n)).strip()
                code_key = code_val if code_val and code_val != "00000" else name_val
                
                d = {
                    "품목": name_val, 
                    "규격": inf.get("spec", ""), 
                    "코드": inf.get("code", ""), 
                    "단위": inf.get("unit", "EA"), 
                    "수량": int(q), 
                    "image_data": inf.get("image")
                }
                
                d["price_1"] = int(inf.get(pk[0], 0))
                if len(pk)>1: d["price_2"] = int(inf.get(pk[1], 0))
                else: d["price_2"] = 0
                
                if code_key in cp_map:
                    d["수량"] = int(cp_map[code_key].get("수량", d["수량"]))
                    if not selectors_changed:
                        d["price_1"] = int(cp_map[code_key].get("price_1", d["price_1"]))
                        d["price_2"] = int(cp_map[code_key].get("price_2", d["price_2"]))
                    processed_keys.add(code_key)
                    
                fdata.append(d)
                
            if st.session_state.get("custom_prices"):
                for cp in st.session_state.custom_prices:
                    k = str(cp.get("코드", "")).strip().zfill(5) if str(cp.get("코드", "")).strip() else str(cp.get("품목", "")).strip()
                    if k not in processed_keys:
                        fdata.append(cp.copy())
                        
            st.session_state.final_edit_df = pd.DataFrame(fdata)
            st.session_state.step3_ready = True
            st.session_state.last_sel = sel
            st.session_state.files_ready = False 

        st.markdown("---")
        
        pk = [pkey[l] for l in sel] if sel else ["price_cons"]
        disp_cols = ["품목", "규격", "코드", "단위", "수량", "price_1"]
        if len(pk) > 1: disp_cols.append("price_2")
        
        for c in disp_cols:
            if c not in st.session_state.final_edit_df.columns:
                st.session_state.final_edit_df[c] = 0 if "price" in c or "수량" in c else ""

        # [V13] 규격/코드/품목/단위 강제 문자열화 — Arrow 직렬화(ArrowTypeError) 방지
        for _c in ["규격", "코드", "품목", "단위"]:
            if _c in st.session_state.final_edit_df.columns:
                st.session_state.final_edit_df[_c] = st.session_state.final_edit_df[_c].astype(str)

        def on_data_change():
            st.session_state.files_ready = False

        with st.expander("➕ 수기 품목 추가 (DB 미등록 품목)", expanded=False):
            c1, c2, c3, c4, c5 = st.columns([3, 2, 1, 1, 2])
            m_name = c1.text_input("품목명 (필수)", key="m_name")
            m_spec = c2.text_input("규격", key="m_spec")
            m_unit = c3.text_input("단위", "EA", key="m_unit")
            m_qty = c4.number_input("수량", 1, key="m_qty")
            m_price = c5.number_input("단가", 0, key="m_price")
            
            if st.button("리스트에 추가", key="btn_add_manual"):
                if m_name:
                    new_row = {
                        "품목": m_name, 
                        "규격": m_spec, 
                        "코드": "", 
                        "단위": m_unit, 
                        "수량": m_qty, 
                        "price_1": m_price, 
                        "price_2": 0, 
                        "image_data": ""
                    }
                    st.session_state.final_edit_df = pd.concat([st.session_state.final_edit_df, pd.DataFrame([new_row])], ignore_index=True)
                    st.session_state.files_ready = False
                    st.rerun()
                else:
                    st.warning("품목명을 입력해주세요.")

        edited = st.data_editor(
            st.session_state.final_edit_df[disp_cols], 
            num_rows="dynamic",
            width="stretch", 
            hide_index=True,
            column_config={
                "품목": st.column_config.TextColumn(required=True),
                "규격": st.column_config.TextColumn(),
                "코드": st.column_config.TextColumn(),
                "단위": st.column_config.TextColumn(),
                "수량": st.column_config.NumberColumn(step=1, required=True),
                "price_1": st.column_config.NumberColumn(label=sel[0] if sel else "단가", format="%d", required=True),
                "price_2": st.column_config.NumberColumn(label=sel[1] if len(sel)>1 else "", format="%d")
            },
            on_change=on_data_change
        )
        
        st.session_state.final_edit_df = edited

        if sel:
            st.write("")
            if st.button("📄 견적서 파일 생성하기 (PDF/Excel)", type="primary", use_container_width=True):
                with st.spinner("파일을 생성하고 있습니다... (이미지 다운로드 및 변환 중)"):
                    fmode = "basic" if "기본" in form_type else "profit"
                    safe_data = edited.fillna(0).to_dict('records')

                    # [V13 IMG-FIX] data_editor가 image_data 컬럼을 떨어뜨리므로,
                    # final_edit_df 원본에서 코드(우선)·품목명(차선) 기준으로 image_data 복원
                    try:
                        _src_df = st.session_state.get("final_edit_df")
                        if _src_df is not None and "image_data" in _src_df.columns:
                            _img_by_code = {}
                            _img_by_name = {}
                            for _r in _src_df.to_dict("records"):
                                _iv = _r.get("image_data", "")
                                if not _iv:
                                    continue
                                _ck = str(_r.get("코드", "")).strip().zfill(5)
                                if _ck and _ck != "00000":
                                    _img_by_code[_ck] = _iv
                                _nm = str(_r.get("품목", "")).strip()
                                if _nm:
                                    _img_by_name[_nm] = _iv
                            for _it in safe_data:
                                if _it.get("image_data"):
                                    continue
                                _ck = str(_it.get("코드", "")).strip().zfill(5)
                                _nm = str(_it.get("품목", "")).strip()
                                if _ck in _img_by_code:
                                    _it["image_data"] = _img_by_code[_ck]
                                elif _nm in _img_by_name:
                                    _it["image_data"] = _img_by_name[_nm]
                    except Exception:
                        pass

                    pdf_excel_services = []
                    for s in st.session_state.services:
                        pdf_excel_services.append(s.copy())
                        
                    if vat_mode == "별도":
                        for item in safe_data:
                            try: item['price_1'] = int(round(float(item.get('price_1', 0)) / 1.1))
                            except: pass
                            try: item['price_2'] = int(round(float(item.get('price_2', 0)) / 1.1))
                            except: pass
                        for svc in pdf_excel_services:
                            try: svc['금액'] = int(round(float(svc.get('금액', 0)) / 1.1))
                            except: pass

                    def sort_items(item_list):
                        high = [x for x in item_list if int(float(x.get('price_1', 0))) >= 20000]
                        norm = [x for x in item_list if int(float(x.get('price_1', 0))) < 20000]
                        high.sort(key=lambda x: int(float(x.get('price_1', 0))), reverse=True)
                        norm.sort(key=lambda x: str(x.get('품목', '')))
                        return high + norm

                    individual_sorted_data = sort_items(safe_data)

                    if print_mode == "세트별 부품 분해 (납품 패킹용)":
                        expanded_data = []
                        pool = {}; price_map_1 = {}; price_map_2 = {}
                        for item in safe_data:
                            k = str(item.get("코드", "")).strip().zfill(5)
                            if k == "00000" or not k: k = str(item.get("품목", "")).strip()
                            pool[k] = pool.get(k, 0) + int(float(item.get("수량", 0)))
                            price_map_1[k] = int(float(item.get("price_1", 0)))
                            price_map_2[k] = int(float(item.get("price_2", 0)))
                        
                        all_sets_db = {}
                        for cat, val in st.session_state.db.get("sets", {}).items(): all_sets_db.update(val)
                        
                        for s_item in st.session_state.set_cart:
                            s_name = s_item['name']
                            s_qty = s_item['qty']
                            if s_qty <= 0 or s_name not in all_sets_db: continue
                            recipe = all_sets_db[s_name].get("recipe", {})
                            
                            for p_code_or_name, p_qty_per_set in recipe.items():
                                p_key = str(p_code_or_name).strip().zfill(5)
                                if p_key not in pool: p_key = str(p_code_or_name).strip()
                                req_qty = p_qty_per_set * s_qty
                                prod_info = next((p for p in st.session_state.db["products"] if str(p.get("code","")).strip().zfill(5) == p_key or p.get("name") == p_key), {})
                                
                                expanded_data.append({
                                    "품목": f"[{s_name}] {prod_info.get('name', p_key)}",
                                    "규격": prod_info.get("spec", ""),
                                    "코드": prod_info.get("code", p_key),
                                    "단위": prod_info.get("unit", "EA"),
                                    "수량": req_qty,
                                    "price_1": price_map_1.get(p_key, 0),
                                    "price_2": price_map_2.get(p_key, 0),
                                    "image_data": prod_info.get("image", "")
                                })
                                if p_key in pool: pool[p_key] -= req_qty
                                
                        for p_item in st.session_state.pipe_cart:
                            p_code = p_item.get('code')
                            p_len = p_item.get('len', 0)
                            prod_info = next((p for p in st.session_state.db["products"] if str(p.get("code","")).strip().zfill(5) == p_code), {})
                            unit_len = prod_info.get("len_per_unit", 4) if prod_info else 4
                            req_qty = math.ceil(p_len / (unit_len if unit_len > 0 else 4))
                            p_key = str(p_code).strip().zfill(5)
                            
                            expanded_data.append({
                                "품목": f"[배관] {prod_info.get('name', p_item.get('name'))}",
                                "규격": prod_info.get("spec", p_item.get("spec", "")),
                                "코드": p_code,
                                "단위": prod_info.get("unit", "EA"),
                                "수량": req_qty,
                                "price_1": price_map_1.get(p_key, 0),
                                "price_2": price_map_2.get(p_key, 0),
                                "image_data": prod_info.get("image", "")
                            })
                            if p_key in pool: pool[p_key] -= req_qty
                            
                        for item in safe_data:
                            k = str(item.get("코드", "")).strip().zfill(5)
                            if k == "00000" or not k: k = str(item.get("품목", "")).strip()
                            rem_qty = pool.get(k, 0)
                            if rem_qty > 0:
                                new_item = item.copy()
                                new_item["품목"] = f"[추가/별도] {item.get('품목')}"
                                new_item["수량"] = rem_qty
                                expanded_data.append(new_item)
                                pool[k] = 0
                                
                        sorted_final_data = expanded_data
                    elif print_mode == "세트 단위 묶음 (신규)":
                        comp_pool = {}
                        comp_price1 = {}
                        comp_price2 = {}
                        
                        for item in safe_data:
                            match_key = str(item.get("코드", "")).strip().zfill(5)
                            if not match_key or match_key == "00000":
                                match_key = str(item.get("품목", "")).strip()
                            
                            qty = int(float(item.get("수량", 0)))
                            comp_pool[match_key] = comp_pool.get(match_key, 0) + qty
                            comp_price1[match_key] = int(float(item.get("price_1", 0)))
                            comp_price2[match_key] = int(float(item.get("price_2", 0)))

                        set_items_out = []
                        all_sets_db = {}
                        for cat, val in st.session_state.db.get("sets", {}).items(): 
                            all_sets_db.update(val)
                            
                        for s_item in st.session_state.set_cart:
                            s_name = s_item['name']
                            s_qty = s_item['qty']
                            if s_qty <= 0: continue
                            
                            s_price1 = 0
                            s_price2 = 0
                            s_img = ""
                            
                            if s_name in all_sets_db:
                                recipe = all_sets_db[s_name].get("recipe", {})
                                s_img = all_sets_db[s_name].get("image", "")
                                
                                for p_code_or_name, p_qty_per_set in recipe.items():
                                    p_key = str(p_code_or_name).strip().zfill(5)
                                    if p_key not in comp_pool:
                                        p_key = str(p_code_or_name).strip()
                                        
                                    p1 = comp_price1.get(p_key, 0)
                                    p2 = comp_price2.get(p_key, 0)
                                    
                                    s_price1 += (p1 * p_qty_per_set)
                                    s_price2 += (p2 * p_qty_per_set)
                                    
                                    if p_key in comp_pool:
                                        comp_pool[p_key] -= (p_qty_per_set * s_qty)
                                        
                            set_items_out.append({
                                "품목": s_name,
                                "규격": "세트",
                                "코드": s_name, 
                                "단위": "SET",
                                "수량": s_qty,
                                "price_1": s_price1,
                                "price_2": s_price2,
                                "image_data": s_img
                            })
                            
                        rem_items_out = []
                        for item in safe_data:
                            match_key = str(item.get("코드", "")).strip().zfill(5)
                            if not match_key or match_key == "00000":
                                match_key = str(item.get("품목", "")).strip()
                                
                            rem_qty = comp_pool.get(match_key, 0)
                            if rem_qty > 0:
                                new_item = item.copy()
                                new_item["수량"] = rem_qty
                                rem_items_out.append(new_item)
                                comp_pool[match_key] = 0 # Prevent duplicate addition
                        
                        sorted_final_data = sort_items(set_items_out) + sort_items(rem_items_out)
                    else:
                        sorted_final_data = individual_sorted_data
                    
                    st.session_state.gen_pdf = create_advanced_pdf(sorted_final_data, pdf_excel_services, st.session_state.current_quote_name, q_date.strftime("%Y-%m-%d"), fmode, sel, st.session_state.buyer_info, st.session_state.quote_remarks)
                    st.session_state.gen_excel = create_quote_excel(sorted_final_data, pdf_excel_services, st.session_state.current_quote_name, q_date.strftime("%Y-%m-%d"), fmode, sel, st.session_state.buyer_info, st.session_state.quote_remarks)
                    
                    st.session_state.gen_comp_pdf = create_composition_pdf(st.session_state.set_cart, st.session_state.pipe_cart, individual_sorted_data, st.session_state.db['products'], st.session_state.db['sets'], st.session_state.current_quote_name)
                    st.session_state.gen_comp_excel = create_composition_excel(st.session_state.set_cart, st.session_state.pipe_cart, individual_sorted_data, st.session_state.db['products'], st.session_state.db['sets'], st.session_state.current_quote_name)
                    
                    st.session_state.files_ready = True
                st.rerun()

            if st.session_state.files_ready:
                st.success("파일 생성이 완료되었습니다! 아래 버튼을 눌러 다운로드하세요.")
                col_pdf, col_xls = st.columns(2)
                with col_pdf:
                    st.download_button("📥 견적서 PDF", st.session_state.gen_pdf, f"quote_{st.session_state.current_quote_name}.pdf", "application/pdf", type="primary", use_container_width=True)
                with col_xls:
                    st.download_button("📊 견적서 엑셀", st.session_state.gen_excel, f"quote_{st.session_state.current_quote_name}.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", use_container_width=True)
                
                st.write("")
                st.markdown("##### 📂 자재 구성 명세서 다운로드")
                c_comp_pdf, c_comp_xls = st.columns(2)
                with c_comp_pdf:
                    st.download_button("📥 자재명세 PDF", st.session_state.gen_comp_pdf, f"composition_{st.session_state.current_quote_name}.pdf", "application/pdf", use_container_width=True)
                with c_comp_xls:
                    st.download_button("📊 자재명세 엑셀", st.session_state.gen_comp_excel, f"composition_{st.session_state.current_quote_name}.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", use_container_width=True)
            else:
                st.info("👆 위 버튼을 눌러 파일을 생성해주세요. (데이터 수정 시 다시 생성해야 합니다)")
        
        st.write("")
        st.markdown("##### 📝 특약사항 및 비고 (수정 가능)")
        st.session_state.quote_remarks = st.text_area(
            "특약사항", 
            value=st.session_state.quote_remarks, 
            height=100, 
            label_visibility="collapsed"
        )

        c1, c2 = st.columns(2)
        with c1: 
            if st.button("⬅️ 수정 (이전 단계)"): 
                st.session_state.quote_step = 2
                st.session_state.step3_ready = False
                st.session_state.files_ready = False
                st.rerun()
        with c2:
            if st.button("🔄 처음으로"):
                st.session_state.quote_step = 1
                st.session_state.quote_items = {}
                st.session_state.services = []
                st.session_state.pipe_cart = []
                st.session_state.set_cart = []
                st.session_state.buyer_info = {"manager": "", "phone": "", "addr": "", "serial": "", "recipient": "", "ref": "", "pay_cond": "/", "valid_period": "견적 후 15일 이내"}
                st.session_state.current_quote_name = ""
                st.session_state.step3_ready = False
                st.session_state.files_ready = False
                st.rerun()

# [V28] 브랜드 푸터 (V27 정의분 활성화)
render_brand_footer()

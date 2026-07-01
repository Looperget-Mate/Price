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

# 구글 연동 라이브러리
import gspread
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload

# ==========================================
# [중요] 0. 페이지 설정을 최상단으로 유지
# ==========================================
st.set_page_config(layout="wide", page_title="루퍼젯 프로 매니저 V12.0")

# 비상용 기본 데이터 글로벌 선언 (NameError 방지)
DEFAULT_DATA = {
    "config": {"password": "1234"}, 
    "products": [], 
    "sets": {}, 
    "jp_quotes": [], 
    "kr_quotes": []
}

# ==========================================
# 1. 설정 및 구글 연동 유틸리티
# ==========================================
FONT_REGULAR = "NanumGothic.ttf"
FONT_BOLD = "NanumGothic-Bold.ttf"

FONT_URL = "https://github.com/google/fonts/raw/main/ofl/nanumgothic/NanumGothic-Regular.ttf"
FONT_BOLD_URL = "https://github.com/google/fonts/raw/main/ofl/nanumgothic/NanumGothic-Bold.ttf"

import urllib.request
if not os.path.exists(FONT_REGULAR):
    if os.path.exists("NanumGothic-Regular.ttf"): FONT_REGULAR = "NanumGothic-Regular.ttf"
    else:
        try: urllib.request.urlretrieve(FONT_URL, "NanumGothic.ttf"); FONT_REGULAR = "NanumGothic.ttf"
        except: pass

if not os.path.exists(FONT_BOLD):
    if os.path.exists("NanumGothic-ExtraBold.ttf"): FONT_BOLD = "NanumGothic-ExtraBold.ttf"
    else:
        try: urllib.request.urlretrieve(FONT_BOLD_URL, "NanumGothic-Bold.ttf"); FONT_BOLD = "NanumGothic-Bold.ttf"
        except: pass

SCOPES = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]

def _build_google_services():
    """구글 서비스 객체 생성 (재연결용)"""
    try:
        creds_dict = dict(st.secrets["gcp_service_account"])
        creds = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
        gc = gspread.authorize(creds)
        drive_service = build('drive', 'v3', credentials=creds)
        return gc, drive_service
    except Exception as e:
        st.error(f"구글 서비스 인증 실패: {e}")
        return None, None

@st.cache_resource(ttl=1800)  # 30분마다 자동 재인증 → Broken Pipe 방지
def get_google_services():
    return _build_google_services()

gc, drive_service = get_google_services()

# --- 구글 드라이브 함수 ---
DRIVE_FOLDER_NAME = "Looperget_Images"
DRIVE_SET_FOLDER_NAME = "Looperget_Images" 
ADMIN_FOLDER_NAME = "Looperget_Admin"
ADMIN_PPT_NAME = "Set_Composition_Master.pptx"

def _get_ds():
    """항상 최신 drive_service 반환 (ttl=1800 캐시 기반)"""
    return get_google_services()[1]

def get_or_create_drive_folder():
    ds = _get_ds()
    if not ds: return None
    # [V20] 공유 드라이브 전환 대비: secrets에 DRIVE_FOLDER_ID가 있으면 이름검색 대신 ID 직접 사용
    #       (옛 '내 드라이브' 폴더 오인 방지. 미설정 시 아래 기존 이름검색 로직 그대로 → 후방호환)
    try:
        _fixed_id = st.secrets.get("DRIVE_FOLDER_ID", "")
        if _fixed_id:
            return _fixed_id
    except Exception:
        pass
    try:
        query_shared = f"name='{DRIVE_FOLDER_NAME}' and mimeType='application/vnd.google-apps.folder' and sharedWithMe=true and trashed=false"
        results_shared = ds.files().list(q=query_shared, fields="files(id)", includeItemsFromAllDrives=True, supportsAllDrives=True, corpora="allDrives").execute()
        files_shared = results_shared.get('files', [])
        if files_shared: return files_shared[0]['id']
        query = f"name='{DRIVE_FOLDER_NAME}' and mimeType='application/vnd.google-apps.folder' and trashed=false"
        results = ds.files().list(q=query, fields="files(id)", includeItemsFromAllDrives=True, supportsAllDrives=True, corpora="allDrives").execute()
        files = results.get('files', [])
        if files: return files[0]['id']
        # [V20] 유령 폴더 생성 폴백 제거: 서비스계정(용량 0) 소유의 빈 폴더가 생기면
        #       이후 검색이 가짜 폴더를 잡는 사고 발생. 미발견 시 None 반환(업로드 단의 수동안내가 처리).
        return None
    except Exception as e:
        err = str(e)
        if "Broken pipe" in err or "Errno 32" in err:
            try:
                get_google_services.clear()
                ds2 = _get_ds()
                if ds2:
                    q2 = f"name='{DRIVE_FOLDER_NAME}' and mimeType='application/vnd.google-apps.folder' and trashed=false"
                    # [V20] 재시도 경로에도 전 드라이브 플래그 추가 (공유 드라이브 폴더 누락 방지)
                    r2 = ds2.files().list(q=q2, fields="files(id)", includeItemsFromAllDrives=True, supportsAllDrives=True, corpora="allDrives").execute()
                    f2 = r2.get('files', [])
                    if f2: return f2[0]['id']
            except Exception:
                pass
        return None  # st.warning 제거 → 반복 오류 메시지 차단

def get_or_create_set_drive_folder():
    return get_or_create_drive_folder()

def upload_image_to_drive(file_obj, filename):
    folder_id = get_or_create_drive_folder()
    if not folder_id: return None
    try:
        file_content = file_obj.getvalue()
        buffer = io.BytesIO(file_content)
        buffer.seek(0)
        file_metadata = {'name': filename, 'parents': [folder_id]}
        media = MediaIoBaseUpload(buffer, mimetype=file_obj.type, resumable=False)
        _get_ds().files().create(body=file_metadata, media_body=media, fields='id', supportsAllDrives=True).execute()
        return filename
    except Exception as e:
        st.error(f"업로드 실패: {e}")
        return None

def upload_set_image_to_drive(file_obj, filename):
    folder_id = get_or_create_drive_folder()
    if not folder_id: return None
    try:
        file_content = file_obj.getvalue()
        buffer = io.BytesIO(file_content)
        buffer.seek(0)
        file_metadata = {'name': filename, 'parents': [folder_id]}
        media = MediaIoBaseUpload(buffer, mimetype=file_obj.type, resumable=False)
        file_info = _get_ds().files().create(body=file_metadata, media_body=media, fields='id', supportsAllDrives=True).execute()
        return file_info.get('id')
    except Exception as e:
        error_msg = str(e)
        if "storageQuotaExceeded" in error_msg:
            st.error("⚠️ 구글 드라이브 용량/권한 정책으로 인해 봇이 직접 파일을 업로드할 수 없습니다.")
            st.info(f"💡 해결책: '{filename}' 파일을 구글 드라이브 '{DRIVE_FOLDER_NAME}' 폴더에 직접 올리신 후, 상단의 [🔄 드라이브 세트 이미지 자동 동기화] 버튼을 눌러주세요.")
        else:
            st.error(f"세트 이미지 업로드 실패: {e}")
        return None

def upload_bytes_to_drive(byte_data: bytes, filename: str, mimetype: str = "image/png") -> str | None:
    """bytes 데이터를 드라이브에 직접 업로드. 빌더 PNG/PPTX 저장에 사용."""
    folder_id = get_or_create_drive_folder()
    if not folder_id: return None
    try:
        buffer = io.BytesIO(byte_data)
        buffer.seek(0)
        file_metadata = {'name': filename, 'parents': [folder_id]}
        media = MediaIoBaseUpload(buffer, mimetype=mimetype, resumable=False)
        file_info = _get_ds().files().create(body=file_metadata, media_body=media, fields='id', supportsAllDrives=True).execute()
        return file_info.get('id')
    except Exception as e:
        st.error(f"업로드 실패: {e}")
        return None

@st.cache_data(ttl=600)
def get_drive_file_map():
    folder_id = get_or_create_drive_folder()
    if not folder_id: return {}
    file_map = {}
    ds = get_google_services()[1]
    if not ds: return {}
    try:
        query = f"'{folder_id}' in parents and trashed=false"
        page_token = None
        while True:
            response = ds.files().list(q=query, spaces='drive', fields='nextPageToken, files(id, name)', pageToken=page_token, includeItemsFromAllDrives=True, supportsAllDrives=True).execute()
            files = response.get('files', [])
            for f in files:
                name_stem = os.path.splitext(f['name'])[0]
                if name_stem.isdigit():
                    norm_name = str(name_stem).zfill(5)
                    file_map[norm_name] = f['id']
                file_map[name_stem] = f['id']
            page_token = response.get('nextPageToken', None)
            if page_token is None: break
    except Exception as e:
        err = str(e)
        if "Broken pipe" in err or "Errno 32" in err:
            get_google_services.clear()  # 다음 호출 시 재인증
    return file_map

@st.cache_data(ttl=600)
def get_drive_file_map_deep():
    """
    [V18] Looperget_Images 루트 + 모든 하위 폴더(products, sets 등)를 재귀 스캔.
    파일명(확장자 제외)을 키로, 파일 ID를 값으로. 숫자 파일명은 zfill(5) 키도 함께 생성.
    [V25, 2026-06-30] 같은 이름이 여러 폴더에 있으면 '가장 최근 수정' 파일이 이김.
      (마이그레이션 복사본(sets/)이 새 빌더 저장(루트)을 가리던 버그 수정 — 옛 '하위폴더 우선' 폐기.)
    """
    root_id = get_or_create_drive_folder()
    if not root_id: return {}
    ds = get_google_services()[1]
    if not ds: return {}
    file_map = {}
    file_mtime = {}  # 키별 채택 파일의 modifiedTime — 이름 충돌 시 최신 우선

    def _put(key, fid, mt):
        if key not in file_map or (mt or "") >= (file_mtime.get(key) or ""):
            file_map[key] = fid
            file_mtime[key] = mt or ""

    def _scan(folder_id):
        subfolders = []
        page_token = None
        try:
            while True:
                resp = ds.files().list(
                    q=f"'{folder_id}' in parents and trashed=false",
                    spaces='drive',
                    fields='nextPageToken, files(id, name, mimeType, modifiedTime)',
                    pageToken=page_token,
                    includeItemsFromAllDrives=True, supportsAllDrives=True
                ).execute()
                for f in resp.get('files', []):
                    if f.get('mimeType') == 'application/vnd.google-apps.folder':
                        subfolders.append(f['id'])
                    else:
                        stem = os.path.splitext(f['name'])[0]
                        mt = f.get('modifiedTime', '')
                        if stem.isdigit():
                            _put(str(stem).zfill(5), f['id'], mt)
                        _put(stem, f['id'], mt)
                page_token = resp.get('nextPageToken')
                if not page_token: break
        except Exception as e:
            err = str(e)
            if "Broken pipe" in err or "Errno 32" in err:
                get_google_services.clear()
            return
        for sid in subfolders:
            _scan(sid)

    _scan(root_id)
    return file_map

@st.cache_data(ttl=600)
def get_set_drive_file_map():
    return get_drive_file_map()

def _do_download_image(ds, file_id):
    """실제 드라이브 다운로드 (재시도 로직 분리)
    - 원본 비율 유지 (지주대 등 세장형 품목 대응)
    - 300×225 박스 안에 중앙 패딩 배치
    - 드라이브 파일 원본은 건드리지 않음
    """
    request = ds.files().get_media(fileId=file_id)
    downloader = request.execute()
    with Image.open(io.BytesIO(downloader)) as img:
        img_rgb = img.convert('RGB')
        # 비율 유지하면서 300×225 박스 안에 맞춤 (LANCZOS: 고품질 다운샘플링)
        img_rgb.thumbnail((300, 225), Image.LANCZOS)
        # 흰 배경 300×225 캔버스에 중앙 배치 (비율이 달라도 여백으로 채움)
        padded = Image.new('RGB', (300, 225), (255, 255, 255))
        offset_x = (300 - img_rgb.width) // 2
        offset_y = (225 - img_rgb.height) // 2
        padded.paste(img_rgb, (offset_x, offset_y))
        img_rgb.close()
        buffer = io.BytesIO()
        padded.save(buffer, format="JPEG", quality=85)
    return f"data:image/jpeg;base64,{base64.b64encode(buffer.getvalue()).decode()}"

# 이미지 다운로드 + 캐시 (ttl=3600)
@st.cache_data(ttl=3600, show_spinner=False)
def download_image_by_id(file_id):
    if not file_id: return None
    ds = get_google_services()[1]  # 항상 최신 서비스 객체 사용
    if not ds: return None
    try:
        return _do_download_image(ds, file_id)
    except Exception as e:
        err = str(e)
        if "Broken pipe" in err or "Errno 32" in err or "ConnectionReset" in err:
            # 소켓 끊김 → 서비스 재생성 후 1회 재시도
            try:
                get_google_services.clear()  # cache_resource 강제 갱신
                ds2 = get_google_services()[1]
                if ds2:
                    return _do_download_image(ds2, file_id)
            except Exception:
                pass
        return None

@st.cache_data(ttl=3600)
def get_image_from_drive(filename_or_id):
    if not filename_or_id: return None
    stem = os.path.splitext(filename_or_id)[0]
    # 루트 맵 우선, 없으면 하위 폴더까지 포함한 깊은 맵 조회
    fmap = get_drive_file_map()
    if stem in fmap: return download_image_by_id(fmap[stem])
    dmap = get_drive_file_map_deep()
    if stem in dmap: return download_image_by_id(dmap[stem])
    if len(filename_or_id) > 10:
         return download_image_by_id(filename_or_id)
    return None

@st.cache_data(ttl=3600, show_spinner=False)
def download_text_from_drive(file_id):
    """드라이브 파일의 원본 텍스트(캔버스 JSON 등)를 그대로 반환."""
    if not file_id: return None
    ds = get_google_services()[1]
    if not ds: return None
    try:
        raw = ds.files().get_media(fileId=file_id).execute()
        return raw.decode("utf-8") if isinstance(raw, (bytes, bytearray)) else str(raw)
    except Exception:
        try:
            get_google_services.clear()
            ds2 = get_google_services()[1]
            if ds2:
                raw = ds2.files().get_media(fileId=file_id).execute()
                return raw.decode("utf-8") if isinstance(raw, (bytes, bytearray)) else str(raw)
        except Exception:
            pass
        return None

@st.cache_data(ttl=600)
def get_admin_ppt_content():
    if not drive_service: return None
    try:
        q_folder = f"name='{ADMIN_FOLDER_NAME}' and mimeType='application/vnd.google-apps.folder' and trashed=false"
        res_folder = _get_ds().files().list(q=q_folder, fields="files(id)").execute()
        folders = res_folder.get('files', [])
        if not folders: return None
        folder_id = folders[0]['id']
        q_file = f"name='{ADMIN_PPT_NAME}' and '{folder_id}' in parents and trashed=false"
        res_file = _get_ds().files().list(q=q_file, fields="files(id)").execute()
        files = res_file.get('files', [])
        if not files: return None
        file_id = files[0]['id']
        request = _get_ds().files().get_media(fileId=file_id)
        return request.execute()
    except Exception:
        return None

def _product_image_index():
    """[근본보강] 현재 제품 카탈로그의 코드(zfill5) → image(드라이브 ID) 인덱스.
    db가 재로드되면 products 리스트 객체가 새로 생성되므로 id()로 캐시 무효화."""
    db = st.session_state.get("db") or {}
    prods = db.get("products", []) or []
    key = id(prods)
    cache = st.session_state.get("_prod_img_idx_cache")
    if cache and cache[0] == key:
        return cache[1]
    idx = {}
    for p in prods:
        c = str(p.get("code", "")).strip().zfill(5)
        iv = p.get("image", "")
        if c and c != "00000" and iv and len(str(iv)) > 10:
            idx[c] = str(iv)
    st.session_state["_prod_img_idx_cache"] = (key, idx)
    return idx

def get_best_image_id(code, db_image_val, file_map):
    # 이미지 해석 우선순위(견고성 순):
    #  1) 코드명 파일 → 깊은 드라이브 맵 (products/ · sets/ 하위폴더 포함)
    #  2) 코드 → 현재 제품 카탈로그의 image(드라이브 ID)  ← 항목 image_data 손실과 무관
    #  3) 항목에 실린 image_data(드라이브 ID)            ← 최후 보루
    clean_code = str(code).strip().zfill(5)
    if clean_code in file_map: return file_map[clean_code]
    pidx = _product_image_index()
    if clean_code in pidx: return pidx[clean_code]
    if db_image_val and len(str(db_image_val)) > 10: return db_image_val
    return None

def list_files_in_drive_folder():
    return get_drive_file_map()

# --- 구글 시트 함수 ---
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
    "최근수정일": "last_updated"
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
    try:
        sh = gc.open(SHEET_NAME)
        ws_sets = sh.worksheet("Sets")
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
        ws_sets.clear()
        ws_sets.update(rows)
    except Exception as e:
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
    if "builder_pending_items" not in st.session_state:
        st.session_state.builder_pending_items = []   # [{code,name,spec,qty,b64}] — JS 캔버스 추가 대기
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
                            st.session_state.builder_canvas_items.append({
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
            if st.button("🗑 집계 초기화", key="builder_clear_recipe"):
                st.session_state.builder_recipe = {}
                st.session_state.builder_pending_items = []
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
            "code": code, "name": it.get("name", ""),
            "spec": it.get("spec", "-"), "qty": it.get("qty", 1),
            "b64": b64 or ""
        })
    pending_json = json.dumps(_canvas_payload, ensure_ascii=False)

    with col_canvas:
        # ── 모드 선택 ──────────────────────────────────────────────────
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
    <button onclick="duplicateObj()" title="선택 복사">📋 복사</button>
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
const PENDING_ITEMS = {pending_json};  // Python에서 "추가" 버튼 누른 품목 [code/name/spec/qty/b64]
let CW = 720, CH = 540;

let canvas, curMode = 'select';
let pipeStart = null, isPiping = false;
let undoStack = [], redoStack = [];
let objRecipe = {{}};   // objId -> {{code, name, qty}}
let lastObjId = 0;
let bgCleared = false;  // (구버전 호환, 미사용)
let bgImageRef = null;  // [V14] 현재 배경 이미지 객체 참조
let zoomLevel = 1;      // [V15] 화면 표시 배율 (저장 품질과 무관)

// ── [V26] 작업중 배관·텍스트 영속화 (Streamlit 리런 견딤) ────────────────
// 신규/빌드 모드는 리런마다 부속(PENDING_ITEMS)만 재주입되어 그린 배관(_isPipe)·
// 텍스트(_isUserText)가 사라졌다. → 캔버스 변경마다 부모 localStorage에 저장하고
// 초기화 직후 복원한다. 부속은 기존 방식 유지(서로 겹치지 않아 안전).
const WORK_SIG = MODE_NEW ? 'NEW' : ('EDIT:' + (TARGET_SET || ''));
const WORK_KEY = 'LOOPER_WORK';
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
        canvas.getObjects().forEach(function(o, idx) {{
            if (o._isPipe || o._isUserText) {{
                const j = o.toObject(['_isPipe','_isUserText','_objId']);
                j.__z = idx;   // [V26.1] 전체 스택 인덱스 보존(맨앞/맨뒤 순서 복원용)
                items.push(j);
            }}
        }});
        _lstore().setItem(WORK_KEY, JSON.stringify({{sig: WORK_SIG, items: items}}));
    }} catch (e) {{}}
}}
function saveWorkStateDebounced() {{
    if (_workTimer) clearTimeout(_workTimer);
    _workTimer = setTimeout(saveWorkState, 200);
}}
function clearWorkState() {{
    try {{ _lstore().removeItem(WORK_KEY); }} catch (e) {{}}
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
    if (PENDING_ITEMS && PENDING_ITEMS.length > 0) {{
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
        const WHITE = 238;   // 이 값 이상이면 배경 후보 (R,G,B 모두)
        const SOFT  = 225;   // 경계 완화 시작점
        for (let p = 0; p < d.length; p += 4) {{
            const r = d[p], g = d[p+1], b = d[p+2];
            const mn = Math.min(r, g, b), mx = Math.max(r, g, b);
            const sat = mx - mn;            // 채도(낮을수록 무채색=흰/회)
            if (r >= WHITE && g >= WHITE && b >= WHITE && sat <= 18) {{
                d[p+3] = 0;                 // 완전 투명
            }} else if (r >= SOFT && g >= SOFT && b >= SOFT && sat <= 24) {{
                // 경계 픽셀: 밝기에 비례해 부분 투명 (계단현상 완화)
                const t = (Math.min(r, g, b) - SOFT) / (WHITE - SOFT);
                d[p+3] = Math.round(255 * (1 - Math.max(0, Math.min(1, t))));
            }}
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
    let col = 0, row = 0;
    const COLS = 4;
    const STEP_X = 130, STEP_Y = 130;
    const OFFSET_X = 30, OFFSET_Y = 30;

    PENDING_ITEMS.forEach(item => {{
        for (let i = 0; i < item.qty; i++) {{
            const lx = OFFSET_X + (col % COLS) * STEP_X;
            const ly = OFFSET_Y + row * STEP_Y;
            col++;
            if (col % COLS === 0) row++;

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

// ── 팔레트 → 캔버스 추가 (b64 직접 전달용, 하위 호환) ───────────────
function addFromPalette(item) {{
    const qty = item.qty || 1;
    for (let i = 0; i < qty; i++) {{
        if (item.b64) {{
            makeTransparentBg(item.b64, function(cleanUrl) {{
                fabric.Image.fromURL(cleanUrl, function(img) {{
                    img.set({{
                        left: 80 + i * 30, top: 80 + i * 20,
                        scaleX: 0.5, scaleY: 0.5,
                        cornerSize: 8, hasRotatingPoint: true,
                    }});
                    img._looperCode = item.code;
                    img._looperName = item.name;
                    img._looperSpec = item.spec;
                    img._objId = ++lastObjId;
                    objRecipe[img._objId] = {{code: item.code, name: item.name, qty: 1}};
                    canvas.add(img);
                    canvas.setActiveObject(img);
                    canvas.renderAll();
                }});
            }});
        }}
    }}
    updateRecipe();
    setStatus(`"${{item.name}}" ${{qty}}개 추가됨`);
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
}}

// ── 변환 버튼들 ─────────────────────────────────────────────────────
function flipX() {{ const o=canvas.getActiveObject(); if(o){{ o.set('flipX',!o.flipX); canvas.renderAll(); pushUndo(); }} }}
function flipY() {{ const o=canvas.getActiveObject(); if(o){{ o.set('flipY',!o.flipY); canvas.renderAll(); pushUndo(); }} }}
function bringFwd()   {{ const o=canvas.getActiveObject(); if(o){{ canvas.bringForward(o); pushUndo(); saveWorkState(); }} }}
function sendBck()    {{ const o=canvas.getActiveObject(); if(o){{ canvas.sendBackwards(o); pushUndo(); saveWorkState(); }} }}
function bringFront() {{ const o=canvas.getActiveObject(); if(o){{ canvas.bringToFront(o); pushUndo(); saveWorkState(); }} }}
function sendBack()   {{ const o=canvas.getActiveObject(); if(o){{ canvas.sendToBack(o); pushUndo(); saveWorkState(); }} }}
function deleteObj()  {{ const o=canvas.getActiveObject(); if(o){{ if(o._objId) delete objRecipe[o._objId]; canvas.remove(o); pushUndo(); updateRecipe(); }} }}
function duplicateObj() {{
    const o = canvas.getActiveObject();
    if (!o) {{ setStatus('복사할 오브젝트를 먼저 선택하세요.'); return; }}
    o.clone(function(cl) {{
        cl.set({{ left: o.left + 24, top: o.top + 24 }});
        // 부속(이미지)이면 메타·집계 복제
        if (o._looperCode) {{
            cl._looperCode = o._looperCode;
            cl._looperName = o._looperName;
            cl._looperSpec = o._looperSpec;
            cl._objId = ++lastObjId;
            objRecipe[cl._objId] = {{code:o._looperCode, name:o._looperName, qty:1}};
        }}
        if (o._isPipe) cl._isPipe = true;
        canvas.add(cl);
        canvas.setActiveObject(cl);
        canvas.renderAll();
        pushUndo(); updateRecipe();
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
    const state = JSON.stringify(canvas.toJSON(['_looperCode','_looperName','_looperSpec','_objId','_isPipe','_isBgImage','_isUserText']));
    if (undoStack[undoStack.length-1] === state) return;
    undoStack.push(state);
    if (undoStack.length > 50) undoStack.shift();
    redoStack = [];
}}
function doUndo() {{
    if (undoStack.length <= 1) return;
    redoStack.push(undoStack.pop());
    const state = undoStack[undoStack.length-1];
    canvas.loadFromJSON(state, () => {{ canvas.renderAll(); updateRecipe(); }});
}}
function doRedo() {{
    if (!redoStack.length) return;
    const state = redoStack.pop();
    undoStack.push(state);
    canvas.loadFromJSON(state, () => {{ canvas.renderAll(); updateRecipe(); }});
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
    const data = JSON.stringify(canvas.toJSON(['_looperCode','_looperName','_looperSpec','_objId','_isPipe','_isUserText']));
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
        const cjson = JSON.stringify(canvas.toJSON(['_looperCode','_looperName','_looperSpec','_objId','_isPipe','_isUserText']));
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

// 하위호환: 기존 호출부가 fitCanvasToArea를 부를 수 있으므로 별칭 유지
function fitCanvasToArea() {{ zoomFit(); }}
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
            st.success("✅ 빌더에서 전송된 이미지가 준비됐습니다. 아래에서 세트명·분류만 확인하고 저장하세요.")
        else:
            st.caption("위 빌더에서 **💾 저장** 버튼을 누르면 이미지·구성이 자동 전송됩니다. (전송이 안 되면 아래 백업 업로드 사용)")
            if _HAS_JS_EVAL:
                st.button("🔄 전송 확인 / 새로고침", key="bridge_refresh",
                          help="빌더에서 '💾 저장'을 눌렀는데 위에 인식이 안 되면 클릭하세요.")

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
                    st.error("저장할 이미지가 없습니다. 빌더에서 '💾 저장'을 누르거나 백업 업로드를 사용하세요.")
                elif not new_sname:
                    st.error("세트명을 입력/선택하세요.")
                else:
                    with st.spinner("저장 중..."):
                        fname = f"{new_sname}.png"
                        # 기존 동일 파일명 삭제(중복 방지)
                        try:
                            fmap = get_drive_file_map_deep()
                            old_id = fmap.get(new_sname)
                            if old_id:
                                _get_ds().files().delete(fileId=old_id, supportsAllDrives=True).execute()
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

                        # [작업 손실 방지] 이미지 업로드가 실패(서비스계정 용량 0 등)해도
                        #  구성·분류·설명은 시트에 저장한다. 이미지 참조는 파일명으로 기록 →
                        #  나중에 같은 이름 PNG를 폴더에 올리면 코드/이름으로 자동 연결된다.
                        upload_failed = not new_id
                        image_ref = new_id or fname
                        if upload_failed:
                            st.warning(
                                f"⚠️ 이미지 자동 업로드가 막혔습니다(서비스계정은 드라이브에 파일 생성 불가). "
                                f"**구성·분류·설명은 저장**했습니다. 이미지는 아래처럼 처리하세요:\n\n"
                                f"1. 빌더에서 **📥 PNG만 내려받기** → 파일명을 **`{fname}`** 로 변경\n"
                                f"2. 구글 드라이브의 세트 이미지 폴더(`sets/`)에 그 PNG를 직접 업로드\n"
                                f"→ 견적서에서 코드/이름으로 자동 연결됩니다. (근본 해결: 공유 드라이브 또는 OAuth — 안내 참고)")

                        get_drive_file_map.clear()
                        get_drive_file_map_deep.clear()
                        try: download_text_from_drive.clear()
                        except Exception: pass

                        sc_val = new_ssc if new_ssc != "-" else None
                        if builder_mode == "✨ 새 세트 만들기":
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
                                        js_expressions="window.parent.localStorage.removeItem('LOOPER_SET_PNG');window.parent.localStorage.removeItem('LOOPER_SET_JSON');window.parent.localStorage.removeItem('LOOPER_SET_TS');window.parent.localStorage.removeItem('LOOPER_SET_READY');window.parent.localStorage.removeItem('LOOPER_WORK');",
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
# 2. PDF 및 Excel 생성 엔진
# ==========================================
class PDF(FPDF):
    def header(self):
        header_font = 'Helvetica'; header_style = 'B'
        if os.path.exists(FONT_REGULAR):
            self.add_font('NanumGothic', '', FONT_REGULAR, uni=True)
            header_font = 'NanumGothic'
            if os.path.exists(FONT_BOLD): self.add_font('NanumGothic', 'B', FONT_BOLD, uni=True); header_style = 'B'
            else: header_style = ''
        # 제목 중앙 + 우측에 회사명
        self.set_font(header_font, header_style, 20)
        title_txt = self.title_text if hasattr(self, 'title_text') else '견 적 서'
        self.cell(130, 16, title_txt, align='C', border=0)
        self.set_font(header_font, header_style, 11)
        self.cell(60, 16, 'ShinJinChemTech', align='C', border=0, new_x="LMARGIN", new_y="NEXT")
        # 구분선
        self.set_draw_color(180, 180, 180)
        self.line(self.l_margin, self.get_y(), self.l_margin + 190, self.get_y())
        self.ln(2)
        self.set_draw_color(0, 0, 0)

    def footer(self):
        self.set_y(-25) 
        footer_font = 'Helvetica'; footer_style = 'B'
        if os.path.exists(FONT_REGULAR):
            footer_font = 'NanumGothic'
            if os.path.exists(FONT_BOLD): footer_style = 'B'
            else: footer_style = ''
        self.set_font(footer_font, footer_style, 12)
        self.cell(0, 5, "주식회사 신진켐텍", align='C', ln=True)
        self.set_font(footer_font, '', 9)
        self.cell(0, 5, "www.sjct.kr", align='C', ln=True)
        self.cell(0, 5, f'Page {self.page_no()}', align='C')

def create_advanced_pdf(final_data_list, service_items, quote_name, quote_date, form_type, price_labels, buyer_info, remarks):
    """
    견적서 PDF 생성 — 첨부 이미지 양식과 동일한 레이아웃
    """
    drive_file_map = get_drive_file_map_deep()
    pdf = PDF()
    pdf.title_text = '견 적 서'
    pdf.set_auto_page_break(False)
    pdf.add_page()

    has_font = os.path.exists(FONT_REGULAR)
    has_bold = os.path.exists(FONT_BOLD)
    font_name = 'NanumGothic' if has_font else 'Helvetica'
    b_style = 'B' if has_bold else ''

    L = pdf.l_margin
    PAGE_W = 190

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # [1] 2단 정보 테이블
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    LEFT_W  = 95
    RIGHT_W = 95
    LBL_W   = 24
    VAL_W   = LEFT_W - LBL_W
    H_ROW   = 7.0  # 행 높이 증가

    serial    = buyer_info.get('serial', '')
    recipient = buyer_info.get('recipient', '')
    ref       = buyer_info.get('ref', '')
    tel_buyer = buyer_info.get('phone', '')
    pay_cond  = buyer_info.get('pay_cond', '/')
    valid_period = buyer_info.get('valid_period', '견적 후 15일 이내')

    left_rows = [
        ("일련번호", serial if serial else quote_date.replace('-', '/') if quote_date else '/'),
        ("수  신", recipient or '/'),
        ("참  조", ref or '/'),
        ("TEL / FAX", tel_buyer or '/'),
        ("결재조건", pay_cond),
        ("유효기간", valid_period),
    ]

    RVAL_W = RIGHT_W - LBL_W
    right_rows = [
        ("사업자등록번호", "411-81-91898"),
        ("회사명/대표", "주식회사 신진켐텍 / 박형석"),
        ("주  소", "경기도 이천시 부발읍 황무로 1859-157"),
        ("업태/종목", "제조,도소매/산업용 밸브, 파이프 및 부속품 제조업"),
        ("담당자", buyer_info.get('manager', '문창근 부장')),
        ("TEL/FAX", "031-638-1809 / 031-635-1801"),
    ]

    y_info = pdf.get_y()

    for i, ((lbl, val), (rlbl, rval)) in enumerate(zip(left_rows, right_rows)):
        cy = y_info + i * H_ROW

        pdf.set_xy(L, cy)
        pdf.set_fill_color(240, 240, 240)
        pdf.set_font(font_name, b_style, 9)   # ↑ 8→9
        pdf.cell(LBL_W, H_ROW, f" {lbl}", border=1, fill=True)
        pdf.set_font(font_name, '', 9)         # ↑ 8→9
        pdf.cell(VAL_W, H_ROW, f" {val}", border=1)

        pdf.set_xy(L + LEFT_W, cy)
        pdf.set_fill_color(240, 240, 240)
        pdf.set_font(font_name, b_style, 8)   # ↑ 7→8
        pdf.cell(LBL_W, H_ROW, f" {rlbl}", border=1, fill=True)
        pdf.set_font(font_name, '', 8)         # ↑ 7→8
        pdf.cell(RVAL_W, H_ROW, f" {rval}", border=1)

    pdf.set_y(y_info + len(left_rows) * H_ROW)

    greeting = (
        "1.귀사의 일의 번창을 기원합니다.\n"
        "2.하기와 같이 견적드리오니 검토하기 바랍니다."
    )
    pdf.set_xy(L, pdf.get_y())
    pdf.set_font(font_name, '', 8.5)   # ↑ 7.5→8.5
    pdf.set_fill_color(255, 255, 255)
    pdf.multi_cell(LEFT_W, 5, greeting, border=1)

    pdf.ln(3)

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # [2] 품목 테이블
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    if form_type == "basic":
        COL_IMG  = 25
        COL_INFO = 63
        COL_UNIT = 13
        COL_QTY  = 13
        COL_P1   = 29
        COL_AMT  = 32
        COL_RMK  = 15
    else:
        COL_IMG  = 25
        COL_INFO = 55
        COL_UNIT = 10
        COL_QTY  = 10
        COL_P1   = 18
        COL_AMT1 = 22
        COL_P2   = 18
        COL_AMT2 = 22
        COL_PROF = 10

    def draw_table_header():
        pdf.set_fill_color(240, 240, 240)
        pdf.set_font(font_name, b_style, 9.5)   # ↑ 8.5→9.5
        H_HDR = 10
        pdf.cell(COL_IMG,  H_HDR, "이미지",    border=1, align='C', fill=True)
        pdf.cell(COL_INFO, H_HDR, "품목정보",   border=1, align='C', fill=True)
        pdf.cell(COL_UNIT, H_HDR, "단위",      border=1, align='C', fill=True)
        pdf.cell(COL_QTY,  H_HDR, "수량",      border=1, align='C', fill=True)
        if form_type == "basic":
            pdf.cell(COL_P1,  H_HDR, price_labels[0] if price_labels else "소비자가", border=1, align='C', fill=True)
            pdf.cell(COL_AMT, H_HDR, "금액",   border=1, align='C', fill=True)
            pdf.cell(COL_RMK, H_HDR, "비고",   border=1, align='C', fill=True, new_x="LMARGIN", new_y="NEXT")
        else:
            l1 = price_labels[0] if price_labels else "단가1"
            l2 = price_labels[1] if len(price_labels) > 1 else "단가2"
            pdf.set_font(font_name, b_style, 8)
            pdf.cell(COL_P1,   H_HDR, l1,     border=1, align='C', fill=True)
            pdf.cell(COL_AMT1, H_HDR, "금액",  border=1, align='C', fill=True)
            pdf.cell(COL_P2,   H_HDR, l2,     border=1, align='C', fill=True)
            pdf.cell(COL_AMT2, H_HDR, "금액",  border=1, align='C', fill=True)
            pdf.cell(COL_PROF, H_HDR, "이익율", border=1, align='C', fill=True, new_x="LMARGIN", new_y="NEXT")

    draw_table_header()

    sum_qty = 0; sum_a1 = 0; sum_a2 = 0; sum_profit = 0
    ITEM_H = 18  # ↑ 17→18

    for item in final_data_list:
        if pdf.get_y() + ITEM_H > 265:
            pdf.add_page()
            draw_table_header()

        x, y = pdf.get_x(), pdf.get_y()
        name = str(item.get("품목", "") or "")
        spec = str(item.get("규격", "-") or "-")
        code = str(item.get("코드", "") or "").strip().zfill(5)

        try: qty = int(float(item.get("수량", 0)))
        except: qty = 0

        img_id = get_best_image_id(code, item.get("image_data"), drive_file_map)
        img_b64 = download_image_by_id(img_id)

        sum_qty += qty
        try: p1 = int(float(item.get("price_1", 0)))
        except: p1 = 0
        a1 = p1 * qty
        sum_a1 += a1

        p2 = 0; a2 = 0; profit = 0; rate = 0
        if form_type == "profit":
            try: p2 = int(float(item.get("price_2", 0)))
            except: p2 = 0
            a2 = p2 * qty
            sum_a2 += a2
            profit = a2 - a1
            sum_profit += profit
            rate = (profit / a2 * 100) if a2 else 0

        # 이미지 셀
        pdf.cell(COL_IMG, ITEM_H, "", border=1)
        if img_b64:
            try:
                img_data_str = img_b64.split(",", 1)[1] if "," in img_b64 else img_b64
                img_bytes = base64.b64decode(img_data_str)
                with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as tmp:
                    tmp.write(img_bytes)
                    tmp_path = tmp.name
                img_sz = min(COL_IMG - 4, ITEM_H - 4, 14)
                pdf.image(tmp_path, x=x + (COL_IMG - img_sz) / 2,
                          y=y + (ITEM_H - img_sz) / 2, w=img_sz, h=img_sz)
                if os.path.exists(tmp_path): os.unlink(tmp_path)
            except: pass

        # 품목정보 셀
        pdf.set_xy(x + COL_IMG, y)
        pdf.cell(COL_INFO, ITEM_H, "", border=1)
        # 품목명 — 굵게 9pt
        pdf.set_xy(x + COL_IMG + 1.5, y + 1.5)
        pdf.set_font(font_name, b_style, 9)    # ↑ 7.5→9
        pdf.multi_cell(COL_INFO - 3, 4.2, name, align='L', max_line_height=4.2)
        # 규격
        pdf.set_xy(x + COL_IMG + 1.5, y + ITEM_H - 6.5)
        pdf.set_font(font_name, '', 7.5)        # ↑ 6.5→7.5
        pdf.cell(COL_INFO - 3, 3.2, spec, align='L')
        # 코드
        pdf.set_xy(x + COL_IMG + 1.5, y + ITEM_H - 3.5)
        pdf.set_font(font_name, '', 7.5)        # ↑ 6.5→7.5
        pdf.cell(COL_INFO - 3, 3.2, code, align='L')

        # 단위 / 수량
        pdf.set_xy(x + COL_IMG + COL_INFO, y)
        pdf.set_font(font_name, '', 9.5)        # ↑ 8→9.5
        pdf.cell(COL_UNIT, ITEM_H, str(item.get("단위", "EA") or "EA"), border=1, align='C')
        pdf.cell(COL_QTY,  ITEM_H, str(qty), border=1, align='C')

        # 단가 / 금액
        if form_type == "basic":
            pdf.set_font(font_name, '', 9)      # ↑ 명시 설정
            pdf.cell(COL_P1,  ITEM_H, f"{p1:,}", border=1, align='R')
            pdf.cell(COL_AMT, ITEM_H, f"{a1:,}", border=1, align='R')
            pdf.cell(COL_RMK, ITEM_H, "", border=1)
            pdf.ln()
        else:
            pdf.set_font(font_name, '', 8.5)
            pdf.cell(COL_P1,   ITEM_H, f"{p1:,}", border=1, align='R')
            pdf.cell(COL_AMT1, ITEM_H, f"{a1:,}", border=1, align='R')
            pdf.cell(COL_P2,   ITEM_H, f"{p2:,}", border=1, align='R')
            pdf.cell(COL_AMT2, ITEM_H, f"{a2:,}", border=1, align='R')
            pdf.set_font(font_name, b_style, 8)
            pdf.cell(COL_PROF, ITEM_H, f"{rate:.1f}%", border=1, align='C')
            pdf.ln()

    # 서비스 비용
    svc_total = 0
    if service_items:
        if pdf.get_y() + (len(service_items) * 7) + 10 > 265:
            pdf.add_page()
            pdf.ln(1)
        else:
            pdf.ln(1)
        pdf.set_fill_color(255, 255, 224)
        pdf.set_font(font_name, b_style, 9)
        pdf.cell(PAGE_W, 7, " [ 추가 비용 ]", border=1, fill=True, new_x="LMARGIN", new_y="NEXT")
        for s in service_items:
            svc_total += s['금액']
            pdf.set_font(font_name, '', 9)
            pdf.cell(PAGE_W - 35, 7, f"  {s['항목']}", border=1)
            pdf.cell(35, 7, f"{s['금액']:,} 원", border=1, align='R', new_x="LMARGIN", new_y="NEXT")

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # [3] 자재비 합계 행
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    if pdf.get_y() + 12 > 265:
        pdf.add_page()

    final_total = (sum_a1 if form_type == "basic" else sum_a2) + svc_total
    TOTAL_H = 11

    pdf.set_fill_color(230, 230, 230)
    pdf.set_font(font_name, b_style, 10)   # ↑ 9→10

    if form_type == "basic":
        label_w = COL_IMG + COL_INFO + COL_UNIT + COL_QTY + COL_P1
        pdf.cell(label_w, TOTAL_H, "자재비 합계", border=1, align='C', fill=True)
        pdf.cell(COL_AMT, TOTAL_H, f"{final_total:,}", border=1, align='R', fill=True)
        pdf.cell(COL_RMK, TOTAL_H, "", border=1, fill=True)
        pdf.ln()
    else:
        label_w = COL_IMG + COL_INFO + COL_UNIT + COL_QTY + COL_P1 + COL_AMT1 + COL_P2
        pdf.cell(label_w, TOTAL_H, "자재비 합계", border=1, align='C', fill=True)
        pdf.cell(COL_AMT2, TOTAL_H, f"{final_total:,}", border=1, align='R', fill=True)
        pdf.cell(COL_PROF, TOTAL_H, "", border=1, fill=True)
        pdf.ln()

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # [4] 특약사항 및 비고
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    if remarks:
        pdf.ln(2)
        if pdf.get_y() + 20 > 270:
            pdf.add_page()
        pdf.set_fill_color(240, 240, 240)
        pdf.set_font(font_name, b_style, 9.5)  # ↑ 8.5→9.5
        pdf.cell(PAGE_W, 8, "  특약사항 및 비고", border=1, fill=True, new_x="LMARGIN", new_y="NEXT")
        pdf.set_font(font_name, '', 9)          # ↑ 8→9
        pdf.set_fill_color(255, 255, 255)
        pdf.multi_cell(PAGE_W, 6, remarks, border=1)

    return bytes(pdf.output())

def create_quote_excel(final_data_list, service_items, quote_name, quote_date, form_type, price_labels, buyer_info, remarks):
    """
    견적서 Excel 생성
    ─ 사용자 지정 폰트 크기 기준 ─
    정보 레이블/값(업태 제외): 11pt  |  업태/종목 값: 10pt
    인사말: 11pt  |  헤더행(9행): 12pt
    품목정보: 12pt  |  단위/수량/단가/금액: 14pt
    자재비합계: 16pt  |  특약사항 헤더+내용: 14pt
    """
    output = io.BytesIO()
    workbook = xlsxwriter.Workbook(output, {'in_memory': True})
    ws = workbook.add_worksheet("견적서")
    drive_file_map = get_drive_file_map_deep()

    FN = '맑은 고딕'  # 기본 폰트

    def fmt(**kw):
        base = {'font_name': FN, 'valign': 'vcenter', 'border': 1}
        base.update(kw)
        return workbook.add_format(base)

    # ── 폰트 크기별 포맷 ──
    # 제목
    f_title    = fmt(bold=True, font_size=20, align='center', border=0)

    # 정보 영역 (레이블 굵게, 값 일반) — 11pt 기본
    f_lbl      = fmt(bold=True, bg_color='#F0F0F0', align='center', font_size=11, text_wrap=False)
    f_val_11   = fmt(align='left', font_size=11, text_wrap=False)          # 일반 정보값 11pt
    f_val_10   = fmt(align='left', font_size=10, text_wrap=False)          # 업태/종목 값 10pt (긴 텍스트)

    # 인사말 — 11pt
    f_greet    = fmt(align='left', font_size=11, text_wrap=True, border=1)

    # 테이블 헤더 (9행) — 12pt 굵게
    f_hdr      = fmt(bold=True, bg_color='#F0F0F0', align='center', font_size=12, text_wrap=True)

    # 품목정보 — 12pt (품목명 굵게, 규격·코드 보통)
    f_item_name = fmt(bold=True, align='left', font_size=12, text_wrap=True)

    # 단위 / 수량 / 단가 / 금액 — 14pt
    f_center_14 = fmt(align='center', font_size=14)
    f_num_14    = fmt(align='right',  font_size=14, num_format='#,##0')

    # 이미지 셀
    f_img_cell  = fmt(align='center', font_size=11)

    # 자재비 합계 — 16pt 굵게
    f_total_lbl = fmt(bold=True, bg_color='#E6E6E6', align='center', font_size=16)
    f_total_val = fmt(bold=True, bg_color='#E6E6E6', align='right',  font_size=16, num_format='#,##0')
    f_total_emp = fmt(bold=True, bg_color='#E6E6E6', align='center', font_size=16)

    # 추가비용
    f_svc_hdr  = fmt(bold=True, bg_color='#FFF9C4', align='center', font_size=13)
    f_svc_val  = fmt(align='left', font_size=12)
    f_svc_num  = fmt(align='right', font_size=12, num_format='#,##0')

    # 특약사항 — 14pt
    f_rmk_hdr  = fmt(bold=True, bg_color='#F0F0F0', align='center', font_size=14)
    f_rmk_val  = fmt(align='left', font_size=14, text_wrap=True)

    # ── 컬럼 구성 ──
    # basic : A(이미지) B(품목정보) C(단위) D(수량) E(단가) F(금액) G(비고)  → 7컬럼
    # profit: A B C D E F(금액1) G(단가2) H(금액2) I(이익율)               → 9컬럼
    #
    # 정보 테이블 열 역할 (basic 기준):
    #   col0(A)=좌레이블 | col1(B)=좌값(단독)
    #   col2~3(C~D)=우레이블 병합 | col4~6(E~G)=우값 병합
    if form_type == "basic":
        NUM_COLS = 7
        # A=14, B=25, C=6, D=8, E=10, F=13, G=10
        col_widths = [14, 25, 6, 8, 10, 13, 10]
        COL_IMG, COL_INFO, COL_UNIT, COL_QTY, COL_P1, COL_AMT, COL_RMK = range(7)
        LAST_COL = 6
    else:
        NUM_COLS = 9
        # A=14, B=25, C=6, D=8, E=10, F=13, G=10, H=13, I=10
        col_widths = [14, 25, 6, 8, 10, 13, 10, 13, 10]
        COL_IMG, COL_INFO, COL_UNIT, COL_QTY, COL_P1, COL_AMT1, COL_P2, COL_AMT2, COL_PROF = range(9)
        LAST_COL = 8

    for ci, cw in enumerate(col_widths):
        ws.set_column(ci, ci, cw)

    # 합계 금액 — shrink_to_fit 버전 포맷 (####방지)
    f_total_val_shrink = fmt(bold=True, bg_color='#E6E6E6', align='right',
                             font_size=16, num_format='#,##0', shrink=True)

    # 수량 / 소비자가 / 금액 — 14pt + shrink_to_fit (셀 폭 부족 시 자동 축소)
    f_center_14_shrink = fmt(align='center', font_size=14, shrink=True)
    f_num_14_shrink    = fmt(align='right',  font_size=14, num_format='#,##0', shrink=True)

    # A열(이미지 열) 폭을 픽셀로 환산: 14 chars * 7.5px/char ≈ 105px
    # 이미지가 이 셀 폭을 절대 넘지 않도록 cell_w_px를 A열 실제 폭에 맞춤
    IMG_COL_PX = 100  # A열 14 chars 기준 안전 픽셀 폭

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # ROW 0 : 제목
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    ws.merge_range(0, 0, 0, LAST_COL, '견 적 서', f_title)
    ws.set_row(0, 36)

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # ROW 1~6 : 정보 2단 테이블
    #   좌: col0(A)=레이블 단독 | col1(B)=값 단독
    #   우: col2~3(C~D)=레이블 병합, 가운데 | col4~LAST(E~)=값 병합, 왼쪽
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    serial    = buyer_info.get('serial', quote_date or '')
    recipient = buyer_info.get('recipient', '')
    ref       = buyer_info.get('ref', '')
    tel_buyer = buyer_info.get('phone', '/')
    pay_cond  = buyer_info.get('pay_cond', '/')
    valid_per = buyer_info.get('valid_period', '견적 후 15일 이내')
    manager   = buyer_info.get('manager', '')

    left_rows  = [
        ("일련번호",  serial or '/'),
        ("수  신",    recipient or '/'),
        ("참  조",    ref or '/'),
        ("TEL / FAX", tel_buyer or '/'),
        ("결재조건",  pay_cond),
        ("유효기간",  valid_per),
    ]
    right_rows = [
        ("사업자등록번호", "411-81-91898"),
        ("회사명/대표",   "주식회사 신진켐텍 / 박형석"),
        ("주  소",        "경기도 이천시 부발읍 황무로 1859-157"),
        ("업태/종목",     "제조,도소매/산업용 밸브, 파이프 및 부속품 제조업"),
        ("담당자",        manager),
        ("TEL/FAX",       "031-638-1809 / 031-635-1801"),
    ]

    # 컬럼 인덱스
    L_LBL   = 0          # 좌 레이블: A (단독)
    L_VAL   = 1          # 좌 값:     B (단독)
    R_LBL_S = 2          # 우 레이블 시작: C
    R_LBL_E = 3          # 우 레이블 끝:   D  → C~D 병합
    R_VAL_S = 4          # 우 값 시작: E
    R_VAL_E = LAST_COL   # 우 값 끝:   G(basic) or I(profit) → E~끝 병합

    for i, ((ll, lv), (rl, rv)) in enumerate(zip(left_rows, right_rows)):
        r = i + 1
        ws.set_row(r, 22)

        # 좌측 레이블(단독) / 값(단독)
        ws.write(r, L_LBL, ll, f_lbl)
        ws.write(r, L_VAL, lv, f_val_11)

        # 우측 레이블: C~D 병합, 가운데 정렬
        ws.merge_range(r, R_LBL_S, r, R_LBL_E, rl, f_lbl)

        # 우측 값: E~LAST 병합, 왼쪽 정렬
        # 업태/종목(i==3)은 10pt, 나머지 11pt
        rv_fmt = f_val_10 if i == 3 else f_val_11
        if R_VAL_S < R_VAL_E:
            ws.merge_range(r, R_VAL_S, r, R_VAL_E, rv, rv_fmt)
        else:
            ws.write(r, R_VAL_S, rv, rv_fmt)

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # ROW 7 : 인사말 — 11pt, 행 높이 36.4
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    greeting = "1.귀사의 일의 번창을 기원합니다.\n2.하기와 같이 견적드리오니 검토하기 바랍니다."
    ws.merge_range(7, 0, 7, LAST_COL, greeting, f_greet)
    ws.set_row(7, 36.4)

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # ROW 8 : 테이블 헤더 — 12pt
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    ws.set_row(8, 24)
    ws.write(8, COL_IMG,  "이미지", f_hdr)
    ws.write(8, COL_INFO, "품목정보", f_hdr)
    ws.write(8, COL_UNIT, "단위", f_hdr)
    ws.write(8, COL_QTY,  "수량", f_hdr)
    if form_type == "basic":
        ws.write(8, COL_P1,  price_labels[0] if price_labels else "소비자가", f_hdr)
        ws.write(8, COL_AMT, "금액", f_hdr)
        ws.write(8, COL_RMK, "비고", f_hdr)
    else:
        l1 = price_labels[0] if price_labels else "단가1"
        l2 = price_labels[1] if len(price_labels) > 1 else "단가2"
        ws.write(8, COL_P1,   l1,      f_hdr)
        ws.write(8, COL_AMT1, "금액",   f_hdr)
        ws.write(8, COL_P2,   l2,      f_hdr)
        ws.write(8, COL_AMT2, "금액",   f_hdr)
        ws.write(8, COL_PROF, "이익율", f_hdr)

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # ROW 9~ : 품목 데이터
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    ROW_H_ITEM = 72   # 품목 행 높이(이미지 충분히)
    data_row = 9
    total_a1 = 0; total_a2 = 0; svc_total = 0
    temp_files = []

    for item in final_data_list:
        ws.set_row(data_row, ROW_H_ITEM)

        try: qty = int(float(item.get("수량", 0)))
        except: qty = 0
        try: p1  = int(float(item.get("price_1", 0)))
        except: p1 = 0
        a1 = p1 * qty
        total_a1 += a1

        code = str(item.get("코드", "") or "").strip().zfill(5)
        img_id  = get_best_image_id(code, item.get("image_data"), drive_file_map)
        img_b64 = download_image_by_id(img_id)

        # 이미지 — 셀 안에서만 (가로·세로 침범 없음), 셀 내 최대 크기·중앙 배치
        ws.write(data_row, COL_IMG, "", f_img_cell)
        if img_b64:
            try:
                img_data_str = img_b64.split(",", 1)[1] if "," in img_b64 else img_b64
                img_bytes    = base64.b64decode(img_data_str)
                with Image.open(io.BytesIO(img_bytes)) as pil_img:
                    orig_w, orig_h = pil_img.size
                with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as tmp:
                    tmp.write(img_bytes); tmp_path = tmp.name
                    temp_files.append(tmp_path)

                # 엑셀 행 높이(pt) → 픽셀: 1pt = 4/3 px (96dpi 기준)
                # ROW_H_ITEM=72pt → 96px
                MARGIN = 4  # 상하좌우 여백(px)
                cell_w_px = int(14 * 7.5) - MARGIN * 2   # A열 14chars → ≈105px → 여백 제외 97px
                cell_h_px = int(ROW_H_ITEM * 4 / 3) - MARGIN * 2  # 72pt → 96px → 여백 제외 88px

                scale = min(cell_w_px / orig_w, cell_h_px / orig_h)
                fw = orig_w * scale
                fh = orig_h * scale

                # 중앙 정렬 offset (여백 + 남은 공간의 절반)
                x_off = MARGIN + int((cell_w_px - fw) / 2)
                y_off = MARGIN + int((cell_h_px - fh) / 2)

                ws.insert_image(data_row, COL_IMG, tmp_path, {
                    'x_scale':  scale,
                    'y_scale':  scale,
                    'x_offset': x_off,
                    'y_offset': y_off,
                    'object_position': 2,
                    'url': None
                })
            except:
                ws.write(data_row, COL_IMG, "No Img", f_img_cell)

        # 품목정보 (품목명\n규격\n코드) — 12pt 굵게
        item_text = f"{item.get('품목', '')}\n{item.get('규격', '')}\n{code}"
        ws.write(data_row, COL_INFO, item_text, f_item_name)

        # 단위 — 14pt
        ws.write(data_row, COL_UNIT, item.get("단위", "EA") or "EA", f_center_14)

        # 수량 / 단가 / 금액 — 14pt + shrink_to_fit
        if form_type == "basic":
            ws.write(data_row, COL_QTY,  qty, f_center_14_shrink)
            ws.write(data_row, COL_P1,   p1,  f_num_14_shrink)
            ws.write(data_row, COL_AMT,  a1,  f_num_14_shrink)
            ws.write(data_row, COL_RMK,  "",  f_img_cell)
        else:
            try: p2 = int(float(item.get("price_2", 0)))
            except: p2 = 0
            a2 = p2 * qty
            profit = a2 - a1
            rate = (profit / a2 * 100) if a2 else 0
            total_a2 += a2
            ws.write(data_row, COL_QTY,  qty,            f_center_14_shrink)
            ws.write(data_row, COL_P1,   p1,             f_num_14_shrink)
            ws.write(data_row, COL_AMT1, a1,             f_num_14_shrink)
            ws.write(data_row, COL_P2,   p2,             f_num_14_shrink)
            ws.write(data_row, COL_AMT2, a2,             f_num_14_shrink)
            ws.write(data_row, COL_PROF, f"{rate:.1f}%", f_center_14)

        data_row += 1

    # ── 추가 비용 ──
    if service_items:
        ws.set_row(data_row, 20)
        ws.merge_range(data_row, 0, data_row, LAST_COL, "[ 추가 비용 ]", f_svc_hdr)
        data_row += 1
        for s in service_items:
            ws.set_row(data_row, 20)
            amt_col = COL_AMT if form_type == "basic" else COL_AMT2
            if amt_col > 0:
                ws.merge_range(data_row, 0, data_row, amt_col - 1, s['항목'], f_svc_val)
            else:
                ws.write(data_row, 0, s['항목'], f_svc_val)
            ws.write(data_row, amt_col, s['금액'], f_svc_num)
            for c in range(amt_col + 1, NUM_COLS):
                ws.write(data_row, c, "", f_img_cell)
            svc_total += s['금액']
            data_row += 1

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # 자재비 합계 — 16pt, 행 높이 30
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    final_total = (total_a1 if form_type == "basic" else total_a2) + svc_total
    ws.set_row(data_row, 30)
    if form_type == "basic":
        ws.merge_range(data_row, 0, data_row, COL_P1, "자재비 합계", f_total_lbl)
        ws.write(data_row, COL_AMT, final_total, f_total_val_shrink)
        ws.write(data_row, COL_RMK, "",          f_total_emp)
    else:
        ws.merge_range(data_row, 0, data_row, COL_P2, "자재비 합계", f_total_lbl)
        ws.write(data_row, COL_AMT2, final_total, f_total_val_shrink)
        ws.write(data_row, COL_PROF, "",           f_total_emp)
    data_row += 1

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # 빈 행 (합계 ~ 특약사항 사이)
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    ws.set_row(data_row, 10)
    for c in range(NUM_COLS):
        ws.write(data_row, c, "", fmt(border=0))
    data_row += 1

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # 특약사항 및 비고 — 14pt, 가운데 정렬 헤더
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    if remarks:
        ws.set_row(data_row, 24)
        ws.merge_range(data_row, 0, data_row, LAST_COL, "특약사항 및 비고", f_rmk_hdr)
        data_row += 1
        line_count = max(remarks.count('\n') + 1, 2)
        ws.set_row(data_row, max(20 * line_count, 40))
        ws.merge_range(data_row, 0, data_row, LAST_COL, remarks, f_rmk_val)

    workbook.close()
    for f in temp_files:
        try:
            if os.path.exists(f): os.unlink(f)
        except: pass
    return output.getvalue()

def create_composition_pdf(set_cart, pipe_cart, final_data_list, db_products, db_sets, quote_name):
    drive_file_map = get_drive_file_map_deep()
    pdf = PDF()
    pdf.title_text = "자재 구성 명세서 (Composition Report)"
    pdf.set_auto_page_break(False)
    pdf.add_page()
    
    has_font = os.path.exists(FONT_REGULAR)
    has_bold = os.path.exists(FONT_BOLD)
    font_name = 'NanumGothic' if has_font else 'Helvetica'
    b_style = 'B' if has_bold else ''
    
    baseline_counts = {}
    all_sets_db = {}
    for cat, val in db_sets.items(): all_sets_db.update(val)
    
    for item in set_cart:
        recipe = all_sets_db.get(item['name'], {}).get("recipe", {})
        for p_code, p_qty in recipe.items():
            baseline_counts[str(p_code)] = baseline_counts.get(str(p_code), 0) + (p_qty * item['qty'])
            
    code_sums = {}
    for p_item in pipe_cart:
        c = p_item.get('code')
        if c: code_sums[c] = code_sums.get(c, 0) + p_item['len']
    for p_code, total_len in code_sums.items():
        prod_info = next((item for item in db_products if str(item["code"]) == str(p_code)), None)
        if prod_info:
            unit_len = prod_info.get("len_per_unit", 4)
            if unit_len <= 0: unit_len = 4
            qty = math.ceil(total_len / unit_len)
            baseline_counts[str(p_code)] = baseline_counts.get(str(p_code), 0) + qty

    additional_items_list = []
    temp_baseline = baseline_counts.copy()

    for item in final_data_list:
        code = str(item.get("코드", "")).strip().zfill(5) if item.get("코드") else ""
        try: total_qty = int(float(item.get("수량", 0)))
        except: total_qty = 0
        name = item.get("품목", "")
        spec = item.get("규격", "")
        img_data = item.get("image_data", "")

        if code and code in temp_baseline:
            base_qty = temp_baseline[code]
            if total_qty > base_qty:
                diff = total_qty - base_qty
                additional_items_list.append({
                    "name": name, "spec": spec, "qty": diff, 
                    "code": code, "image": img_data
                })
                temp_baseline[code] = total_qty
            else:
                temp_baseline[code] -= total_qty
        else:
            if total_qty > 0:
                additional_items_list.append({
                    "name": name, "spec": spec, "qty": total_qty, 
                    "code": code, "image": img_data
                })

    pdf.set_font(font_name, '', 10)
    pdf.cell(0, 8, f"현장명: {quote_name}", align='R', new_x="LMARGIN", new_y="NEXT")
    pdf.ln(5)

    def check_page_break(h_needed):
        if pdf.get_y() + h_needed > 270:
            pdf.add_page()

    # 1. 부속 세트 구성
    pdf.set_fill_color(220, 220, 220)
    pdf.set_font(font_name, b_style, 12)
    pdf.cell(0, 10, "1. 부속 세트 구성 (Fitting Sets)", border=1, fill=True, new_x="LMARGIN", new_y="NEXT")
    
    header_h = 8
    # ── 컬럼 폭 재배분: 구분·수량 줄이고 세트명 늘림 ──
    col_w_img  = 40   # 이미지
    col_w_name = 105  # 세트명 + 구성품 목록 (↑ 70→105)
    col_w_type = 25   # 구분 (↓ 40→25)
    col_w_qty  = 20   # 수량 (↓ 30→20)
    # 합계 = 190

    pdf.set_fill_color(240, 240, 240)
    pdf.set_font(font_name, b_style, 9)
    pdf.cell(col_w_img,  header_h, "IMG",            border=1, align='C', fill=True)
    pdf.cell(col_w_name, header_h, "세트명 (Set Name)", border=1, align='C', fill=True)
    pdf.cell(col_w_type, header_h, "구분",            border=1, align='C', fill=True)
    pdf.cell(col_w_qty,  header_h, "수량",            border=1, align='C', fill=True, new_x="LMARGIN", new_y="NEXT")

    # 품목 코드 → 이름 맵
    prod_code_to_name = {str(p.get("code","")).strip().zfill(5): p.get("name","") for p in db_products}

    for item in set_cart:
        name  = item.get('name')
        qty   = item.get('qty')
        stype = item.get('type')

        # 세트의 레시피(구성품) 가져오기
        recipe = {}
        for cat, sets in db_sets.items():
            if name in sets:
                recipe = sets[name].get('recipe', {})
                break

        # 구성품 텍스트 (코드 → 이름+규격+코드 변환)
        recipe_lines = []
        for p_code, p_qty in recipe.items():
            norm_code = str(p_code).strip().zfill(5)
            p_name = prod_code_to_name.get(norm_code, str(p_code))
            # 규격 조회
            p_prod = next((p for p in db_products if str(p.get("code","")).strip().zfill(5) == norm_code), None)
            p_spec = p_prod.get("spec", "") if p_prod else ""
            spec_str = f" [{p_spec}]" if p_spec and p_spec != "-" else ""
            recipe_lines.append(f"  · {p_name}{spec_str}  ×{p_qty}  (#{norm_code})")
        recipe_text = "\n".join(recipe_lines)

        # 행 높이: 세트명 1줄 + 구성품 줄 수 기준
        n_lines = max(len(recipe_lines), 1)
        # 세트명 11pt(5mm) + 구성품 1줄당 4.5mm + 상하 여백 4mm
        row_h = max(5 + n_lines * 4.5 + 4, 22)

        check_page_break(row_h)

        # 이미지 셀
        img_id = None
        for cat, sets in db_sets.items():
            if name in sets:
                img_id = sets[name].get('image')
                break
        img_b64 = download_image_by_id(img_id)

        x, y = pdf.get_x(), pdf.get_y()
        pdf.cell(col_w_img, row_h, "", border=1)
        if img_b64:
            try:
                img_data = img_b64.split(",", 1)[1]
                img_bytes = base64.b64decode(img_data)
                with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as tmp:
                    tmp.write(img_bytes)
                    tmp_path = tmp.name
                img_sz = min(col_w_img - 6, row_h - 5, 32)
                pdf.image(tmp_path, x=x + (col_w_img - img_sz) / 2,
                          y=y + (row_h - img_sz) / 2, w=img_sz, h=img_sz)
                os.unlink(tmp_path)
            except: pass

        # 세트명 셀 — 세트명(굵게 11pt) + 구성품(9pt)
        pdf.set_xy(x + col_w_img, y)
        pdf.cell(col_w_name, row_h, "", border=1)

        # 세트명 텍스트 (굵게, 크게)
        pdf.set_xy(x + col_w_img + 2, y + 2)
        pdf.set_font(font_name, b_style, 11)
        pdf.cell(col_w_name - 4, 5.5, name, align='L')

        # 구성품 텍스트 (보통, 9pt)
        if recipe_text:
            pdf.set_xy(x + col_w_img + 2, y + 8)
            pdf.set_font(font_name, '', 8.5)
            pdf.multi_cell(col_w_name - 4, 4.5, recipe_text, align='L', max_line_height=4.5)

        # 구분 / 수량 셀
        pdf.set_xy(x + col_w_img + col_w_name, y)
        pdf.set_font(font_name, '', 10)
        pdf.cell(col_w_type, row_h, stype, border=1, align='C')
        pdf.cell(col_w_qty,  row_h, str(qty), border=1, align='C', new_x="LMARGIN", new_y="NEXT")

    pdf.ln(5)

    # 2. 배관 물량
    pdf.set_font(font_name, b_style, 12)
    pdf.set_fill_color(220, 220, 220)
    check_page_break(20)
    pdf.cell(0, 10, "2. 배관 물량 (Pipe Quantities)", border=1, fill=True, new_x="LMARGIN", new_y="NEXT")
    
    pdf.set_fill_color(240, 240, 240)
    pdf.set_font(font_name, b_style, 9)
    pdf.cell(22, header_h, "IMG", border=1, align='C', fill=True)
    pdf.cell(108, header_h, "품목명 (Product Name)", border=1, align='C', fill=True)
    pdf.cell(35, header_h, "총 길이(m)", border=1, align='C', fill=True)
    pdf.cell(25, header_h, "롤 수(EA)", border=1, align='C', fill=True, new_x="LMARGIN", new_y="NEXT")

    pipe_summary = {}
    for p in pipe_cart:
        code = p.get('code')
        if not code: continue
        if code not in pipe_summary:
            pipe_summary[code] = {'len': 0, 'name': p.get('name'), 'spec': p.get('spec')}
        pipe_summary[code]['len'] += p.get('len', 0)

    for code, info in pipe_summary.items():
        check_page_break(16)
        prod_info = next((item for item in db_products if str(item["code"]) == str(code)), None)
        unit_len = prod_info.get("len_per_unit", 4) if prod_info else 4
        if unit_len <= 0: unit_len = 4
        rolls = math.ceil(info['len'] / unit_len)
        img_val = prod_info.get("image") if prod_info else None
        
        img_id = get_best_image_id(code, img_val, drive_file_map)
        img_b64 = download_image_by_id(img_id)

        x, y = pdf.get_x(), pdf.get_y()
        pdf.cell(22, 16, "", border=1)
        if img_b64:
            try:
                img_data = img_b64.split(",", 1)[1]
                img_bytes = base64.b64decode(img_data)
                with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as tmp:
                    tmp.write(img_bytes)
                    tmp_path = tmp.name
                pdf.image(tmp_path, x=x+2, y=y+2, w=13, h=13)
                if os.path.exists(tmp_path):
                    os.unlink(tmp_path)
            except: pass
            
        pdf.set_xy(x+22, y)
        pdf.set_font(font_name, '', 10)
        pdf.cell(108, 16, f"{info['name']} ({info['spec']})", border=1, align='L')
        pdf.cell(35,  16, f"{info['len']} m", border=1, align='C')
        pdf.cell(25,  16, f"{rolls} 롤", border=1, align='C', new_x="LMARGIN", new_y="NEXT")

    pdf.ln(5)

    # 3. 추가 자재
    if additional_items_list:
        pdf.set_font(font_name, b_style, 12)
        pdf.set_fill_color(220, 220, 220)
        check_page_break(20)
        pdf.cell(0, 10, "3. 추가 자재 (Additional Components / Spares)", border=1, fill=True, new_x="LMARGIN", new_y="NEXT")
        
        pdf.set_fill_color(240, 240, 240)
        pdf.set_font(font_name, b_style, 9)
        pdf.cell(22, header_h, "IMG", border=1, align='C', fill=True)
        pdf.cell(133, header_h, "품목정보 (Name/Spec)", border=1, align='C', fill=True)
        pdf.cell(35, header_h, "추가 수량", border=1, align='C', fill=True, new_x="LMARGIN", new_y="NEXT")

        for item in additional_items_list:
            check_page_break(16)
            name = item['name']
            spec = item['spec'] if item['spec'] else '-'
            qty = item['qty']
            code = item.get('code')
            img_val = item.get('image')
            
            img_id = get_best_image_id(code, img_val, drive_file_map)
            img_b64 = download_image_by_id(img_id)

            x, y = pdf.get_x(), pdf.get_y()
            pdf.cell(22, 16, "", border=1)
            if img_b64:
                try:
                    img_data = img_b64.split(",", 1)[1]
                    img_bytes = base64.b64decode(img_data)
                    with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as tmp:
                        tmp.write(img_bytes)
                        tmp_path = tmp.name
                    pdf.image(tmp_path, x=x+2, y=y+2, w=13, h=13)
                    if os.path.exists(tmp_path):
                        os.unlink(tmp_path)
                except: pass
                
            pdf.set_xy(x+22, y)
            pdf.set_font(font_name, '', 10)
            pdf.cell(133, 16, f"{name} ({spec})", border=1, align='L')
            pdf.cell(35,  16, f"{int(qty)} EA", border=1, align='C', new_x="LMARGIN", new_y="NEXT")
        
        pdf.ln(5)

    # 4. 전체 자재
    pdf.set_font(font_name, b_style, 12)
    pdf.set_fill_color(220, 220, 220)
    check_page_break(20)
    idx_num = "4" if additional_items_list else "3"
    pdf.cell(0, 10, f"{idx_num}. 전체 자재 산출 목록 (Total Components)", border=1, fill=True, new_x="LMARGIN", new_y="NEXT")
    
    pdf.set_fill_color(240, 240, 240)
    pdf.set_font(font_name, b_style, 9)
    pdf.cell(22, header_h, "IMG", border=1, align='C', fill=True)
    pdf.cell(133, header_h, "품목정보 (Name/Spec)", border=1, align='C', fill=True)
    pdf.cell(35, header_h, "총 수량", border=1, align='C', fill=True, new_x="LMARGIN", new_y="NEXT")

    for item in final_data_list:
        try: qty = int(float(item.get("수량", 0)))
        except: qty = 0
        if qty == 0: continue

        check_page_break(16)
        name = item.get("품목", "")
        spec = item.get("규격", "-")
        code = item.get("코드", "")
        img_val = item.get("image_data")
        
        img_id = get_best_image_id(code, img_val, drive_file_map)
        img_b64 = download_image_by_id(img_id)

        x, y = pdf.get_x(), pdf.get_y()
        pdf.cell(22, 16, "", border=1)
        if img_b64:
            try:
                img_data = img_b64.split(",", 1)[1]
                img_bytes = base64.b64decode(img_data)
                with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as tmp:
                    tmp.write(img_bytes)
                    tmp_path = tmp.name
                pdf.image(tmp_path, x=x+2, y=y+2, w=13, h=13)
                if os.path.exists(tmp_path):
                    os.unlink(tmp_path)
            except: pass
            
        pdf.set_xy(x+22, y)
        pdf.set_font(font_name, '', 10)
        pdf.cell(133, 16, f"{name} ({spec})", border=1, align='L')
        pdf.cell(35,  16, f"{int(qty)} EA", border=1, align='C', new_x="LMARGIN", new_y="NEXT")

    return bytes(pdf.output())

def create_composition_excel(set_cart, pipe_cart, final_data_list, db_products, db_sets, quote_name):
    output = io.BytesIO()
    workbook = xlsxwriter.Workbook(output, {'in_memory': True})
    drive_file_map = get_drive_file_map_deep()
    
    fmt_header = workbook.add_format({'bold': True, 'bg_color': '#f0f0f0', 'border': 1, 'align': 'center', 'valign': 'vcenter'})
    fmt_center = workbook.add_format({'border': 1, 'align': 'center', 'valign': 'vcenter'})
    fmt_left = workbook.add_format({'border': 1, 'align': 'left', 'valign': 'vcenter'})

    baseline_counts = {}
    all_sets_db = {}
    for cat, val in db_sets.items(): all_sets_db.update(val)
    for item in set_cart:
        recipe = all_sets_db.get(item['name'], {}).get("recipe", {})
        for p, q in recipe.items(): baseline_counts[str(p)] = baseline_counts.get(str(p), 0) + (q * item['qty'])
    
    code_sums = {}
    for p_item in pipe_cart:
        c = p_item.get('code')
        if c: code_sums[c] = code_sums.get(c, 0) + p_item['len']
    for p_code, total_len in code_sums.items():
        prod_info = next((item for item in db_products if str(item["code"]) == str(p_code)), None)
        if prod_info:
            unit_len = prod_info.get("len_per_unit", 4)
            if unit_len <= 0: unit_len = 4
            baseline_counts[str(p_code)] = baseline_counts.get(str(p_code), 0) + math.ceil(total_len / unit_len)

    additional_items_list = []
    temp_baseline = baseline_counts.copy()

    for item in final_data_list:
        code = str(item.get("코드", "")).strip().zfill(5) if item.get("코드") else ""
        try: total_qty = int(float(item.get("수량", 0)))
        except: total_qty = 0
        name = item.get("품목", "")
        spec = item.get("규격", "")
        img_data = item.get("image_data", "")

        if code and code in temp_baseline:
            base_qty = temp_baseline[code]
            if total_qty > base_qty:
                diff = total_qty - base_qty
                additional_items_list.append({"name": name, "spec": spec, "qty": diff, "code": code, "image": img_data})
                temp_baseline[code] = total_qty
            else:
                temp_baseline[code] -= total_qty
        else:
            if total_qty > 0:
                additional_items_list.append({"name": name, "spec": spec, "qty": total_qty, "code": code, "image": img_data})

    temp_files = []

    def insert_scaled_image(ws, row, col, img_b64):
        if not img_b64: 
            ws.write(row, col, "", fmt_center)
            return
        try:
            img_data = img_b64.split(",", 1)[1] if "," in img_b64 else img_b64
            img_bytes = base64.b64decode(img_data)
            
            with Image.open(io.BytesIO(img_bytes)) as pil_img:
                orig_w, orig_h = pil_img.size
                pil_img.close()
            
            with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as tmp:
                tmp.write(img_bytes)
                tmp_path = tmp.name
                temp_files.append(tmp_path)
            
            cell_w_px = 110
            cell_h_px = 106
            
            scale_x = cell_w_px / orig_w
            scale_y = cell_h_px / orig_h
            scale = min(scale_x, scale_y) * 0.9 
            
            final_w = orig_w * scale
            final_h = orig_h * scale
            
            offset_x = (cell_w_px - final_w) / 2
            offset_y = (cell_h_px - final_h) / 2
            
            ws.insert_image(row, col, tmp_path, {
                'x_scale': scale, 'y_scale': scale,
                'x_offset': offset_x, 'y_offset': offset_y,
                'object_position': 1
            })
        except:
            ws.write(row, col, "Err", fmt_center)

    ws1 = workbook.add_worksheet("부속세트")
    ws1.write(0, 0, "이미지", fmt_header)
    ws1.write(0, 1, "세트명", fmt_header)
    ws1.write(0, 2, "구성품 (품목명 / 규격 / 코드 / 수량)", fmt_header)
    ws1.write(0, 3, "구분", fmt_header)
    ws1.write(0, 4, "수량", fmt_header)
    ws1.set_column(0, 0, 15)
    ws1.set_column(1, 1, 22)
    ws1.set_column(2, 2, 55)
    ws1.set_column(3, 3, 12)
    ws1.set_column(4, 4, 8)

    # 엑셀용 구성품 포맷
    fmt_recipe = workbook.add_format({'border': 1, 'align': 'left', 'valign': 'top', 'text_wrap': True, 'font_size': 9})

    prod_code_to_info = {
        str(p.get("code","")).strip().zfill(5): p
        for p in db_products
    }

    row = 1
    for item in set_cart:
        name = item.get('name')
        # 세트 레시피 조회
        recipe = {}
        for cat, sets in db_sets.items():
            if name in sets:
                recipe = sets[name].get('recipe', {})
                break

        # 구성품 텍스트 조합
        recipe_lines = []
        for p_code, p_qty in recipe.items():
            norm = str(p_code).strip().zfill(5)
            p_info = prod_code_to_info.get(norm, {})
            p_name = p_info.get("name", norm)
            p_spec = p_info.get("spec", "")
            spec_str = f" [{p_spec}]" if p_spec and p_spec != "-" else ""
            recipe_lines.append(f"· {p_name}{spec_str}  #{norm}  ×{p_qty}")
        recipe_text = "\n".join(recipe_lines) if recipe_lines else "-"

        n_lines = max(len(recipe_lines), 1)
        row_h = max(80, n_lines * 18)
        ws1.set_row(row, row_h)

        img_id = None
        for cat, sets in db_sets.items():
            if name in sets:
                img_id = sets[name].get('image')
                break
        insert_scaled_image(ws1, row, 0, download_image_by_id(img_id))
        ws1.write(row, 1, name, fmt_left)
        ws1.write(row, 2, recipe_text, fmt_recipe)
        ws1.write(row, 3, item.get('type'), fmt_center)
        ws1.write(row, 4, item.get('qty'), fmt_center)
        row += 1

    ws2 = workbook.add_worksheet("배관물량")
    ws2.write(0, 0, "이미지", fmt_header)
    ws2.write(0, 1, "품목명", fmt_header)
    ws2.write(0, 2, "총길이(m)", fmt_header)
    ws2.write(0, 3, "롤수", fmt_header)
    ws2.set_column(0, 0, 15)
    ws2.set_column(1, 1, 30)

    pipe_summary = {}
    for p in pipe_cart:
        code = p.get('code')
        if not code: continue
        if code not in pipe_summary:
            pipe_summary[code] = {'len': 0, 'name': p.get('name'), 'spec': p.get('spec')}
        pipe_summary[code]['len'] += p.get('len', 0)

    row = 1
    for code, info in pipe_summary.items():
        ws2.set_row(row, 80)
        prod_info = next((item for item in db_products if str(item["code"]) == str(code)), None)
        unit_len = prod_info.get("len_per_unit", 4) if prod_info else 4
        if unit_len <= 0: unit_len = 4
        rolls = math.ceil(info['len'] / unit_len)
        img_val = prod_info.get("image") if prod_info else None
        
        insert_scaled_image(ws2, row, 0, download_image_by_id(get_best_image_id(code, img_val, drive_file_map)))
        ws2.write(row, 1, f"{info['name']} ({info['spec']})", fmt_left)
        ws2.write(row, 2, info['len'], fmt_center)
        ws2.write(row, 3, rolls, fmt_center)
        row += 1

    if additional_items_list:
        ws_add = workbook.add_worksheet("추가자재")
        ws_add.write(0, 0, "이미지", fmt_header)
        ws_add.write(0, 1, "품목명", fmt_header)
        ws_add.write(0, 2, "규격", fmt_header)
        ws_add.write(0, 3, "추가수량", fmt_header)
        ws_add.set_column(0, 0, 15)
        ws_add.set_column(1, 1, 30)
        
        row = 1
        for item in additional_items_list:
            ws_add.set_row(row, 80)
            img_val = item.get('image')
            code = item.get('code')
            
            insert_scaled_image(ws_add, row, 0, download_image_by_id(get_best_image_id(code, img_val, drive_file_map)))
            ws_add.write(row, 1, item['name'], fmt_left)
            ws_add.write(row, 2, item['spec'], fmt_center)
            ws_add.write(row, 3, item['qty'], fmt_center)
            row += 1

    ws3 = workbook.add_worksheet("전체자재")
    ws3.write(0, 0, "이미지", fmt_header)
    ws3.write(0, 1, "품목명", fmt_header)
    ws3.write(0, 2, "규격", fmt_header)
    ws3.write(0, 3, "총수량", fmt_header)
    ws3.set_column(0, 0, 15)
    ws3.set_column(1, 1, 30)

    row = 1
    for item in final_data_list:
        try: qty = int(float(item.get("수량", 0)))
        except: qty = 0
        if qty == 0: continue
        
        ws3.set_row(row, 80)
        code = item.get("코드", "")
        img_val = item.get("image_data")
        
        insert_scaled_image(ws3, row, 0, download_image_by_id(get_best_image_id(code, img_val, drive_file_map)))
        ws3.write(row, 1, item.get("품목", ""), fmt_left)
        ws3.write(row, 2, item.get("규격", "-"), fmt_center)
        ws3.write(row, 3, qty, fmt_center)
        row += 1

    workbook.close()
    
    for f in temp_files:
        try: 
            if os.path.exists(f):
                os.unlink(f)
        except: pass
        
    return output.getvalue()

# ==========================================
# 3. 메인 로직 (DB Init & 2FA Lockout)
# ==========================================
if "db" not in st.session_state:
    with st.spinner("DB 연동 중..."): 
        st.session_state.db = load_data_from_sheet()

if "app_authenticated" not in st.session_state:
    st.session_state.app_authenticated = False
    st.session_state.failed_attempts = 0
    st.session_state.lockout_time = None

if st.session_state.lockout_time:
    if datetime.datetime.now() < st.session_state.lockout_time:
        remaining_time = (st.session_state.lockout_time - datetime.datetime.now()).seconds // 60
        st.error(f"🚫 보안 잠금 상태입니다. {remaining_time + 1}분 후에 다시 시도하세요.")
        st.stop()
    else:
        st.session_state.failed_attempts = 0
        st.session_state.lockout_time = None

if not st.session_state.app_authenticated:
    st.markdown("<h2 style='text-align: center; margin-top: 100px;'>🔒 루퍼젯 프로 매니저</h2>", unsafe_allow_html=True)
    col1, col2, col3 = st.columns([1, 1, 1])
    with col2:
        with st.container(border=True):
            pwd = st.text_input("프로그램 접속 비밀번호", type="password", key="app_pwd")
            if st.button("접속", use_container_width=True):
                app_pwd_db = str(st.session_state.db.get("config", {}).get("app_pwd", "1234"))
                if pwd == app_pwd_db:
                    st.session_state.app_authenticated = True
                    st.session_state.failed_attempts = 0
                    st.rerun()
                else:
                    st.session_state.failed_attempts += 1
                    if st.session_state.failed_attempts >= 5:
                        st.session_state.lockout_time = datetime.datetime.now() + datetime.timedelta(minutes=30)
                        st.error("🚫 비밀번호를 5회 틀렸습니다. 30분 동안 접속이 차단됩니다.")
                        time.sleep(2)
                        st.rerun()
                    else:
                        st.error(f"❌ 비밀번호가 틀렸습니다. ({st.session_state.failed_attempts}/5)")
    st.stop()

# --- Authenticated App Start ---

if "history" not in st.session_state: st.session_state.history = {} 
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

st.title("💧 루퍼젯 프로 매니저 V12.0 (Cloud)")

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
    
    col_s1, col_s2, col_s3 = st.columns(3)
    with col_s1: btn_save_temp = st.button("💾 임시저장")
    with col_s2: btn_save_off = st.button("✅ 정식저장")
    with col_s3: btn_init = st.button("✨ 초기화")
    
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
        mode = st.radio("모드", ["견적 작성", "관리자 모드", "🇯🇵 일본 수출 분석"], key="main_sidebar_mode")
    else:
        mode = st.radio("モード", ["見積作成", "管理者モード"], key="main_sidebar_mode")

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
        
        c_l1, c_l2, c_l3 = st.columns(3)
        with c_l1: btn_load = st.button("📂 불러오기")
        with c_l2: btn_copy = st.button("📝 복사/수정")
        with c_l3: btn_del = st.button("🗑️ 삭제")
        
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

if mode == "관리자 모드" or mode == "管理者モード":
    st.header("🛠 관리자 모드")
    if st.button("🔄 구글시트 데이터 새로고침"): st.session_state.db = load_data_from_sheet(); st.session_state._img_cache = {}; st.success("완료"); st.rerun()
    if not st.session_state.auth_admin:
        pw = st.text_input("관리자 비밀번호", type="password")
        if st.button("로그인"):
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

            # ── [V11] 매입단가 변동 → 전체 단가 자동 재계산 ────────────
            st.divider()
            st.markdown("##### 💹 매입단가 변동 → 전체 단가 자동 재계산")
            with st.expander("품목을 선택하여 매입단가 변경 시 다른 단가를 자동 재계산합니다.", expanded=False):
                st.info("매입단가를 입력하면 기존 단가 구조(비율)를 유지하며 자동 재계산합니다.\n라운드업 규칙: ~999원→1원 단위 / 1천~9999원→10원 단위 / 1만원~→100원 단위")

                products_for_recalc = st.session_state.db["products"]
                recalc_target = st.selectbox(
                    "재계산 대상 품목 선택",
                    products_for_recalc,
                    format_func=lambda p: (
                        f"[{p.get('code','?')}] {p.get('name','')} ({p.get('spec','-')}) "
                        f"| 매입가: {int(p.get('price_buy', 0) or 0):,}원"
                        + (f" | 🕒 {p.get('last_updated','')}" if p.get('last_updated') else "")
                    ),
                    key="recalc_product_sel"
                )

                if recalc_target:
                    old_buy = int(recalc_target.get("price_buy", 0) or 0)
                    col_new_buy, col_preview = st.columns([1, 2])
                    with col_new_buy:
                        new_buy_input = st.number_input(
                            "새 매입단가 (원)", min_value=0, value=old_buy, step=10, key="new_buy_input"
                        )

                    if new_buy_input > 0:
                        # 매입가 변동 여부와 무관하게 항상 editor 표시
                        preview = recalc_prices_from_buy(recalc_target, new_buy_input)
                        with col_preview:
                            st.markdown("**📊 재계산 미리보기**")
                            preview_rows = []
                            for fk, label in KR_PRICE_LABELS.items():
                                old_v = float(recalc_target.get(fk, 0) or 0)
                                new_v = float(preview.get(fk, 0))
                                delta = new_v - old_v
                                fmt = lambda x: round(x, 1) if x < 1000 else int(x)
                                preview_rows.append({
                                    "_field": fk,
                                    "항목": label,
                                    "기존": fmt(old_v),
                                    "변경후": fmt(new_v),
                                })
                            edited_preview = st.data_editor(
                                pd.DataFrame(preview_rows),
                                column_config={
                                    "_field": None,  # 숨김
                                    "항목": st.column_config.TextColumn("항목", disabled=True, width="small"),
                                    "기존": st.column_config.NumberColumn("기존", disabled=True, format="%.1f", width="small"),
                                    "변경후": st.column_config.NumberColumn("변경후 ✏️", format="%.1f", width="small"),
                                },
                                hide_index=True,
                                use_container_width=True,
                                key="preview_editor"
                            )
                            # 수정된 값으로 preview 덮어쓰기
                            for _, row in edited_preview.iterrows():
                                fk = row["_field"]
                                if fk in preview:
                                    preview[fk] = row["변경후"]

                        if new_buy_input != old_buy:
                            st.warning(f"⚠️ [{recalc_target.get('code')}] {recalc_target.get('name')} 의 단가를 위와 같이 변경합니다.")
                        else:
                            st.info(f"ℹ️ 매입가 동일 — 변경후 열을 직접 수정한 항목만 저장됩니다.")
                        col_ok, col_cancel = st.columns(2)
                        with col_ok:
                            if st.button("✅ 확인 — 단가 반영 및 저장", key="btn_recalc_confirm", type="primary"):
                                target_code = str(recalc_target.get("code", "")).strip()
                                today_str = datetime.datetime.now().strftime("%Y-%m-%d")
                                updated_products = []
                                for p in st.session_state.db["products"]:
                                    if str(p.get("code", "")).strip() == target_code:
                                        p.update(preview)
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
            ppt_data = get_admin_ppt_content()
            if ppt_data:
                st.download_button(label="📥 세트 구성 일람표(PPT) 다운로드", data=ppt_data, file_name="Set_Composition_Master.pptx", mime="application/vnd.openxmlformats-officedocument.presentationml.presentation", use_container_width=True)
            else:
                st.warning("⚠️ 구글 드라이브 'Looperget_Admin' 폴더에 'Set_Composition_Master.pptx' 파일이 없습니다.")
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
                                st.session_state.set_manage_mode = "수정" 
                                st.rerun()
                        with col_img:
                            with st.expander("🖼️ 세트 이미지 관리", expanded=True):
                                set_folder_id = get_or_create_set_drive_folder()
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
            st.divider()
            # ── V12: 세트 이미지 빌더 (Fabric.js) ─────────────────────────
            st.markdown("##### 🎨 세트 이미지 빌더 (Fabric.js)")
            with st.expander("캔버스에서 부속 배치 → 세트 이미지 생성 / 신규 세트 통합 등록", expanded=False):
                build_set_image_editor(st.session_state.db.get("sets", {}), st.session_state.db.get("products", []), get_drive_file_map_deep())
            if "set_manage_mode" not in st.session_state: st.session_state.set_manage_mode = "신규"
            mt = st.radio("작업", ["신규", "수정"], horizontal=True, key="set_manage_mode")
            sub_cat = None
            if cat == "주배관세트": sub_cat = st.selectbox("하위분류", ["50mm", "40mm", "기타"], key="sub_c")
            products_obj = st.session_state.db["products"]
            code_name_map = {str(p.get("code")): f"[{p.get('code')}] {p.get('name')} ({p.get('spec')})" for p in products_obj}
            
            if mt == "신규":
                nn = st.text_input("세트명")
                c1, c2, c3 = st.columns([3,2,1])
                with c1: sp_obj = st.selectbox("부품", products_obj, format_func=format_prod_label, key="nsp")
                with c2: sq = st.number_input("수량", 1, key="nsq")
                with c3: 
                    if st.button("담기"): st.session_state.temp_set_recipe[str(sp_obj['code'])] = sq
                st.caption("구성 품목 (수량 수정 및 행 삭제 가능)")
                
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
                        key="recipe_editor_new"
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
                
                if st.button("저장", key="btn_new_set"):
                    if cat not in st.session_state.db["sets"]: st.session_state.db["sets"][cat] = {}
                    st.session_state.db["sets"][cat][nn] = {"recipe": st.session_state.temp_set_recipe, "image": "", "sub_cat": sub_cat}
                    save_sets_to_sheet(st.session_state.db["sets"]); st.session_state.temp_set_recipe={}; st.success("저장")
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
                    pdf.set_font(FONT_REGULAR if os.path.exists(FONT_REGULAR) else 'Helvetica', '', 10)
                    
                    pdf.cell(0, 10, f"Analysis Date: {datetime.datetime.now().strftime('%Y-%m-%d')}", ln=True, align='R')
                    pdf.cell(0, 10, f"Quote Name: {target_quote.get('현장명')}", ln=True)
                    pdf.ln(5)
                    
                    pdf.set_fill_color(220, 220, 220)
                    cols = ["Code", "Item Name", "Spec", "Qty", "Buy Price", "Supply Price", "Sum Revenue", "Sum Cost", "Profit"]
                    widths = [20, 50, 40, 15, 30, 30, 35, 35, 30]
                    for head, w in zip(cols, widths):
                        pdf.cell(w, 10, head, border=1, align='C', fill=True)
                    pdf.ln()
                    
                    pdf.set_font(FONT_REGULAR if os.path.exists(FONT_REGULAR) else 'Helvetica', '', 8)
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
                    
                    pdf.set_font(FONT_BOLD if os.path.exists(FONT_BOLD) else 'Helvetica', 'B', 10)
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
                        added = sum(1 for k,v in all_inp.items() if v > 0 and not st.session_state.set_cart.append({"name":k,"qty":v,"type":"メイン管"}) for _ in [None] if v>0)
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
            mt1, mt2, mt3, mt4 = st.tabs(["50mm", "40mm", "기타", "전체"])
            # ── V12: 세션 캐시 + 카드 + 툴팁 렌더 ──────────────────────────
            def get_cached_set_image(set_name, img_ref):
                if "_img_cache" not in st.session_state:
                    st.session_state._img_cache = {}
                if set_name not in st.session_state._img_cache:
                    st.session_state._img_cache[set_name] = get_image_from_drive(img_ref)
                return st.session_state._img_cache.get(set_name)

            def render_inputs_with_key(d, pf):
                cols = st.columns(4); res = {}
                for i, (n, v) in enumerate(d.items()):
                    with cols[i % 4]:
                        img_name = v.get("image") if isinstance(v, dict) else None
                        recipe = v.get("recipe", {}) if isinstance(v, dict) else {}
                        if recipe:
                            pdb_local = {str(p.get("code","")): p.get("name","") for p in st.session_state.db.get("products", [])}
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

            with mt1: inp_m_50 = render_inputs_with_key(grouped.get("50mm", {}), "m50")
            with mt2: inp_m_40 = render_inputs_with_key(grouped.get("40mm", {}), "m40")
            with mt3: inp_m_etc = render_inputs_with_key(grouped.get("기타", {}), "metc")
            with mt4: inp_m_all = render_inputs_with_key(m_sets, "mall")
            
            st.write("")
            if st.button("➕ 입력한 수량 세트 목록에 추가"):
                def sum_dictionaries(*dicts):
                    result = {}
                    for d in dicts:
                        for k, v in d.items():
                            result[k] = result.get(k, 0) + v
                    return result
                
                all_inputs = sum_dictionaries(inp_m_50, inp_m_40, inp_m_etc, grouped.get("미분류", {}), inp_m_all)
                
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
            c1, c2, c3 = st.tabs(["가지관", "살수", "기타자재"])
            with c1: inp_b = render_inputs_with_key(sets.get("가지관세트", {}), "b_set")
            with c2: inp_s = render_inputs_with_key(sets.get("살수세트", {}), "s_set")
            with c3: inp_e = render_inputs_with_key(sets.get("기타자재", {}), "e_set")
            if st.button("➕ 가지관/살수/기타 목록 추가"):
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
                pw = st.text_input("원가 조회 비번", type="password")
                if st.button("해제"):
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
                c_pw, c_btn = st.columns([2,1])
                with c_pw: input_pw = st.text_input("비밀번호", type="password", key="step3_pw")
                with c_btn: 
                    if st.button("해제", key="step3_btn"):
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

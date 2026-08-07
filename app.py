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

# [V27] 브랜드 로고(옐로우, 다크헤더용) — 없으면 텍스트 폴백
try:
    from looperget_brand import LOGO_YELLOW_B64
except Exception:
    LOGO_YELLOW_B64 = ""

# 구글 연동 라이브러리
import gspread
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload

# ==========================================
# [중요] 0. 페이지 설정을 최상단으로 유지
# ==========================================
st.set_page_config(layout="wide", page_title="Looperget 프로 매니저", page_icon="🟡")

# ==========================================
# [V27] 루퍼젯 브랜드 디자인 (다크 인더스트리얼) — 판매가이드 규격
#   Yellow #F4D624 · Black #191414 · White #FFFFFF
# ==========================================
st.markdown("""
<style>
:root { --lg-yellow:#F4D624; --lg-ink:#191414; --lg-line:#3A3433; }
.block-container { padding-top: 3.2rem; }

/* 브랜드 헤더 */
.lg-header { display:flex; align-items:center; gap:14px; padding:8px 2px 13px 2px;
    margin-bottom:14px; border-bottom:3px solid var(--lg-yellow); overflow:visible; }
.lg-header img.lg-logo { height:38px; width:auto; display:block; }
.lg-header .lg-sub { color:#F2F1EE; font-size:19px; font-weight:800; letter-spacing:.3px;
    padding-left:16px; border-left:2px solid var(--lg-line); }
.lg-header .lg-corp { margin-left:auto; color:#8C8681; font-size:12px; font-weight:600; letter-spacing:.3px; }
.lg-header .lg-corp b { color:var(--lg-yellow); }

/* 버튼 — 둥근 모서리·볼드 (색상은 테마 primaryColor=옐로우 사용) */
.stButton>button, .stDownloadButton>button, .stFormSubmitButton>button {
    border-radius:8px; font-weight:700; }

/* 탭 활성 강조 */
.stTabs [aria-selected="true"] { color:var(--lg-yellow) !important; }

/* 구분선·사이드바 */
hr { border-color:var(--lg-line); }
[data-testid="stSidebar"] { border-right:1px solid var(--lg-line); }

/* 브랜드 푸터 */
.lg-footer { margin-top:30px; padding-top:11px; border-top:1px solid var(--lg-line);
    color:#7C7773; font-size:11.5px; letter-spacing:.3px; }
.lg-footer b { color:var(--lg-yellow); }
</style>
""", unsafe_allow_html=True)

def render_brand_header(subtitle="프로 매니저"):
    """[V27] 브랜드 헤더(로고+부제) 렌더. 로고 없으면 텍스트 폴백."""
    if LOGO_YELLOW_B64:
        logo_html = f'<img class="lg-logo" src="data:image/png;base64,{LOGO_YELLOW_B64}" alt="Looperget"/>'
    else:
        logo_html = '<span style="font-size:26px;font-weight:900;color:#F4D624;letter-spacing:1px;">Looperget</span>'
    st.markdown(
        f'<div class="lg-header">{logo_html}'
        f'<span class="lg-sub">{subtitle}</span>'
        f'<span class="lg-corp">by <b>ShinJin</b>ChemTech</span></div>',
        unsafe_allow_html=True)

def render_brand_footer():
    """[V27] 브랜드 푸터."""
    st.markdown(
        '<div class="lg-footer"><b>Looperget</b> Pro Manager · ShinJinChemTech · © 2026 신진켐텍(주)</div>',
        unsafe_allow_html=True)

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

# [V32] 소켓 끊김(Broken pipe 등) 감지 키워드 — 재인증 재시도 판단 공통.
_SOCKET_ERRS = ("Broken pipe", "Errno 32", "Errno 104", "10053", "10054",
                "Connection reset", "Connection aborted", "ConnectionReset",
                "RemoteDisconnected", "EOF occurred", "IncompleteRead", "timed out")

def upload_image_to_drive(file_obj, filename):
    folder_id = get_or_create_drive_folder()
    if not folder_id: return None
    def _do():
        buf = io.BytesIO(file_obj.getvalue()); buf.seek(0)
        media = MediaIoBaseUpload(buf, mimetype=file_obj.type, resumable=False)
        _get_ds().files().create(body={'name': filename, 'parents': [folder_id]}, media_body=media, fields='id', supportsAllDrives=True).execute(num_retries=3)
        return filename
    try:
        return _do()
    except Exception as e:
        if any(k in str(e) for k in _SOCKET_ERRS):   # [V32] 끊긴 연결 → 재인증 후 재시도
            try:
                get_google_services.clear(); return _do()
            except Exception as e2:
                st.error(f"업로드 실패(재연결 후에도): {e2}. 잠시 뒤 다시 시도해주세요."); return None
        st.error(f"업로드 실패: {e}")
        return None

def upload_set_image_to_drive(file_obj, filename):
    folder_id = get_or_create_drive_folder()
    if not folder_id: return None
    def _do():
        buf = io.BytesIO(file_obj.getvalue()); buf.seek(0)
        media = MediaIoBaseUpload(buf, mimetype=file_obj.type, resumable=False)
        info = _get_ds().files().create(body={'name': filename, 'parents': [folder_id]}, media_body=media, fields='id', supportsAllDrives=True).execute(num_retries=3)
        return info.get('id')
    try:
        return _do()
    except Exception as e:
        error_msg = str(e)
        if any(k in error_msg for k in _SOCKET_ERRS):   # [V32] 끊긴 연결 → 재인증 후 재시도
            try:
                get_google_services.clear(); return _do()
            except Exception as e2:
                st.error(f"세트 이미지 업로드 실패(재연결 후에도): {e2}. 잠시 뒤 다시 시도해주세요."); return None
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
    def _do():
        # [V32] 재시도마다 새 버퍼(소진 방지) + 최신 서비스객체(_get_ds)
        buf = io.BytesIO(byte_data); buf.seek(0)
        meta = {'name': filename, 'parents': [folder_id]}
        media = MediaIoBaseUpload(buf, mimetype=mimetype, resumable=False)
        info = _get_ds().files().create(body=meta, media_body=media, fields='id', supportsAllDrives=True).execute(num_retries=3)
        return info.get('id')
    try:
        return _do()
    except Exception as e:
        err = str(e)
        # [V32] Broken pipe/소켓 끊김 = 캐시된 드라이브 연결이 죽은 것(30분 TTL·유휴). 재인증 후 1회 재시도.
        #  (공유드라이브 전환 완료 상태이므로 권한 문제 아님 — 대개 재시도로 성공.)
        if any(k in err for k in ("Broken pipe", "Errno 32", "ConnectionReset", "RemoteDisconnected", "EOF occurred")):
            try:
                get_google_services.clear()
                return _do()
            except Exception as e2:
                st.error(f"업로드 실패(재연결 후에도): {e2}. 잠시 뒤 다시 시도해주세요.")
                return None
        if "storageQuotaExceeded" in err:
            st.error("업로드 실패: 드라이브 용량/권한(서비스계정). 공유드라이브 설정을 확인하세요.")
            return None
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

def _do_download_image(ds, file_id):
    """실제 드라이브 다운로드 (재시도 로직 분리)
    - 원본 비율 유지 (지주대 등 세장형 품목 대응)
    - 300×225 박스 안에 중앙 패딩 배치
    - 드라이브 파일 원본은 건드리지 않음
    """
    request = ds.files().get_media(fileId=file_id)
    downloader = request.execute(num_retries=3)   # [V36] 소켓 끊김 자동 재시도
    with Image.open(io.BytesIO(downloader)) as img:
        # [V29] 투명 PNG(RGBA/LA/P+투명) → 흰 배경에 합성 후 RGB.
        #  기존 convert('RGB')는 알파를 검정으로 채워, 누끼 PNG가 빌더·견적서에서 검정배경이 되는 사고 유발(V15 §2-6).
        #  흰 배경 합성 시 빌더의 흰배경 키아웃(makeTransparentBg)·여백자르기가 정상 동작.
        if img.mode in ('RGBA', 'LA') or (img.mode == 'P' and 'transparency' in img.info):
            _rgba = img.convert('RGBA')
            _wbg = Image.new('RGBA', _rgba.size, (255, 255, 255, 255))
            _wbg.paste(_rgba, (0, 0), _rgba)   # 알파를 마스크로 → 투명영역은 흰색
            img_rgb = _wbg.convert('RGB')
        else:
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
# [V33] 실패(None)를 캐시하지 않는다 — 예전엔 Broken pipe 한 번이면 None이 1시간 캐시돼
#  해당 부속이 리런마다 계속 빈칸/사라진 것처럼 보였음. st.cache_data는 예외를 캐시하지 않으므로,
#  캐시되는 내부 함수는 실패 시 예외를 던지고 외부 래퍼가 None으로 감싼다. (다음 리런에 자동 재시도)
# [V35] ttl 1h→24h — 키가 파일ID라 안전(이미지 교체 시 새 ID 발급 → 자동 반영). 매시간 전체 재다운로드 폭풍 제거.
@st.cache_data(ttl=86400, show_spinner=False)
def _download_image_cached(file_id):
    ds = get_google_services()[1]  # 항상 최신 서비스 객체 사용
    if not ds: raise RuntimeError("drive service unavailable")
    try:
        return _do_download_image(ds, file_id)
    except Exception as e:
        if any(k in str(e) for k in _SOCKET_ERRS):
            get_google_services.clear()  # 소켓 끊김 → 재인증 후 1회 재시도
            ds2 = get_google_services()[1]
            if ds2:
                return _do_download_image(ds2, file_id)
        raise

def download_image_by_id(file_id):
    if not file_id: return None
    try:
        return _download_image_cached(file_id)
    except Exception:
        return None

def get_image_from_drive(filename_or_id):
    # [V33] 캐시 데코레이터 제거 — 맵·다운로드가 이미 캐시라 중복이고, 실패 None을 1시간 물고 있었음.
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
        raw = ds.files().get_media(fileId=file_id).execute(num_retries=3)
        return raw.decode("utf-8") if isinstance(raw, (bytes, bytearray)) else str(raw)
    except Exception:
        try:
            get_google_services.clear()
            ds2 = get_google_services()[1]
            if ds2:
                raw = ds2.files().get_media(fileId=file_id).execute(num_retries=3)
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
        return request.execute(num_retries=3)
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

# ==========================================
# [V41] 아쿠나리스(농협 관수코너) — 시트 로드
#  - 단가 정본은 Products. AQ_Items는 진열 속성만 담는다(단가 컬럼 없음).
#  [V46] 읽기쿼터 보호: 4개 시트를 일괄 1회 로드(open_by_key — 이름검색 제거) + 429 친화 안내.
#        구글 무료 한도 = 분당 읽기 60회/사용자(서비스계정 공유) — 개별 open×4가 세션시작 읽기와
#        겹치며 429 유발(2026-07-18 배포 실증) → 열기 1회+읽기 4회로 축소.
# ==========================================
AQ_SHEET_ID = "1oKtEJ47qOyrNS1JrIQT5dIuXs8MiiXkDeDsRNQdymFM"   # Looperget_DB (tools/gs.py와 동일 문서)

@st.cache_resource(ttl=600, show_spinner=False)
def _aq_sh():
    """아쿠나리스용 스프레드시트 핸들(캐시). ID 직접 열기 — 이름검색(Drive API) 생략."""
    try:
        return gc.open_by_key(AQ_SHEET_ID)
    except Exception:
        return gc.open(SHEET_NAME)

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

# ── [V48] 계정·권한 — Users 시트 기반. 시트가 없거나 공용 비밀번호 로그인이면 기존 동작 100% 보존 ──
@st.cache_data(ttl=300, show_spinner=False)
def load_users():
    """Users 시트 → list[dict] (아이디 있는 행만). 시트 없음/실패 시 []."""
    if not gc: return []
    try:
        return [u for u in _aq_sh().worksheet("Users").get_all_records()
                if str(u.get("아이디", "")).strip()]
    except Exception:
        return []

def aq_can(perm, strict=False):
    """권한 검사. 공용(비아이디) 로그인 세션: strict=False→허용(기존 동작), strict=True→차단(민감 기능 전용).
    권한 토큰: master/quote/aqunaris/aq_profit/admin/jp (Users 시트 '권한' 쉼표 구분)."""
    perms = st.session_state.get("user_perms")
    if perms is None:
        return not strict
    return ("master" in perms) or (perm in perms)

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

from aquanaris_layout import *   # [V66] 아쿠나리스 배치 엔진 분리 — ⚠배포 시 aquanaris_layout.py도 함께 올릴 것
# [V67] 신구 짝 검증 — 모듈이 구버전이면(NameError로 죽기 전에) 원인과 조치를 한국어로 안내하고 정지.
#  (2026-07-24 실배포에서 app.py만 푸시되어 line 6573 NameError 발생 → 재발 방지 가드)
if int(globals().get("AQ_LAYOUT_VER", 0) or 0) < 71:
    st.error("🚨 **aquanaris_layout.py가 구버전입니다** — app.py(V71)와 짝이 맞지 않습니다.\n\n"
             "GitHub `Looperget-Mate/Price`에 **최신 `aquanaris_layout.py`를 app.py와 함께** 올린 뒤 "
             "재배포하세요. 두 파일은 항상 세트로 푸시해야 합니다.")
    st.stop()

# ══ [V72] 아쿠나리스 인쇄물(스티커·가이드북·배치도 PDF) → `looperget/aq_print.py` 분리 ══
# 원본 L1034-2035(1,002줄)을 기계적 추출. 로직 무변경. 배포 시 looperget/ 폴더를 함께 올릴 것.
# ── 분리 모듈 짝 검증: 폴더가 없거나 구버전이면 크래시 대신 한국어로 안내하고 정지 ──
try:
    import looperget as _lg
    _LG_VER = int(getattr(_lg, "PKG_VER", 0) or 0)
except Exception:
    _LG_VER = 0
if _LG_VER < 73:
    st.error("🚨 **`looperget/` 폴더가 없거나 구버전입니다** — app.py(V73)와 짝이 맞지 않습니다.\n\n"
             "GitHub `Looperget-Mate/Price`에 **`looperget/` 폴더를 통째로** "
             "`app.py`·`aquanaris_layout.py`와 함께 올린 뒤 재배포하세요. **셋은 항상 세트입니다.**")
    st.stop()

from looperget import aq_print as _aqp
_aqp.bind(FONT_REGULAR=FONT_REGULAR, FONT_BOLD=FONT_BOLD,
          aq_err_str=aq_err_str,
          aq_load_items=aq_load_items, aq_load_sites=aq_load_sites,
          aq_load_boxes=aq_load_boxes,
          download_image_by_id=download_image_by_id)
from looperget.aq_print import *
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
    _logo_tag = (f'<img src="data:image/png;base64,{LOGO_YELLOW_B64}" style="height:58px;width:auto;margin-bottom:2px;"/>'
                 if LOGO_YELLOW_B64 else '<span style="font-size:44px;font-weight:900;color:#F4D624;letter-spacing:1px;">Looperget</span>')
    st.markdown(
        f"<div style='text-align:center; margin-top:80px; margin-bottom:10px;'>{_logo_tag}"
        f"<div style='color:#F2F1EE;font-size:17px;font-weight:800;letter-spacing:4px;margin-top:10px;'>PRO MANAGER</div>"
        f"<div style='color:#8C8681;font-size:12px;letter-spacing:1px;margin-top:6px;'>🔒 ShinJinChemTech</div></div>",
        unsafe_allow_html=True)
    col1, col2, col3 = st.columns([1, 1, 1])
    with col2:
        with st.form("login_form", border=True):
            login_id = st.text_input("아이디 (계정 로그인 시 — 비우면 공용 비밀번호)", key="app_login_id")
            pwd = st.text_input("프로그램 접속 비밀번호", type="password", key="app_pwd")
            # [V27] 폼: 비밀번호 입력 후 Enter 또는 '접속' 클릭 둘 다 제출
            # [V48] 아이디 입력 시 Users 시트 계정 인증(기능 권한 부여) · 비우면 기존 공용 비번 그대로
            if st.form_submit_button("접속", use_container_width=True, type="primary"):
                app_pwd_db = str(st.session_state.db.get("config", {}).get("app_pwd", "1234"))
                _uid = (login_id or "").strip()
                _urec = None
                if _uid:
                    _urec = next((u for u in load_users()
                                  if str(u.get("아이디", "")).strip() == _uid
                                  and str(u.get("비밀번호", "")) == pwd), None)
                if _urec is not None:
                    st.session_state.app_authenticated = True
                    st.session_state.failed_attempts = 0
                    st.session_state.user_id = _uid
                    st.session_state.user_perms = [p.strip() for p in str(_urec.get("권한", "")).split(",") if p.strip()]
                    st.rerun()
                elif (not _uid) and pwd == app_pwd_db:
                    st.session_state.app_authenticated = True
                    st.session_state.failed_attempts = 0
                    st.session_state.user_id = ""
                    st.session_state.user_perms = None   # 공용 로그인 = 권한 제한 없음(기존 동작)
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
        _mode_opts = [m for m, p in [("견적 작성", "quote"), ("🏪 아쿠나리스", "aqunaris"),
                                     ("관리자 모드", "admin"), ("🇯🇵 일본 수출 분석", "jp")] if aq_can(p)]
        if not _mode_opts: _mode_opts = ["견적 작성"]
        if st.session_state.get("main_sidebar_mode") not in _mode_opts:
            st.session_state["main_sidebar_mode"] = _mode_opts[0]
        mode = st.radio("모드", _mode_opts, key="main_sidebar_mode")  # [V41] 아쿠나리스 추가
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

elif mode == "🏪 아쿠나리스":
    # ==========================================
    # [V41] 아쿠나리스(농협 관수코너) 모드 — Phase A 골격
    #  현황 / 진열 품목 브라우저 / 진열 공급 간이 견적. 전부 읽기 전용(시트 쓰기 없음).
    # ==========================================
    st.header("🏪 아쿠나리스 — 농협 관수코너")
    st.caption("지역농협 자재센터 진열·관리 시스템 (Aqunaris®) · 단가 정본 = Products 시트 · 진열 속성 = AQ_Items 시트")

    aq_items = aq_load_items()
    if not aq_items:
        _rerr = st.session_state.get("_aq_read_err", "")
        if "429" in _rerr or "Quota" in _rerr:
            st.warning("⏳ 구글 시트 분당 읽기 한도(무료 60회/분)를 잠시 초과했습니다. **약 1분 후 [다시 시도]**를 눌러주세요. 데이터는 안전하며, 다른 화면 사용에는 지장 없습니다.")
        else:
            st.warning("AQ_Items 시트를 읽지 못했습니다. Looperget_DB에 AQ_Items 시트가 있는지 확인하세요." + (f" (오류: {_rerr[:120]})" if _rerr else ""))
        if st.button("🔄 다시 시도", key="aq_retry"):
            aq_load_all.clear(); st.rerun()
    else:
        prod_by_code = {str(p.get("code", "")).zfill(5): p for p in st.session_state.db.get("products", [])}
        aq_groups = sorted({(r.get("진열분류") or "(미지정)") for r in aq_items})
        # [V42] 유연 상자 모델: 상자 마스터·수용량 축적 로드
        aq_boxes = aq_load_boxes()
        aq_box_names = [str(b.get("상자종류", "")).strip() for b in aq_boxes]
        aq_box_price = {}
        for _b in aq_boxes:
            _bn = str(_b.get("상자종류", "")).strip()
            try: aq_box_price[_bn] = int(float(str(_b.get("단가") or 0)))
            except Exception: aq_box_price[_bn] = 0
        aq_itembox = aq_load_itembox()
        aq_caps = aq_capacity_map(aq_itembox)

        if st.button("🔄 아쿠나리스 데이터 새로고침", key="aq_refresh"):
            aq_load_all.clear(); st.rerun()

        tab_stat, tab_items, tab_quote, tab_box, tab_site, tab_print = st.tabs(
            ["📊 현황", "🗄️ 진열 품목", "🧮 진열 공급 견적(간이)", "📦 상자·수용량", "🏗️ 사이트 설계", "🖨️ 인쇄물"])

        # ── [V52] 인쇄물 — 스티커·가이드북 자동 생성 (부속군 색상 중심 v2) ──
        with tab_print:
            st.markdown("##### 🖨️ 스티커 · 가이드북 자동 생성")
            st.caption("카드 = **부속군 색 프레임** + [제품명|규격] / [이미지|QR|농협 바코드] / [제품설명] — 섹션/단/열 표기 없음(색상 구분). "
                       "QR = AQ_Items `QR링크`(제품 사용법 쇼츠). [V73] 촬영 트랙 반영분은 실제 영상으로 열리고, "
                       "아직 촬영 안 된 품목만 자리표시로 남습니다 — `python tools/media_ingest.py`로 채웁니다.")
            _pr_bc_sel = st.radio("바코드 체계 (농협 선택)", ["표준바코드 (880 GS1)", "지역바코드 (21 인스토어)"],
                                  horizontal=True, key="aq_pr_bc")
            _pr_bc_mode = "표준" if _pr_bc_sel.startswith("표준") else "지역"
            _pr_img_on = st.checkbox("제품 이미지 포함 (드라이브에서 로드 — 첫 생성은 오래 걸릴 수 있음, 이후 캐시)",
                                     value=True, key="aq_pr_img")
            _pr_imgof = None
            if _pr_img_on:
                _pr_fmap = get_drive_file_map_deep()
                _pr_by_code = {str(r.get("품목코드", "")).strip().zfill(5): r for r in aq_items}
                def _pr_imgof(code, _fm=_pr_fmap, _bc=_pr_by_code):
                    _c9 = str(code).strip().zfill(5)
                    _iso9 = str((_bc.get(_c9, {}) or {}).get("이미지ISO", "") or "").strip()
                    if _iso9:                                   # [V53] ①등각(ISO)/등재 이미지 우선
                        _im9 = _aq_pil_from_any(download_image_by_id(_iso9))
                        if _im9 is not None: return _aq_trim_white(_im9)   # [V54] 흰 여백 크롭
                    _p9 = prod_by_code.get(_c9, {}) or {}       # ②차순위 — 드라이브 코드명/카탈로그 이미지
                    _fid9 = get_best_image_id(code, str(_p9.get("image_data") or _p9.get("image") or ""), _fm)
                    _im9 = _aq_pil_from_any(download_image_by_id(_fid9)) if _fid9 else None
                    return _aq_trim_white(_im9) if _im9 is not None else None

            # ── [V54] 대상 사이트 (스티커·가이드북 공통) — 농협 선택 시 확정 배치 품목·변경된 상자 기준 ──
            _pr_site_opts = ["(전체 품목)"] + [str(s.get("농협명", "")).strip()
                                           for s in aq_load_sites() if str(s.get("농협명", "")).strip()]
            _pr_site = st.selectbox("대상 사이트 — 농협 선택 시 그 농협의 **확정 배치 품목·상자 기준**으로 스티커·가이드북 생성",
                                    _pr_site_opts, key="aq_pr_site")
            _AQ_BOX2ST = {"6호": "80", "3호": "98", "431-1호": "160", "432호": "160"}   # 상자→스티커 용지
            _sp_items, _sp_assign = {}, {}
            if _pr_site != "(전체 품목)":
                for _srow9 in aq_load_sites():
                    if str(_srow9.get("농협명", "")).strip() == _pr_site:
                        try:
                            _pl9 = json.loads(str(_srow9.get("배치JSON") or "{}"))
                            if isinstance(_pl9, dict):
                                _sp_items = _pl9.get("items", {}) if isinstance(_pl9.get("items", {}), dict) else {}
                                _sp_assign = _pl9.get("assign", {}) if isinstance(_pl9.get("assign", {}), dict) else {}
                        except Exception:
                            pass
                if not _sp_assign:
                    st.info(f"'{_pr_site}'에 저장된 확정 배치가 없어 전체 품목 기준으로 동작합니다 — 사이트 설계에서 배치 후 💾 저장하세요.")

            st.markdown("**📦 부품상자 스티커** — 부속군에서 골라 **체크한 품목만** 생성 · 이미지 ①등각(ISO) ②제품 사진")
            st.caption("용지: " + " / ".join(AQ_STICKER_SPEC[s]["label"] for s in ("80", "98", "160"))
                       + " — 기본 = 품목의 **상자** 기준 자동 결정(농협 선택 시 그 농협에 저장된 변경 상자 기준). "
                         "[V59] 아래 표의 **용지 칸을 품목별로 직접 변경**할 수도 있습니다.")
            _pr_targets = []
            for r in aq_items:
                _c9t = str(r.get("품목코드", "")).strip().zfill(5)
                if _sp_assign:   # 농협 확정 배치 품목만 + 사이트의 상자 오버라이드 반영
                    _a9t = _sp_assign.get(_c9t)
                    if not isinstance(_a9t, dict) or str(_a9t.get("rack", "")).startswith("🅥"):
                        continue
                    _bx9 = str((_sp_items.get(_c9t, {}) or {}).get("box") or r.get("기본상자") or "").strip()
                else:
                    _bx9 = str(r.get("기본상자") or "").strip()
                _sz9 = _AQ_BOX2ST.get(_bx9) or (str(r.get("스티커", "")).strip()
                                                if str(r.get("스티커", "")).strip() in AQ_STICKER_SPEC else "")
                if not _sz9:
                    continue
                _pr_targets.append({"품목코드": _c9t, "품목명": str(r.get("품목명_AQ", "") or ""),
                                    "규격": str(r.get("규격_AQ", "") or ""),
                                    "부속군": str(r.get("진열분류", "") or "(미지정)"),
                                    "상자": _bx9 or "-", "용지": AQ_STICKER_SPEC[_sz9]["label"], "_sz": _sz9})
            if not _pr_targets:
                st.info("스티커 대상 품목이 없습니다 — 상자(6호/3호/431-1호/432호) 또는 AQ_Items 스티커 컬럼을 확인하세요.")
            else:
                _pg_all9 = sorted({t["부속군"] for t in _pr_targets})
                _pr_gsel = st.multiselect("부속군 필터", _pg_all9, default=_pg_all9, key=f"aq_pr_gsel_{_pr_site}")
                _view9 = [t for t in _pr_targets if t["부속군"] in (_pr_gsel or _pg_all9)]
                if "aq_pr_pick_ver" not in st.session_state: st.session_state["aq_pr_pick_ver"] = 0
                _pc1, _pc2, _pc3 = st.columns([1, 1, 4])
                if _pc1.button("✅ 전체 선택", key="aq_pr_all"):
                    st.session_state["aq_pr_pick_def"] = True
                    st.session_state["aq_pr_pick_ver"] += 1
                    st.rerun()
                if _pc2.button("⬜ 전체 해제", key="aq_pr_none"):
                    st.session_state["aq_pr_pick_def"] = False
                    st.session_state["aq_pr_pick_ver"] += 1
                    st.rerun()
                if not _view9:
                    st.info("부속군 필터에 해당하는 품목이 없습니다.")
                    df_pick_ed = None
                else:
                    _def9 = st.session_state.get("aq_pr_pick_def", True)
                    _df_pick = pd.DataFrame([{"선택": _def9, **{k: t[k] for k in ("품목코드", "품목명", "규격", "부속군", "상자", "용지")}}
                                             for t in _view9])
                    df_pick_ed = st.data_editor(
                        _df_pick, hide_index=True, height=290,
                        key=f"aq_pr_pick_{_pr_site}_{st.session_state['aq_pr_pick_ver']}",
                        disabled=["품목코드", "품목명", "규격", "부속군", "상자"],
                        column_config={"선택": st.column_config.CheckboxColumn("선택", help="체크한 품목만 스티커 생성"),
                                       "용지": st.column_config.SelectboxColumn(   # [V59] 품목별 라벨(용지) 변경
                                           "용지", options=[AQ_STICKER_SPEC[k]["label"] for k in ("80", "98", "160")],
                                           help="기본 = 상자 기준 자동. 품목별로 다른 라벨 용지로 바꿔 생성할 수 있습니다.")})
                _sel_codes9 = set()
                _sz_of9 = {t["품목코드"]: t["_sz"] for t in _pr_targets}
                if df_pick_ed is not None:
                    _lbl2sz9 = {AQ_STICKER_SPEC[k]["label"]: k for k in AQ_STICKER_SPEC}
                    for _, _row9 in df_pick_ed.iterrows():
                        _c9p = str(_row9["품목코드"]).strip().zfill(5)
                        if bool(_row9["선택"]): _sel_codes9.add(_c9p)
                        _szp9 = _lbl2sz9.get(str(_row9.get("용지") or "").strip())
                        if _szp9: _sz_of9[_c9p] = _szp9   # [V59] 표에서 바꾼 용지 우선
                st.caption(f"선택 {len(_sel_codes9)} / 표시 {len(_view9)} / 대상 {len(_pr_targets)}품목"
                           + (f" · **{_pr_site} 확정 배치 기준**" if _sp_assign else " · 전체 품목 기준"))
                if st.button("🖨️ 선택 품목 스티커 PDF 생성", key="aq_pr_st_go", type="primary"):
                    with st.spinner("스티커 생성 중..."):
                        try:
                            _by_code9 = {str(r.get("품목코드", "")).strip().zfill(5): r for r in aq_items}
                            _outs9 = {}
                            for _s9 in ("80", "98", "160"):
                                _grp9 = [_by_code9[c] for c in sorted(_sel_codes9)
                                         if _sz_of9.get(c) == _s9 and c in _by_code9]
                                if _grp9:
                                    _outs9[_s9] = (aq_sticker_pdf_bytes(_grp9, _s9, _pr_bc_mode, _pr_imgof), len(_grp9))
                            st.session_state["aq_pr_st_out"] = _outs9
                            if not _outs9:
                                st.warning("선택된 품목이 없습니다 — 체크박스를 확인하세요.")
                        except Exception as e:
                            st.error(f"스티커 생성 실패: {aq_err_str(e)}")
            for _s9, (_b9, _n9) in (st.session_state.get("aq_pr_st_out") or {}).items():
                st.download_button(f"⬇️ {AQ_STICKER_SPEC[_s9]['label']} — {_n9}품목 ({len(_b9) // 1024}KB)", data=_b9,
                                   file_name=f"{AQ_STICKER_SPEC[_s9]['fname']}_{datetime.date.today().strftime('%Y%m%d')}.pdf",
                                   mime="application/pdf", key=f"aq_pr_st_dl_{_s9}")

            st.markdown("---")
            st.markdown("**📖 농협 맞춤 가이드북** — 표지 + **목차(2p)** + **부속군 색상 색인(3p)** + **배치도 펼침면(4·5p~)** + 군별 품목 카드 (위 대상 사이트 기준)")
            st.caption("🗺 [V71] 농협을 고르면 그 농협의 **저장된 배치도가 4페이지부터 펼침면으로** 들어갑니다 — "
                       "펼치면 **왼쪽 면 위 1·2·3 / 오른쪽 면 위 4·5·6 / 왼쪽 아래 7·8·9 / 오른쪽 아래 10·11·12**, "
                       "페이지당 6섹션이고 12섹션이 넘으면 다음 장으로 이어집니다(가상랙 제외). "
                       "표지를 뺀 모든 페이지는 **짝수는 왼쪽·홀수는 오른쪽으로 5mm** 밀어 인쇄해, 책자로 묶었을 때 가운데가 가려지지 않습니다.")
            if st.button("📖 가이드북 PDF 생성", key="aq_pr_gb_go"):
                with st.spinner("가이드북 생성 중..."):
                    try:
                        st.session_state.pop("_aq_gb_layout_note", None)
                        _gb_b, _gb_n, _gb_asg = aq_guidebook_pdf_bytes(aq_items, _pr_site, _pr_bc_mode, _pr_imgof)
                        st.session_state["aq_pr_gb_out"] = (_gb_b, _pr_site, _gb_n, _gb_asg, _pr_bc_mode)
                    except Exception as e:
                        st.error(f"가이드북 생성 실패: {aq_err_str(e)}")
            if st.session_state.get("_aq_gb_layout_note"):   # [V69] 배치도 페이지 생략 사유 노출(조용히 넘어가지 않음)
                st.info(st.session_state["_aq_gb_layout_note"])
            _gb9 = st.session_state.get("aq_pr_gb_out")
            if _gb9:
                st.caption(f"{_gb9[1]} · {_gb9[2]}품목 · {'확정 배치 기준' if _gb9[3] else '진열분류 전체 기준'} · {_gb9[4]}바코드")
                st.download_button(f"⬇️ 가이드북 PDF ({len(_gb9[0]) // 1024}KB)", data=_gb9[0],
                                   file_name=f"가이드북_{_gb9[1]}_{_gb9[4]}_{datetime.date.today().strftime('%Y%m%d')}.pdf",
                                   mime="application/pdf", key="aq_pr_gb_dl")

        # ── 현황 ─────────────────────────────────────────
        with tab_stat:
            st.markdown("##### 🏢 설치 농협 (AQ_Sites)")
            aq_sites = aq_load_sites()
            if aq_sites:
                df_sites = pd.DataFrame(aq_sites)
                cols_show = [c for c in ["농협ID", "농협명", "지역", "상태", "설치일", "비고"] if c in df_sites.columns]
                st.dataframe(df_sites[cols_show].astype(str), hide_index=True)
            else:
                st.info("등록된 농협이 없습니다. (AQ_Sites 시트)")

            st.markdown("##### 📦 진열 품목 DB 요약 (AQ_Items)")
            n_loc = sum(1 for r in aq_items if r.get("섹션"))
            n_88 = sum(1 for r in aq_items if str(r.get("표준바코드", "")).strip())
            n_link = sum(1 for r in aq_items if r["품목코드"] in prod_by_code)
            m1, m2, m3, m4, m5 = st.columns(5)
            m1.metric("품목 수", f"{len(aq_items)}")
            m2.metric("위치 지정", f"{n_loc}")
            m3.metric("88바코드 보유", f"{n_88}")
            m4.metric("Products 연결", f"{n_link}")
            m5.metric("수용량 기록", f"{len(aq_itembox)}건")  # [V42] 축적 현황
            if n_link < len(aq_items):
                miss = [r["품목코드"] for r in aq_items if r["품목코드"] not in prod_by_code]
                st.warning(f"Products에 없는 코드 {len(miss)}건: {', '.join(miss[:10])}{' 외' if len(miss) > 10 else ''}")

            cnt_g = {}
            for r in aq_items:
                g = r.get("진열분류") or "(미지정)"
                cnt_g[g] = cnt_g.get(g, 0) + 1
            cnt_b = {}
            for r in aq_items:
                b = str(r.get("기본상자", "")).strip() or "(미지정)"
                cnt_b[b] = cnt_b.get(b, 0) + 1
            c_g, c_b = st.columns(2)
            with c_g:
                st.caption("진열분류별 품목수")
                st.dataframe(pd.DataFrame(sorted(cnt_g.items(), key=lambda x: -x[1]), columns=["진열분류", "품목수"]), hide_index=True)
            with c_b:
                st.caption("기본상자별 품목수 (기본값 기준 — 실제 배치는 사이트별 조정)")
                st.dataframe(pd.DataFrame(sorted(cnt_b.items(), key=lambda x: -x[1]), columns=["기본상자", "품목수"]), hide_index=True)

        # ── 진열 품목 브라우저 ────────────────────────────
        with tab_items:
            # [V60] 사이트 선택 — 표준(AQ_Items 정본) 외에 저장된 농협·표준v2 등 어느 사이트의 배치든 조회
            _ib_site_opts = ["(표준 — AQ_Items 섹션·단·열)"] + [str(s.get("농협명", "")).strip()
                                                          for s in aq_load_sites() if str(s.get("농협명", "")).strip()]
            # [V69] 사이트 설계 '진열 품목 상세 보기' → 그 농협 기준으로 자동 설정(위젯 생성 전에만 가능)
            if st.session_state.get("_aq_items_jump"):
                _ij9 = st.session_state.pop("_aq_items_jump")
                if _ij9 in _ib_site_opts:
                    st.session_state["aq_items_site"] = _ij9   # '배치된 품목만' 체크는 배치 유무로 자동 기본값
            if st.session_state.pop("_aq_items_tabjump", False):   # 탭도 함께 전환(부모 문서 탭 버튼 클릭)
                import streamlit.components.v1 as _cmp9
                _cmp9.html(   # ⚠ Streamlit 탭은 <button>이 아니라 role="tab" DIV — 태그로 좁히면 못 찾는다
                    "<script>(function(){var n=0;var t=setInterval(function(){try{"
                    "var bs=window.parent.document.querySelectorAll('[role=\"tab\"]');"
                    "for(var i=0;i<bs.length;i++){if((bs[i].innerText||'').indexOf('진열 품목')>-1){"
                    "bs[i].click();clearInterval(t);return;}}}catch(e){}"
                    "if(++n>24)clearInterval(t);},250);})();</script>", height=0)
            c_f0, c_f1, c_f2 = st.columns([2, 1.4, 2.6])
            with c_f0:
                _ib_site = st.selectbox("배치 기준 사이트", _ib_site_opts, key="aq_items_site",
                                        help="농협(또는 표준v2 등 저장 사이트)을 고르면 그 사이트에 저장된 배치·상자 기준으로 표시합니다.")
            with c_f1:
                aq_g_sel = st.selectbox("진열분류", ["전체"] + aq_groups, key="aq_grp_sel")
            with c_f2:
                aq_kw = st.text_input("검색 (코드/품목명/규격)", key="aq_kw")
            _ib_assign, _ib_items = {}, {}
            if not _ib_site.startswith("(표준"):
                for _srow0 in aq_load_sites():
                    if str(_srow0.get("농협명", "")).strip() == _ib_site:
                        try:
                            _pl0 = json.loads(str(_srow0.get("배치JSON") or "{}"))
                            if isinstance(_pl0, dict):
                                _ib_assign = _pl0.get("assign", {}) if isinstance(_pl0.get("assign", {}), dict) else {}
                                _ib_items = _pl0.get("items", {}) if isinstance(_pl0.get("items", {}), dict) else {}
                        except Exception:
                            pass
                if not _ib_assign:
                    st.info(f"'{_ib_site}'에 저장된 확정 배치가 없습니다 — 표준 위치 컬럼으로 표시합니다. (사이트 설계에서 배치 후 💾 저장)")
            _ib_only = st.checkbox("배치된 품목만 보기", value=bool(_ib_assign), key="aq_items_only",
                                   disabled=not _ib_assign) if not _ib_site.startswith("(표준") else False
            rows_view = []
            for r in aq_items:
                if aq_g_sel != "전체" and (r.get("진열분류") or "(미지정)") != aq_g_sel:
                    continue
                hay = f"{r['품목코드']} {r.get('품목명_AQ', '')} {r.get('규격_AQ', '')}".lower()
                if aq_kw and aq_kw.strip() and aq_kw.strip().lower() not in hay:
                    continue
                p = prod_by_code.get(r["품목코드"], {})
                _a0 = _ib_assign.get(r["품목코드"]) if _ib_assign else None
                if _ib_only and not isinstance(_a0, dict):
                    continue
                if isinstance(_a0, dict):   # [V60] 사이트 저장 배치 기준 위치·상자
                    loc = f"{_a0.get('rack', '')}-단{_a0.get('shelf', '')}" + (f"×{_a0.get('n')}" if int(_a0.get("n", 1) or 1) > 1 else "")
                    _bx0 = str((_ib_items.get(r["품목코드"], {}) or {}).get("box") or r.get("기본상자") or "")
                else:
                    loc = "-".join(str(x) for x in [r.get("섹션", ""), r.get("단", ""), r.get("열", "")] if str(x).strip())
                    if _ib_assign: loc = ""   # 사이트 기준인데 미배치 → 빈칸
                    _bx0 = str(r.get("기본상자", "") or "")
                rows_view.append({
                    "품목코드": r["품목코드"], "품목명": str(r.get("품목명_AQ", "") or ""), "규격": str(r.get("규격_AQ", "") or ""),
                    "진열분류": str(r.get("진열분류", "") or ""),
                    ("배치(랙-단)" if _ib_assign else "위치(섹션-단-열)"): loc,
                    "상자": _bx0, "기본수량": str(r.get("기본수량", "") or ""),
                    "수용기록": len(aq_caps.get(r["품목코드"], {})),
                    "스티커": str(r.get("스티커", "") or ""), "지역농협가": str(p.get("price_nh_loc", "") or ""),
                    "소비자가": str(p.get("price_cons", "") or ""), "계통등록": str(r.get("계통등록", "") or ""),
                    "상태": str(r.get("상태", "") or ""),
                })
            st.caption(f"표시 {len(rows_view)}개 품목 · 기준 = {_ib_site}"
                       + (" (저장 배치·사이트 상자 반영)" if _ib_assign else " (AQ_Items 표준 위치)")
                       + " · 매입가 미표시 · 수용기록=축적된 상자별 수용량 데이터 수")
            st.dataframe(pd.DataFrame(rows_view), hide_index=True, height=480)

            # ── [V61] Looperget_DB 절대값(대표님 승인 2026-07-23) — Products에서 진열 품목 추가(흡수 1단계) ──
            with st.expander("➕ 진열 품목 추가 — Looperget_DB(Products)에서", expanded=False):
                st.caption("품목 정본은 **Looperget_DB(Products)** 입니다. 여기서 고른 품목이 진열 속성(AQ_Items)에 등재되어 "
                           "부속군 색·사이트 배치·스티커 대상이 됩니다. 상자·수용량은 등재 후 📦 상자·수용량 탭에서 보강하세요.")
                _ex_codes61 = {str(r.get("품목코드", "")).strip().zfill(5) for r in aq_items}
                _cand61 = [p for p in st.session_state.db.get("products", [])
                           if str(p.get("code", "")).strip()
                           and str(p.get("code", "")).strip().zfill(5) not in _ex_codes61]
                _kw61 = st.text_input("Products 검색 (코드/이름/규격)", key="aq_addp_kw")
                if _kw61.strip():
                    _k61 = _kw61.strip().lower()
                    _cand61 = [p for p in _cand61
                               if _k61 in f"{p.get('code', '')} {p.get('name', '')} {p.get('spec', '')}".lower()]
                st.caption(f"추가 가능 {len(_cand61)}개 (이미 등재된 {len(_ex_codes61)}개 제외 · 표시 최대 300)")
                _by61 = {str(p.get("code", "")).zfill(5): p for p in _cand61}
                _opts61 = [f"{str(p.get('code', '')).zfill(5)} | {p.get('name', '')} {p.get('spec', '')}".strip()
                           for p in _cand61[:300]]
                _sel61 = st.multiselect("추가할 품목", _opts61, key="aq_addp_sel")
                _c61a, _c61b = st.columns(2)
                with _c61a:
                    _grp61 = st.selectbox("부속군(진열분류)", [g for g in AQ_GROUP_COLORS if g != "(미지정)"],
                                          key="aq_addp_grp")
                with _c61b:
                    _box61 = st.selectbox("기본상자 (빈칸 = 자유배치로 진열)", [""] + [b for b in aq_box_names if b],
                                          key="aq_addp_box")
                if _sel61 and st.button(f"➕ {len(_sel61)}개 품목 등재", key="aq_addp_go", type="primary"):
                    try:
                        ws61 = _aq_sh().worksheet("AQ_Items")
                        hdr61 = ws61.row_values(1)
                        _rows61 = []
                        for _s61 in _sel61:
                            _cd61 = _s61.split("|")[0].strip()
                            _p61 = _by61.get(_cd61, {})
                            _d61 = {"품목코드": _cd61, "품목명_AQ": str(_p61.get("name", "") or ""),
                                    "규격_AQ": str(_p61.get("spec", "") or ""), "진열분류": _grp61,
                                    "기본상자": _box61,
                                    "비고": f"Products에서 추가 {datetime.date.today().isoformat()}"}
                            _rows61.append([str(_d61.get(h, "")) for h in hdr61])
                        ws61.append_rows(_rows61, value_input_option="RAW")
                        aq_load_all.clear()
                        st.success(f"{len(_rows61)}개 등재 완료 — 부속군 '{_grp61}'")
                        time.sleep(0.5); st.rerun()
                    except Exception as _e61:
                        st.error(f"등재 실패: {aq_err_str(_e61)}")

            # ── [V48] 품목 이미지 2종 체계 — 빌더용(기존 유지)과 등각(ISO: 현장 시연·가이드북·스티커용) ──
            with st.expander("🖼️ 품목 이미지 관리 — 등각(ISO) 등록·미리보기", expanded=False):
                st.caption("빌더용 이미지(2D 배치용)는 기존 관리자 모드에서 그대로 관리합니다. 여기서는 현장 시연·가이드북·스티커 자동생성용 **등각(isometric) 이미지**를 품목별로 추가 등록합니다. (드라이브 파일명 `코드_iso` — 기존 이미지 해석과 충돌 없음)")
                _iso_opts = [f"{r['품목코드']} | {r.get('품목명_AQ', '')} {r.get('규격_AQ', '')}".strip() for r in aq_items]
                _iso_sel = st.selectbox("품목 선택", _iso_opts, key="aq_iso_item")
                _iso_code = _iso_sel.split("|")[0].strip()
                _iso_rec = next((r for r in aq_items if r["품목코드"] == _iso_code), {})
                ci1, ci2 = st.columns(2)
                with ci1:
                    st.markdown("**등각(ISO) 이미지 — 시연·인쇄물용**")
                    _iso_id = str(_iso_rec.get("이미지ISO", "") or "").strip()
                    if _iso_id:
                        try:
                            _img_iso = download_image_by_id(_iso_id)
                            if _img_iso is not None:
                                st.image(_img_iso, width=260)
                            else:
                                st.info("이미지 로드 실패 — 드라이브 파일 확인")
                        except Exception as _e9:
                            st.info(f"이미지 로드 실패: {aq_err_str(_e9)}")
                    else:
                        st.info("등각 이미지 미등록")
                with ci2:
                    st.markdown("**빌더용(기존) 이미지 — 2D 배치용**")
                    _pb = prod_by_code.get(_iso_code, {})
                    _bld_id = str(_pb.get("image", "") or "")
                    if len(_bld_id) > 10:
                        try:
                            _img_b = download_image_by_id(_bld_id)
                            if _img_b is not None:
                                st.image(_img_b, width=260)
                            else:
                                st.caption("등록됨 (미리보기 실패)")
                        except Exception:
                            st.caption("등록됨 (미리보기 실패)")
                    else:
                        st.caption("Products 이미지데이터 기준 미등록 (드라이브 파일명 매칭분은 별도)")
                _up = st.file_uploader("등각 이미지 업로드 (JPG/PNG)", type=["jpg", "jpeg", "png"], key="aq_iso_up")
                if _up is not None and st.button("⬆️ 등각 이미지 등록", key="aq_iso_save", type="primary"):
                    try:
                        _ext = "png" if str(_up.type).endswith("png") else "jpg"
                        _fid = upload_bytes_to_drive(_up.getvalue(), f"{_iso_code}_iso.{_ext}",
                                                     mimetype=_up.type or "image/jpeg")
                        if not _fid:
                            st.error("드라이브 업로드 실패 — 잠시 후 재시도")
                        else:
                            aq_update_item_cell(_iso_code, "이미지ISO", _fid)
                            aq_load_all.clear()
                            st.success(f"{_iso_code} 등각 이미지 등록 완료")
                            time.sleep(0.5); st.rerun()
                    except Exception as _e8:
                        st.error(f"등록 실패: {aq_err_str(_e8)}")

        # ── 진열 공급 간이 견적 ───────────────────────────
        with tab_quote:
            st.caption("선택한 진열분류를 '기본상자·기본수량(폴백 기본값)'으로 채우는 초도 공급 견적 미리보기. 단가 = Products 지역농협가, 계통2(5%) 수수료는 참고 표시. 사이트별 상자·수량 조정은 🏗️ 사이트 설계 탭에서.")
            aq_q_groups = st.multiselect("진열분류 선택", aq_groups, key="aq_q_groups")
            with st.expander("📦 상자(하드웨어) 단가 — AQ_Boxes 시트값, 필요 시 임시 조정", expanded=False):
                aq_box_prices = {}
                if aq_box_names:
                    _cols_bx = st.columns(min(len(aq_box_names), 4))
                    for _i, _bn in enumerate(aq_box_names):
                        with _cols_bx[_i % len(_cols_bx)]:
                            aq_box_prices[_bn] = st.number_input(
                                _bn, value=int(aq_box_price.get(_bn, 0)), step=100, key=f"aq_bxp_{_bn}")
                else:
                    st.info("등록된 상자가 없습니다. '📦 상자·수용량' 탭에서 추가하세요.")
                aq_inc_box = st.checkbox("상자 하드웨어 포함", value=True, key="aq_inc_box")
            if not aq_q_groups:
                st.info("진열분류를 1개 이상 선택하면 견적이 계산됩니다.")
            else:
                det_rows, skipped = [], []
                parts_sum = 0.0
                box_cnt = {}
                for r in aq_items:
                    if (r.get("진열분류") or "(미지정)") not in aq_q_groups:
                        continue
                    p = prod_by_code.get(r["품목코드"])
                    try: q_fill = int(float(str(r.get("기본수량") or 0)))
                    except Exception: q_fill = 0
                    try: unit = float(p.get("price_nh_loc") or 0) if p else 0.0
                    except Exception: unit = 0.0
                    if q_fill <= 0 or unit <= 0:
                        skipped.append(r["품목코드"]); continue
                    amt = unit * q_fill
                    parts_sum += amt
                    bx = str(r.get("기본상자", "")).strip()
                    if bx: box_cnt[bx] = box_cnt.get(bx, 0) + 1
                    det_rows.append({
                        "품목코드": r["품목코드"], "품목명": str(r.get("품목명_AQ", "") or ""), "규격": str(r.get("규격_AQ", "") or ""),
                        "상자": bx, "수량": q_fill, "지역농협가": int(unit), "금액": int(amt),
                    })
                box_sum = sum(aq_box_prices.get(b, 0) * n for b, n in box_cnt.items()) if aq_inc_box else 0
                fee2 = parts_sum * 0.05
                q1, q2, q3, q4 = st.columns(4)
                q1.metric("부속 합계", f"{parts_sum:,.0f}원")
                q2.metric("상자 하드웨어", f"{box_sum:,.0f}원")
                q3.metric("공급 합계", f"{parts_sum + box_sum:,.0f}원")
                q4.metric("계통2 수수료(참고)", f"-{fee2:,.0f}원")
                if box_cnt:
                    st.caption("상자 구성: " + ", ".join(f"{b}×{n}" for b, n in sorted(box_cnt.items())))
                if skipped:
                    st.warning(f"단가/수량 미비로 제외 {len(skipped)}건: {', '.join(skipped[:10])}{' 외' if len(skipped) > 10 else ''}")
                if det_rows:
                    df_det = pd.DataFrame(det_rows)
                    st.dataframe(df_det, hide_index=True, height=420)
                    st.download_button(
                        "⬇️ 간이 견적 CSV 다운로드",
                        df_det.to_csv(index=False).encode("utf-8-sig"),
                        file_name="aqunaris_진열공급_간이견적.csv", mime="text/csv",
                        key="aq_csv_dl",
                    )

        # ── [V42] 상자·수용량 — 유연 상자 모델의 축적 UI ─────────
        with tab_box:
            st.caption("품목↔상자 매핑은 고정이 아닙니다. 농협 상황·랙 크기에 따라 상자가 바뀌고 새 상자가 추가됩니다. '어떤 부속이 어떤 상자에 얼마나 담기는지'를 여기서 계속 축적하세요.")
            c_bm, c_add = st.columns([3, 2])
            with c_bm:
                st.markdown("##### 📦 상자 마스터 (AQ_Boxes) — 표에서 직접 수정")
                # [V43] 치수는 배치 방향 판정의 기초: 세로(표준)=단 깊이≥상자 깊이 / 가로=단 깊이≥상자 폭
                st.caption("치수(폭·깊이)를 채우면 배치 판정에 사용됩니다 — **세로**(표준) 배치는 단 깊이 ≥ 상자 깊이, **가로** 배치는 단 깊이 ≥ 상자 폭. "
                           "[V50] **셀을 고쳐 '상자 정보 저장'을 누르면 반영**됩니다(치수 실측값 입력·단가 변경 등). 상자 **이름 변경은 아래 '✏️ 상자 이름 변경'**(참조처 연쇄 반영).")
                if aq_boxes:
                    _bx_cols = [c for c in ["상자종류", "폭mm", "깊이mm", "높이mm", "단가", "상태", "비고"]
                                if any(c in b for b in aq_boxes)]
                    _df_bx_in = pd.DataFrame([{c: b.get(c, "") for c in _bx_cols} for b in aq_boxes])
                    for _c in ["폭mm", "깊이mm", "높이mm", "단가"]:
                        if _c in _df_bx_in.columns:
                            _df_bx_in[_c] = pd.to_numeric(_df_bx_in[_c], errors="coerce")
                    df_bx_ed = st.data_editor(
                        _df_bx_in, hide_index=True, key="aq_box_ed",
                        disabled=["상자종류"],
                        column_config={
                            "상자종류": st.column_config.TextColumn("상자종류", help="이름 변경은 아래 '상자 이름 변경' 사용 — 참조처까지 함께 바꿔야 안전합니다"),
                            "폭mm": st.column_config.NumberColumn(format="%d", min_value=0),
                            "깊이mm": st.column_config.NumberColumn(format="%d", min_value=0),
                            "높이mm": st.column_config.NumberColumn(format="%d", min_value=0),
                            "단가": st.column_config.NumberColumn(format="%d", min_value=0),
                        })
                    if st.button("💾 상자 정보 저장", type="primary", key="aq_box_save"):
                        try:
                            _out_bx = []
                            for _i, _b in enumerate(aq_boxes):
                                _row = dict(_b)                      # 등록일 등 미표시 컬럼 보존
                                if _i < len(df_bx_ed):
                                    _ed = df_bx_ed.iloc[_i]
                                    for _c in _bx_cols:
                                        if _c == "상자종류": continue
                                        _v = _ed.get(_c)
                                        if _v is None or (isinstance(_v, float) and pd.isna(_v)):
                                            _row[_c] = ""
                                        elif _c in ("폭mm", "깊이mm", "높이mm", "단가"):
                                            _row[_c] = int(_v)
                                        else:
                                            _row[_c] = str(_v)
                                _out_bx.append(_row)
                            aq_save_ws("AQ_Boxes", _out_bx)
                            aq_load_all.clear()
                            st.success(f"상자 {len(_out_bx)}건 저장 완료"); time.sleep(0.5); st.rerun()
                        except Exception as e:
                            st.error(f"저장 실패: {aq_err_str(e)}")
                else:
                    st.info("등록된 상자가 없습니다.")
            with c_add:
                st.markdown("##### ➕ 새 상자 등록")
                with st.form("aq_box_add_form", clear_on_submit=True):
                    nb_name = st.text_input("상자종류(이름) *", help="예: 5호, 대형-A, ○○농협 전용상자")
                    cnb1, cnb2, cnb3 = st.columns(3)
                    nb_w = cnb1.number_input("폭mm", value=0, step=10)
                    nb_d = cnb2.number_input("깊이mm", value=0, step=10)
                    nb_h = cnb3.number_input("높이mm", value=0, step=10)
                    nb_price = st.number_input("단가(원)", value=0, step=100)
                    nb_memo = st.text_input("비고", help="예: ○○농협 기존 랙용")
                    if st.form_submit_button("상자 등록", type="primary"):
                        _nm = nb_name.strip()
                        if not _nm:
                            st.error("상자 이름을 입력하세요.")
                        elif _nm in aq_box_names:
                            st.error(f"'{_nm}' 은 이미 등록된 상자입니다.")
                        else:
                            try:
                                aq_append_row("AQ_Boxes", [_nm, nb_w or "", nb_d or "", nb_h or "",
                                                           nb_price or "", "신규",
                                                           datetime.datetime.now().strftime("%Y-%m-%d"), nb_memo])
                                aq_load_all.clear()
                                st.success(f"'{_nm}' 등록 완료"); time.sleep(0.5); st.rerun()
                            except Exception as e:
                                st.error(f"등록 실패: {aq_err_str(e)}")

            # [V50] 상자 이름 변경 — 참조처(품목 기본상자·수용량 기록·사이트 배치)까지 연쇄 반영
            with st.expander("✏️ 상자 이름 변경 (참조처 연쇄 반영)", expanded=False):
                st.caption("이름만 바꾸면 품목의 기본상자·수용량 기록·사이트 배치가 옛 이름을 가리켜 배치가 깨집니다. "
                           "여기서 바꾸면 **AQ_Boxes·AQ_Items(기본상자)·AQ_ItemBox·AQ_Sites(배치JSON)를 한 번에** 고칩니다.")
                if aq_box_names:
                    _rn1, _rn2 = st.columns(2)
                    _rn_old = _rn1.selectbox("현재 이름", aq_box_names, key="aq_box_rn_old")
                    _rn_new = _rn2.text_input("새 이름", key="aq_box_rn_new")
                    _n_it = sum(1 for r in aq_items if str(r.get("기본상자", "")).strip() == _rn_old)
                    _n_ib = sum(1 for r in aq_itembox if str(r.get("상자종류", "")).strip() == _rn_old)
                    st.caption(f"'{_rn_old}' 참조 현황 — 품목 기본상자 {_n_it}건 · 수용량 기록 {_n_ib}건 (+ 사이트 배치JSON은 실행 시 집계)")
                    if st.button("이름 변경 실행", key="aq_box_rn_go"):
                        _nn = (_rn_new or "").strip()
                        if not _nn:
                            st.error("새 이름을 입력하세요.")
                        elif _nn == _rn_old:
                            st.error("현재 이름과 같습니다.")
                        elif _nn in aq_box_names:
                            st.error(f"'{_nn}' 은 이미 있는 상자입니다. (합치려면 수용량 기록의 상자를 개별 변경하세요)")
                        else:
                            try:
                                _res = aq_rename_box(_rn_old, _nn)
                                aq_load_all.clear()
                                st.success(f"'{_rn_old}' → '{_nn}' 변경 완료 — "
                                           + " · ".join(f"{k} {v}건" for k, v in _res.items()))
                                time.sleep(0.8); st.rerun()
                            except Exception as e:
                                st.error(f"이름 변경 실패: {aq_err_str(e)}")
                else:
                    st.info("등록된 상자가 없습니다.")

            st.divider()
            st.markdown("##### 📝 수용량 기록 추가 — 품목이 이 상자에 몇 개 담기는가")
            _opt_items = [f"{r['품목코드']} | {r.get('품목명_AQ', '')} {r.get('규격_AQ', '')}".strip() for r in aq_items]
            with st.form("aq_cap_add_form", clear_on_submit=True):
                cf1, cf2 = st.columns([3, 2])
                with cf1:
                    cap_item_lbl = st.selectbox("품목", _opt_items)
                with cf2:
                    cap_box = st.selectbox("상자", aq_box_names if aq_box_names else ["(상자 먼저 등록)"])
                cf3, cf4, cf5 = st.columns(3)
                cap_qty = cf3.number_input("수용수량 *", value=0, step=10, min_value=0)
                cap_basis = cf4.selectbox("근거", ["실측", "추정", "카탈로그"])
                cap_src = cf5.text_input("출처", help="예: 부발농협 설치, 창고 실측")
                cap_memo = st.text_input("비고", key="aq_cap_memo")
                if st.form_submit_button("수용량 기록 추가", type="primary"):
                    if cap_qty <= 0:
                        st.error("수용수량을 입력하세요.")
                    elif not aq_box_names:
                        st.error("상자를 먼저 등록하세요.")
                    else:
                        try:
                            _code = cap_item_lbl.split("|")[0].strip()
                            aq_append_row("AQ_ItemBox", [_code, cap_box, int(cap_qty), cap_basis, cap_src,
                                                         datetime.datetime.now().strftime("%Y-%m-%d"), cap_memo])
                            aq_load_all.clear()
                            st.success(f"{_code} × {cap_box} = {int(cap_qty)}개 기록 완료"); time.sleep(0.5); st.rerun()
                        except Exception as e:
                            st.error(f"기록 실패: {aq_err_str(e)}")

            # [V50] 수용량 기록 수정·삭제 — 잘못 기록된 수량·근거·상자를 고칠 수 있어야 한다
            with st.expander(f"🛠 수용량 기록 수정·삭제 (총 {len(aq_itembox)}건)", expanded=False):
                st.caption("셀을 고치거나 행을 지운 뒤 **'기록 저장'**을 누르면 반영됩니다. 같은 품목×상자 기록이 여럿이면 **뒤(나중) 기록이 우선** 적용됩니다. "
                           "품목코드는 잠금(잘못된 매칭 방지) — 품목을 바꾸려면 지우고 위 폼에서 새로 추가하세요. 저장 시 빈 행은 정리됩니다.")
                _nm_by_code = {r["품목코드"]: str(r.get("품목명_AQ", "") or "") for r in aq_items}
                _ib_all = []
                for _i, _r in enumerate(aq_itembox):
                    _ib_all.append({
                        "행": _i, "품목코드": _r["품목코드"], "품목명": _nm_by_code.get(_r["품목코드"], ""),
                        "상자종류": str(_r.get("상자종류", "") or ""),
                        "수용수량": pd.to_numeric(_r.get("수용수량"), errors="coerce"),
                        "근거": str(_r.get("근거", "") or ""), "출처": str(_r.get("출처", "") or ""),
                        "비고": str(_r.get("비고", "") or ""),
                    })
                _fb1, _fb2 = st.columns([2, 3])
                _f_box = _fb1.selectbox("상자 필터", ["(전체)"] + aq_box_names, key="aq_ib_fbox")
                _f_q = _fb2.text_input("품목 검색 (코드·품명)", key="aq_ib_fq").strip()
                _ib_view = [r for r in _ib_all
                            if (_f_box == "(전체)" or r["상자종류"] == _f_box)
                            and (not _f_q or _f_q in r["품목코드"] or _f_q in r["품목명"])]
                if not _ib_view:
                    st.info("조건에 맞는 기록이 없습니다.")
                else:
                    _basis_opts = sorted({r["근거"] for r in _ib_all if r["근거"]} | {"실측", "추정", "카탈로그", "표준설치"})
                    df_ib_ed = st.data_editor(
                        pd.DataFrame(_ib_view), hide_index=True, height=330, num_rows="dynamic",
                        key=f"aq_ib_ed_{_f_box}_{_f_q}",
                        disabled=["행", "품목코드", "품목명"],
                        column_config={
                            "행": st.column_config.NumberColumn("행", format="%d", help="원본 행 번호(수정 위치 추적용)"),
                            "상자종류": st.column_config.SelectboxColumn("상자종류", options=aq_box_names or [""]),
                            "수용수량": st.column_config.NumberColumn(format="%d", min_value=0),
                            "근거": st.column_config.SelectboxColumn("근거", options=_basis_opts),
                        })
                    if st.button("💾 기록 저장 (수정·삭제 반영)", type="primary", key="aq_ib_save"):
                        try:
                            _ed_by_row, _new_rows = {}, []
                            for _, _er in df_ib_ed.iterrows():
                                _rn = _er.get("행")
                                if _rn is None or (isinstance(_rn, float) and pd.isna(_rn)):
                                    _new_rows.append(_er); continue      # 표에서 추가한 행(코드 없음) → 무시
                                _ed_by_row[int(_rn)] = _er
                            _view_rows = {r["행"] for r in _ib_view}
                            _kept = _view_rows & set(_ed_by_row)
                            _deleted = _view_rows - _kept
                            _out_ib = []
                            for _i, _r in enumerate(aq_itembox):
                                if _i in _deleted: continue
                                _row = dict(_r)
                                if _i in _ed_by_row:
                                    _er = _ed_by_row[_i]
                                    _qv = _er.get("수용수량")
                                    if _qv is None or (isinstance(_qv, float) and pd.isna(_qv)):
                                        _row["수용수량"] = ""
                                    else:
                                        _row["수용수량"] = int(_qv)
                                    for _c in ("상자종류", "근거", "출처", "비고"):
                                        _v = _er.get(_c)
                                        _row[_c] = "" if (_v is None or (isinstance(_v, float) and pd.isna(_v))) else str(_v)
                                _out_ib.append(_row)
                            aq_save_ws("AQ_ItemBox", _out_ib)
                            aq_load_all.clear()
                            _msg = f"수용량 기록 저장 완료 — {len(_out_ib)}건 유지"
                            if _deleted: _msg += f" · {len(_deleted)}건 삭제"
                            if len(_new_rows): _msg += f" · 표에서 추가한 {len(_new_rows)}행은 무시(위 폼으로 추가)"
                            st.success(_msg); time.sleep(0.8); st.rerun()
                        except Exception as e:
                            st.error(f"저장 실패: {aq_err_str(e)}")

            c_v1, c_v2 = st.columns(2)
            with c_v1:
                st.markdown("##### 🔎 품목별 수용량 조회")
                _q_item = st.selectbox("품목 선택", _opt_items, key="aq_cap_view_item")
                _q_code = _q_item.split("|")[0].strip()
                _caps = aq_caps.get(_q_code, {})
                if _caps:
                    st.dataframe(pd.DataFrame(
                        [{"상자": b, "수용수량": q, "근거": s} for b, (q, s) in _caps.items()]), hide_index=True)
                else:
                    st.info("이 품목의 수용량 기록이 아직 없습니다.")
            with c_v2:
                st.markdown("##### 🕘 최근 기록")
                if aq_itembox:
                    _recent = aq_itembox[-15:][::-1]
                    st.dataframe(pd.DataFrame(_recent).astype(str), hide_index=True, height=280)
                else:
                    st.info("기록이 없습니다.")

        # ── [V42] 사이트 설계 (Phase B-1) — 농협별 랙 구성·진열 계획·견적 ──
        with tab_site:
            aq_sites_all = aq_load_sites()
            st.markdown("##### 🏢 농협(사이트) 선택")
            _site_names = [str(s.get("농협명", "")).strip() for s in aq_sites_all]
            # [V44] 표준 불러오기 후 자동 선택 점프 (위젯 생성 전에만 키 설정 가능)
            if st.session_state.get("_aq_site_jump"):
                _jump = st.session_state.pop("_aq_site_jump")
                if _jump in _site_names:
                    st.session_state["aq_site_sel"] = _jump
            # [V69] 표준 시스템을 목록 맨 위·강조 표시 — 표준은 계속 다듬어 나가는 '살아있는 기준'이다.
            _has_std9 = AQ_STD_SITE in _site_names
            _opts9 = (["(신규 등록)"] + ([AQ_STD_SITE] if _has_std9 else [])
                      + [n for n in _site_names if n != AQ_STD_SITE])
            def _site_fmt9(n):
                return f"⭐ {n} — 기준 시스템" if n == AQ_STD_SITE else n
            c_sel, c_std = st.columns([3, 2])
            with c_sel:
                sel_site = st.selectbox("사이트", _opts9, key="aq_site_sel", format_func=_site_fmt9)
            with c_std:
                st.caption("표준 시스템 = 계속 다듬어 나가는 **기준 배치**입니다. 아래 버튼으로 바로 열고, "
                           "농협 설계는 **복제 후 수정**하세요.")
                if st.button("📐 표준 시스템 열기", key="aq_std_load", use_container_width=True,
                             help="저장된 표준 시스템 사이트를 즉시 엽니다(없으면 V1 도면 기준으로 처음 한 번 생성)."):
                    try:
                        if _has_std9:                      # [V69] 이미 있으면 '열기'만 — 손질본을 덮어쓰지 않는다
                            st.session_state["_aq_site_jump"] = AQ_STD_SITE
                            st.rerun()
                        _racks_std, _plan_std = aq_std_payload(aq_items)
                        aq_sites_all.append({"농협ID": "S000", "농협명": AQ_STD_SITE, "지역": "-",
                                             "상태": "표준", "설치일": "2023-03",
                                             "랙구성JSON": json.dumps(_racks_std, ensure_ascii=False, separators=(",", ":")),
                                             "배치JSON": json.dumps(_plan_std, ensure_ascii=False, separators=(",", ":")),
                                             "견적ID": "", "담당자": "",
                                             "비고": "V1 도면 역산 표준 시스템 — 검증 기준"})
                        aq_save_sites(aq_sites_all)
                        aq_load_all.clear()
                        st.session_state["_aq_site_jump"] = AQ_STD_SITE
                        st.success("표준 시스템을 새로 만들었습니다"); time.sleep(0.5); st.rerun()
                    except Exception as e:
                        st.error(f"표준 열기 실패: {aq_err_str(e)}")
            if sel_site == AQ_STD_SITE:   # 선택값도 굵게(가능한 경우) — 기준 시스템 작업 중임을 눈에 띄게
                st.markdown('<style>.st-key-aq_site_sel div[data-baseweb="select"] '
                            '{font-weight:800 !important;}</style>', unsafe_allow_html=True)

            # ── [V69] 사이트 복제 — 표준(또는 비슷한 농협)을 복제해 이름만 바꿔 시작 ──
            if sel_site != "(신규 등록)":
                with st.expander(f"📄 '{sel_site}' 복제해서 새 농협 만들기", expanded=False):
                    st.caption("랙 구성·배치·진열 계획을 **그대로 복사**한 새 사이트를 만듭니다. "
                               "A농협이 표준과 거의 같다면 → 복제 → 다른 부분만 수정 → 💾 저장.")
                    _cp1, _cp2 = st.columns([3, 1.4])
                    with _cp1:
                        _cp_nm9 = st.text_input("새 농협명 *", key=f"aq_cp_nm_{sel_site}",
                                                placeholder="예: 여주농협")
                    with _cp2:
                        _cp_rg9 = st.text_input("지역", key=f"aq_cp_rg_{sel_site}")
                    if st.button("📄 복제 실행", key=f"aq_cp_go_{sel_site}"):
                        _nm9 = _cp_nm9.strip()
                        if not _nm9:
                            st.error("새 농협명을 입력하세요.")
                        elif _nm9 in _site_names:
                            st.error("이미 등록된 농협명입니다.")
                        else:
                            try:
                                _src9 = next(s for s in aq_sites_all
                                             if str(s.get("농협명", "")).strip() == sel_site)
                                _ids9 = {str(s.get("농협ID", "")).strip() for s in aq_sites_all}
                                _n9i = len(aq_sites_all) + 1
                                while f"S{_n9i:03d}" in _ids9: _n9i += 1
                                aq_sites_all.append({
                                    "농협ID": f"S{_n9i:03d}", "농협명": _nm9,
                                    "지역": _cp_rg9.strip() or str(_src9.get("지역", "")),
                                    "상태": "제안", "설치일": "",
                                    "랙구성JSON": str(_src9.get("랙구성JSON") or ""),
                                    "배치JSON": str(_src9.get("배치JSON") or ""),
                                    "견적ID": "", "담당자": str(_src9.get("담당자", "")),
                                    "비고": f"'{sel_site}' 복제 ({datetime.date.today().strftime('%Y-%m-%d')})"})
                                aq_save_sites(aq_sites_all)
                                aq_load_all.clear()
                                for _k9 in list(st.session_state.keys()):   # 복제본은 새 세션 상태로 시작
                                    if _k9.startswith((f"aq_inst_{_nm9}", f"aq_rows_{_nm9}")):
                                        st.session_state.pop(_k9, None)
                                st.session_state["_aq_site_jump"] = _nm9
                                st.success(f"'{_nm9}' 복제 완료 — 수정 후 💾 저장하세요.")
                                time.sleep(0.6); st.rerun()
                            except Exception as e:
                                st.error(f"복제 실패: {aq_err_str(e)}")

            # ── [V69] 표준 공장초기화 — 되돌릴 수 없어 깊이 숨긴다(손질본이 날아감) ──
            if sel_site == AQ_STD_SITE:
                with st.expander("⚠ 표준을 V1 도면 원본으로 되돌리기 (공장초기화)", expanded=False):
                    st.caption("코드에 박힌 V1 도면 상수로 랙·배치를 **재생성**합니다 — 그동안 다듬어 온 "
                               "표준 손질본이 사라집니다. 복구는 시트 버전 기록으로만 가능.")
                    _rs_in9 = st.text_input("확인 — '초기화' 입력", key="aq_std_reset_in")
                    if st.button("⚠ 표준 공장초기화 실행", key="aq_std_reset_go"):
                        if _rs_in9.strip() != "초기화":
                            st.error("'초기화'를 정확히 입력하세요.")
                        else:
                            try:
                                _racks_std, _plan_std = aq_std_payload(aq_items)
                                for s in aq_sites_all:
                                    if str(s.get("농협명", "")).strip() == AQ_STD_SITE:
                                        s["랙구성JSON"] = json.dumps(_racks_std, ensure_ascii=False, separators=(",", ":"))
                                        s["배치JSON"] = json.dumps(_plan_std, ensure_ascii=False, separators=(",", ":"))
                                        s["상태"] = "표준"
                                aq_save_sites(aq_sites_all)
                                aq_load_all.clear()
                                for _k9 in (f"aq_inst_{AQ_STD_SITE}", f"aq_rows_{AQ_STD_SITE}"):
                                    st.session_state.pop(_k9, None)
                                st.success("표준을 V1 도면 원본으로 되돌렸습니다"); time.sleep(0.5); st.rerun()
                            except Exception as e:
                                st.error(f"초기화 실패: {aq_err_str(e)}")

            # ── [V55] 사이트 삭제 (대표님 요청 — 테스트 사이트 정리) ──
            if sel_site != "(신규 등록)":
                with st.expander("🗑 사이트 삭제", expanded=False):
                    st.caption("이 사이트 행이 AQ_Sites 시트에서 제거됩니다(랙 구성·배치 포함). "
                               "실수 방지를 위해 농협명을 그대로 입력해야 삭제됩니다. 복구는 시트 버전 기록으로 가능.")
                    _del_in9 = st.text_input(f"삭제 확인 — 농협명 입력: {sel_site}", key=f"aq_del_in_{sel_site}")
                    if st.button("🗑 이 사이트 삭제", key=f"aq_del_go_{sel_site}"):
                        if _del_in9.strip() != sel_site:
                            st.error("농협명이 일치하지 않습니다.")
                        else:
                            try:
                                _rest9 = [s for s in aq_sites_all
                                          if str(s.get("농협명", "")).strip() != sel_site]
                                aq_save_sites(_rest9)
                                aq_load_all.clear()
                                st.success("삭제 완료"); time.sleep(0.5); st.rerun()
                            except Exception as e:
                                st.error(f"삭제 실패: {aq_err_str(e)}")

            if sel_site == "(신규 등록)":
                with st.form("aq_site_add_form", clear_on_submit=True):
                    ns1, ns2, ns3 = st.columns(3)
                    s_name = ns1.text_input("농협명 *")
                    s_region = ns2.text_input("지역")
                    s_mgr = ns3.text_input("담당자")
                    s_memo = st.text_input("비고", key="aq_site_memo")
                    if st.form_submit_button("사이트 등록", type="primary"):
                        _nm = s_name.strip()
                        if not _nm:
                            st.error("농협명을 입력하세요.")
                        elif _nm in _site_names:
                            st.error("이미 등록된 농협입니다.")
                        else:
                            try:
                                _sid = f"S{len(aq_sites_all) + 1:03d}"
                                aq_append_row("AQ_Sites", [_sid, _nm, s_region, "제안", "", "", "", "", s_mgr, s_memo])
                                aq_load_all.clear()
                                st.success(f"'{_nm}' 등록 완료"); time.sleep(0.5); st.rerun()
                            except Exception as e:
                                st.error(f"등록 실패: {aq_err_str(e)}")
            else:
                _site = next(s for s in aq_sites_all if str(s.get("농협명", "")).strip() == sel_site)
                st.caption(f"상태: {_site.get('상태', '')} · 지역: {_site.get('지역', '')} · 설치일: {_site.get('설치일', '')}")

                st.markdown("##### 1️⃣ 공간(랙) 구성 — 현장 실측 입력 (행 추가/삭제 가능)")
                # [V54] 단깊이 컬럼 폐지(대표님 지시 — 랙 깊이만 사용) · 새 행은 첫 랙 값 자동 상속
                st.caption("📋 **새 랙 행은 명칭만 입력하면 첫 랙의 값(폭·깊이·총높이·단수·단두께·단높이)이 자동 적용**됩니다 — 현장 랙은 대부분 같은 규격이므로 다른 부분만 수정하세요. 저장 시 실제 값으로 기록됩니다.")
                # [V49] 단높이 검증 규칙: 총높이mm 입력 시 Σ단높이 + 단두께×(단수−1) = 총높이 여야 배치에 반영.
                st.caption("📐 **총높이mm**를 입력하면 단높이 합을 검증합니다 — Σ단높이 = 총높이 − 단두께×(단높이 개수−1). 예: 총 2000·두께 40·3단 → 단높이 합이 1920('800,800,320' ✓ / '800,700,320' ✗). 불일치 랙은 맞출 때까지 배치에서 제외됩니다.")
                try: _racks_cur = json.loads(str(_site.get("랙구성JSON") or "[]"))
                except Exception: _racks_cur = []
                # [V71] 랙 복제·삭제(그림 더블클릭)로 바뀐 구성은 세션에 남긴다 —
                #  data_editor는 매 실행 base(시트값)로 되돌아가므로, 오버라이드가 없으면
                #  다음 조작 때 복제한 랙이 사라진다. 💾 사이트 저장에 성공하면 이 키를 비운다.
                _rkov_key = f"aq_racks_ov_{sel_site}"
                _rkov9 = st.session_state.get(_rkov_key)
                if isinstance(_rkov9, list) and _rkov9:
                    _racks_cur = _rkov9
                _rack_cols = ["명칭", "폭mm", "깊이mm", "총높이mm", "단수", "단두께mm", "단높이mm(콤마구분)", "비고"]   # [V54] 단깊이 폐지
                _df_racks_in = pd.DataFrame(_racks_cur)
                for _c in _rack_cols:
                    if _c not in _df_racks_in.columns: _df_racks_in[_c] = ""
                _df_racks_in = _df_racks_in[_rack_cols]
                for _c in ["폭mm", "깊이mm", "총높이mm", "단수", "단두께mm"]:
                    _df_racks_in[_c] = pd.to_numeric(_df_racks_in[_c], errors="coerce")
                # [V55] 상속 가시화 — 상속으로 채운 표를 다음 렌더에 실제 데이터로 주입
                _rkv_key = f"aq_rack_ver_{sel_site}"
                if _rkv_key not in st.session_state: st.session_state[_rkv_key] = 0
                _df_over = st.session_state.pop(f"aq_rack_fill_{sel_site}", None)
                if _df_over is not None:
                    _df_racks_in = _df_over

                def _aq_rack_apply9(recs, _site=sel_site, _cols=_rack_cols, _vk=_rkv_key, _ok=_rkov_key):
                    """[V71] 랙 구성 표를 records로 교체 — 랙 복제·삭제와 그 되돌리기 공통 경로.
                    세션 오버라이드(_ok)에 남겨 다음 실행에서도 유지되게 하고, 편집표 키를 새로 발급한다."""
                    if recs is None: return
                    _dfr = pd.DataFrame(recs)
                    for _c in _cols:
                        if _c not in _dfr.columns: _dfr[_c] = ""
                    _dfr = _dfr[_cols].reset_index(drop=True)
                    st.session_state[_ok] = _dfr.to_dict("records")
                    st.session_state[f"aq_rack_fill_{_site}"] = _dfr
                    st.session_state[_vk] += 1
                    # '표시할 랙' 다중선택은 위젯 상태가 남아 새 랙이 자동으로 켜지지 않는다 —
                    #  없어진 랙은 빼고 새 랙은 더해 준다(이 동기화가 없으면 복제한 랙이 그림에 안 보임).
                    _vwk = f"aq_rk_view_{_site}"
                    _vw = st.session_state.get(_vwk)
                    if isinstance(_vw, list):
                        _nms = [str(r.get("명칭") or "").strip() for r in st.session_state[_ok]
                                if str(r.get("명칭") or "").strip()]
                        st.session_state[_vwk] = ([n for n in _vw if n in _nms or n.startswith("🅥")]
                                                  + [n for n in _nms if n not in _vw])

                _aq_rack_restore9 = _aq_rack_apply9   # ↩️/↪️ 되돌리기에서 쓰는 이름
                df_racks_ed = st.data_editor(
                    _df_racks_in, num_rows="dynamic", hide_index=True,
                    key=f"aq_racks_ed_{sel_site}_{st.session_state[_rkv_key]}",
                    column_config={
                        "폭mm": st.column_config.NumberColumn(format="%d"),
                        "깊이mm": st.column_config.NumberColumn(format="%d"),
                        "총높이mm": st.column_config.NumberColumn(format="%d", help="랙 최하단~최상단 전체 높이 — 입력 시 단높이 합 검증"),
                        "단수": st.column_config.NumberColumn(format="%d"),
                        "단두께mm": st.column_config.NumberColumn(format="%d", help="선반(단) 판 두께 — 예 40 (빈칸=0)"),
                    })
                # ── [V54] 첫 랙 값 자동 상속 — 이후 모든 검증·배치·저장은 df_racks_eff 기준 ──
                df_racks_eff = df_racks_ed.copy()
                _base_r = None
                for _bi9, _br9 in df_racks_eff.iterrows():
                    if pd.notna(_br9.get("폭mm")) and str(_br9.get("단높이mm(콤마구분)") or "").strip():
                        _base_r = _br9; break
                if _base_r is not None:
                    for _bi9, _br9 in df_racks_eff.iterrows():
                        _has_any9 = bool(str(_br9.get("명칭") or "").strip()) or pd.notna(_br9.get("폭mm"))
                        if not _has_any9 or _bi9 == _base_r.name: continue
                        for _fc9 in ["폭mm", "깊이mm", "총높이mm", "단수", "단두께mm"]:
                            if pd.isna(_br9.get(_fc9)):
                                df_racks_eff.at[_bi9, _fc9] = _base_r.get(_fc9)
                        # 단높이는 단수가 첫 랙과 같을 때만 상속(다른 단수는 직접 입력)
                        if not str(_br9.get("단높이mm(콤마구분)") or "").strip():
                            try: _cnt_b9 = int(float(df_racks_eff.at[_bi9, "단수"] or 0))
                            except Exception: _cnt_b9 = 0
                            try: _cnt_a9 = int(float(_base_r.get("단수") or 0))
                            except Exception: _cnt_a9 = 0
                            if _cnt_b9 == 0 or _cnt_b9 == _cnt_a9:
                                df_racks_eff.at[_bi9, "단높이mm(콤마구분)"] = _base_r.get("단높이mm(콤마구분)")
                # [V55] 상속으로 값이 채워졌으면 편집표에 즉시 반영(가시화) — 사용자가 채워진 값을 보고 수정
                try:
                    _same_fill9 = df_racks_eff.fillna("").astype(str).equals(df_racks_ed.fillna("").astype(str))
                except Exception:
                    _same_fill9 = True
                if not _same_fill9:
                    st.session_state[f"aq_rack_fill_{sel_site}"] = df_racks_eff
                    st.session_state[_rkv_key] += 1
                    st.rerun()
                # [V49] 랙 총높이 검증 — 불일치 랙은 배치(_rk_list)에서 제외
                _rack_errs, _rack_notes, _bad_racks, _rack_reqs = [], [], set(), []   # [V53] 필요 Σ단높이 안내
                for _ri9, _rr in df_racks_eff.iterrows():
                    _nm9 = str(_rr.get("명칭") or "").strip()
                    _lb9 = _nm9 or f"{_ri9 + 1}행"   # [V54] 이름 없는 새 행도 필요합계 안내
                    try: _tot9 = int(float(_rr.get("총높이mm") or 0))
                    except Exception: _tot9 = 0
                    try: _thk9 = int(float(_rr.get("단두께mm") or 0))
                    except Exception: _thk9 = 0
                    try:
                        _hs9 = [int(float(x)) for x in str(_rr.get("단높이mm(콤마구분)") or "").split(",") if str(x).strip()]
                    except Exception:
                        _hs9 = []
                    try: _cnt9 = int(float(_rr.get("단수") or 0))
                    except Exception: _cnt9 = 0
                    if _tot9 > 0 and (_cnt9 or _hs9):   # [V53] 총높이·단수·단두께 입력 → 필요 Σ단높이 즉시 안내
                        _n9c = _cnt9 or len(_hs9)
                        _req9 = _tot9 - _thk9 * max(0, _n9c - 1)
                        _rack_reqs.append(f"{_lb9}: 필요 Σ단높이 {_req9}mm"
                                          + (f" (현재 {sum(_hs9)})" if _hs9 else ""))
                    if not _nm9: continue
                    if _tot9 > 0 and _hs9:
                        _eff9 = _tot9 - _thk9 * (len(_hs9) - 1)
                        if sum(_hs9) != _eff9:
                            _bad_racks.add(_nm9)
                            _rack_errs.append(f"**{_nm9}**: 단높이 합 {sum(_hs9)} ≠ {_eff9} (총 {_tot9} − 두께 {_thk9}×{len(_hs9) - 1})")
                    if _cnt9 and _hs9 and _cnt9 != len(_hs9):
                        _rack_notes.append(f"{_nm9}: 단수 {_cnt9} ≠ 단높이 {len(_hs9)}개")
                if _rack_reqs:
                    st.caption("📐 **필요 단높이 합** — 총높이 − 단두께×(단수−1): " + " · ".join(_rack_reqs))
                if _rack_errs:
                    st.warning("📐 단높이 합이 총높이와 맞지 않는 랙이 있습니다(입력한 단높이로 그대로 그려집니다 — 확인용 안내).\n- " + "\n- ".join(_rack_errs))
                if _rack_notes:
                    st.caption("ℹ️ 단수 확인: " + " · ".join(_rack_notes))
                # [V44] 슬롯·층수 힌트 (상자 치수 기반)
                _dims_hint = aq_box_dims_map(aq_boxes)
                if _dims_hint:
                    _hint = " · ".join(f"{n} {AQ_STD_INNER // wh[0]}칸" for n, wh in sorted(_dims_hint.items()))
                    st.caption(f"표준 랙(W1200, 내측 1162mm) 단당 칸수: {_hint} — 층수 = 단높이 ÷ 상자높이 (예: 단높이 292 → 431-1호(112) 2층, 3호(116) 2층)")

                st.markdown("##### 2️⃣ 진열할 부속군 선택")
                try: _plan_cur = json.loads(str(_site.get("배치JSON") or "{}"))
                except Exception: _plan_cur = {}
                if not isinstance(_plan_cur, dict): _plan_cur = {}
                _plan_items = _plan_cur.get("items", {}) if isinstance(_plan_cur.get("items", {}), dict) else {}
                _g_default = [g for g in (aq_grp_norm(x) for x in _plan_cur.get("groups", [])) if g in aq_groups]   # [V59] 구군 호환
                plan_groups = st.multiselect("진열분류", aq_groups, default=_g_default, key=f"aq_plan_g_{sel_site}")

                edited_plan = None
                if plan_groups:
                    with st.expander("✏️ 상자·방향·수량 조정 (기본값 자동 적용 — 필요할 때만)", expanded=False):
                        _rows_plan = []
                        for r in aq_items:
                            if (r.get("진열분류") or "(미지정)") not in plan_groups: continue
                            _code = r["품목코드"]
                            _ov = _plan_items.get(_code, {}) if isinstance(_plan_items.get(_code, {}), dict) else {}
                            _caps_i = aq_caps.get(_code, {})
                            _cap_txt = " · ".join(f"{b}:{q}({s})" for b, (q, s) in _caps_i.items())
                            _box_def = str(_ov.get("box") or r.get("기본상자") or "")
                            _ori_def = str(_ov.get("ori") or "세로")            # [V43] 방향 기본=세로(표준)
                            if _ori_def not in ("세로", "가로"): _ori_def = "세로"
                            _use_def = (_ov.get("use", True) is not False)      # [V48] 공급 체크(기본 포함)
                            try:
                                _qty_def = int(_ov.get("qty")) if _ov.get("qty") is not None \
                                    else int(float(str(r.get("기본수량") or 0)))
                            except Exception:
                                _qty_def = 0
                            _p = prod_by_code.get(_code, {})
                            try: _unit_i = int(float(_p.get("price_nh_loc") or 0))
                            except Exception: _unit_i = 0
                            _rows_plan.append({
                                "공급": _use_def,
                                "품목코드": _code, "품목명": str(r.get("품목명_AQ", "") or ""), "규격": str(r.get("규격_AQ", "") or ""),
                                "수용정보": _cap_txt, "상자": _box_def, "방향": _ori_def, "수량": _qty_def, "지역농협가": _unit_i,
                            })
                        _box_opts = sorted(set(aq_box_names) | {rp["상자"] for rp in _rows_plan if rp["상자"]})
                        edited_plan = st.data_editor(
                            pd.DataFrame(_rows_plan), hide_index=True, height=420, key=f"aq_plan_ed_{sel_site}",
                            disabled=["품목코드", "품목명", "규격", "수용정보", "지역농협가"],
                            column_config={
                                "공급": st.column_config.CheckboxColumn("공급", help="체크 해제 = 이 농협에는 공급/배치 제외"),
                                "상자": st.column_config.SelectboxColumn("상자", options=[""] + _box_opts),
                                "방향": st.column_config.SelectboxColumn(
                                    "방향", options=["세로", "가로"],
                                    help="세로=표준(상자 폭이 전면, 최대 배치) · 가로=깊이 얕은 단용(상자 깊이가 전면)"),
                                "수량": st.column_config.NumberColumn(format="%d", min_value=0),
                            })
                        _n_excl = int((~edited_plan["공급"].astype(bool)).sum()) if "공급" in edited_plan.columns else 0
                        if _n_excl:
                            st.caption(f"🚫 공급 제외 {_n_excl}개 품목 (배치·견적에서 빠집니다)")
                else:
                    st.info("진열분류를 선택하면 품목별 계획 표가 나타납니다.")

                # [V48] 품목별 공급 여부 (편집표 우선 → 저장값 → 기본 포함)
                def _aq_use(code):
                    if edited_plan is not None and "공급" in edited_plan.columns:
                        _m = edited_plan.loc[edited_plan["품목코드"] == code, "공급"]
                        if len(_m): return bool(_m.iloc[0])
                    _o = _plan_items.get(code, {})
                    return (_o.get("use", True) is not False) if isinstance(_o, dict) else True

                _aq_by_code = {r["품목코드"]: r for r in aq_items}   # [V49] 코드→AQ_Items 레코드

                # ── [V49] 자유 배치 — 상자에 담기지 않는 품목을 도형/등각(ISO) 이미지로 등록 ──
                _free_cur = _plan_cur.get("free", {}) if isinstance(_plan_cur.get("free", {}), dict) else {}
                df_free = None
                with st.expander("🎨 자유 배치 품목 — 상자 없는 제품 (도형/등각 이미지, 크기 직접 지정)", expanded=False):
                    st.caption("상자 미지정 품목(전시품·행잉·공구류)을 **폭×높이(mm)** 직접 지정으로 단에 올립니다. "
                               "형태 = 사각/원/이미지(등각 ISO 등록 품목만). **품명(코드)·수량 매칭 필수** — 수량·크기가 없으면 배치되지 않습니다. "
                               "랙·단 지정은 아래 3️⃣ 세부 조정 표에서(상자란에 '(자유)'로 표시).")
                    _rows_free = []
                    for r in aq_items:
                        _cf = r["품목코드"]
                        if not _aq_use(_cf): continue
                        _boxf = str((_plan_items.get(_cf, {}) or {}).get("box") or r.get("기본상자") or "").strip()
                        if _boxf: continue   # 상자가 있는 품목은 대상 아님
                        _fc = _free_cur.get(_cf, {}) if isinstance(_free_cur.get(_cf, {}), dict) else {}
                        if not _fc and aq_std_free_of(_cf):   # [V58] 표준 자유배치 존(여과기·지주대) 기본 제공
                            _fc = dict(aq_std_free_of(_cf))
                        _has_iso = bool(str(r.get("이미지ISO", "") or "").strip())
                        try: _wdef = int(_fc.get("w") or 0) or int(float(str(r.get("가로") or 0))) or None
                        except Exception: _wdef = None
                        try: _hdef = int(_fc.get("h") or 0) or int(float(str(r.get("높이") or 0))) or None
                        except Exception: _hdef = None
                        _rows_free.append({
                            "사용": (_cf in _free_cur) or bool(aq_std_free_of(_cf)),   # [V58] 표준 존 기본 사용
                            "품목코드": _cf, "품목명": str(r.get("품목명_AQ", "") or ""), "규격": str(r.get("규격_AQ", "") or ""),
                            "형태": str(_fc.get("shape") or ("이미지" if _has_iso else "사각")),
                            "폭mm": _wdef, "높이mm": _hdef,
                            "수량": int(_fc.get("qty") or 0),
                            "ISO": "✓" if _has_iso else "",
                        })
                    if _rows_free:
                        df_free = st.data_editor(
                            pd.DataFrame(_rows_free), hide_index=True, height=280, key=f"aq_free_ed_{sel_site}",
                            disabled=["품목코드", "품목명", "규격", "ISO"],
                            column_config={
                                "사용": st.column_config.CheckboxColumn("사용", help="체크 = 자유 배치 대상으로 등록"),
                                "형태": st.column_config.SelectboxColumn("형태", options=["사각", "원", "이미지"],
                                                                       help="이미지 = 등각(ISO) 이미지 누끼 표시 (ISO ✓ 품목만)"),
                                "폭mm": st.column_config.NumberColumn(format="%d", min_value=0, help="진열 시 차지하는 전면 폭"),
                                "높이mm": st.column_config.NumberColumn(format="%d", min_value=0),
                                "수량": st.column_config.NumberColumn(format="%d", min_value=0, help="이 자리에 진열하는 수량 (필수)"),
                            })
                    else:
                        st.info("상자 미지정 품목이 없습니다 — 모든 품목에 상자가 지정되어 있습니다.")
                _free_live, _free_bad = {}, []
                if df_free is not None:
                    for _, _rf in df_free.iterrows():
                        if not bool(_rf.get("사용")): continue
                        try: _wf = int(_rf.get("폭mm") or 0)
                        except Exception: _wf = 0
                        try: _hf = int(_rf.get("높이mm") or 0)
                        except Exception: _hf = 0
                        try: _qf = int(_rf.get("수량") or 0)
                        except Exception: _qf = 0
                        if _wf <= 0 or _hf <= 0 or _qf <= 0:
                            _free_bad.append(str(_rf["품목코드"])); continue   # 품명·수량 매칭 강제
                        _shf = str(_rf.get("형태") or "사각")
                        if _shf == "이미지" and not str(_rf.get("ISO") or ""):
                            _shf = "사각"   # ISO 미등록 품목의 이미지 선택 → 사각 폴백
                        _free_live[str(_rf["품목코드"])] = {"shape": _shf, "w": _wf, "h": _hf, "qty": _qf}
                if _free_bad:
                    st.warning(f"🎨 자유 배치 제외 {len(_free_bad)}건 — 폭·높이·수량이 모두 입력되어야 배치됩니다: {', '.join(_free_bad[:6])}{' 외' if len(_free_bad) > 6 else ''}")

                # ── [V45] 단(선반) 중심 배치 설계 — 자동배치 + 실척 시각화 + 수동 조정 ──
                st.markdown("##### 3️⃣ 배치 — ⚡ 자동배치 후 전체 그림으로 확인")
                df_asg = None   # [V49] 세부 조정 표 핸들 (랙·치수 없으면 None 유지 — 저장 시 가드)
                if True:   # [V47] expander→상시 표시(내부 들여쓰기 보존)
                    st.caption("배치의 단위는 **단(선반)**입니다. 용도군(진열분류)별로 단에 군집 배치하고, 단 아래 **색상 자석테이프**로 영역을 표시합니다(색=분류별 지정색). 섹션(세로 열) 개념은 표준화 참고 전용입니다.")
                    _rk_list = []
                    for _, _rr in df_racks_eff.iterrows():   # [V54] 상속 적용본
                        _nm3 = str(_rr.get("명칭") or "").strip()
                        if not _nm3: continue
                        # [V64] 단높이 합이 총높이와 안 맞아도 랙을 숨기지 않는다(입력한 단높이로 그대로 렌더·배치).
                        #  총높이는 검증 안내용일 뿐 — 렌더는 Σ단높이+단두께, 패킹은 단별 높이라 총높이에 의존하지 않음.
                        #  (구: _bad_racks 제외 → 단높이 한 칸만 고쳐도 랙이 통째로 사라지던 문제 해소)
                        try: _wv3 = int(float(_rr.get("폭mm") or 0))
                        except Exception: _wv3 = 0
                        try:
                            _hs3 = [int(float(x)) for x in str(_rr.get("단높이mm(콤마구분)") or "").split(",") if str(x).strip()]
                        except Exception: _hs3 = []
                        try:                                # [V49] 탑뷰용 깊이 정보
                            _ds3 = [int(float(x)) for x in str(_rr.get("단깊이mm(콤마구분)") or "").split(",") if str(x).strip()]
                        except Exception: _ds3 = []
                        try: _dp3 = int(float(_rr.get("깊이mm") or 0))
                        except Exception: _dp3 = 0
                        try: _tk3 = int(float(_rr.get("단두께mm") or 0))   # [V62] 단 판 두께
                        except Exception: _tk3 = 0
                        if _wv3 > 0 and _hs3:
                            _rk_list.append({"명칭": _nm3, "내측폭": _wv3 - 38, "단높이": _hs3,
                                             "단깊이": _ds3, "깊이": _dp3 or 450, "단두께": _tk3})
                    _dims_p = aq_box_dims_map(aq_boxes)
                    _dims_p.update({f"자유:{c}": (fc["w"], fc["h"]) for c, fc in _free_live.items()})   # [V49] 자유 배치 치수
                    if not _rk_list:
                        st.info("랙 구성에 폭mm·단높이가 입력된 랙이 필요합니다. (📐 표준 시스템 불러오기로 예시 구성 가능)")
                    elif not _dims_p:
                        st.info("상자 치수가 필요합니다 — 📦 상자·수용량 탭에서 폭·높이를 등록하세요.")
                    else:
                        _pg = plan_groups if plan_groups else aq_groups
                        # [V67] 상자 인스턴스 모델(2단계) — 정본 상태 = 인스턴스 리스트(각 상자가 좌표 소유).
                        #  구 assign/split/xord/mstack 4중 모델 폐기(로드는 아래에서 1회 마이그레이션).
                        _inst_key = f"aq_inst_{sel_site}"   # [{"id","code","box","rack","shelf","col","layer"}]
                        _rows_key = f"aq_rows_{sel_site}"   # {코드: 깊이 줄수} — 탑뷰 표시용 메타
                        _ver_key = f"aq_asg_ver_{sel_site}"
                        if _ver_key not in st.session_state: st.session_state[_ver_key] = 0
                        # ── [V51] 가상랙(임시 보관 공간) + 배치 그림 드래그/더블클릭 조작 브리지 ──
                        AQ_VIRT = "🅥 가상랙"
                        if "aq_ops_salt" not in st.session_state:   # 세션 고유 논스 — 이전 세션 조작 재적용 방지
                            st.session_state["aq_ops_salt"] = str(int(time.time() * 1000))
                        _vc1, _vc2 = st.columns([3, 1.4])
                        with _vc1:
                            _virt_on = st.checkbox(
                                "🅥 가상랙 표시 — 꽉 찬 랙의 상자를 잠시 옮겨 둘 임시 공간 (견적·적합판정·자동배치와 무관, 배치는 저장됨)",
                                value=True, key=f"aq_virt_{sel_site}")
                        with _vc2:
                            _virt_pos = st.radio("가상랙 위치", ["맨 앞", "맨 뒤"], horizontal=True,
                                                 key=f"aq_virt_pos_{sel_site}")   # [V56] 즉시 이동
                        _vp_prev9 = st.session_state.get(f"aq_vp_prev_{sel_site}")
                        if _vp_prev9 != _virt_pos:   # 위치 선택이 바뀌면 드래그 순서 기록에서 가상랙 제거(라디오 우선)
                            st.session_state[f"aq_vp_prev_{sel_site}"] = _virt_pos
                            _ro9 = st.session_state.get(f"aq_rkord_{sel_site}")
                            if _ro9:
                                st.session_state[f"aq_rkord_{sel_site}"] = [n for n in _ro9 if n != AQ_VIRT]
                        _virt_rk9 = [{"명칭": AQ_VIRT, "내측폭": 900, "단높이": [600, 600, 600],
                                      "단깊이": [], "깊이": 450}]
                        _rk_all = (((_virt_rk9 if _virt_pos == "맨 앞" else []) + _rk_list
                                    + (_virt_rk9 if _virt_pos == "맨 뒤" else [])) if _virt_on else _rk_list)
                        # ── [V67] 인스턴스 상태 로드 — schema 2는 좌표 그대로, v1 레거시는 1회 마이그레이션 ──
                        if _inst_key not in st.session_state:
                            _rows0 = {}
                            _sv_asg0 = _plan_cur.get("assign", {}) if isinstance(_plan_cur.get("assign", {}), dict) else {}
                            for _c0, _d0 in _sv_asg0.items():
                                if isinstance(_d0, dict):
                                    try: _rows0[str(_c0)] = max(1, int(_d0.get("rows") or 1))
                                    except Exception: pass
                            def _box_of0(c):
                                """저장본에는 상자명이 없다([V68] inst2) — items→기본상자→자유배치 순 재해석."""
                                _r0b = _aq_by_code.get(c, {}) or {}
                                _b0b = str((_plan_items.get(c, {}) or {}).get("box") or _r0b.get("기본상자") or "").strip()
                                if not _b0b and c in _free_live: _b0b = "자유:" + c
                                return _b0b
                            _packed0 = _plan_cur.get("inst2")
                            _insts0 = _plan_cur.get("instances")
                            if isinstance(_packed0, dict) and _packed0:
                                # [V68] 압축 저장본(정식 포맷) — 좌표 그대로 복원, 재계산 없음
                                st.session_state[_inst_key] = aq_inst_unpack(_packed0, _box_of0)
                            elif isinstance(_insts0, list):
                                # schema 2 초기(장황) 포맷 — 저장된 좌표를 그대로 신뢰(재계산 없음)
                                _ld0 = []
                                for _x0 in _insts0:
                                    if not isinstance(_x0, dict): continue
                                    try:
                                        _e0 = {"id": str(_x0.get("id") or ""), "code": str(_x0.get("code") or ""),
                                               "box": str(_x0.get("box") or ""), "rack": str(_x0.get("rack") or ""),
                                               "shelf": int(_x0.get("shelf") or 0),
                                               "col": float(_x0.get("col") or 0), "layer": float(_x0.get("layer") or 0)}
                                    except Exception:
                                        continue
                                    if _e0["id"] and _e0["code"] and _e0["rack"] and _e0["shelf"] > 0:
                                        _ld0.append(_e0)
                                aq_inst_normalize(_ld0)
                                st.session_state[_inst_key] = _ld0
                            else:
                                # v1 → 종전 패킹 규칙을 마지막 1회 재현해 좌표 확정(이후 리런·조작은 재계산 없음)
                                _sv_sp0 = _plan_cur.get("splits", {}) if isinstance(_plan_cur.get("splits", {}), dict) else {}
                                _sv_mst0 = _plan_cur.get("mstack")
                                if isinstance(_sv_mst0, dict): _sv_mst0 = {str(k): str(v) for k, v in _sv_mst0.items()}
                                elif isinstance(_sv_mst0, (list, set)): _sv_mst0 = {str(c): str(c) for c in _sv_mst0}
                                else: _sv_mst0 = {}
                                _mig_seqs0 = {}
                                def _mig_add0(c, rack, shelf, n, ordv):
                                    _b0 = _box_of0(c)
                                    _wh0 = _dims_p.get(_b0)
                                    if not _wh0: return
                                    _r0 = _aq_by_code.get(c, {}) or {}
                                    _g0 = str(_r0.get("진열분류") or "(미지정)")
                                    if ordv is not None:
                                        try: _h0 = float(ordv)
                                        except Exception: _h0 = 1
                                    else:
                                        _se0 = str(_r0.get("섹션", "") or "").strip()
                                        try: _sd0 = int(float(_r0.get("단") or 0))
                                        except Exception: _sd0 = 0
                                        _h0 = AQ_COL_ORD.get(str(_r0.get("열", "") or "").strip(), 1) \
                                            if (_se0 and _sd0 == shelf and rack in (f"섹션{_se0}", _se0)) else 1
                                    for _ in range(max(1, int(n or 1))):
                                        _mig_seqs0.setdefault((rack, shelf), []).append(
                                            (c, _g0, _b0, _wh0[0], _wh0[1], _h0))
                                for _c0, _d0 in _sv_asg0.items():
                                    if not isinstance(_d0, dict): continue
                                    _rk0 = str(_d0.get("rack") or "")
                                    try: _sh0 = int(_d0.get("shelf") or 0)
                                    except Exception: _sh0 = 0
                                    if not _rk0 or _sh0 <= 0: continue
                                    _mig_add0(str(_c0), _rk0, _sh0, _d0.get("n") or 1, _d0.get("ord"))
                                for _c0, _lst0 in _sv_sp0.items():
                                    if not isinstance(_lst0, list): continue
                                    for _e0 in _lst0:
                                        try: _mig_add0(str(_c0), str(_e0[0]), int(_e0[1]), int(_e0[2]), None)
                                        except Exception: continue
                                for _k0 in _mig_seqs0:
                                    _mig_seqs0[_k0] = aq_canon_seq(_mig_seqs0[_k0], _pg)
                                st.session_state[_inst_key] = aq_instances_from_seqs(
                                    _mig_seqs0, _rk_all + ([] if _virt_on else _virt_rk9), mstack=_sv_mst0)
                            st.session_state[_rows_key] = _rows0
                        if _HAS_JS_EVAL:
                            # [V55] 근본 수정: streamlit_js_eval 프론트는 js_expressions "문자열이 바뀔 때만"
                            #  재평가한다(index.html: if (new_value !== data_from_streamlit)). 고정 문자열이라
                            #  최초 1회만 읽고 끝 → 조작이 영영 미반영되던 원인.
                            #  '🔄 배치 조작 반영' 클릭(그림에서 자동클릭 포함) 턴에만 시퀀스를 올려 재평가
                            #  (매 실행 변경은 리런 폭풍 유발 — 실브라우저 검증으로 확인).
                            if st.session_state.pop("aq_ops_bump", False):
                                st.session_state["aq_ops_read_seq"] = st.session_state.get("aq_ops_read_seq", 0) + 1
                            _rdseq9 = st.session_state.get("aq_ops_read_seq", 0)
                            try:
                                _ops_raw = streamlit_js_eval(
                                    js_expressions=f"window.parent.localStorage.getItem('AQ_OPS') /*{_rdseq9}*/",
                                    key=f"aq_ops_{sel_site}")
                            except Exception:
                                _ops_raw = None
                            _ops_pl = None
                            if _ops_raw:
                                try: _ops_pl = json.loads(_ops_raw)
                                except Exception: _ops_pl = None
                            # [V67] 배치(batch) 단위 1회 적용 — 처리된 배치는 재적용 금지, 적용 후 ACK를
                            #  iframe에 주입해 localStorage를 정리시킨다(누적 재전송·무한 버퍼링 근본 차단).
                            #  op id 디둡은 유지 — 전송 중 배치가 합쳐져도 같은 조작이 두 번 반영되지 않게.
                            _nonce_cur = f"{st.session_state['aq_ops_salt']}|{sel_site}"
                            _done_b9 = st.session_state.setdefault(f"aq_done_b_{sel_site}", set())
                            _done_ids = st.session_state.setdefault(f"aq_ops_ids_{sel_site}", set())
                            _batch9 = str(_ops_pl.get("batch") or "") if isinstance(_ops_pl, dict) else ""
                            if (isinstance(_ops_pl, dict) and _ops_pl.get("ops") and _batch9
                                    and _ops_pl.get("nonce") == _nonce_cur and _batch9 not in _done_b9):
                                _done_b9.add(_batch9)
                                if len(_done_b9) > 60:
                                    st.session_state[f"aq_done_b_{sel_site}"] = set(list(_done_b9)[-30:])
                                _new_ops = [o for o in _ops_pl["ops"]
                                            if isinstance(o, dict) and o.get("id") and o["id"] not in _done_ids]
                                if _new_ops:
                                    # [V56] 조작 전 상태 스냅샷 → ↩️ 되돌리기 스택(최근 20건), 새 조작 시 redo 비움
                                    _un9 = st.session_state.setdefault(f"aq_undo_{sel_site}", [])
                                    _un9.append({"inst": [dict(x) for x in st.session_state.get(_inst_key, [])],
                                                 "boxov": dict(st.session_state.get(f"aq_boxov_{sel_site}", {})),
                                                 "rkord": list(st.session_state.get(f"aq_rkord_{sel_site}") or []),
                                                 "rows": dict(st.session_state.get(_rows_key, {}) or {}),
                                                 "racks": df_racks_eff.to_dict("records")})   # [V71] 랙 복제·삭제 되돌리기
                                    if len(_un9) > 20:
                                        del _un9[0]
                                    st.session_state[f"aq_redo_{sel_site}"] = []
                                    # [V67] 인스턴스(iid) 단위 적용 — 각 상자가 좌표를 소유하므로
                                    #  이동/복제/삭제가 그 상자에만 영향(품목 전체 재배치 없음).
                                    #  실패는 삼키지 않고 수집해 화면에 노출(무한 재시도 방지 위해 done은 유지).
                                    _ins9s = st.session_state.setdefault(_inst_key, [])
                                    _op_errs9 = []
                                    _rack_edit9 = None   # [V71] 랙 복제·삭제로 바뀐 랙 구성 표(records)
                                    _rk_by9 = {rk["명칭"]: rk for rk in _rk_all}
                                    def _shelf_h9(rk, sh):
                                        _r9h = _rk_by9.get(str(rk))
                                        try:
                                            return _r9h["단높이"][int(sh) - 1] \
                                                if _r9h and 0 < int(sh) <= len(_r9h["단높이"]) else 0
                                        except Exception:
                                            return 0
                                    for _op9 in _new_ops:
                                        try:
                                            _t9 = _op9.get("t")
                                            _c9o = str(_op9.get("code") or "")
                                            if _t9 == "move" and _op9.get("track") and _op9.get("iid"):
                                                _trk9 = str(_op9["track"]); _tsh9 = int(_op9.get("tshelf") or 0)
                                                _e9m = aq_inst_move(
                                                    _ins9s, str(_op9["iid"]), _trk9, _tsh9,
                                                    xr=_op9.get("xr"), onto=_op9.get("onto"),
                                                    dims=_dims_p, shelf_h=_shelf_h9(_trk9, _tsh9),
                                                    inner=(_rk_by9.get(_trk9) or {}).get("내측폭") or 0,
                                                    anchor=_op9.get("anchor"))   # [V70] 놓은 쪽(좌/우)
                                                if _e9m: _op_errs9.append(_e9m)
                                            elif _t9 == "dup" and _op9.get("iid"):
                                                _sd9 = next((x for x in _ins9s
                                                             if str(x.get("id")) == str(_op9["iid"])), None)
                                                _e9m = aq_inst_dup(
                                                    _ins9s, str(_op9["iid"]), dims=_dims_p,
                                                    shelf_h=(_shelf_h9(_sd9.get("rack"), _sd9.get("shelf"))
                                                             if _sd9 else 0))
                                                if _e9m: _op_errs9.append(_e9m)
                                            elif _t9 == "del" and _op9.get("iid"):
                                                _e9m = aq_inst_del(_ins9s, str(_op9["iid"]))
                                                if _e9m: _op_errs9.append(_e9m)
                                            elif _t9 == "box" and _op9.get("box") and _c9o:   # [V54] 상자 변경(코드 단위)
                                                _bx9o = str(_op9["box"])
                                                if _bx9o not in _dims_p:
                                                    _op_errs9.append(f"{_c9o}: 상자 '{_bx9o}' 치수 미등록 — 변경 불가")
                                                else:
                                                    st.session_state.setdefault(f"aq_boxov_{sel_site}", {})[_c9o] = _bx9o
                                                    for _x9 in _ins9s:
                                                        if str(_x9.get("code")) == _c9o: _x9["box"] = _bx9o
                                                    aq_inst_normalize(_ins9s)
                                            elif _t9 == "rord" and _op9.get("rack") and _op9.get("target"):
                                                # [V55] 랙 순서 변경 — 드래그한 랙을 대상 랙 앞/뒤로
                                                _co9 = (st.session_state.get(f"aq_rkord_{sel_site}")
                                                        or [rk["명칭"] for rk in _rk_all])
                                                _co9 = [n for n in _co9 if n != _op9["rack"]]
                                                if _op9["target"] in _co9:
                                                    _ti9 = _co9.index(_op9["target"]) + (1 if _op9.get("after") else 0)
                                                else:
                                                    _ti9 = len(_co9)
                                                _co9.insert(_ti9, str(_op9["rack"]))
                                                st.session_state[f"aq_rkord_{sel_site}"] = _co9
                                            elif _t9 in ("rdup", "rdel") and _op9.get("rack"):
                                                # [V71] 섹션(랙) 더블클릭 → 복제/삭제. 랙 구성 표(1️⃣)·상자
                                                #  인스턴스·랙 순서를 함께 고쳐 배치·견적·저장에 자동 반영.
                                                _rn9 = str(_op9["rack"])
                                                _recs9 = (_rack_edit9 if _rack_edit9 is not None
                                                          else df_racks_eff.to_dict("records"))
                                                _ix9 = next((_i for _i, _r in enumerate(_recs9)
                                                             if str(_r.get("명칭") or "").strip() == _rn9), None)
                                                _ord9r = list(st.session_state.get(f"aq_rkord_{sel_site}")
                                                              or [rk["명칭"] for rk in _rk_all])
                                                if _rn9 == AQ_VIRT:
                                                    _op_errs9.append("🅥 가상랙은 임시 보관 공간이라 복제·삭제할 수 없습니다.")
                                                elif _ix9 is None:
                                                    _op_errs9.append(f"{_rn9}: 랙 구성 표에서 찾지 못해 건너뜁니다.")
                                                elif _t9 == "rdel":
                                                    del _recs9[_ix9]
                                                    _ins9s[:] = [_x for _x in _ins9s
                                                                 if str(_x.get("rack") or "") != _rn9]
                                                    st.session_state[f"aq_rkord_{sel_site}"] = [
                                                        _n for _n in _ord9r if _n != _rn9]
                                                    _rack_edit9 = _recs9
                                                else:
                                                    _used9 = {str(_r.get("명칭") or "").strip() for _r in _recs9}
                                                    _stem9 = _rn9   # 섹션07-2를 다시 복제하면 섹션07-3 (꼬리표 누적 방지)
                                                    if "-" in _stem9 and _stem9.rsplit("-", 1)[1].isdigit():
                                                        _stem9 = _stem9.rsplit("-", 1)[0]
                                                    _k9r = 2
                                                    while f"{_stem9}-{_k9r}" in _used9: _k9r += 1
                                                    _new9r = f"{_stem9}-{_k9r}"
                                                    _row9r = dict(_recs9[_ix9]); _row9r["명칭"] = _new9r
                                                    _recs9.insert(_ix9 + 1, _row9r)
                                                    if _op9.get("deep"):   # 상자까지 복제 — 좌표 그대로 새 랙에
                                                        for _sx9 in [_x for _x in _ins9s
                                                                     if str(_x.get("rack") or "") == _rn9]:
                                                            _cp9r = dict(_sx9)
                                                            _cp9r["rack"] = _new9r
                                                            _cp9r["id"] = aq_inst_new_id(_ins9s, str(_sx9.get("code")))
                                                            _ins9s.append(_cp9r)
                                                    if _rn9 in _ord9r: _ord9r.insert(_ord9r.index(_rn9) + 1, _new9r)
                                                    else: _ord9r.append(_new9r)
                                                    st.session_state[f"aq_rkord_{sel_site}"] = _ord9r
                                                    _rack_edit9 = _recs9
                                        except Exception as _oe9:
                                            _op_errs9.append(f"{_op9.get('t', '?')} {_op9.get('code', '')}: {aq_err_str(_oe9)}")
                                        _done_ids.add(_op9.get("id"))
                                    if _rack_edit9 is not None:
                                        # [V71] 바뀐 랙 구성을 편집표에 반영 — 다음 리런에서 표가 갱신되고,
                                        #  💾 저장 시 랙구성JSON에 그대로 기록된다.
                                        _aq_rack_apply9(_rack_edit9)
                                        aq_inst_normalize(_ins9s)
                                    if _op_errs9:   # [V65] 실패한 조작을 화면에 노출(조용히 사라지지 않게)
                                        st.session_state["aq_op_errs"] = _op_errs9
                                    if len(_done_ids) > 400:   # 세션 메모리 상한
                                        st.session_state[f"aq_ops_ids_{sel_site}"] = set(list(_done_ids)[-200:])
                                # [V67] ACK — 이 배치는 처리 완료. iframe이 다음 로드에서 localStorage 삭제.
                                #  (_new_ops가 비어도 ACK는 기록 — 이미 반영된 배치의 잔재 정리)
                                st.session_state[f"aq_ack_{sel_site}"] = _batch9
                                st.session_state[_ver_key] += 1
                                st.rerun()
                        # [V55] 랙 순서 적용 (세션 → 없으면 저장된 rack_order) — 표시·자동배치·편집표 공통
                        _ord9 = st.session_state.get(f"aq_rkord_{sel_site}")
                        if not _ord9:
                            _ord9 = [n for n in (_plan_cur.get("rack_order") or []) if isinstance(n, str)]
                            if _ord9:
                                st.session_state[f"aq_rkord_{sel_site}"] = _ord9
                        if _ord9:
                            _oidx9 = {n: i for i, n in enumerate(_ord9)}
                            _rk_all = sorted(_rk_all, key=lambda rk: _oidx9.get(rk["명칭"], 999))
                            _rk_list = sorted(_rk_list, key=lambda rk: _oidx9.get(rk["명칭"], 999))
                        ca1, ca0, ca2 = st.columns([2, 1, 3])
                        with ca0:
                            if st.button("🗑 배치 초기화", key=f"aq_clear_{sel_site}"):
                                st.session_state[_inst_key] = []   # [V67] 인스턴스 전부 제거
                                st.session_state[_ver_key] += 1
                                st.session_state[f"aq_unp_{sel_site}"] = []
                                st.rerun()
                        with ca1:
                            if st.button("⚡ 자동배치 (단 중심 군집)", key=f"aq_auto_{sel_site}",
                                         help="[V67] 누를 때만 실행됩니다 — 기존 수동 배치(드래그 이동·적층 포함)를 "
                                              "전부 표준 규칙 배치로 덮어씁니다. 확정 배치는 💾 사이트 저장으로 보존하세요."):
                                _seq = []
                                for g in _pg:
                                    _gi = [r for r in aq_items if (r.get("진열분류") or "(미지정)") == g]
                                    def _eff_box(r):   # [V49] 유효 상자 — 없으면 자유 배치 치수 사용
                                        _b0 = str((_plan_items.get(r["품목코드"], {}) or {}).get("box") or r.get("기본상자") or "")
                                        if not _b0 and r["품목코드"] in _free_live:
                                            _b0 = "자유:" + r["품목코드"]
                                        return _b0
                                    def _bw_key(r):
                                        return (-_dims_p.get(_eff_box(r), (0, 0))[0], r["품목코드"])
                                    for r in sorted(_gi, key=_bw_key):
                                        if not _aq_use(r["품목코드"]): continue   # [V48] 공급 제외 반영
                                        _seq.append((r["품목코드"], g, _eff_box(r)))
                                # [V53] ① 표준 위치(섹션·단) 우선 — 랙 명칭이 '섹션NN'(또는 'NN')과 일치하면 그 자리에
                                _std_pre9 = {}
                                _rk_by_nm9 = {rk["명칭"]: rk for rk in _rk_list}
                                for _c9s, _g9s, _b9s in _seq:
                                    _r9s = _aq_by_code.get(_c9s, {}) or {}
                                    _sec9 = str(_r9s.get("섹션", "") or "").strip()
                                    try: _sh9s = int(float(_r9s.get("단") or 0))
                                    except Exception: _sh9s = 0
                                    if not _sec9 or _sh9s <= 0: continue
                                    for _cand9 in (f"섹션{_sec9}", _sec9):
                                        _rk9s = _rk_by_nm9.get(_cand9)
                                        if _rk9s and _sh9s <= len(_rk9s["단높이"]):
                                            _std_pre9[_c9s] = (_cand9, _sh9s); break
                                # [V53] ② 루퍼젯 본품(루퍼젯팩)은 가운데 랙 중앙 단 우선
                                _ctr9 = [_c9s for _c9s, _g9s, _b9s in _seq
                                         if _b9s == "루퍼젯팩" and _c9s not in _std_pre9]
                                def _ch_auto9(c, rk, sh):   # [V59] 시험 패킹도 렌더와 같은 열힌트 사용
                                    _r0 = _aq_by_code.get(c, {}) or {}
                                    _se0 = str(_r0.get("섹션", "") or "").strip()
                                    try: _sd0 = int(float(_r0.get("단") or 0))
                                    except Exception: _sd0 = 0
                                    if _se0 and _sd0 == sh and rk in (f"섹션{_se0}", _se0):
                                        return AQ_COL_ORD.get(str(_r0.get("열", "") or "").strip(), 1)
                                    return 1
                                # [V67] 기존 상자수 보존 = 현재 인스턴스 총 개수(분할 포함) — 없으면 표준 상자수
                                _cnt_old9 = {}
                                for _x9 in st.session_state.get(_inst_key, []):
                                    _cd9 = str(_x9.get("code"))
                                    _cnt_old9[_cd9] = _cnt_old9.get(_cd9, 0) + 1
                                def _nf_auto9(c):
                                    return _cnt_old9.get(c, 0) or aq_std_n_of(c)
                                _asg_new, _unp = aq_auto_place(_rk_list, _seq, _dims_p, group_order=_pg,
                                                               pre=_std_pre9, center_codes=_ctr9,
                                                               colhint=_ch_auto9, n_of=_nf_auto9)
                                # [V67] 결과를 인스턴스 좌표로 확정(패킹은 지금 1회만) — 이후 리런은 재계산 없음.
                                #  ⚠ 자동배치는 '누를 때만' 기존 수동 배치(드래그·적층 포함)를 전부 덮어쓴다.
                                _meta9 = {c: (g, b) for c, g, b in _seq}
                                _sq_by9 = {}
                                for _c9a, (_rk9a, _sh9a) in _asg_new.items():
                                    _g9a, _b9a = _meta9.get(_c9a, ("(미지정)", ""))
                                    _wh9a = _dims_p.get(_b9a)
                                    if not _wh9a: continue
                                    for _ in range(max(1, int(_nf_auto9(_c9a) or 1))):
                                        _sq_by9.setdefault((_rk9a, _sh9a), []).append(
                                            (_c9a, _g9a, _b9a, _wh9a[0], _wh9a[1],
                                             _ch_auto9(_c9a, _rk9a, _sh9a)))
                                for _k9a in _sq_by9:
                                    _sq_by9[_k9a] = aq_canon_seq(_sq_by9[_k9a], _pg)
                                st.session_state[_inst_key] = aq_instances_from_seqs(_sq_by9, _rk_all)
                                st.session_state[_ver_key] += 1
                                st.session_state[f"aq_unp_{sel_site}"] = _unp
                                st.rerun()
                        with ca2:
                            _unp_l = st.session_state.get(f"aq_unp_{sel_site}", [])
                            if _unp_l:
                                st.warning(f"미배치 {len(_unp_l)}건(상자 미지정·공간 부족): {', '.join(_unp_l[:8])}{' 외' if len(_unp_l) > 8 else ''}")
                        with st.expander("✏️ 세부 조정 — 품목별 랙·단·상자·줄 (자동배치 결과 수정)", expanded=False):
                            # [V67] 이 표는 인스턴스(상자 좌표) 상태의 요약 뷰 — 편집하면 아래 diff가
                            #  그 품목의 본 자리 상자들만 외과적으로 재배치한다(그림 드래그 배치가 정본).
                            _ins_cur9 = st.session_state.get(_inst_key, [])
                            _rows_meta9 = st.session_state.setdefault(_rows_key, {})
                            _bov4 = st.session_state.get(f"aq_boxov_{sel_site}", {})
                            _agg9, _spl9 = aq_inst_derive_assign(_ins_cur9, _rows_meta9)
                            _ibox9 = {}
                            for _x9 in _ins_cur9:   # 코드→배치된 상자(인스턴스가 정본)
                                _ibox9.setdefault(str(_x9.get("code")), str(_x9.get("box") or ""))
                            _rows_asg = []
                            for g in _pg:
                                for r in aq_items:
                                    if (r.get("진열분류") or "(미지정)") != g: continue
                                    if not _aq_use(r["품목코드"]): continue   # [V48] 공급 제외 반영
                                    _c4 = r["품목코드"]
                                    _b4 = _ibox9.get(_c4, "")
                                    if _b4.startswith("자유:"): _b4 = "(자유)"
                                    if not _b4 and _c4 in _bov4: _b4 = str(_bov4[_c4])   # [V54] 더블클릭 상자 변경
                                    if not _b4 and edited_plan is not None:   # [V49] 진열 계획 편집값
                                        _mb4 = edited_plan.loc[edited_plan["품목코드"] == _c4, "상자"]
                                        if len(_mb4): _b4 = str(_mb4.iloc[0] or "").strip()
                                    if not _b4:
                                        _b4 = str((_plan_items.get(_c4, {}) or {}).get("box") or r.get("기본상자") or "")
                                    if not _b4 and _c4 in _free_live: _b4 = "(자유)"   # [V49] 자유 배치 표시
                                    _d4 = _agg9.get(_c4) or {}
                                    _rows_asg.append({"품목코드": _c4, "품목명": str(r.get("품목명_AQ", "") or ""), "분류": g,
                                                      "상자": _b4, "랙": str(_d4.get("rack") or ""),
                                                      "단": int(_d4.get("shelf") or 0),
                                                      "줄": int(_rows_meta9.get(_c4, 1) or 1),
                                                      "상자수": int(_d4.get("n") or 1)})
                            # [V54] 자유 배치 등록 품목은 분류 미선택/미지정이어도 표에 포함 — 랙·단 지정 가능해야 배치됨
                            _added4 = {rp["품목코드"] for rp in _rows_asg}
                            for _cf4 in _free_live:
                                if _cf4 in _added4: continue
                                _rf4 = _aq_by_code.get(_cf4, {}) or {}
                                _df4 = _agg9.get(_cf4) or {}
                                _rows_asg.append({"품목코드": _cf4, "품목명": str(_rf4.get("품목명_AQ", "") or _cf4),
                                                  "분류": str(_rf4.get("진열분류", "") or "(미지정)"),
                                                  "상자": "(자유)", "랙": str(_df4.get("rack") or ""),
                                                  "단": int(_df4.get("shelf") or 0),
                                                  "줄": int(_rows_meta9.get(_cf4, 1) or 1),
                                                  "상자수": int(_df4.get("n") or 1)})
                            _base9 = {rp["품목코드"]: (rp["랙"], rp["단"], rp["줄"], rp["상자수"], rp["상자"])
                                      for rp in _rows_asg}   # [V67] 표 diff 기준선(이 리런의 뷰 원본)
                            _rk_names = [rk["명칭"] for rk in _rk_all]   # [V51] 가상랙 포함
                            _box_opts4 = sorted(set(aq_box_names) | {rp["상자"] for rp in _rows_asg if rp["상자"] and rp["상자"] != "(자유)"})
                            df_asg = st.data_editor(
                                pd.DataFrame(_rows_asg), hide_index=True, height=300,
                                key=f"aq_asg_ed_{sel_site}_{st.session_state[_ver_key]}",
                                disabled=["품목코드", "품목명", "분류"],
                                column_config={
                                    "상자": st.column_config.SelectboxColumn(   # [V49] 농협별 상자 변경
                                        "상자", options=[""] + _box_opts4 + ["(자유)"],
                                        help="농협 상황에 따라 상자 변경 가능 — 변경 즉시 배치 그림·저장에 반영"),
                                    "랙": st.column_config.SelectboxColumn("랙", options=[""] + _rk_names),
                                    "단": st.column_config.SelectboxColumn(   # [V48] 드롭다운 선택
                                        "단", options=list(range(0, (max(len(rk["단높이"]) for rk in _rk_all) if _rk_all else 8) + 1)),
                                        help="0=미배치 · 1=최하단"),
                                    "줄": st.column_config.SelectboxColumn(   # [V49] 깊이 방향 줄수
                                        "줄", options=[1, 2, 3, 4],
                                        help="깊이 방향 줄수 — 탑뷰에 반영 (예: 루퍼젯 팩은 1단 2줄 가능)"),
                                    "상자수": st.column_config.SelectboxColumn(   # [V51] 전면 상자수
                                        "상자수", options=[1, 2, 3, 4, 5, 6, 7, 8],
                                        help="정면(전면)에 놓는 상자 수 — 그림 더블클릭 복제/삭제와 연동"),
                                })
                        # ── [V67] 표 편집 diff → 인스턴스 외과 적용 (표는 뷰 — 리런마다 재계산하지 않음) ──
                        _rk_by9v = {rk["명칭"]: rk for rk in _rk_all}
                        def _shelfh9v(rk, sh):
                            _r9v = _rk_by9v.get(str(rk))
                            try:
                                return _r9v["단높이"][int(sh) - 1] \
                                    if _r9v and 0 < int(sh) <= len(_r9v["단높이"]) else 0
                            except Exception:
                                return 0
                        _tbl_chg9 = False
                        _tbl_errs9 = []
                        for _, _row4 in df_asg.iterrows():
                            _c5 = str(_row4["품목코드"])
                            _bl5 = _base9.get(_c5)
                            if _bl5 is None: continue
                            _rk5 = str(_row4["랙"] or "").strip()
                            try: _sh5 = int(_row4["단"] or 0)
                            except Exception: _sh5 = 0
                            try: _rw5 = max(1, int(_row4.get("줄") or 1))
                            except Exception: _rw5 = 1
                            try: _n5 = max(0, int(_row4.get("상자수") or 0))
                            except Exception: _n5 = 1
                            _b5 = str(_row4["상자"] or "").strip()
                            if (_rk5, _sh5, _rw5, _n5, _b5) == _bl5: continue
                            _tbl_chg9 = True
                            if _rw5 != _bl5[2]:   # 줄수(깊이) — 탑뷰 표시 메타
                                _rows_meta9[_c5] = _rw5
                            if _b5 != _bl5[4] and _b5 and _b5 != "(자유)":   # 상자 변경(코드 단위 속성)
                                if _b5 not in _dims_p:
                                    _tbl_errs9.append(f"{_c5}: 상자 '{_b5}' 치수 미등록 — 변경 불가")
                                else:
                                    st.session_state.setdefault(f"aq_boxov_{sel_site}", {})[_c5] = _b5
                                    for _x5 in _ins_cur9:
                                        if str(_x5.get("code")) == _c5 and not str(_x5.get("box") or "").startswith("자유:"):
                                            _x5["box"] = _b5
                                    aq_inst_normalize(_ins_cur9)
                            if (_rk5, _sh5) != (_bl5[0], _bl5[1]) or _n5 != _bl5[3]:
                                # 본 자리(구 랙·단) 인스턴스만 제거 후 새 자리에 n개 재배치 — 분할 자리는 유지
                                _eff5 = _b5 or _bl5[4]
                                if _eff5 == "(자유)" or (not _eff5 and _c5 in _free_live):
                                    _eff5 = "자유:" + _c5
                                _old5 = [x for x in _ins_cur9 if str(x.get("code")) == _c5
                                         and (str(x.get("rack")), int(x.get("shelf") or 0)) == (_bl5[0], _bl5[1])]
                                if _rk5 and _sh5 > 0 and _n5 > 0:
                                    if _eff5 not in _dims_p:
                                        _tbl_errs9.append(f"{_c5}: 상자 '{_eff5 or '(미지정)'}' 치수 미등록 — 배치 불가")
                                    else:
                                        for _x5 in _old5: _ins_cur9.remove(_x5)
                                        aq_inst_place_code(_ins_cur9, _c5, _eff5, _rk5, _sh5, _n5,
                                                           dims=_dims_p, shelf_h=_shelfh9v(_rk5, _sh5))
                                else:   # 랙 비움·단 0·상자수 0 → 본 자리 제거(미배치)
                                    for _x5 in _old5: _ins_cur9.remove(_x5)
                                    aq_inst_normalize(_ins_cur9)
                        if _tbl_errs9:
                            st.session_state["aq_op_errs"] = (st.session_state.get("aq_op_errs") or []) + _tbl_errs9
                        if _tbl_chg9:
                            st.session_state[_inst_key] = _ins_cur9
                            st.session_state[_ver_key] += 1
                            st.rerun()
                        # ── [V67] 렌더 준비 — 저장된 좌표 그대로 그린다(패킹·재계산 없음) ──
                        _ins_eff9 = st.session_state.get(_inst_key, [])
                        # [V49] 호버 툴팁 정보(품목명·규격·상자·최대수량) + [V67] 분류(색)·자유 도형 메타
                        _info_map = {}
                        for _x9 in _ins_eff9:
                            _c9 = str(_x9.get("code"))
                            if _c9 in _info_map: continue
                            _r9 = _aq_by_code.get(_c9, {})
                            _bx9i = str(_x9.get("box") or "")
                            _m9 = {"name": str(_r9.get("품목명_AQ", "") or _c9),
                                   "spec": str(_r9.get("규격_AQ", "") or ""),
                                   "grp": str(_r9.get("진열분류") or "(미지정)")}
                            _fc9 = _free_live.get(_c9)
                            if _fc9 and _bx9i.startswith("자유:"):
                                _m9["box"] = "자유 배치"
                                _m9["cap"] = str(_fc9.get("qty") or "")
                                _m9["shape"] = _fc9.get("shape") or "사각"
                                if _m9["shape"] == "이미지":
                                    _iso9 = str(_r9.get("이미지ISO", "") or "").strip()
                                    _uri9 = aq_iso_data_uri(_iso9) if _iso9 else ""
                                    if _uri9: _m9["img"] = _uri9
                                    else: _m9["shape"] = "사각"
                            else:
                                _m9["box"] = _bx9i
                                try: _m9["cap"] = str(aq_caps.get(_c9, {}).get(_bx9i, ("", ""))[0] or "")
                                except Exception: _m9["cap"] = ""
                                if not _m9["cap"]:
                                    _m9["cap"] = "없음"   # [V54] 상자 수용량 기록 없음 → '수량정보 없음' 표기
                                if _bx9i == "루퍼젯팩":   # [V53] 루퍼젯 본품 — 박스 전면에 뒷표기 노출
                                    _nm_t9 = str(_r9.get("품목명_AQ", "") or "").split()
                                    _m9["tag"] = _nm_t9[-1] if _nm_t9 else ""
                            _info_map[_c9] = _m9
                        if st.session_state.get("aq_op_errs"):   # [V65] 조작 반영 중 실패한 것 노출(조용히 사라지지 않게)
                            _oe = st.session_state.pop("aq_op_errs")
                            st.error("⚠️ 일부 배치 조작이 반영되지 않았습니다(무시되고 넘어감) — 아래 확인:\n- " + "\n- ".join(_oe[:8]))
                        _view_rks = st.multiselect("표시할 랙 (기본 전체 — V1 도면처럼 나란히)", _rk_names, default=_rk_names, key=f"aq_rk_view_{sel_site}")
                        _rk_show = [rk for rk in _rk_all if rk["명칭"] in (_view_rks or _rk_names)]   # [V51] 가상랙 포함
                        import streamlit.components.v1 as _components9   # [V49] 호버 툴팁은 iframe에서만 동작
                        # [V67] 렌더 = 인스턴스 좌표 그대로 (mstack·seq 패킹 경로 폐기)
                        _svg_all9 = aq_racks_svg_all(_rk_show, {}, info=_info_map,
                                                     instances=_ins_eff9, dims=_dims_p)
                        if _svg_all9:
                            _nonce9 = f"{st.session_state['aq_ops_salt']}|{sel_site}"   # [V53] ver 제외 — 늦은 조작 유실 방지(op id 중복 차단)
                            _ack9 = str(st.session_state.get(f"aq_ack_{sel_site}", "") or "")   # [V67] 마지막 ACK 배치 id
                            _html9, _hpx9 = aq_svg_hover_html(_svg_all9, interactive=True, nonce=_nonce9,
                                                              boxes=_box_opts4, ack=_ack9)   # [V51/V54/V67]
                            _components9.html(_html9, height=min(_hpx9 + 34, 960), scrolling=True)
                            _cb1, _cbU, _cbR, _cb2 = st.columns([3.4, 1, 1, 1.5])
                            with _cb1:
                                st.caption("🖱️ 호버=정보 · **드래그=상자 1개 이동**(각 상자가 자기 좌표를 기억 — 반영 후에도 그 자리 유지) · **빈 곳 드래그=영역 다중선택 · Shift+클릭=추가 선택**(선택 후 드래그=일괄 이동, Delete=일괄 삭제) · "
                                           "**더블클릭=복제/삭제/상자 변경** · **랙 이름(≡)이나 랙 바탕을 더블클릭 = 그 섹션(랙) 복제/삭제**(랙 구성 표·견적·저장에 자동 반영) · "
                                           "**⛶ 전체화면=꽉 차게 확대+전 상자 품명·규격**(전체화면에서도 이동·삭제 가능). "
                                           "🧱 **다른 상자 위에 올려 놓으면 그 열 위에 적층**(좌표로 저장되어 유지 · 단높이 초과 시 오류로 알려줌). "
                                           "조작은 그림에 즉시 표시되고 **4초 뒤(전체화면은 종료 시) 일괄 반영** — 바로 반영하려면 🔄.")
                            _un_st9 = st.session_state.get(f"aq_undo_{sel_site}") or []
                            _rd_st9 = st.session_state.get(f"aq_redo_{sel_site}") or []
                            with _cbU:
                                if st.button(f"↩️ 되돌리기({len(_un_st9)})", key=f"aq_undo_btn_{sel_site}",
                                             disabled=not _un_st9,
                                             help="그림 조작(이동·복제·삭제·상자 변경·랙 순서)을 한 단계 되돌립니다."):
                                    _rd9 = st.session_state.setdefault(f"aq_redo_{sel_site}", [])
                                    _rd9.append({"inst": [dict(x) for x in st.session_state.get(_inst_key, [])],
                                                 "boxov": dict(st.session_state.get(f"aq_boxov_{sel_site}", {})),
                                                 "rkord": list(st.session_state.get(f"aq_rkord_{sel_site}") or []),
                                                 "rows": dict(st.session_state.get(_rows_key, {}) or {}),
                                                 "racks": df_racks_eff.to_dict("records")})   # [V67/V71]
                                    _sn9 = _un_st9.pop()
                                    st.session_state[_inst_key] = [dict(x) for x in _sn9.get("inst", [])]
                                    st.session_state[f"aq_boxov_{sel_site}"] = _sn9["boxov"]
                                    st.session_state[f"aq_rkord_{sel_site}"] = _sn9["rkord"]
                                    st.session_state[_rows_key] = dict(_sn9.get("rows", {}) or {})
                                    _aq_rack_restore9(_sn9.get("racks"))   # [V71] 랙 구성 표 복원
                                    st.session_state[_ver_key] += 1
                                    st.rerun()
                            with _cbR:
                                if st.button(f"↪️ 다시 실행({len(_rd_st9)})", key=f"aq_redo_btn_{sel_site}",
                                             disabled=not _rd_st9,
                                             help="되돌린 조작을 다시 적용합니다."):
                                    _un9b = st.session_state.setdefault(f"aq_undo_{sel_site}", [])
                                    _un9b.append({"inst": [dict(x) for x in st.session_state.get(_inst_key, [])],
                                                  "boxov": dict(st.session_state.get(f"aq_boxov_{sel_site}", {})),
                                                  "rkord": list(st.session_state.get(f"aq_rkord_{sel_site}") or []),
                                                  "rows": dict(st.session_state.get(_rows_key, {}) or {}),
                                                  "racks": df_racks_eff.to_dict("records")})   # [V67/V71]
                                    _sn9 = _rd_st9.pop()
                                    st.session_state[_inst_key] = [dict(x) for x in _sn9.get("inst", [])]
                                    st.session_state[f"aq_boxov_{sel_site}"] = _sn9["boxov"]
                                    st.session_state[f"aq_rkord_{sel_site}"] = _sn9["rkord"]
                                    st.session_state[_rows_key] = dict(_sn9.get("rows", {}) or {})
                                    _aq_rack_restore9(_sn9.get("racks"))   # [V71] 랙 구성 표 복원
                                    st.session_state[_ver_key] += 1
                                    st.rerun()
                            with _cb2:
                                if st.button("🔄 배치 조작 반영", key=f"aq_ops_apply_{sel_site}",
                                             help="그림에서 드래그·더블클릭한 조작을 표와 배치에 반영합니다."):
                                    st.session_state["aq_ops_bump"] = True   # [V55] 다음 턴에 브리지 재평가
                                    st.rerun()
                            # ── [V69] 배치도 파일 저장 — 캡처 대신 벡터로(확대해도 선명) · 가상랙 제외 ──
                            _ins_real9 = [x for x in _ins_eff9 if str(x.get("rack") or "") != AQ_VIRT]
                            _rk_file9 = [rk for rk in _rk_list if rk["명칭"] != AQ_VIRT]
                            _fd1, _fd2, _fd3 = st.columns([1.5, 1.5, 3])
                            _fstem9 = f"아쿠나리스_배치도_{sel_site}_{datetime.date.today().strftime('%Y%m%d')}"
                            with _fd1:
                                _svg_f9 = _aq_svg_for_file(
                                    aq_racks_svg_all(_rk_file9, {}, per_row=6, scale=0.30, info=_info_map,
                                                     instances=_ins_real9, dims=_dims_p)) if _ins_real9 else ""
                                st.download_button("🖼 배치도 SVG 저장", data=(_svg_f9 or "").encode("utf-8"),
                                                   file_name=f"{_fstem9}.svg", mime="image/svg+xml",
                                                   disabled=not _svg_f9, use_container_width=True,
                                                   key=f"aq_dl_svg_{sel_site}",
                                                   help="벡터 원본 — 확대해도 화질 손실 없음(브라우저·일러스트레이터·한글/워드 삽입 가능). 전 상자 품명·규격 표시.")
                            with _fd2:
                                if st.button("📄 배치도 PDF 만들기", key=f"aq_dl_pdf_go_{sel_site}",
                                             disabled=not _ins_real9, use_container_width=True,
                                             help="A4 가로 1장 벡터 도면 — 인쇄·문서 첨부용."):
                                    try:
                                        st.session_state[f"aq_lay_pdf_{sel_site}"] = aq_layout_pdf_bytes(
                                            sel_site, _rk_file9, _ins_real9, _dims_p, _info_map)
                                    except Exception as _pe9:
                                        st.error(f"배치도 PDF 생성 실패: {aq_err_str(_pe9)}")
                            with _fd3:
                                _lp9 = st.session_state.get(f"aq_lay_pdf_{sel_site}")
                                if _lp9:
                                    st.download_button(f"⬇️ 배치도 PDF ({len(_lp9) // 1024}KB)", data=_lp9,
                                                       file_name=f"{_fstem9}.pdf", mime="application/pdf",
                                                       key=f"aq_dl_pdf_{sel_site}")
                                else:
                                    st.caption("💾 저장하면 이 배치도가 **가이드북 2·3페이지 펼침면**에도 들어갑니다(가상랙 제외).")
                        _leg = " ".join(
                            f'<span style="display:inline-block;width:10px;height:10px;background:{AQ_GROUP_COLORS.get(aq_grp_norm(g), "#9AA0A6")};margin-right:4px;"></span>'
                            f'<span style="font-size:12px;margin-right:10px;">{g}</span>' for g in _pg)
                        st.markdown(_leg, unsafe_allow_html=True)
                        _virt_cnt = len({str(x.get("code")) for x in _ins_eff9 if str(x.get("rack")) == AQ_VIRT})   # [V51/V67]
                        if _virt_cnt:
                            st.info(f"🅥 가상랙 보관 {_virt_cnt}건 — 실제 랙이 아닙니다. 설치 확정 전에 실제 랙으로 옮기거나 단 0(미배치)으로 정리하세요.")
                        # [V67] 좌표 기반 검증 — 렌더와 동일한 좌표로 폭·적층높이·치수미상을 판정(숨김 없음)
                        _over = aq_inst_validate([x for x in _ins_eff9 if str(x.get("rack")) != AQ_VIRT],
                                                 _rk_list, _dims_p)
                        if _over:
                            st.warning("⚠ 배치 검증 — 단높이 조정·상자 변경·자리 이동 필요: " + " / ".join(_over[:6])
                                       + (f" 외 {len(_over) - 6}건" if len(_over) > 6 else ""))
                        elif _ins_eff9:
                            st.success("✅ 배치된 모든 단이 실척 좌표 기준 적합합니다. (열폭 합 ≤ 내측폭 · 적층 높이 ≤ 단높이)")

                        # ── [V49] 탑뷰 — 단 위에서 내려다보기 (깊이 방향 줄 배치) ──
                        with st.expander("🔝 탑뷰 — 단 위에서 내려다보기 (깊이 방향 줄 배치)", expanded=False):
                            _tv_keys = sorted({(str(x.get("rack")), int(x.get("shelf") or 0)) for x in _ins_eff9})
                            if not _tv_keys:
                                st.info("배치된 단이 없습니다 — ⚡ 자동배치 또는 세부 조정에서 랙·단을 지정하세요.")
                            else:
                                _bdep9 = aq_box_depth_map(aq_boxes)
                                _tv_sel = st.selectbox("단 선택", _tv_keys,
                                                       format_func=lambda k: f"{k[0]} · 단{k[1]}", key=f"aq_tv_{sel_site}")
                                _rk_tv = next((x for x in _rk_all if x["명칭"] == _tv_sel[0]), None)   # [V51] 가상랙 포함
                                if _rk_tv and 0 < _tv_sel[1] <= len(_rk_tv["단높이"]):
                                    _dlist9 = _rk_tv.get("단깊이") or []
                                    _dp9 = _dlist9[_tv_sel[1] - 1] if 0 < _tv_sel[1] <= len(_dlist9) else _rk_tv.get("깊이", 450)
                                    _rows_map9 = {c: int(v or 1) for c, v in
                                                  (st.session_state.get(_rows_key) or {}).items()}   # [V67] 줄수 메타
                                    # [V67] 정면과 동일한 인스턴스 좌표 열을 탑뷰에 그대로 사용(재패킹 없음)
                                    _ins_tv9 = [x for x in _ins_eff9
                                                if (str(x.get("rack")), int(x.get("shelf") or 0)) == _tv_sel]
                                    _colsTV, _unkTV = aq_inst_cols(_ins_tv9, _dims_p, _rk_tv["내측폭"])   # [V70]
                                    _cols_tv9 = [(_cx9, _cw9,
                                                  [(str(i9.get("code")),
                                                    str((_info_map.get(str(i9.get("code")), {}) or {}).get("grp") or "(미지정)"),
                                                    str(i9.get("box") or ""), wh9[0], wh9[1])
                                                   for i9, wh9 in _st9])
                                                 for _cx9, _cw9, _st9 in _colsTV]
                                    _svg_tv = aq_shelf_top_svg(_tv_sel[0], _tv_sel[1], _rk_tv["내측폭"],
                                                               _rk_tv["단높이"][_tv_sel[1] - 1], _dp9,
                                                               [], rows_by_code=_rows_map9,
                                                               box_depths=_bdep9, info=_info_map,
                                                               cols=_cols_tv9)
                                    _html_tv, _h_tv = aq_svg_hover_html(_svg_tv)
                                    _components9.html(_html_tv, height=min(_h_tv, 500), scrolling=True)
                                    st.caption("정면도는 맨 앞줄만 보입니다 — 깊이 방향 **줄수**는 세부 조정 표의 '줄' 컬럼으로 지정 "
                                               "(예: 루퍼젯 팩 255×95 → 깊이 450 단에 2줄 이상). 상자 깊이 미등록 시 1줄 전체 깊이로 표시.")
                                else:
                                    st.info("선택한 단 정보를 찾을 수 없습니다.")

                st.markdown("##### 4️⃣ 견적 확인 · 저장")
                _parts2 = 0.0   # [V69] 부속 합계 — 저장 버튼 행의 내부 지표에서도 사용
                if plan_groups and (edited_plan is not None):
                    _bcnt2, _skip2 = {}, []
                    for _, _row in edited_plan.iterrows():
                        if not _aq_use(str(_row["품목코드"])): continue   # [V48] 공급 제외
                        try: _q = int(_row["수량"] or 0)
                        except Exception: _q = 0
                        try: _u = int(_row["지역농협가"] or 0)
                        except Exception: _u = 0
                        if _q <= 0 or _u <= 0:
                            _skip2.append(str(_row["품목코드"])); continue
                        _parts2 += _q * _u
                        _bx2 = str(_row["상자"] or "").strip()
                        if _bx2: _bcnt2[_bx2] = _bcnt2.get(_bx2, 0) + 1
                    _bsum2 = sum(aq_box_price.get(b, 0) * n for b, n in _bcnt2.items())
                    sq1, sq2, sq3, sq4 = st.columns(4)
                    sq1.metric("부속 합계", f"{_parts2:,.0f}원")
                    sq2.metric("상자 하드웨어", f"{_bsum2:,.0f}원")
                    sq3.metric("공급 합계", f"{_parts2 + _bsum2:,.0f}원")
                    sq4.metric("계통2 수수료(참고)", f"-{_parts2 * 0.05:,.0f}원")
                    if _bcnt2:
                        st.caption("상자 구성: " + ", ".join(f"{b}×{n}" for b, n in sorted(_bcnt2.items()))
                                   + " (품목 1종=상자 1개 가정, 상자 단가는 AQ_Boxes 기준)")
                    _n_garo = sum(1 for _, _r2 in edited_plan.iterrows() if str(_r2.get("방향", "")) == "가로")
                    if _n_garo:
                        st.caption(f"↔ 가로 배치 {_n_garo}건 — 깊이 얕은 단용 (전면 폭을 상자 깊이만큼 차지)")
                    if _skip2:
                        st.caption(f"수량/단가 0으로 집계 제외 {len(_skip2)}건")
                    _csv_c1, _csv_c2 = st.columns([1.6, 2.4])
                    with _csv_c1:
                        st.download_button(
                            "⬇️ 사이트 진열계획 CSV",
                            edited_plan.to_csv(index=False).encode("utf-8-sig"),
                            file_name=f"aqunaris_{sel_site}_진열계획.csv", mime="text/csv",
                            key=f"aq_site_csv_{sel_site}", use_container_width=True)
                    with _csv_c2:
                        # [V69] 총괄표의 세부 내역 → 진열 품목 탭으로 바로 이동(그 농협 기준으로 자동 설정)
                        if st.button("🗄️ 이 농협 진열 품목 상세 보기 →", key=f"aq_go_items_{sel_site}",
                                     use_container_width=True,
                                     help="진열 품목 탭으로 이동하며, 배치 기준 사이트를 이 농협으로 자동 설정합니다."):
                            st.session_state["_aq_items_jump"] = sel_site
                            st.session_state["_aq_items_tabjump"] = True
                            st.rerun()

                # ── [V44] 표준 배치 검증 — 랙 단높이 × 상자 치수 × 실배치(V1 위치)로 단별 용량 판정 ──
                with st.expander("📏 표준 배치 검증 (V1 섹션 위치 기준 — 표준화 참고 전용)", expanded=(sel_site == AQ_STD_SITE)):
                    _dims_v = aq_box_dims_map(aq_boxes)
                    _rack_h_map, _inner_by_sec = {}, {}
                    for _, _rr in df_racks_eff.iterrows():   # [V54] 상속 적용본
                        _nm2 = str(_rr.get("명칭") or "")
                        if "섹션" not in _nm2: continue
                        _digits = "".join(ch for ch in _nm2 if ch.isdigit())
                        if not _digits: continue
                        _sec2 = _digits.zfill(2)
                        try:
                            _hs = [int(float(x)) for x in str(_rr.get("단높이mm(콤마구분)") or "").split(",") if str(x).strip()]
                        except Exception:
                            _hs = []
                        if _hs: _rack_h_map[_sec2] = _hs
                        try:
                            _wv = int(float(_rr.get("폭mm") or 0))
                            if _wv > 0: _inner_by_sec[_sec2] = _wv - 38
                        except Exception:
                            pass
                    if not _dims_v:
                        st.info("상자 치수가 없습니다. '📦 상자·수용량' 탭에서 폭·높이를 등록하세요.")
                    elif not _rack_h_map:
                        st.info("랙 구성에 '섹션NN' 명칭의 랙이 없습니다. 📐 표준 시스템 불러오기를 누르면 자동 구성됩니다.")
                    else:
                        _pi_live = dict(_plan_items) if isinstance(_plan_items, dict) else {}
                        if edited_plan is not None:
                            for _, _row in edited_plan.iterrows():
                                _pi_live[str(_row["품목코드"])] = {"box": str(_row["상자"] or "").strip()}
                        _vr = aq_capacity_rows(aq_items, _pi_live, _dims_v, _rack_h_map, inner_by_sec=_inner_by_sec)
                        _n_ok = sum(1 for v in _vr if v["판정"].startswith("✓"))
                        _n_unk = sum(v["미지정"] for v in _vr)
                        cv1, cv2, cv3 = st.columns(3)
                        cv1.metric("검증 단(선반)", f"{len(_vr)}")
                        cv2.metric("적합", f"{_n_ok} / {len(_vr)}")
                        cv3.metric("상자 미지정 품목", f"{_n_unk}")
                        if _n_ok == len(_vr) and _vr:
                            st.success("✅ 전 단 적합 — 표준 시스템과 동일한 배치가 재현됩니다. (Σ상자폭÷층수 ≤ 내측폭)")
                        elif _vr:
                            st.warning("⚠ 초과 단이 있습니다. 상자 변경(가로/작은 상자) 또는 단높이 조정을 검토하세요.")
                        _only_bad = st.checkbox("초과 단만 보기", value=False, key=f"aq_v_bad_{sel_site}")
                        _vshow = [v for v in _vr if not _only_bad or v["판정"].startswith("⚠")]
                        st.dataframe(pd.DataFrame(_vshow), hide_index=True, height=300)

                # [V69] 저장 행 — 왼쪽 저장 버튼, 같은 레벨 **오른쪽 끝**에 내부 지표(눈에 띄지 않게)
                _sv_c1, _sv_c2 = st.columns([6, 1])
                with _sv_c2:
                    if aq_can("aq_profit", strict=True) and (edited_plan is not None):
                        with st.expander("⋯", expanded=False):   # 라벨 최소화 — 현장 시연 화면 보호
                            _buy_sum, _n_nobuy = 0.0, 0
                            for _, _row in edited_plan.iterrows():
                                if not _aq_use(str(_row["품목코드"])): continue
                                try: _q9 = int(_row["수량"] or 0)
                                except Exception: _q9 = 0
                                if _q9 <= 0: continue
                                _p9 = prod_by_code.get(str(_row["품목코드"]), {})
                                try: _b9 = float(_p9.get("price_buy") or 0)
                                except Exception: _b9 = 0.0
                                if _b9 <= 0:
                                    _n_nobuy += 1; continue
                                _buy_sum += _b9 * _q9
                            _rev9 = _parts2
                            _profit9 = _rev9 - _buy_sum
                            _net9 = _rev9 * 0.95 - _buy_sum
                            st.caption("내부 지표 (권한 계정 전용)")
                            pm1, pm2, pm3, pm4 = st.columns(4)
                            pm1.metric("매입 합계", f"{_buy_sum:,.0f}원")
                            pm2.metric("이익(수수료 전)", f"{_profit9:,.0f}원 ({(_profit9 / _rev9 * 100 if _rev9 else 0):.1f}%)")
                            pm3.metric("계통2 반영 순이익", f"{_net9:,.0f}원")
                            pm4.metric("매입가 미등록", f"{_n_nobuy}건")
                            st.caption("이익 = 부속 합계(지역농협가) − 매입 합계 · 계통2 반영 = 매출×95% − 매입 (상자·설치·운송비 별도)")
                if _sv_c1.button("💾 사이트 저장 (랙 구성 + 진열 계획)", type="primary",
                                 key=f"aq_site_save_{sel_site}", use_container_width=True):
                    try:
                        _racks_out = []
                        for _, _rr in df_racks_eff.iterrows():   # [V54] 상속 적용본 저장 = 실제 값으로 기록
                            _d = {}
                            for _c in _rack_cols:
                                _v = _rr.get(_c)
                                _d[_c] = "" if (_v is None or (isinstance(_v, float) and pd.isna(_v))) else _v
                            if not any(str(_v).strip() for _v in _d.values()): continue
                            for _c in ["폭mm", "깊이mm", "총높이mm", "단수", "단두께mm"]:   # [V49] 신규 컬럼 포함
                                try: _d[_c] = int(float(_d[_c])) if str(_d[_c]).strip() else ""
                                except Exception: _d[_c] = str(_d[_c])
                            for _c in ["명칭", "단높이mm(콤마구분)", "비고"]:   # [V54] 단깊이 폐지
                                _d[_c] = str(_d[_c])
                            _racks_out.append(_d)
                        _items_out = {}
                        if edited_plan is not None:
                            for _, _row in edited_plan.iterrows():
                                try: _q = int(_row["수량"] or 0)
                                except Exception: _q = 0
                                _bx3 = str(_row["상자"] or "").strip()
                                _ori3 = str(_row.get("방향") or "세로").strip() or "세로"   # [V43]
                                _use3 = bool(_row.get("공급", True))                       # [V48]
                                if _q > 0 or _bx3 or (not _use3):
                                    _items_out[str(_row["품목코드"])] = {"box": _bx3, "qty": _q, "ori": _ori3, "use": _use3}
                        # [V49] 세부 조정 표의 상자 변경 반영 (진열 계획 편집표에 없던 오버라이드 포함)
                        if df_asg is not None:
                            for _, _row8 in df_asg.iterrows():
                                _c8 = str(_row8["품목코드"]); _b8 = str(_row8["상자"] or "").strip()
                                if _b8 == "(자유)": _b8 = ""
                                if _c8 in _items_out:
                                    if _b8 != str(_items_out[_c8].get("box", "")).strip():
                                        _items_out[_c8]["box"] = _b8
                                else:
                                    _o8 = _plan_items.get(_c8, {}) if isinstance(_plan_items.get(_c8, {}), dict) else {}
                                    _def8 = str(_o8.get("box") or (_aq_by_code.get(_c8, {}) or {}).get("기본상자") or "").strip()
                                    if _b8 != _def8:
                                        try: _q8 = int(_o8.get("qty") or 0)
                                        except Exception: _q8 = 0
                                        _items_out[_c8] = {"box": _b8, "qty": _q8, "ori": str(_o8.get("ori") or "세로"),
                                                           "use": (_o8.get("use", True) is not False)}
                        _new_plan = {"groups": plan_groups, "items": _items_out,
                                     "updated": datetime.datetime.now().strftime("%Y-%m-%d %H:%M")}
                        # [V49] 자유 배치 저장 (편집표가 없던 리런에서는 기존값 보존)
                        _new_plan["free"] = _free_live if df_free is not None else _free_cur
                        # [V67] 배치 저장 = 상자 인스턴스 좌표(schema 2) — 불러오면 저장 시점 모습 그대로.
                        #  [V68] 시트 셀 50,000자 한도 대응: 좌표는 압축 포맷 inst2(상자명 미저장 — items에서
                        #  재해석), assign/splits는 파생 하위호환(진열품목 탭·인쇄물이 읽음).
                        _ins_sv = st.session_state.get(f"aq_inst_{sel_site}", [])
                        if _ins_sv:
                            _new_plan["schema_version"] = AQ_SCHEMA_V
                            _new_plan["inst2"] = aq_inst_pack(_ins_sv)
                            _asg_dv9, _sp_dv9 = aq_inst_derive_assign(
                                _ins_sv, st.session_state.get(f"aq_rows_{sel_site}") or {})
                            _new_plan["assign"] = _asg_dv9
                            if _sp_dv9:
                                _new_plan["splits"] = _sp_dv9
                        _ord_sv = st.session_state.get(f"aq_rkord_{sel_site}")   # [V55] 랙 순서 저장
                        if _ord_sv:
                            _new_plan["rack_order"] = _ord_sv
                        elif isinstance(_plan_cur.get("rack_order"), list):
                            _new_plan["rack_order"] = _plan_cur["rack_order"]
                        # [V68] 시트 셀 한도(50,000자) 가드 — 공백 없는 JSON + 한도 임박 시
                        #  하위호환 필드부터 단계 생략(좌표 inst2는 항상 보존), 그래도 초과면 저장 중단·안내.
                        _SEP9 = (",", ":")
                        _pj9 = json.dumps(_new_plan, ensure_ascii=False, separators=_SEP9)
                        if len(_pj9) > 49500 and "splits" in _new_plan:
                            _new_plan.pop("splits", None)
                            _pj9 = json.dumps(_new_plan, ensure_ascii=False, separators=_SEP9)
                            st.warning("배치JSON이 커서 하위호환 splits를 생략하고 저장합니다 — 배치 좌표는 전부 보존됩니다.")
                        if len(_pj9) > 49500 and "assign" in _new_plan:
                            _new_plan.pop("assign", None)
                            _pj9 = json.dumps(_new_plan, ensure_ascii=False, separators=_SEP9)
                            st.warning("배치JSON이 커서 하위호환 assign을 생략하고 저장합니다 — 배치 좌표는 전부 보존되지만, "
                                       "진열품목·인쇄물의 '확정 배치 기준' 필터가 이 사이트에선 동작하지 않을 수 있습니다.")
                        if len(_pj9) > 50000:
                            st.error(f"저장 불가: 배치JSON {len(_pj9):,}자 — 시트 셀 한도(50,000자) 초과. "
                                     "배치 품목 수를 줄이거나 다음 세션에서 셀 분할 저장을 요청하세요.")
                        else:
                            for s in aq_sites_all:
                                if str(s.get("농협명", "")).strip() == sel_site:
                                    s["랙구성JSON"] = json.dumps(_racks_out, ensure_ascii=False, separators=_SEP9)
                                    s["배치JSON"] = _pj9
                            aq_save_sites(aq_sites_all)
                            aq_load_all.clear()
                            st.session_state.pop(f"aq_racks_ov_{sel_site}", None)   # [V71] 시트와 동기화됨 — 랙 오버라이드 해제
                            st.success(f"저장 완료 (AQ_Sites 시트 · 배치JSON {len(_pj9):,}자/50,000)")
                            time.sleep(0.5); st.rerun()
                    except Exception as e:
                        st.error(f"저장 실패: {aq_err_str(e)}")

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

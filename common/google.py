# -*- coding: utf-8 -*-
"""[공용] 폰트 · 구글 서비스 · 드라이브 · 이미지 — app.py(V107) L100-486 을 그대로 옮겼다(로직 무변경).
V15 §2 보존 규칙 7·8·9(드라이브는 _get_ds() · 깊은 파일맵 · 이미지 해석 우선순위)는 이 파일에서 지킨다.
"""
import os
import io
import sys
import math
import json
import time
import base64
import tempfile
import datetime
import streamlit as st
from PIL import Image
import gspread
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload

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

def refresh_services():
    """[분리 · 2026-09-11] 원본은 **매 실행(rerun)마다** `gc, drive_service = get_google_services()` 를 돌렸다
    (캐시 TTL 1800초가 지나면 다시 인증 — V15 §2-7). 모듈로 옮기면 import 때 한 번만 돈다 — 원래 동작을 지키려고
    입구 파일이 매 실행 이것을 부른다. star import 로 같은 객체를 받아 간 모듈(common.db · common.auth ·
    aqunaris.sheets)의 전역도 함께 바꿔 준다. 반환 (gc, drive_service)."""
    global gc, drive_service
    old_gc = gc
    new = get_google_services()
    gc, drive_service = new
    for _m in list(sys.modules.values()):
        _d = getattr(_m, "__dict__", None)
        if isinstance(_d, dict) and "drive_service" in _d and _d.get("gc") is old_gc:
            _d["gc"], _d["drive_service"] = new
    return new

__all__ = [n for n in list(globals()) if not n.startswith("__")]   # star import 로 밑줄 이름까지 넘긴다

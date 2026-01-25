import os
import streamlit as st
import pandas as pd
import math
import io
import base64
import tempfile
import json
import datetime
import time
from PIL import Image
from fpdf import FPDF

# 구글 연동 라이브러리
import gspread
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload

# ==========================================
# 1. 설정 및 구글 연동 유틸리티
# ==========================================
FONT_FILE = "NanumGothic.ttf"
FONT_BOLD_FILE = "NanumGothicBold.ttf"
# 폰트 다운로드 URL
FONT_URL = "https://github.com/google/fonts/raw/main/ofl/nanumgothic/NanumGothic-Regular.ttf"

if not os.path.exists(FONT_FILE):
    import urllib.request
    try: urllib.request.urlretrieve(FONT_URL, FONT_FILE)
    except: pass

# --- 구글 인증 및 서비스 연결 ---
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive"
]

@st.cache_resource
def get_google_services():
    """구글 인증 및 서비스 객체 생성 (캐싱)"""
    try:
        # st.secrets에서 정보 가져오기
        creds_dict = dict(st.secrets["gcp_service_account"])
        creds = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
        
        # Gspread (시트) 클라이언트
        gc = gspread.authorize(creds)
        
        # Drive API 클라이언트
        drive_service = build('drive', 'v3', credentials=creds)
        
        return gc, drive_service
    except Exception as e:
        st.error(f"구글 서비스 인증 실패: {e}")
        return None, None

gc, drive_service = get_google_services()

# --- 구글 드라이브 함수 ---
DRIVE_FOLDER_NAME = "Looperget_Images"

def get_or_create_drive_folder():
    """이미지 저장용 폴더 ID 찾기 또는 생성"""
    if not drive_service: return None
    try:
        query = f"name='{DRIVE_FOLDER_NAME}' and mimeType='application/vnd.google-apps.folder' and trashed=false"
        results = drive_service.files().list(q=query, fields="files(id)").execute()
        files = results.get('files', [])
        
        if files:
            return files[0]['id']
        else:
            # 폴더 생성
            file_metadata = {
                'name': DRIVE_FOLDER_NAME,
                'mimeType': 'application/vnd.google-apps.folder'
            }
            folder = drive_service.files().create(body=file_metadata, fields='id').execute()
            return folder.get('id')
    except Exception as e:
        st.error(f"드라이브 폴더 오류: {e}")
        return None

def upload_image_to_drive(file_obj, filename):
    """이미지를 드라이브에 업로드하고 파일명 반환"""
    folder_id = get_or_create_drive_folder()
    if not folder_id: return None
    
    try:
        file_metadata = {
            'name': filename,
            'parents': [folder_id]
        }
        media = MediaIoBaseUpload(file_obj, mimetype=file_obj.type, resumable=True)
        drive_service.files().create(body=file_metadata, media_body=media, fields='id').execute()
        return filename
    except Exception as e:
        st.error(f"업로드 실패: {e}")
        return None

@st.cache_data(ttl=3600)
def get_image_from_drive(filename):
    """드라이브에서 파일명으로 이미지 다운로드 후 Base64 반환 (캐싱됨)"""
    if not filename or not drive_service: return None
    try:
        # 폴더 내 검색
        folder_id = get_or_create_drive_folder()
        query = f"name='{filename}' and '{folder_id}' in parents and trashed=false"
        results = drive_service.files().list(q=query, fields="files(id)").execute()
        files = results.get('files', [])
        
        if not files: return None
        
        file_id = files[0]['id']
        request = drive_service.files().get_media(fileId=file_id)
        # 작은 파일은 바로 다운로드
        downloader = request.execute()
        
        img = Image.open(io.BytesIO(downloader))
        img = img.convert('RGB')
        img.thumbnail((300, 225))
        buffer = io.BytesIO()
        img.save(buffer, format="JPEG")
        return f"data:image/jpeg;base64,{base64.b64encode(buffer.getvalue()).decode()}"
    except Exception:
        return None

# --- 구글 시트 함수 ---
SHEET_NAME = "Looperget_DB"

def init_db():
    """DB 시트 연결 및 초기화"""
    if not gc: return None, None
    try:
        sh = gc.open(SHEET_NAME)
    except gspread.exceptions.SpreadsheetNotFound:
        try:
            sh = gc.create(SHEET_NAME)
            # 초기 시트 생성
            sh.add_worksheet(title="Products", rows=100

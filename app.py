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
            sh.add_worksheet(title="Products", rows=100, cols=20)
            sh.add_worksheet(title="Sets", rows=100, cols=10)
            # 헤더 추가
            sh.worksheet("Products").append_row(list(COL_MAP.keys()))
            sh.worksheet("Sets").append_row(["세트명", "카테고리", "하위분류", "이미지파일명", "레시피JSON"])
        except Exception as e:
            st.error(f"시트 생성 실패: {e}")
            return None, None

    # --- 시트 연결 확인용 코드 ---
    if sh:
        st.sidebar.success(f"현재 연결된 시트: {sh.title}")
        st.sidebar.markdown(f"👉 [구글 시트 바로가기]({sh.url})")
    
    # 워크시트 가져오기 (없으면 생성)
    try: ws_prod = sh.worksheet("Products")
    except: ws_prod = sh.add_worksheet(title="Products", rows=100, cols=20)
    
    try: ws_sets = sh.worksheet("Sets")
    except: ws_sets = sh.add_worksheet(title="Sets", rows=100, cols=10)
            
    return ws_prod, ws_sets

def load_data_from_sheet():
    """시트에서 데이터 읽어오기"""
    ws_prod, ws_sets = init_db()
    if not ws_prod or not ws_sets: return DEFAULT_DATA
    
    data = {"config": {"password": "1234"}, "products": [], "sets": {}}
    
    # 1. Products 로드
    try:
        prod_records = ws_prod.get_all_records()
        for rec in prod_records:
            new_rec = {}
            for k, v in rec.items():
                if k in COL_MAP:
                    # [수정] 품목코드 5자리 강제 변환 (00200 유지)
                    if k == "품목코드":
                        new_rec[COL_MAP[k]] = str(v).zfill(5)
                    else:
                        new_rec[COL_MAP[k]] = v
            
            # 이미지 처리
            if "image" in new_rec and new_rec["image"]:
                pass 
            data["products"].append(new_rec)
    except Exception as e:
        st.error(f"🚨 데이터 로드 오류 발생: {e}")

    # 2. Sets 로드
    try:
        set_records = ws_sets.get_all_records()
        for rec in set_records:
            cat = rec["카테고리"]
            name = rec["세트명"]
            sub = rec["하위분류"]
            img = rec["이미지파일명"]
            recipe_str = rec["레시피JSON"]
            
            if cat not in data["sets"]: data["sets"][cat] = {}
            try:
                recipe = json.loads(recipe_str)
            except:
                recipe = {}
                
            data["sets"][cat][name] = {
                "recipe": recipe,
                "image": img,
                "sub_cat": sub
            }
    except: pass
            
    return data

def save_products_to_sheet(products_list):
    """제품 리스트 통째로 덮어쓰기"""
    ws_prod, _ = init_db()
    if not ws_prod: return
    
    # DataFrame 변환 후 업로드
    df = pd.DataFrame(products_list)
    
    # [수정] 품목코드 00 채우기 (저장할 때도 확실하게)
    if "code" in df.columns:
        df["code"] = df["code"].astype(str).apply(lambda x: x.zfill(5))

    # 영문 키 -> 한글 키 변환
    df_upload = df.rename(columns=REV_COL_MAP)
    
    # 시트 클리어 후 헤더+데이터 쓰기
    ws_prod.clear()
    ws_prod.update([df_upload.columns.values.tolist()] + df_upload.values.tolist())

def save_sets_to_sheet(sets_dict):
    """세트 데이터를 시트 형식으로 변환 후 저장"""
    _, ws_sets = init_db()
    if not ws_sets: return
    
    rows = []
    header = ["세트명", "카테고리", "하위분류", "이미지파일명", "레시피JSON"]
    rows.append(header)
    
    for cat, items in sets_dict.items():
        for name, info in items.items():
            row = [
                name,
                cat,
                info.get("sub_cat", ""),
                info.get("image", ""),
                json.dumps(info.get("recipe", {}), ensure_ascii=False)
            ]
            rows.append(row)
    
    ws_sets.clear()
    ws_sets.update(rows)


# ==========================================
# 2. PDF 생성 엔진 (Drive 이미지 연동 & 3줄 출력 & 텍스트 삭제)
# ==========================================
class PDF(FPDF):
    def header(self):
        if os.path.exists(FONT_FILE):
            self.add_font('NanumGothic', '', FONT_FILE, uni=True)
            if os.path.exists(FONT_BOLD_FILE):
                self.add_font('NanumGothic', 'B', FONT_BOLD_FILE, uni=True)
            self.set_font('NanumGothic', 'B' if os.path.exists(FONT_BOLD_FILE) else '', 20) 
        else: self.set_font('Helvetica', 'B', 20)
        
        self.cell(0, 15, '견 적 서 (Quotation)', align='C', new_x="LMARGIN", new_y="NEXT")
        self.set_font('NanumGothic', '', 9) if os.path.exists(FONT_FILE) else self.set_font('Helvetica', '', 9)
        self.ln(2)
        self.cell(0, 5, "1. 견적 유효기간: 견적일로부터 15일 이내", ln=True, align='R')
        self.cell(0, 5, "2. 출고: 결재 완료 후 즉시 또는 7일 이내", ln=True, align='R')
        self.ln(5)

    def footer(self):
        self.set_y(-20)
        if os.path.exists(FONT_FILE):
            self.set_font('NanumGothic', 'B' if os.path.exists(FONT_BOLD_FILE) else '', 12)
            self.cell(0, 8, "주식회사 신진켐텍", align='C', ln=True)
            self.set_font('NanumGothic', '', 8)
        else:
            self.set_font('Helvetica', 'B', 12)
            self.cell(0, 8, "SHIN JIN CHEMTECH Co., Ltd.", align='C', ln=True)
            self.set_font('Helvetica', 'I', 8)
        self.cell(0, 5, f'Page {self.page_no()}', align='C')

def create_advanced_pdf(final_data_list, service_items, quote_name, quote_date, form_type, price_labels):
    pdf = PDF()
    pdf.add_page()
    has_font = os.path.exists(FONT_FILE)
    has_bold = os.path.exists(FONT_BOLD_FILE)
    font_name = 'NanumGothic' if has_font else 'Helvetica'
    
    if has_font: 
        pdf.add_font(font_name, '', FONT_FILE, uni=True)
        if has_bold: pdf.add_font(font_name, 'B', FONT_BOLD_FILE, uni=True)
    
    pdf.set_font(font_name, '', 10)

    # 견적명
    pdf.set_font(font_name, 'B' if has_bold else '', 12)
    pdf.cell(120, 10, f"현장명 : {quote_name}", border=0)
    pdf.cell(70, 10, f"견적일 : {quote_date}", border=0, align='R', new_x="LMARGIN", new_y="NEXT")
    pdf.set_font(font_name, '', 10)

    # 헤더
    pdf.set_fill_color(240, 240, 240)
    h_height = 10
    pdf.cell(15, h_height, "IMG", border=1, align='C', fill=True)
    pdf.cell(45, h_height, "품목정보 (명/규격/코드)", border=1, align='C', fill=True) 
    pdf.cell(10, h_height, "단위", border=1, align='C', fill=True)
    pdf.cell(12, h_height, "수량", border=1, align='C', fill=True)

    if form_type == "basic":
        pdf.cell(35, h_height, f"단가 ({price_labels[0]})", border=1, align='C', fill=True)
        pdf.cell(35, h_height, "금액", border=1, align='C', fill=True)
        pdf.cell(38, h_height, "비고", border=1, align='C', fill=True, new_x="LMARGIN", new_y="NEXT")
    else:
        l1, l2 = price_labels[0], price_labels[1]
        pdf.set_font(font_name, '', 8)
        pdf.cell(18, h_height, f"{l1}단가", border=1, align='C', fill=True)
        pdf.cell(22, h_height, f"{l1}금액", border=1, align='C', fill=True)
        pdf.cell(18, h_height, f"{l2}단가", border=1, align='C', fill=True)
        pdf.cell(22, h_height, f"{l2}금액", border=1, align='C', fill=True)
        pdf.cell(15, h_height, "이익금", border=1, align='C', fill=True)
        pdf.cell(13, h_height, "율(%)", border=1, align='C', fill=True, new_x="LMARGIN", new_y="NEXT")
        pdf.set_font(font_name, '', 9)

    sum_qty = 0; sum_a1 = 0; sum_a2 = 0; sum_profit = 0

    for item in final_data_list:
        name = item.get("품목", "")
        spec = item.get("규격", "-")
        code = str(item.get("코드", "")).zfill(5) 
        
        qty = int(item.get("수량", 0))
        img_filename = item.get("image_data", None)
        
        # PDF 생성을 위해 드라이브에서 이미지 Fetch
        img_b64 = None
        if img_filename:
            img_b64 = get_image_from_drive(img_filename)

        sum_qty += qty
        p1 = int(item.get("price_1", 0))
        a1 = p1 * qty
        sum_a1 += a1
        
        p2 = 0; a2 = 0; profit = 0; rate = 0
        if form_type == "profit":
            p2 = int(item.get("price_2", 0))
            a2 = p2 * qty
            sum_a2 += a2
            profit = a2 - a1
            sum_profit += profit
            rate = (profit / a2 * 100) if a2 else 0

        h = 15
        x, y = pdf.get_x(), pdf.get_y()
        
        # 1. 이미지
        pdf.cell(15, h, "", border=1)
        if img_b64:
            try:
                data = base64.b64decode(img_b64.split(",", 1)[1])
                with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as tmp:
                    tmp.write(data); tmp_path = tmp.name
                pdf.image(tmp_path, x=x+2, y=y+2, w=11, h=11)
                os.unlink(tmp_path)
            except: pass

        # 2. 품목정보 (3줄 출력) [수정: Spec/Code 텍스트 삭제]
        pdf.set_xy(x+15, y)
        pdf.cell(45, h, "", border=1) 
        
        # 줄 1: 제품명
        pdf.set_xy(x+15, y+1.5) 
        pdf.set_font(font_name, '', 8) 
        pdf.multi_cell(45, 4, name, align='L')
        
        # 줄 2: 규격 (텍스트 삭제)
        pdf.set_xy(x+15, y+6.0)
        pdf.set_font(font_name, '', 7) 
        pdf.cell(45, 3, f"{spec}", align='L') # Spec: 삭제
        
        # 줄 3: 코드 (텍스트 삭제)
        pdf.set_xy(x+15, y+10.0)
        pdf.set_font(font_name, '', 7)
        pdf.cell(45, 3, f"{code}", align='L') # Code: 삭제

        # 좌표 복귀 및 나머지 컬럼
        pdf.set_xy(x+60, y)
        pdf.set_font(font_name, '', 9) 

        pdf.cell(10, h, item.get("단위", "EA"), border=1, align='C')
        pdf.cell(12, h, str(qty), border=1, align='C')

        if form_type == "basic":
            pdf.cell(35, h, f"{p1:,}", border=1, align='R')
            pdf.cell(35, h, f"{a1:,}", border=1, align='R')
            pdf.cell(38, h, "", border=1, align='C')
            pdf.ln()
        else:
            pdf.set_font(font_name, '', 8)
            pdf.cell(18, h, f"{p1:,}", border=1, align='R')
            pdf.cell(22, h, f"{a1:,}", border=1, align='R')
            pdf.cell(18, h, f"{p2:,}", border=1, align='R')
            pdf.cell(22, h, f"{a2:,}", border=1, align='R')
            pdf.set_font(font_name, 'B' if has_bold else '', 8)
            pdf.cell(15, h, f"{profit:,}", border=1, align='R')
            pdf.cell(13, h, f"{rate:.1f}%", border=1, align='C')
            pdf.set_font(font_name, '', 9)
            pdf.ln()

    # 소계
    pdf.set_fill_color(230, 230, 230)
    pdf.set_font(font_name, 'B' if has_bold else '', 9)
    pdf.cell(15+45+10, 10, "소 계 (Sub Total)", border=1, align='C', fill=True)
    pdf.cell(12, 10, f"{sum_qty:,}", border=1, align='C', fill=True)
    
    if form_type == "basic":
        pdf.cell(35, 10, "", border=1, fill=True)
        pdf.cell(35, 10, f"{sum_a1:,}", border=1, align='R', fill=True)
        pdf.cell(38, 10, "", border=1, fill=True)
        pdf.ln()
    else:
        avg_rate = (sum_profit / sum_a2 * 100) if sum_a2 else 0
        pdf.set_font(font_name, 'B' if has_bold else '', 8)
        pdf.cell(18, 10, "", border=1, fill=True)
        pdf.cell(22, 10, f"{sum_a1:,}", border=1, align='R', fill=True)
        pdf.cell(18, 10, "", border=1, fill=True)
        pdf.cell(22, 10, f"{sum_a2:,}", border=1, align='R', fill=True)
        pdf.cell(15, 10, f"{sum_profit:,}", border=1, align='R', fill=True)
        pdf.cell(13, 10, f"{avg_rate:.1f}%", border=1, align='C', fill=True)
        pdf.ln()

    # 비용
    svc_total = 0
    if service_items:
        pdf.ln(2)
        pdf.set_fill_color(255, 255, 224)
        pdf.cell(190, 6, " [ 추가 비용 ] ", border=1, fill=True, new_x="LMARGIN", new_y="NEXT")
        for s in service_items:
            svc_total += s['금액']
            pdf.cell(155, 6, s['항목'], border=1)
            pdf.cell(35, 6, f"{s['금액']:,} 원", border=1, align='R', new_x="LMARGIN", new_y="NEXT")

    # 총계
    pdf.ln(5)
    pdf.set_font(font_name, 'B' if has_bold else '', 12)
    if form_type == "basic":
        final_total = sum_a1 + svc_total
        pdf.cell(120, 10, "", border=0)
        pdf.cell(35, 10, "총 합계", border=1, align='C', fill=True)
        pdf.cell(35, 10, f"{final_total:,} 원", border=1, align='R')
    else:
        t1_final = sum_a1 + svc_total
        t2_final = sum_a2 + svc_total
        total_profit = t2_final - t1_final
        pdf.set_font(font_name, '', 10)
        pdf.cell(82, 10, "총 합계 (VAT 포함)", border=1, align='C', fill=True)
        pdf.cell(40, 10, f"{t1_final:,}", border=1, align='R')
        pdf.set_font(font_name, 'B' if has_bold else '', 10)
        pdf.cell(40, 10, f"{t2_final:,}", border=1, align='R')
        pdf.cell(28, 10, f"({total_profit:,})", border=1, align='R')
        
    return bytes(pdf.output())

# ==========================================
# 3. 메인 로직
# ==========================================
if "db" not in st.session_state:
    with st.spinner("DB 접속 중..."):
        st.session_state.db = load_data_from_sheet()

if "history" not in st.session_state: st.session_state.history = {} 
if "quote_step" not in st.session_state: st.session_state.quote_step = 1
if "quote_items" not in st.session_state: st.session_state.quote_items = {}
if "services" not in st.session_state: st.session_state.services = []
if "temp_set_recipe" not in st.session_state: st.session_state.temp_set_recipe = {}
if "current_quote_name" not in st.session_state: st.session_state.current_quote_name = ""
if "auth_admin" not in st.session_state: st.session_state.auth_admin = False
if "auth_price" not in st.session_state: st.session_state.auth_price = False

# 기본값
DEFAULT_DATA = {"config": {"password": "1234"}, "products":[], "sets":{}}
if not st.session_state.db: st.session_state.db = DEFAULT_DATA
if "config" not in st.session_state.db: st.session_state.db["config"] = {"password": "1234"}

st.set_page_config(layout="wide", page_title="루퍼젯 프로 매니저 V10.0")
st.title("💧 루퍼젯 프로 매니저 V10.0 (Cloud)")

# 컬럼 매핑
COL_MAP = {"품목코드": "code", "카테고리": "category", "제품명": "name", "규격": "spec", "단위": "unit", "1롤길이(m)": "len_per_unit", "매입단가": "price_buy", "총판가1": "price_d1", "총판가2": "price_d2", "대리점가": "price_agy", "소비자가": "price_cons", "이미지데이터": "image"}
REV_COL_MAP = {v: k for k, v in COL_MAP.items()}

# --- 사이드바 ---
with st.sidebar:
    st.header("🗂️ 견적 보관함")
    q_name = st.text_input("현장명", value=st.session_state.current_quote_name)
    c1, c2 = st.columns(2)
    with c1:
        if st.button("💾 임시저장"):
            st.session_state.history[q_name] = {
                "items": st.session_state.quote_items, "services": st.session_state.services, "step": st.session_state.quote_step
            }
            st.session_state.current_quote_name = q_name; st.success("저장됨")
    with c2:
        if st.button("✨ 초기화"):
            st.session_state.quote_items = {}; st.session_state.services = []; st.session_state.quote_step = 1; st.session_state.current_quote_name = ""; st.rerun()
    st.divider()
    h_list = list(st.session_state.history.keys())[::-1]
    if h_list:
        sel_h = st.selectbox("불러오기", h_list)
        if st.button("📂 로드"):
            d = st.session_state.history[sel_h]
            st.session_state.quote_items = d["items"]; st.session_state.services = d["services"]; st.session_state.quote_step = d.get("step", 2); st.session_state.current_quote_name = sel_h; st.rerun()
    
    st.divider()
    mode = st.radio("모드", ["견적 작성", "관리자 모드"])

# --- [관리자 모드] ---
if mode == "관리자 모드":
    st.header("🛠 관리자 모드 (Google Cloud 연동)")
    if st.button("🔄 구글시트 데이터 새로고침"):
        st.session_state.db = load_data_from_sheet()
        st.success("최신 데이터로 업데이트 완료!")
        st.rerun()
    if not st.session_state.auth_admin:
        pw = st.text_input("관리자 비밀번호", type="password")
        if st.button("로그인"):
            if pw == st.session_state.db["config"]["password"]: st.session_state.auth_admin = True; st.rerun()
            else: st.error("비밀번호 불일치")
    else:
        if st.button("로그아웃"): st.session_state.auth_admin = False; st.rerun()
        t1, t2, t3 = st.tabs(["부품 관리", "세트 관리", "설정"])
        
        with t1:
            st.markdown("##### 🔍 제품 및 엑셀 관리")
            with st.expander("📂 엑셀 데이터 등록/다운로드 (클릭)", expanded=True):
                ec1, ec2 = st.columns(2)
                with ec1:
                    df = pd.DataFrame(st.session_state.db["products"]).rename(columns=REV_COL_MAP)
                    # 이미지 데이터 처리
                    if "이미지데이터" in df.columns: 
                        df["이미지데이터"] = df["이미지데이터"].apply(lambda x: x if x else "")
                    
                    # 엑셀 다운로드 준비
                    buf = io.BytesIO()
                    with pd.ExcelWriter(buf, engine='xlsxwriter') as w: 
                        df.to_excel(w, index=False)
                    
                    st.dataframe(df, use_container_width=True, hide_index=True)
                    st.download_button("엑셀 다운로드", buf.getvalue(), "products.xlsx")
                with ec2:
                    uf = st.file_uploader("엑셀 업로드", ["xlsx"])
                    if uf and st.button("시트에 덮어쓰기"):
                        try:
                            # [수정] 엑셀 읽을 때 품목코드 문자열로 강제 지정
                            ndf = pd.read_excel(uf, dtype={'품목코드': str}).rename(columns=COL_MAP).fillna(0)
                            nrec = ndf.to_dict('records')
                            save_products_to_sheet(nrec)
                            st.session_state.db = load_data_from_sheet() 
                            st.success("업로드 및 동기화 완료 (품목코드 00 유지됨)"); st.rerun()
                        except Exception as e: st.error(e)

            # 이미지 업로드
            st.divider()
            st.markdown("##### 🖼️ 이미지 드라이브 업로드")
            c1, c2, c3 = st.columns([2, 2, 1])
            pn = [p["name"] for p in st.session_state.db["products"]]
            with c1: tp = st.selectbox("대상 품목", pn)
            with c2: ifile = st.file_uploader("이미지 파일", ["png", "jpg"], key="pimg")
            with c3:
                st.write(""); st.write("")
                if st.button("드라이브 저장"):
                    if ifile:
                        with st.spinner("드라이브 업로드 중..."):
                            fname = f"{tp}_{ifile.name}"
                            fid = upload_image_to_drive(ifile, fname)
                            if fid:
                                for p in st.session_state.db["products"]:
                                    if p["name"] == tp: p["image"] = fid
                                save_products_to_sheet(st.session_state.db["products"])
                                st.success("저장 완료!")
                            else: st.error("실패")

        with t2:
            st.subheader("세트 관리")
            cat = st.selectbox("분류", ["주배관세트", "가지관세트", "기타자재"])
            cset = st.session_state.db["sets"].get(cat, {})
            
            # 현황표
            if cset:
                set_list = [{"세트명": k, "부품수": len(v.get("recipe", {}))} for k,v in cset.items()]
                st.dataframe(pd.DataFrame(set_list), use_container_width=True, on_select="rerun", selection_mode="single-row", key="set_table")
                sel_rows = st.session_state.set_table.get("selection", {}).get("rows", [])
                if sel_rows:
                    sel_idx = sel_rows[0]
                    target_set = set_list[sel_idx]["세트명"]
                    if st.button(f"'{target_set}' 수정하기"):
                        st.session_state.temp_set_recipe = cset[target_set].get("recipe", {}).copy()
                        st.session_state.target_set_edit = target_set
                        st.rerun()

            st.divider()
            mt = st.radio("작업", ["신규", "수정"], horizontal=True)
            sub_cat = None
            if cat == "주배관세트": sub_cat = st.selectbox("하위분류", ["50mm", "40mm", "기타"], key="sub_c")
            
            products_obj = st.session_state.db["products"]

            if mt == "신규":
                 nn = st.text_input("세트명")
                 c1, c2, c3 = st.columns([3,2,1])
                 with c1: sp_obj = st.selectbox("부품", products_obj, format_func=lambda x: f"{x['name']} ({x.get('spec','-')})", key="nsp")
                 with c2: sq = st.number_input("수량", 1, key="nsq")
                 with c3: 
                     if st.button("담기"): st.session_state.temp_set_recipe[sp_obj['name']] = sq
                 st.write(st.session_state.temp_set_recipe)
                 if st.button("저장"):
                     if cat not in st.session_state.db["sets"]: st.session_state.db["sets"][cat] = {}
                     st.session_state.db["sets"][cat][nn] = {"recipe": st.session_state.temp_set_recipe, "image": "", "sub_cat": sub_cat}
                     save_sets_to_sheet(st.session_state.db["sets"])
                     st.session_state.temp_set_recipe={}; st.success("저장")
            else:
                 if "target_set_edit" in st.session_state and st.session_state.target_set_edit:
                     tg = st.session_state.target_set_edit
                     st.info(f"편집: {tg}")
                     for k,v in list(st.session_state.temp_set_recipe.items()):
                         c1, c2, c3 = st.columns([4,1,1])
                         c1.text(f"{k} (수량:{v})")
                         if c3.button("삭제", key=f"d{k}"): del st.session_state.temp_set_recipe[k]; st.rerun()
                     
                     c1, c2, c3 = st.columns([3,2,1])
                     with c1: ap_obj = st.selectbox("추가", products_obj, format_func=lambda x: f"{x['name']} ({x.get('spec','-')})", key="esp")
                     with c2: aq = st.number_input("수량", 1, key="esq")
                     with c3: 
                         if st.button("담기", key="esa"): st.session_state.temp_set_recipe[ap_obj['name']] = aq; st.rerun()
                     
                     if st.button("수정 저장"):
                         st.session_state.db["sets"][cat][tg]["recipe"] = st.session_state.temp_set_recipe
                         save_sets_to_sheet(st.session_state.db["sets"]); st.success("수정됨")
                     if st.button("세트 삭제", type="primary"):
                         del st.session_state.db["sets"][cat][tg]
                         save_sets_to_sheet(st.session_state.db["sets"]); st.rerun()

        with t3:
            st.write("설정 기능 (비밀번호 등은 시트 Config 시트 등을 활용해 확장 가능)")

# --- [견적 모드] ---
else:
    st.markdown(f"### 📝 현장명: **{st.session_state.current_quote_name if st.session_state.current_quote_name else '(제목 없음)'}**")

    # STEP 1
    if st.session_state.quote_step == 1:
        st.subheader("STEP 1. 물량 입력")
        sets = st.session_state.db.get("sets", {})
        
        # 헬퍼
        def render_inputs(d, pf):
            cols = st.columns(4)
            res = {}
            for i, (n, v) in enumerate(d.items()):
                with cols[i%4]:
                    img_name = v.get("image") if isinstance(v, dict) else None
                    if img_name:
                        b64 = get_image_from_drive(img_name)
                        if b64: st.image(b64, use_container_width=True)
                        else: st.markdown("No Image")
                    else: st.markdown("<div style='height:80px;background:#eee'></div>", unsafe_allow_html=True)
                    res[n] = st.number_input(n, 0, key=f"{pf}_{n}")
            return res

        with st.expander("1. 주배관", True):
            m_sets = sets.get("주배관세트", {})
            grouped = {"50mm":{}, "40mm":{}, "기타":{}, "미분류":{}}
            for k, v in m_sets.items():
                sc = v.get("sub_cat", "미분류") if isinstance(v, dict) else "미분류"
                if sc not in grouped: grouped[sc] = {}
                grouped[sc][k] = v
            mt1, mt2, mt3, mt4 = st.tabs(["50mm", "40mm", "기타", "전체"])
            with mt1: inp_m_50 = render_inputs(grouped["50mm"], "m50")
            with mt2: inp_m_40 = render_inputs(grouped["40mm"], "m40")
            with mt3: inp_m_etc = render_inputs(grouped["기타"], "metc")
            with mt4: inp_m_u = render_inputs(grouped["미분류"], "mu")
        
        with st.expander("2. 가지관"): inp_b = render_inputs(sets.get("가지관세트", {}), "b")
        with st.expander("3. 기타"): inp_e = render_inputs(sets.get("기타자재", {}), "e")
        
        all_products = st.session_state.db["products"]
        mpl = [p for p in all_products if p["category"] == "주배관"]
        bpl = [p for p in all_products if p["category"] == "가지관"]
        
        c1, c2 = st.columns(2)
        with c1: 
            sm_obj = st.selectbox("주배관", mpl, format_func=lambda x: f"{x['name']} ({x.get('spec','-')})") if mpl else None
            lm = st.number_input("길이m", 0, key="lm")
        with c2: 
            sb_obj = st.selectbox("가지관", bpl, format_func=lambda x: f"{x['name']} ({x.get('spec','-')})") if bpl else None
            lb = st.number_input("길이m", 0, key="lb")

        if st.button("계산하기 (STEP 2)"):
            res = {}
            all_m = {**inp_m_50, **inp_m_40, **inp_m_etc, **inp_m_u}
            def ex(ins, db):
                for k,v in ins.items():
                    if v>0:
                        rec = db[k].get("recipe", db[k])
                        for p, q in rec.items(): res[p] = res.get(p, 0) + q*v
            ex(all_m, sets.get("주배관세트", {})); ex(inp_b, sets.get("가지관세트", {})); ex(inp_e, sets.get("기타자재", {}))
            def cr(p_obj, l):
                if l>0 and p_obj: res[p_obj['name']] = res.get(p_obj['name'], 0) + math.ceil(l/p_obj["len_per_unit"])
            cr(sm_obj, lm); cr(sb_obj, lb)
            st.session_state.quote_items = res; st.session_state.quote_step = 2; st.rerun()

    # STEP 2
    elif st.session_state.quote_step == 2:
        st.subheader("STEP 2. 내용 검토")
        view_opts = ["소비자가"]
        if st.session_state.auth_price: view_opts += ["매입가", "총판1", "총판2", "대리점"]
        
        c_lock, c_view = st.columns([1, 2])
        with c_lock:
            if not st.session_state.auth_price:
                pw = st.text_input("원가 조회 비번", type="password")
                if st.button("해제"):
                    if pw == st.session_state.db["config"]["password"]: st.session_state.auth_price = True; st.rerun()
                    else: st.error("오류")
            else: st.success("🔓 원가 조회 가능")
        with c_view: view = st.radio("단가 보기", view_opts, horizontal=True)

        key_map = {"매입가":("price_buy","매입"), "총판1":("price_d1","총판1"), "총판2":("price_d2","총판2"), "대리점":("price_agy","대리점")}
        rows = []
        pdb = {p["name"]: p for p in st.session_state.db["products"]}
        for n, q in st.session_state.quote_items.items():
            inf = pdb.get(n, {})
            cpr = inf.get("price_cons", 0)
            row = {"품목": n, "규격": inf.get("spec", ""), "수량": q, "소비자가": cpr, "합계": cpr*q}
            if view != "소비자가":
                k, l = key_map[view]
                pr = inf.get(k, 0)
                row[f"{l}단가"] = pr; row[f"{l}합계"] = pr*q
                row["이익"] = row["합계"] - row[f"{l}합계"]
                row["율(%)"] = (row["이익"]/row["합계"]*100) if row["합계"] else 0
            rows.append(row)
        
        df = pd.DataFrame(rows)
        disp = ["품목", "규격", "수량"]
        if view == "소비자가": disp += ["소비자가", "합계"]
        else: 
            l = key_map[view][1]
            disp += [f"{l}단가", f"{l}합계", "소비자가", "합계", "이익", "율(%)"]
        st.dataframe(df[disp], use_container_width=True, hide_index=True)
        
        c1, c2 = st.columns(2)
        with c1:
            all_products = st.session_state.db["products"]
            ap_obj = st.selectbox("품목 추가", all_products, format_func=lambda x: f"{x['name']} ({x.get('spec','-')})")
            aq = st.number_input("수량", 1)
            if st.button("추가"): st.session_state.quote_items[ap_obj['name']] = st.session_state.quote_items.get(ap_obj['name'], 0) + aq; st.rerun()
        with c2:
            stype = st.selectbox("비용", ["배송비", "용역비", "기타"])
            sn = st.text_input("내용") if stype=="기타" else stype
            sp = st.number_input("금액", 0, step=1000)
            if st.button("비용추가"): st.session_state.services.append({"항목": sn, "금액": sp}); st.rerun()
        if st.session_state.services: st.table(st.session_state.services)
        if st.button("최종 확정 (STEP 3)"): st.session_state.quote_step = 3; st.rerun()

    # STEP 3
    elif st.session_state.quote_step == 3:
        st.header("🏁 최종 견적")
        if not st.session_state.current_quote_name: st.warning("저장해주세요!")
        st.markdown("##### 🖨️ 출력 옵션")
        c_date, c_opt1, c_opt2 = st.columns([1, 1, 1])
        with c_date: q_date = st.date_input("견적일", datetime.datetime.now())
        with c_opt1: form_type = st.radio("양식", ["기본 양식", "이익 분석 양식"])
        with c_opt2:
            opts = ["소비자가"]
            if st.session_state.auth_price: opts = ["매입단가", "총판가1", "총판가2", "대리점가", "소비자가"]
            
            # [수정] 이익 분석 선택 시 비밀번호 입력창 바로 표시
            if "이익" in form_type and not st.session_state.auth_price:
                st.warning("🔒 원가 정보를 보려면 비밀번호를 입력하세요.")
                c_pw, c_btn = st.columns([2,1])
                with c_pw: input_pw = st.text_input("비밀번호", type="password", key="step3_pw")
                with c_btn: 
                    if st.button("해제", key="step3_btn"):
                        if input_pw == st.session_state.db["config"]["password"]: 
                            st.session_state.auth_price = True; st.rerun()
                        else: st.error("불일치")
                st.stop()

            if "기본" in form_type: sel = st.multiselect("출력 단가", opts, default=["소비자가"], max_selections=1)
            else: sel = st.multiselect("비교 단가 (2개)", opts, max_selections=2)

        if "이익" in form_type and len(sel) < 2: st.warning("2개 선택 필요"); st.stop()

        price_rank = {"매입단가": 0, "총판가1": 1, "총판가2": 2, "대리점가": 3, "소비자가": 4}
        if sel: sel = sorted(sel, key=lambda x: price_rank.get(x, 5))

        pkey = {"매입단가":"price_buy", "총판가1":"price_d1", "총판가2":"price_d2", "대리점가":"price_agy", "소비자가":"price_cons"}
        pdb = {p["name"]: p for p in st.session_state.db["products"]}
        pk = [pkey[l] for l in sel] if sel else ["price_cons"]
        
        fdata = []
        for n, q in st.session_state.quote_items.items():
            inf = pdb.get(n, {})
            d = {
                "품목": n, 
                "규격": inf.get("spec", ""), 
                "코드": inf.get("code", ""),
                "단위": inf.get("unit", "EA"), 
                "수량": int(q), 
                "image_data": inf.get("image")
            }
            d["price_1"] = int(inf.get(pk[0], 0))
            if len(pk)>1: d["price_2"] = int(inf.get(pk[1], 0))
            fdata.append(d)
        
        st.markdown("---")
        cc = {"품목": st.column_config.TextColumn(disabled=True), "규격": st.column_config.TextColumn(disabled=True), "코드": st.column_config.TextColumn(disabled=True), "image_data": None, "수량": st.column_config.NumberColumn(step=1), "price_1": st.column_config.NumberColumn(label=sel[0] if sel else "단가", format="%d")}
        if len(pk)>1: cc["price_2"] = st.column_config.NumberColumn(label=sel[1], format="%d")
        
        disp_cols = ["품목", "규격", "코드", "단위", "수량", "price_1"]
        if len(pk)>1: disp_cols.append("price_2")
        
        edited = st.data_editor(pd.DataFrame(fdata)[disp_cols], column_config=cc, use_container_width=True, hide_index=True)
        
        if sel:
            fmode = "basic" if "기본" in form_type else "profit"
            pdf_b = create_advanced_pdf(edited.to_dict('records'), st.session_state.services, st.session_state.current_quote_name, q_date.strftime("%Y-%m-%d"), fmode, sel)
            st.download_button("📥 PDF 다운로드", pdf_b, f"quote_{st.session_state.current_quote_name}.pdf", "application/pdf", type="primary")

        c1, c2 = st.columns(2)
        with c1: 
            if st.button("⬅️ 수정"): st.session_state.quote_step = 2; st.rerun()
        with c2:
            if st.button("🔄 처음으로"): st.session_state.quote_step = 1; st.session_state.quote_items = {}; st.session_state.services = []; st.session_state.current_quote_name = ""; st.rerun()

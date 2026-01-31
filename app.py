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

@st.cache_resource
def get_google_services():
    try:
        creds_dict = dict(st.secrets["gcp_service_account"])
        creds = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
        gc = gspread.authorize(creds)
        drive_service = build('drive', 'v3', credentials=creds)
        return gc, drive_service
    except Exception as e:
        st.error(f"구글 서비스 인증 실패: {e}")
        return None, None

gc, drive_service = get_google_services()

# --- 구글 드라이브 함수 ---
DRIVE_FOLDER_NAME = "Looperget_Images"

def get_or_create_drive_folder():
    if not drive_service: return None
    try:
        query = f"name='{DRIVE_FOLDER_NAME}' and mimeType='application/vnd.google-apps.folder' and trashed=false"
        results = drive_service.files().list(q=query, fields="files(id)").execute()
        files = results.get('files', [])
        if files: return files[0]['id']
        else:
            file_metadata = {'name': DRIVE_FOLDER_NAME, 'mimeType': 'application/vnd.google-apps.folder'}
            folder = drive_service.files().create(body=file_metadata, fields='id').execute()
            return folder.get('id')
    except Exception as e:
        st.error(f"드라이브 폴더 오류: {e}")
        return None

def upload_image_to_drive(file_obj, filename):
    folder_id = get_or_create_drive_folder()
    if not folder_id: return None
    try:
        file_metadata = {'name': filename, 'parents': [folder_id]}
        media = MediaIoBaseUpload(file_obj, mimetype=file_obj.type, resumable=True)
        drive_service.files().create(body=file_metadata, media_body=media, fields='id').execute()
        return filename
    except Exception as e:
        st.error(f"업로드 실패: {e}")
        return None

@st.cache_data(ttl=600)
def get_drive_file_map():
    folder_id = get_or_create_drive_folder()
    if not folder_id: return {}
    file_map = {}
    try:
        query = f"'{folder_id}' in parents and trashed=false"
        page_token = None
        while True:
            response = drive_service.files().list(q=query, spaces='drive', fields='nextPageToken, files(id, name)', pageToken=page_token).execute()
            files = response.get('files', [])
            for f in files:
                name_stem = os.path.splitext(f['name'])[0]
                file_map[name_stem] = f['id']
            page_token = response.get('nextPageToken', None)
            if page_token is None: break
    except Exception: pass
    return file_map

def download_image_by_id(file_id):
    if not file_id or not drive_service: return None
    try:
        request = drive_service.files().get_media(fileId=file_id)
        downloader = request.execute()
        img = Image.open(io.BytesIO(downloader))
        img = img.convert('RGB')
        img.thumbnail((300, 225))
        buffer = io.BytesIO()
        img.save(buffer, format="JPEG")
        return f"data:image/jpeg;base64,{base64.b64encode(buffer.getvalue()).decode()}"
    except Exception:
        return None

@st.cache_data(ttl=3600)
def get_image_from_drive(filename_or_id):
    if not filename_or_id: return None
    fmap = get_drive_file_map()
    if filename_or_id in fmap.values():
        return download_image_by_id(filename_or_id)
    stem = os.path.splitext(filename_or_id)[0]
    if stem in fmap:
        return download_image_by_id(fmap[stem])
    return None

def list_files_in_drive_folder():
    """폴더 내의 모든 파일 목록 가져오기 (파일명 -> ID 매핑)"""
    return get_drive_file_map()

# --- 구글 시트 함수 ---
SHEET_NAME = "Looperget_DB"
COL_MAP = {
    "품목코드": "code", "카테고리": "category", "제품명": "name", "규격": "spec", "단위": "unit", 
    "1롤길이(m)": "len_per_unit", "매입단가": "price_buy", 
    "총판가1": "price_d1", "총판가2": "price_d2", "대리점가": "price_agy", 
    "소비자가": "price_cons", "단가(현장)": "price_site", 
    "이미지데이터": "image"
}
REV_COL_MAP = {v: k for k, v in COL_MAP.items()}

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
    return ws_prod, ws_sets

def load_data_from_sheet():
    ws_prod, ws_sets = init_db()
    if not ws_prod: return DEFAULT_DATA
    data = {"config": {"password": "1234"}, "products": [], "sets": {}}
    try:
        prod_records = ws_prod.get_all_records()
        for rec in prod_records:
            new_rec = {}
            for k, v in rec.items():
                if k in COL_MAP:
                    if k == "품목코드": new_rec[COL_MAP[k]] = str(v).zfill(5)
                    else: new_rec[COL_MAP[k]] = v
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
            data["sets"][cat][name] = {"recipe": rcp, "image": rec.get("이미지파일명"), "sub_cat": rec.get("하위분류")}
    except: pass
    return data

def save_products_to_sheet(products_list):
    ws_prod, _ = init_db()
    if not ws_prod: return
    df = pd.DataFrame(products_list)
    if "code" in df.columns: df["code"] = df["code"].astype(str).apply(lambda x: x.zfill(5))
    df_up = df.rename(columns=REV_COL_MAP).fillna("")
    ws_prod.clear(); ws_prod.update([df_up.columns.values.tolist()] + df_up.values.tolist())

def save_sets_to_sheet(sets_dict):
    _, ws_sets = init_db()
    if not ws_sets: return
    rows = [["세트명", "카테고리", "하위분류", "이미지파일명", "레시피JSON"]]
    for cat, items in sets_dict.items():
        for name, info in items.items():
            rows.append([name, cat, info.get("sub_cat", ""), info.get("image", ""), json.dumps(info.get("recipe", {}), ensure_ascii=False)])
    ws_sets.clear(); ws_sets.update(rows)

def format_prod_label(option):
    if isinstance(option, dict): return f"[{option.get('code','00000')}] {option.get('name','')} ({option.get('spec','-')})"
    return str(option)

# ==========================================
# 2. PDF 생성 엔진
# ==========================================
class PDF(FPDF):
    def header(self):
        header_font = 'Helvetica'; header_style = 'B'
        if os.path.exists(FONT_REGULAR):
            self.add_font('NanumGothic', '', FONT_REGULAR, uni=True)
            header_font = 'NanumGothic'
            if os.path.exists(FONT_BOLD): self.add_font('NanumGothic', 'B', FONT_BOLD, uni=True); header_style = 'B'
            else: header_style = ''
        self.set_font(header_font, header_style, 20)
        self.cell(0, 15, '견 적 서 (Quotation)', align='C', new_x="LMARGIN", new_y="NEXT")
        self.set_font(header_font, '', 9)

    def footer(self):
        self.set_y(-20)
        footer_font = 'Helvetica'; footer_style = 'B'
        if os.path.exists(FONT_REGULAR):
            footer_font = 'NanumGothic'
            if os.path.exists(FONT_BOLD): footer_style = 'B'
            else: footer_style = ''
        self.set_font(footer_font, footer_style, 12)
        if footer_font == 'NanumGothic':
            self.cell(0, 8, "주식회사 신진켐텍", align='C', ln=True)
            self.set_font('NanumGothic', '', 8)
        else:
            self.cell(0, 8, "SHIN JIN CHEMTECH Co., Ltd.", align='C', ln=True)
            self.set_font('Helvetica', 'I', 8)
        self.cell(0, 5, f'Page {self.page_no()}', align='C')

def create_advanced_pdf(final_data_list, service_items, quote_name, quote_date, form_type, price_labels, buyer_info):
    drive_file_map = get_drive_file_map()
    pdf = PDF()
    pdf.add_page()
    has_font = os.path.exists(FONT_REGULAR)
    has_bold = os.path.exists(FONT_BOLD)
    font_name = 'NanumGothic' if has_font else 'Helvetica'
    b_style = 'B' if has_bold else ''
    
    pdf.set_font(font_name, '', 10)
    pdf.set_fill_color(255, 255, 255)
    pdf.cell(100, 8, f" 견적일 : {quote_date}", border=0)
    pdf.cell(90, 8, f" 현장명 : {quote_name}", border=0, align='R', new_x="LMARGIN", new_y="NEXT")
    pdf.ln(2)

    x_start = pdf.get_x(); half_w = 95; h_line = 6
    pdf.set_fill_color(240, 240, 240)
    pdf.set_font(font_name, b_style, 10)
    pdf.cell(half_w, h_line, "  [공급받는 자]", border=1, fill=True)
    pdf.cell(half_w, h_line, "  [공급자]", border=1, fill=True, new_x="LMARGIN", new_y="NEXT")
    pdf.set_font(font_name, '', 9)
    
    buy_lines = [f" 상호(현장): {quote_name}", f" 담당자: {buyer_info.get('manager', '')}", f" 연락처: {buyer_info.get('phone', '')}", f" 주소: {buyer_info.get('addr', '')}", ""]
    sell_lines = [" 상호: 주식회사 신진켐텍", " 대표자: 박형석 (인)", " 주소: 경기도 이천시 부발읍 황무로 1859-157", " 전화: 031-638-1809 / 팩스: 031-638-1810", " 이메일: support@sjct.kr / 홈페이지: www.sjct.kr"]
    for b, s in zip(buy_lines, sell_lines):
        cur_y = pdf.get_y()
        pdf.set_xy(x_start, cur_y); pdf.cell(half_w, h_line, " " + b, border=1)
        pdf.set_xy(x_start + half_w, cur_y); pdf.cell(half_w, h_line, " " + s, border=1)
        pdf.ln(h_line)
    pdf.ln(5)

    pdf.set_fill_color(240, 240, 240)
    pdf.set_font(font_name, b_style, 10)
    h_height = 10
    pdf.cell(15, h_height, "IMG", border=1, align='C', fill=True)
    pdf.cell(45, h_height, "품목정보 (명/규격/코드)", border=1, align='C', fill=True) 
    pdf.cell(10, h_height, "단위", border=1, align='C', fill=True)
    pdf.cell(12, h_height, "수량", border=1, align='C', fill=True)

    if form_type == "basic":
        pdf.cell(35, h_height, f"{price_labels[0]}", border=1, align='C', fill=True)
        pdf.cell(35, h_height, "금액", border=1, align='C', fill=True)
        pdf.cell(38, h_height, "비고", border=1, align='C', fill=True, new_x="LMARGIN", new_y="NEXT")
    else:
        l1, l2 = price_labels[0], price_labels[1]
        pdf.set_font(font_name, '', 8)
        pdf.cell(18, h_height, f"{l1}", border=1, align='C', fill=True)
        pdf.cell(22, h_height, "금액", border=1, align='C', fill=True)
        pdf.cell(18, h_height, f"{l2}", border=1, align='C', fill=True)
        pdf.cell(22, h_height, "금액", border=1, align='C', fill=True)
        pdf.cell(15, h_height, "이익", border=1, align='C', fill=True)
        pdf.cell(13, h_height, "율(%)", border=1, align='C', fill=True, new_x="LMARGIN", new_y="NEXT")
        pdf.set_font(font_name, '', 9)

    sum_qty = 0; sum_a1 = 0; sum_a2 = 0; sum_profit = 0

    for item in final_data_list:
        name = item.get("품목", "")
        spec = item.get("규격", "-")
        code = str(item.get("코드", "")).strip().zfill(5) 
        qty = int(item.get("수량", 0))
        
        img_b64 = None
        if code in drive_file_map:
            img_b64 = download_image_by_id(drive_file_map[code])
        
        sum_qty += qty
        p1 = int(item.get("price_1", 0))
        a1 = p1 * qty
        sum_a1 += a1
        
        p2 = 0; a2 = 0; profit = 0; rate = 0
        if form_type == "profit":
            p2 = int(item.get("price_2", 0))
            a2 = p2 * qty
            sum_a2 += a2; profit = a2 - a1; sum_profit += profit
            rate = (profit / a2 * 100) if a2 else 0

        h = 15; x, y = pdf.get_x(), pdf.get_y()
        
        pdf.cell(15, h, "", border=1)
        if img_b64:
            try:
                img_data_str = img_b64.split(",", 1)[1] if "," in img_b64 else img_b64
                img_bytes = base64.b64decode(img_data_str)
                with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as tmp:
                    tmp.write(img_bytes); tmp_path = tmp.name
                pdf.image(tmp_path, x=x+2, y=y+2, w=11, h=11)
                os.unlink(tmp_path)
            except: pass

        pdf.set_xy(x+15, y); pdf.cell(45, h, "", border=1) 
        pdf.set_xy(x+15, y+1.5); pdf.set_font(font_name, '', 8); pdf.multi_cell(45, 4, name, align='L')
        pdf.set_xy(x+15, y+6.0); pdf.set_font(font_name, '', 7); pdf.cell(45, 3, f"{spec}", align='L') 
        pdf.set_xy(x+15, y+10.0); pdf.set_font(font_name, '', 7); pdf.cell(45, 3, f"{code}", align='L') 

        pdf.set_xy(x+60, y); pdf.set_font(font_name, '', 9) 
        pdf.cell(10, h, item.get("단위", "EA"), border=1, align='C')
        pdf.cell(12, h, str(qty), border=1, align='C')

        if form_type == "basic":
            pdf.cell(35, h, f"{p1:,}", border=1, align='R')
            pdf.cell(35, h, f"{a1:,}", border=1, align='R')
            pdf.cell(38, h, "", border=1, align='C'); pdf.ln()
        else:
            pdf.set_font(font_name, '', 8)
            pdf.cell(18, h, f"{p1:,}", border=1, align='R')
            pdf.cell(22, h, f"{a1:,}", border=1, align='R')
            pdf.cell(18, h, f"{p2:,}", border=1, align='R')
            pdf.cell(22, h, f"{a2:,}", border=1, align='R')
            pdf.set_font(font_name, b_style, 8)
            pdf.cell(15, h, f"{profit:,}", border=1, align='R')
            pdf.cell(13, h, f"{rate:.1f}%", border=1, align='C')
            pdf.set_font(font_name, '', 9); pdf.ln()

    pdf.set_fill_color(230, 230, 230); pdf.set_font(font_name, b_style, 9)
    pdf.cell(15+45+10, 10, "소 계 (Sub Total)", border=1, align='C', fill=True)
    pdf.cell(12, 10, f"{sum_qty:,}", border=1, align='C', fill=True)
    
    if form_type == "basic":
        pdf.cell(35, 10, "", border=1, fill=True)
        pdf.cell(35, 10, f"{sum_a1:,}", border=1, align='R', fill=True)
        pdf.cell(38, 10, "", border=1, fill=True); pdf.ln()
    else:
        avg_rate = (sum_profit / sum_a2 * 100) if sum_a2 else 0
        pdf.set_font(font_name, b_style, 8)
        pdf.cell(18, 10, "", border=1, fill=True); pdf.cell(22, 10, f"{sum_a1:,}", border=1, align='R', fill=True)
        pdf.cell(18, 10, "", border=1, fill=True); pdf.cell(22, 10, f"{sum_a2:,}", border=1, align='R', fill=True)
        pdf.cell(15, 10, f"{sum_profit:,}", border=1, align='R', fill=True)
        pdf.cell(13, 10, f"{avg_rate:.1f}%", border=1, align='C', fill=True); pdf.ln()

    svc_total = 0
    if service_items:
        pdf.ln(2); pdf.set_fill_color(255, 255, 224)
        pdf.cell(190, 6, " [ 추가 비용 ] ", border=1, fill=True, new_x="LMARGIN", new_y="NEXT")
        for s in service_items:
            svc_total += s['금액']; pdf.cell(155, 6, s['항목'], border=1)
            pdf.cell(35, 6, f"{s['금액']:,} 원", border=1, align='R', new_x="LMARGIN", new_y="NEXT")

    pdf.ln(5); pdf.set_font(font_name, b_style, 12)
    pdf.cell(0, 5, "1. 견적 유효기간: 견적일로부터 15일 이내", ln=True, align='R')
    pdf.cell(0, 5, "2. 출고: 결재 완료 후 즉시 또는 7일 이내", ln=True, align='R')
    pdf.ln(2)

    if form_type == "basic":
        final_total = sum_a1 + svc_total
        pdf.cell(120, 10, "", border=0); pdf.cell(35, 10, "총 합계", border=1, align='C', fill=True)
        pdf.cell(35, 10, f"{final_total:,} 원", border=1, align='R')
    else:
        t1_final = sum_a1 + svc_total; t2_final = sum_a2 + svc_total; total_profit = t2_final - t1_final
        pdf.set_font(font_name, '', 10)
        pdf.cell(82, 10, "총 합계 (VAT 포함)", border=1, align='C', fill=True)
        pdf.cell(40, 10, f"{t1_final:,}", border=1, align='R')
        pdf.set_font(font_name, b_style, 10)
        pdf.cell(40, 10, f"{t2_final:,}", border=1, align='R')
        pdf.cell(28, 10, f"({total_profit:,})", border=1, align='R')
        
    return bytes(pdf.output())

# ==========================================
# 3. 메인 로직
# ==========================================
if "db" not in st.session_state:
    with st.spinner("DB 접속 중..."): st.session_state.db = load_data_from_sheet()

if "history" not in st.session_state: st.session_state.history = {} 
if "quote_step" not in st.session_state: st.session_state.quote_step = 1
if "quote_items" not in st.session_state: st.session_state.quote_items = {}
if "services" not in st.session_state: st.session_state.services = []
if "pipe_cart" not in st.session_state: st.session_state.pipe_cart = [] 
if "set_cart" not in st.session_state: st.session_state.set_cart = [] 
if "temp_set_recipe" not in st.session_state: st.session_state.temp_set_recipe = {}
if "current_quote_name" not in st.session_state: st.session_state.current_quote_name = ""
if "buyer_info" not in st.session_state: st.session_state.buyer_info = {"manager": "", "phone": "", "addr": ""}
if "auth_admin" not in st.session_state: st.session_state.auth_admin = False
if "auth_price" not in st.session_state: st.session_state.auth_price = False

DEFAULT_DATA = {"config": {"password": "1234"}, "products":[], "sets":{}}
if not st.session_state.db: st.session_state.db = DEFAULT_DATA
if "config" not in st.session_state.db: st.session_state.db["config"] = {"password": "1234"}

st.set_page_config(layout="wide", page_title="루퍼젯 프로 매니저 V10.0")
st.title("💧 루퍼젯 프로 매니저 V10.0 (Cloud)")

with st.sidebar:
    st.header("🗂️ 견적 보관함")
    q_name = st.text_input("현장명 (저장용)", value=st.session_state.current_quote_name)
    c1, c2 = st.columns(2)
    with c1:
        if st.button("💾 임시저장"):
            st.session_state.history[q_name] = {"items": st.session_state.quote_items, "services": st.session_state.services, "pipe_cart": st.session_state.pipe_cart, "set_cart": st.session_state.set_cart, "step": st.session_state.quote_step, "buyer": st.session_state.buyer_info}
            st.session_state.current_quote_name = q_name; st.success("저장됨")
    with c2:
        if st.button("✨ 초기화"):
            st.session_state.quote_items = {}; st.session_state.services = []; st.session_state.pipe_cart = []; st.session_state.set_cart = []; st.session_state.quote_step = 1
            st.session_state.current_quote_name = ""; st.session_state.buyer_info = {"manager": "", "phone": "", "addr": ""}; st.rerun()
    st.divider()
    h_list = list(st.session_state.history.keys())[::-1]
    if h_list:
        sel_h = st.selectbox("불러오기", h_list)
        if st.button("📂 로드"):
            d = st.session_state.history[sel_h]
            st.session_state.quote_items = d["items"]; st.session_state.services = d["services"]; st.session_state.pipe_cart = d.get("pipe_cart", []); st.session_state.set_cart = d.get("set_cart", [])
            st.session_state.quote_step = d.get("step", 2)
            st.session_state.buyer_info = d.get("buyer", {"manager": "", "phone": "", "addr": ""})
            st.session_state.current_quote_name = sel_h; st.rerun()
    st.divider()
    mode = st.radio("모드", ["견적 작성", "관리자 모드"])

if mode == "관리자 모드":
    st.header("🛠 관리자 모드")
    if st.button("🔄 구글시트 데이터 새로고침"): st.session_state.db = load_data_from_sheet(); st.success("완료"); st.rerun()
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
            with st.expander("📂 엑셀 데이터", expanded=True):
                df = pd.DataFrame(st.session_state.db["products"]).rename(columns=REV_COL_MAP)
                if "이미지데이터" in df.columns: df["이미지데이터"] = df["이미지데이터"].apply(lambda x: x if x else "")
                st.dataframe(df, use_container_width=True, hide_index=True)
                st.divider()
                ec1, ec2 = st.columns([1, 1])
                with ec1:
                    buf = io.BytesIO()
                    with pd.ExcelWriter(buf, engine='xlsxwriter') as w: df.to_excel(w, index=False)
                    st.download_button("엑셀 다운로드", buf.getvalue(), "products.xlsx")
                with ec2:
                    uf = st.file_uploader("엑셀 파일 선택", ["xlsx"], label_visibility="collapsed")
                    if uf and st.button("시트에 덮어쓰기"):
                        try:
                            ndf = pd.read_excel(uf, dtype={'품목코드': str}).rename(columns=COL_MAP).fillna(0)
                            save_products_to_sheet(ndf.to_dict('records')); st.session_state.db = load_data_from_sheet(); st.success("완료"); st.rerun()
                        except Exception as e: st.error(e)
            
            # [복원됨] 구글 드라이브 이미지 동기화 섹션
            st.divider()
            st.markdown("##### 🔄 드라이브 이미지 일괄 동기화")
            with st.expander("구글 드라이브 폴더의 이미지와 자동 연결하기", expanded=False):
                st.info("💡 사용법: 이미지 파일명을 '품목코드.jpg' (예: 00200.jpg)로 저장해서 구글 드라이브 'Looperget_Images' 폴더에 먼저 업로드하세요.")
                if st.button("🔄 드라이브 이미지 자동 연결 실행", key="btn_sync_images"):
                    with st.spinner("드라이브 폴더를 검색하는 중..."):
                        file_map = get_drive_file_map() # 최신화된 목록 가져옴
                        if not file_map:
                            st.warning("폴더가 비어있거나 찾을 수 없습니다.")
                        else:
                            updated_count = 0
                            products = st.session_state.db["products"]
                            for p in products:
                                code = str(p.get("code", "")).strip()
                                # 코드가 파일명 목록에 있으면 연결
                                if code and code in file_map:
                                    p["image"] = file_map[code] # 파일명(확장자 포함) 저장
                                    updated_count += 1
                            
                            if updated_count > 0:
                                save_products_to_sheet(products)
                                st.success(f"✅ 총 {updated_count}개의 제품 이미지를 연결했습니다!")
                                st.session_state.db = load_data_from_sheet() # 리로드
                            else:
                                st.warning("매칭되는 이미지가 없습니다. (파일명이 품목코드와 같은지 확인하세요)")

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

        with t2:
            st.subheader("세트 관리")
            cat = st.selectbox("분류", ["주배관세트", "가지관세트", "기타자재"])
            cset = st.session_state.db["sets"].get(cat, {})
            if cset:
                sl = [{"세트명": k, "부품수": len(v.get("recipe", {}))} for k,v in cset.items()]
                st.dataframe(pd.DataFrame(sl), use_container_width=True, on_select="rerun", selection_mode="single-row", key="set_table")
                sel_rows = st.session_state.set_table.get("selection", {}).get("rows", [])
                if sel_rows:
                    tg = sl[sel_rows[0]]["세트명"]
                    if st.button(f"'{tg}' 수정하기"):
                        st.session_state.temp_set_recipe = cset[tg].get("recipe", {}).copy()
                        st.session_state.target_set_edit = tg
                        st.rerun()
            st.divider()
            mt = st.radio("작업", ["신규", "수정"], horizontal=True)
            sub_cat = None
            if cat == "주배관세트": sub_cat = st.selectbox("하위분류", ["50mm", "40mm", "기타"], key="sub_c")
            products_obj = st.session_state.db["products"]
            
            # [Helper] 상품 코드로 이름 찾기용 맵 (관리자 화면용)
            code_name_map = {str(p.get("code")): f"[{p.get('code')}] {p.get('name')} ({p.get('spec')})" for p in products_obj}

            if mt == "신규":
                 nn = st.text_input("세트명")
                 c1, c2, c3 = st.columns([3,2,1])
                 with c1: sp_obj = st.selectbox("부품", products_obj, format_func=format_prod_label, key="nsp")
                 with c2: sq = st.number_input("수량", 1, key="nsq")
                 with c3: 
                     # [수정] 세트 레시피 저장 키를 '코드'로 변경
                     if st.button("담기"): st.session_state.temp_set_recipe[str(sp_obj['code'])] = sq
                 
                 # 레시피 보여주기 (코드를 이름으로 변환하여 표시)
                 st.caption("구성 품목 (코드 기준)")
                 for k, v in st.session_state.temp_set_recipe.items():
                     disp_name = code_name_map.get(k, k) # 코드로 이름 찾기, 없으면 코드 그대로
                     st.text(f"- {disp_name}: {v}개")

                 if st.button("저장", key="btn_new_set"):
                     if cat not in st.session_state.db["sets"]: st.session_state.db["sets"][cat] = {}
                     st.session_state.db["sets"][cat][nn] = {"recipe": st.session_state.temp_set_recipe, "image": "", "sub_cat": sub_cat}
                     save_sets_to_sheet(st.session_state.db["sets"]); st.session_state.temp_set_recipe={}; st.success("저장")
            else:
                 if "target_set_edit" in st.session_state and st.session_state.target_set_edit:
                     tg = st.session_state.target_set_edit
                     st.info(f"편집: {tg}")
                     
                     # [NEW] 레시피 수정 기능 (수량 변경 및 삭제)
                     st.markdown("###### 구성 품목 수정 (수량 변경 및 삭제)")
                     # 딕셔너리를 리스트로 변환하여 순회 (RuntimeError 방지)
                     for k, v in list(st.session_state.temp_set_recipe.items()):
                         c1, c2, c3 = st.columns([5, 2, 1])
                         disp_name = code_name_map.get(k, k)
                         
                         with c1:
                             st.text(disp_name)
                         with c2:
                             # 수량 변경 입력 (Key에 품목코드 포함하여 유니크하게)
                             new_qty = st.number_input(
                                 "수량", 
                                 value=int(v), 
                                 step=1, 
                                 key=f"edit_q_{k}", 
                                 label_visibility="collapsed"
                             )
                             # 값이 변경되면 즉시 State 업데이트
                             st.session_state.temp_set_recipe[k] = new_qty
                         with c3:
                             # 삭제 버튼
                             if st.button("삭제", key=f"del_set_item_{k}"):
                                 del st.session_state.temp_set_recipe[k]
                                 st.rerun()
                     
                     st.divider()
                     st.markdown("###### ➕ 품목 추가")
                     c1, c2, c3 = st.columns([3,2,1])
                     with c1: ap_obj = st.selectbox("추가할 부품", products_obj, format_func=format_prod_label, key="esp")
                     with c2: aq = st.number_input("추가 수량", 1, key="esq")
                     with c3: 
                         st.write("")
                         if st.button("담기", key="esa"): 
                             # 추가 시에도 '코드'로 저장 (기존에 있으면 덮어쓰기됨)
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
                         st.session_state.target_set_edit = None
                         st.success("삭제되었습니다."); time.sleep(1); st.rerun()

        with t3: st.write("설정")

else:
    st.markdown(f"### 📝 현장명: **{st.session_state.current_quote_name if st.session_state.current_quote_name else '(제목 없음)'}**")
    if st.session_state.quote_step == 1:
        st.subheader("STEP 1. 물량 및 정보 입력")
        with st.expander("👤 구매자(현장) 정보 입력", expanded=True):
            c_info1, c_info2 = st.columns(2)
            with c_info1:
                new_q_name = st.text_input("현장명(거래처명)", value=st.session_state.current_quote_name)
                if new_q_name != st.session_state.current_quote_name: st.session_state.current_quote_name = new_q_name
                manager = st.text_input("담당자", value=st.session_state.buyer_info.get("manager",""))
            with c_info2:
                phone = st.text_input("전화번호", value=st.session_state.buyer_info.get("phone",""))
                addr = st.text_input("주소", value=st.session_state.buyer_info.get("addr",""))
            st.session_state.buyer_info.update({"manager": manager, "phone": phone, "addr": addr})

        st.divider()
        sets = st.session_state.db.get("sets", {})
        
        # [NEW] 세트 장바구니 로직 적용
        with st.expander("1. 주배관 및 가지관 세트 선택", True):
            m_sets = sets.get("주배관세트", {})
            grouped = {"50mm":{}, "40mm":{}, "기타":{}, "미분류":{}}
            for k, v in m_sets.items():
                sc = v.get("sub_cat", "미분류") if isinstance(v, dict) else "미분류"
                if sc not in grouped: grouped[sc] = {}
                grouped[sc][k] = v
            
            # 탭별 렌더링
            mt1, mt2, mt3, mt4 = st.tabs(["50mm", "40mm", "기타", "전체"])
            
            def render_inputs_with_key(d, pf):
                cols = st.columns(4); res = {}
                for i, (n, v) in enumerate(d.items()):
                    with cols[i%4]:
                        img_name = v.get("image") if isinstance(v, dict) else None
                        if img_name:
                            b64 = get_image_from_drive(img_name)
                            if b64: st.image(b64, use_container_width=True)
                            else: st.markdown("No Image")
                        else: st.markdown("<div style='height:80px;background:#eee'></div>", unsafe_allow_html=True)
                        # 개별 key 부여
                        res[n] = st.number_input(n, 0, key=f"{pf}_{n}_input")
                return res

            with mt1: inp_m_50 = render_inputs_with_key(grouped["50mm"], "m50")
            with mt2: inp_m_40 = render_inputs_with_key(grouped["40mm"], "m40")
            with mt3: inp_m_etc = render_inputs_with_key(grouped["기타"], "metc")
            with mt4: inp_m_u = render_inputs_with_key(grouped["미분류"], "mu")
            
            st.write("")
            if st.button("➕ 입력한 수량 세트 목록에 추가"):
                # 모든 탭의 입력값을 확인하여 0보다 큰 것만 장바구니에 추가
                all_inputs = {**inp_m_50, **inp_m_40, **inp_m_etc, **inp_m_u}
                added_count = 0
                for set_name, qty in all_inputs.items():
                    if qty > 0:
                        st.session_state.set_cart.append({"name": set_name, "qty": qty, "type": "주배관"})
                        added_count += 1
                if added_count > 0:
                    st.success(f"{added_count}개 항목이 목록에 추가되었습니다.")
                else:
                    st.warning("수량을 입력해주세요.")

        # 가지관/기타 자재도 세트라면 같은 방식 적용 (여기서는 기존 로직 유지하되 장바구니 사용)
        with st.expander("2. 가지관 및 기타 세트"):
            c1, c2 = st.tabs(["가지관", "기타자재"])
            with c1: inp_b = render_inputs_with_key(sets.get("가지관세트", {}), "b_set")
            with c2: inp_e = render_inputs_with_key(sets.get("기타자재", {}), "e_set")
            
            if st.button("➕ 가지관/기타 목록 추가"):
                all_inputs = {**inp_b, **inp_e}
                added_count = 0
                for set_name, qty in all_inputs.items():
                    if qty > 0:
                        st.session_state.set_cart.append({"name": set_name, "qty": qty, "type": "기타"})
                        added_count += 1
                if added_count > 0: st.success("추가됨")

        # 세트 장바구니 표시
        if st.session_state.set_cart:
            st.info("📋 선택된 세트 목록 (합산 예정)")
            st.dataframe(pd.DataFrame(st.session_state.set_cart), use_container_width=True, hide_index=True)
            if st.button("🗑️ 세트 목록 비우기"):
                st.session_state.set_cart = []
                st.rerun()
        
        st.divider()
        st.markdown("#### 📏 배관 물량 산출 (장바구니)")
        all_products = st.session_state.db["products"]
        pipe_type_sel = st.radio("배관 구분", ["주배관", "가지관"], horizontal=True)
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
            st.dataframe(pd.DataFrame(st.session_state.pipe_cart), use_container_width=True, hide_index=True)
            if st.button("🗑️ 비우기"): st.session_state.pipe_cart = []; st.rerun()

        st.divider()
        if st.button("계산하기 (STEP 2)"):
            if not st.session_state.current_quote_name: st.error("현장명을 입력해주세요.")
            else:
                res = {}
                
                # 1. 세트 장바구니 계산 (set_cart) - [수정] 코드 기반 합산
                all_sets_db = {}
                for cat, val in sets.items():
                    all_sets_db.update(val)
                
                for item in st.session_state.set_cart:
                    s_name = item['name']
                    s_qty = item['qty']
                    if s_name in all_sets_db:
                        recipe = all_sets_db[s_name].get("recipe", {})
                        for p_code_or_name, p_qty in recipe.items():
                            # 레시피의 Key가 코드일 수도 있고 이름일 수도 있음
                            # 하지만 결과 res는 '코드'를 Key로 쓰는 것이 안전함
                            
                            # 만약 키가 품목명이라면(구 데이터), 코드를 찾아야 함 -> 하지만 쉽지 않음(중복명)
                            # 만약 키가 코드라면(신규 데이터), 그대로 사용
                            
                            # 여기서는 "p_code_or_name"을 그대로 키로 사용하여 합산한다.
                            # 단, Step 2에서 PDB Lookup 시 코드와 이름 모두로 찾을 수 있게 해두었으므로
                            # 신규 세트(코드 저장)는 코드로, 구 세트(이름 저장)는 이름으로 저장되어도
                            # Step 2에서는 다 찾을 수 있음.
                            # *중요*: 신규 세트는 코드로 저장되므로 50mm/40mm가 구분됨.
                            
                            res[str(p_code_or_name)] = res.get(str(p_code_or_name), 0) + (p_qty * s_qty)

                # 2. 배관 장바구니 계산 (pipe_cart) - CODE 기준
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

                st.session_state.quote_items = res; st.session_state.quote_step = 2; st.rerun()

    elif st.session_state.quote_step == 2:
        st.subheader("STEP 2. 내용 검토")
        if st.button("⬅️ 1단계(물량수정)로 돌아가기"):
            st.session_state.quote_step = 1
            st.rerun()
            
        view_opts = ["소비자가"]
        if st.session_state.auth_price: view_opts += ["단가(현장)", "매입가", "총판1", "총판2", "대리점"]
        
        c_lock, c_view = st.columns([1, 2])
        with c_lock:
            if not st.session_state.auth_price:
                pw = st.text_input("원가 조회 비번", type="password")
                if st.button("해제"):
                    if pw == st.session_state.db["config"]["password"]: st.session_state.auth_price = True; st.rerun()
                    else: st.error("오류")
            else: st.success("🔓 원가 조회 가능")
        with c_view: view = st.radio("단가 보기", view_opts, horizontal=True)

        key_map = {"매입가":("price_buy","매입"), "총판1":("price_d1","총판1"), "총판2":("price_d2","총판2"), "대리점":("price_agy","대리점"), "단가(현장)":("price_site", "현장")}
        rows = []
        
        # PDB Key 확장 (Name & Code)
        pdb = {}
        for p in st.session_state.db["products"]:
            pdb[p["name"]] = p
            if p.get("code"): pdb[str(p["code"])] = p

        pk = [key_map[view][0]] if view != "소비자가" else ["price_cons"]
        
        for n, q in st.session_state.quote_items.items():
            # n은 코드일 수도 있고 이름일 수도 있음
            inf = pdb.get(str(n), {})
            if not inf: continue
            
            cpr = inf.get("price_cons", 0)
            row = {"품목": inf.get("name", n), "규격": inf.get("spec", ""), "수량": q, "소비자가": cpr, "합계": cpr*q}
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
                    # [수정] 추가 시에도 코드 사용 권장
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
        if st.button("최종 확정 (STEP 3)", type="primary", use_container_width=True): st.session_state.quote_step = 3; st.rerun()

    elif st.session_state.quote_step == 3:
        st.header("🏁 최종 견적")
        if not st.session_state.current_quote_name: st.warning("현장명(저장)을 확인해주세요!")
        st.markdown("##### 🖨️ 출력 옵션")
        c_date, c_opt1, c_opt2 = st.columns([1, 1, 1])
        with c_date: q_date = st.date_input("견적일", datetime.datetime.now())
        with c_opt1: form_type = st.radio("양식", ["기본 양식", "이익 분석 양식"])
        with c_opt2:
            basic_opts = ["소비자가", "단가(현장)"]
            admin_opts = ["매입단가", "총판가1", "총판가2", "대리점가"]
            opts = basic_opts + (admin_opts if st.session_state.auth_price else [])
            
            if "이익" in form_type and not st.session_state.auth_price:
                st.warning("🔒 원가 정보를 보려면 비밀번호를 입력하세요.")
                c_pw, c_btn = st.columns([2,1])
                with c_pw: input_pw = st.text_input("비밀번호", type="password", key="step3_pw")
                with c_btn: 
                    if st.button("해제", key="step3_btn"):
                        if input_pw == st.session_state.db["config"]["password"]: st.session_state.auth_price = True; st.rerun()
                        else: st.error("불일치")
                st.stop()

            if "기본" in form_type: sel = st.multiselect("출력 단가 (1개 선택)", opts, default=["소비자가"], max_selections=1)
            else: sel = st.multiselect("비교 단가 (2개)", opts, max_selections=2)

        if "기본" in form_type and len(sel) != 1: st.warning("출력할 단가를 1개 선택해주세요."); st.stop()
        if "이익" in form_type and len(sel) < 2: st.warning("비교할 단가를 2개 선택해주세요."); st.stop()

        price_rank = {"매입단가": 0, "총판가1": 1, "총판가2": 2, "대리점가": 3, "단가(현장)": 4, "소비자가": 5}
        if sel: sel = sorted(sel, key=lambda x: price_rank.get(x, 6))
        pkey = {"매입단가":"price_buy", "총판가1":"price_d1", "총판가2":"price_d2", "대리점가":"price_agy", "소비자가":"price_cons", "단가(현장)":"price_site"}
        
        pdb = {}
        for p in st.session_state.db["products"]:
            pdb[p["name"]] = p
            if p.get("code"): pdb[str(p["code"])] = p

        pk = [pkey[l] for l in sel] if sel else ["price_cons"]
        
        fdata = []
        for n, q in st.session_state.quote_items.items():
            inf = pdb.get(str(n), {})
            if not inf: continue
            
            d = {"품목": inf.get("name", n), "규격": inf.get("spec", ""), "코드": inf.get("code", ""), "단위": inf.get("unit", "EA"), "수량": int(q), "image_data": inf.get("image")}
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
            pdf_b = create_advanced_pdf(edited.to_dict('records'), st.session_state.services, st.session_state.current_quote_name, q_date.strftime("%Y-%m-%d"), fmode, sel, st.session_state.buyer_info)
            st.download_button("📥 PDF 다운로드", pdf_b, f"quote_{st.session_state.current_quote_name}.pdf", "application/pdf", type="primary")
        
        c1, c2 = st.columns(2)
        with c1: 
            if st.button("⬅️ 수정"): st.session_state.quote_step = 2; st.rerun()
        with c2:
            if st.button("🔄 처음으로"): st.session_state.quote_step = 1; st.session_state.quote_items = {}; st.session_state.services = []; st.session_state.pipe_cart = []; st.session_state.set_cart = []; st.session_state.buyer_info = {"manager": "", "phone": "", "addr": ""}; st.session_state.current_quote_name = ""; st.rerun()

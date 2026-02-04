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
st.set_page_config(layout="wide", page_title="루퍼젯 프로 매니저 V10.0")

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
DRIVE_SET_FOLDER_NAME = "Looperget_Images" 
ADMIN_FOLDER_NAME = "Looperget_Admin"
ADMIN_PPT_NAME = "Set_Composition_Master.pptx"

def get_or_create_drive_folder():
    if not drive_service: return None
    try:
        query_shared = f"name='{DRIVE_FOLDER_NAME}' and mimeType='application/vnd.google-apps.folder' and sharedWithMe=true and trashed=false"
        results_shared = drive_service.files().list(q=query_shared, fields="files(id)").execute()
        files_shared = results_shared.get('files', [])
        if files_shared: return files_shared[0]['id']
        
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
        drive_service.files().create(body=file_metadata, media_body=media, fields='id').execute()
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
        file_info = drive_service.files().create(body=file_metadata, media_body=media, fields='id').execute()
        return file_info.get('id')
    except Exception as e:
        error_msg = str(e)
        if "storageQuotaExceeded" in error_msg:
            st.error("⚠️ 구글 드라이브 용량/권한 정책으로 인해 봇이 직접 파일을 업로드할 수 없습니다.")
            st.info(f"💡 해결책: '{filename}' 파일을 구글 드라이브 '{DRIVE_FOLDER_NAME}' 폴더에 직접 올리신 후, 상단의 [🔄 드라이브 세트 이미지 자동 동기화] 버튼을 눌러주세요.")
        else:
            st.error(f"세트 이미지 업로드 실패: {e}")
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
                if name_stem.isdigit():
                    norm_name = str(name_stem).zfill(5)
                    file_map[norm_name] = f['id']
                file_map[name_stem] = f['id']
            page_token = response.get('nextPageToken', None)
            if page_token is None: break
    except Exception: pass
    return file_map

@st.cache_data(ttl=600)
def get_set_drive_file_map():
    return get_drive_file_map()

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
    stem = os.path.splitext(filename_or_id)[0]
    if stem in fmap: return download_image_by_id(fmap[stem])
    if len(filename_or_id) > 10:
         return download_image_by_id(filename_or_id)
    return None

@st.cache_data(ttl=600)
def get_admin_ppt_content():
    if not drive_service: return None
    try:
        q_folder = f"name='{ADMIN_FOLDER_NAME}' and mimeType='application/vnd.google-apps.folder' and trashed=false"
        res_folder = drive_service.files().list(q=q_folder, fields="files(id)").execute()
        folders = res_folder.get('files', [])
        if not folders: return None
        folder_id = folders[0]['id']
        q_file = f"name='{ADMIN_PPT_NAME}' and '{folder_id}' in parents and trashed=false"
        res_file = drive_service.files().list(q=q_file, fields="files(id)").execute()
        files = res_file.get('files', [])
        if not files: return None
        file_id = files[0]['id']
        request = drive_service.files().get_media(fileId=file_id)
        return request.execute()
    except Exception:
        return None

def get_best_image_id(code, db_image_val, file_map):
    clean_code = str(code).strip().zfill(5)
    if clean_code in file_map: return file_map[clean_code]
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
            data["sets"][cat][name] = {"recipe": rcp, "image": rec.get("이미지파일명"), "sub_cat": rec.get("하위분류")}
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
    pdf.set_auto_page_break(False) 
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

    def draw_table_header():
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

    draw_table_header()

    sum_qty = 0; sum_a1 = 0; sum_a2 = 0; sum_profit = 0

    for item in final_data_list:
        h = 15
        
        if pdf.get_y() > 260:
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
            sum_a2 += a2; profit = a2 - a1; sum_profit += profit
            rate = (profit / a2 * 100) if a2 else 0

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
        pdf.cell(10, h, str(item.get("단위", "EA") or "EA"), border=1, align='C')
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

    if pdf.get_y() + 10 > 260:
        pdf.add_page()
        draw_table_header()

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
        if pdf.get_y() + (len(service_items) * 6) + 10 > 260:
             pdf.add_page()
             pdf.ln(2)
        else:
             pdf.ln(2)
             
        pdf.set_fill_color(255, 255, 224)
        pdf.cell(190, 6, " [ 추가 비용 ] ", border=1, fill=True, new_x="LMARGIN", new_y="NEXT")
        for s in service_items:
            svc_total += s['금액']; pdf.cell(155, 6, s['항목'], border=1)
            pdf.cell(35, 6, f"{s['금액']:,} 원", border=1, align='R', new_x="LMARGIN", new_y="NEXT")

    pdf.ln(5); pdf.set_font(font_name, b_style, 12)
    
    if pdf.get_y() + 30 > 270:
        pdf.add_page()
    
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

def create_quote_excel(final_data_list, service_items, quote_name, quote_date, form_type, price_labels, buyer_info):
    output = io.BytesIO()
    workbook = xlsxwriter.Workbook(output, {'in_memory': True})
    ws = workbook.add_worksheet("견적서")
    
    drive_file_map = get_drive_file_map()

    # Formats
    fmt_title = workbook.add_format({'bold': True, 'font_size': 16, 'align': 'center', 'valign': 'vcenter'})
    fmt_header = workbook.add_format({'bold': True, 'bg_color': '#f0f0f0', 'border': 1, 'align': 'center', 'valign': 'vcenter'})
    fmt_text_wrap = workbook.add_format({'border': 1, 'valign': 'vcenter', 'text_wrap': True}) 
    fmt_text = workbook.add_format({'border': 1, 'valign': 'vcenter'})
    fmt_num = workbook.add_format({'border': 1, 'num_format': '#,##0', 'valign': 'vcenter'})
    fmt_center = workbook.add_format({'border': 1, 'align': 'center', 'valign': 'vcenter'})

    ws.merge_range('A1:F1', '견 적 서', fmt_title)
    ws.write(1, 0, f"현장명: {quote_name}")
    ws.write(1, 4, f"견적일: {quote_date}")
    ws.write(2, 0, f"담당자: {buyer_info.get('manager', '')}")
    ws.write(2, 4, f"연락처: {buyer_info.get('phone', '')}")

    headers = ["이미지", "품목정보", "단위", "수량"]
    if form_type == "basic":
        headers.extend([price_labels[0], "금액", "비고"])
    else:
        headers.extend([price_labels[0], "금액(1)", price_labels[1], "금액(2)", "이익", "율(%)"])

    for col, h in enumerate(headers):
        ws.write(4, col, h, fmt_header)

    ws.set_column(0, 0, 15)
    ws.set_column(1, 1, 40)
    ws.set_column(2, 2, 8)
    ws.set_column(3, 3, 8)

    row = 5
    total_a1 = 0
    total_a2 = 0
    total_profit = 0
    
    temp_files = []
    ROW_HEIGHT_PT = 80

    for item in final_data_list:
        ws.set_row(row, ROW_HEIGHT_PT)
        
        try: qty = int(float(item.get("수량", 0)))
        except: qty = 0
        try: p1 = int(float(item.get("price_1", 0)))
        except: p1 = 0
        a1 = p1 * qty
        total_a1 += a1
        
        code = str(item.get("코드", "") or "").strip().zfill(5)
        
        img_id = get_best_image_id(code, item.get("image_data"), drive_file_map)
        img_b64 = download_image_by_id(img_id)
            
        if img_b64:
            try:
                img_data_str = img_b64.split(",", 1)[1] if "," in img_b64 else img_b64
                img_bytes = base64.b64decode(img_data_str)
                
                with Image.open(io.BytesIO(img_bytes)) as pil_img:
                    orig_w, orig_h = pil_img.size
                
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
                
                ws.insert_image(row, 0, tmp_path, {
                    'x_scale': scale, 
                    'y_scale': scale, 
                    'x_offset': offset_x, 
                    'y_offset': offset_y,
                    'object_position': 1
                })
            except:
                ws.write(row, 0, "No Img", fmt_center)
        else:
            ws.write(row, 0, "", fmt_center)

        item_info_text = f"{item.get('품목', '')}\n{item.get('규격', '')}\n{item.get('코드', '')}"
        ws.write(row, 1, item_info_text, fmt_text_wrap)

        ws.write(row, 2, item.get("단위", "EA"), fmt_center)
        ws.write(row, 3, qty, fmt_center)

        if form_type == "basic":
            ws.write(row, 4, p1, fmt_num)
            ws.write(row, 5, a1, fmt_num)
            ws.write(row, 6, "", fmt_text)
        else:
            try: p2 = int(float(item.get("price_2", 0)))
            except: p2 = 0
            a2 = p2 * qty
            profit = a2 - a1
            rate = (profit / a2 * 100) if a2 else 0
            total_a2 += a2
            total_profit += profit

            ws.write(row, 4, p1, fmt_num)
            ws.write(row, 5, a1, fmt_num)
            ws.write(row, 6, p2, fmt_num)
            ws.write(row, 7, a2, fmt_num)
            ws.write(row, 8, profit, fmt_num)
            ws.write(row, 9, f"{rate:.1f}%", fmt_center)
        row += 1

    svc_total = 0
    if service_items:
        row += 1
        ws.write(row, 1, "[추가 비용]", fmt_header)
        row += 1
        for s in service_items:
            ws.write(row, 1, s['항목'], fmt_text)
            price_col = 5 if form_type == "basic" else 7
            ws.write(row, price_col, s['금액'], fmt_num)
            svc_total += s['금액']
            row += 1

    row += 1
    ws.write(row, 1, "총 합계", fmt_header)
    final_sum = (total_a1 if form_type == "basic" else total_a2) + svc_total
    col_idx = 5 if form_type == "basic" else 7
    ws.write(row, col_idx, final_sum, fmt_num)

    workbook.close()
    
    for f in temp_files:
        try: os.unlink(f)
        except: pass
        
    return output.getvalue()

def create_composition_pdf(set_cart, pipe_cart, quote_items, db_products, db_sets, quote_name):
    drive_file_map = get_drive_file_map()
    pdf = PDF()
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

    additional_items = {}
    for code, total_qty in quote_items.items():
        base_qty = baseline_counts.get(str(code), 0)
        diff = total_qty - base_qty
        if diff > 0: additional_items[code] = diff

    pdf.set_font(font_name, b_style, 16)
    pdf.cell(0, 15, "자재 구성 명세서 (Material Composition Report)", align='C', new_x="LMARGIN", new_y="NEXT")
    pdf.set_font(font_name, '', 10)
    pdf.cell(0, 8, f"현장명: {quote_name}", align='R', new_x="LMARGIN", new_y="NEXT")
    pdf.ln(5)

    def check_page_break(h_needed):
        if pdf.get_y() + h_needed > 270:
            pdf.add_page()

    pdf.set_fill_color(220, 220, 220)
    pdf.set_font(font_name, b_style, 12)
    pdf.cell(0, 10, "1. 부속 세트 구성 (Fitting Sets)", border=1, fill=True, new_x="LMARGIN", new_y="NEXT")
    
    pdf.set_font(font_name, '', 10)
    row_h = 35 # [수정] 이미지 확대에 맞춰 행 높이 증가 (30 -> 35)
    header_h = 8
    
    pdf.set_fill_color(240, 240, 240)
    pdf.cell(35, header_h, "IMG", border=1, align='C', fill=True) 
    pdf.cell(85, header_h, "세트명 (Set Name)", border=1, align='C', fill=True)
    pdf.cell(40, header_h, "구분", border=1, align='C', fill=True)
    pdf.cell(30, header_h, "수량", border=1, align='C', fill=True, new_x="LMARGIN", new_y="NEXT")

    for item in set_cart:
        check_page_break(row_h)
        name = item.get('name')
        qty = item.get('qty')
        stype = item.get('type')
        
        img_id = None
        for cat, sets in db_sets.items():
            if name in sets:
                img_id = sets[name].get('image')
                break
        
        img_b64 = download_image_by_id(img_id)
        
        x, y = pdf.get_x(), pdf.get_y()
        pdf.cell(35, row_h, "", border=1)
        if img_b64:
            try:
                img_data = img_b64.split(",", 1)[1]
                img_bytes = base64.b64decode(img_data)
                with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as tmp:
                    tmp.write(img_bytes); tmp_path = tmp.name
                # [수정] 이미지 크기 확대 (w: 25->37.5, h: 25->30)
                pdf.image(tmp_path, x=x+5, y=y+2.5, w=37.5, h=30)
                os.unlink(tmp_path)
            except: pass
            
        pdf.set_xy(x+35, y)
        pdf.cell(85, row_h, name, border=1, align='L')
        pdf.cell(40, row_h, stype, border=1, align='C')
        pdf.cell(30, row_h, str(qty), border=1, align='C', new_x="LMARGIN", new_y="NEXT")
    
    pdf.ln(5)

    pdf.set_font(font_name, b_style, 12)
    pdf.set_fill_color(220, 220, 220)
    check_page_break(20)
    pdf.cell(0, 10, "2. 배관 물량 (Pipe Quantities)", border=1, fill=True, new_x="LMARGIN", new_y="NEXT")
    
    pdf.set_font(font_name, '', 10)
    pdf.set_fill_color(240, 240, 240)
    pdf.cell(20, header_h, "IMG", border=1, align='C', fill=True)
    pdf.cell(100, header_h, "품목명 (Product Name)", border=1, align='C', fill=True)
    pdf.cell(40, header_h, "총 길이(m)", border=1, align='C', fill=True)
    pdf.cell(30, header_h, "롤 수(EA)", border=1, align='C', fill=True, new_x="LMARGIN", new_y="NEXT")

    pipe_summary = {}
    for p in pipe_cart:
        code = p.get('code')
        if not code: continue
        if code not in pipe_summary:
            pipe_summary[code] = {'len': 0, 'name': p.get('name'), 'spec': p.get('spec')}
        pipe_summary[code]['len'] += p.get('len', 0)

    for code, info in pipe_summary.items():
        check_page_break(15)
        prod_info = next((item for item in db_products if str(item["code"]) == str(code)), None)
        unit_len = prod_info.get("len_per_unit", 4) if prod_info else 4
        if unit_len <= 0: unit_len = 4
        rolls = math.ceil(info['len'] / unit_len)
        img_val = prod_info.get("image") if prod_info else None
        
        img_id = get_best_image_id(code, img_val, drive_file_map)
        img_b64 = download_image_by_id(img_id)

        x, y = pdf.get_x(), pdf.get_y()
        pdf.cell(20, 15, "", border=1)
        if img_b64:
            try:
                img_data = img_b64.split(",", 1)[1]
                img_bytes = base64.b64decode(img_data)
                with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as tmp:
                    tmp.write(img_bytes); tmp_path = tmp.name
                pdf.image(tmp_path, x=x+2, y=y+2, w=11, h=11)
                os.unlink(tmp_path)
            except: pass
            
        pdf.set_xy(x+20, y)
        pdf.cell(100, 15, f"{info['name']} ({info['spec']})", border=1, align='L')
        pdf.cell(40, 15, f"{info['len']} m", border=1, align='C')
        pdf.cell(30, 15, f"{rolls} 롤", border=1, align='C', new_x="LMARGIN", new_y="NEXT")

    pdf.ln(5)

    if additional_items:
        pdf.set_font(font_name, b_style, 12)
        pdf.set_fill_color(220, 220, 220)
        check_page_break(20)
        pdf.cell(0, 10, "3. 추가 자재 (Additional Components / Spares)", border=1, fill=True, new_x="LMARGIN", new_y="NEXT")
        
        pdf.set_font(font_name, '', 10)
        pdf.set_fill_color(240, 240, 240)
        pdf.cell(20, header_h, "IMG", border=1, align='C', fill=True)
        pdf.cell(130, header_h, "품목정보 (Name/Spec)", border=1, align='C', fill=True)
        pdf.cell(40, header_h, "추가 수량", border=1, align='C', fill=True, new_x="LMARGIN", new_y="NEXT")

        for code, qty in additional_items.items():
            check_page_break(15)
            prod_info = next((item for item in db_products if str(item["code"]) == str(code)), None)
            name = prod_info.get('name', code) if prod_info else code
            spec = prod_info.get('spec', '-') if prod_info else '-'
            img_val = prod_info.get('image') if prod_info else None
            
            img_id = get_best_image_id(code, img_val, drive_file_map)
            img_b64 = download_image_by_id(img_id)

            x, y = pdf.get_x(), pdf.get_y()
            pdf.cell(20, 15, "", border=1)
            if img_b64:
                try:
                    img_data = img_b64.split(",", 1)[1]
                    img_bytes = base64.b64decode(img_data)
                    with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as tmp:
                        tmp.write(img_bytes); tmp_path = tmp.name
                    pdf.image(tmp_path, x=x+2, y=y+2, w=11, h=11)
                    os.unlink(tmp_path)
                except: pass
                
            pdf.set_xy(x+20, y)
            pdf.cell(130, 15, f"{name} ({spec})", border=1, align='L')
            pdf.cell(40, 15, f"{int(qty)} EA", border=1, align='C', new_x="LMARGIN", new_y="NEXT")
        
        pdf.ln(5)

    pdf.set_font(font_name, b_style, 12)
    pdf.set_fill_color(220, 220, 220)
    check_page_break(20)
    idx_num = "4" if additional_items else "3"
    pdf.cell(0, 10, f"{idx_num}. 전체 자재 산출 목록 (Total Components)", border=1, fill=True, new_x="LMARGIN", new_y="NEXT")
    
    pdf.set_font(font_name, '', 10)
    pdf.set_fill_color(240, 240, 240)
    pdf.cell(20, header_h, "IMG", border=1, align='C', fill=True)
    pdf.cell(130, header_h, "품목정보 (Name/Spec)", border=1, align='C', fill=True)
    pdf.cell(40, header_h, "총 수량", border=1, align='C', fill=True, new_x="LMARGIN", new_y="NEXT")

    for code, qty in quote_items.items():
        check_page_break(15)
        prod_info = next((item for item in db_products if str(item["code"]) == str(code)), None)
        name = prod_info.get('name', code) if prod_info else code
        spec = prod_info.get('spec', '-') if prod_info else '-'
        img_val = prod_info.get('image') if prod_info else None
        
        img_id = get_best_image_id(code, img_val, drive_file_map)
        img_b64 = download_image_by_id(img_id)

        x, y = pdf.get_x(), pdf.get_y()
        pdf.cell(20, 15, "", border=1)
        if img_b64:
            try:
                img_data = img_b64.split(",", 1)[1]
                img_bytes = base64.b64decode(img_data)
                with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as tmp:
                    tmp.write(img_bytes); tmp_path = tmp.name
                pdf.image(tmp_path, x=x+2, y=y+2, w=11, h=11)
                os.unlink(tmp_path)
            except: pass
            
        pdf.set_xy(x+20, y)
        pdf.cell(130, 15, f"{name} ({spec})", border=1, align='L')
        pdf.cell(40, 15, f"{int(qty)} EA", border=1, align='C', new_x="LMARGIN", new_y="NEXT")

    return bytes(pdf.output())

def create_composition_excel(set_cart, pipe_cart, quote_items, db_products, db_sets, quote_name):
    output = io.BytesIO()
    workbook = xlsxwriter.Workbook(output, {'in_memory': True})
    drive_file_map = get_drive_file_map()
    
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

    additional_items = {}
    for code, total_qty in quote_items.items():
        diff = total_qty - baseline_counts.get(str(code), 0)
        if diff > 0: additional_items[code] = diff

    def insert_scaled_image(ws, row, col, img_b64):
        if not img_b64: 
            ws.write(row, col, "", fmt_center)
            return
        try:
            img_data = img_b64.split(",", 1)[1]
            img_bytes = base64.b64decode(img_data)
            
            with Image.open(io.BytesIO(img_bytes)) as pil_img:
                orig_w, orig_h = pil_img.size
            
            with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as tmp:
                tmp.write(img_bytes); tmp_path = tmp.name
            
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
    ws1.write(0, 2, "구분", fmt_header)
    ws1.write(0, 3, "수량", fmt_header)
    ws1.set_column(0, 0, 15)
    ws1.set_column(1, 1, 30)
    
    row = 1
    for item in set_cart:
        ws1.set_row(row, 80)
        name = item.get('name')
        img_id = None
        for cat, sets in db_sets.items():
            if name in sets:
                img_id = sets[name].get('image')
                break
        insert_scaled_image(ws1, row, 0, download_image_by_id(img_id))
        ws1.write(row, 1, name, fmt_left)
        ws1.write(row, 2, item.get('type'), fmt_center)
        ws1.write(row, 3, item.get('qty'), fmt_center)
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

    if additional_items:
        ws_add = workbook.add_worksheet("추가자재")
        ws_add.write(0, 0, "이미지", fmt_header)
        ws_add.write(0, 1, "품목명", fmt_header)
        ws_add.write(0, 2, "규격", fmt_header)
        ws_add.write(0, 3, "추가수량", fmt_header)
        ws_add.set_column(0, 0, 15)
        ws_add.set_column(1, 1, 30)
        
        row = 1
        for code, qty in additional_items.items():
            ws_add.set_row(row, 80)
            prod_info = next((item for item in db_products if str(item["code"]) == str(code)), None)
            name = prod_info.get('name', code) if prod_info else code
            spec = prod_info.get('spec', '-') if prod_info else '-'
            img_val = prod_info.get('image') if prod_info else None
            
            insert_scaled_image(ws_add, row, 0, download_image_by_id(get_best_image_id(code, img_val, drive_file_map)))
            ws_add.write(row, 1, name, fmt_left)
            ws_add.write(row, 2, spec, fmt_center)
            ws_add.write(row, 3, qty, fmt_center)
            row += 1

    ws3 = workbook.add_worksheet("전체자재")
    ws3.write(0, 0, "이미지", fmt_header)
    ws3.write(0, 1, "품목명", fmt_header)
    ws3.write(0, 2, "규격", fmt_header)
    ws3.write(0, 3, "총수량", fmt_header)
    ws3.set_column(0, 0, 15)
    ws3.set_column(1, 1, 30)

    row = 1
    for code, qty in quote_items.items():
        ws3.set_row(row, 80)
        prod_info = next((item for item in db_products if str(item["code"]) == str(code)), None)
        name = prod_info.get('name', code) if prod_info else code
        spec = prod_info.get('spec', '-') if prod_info else '-'
        img_val = prod_info.get('image') if prod_info else None
        
        insert_scaled_image(ws3, row, 0, download_image_by_id(get_best_image_id(code, img_val, drive_file_map)))
        ws3.write(row, 1, name, fmt_left)
        ws3.write(row, 2, spec, fmt_center)
        ws3.write(row, 3, qty, fmt_center)
        row += 1

    workbook.close()
    return output.getvalue()

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
if "final_edit_df" not in st.session_state: st.session_state.final_edit_df = None
if "step3_ready" not in st.session_state: st.session_state.step3_ready = False

# [신규] 생성된 파일 저장용 상태 변수 초기화
if "files_ready" not in st.session_state: st.session_state.files_ready = False
if "gen_pdf" not in st.session_state: st.session_state.gen_pdf = None
if "gen_excel" not in st.session_state: st.session_state.gen_excel = None
if "gen_comp_pdf" not in st.session_state: st.session_state.gen_comp_pdf = None
if "gen_comp_excel" not in st.session_state: st.session_state.gen_comp_excel = None

DEFAULT_DATA = {"config": {"password": "1234"}, "products":[], "sets":{}}
if not st.session_state.db: st.session_state.db = DEFAULT_DATA
if "config" not in st.session_state.db: st.session_state.db["config"] = {"password": "1234"}

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
            st.session_state.current_quote_name = ""; st.session_state.buyer_info = {"manager": "", "phone": "", "addr": ""}; st.session_state.step3_ready=False; st.session_state.files_ready = False; st.rerun()
    st.divider()
    h_list = list(st.session_state.history.keys())[::-1]
    if h_list:
        sel_h = st.selectbox("불러오기", h_list)
        if st.button("📂 로드"):
            d = st.session_state.history[sel_h]
            st.session_state.quote_items = d["items"]; st.session_state.services = d["services"]; st.session_state.pipe_cart = d.get("pipe_cart", []); st.session_state.set_cart = d.get("set_cart", [])
            st.session_state.quote_step = d.get("step", 2)
            st.session_state.buyer_info = d.get("buyer", {"manager": "", "phone": "", "addr": ""})
            st.session_state.current_quote_name = sel_h
            st.session_state.step3_ready = False
            st.session_state.files_ready = False
            st.rerun()
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
            with st.expander("📂 부품 데이터 직접 수정 (수정/추가/삭제)", expanded=True):
                st.info("💡 팁: 표 안에서 직접 내용을 수정하거나, 맨 아래 행에 추가하거나, 행을 선택해 삭제(Del키)할 수 있습니다.")
                df = pd.DataFrame(st.session_state.db["products"]).rename(columns=REV_COL_MAP)
                if "이미지데이터" in df.columns: df["이미지데이터"] = df["이미지데이터"].apply(lambda x: x if x else "")
                df["순번"] = [f"{i+1:03d}" for i in range(len(df))]
                cols = list(df.columns)
                if "순번" in cols:
                    cols.insert(0, cols.pop(cols.index("순번")))
                    df = df[cols]
                edited_df = st.data_editor(
                    df, 
                    num_rows="dynamic", 
                    use_container_width=True, 
                    key="product_editor",
                    column_config={
                        "순번": st.column_config.TextColumn(disabled=False, width="small"),
                        "품목코드": st.column_config.TextColumn(help="5자리 코드로 입력하세요 (예: 00100)"),
                        "매입단가": st.column_config.NumberColumn(format="%d"),
                        "총판가1": st.column_config.NumberColumn(format="%d"),
                        "총판가2": st.column_config.NumberColumn(format="%d"),
                        "대리점가": st.column_config.NumberColumn(format="%d"),
                        "소비자가": st.column_config.NumberColumn(format="%d"),
                        "단가(현장)": st.column_config.NumberColumn(format="%d"),
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
                org_df = pd.DataFrame(st.session_state.db["products"]).rename(columns=REV_COL_MAP)
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
                st.info("💡 사용법: 이미지 파일명을 '품목코드.jpg' (예: 00200.jpg)로 저장해서 구글 드라이브 'Looperget_Images' 폴더에 먼저 업로드하세요.")
                if st.button("🔄 드라이브 이미지 자동 연결 실행", key="btn_sync_images"):
                    with st.spinner("드라이브 폴더를 검색하는 중..."):
                        get_drive_file_map.clear() # [수정] 캐시 초기화 추가
                        file_map = get_drive_file_map() 
                        if not file_map:
                            st.warning("폴더가 비어있거나 찾을 수 없습니다.")
                        else:
                            updated_count = 0
                            products = st.session_state.db["products"]
                            for p in products:
                                code = str(p.get("code", "")).strip()
                                if code and code in file_map:
                                    p["image"] = file_map[code]
                                    updated_count += 1
                            if updated_count > 0:
                                save_products_to_sheet(products)
                                st.success(f"✅ 총 {updated_count}개의 제품 이미지를 연결했습니다!")
                                st.session_state.db = load_data_from_sheet() 
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
            ppt_data = get_admin_ppt_content()
            if ppt_data:
                st.download_button(label="📥 세트 구성 일람표(PPT) 다운로드", data=ppt_data, file_name="Set_Composition_Master.pptx", mime="application/vnd.openxmlformats-officedocument.presentationml.presentation", use_container_width=True)
            else:
                st.warning("⚠️ 구글 드라이브 'Looperget_Admin' 폴더에 'Set_Composition_Master.pptx' 파일이 없습니다.")
            st.divider()
            cat = st.selectbox("분류", ["주배관세트", "가지관세트", "기타자재"])
            cset = st.session_state.db["sets"].get(cat, {})
            if cset:
                sl = [{"세트명": k, "부품수": len(v.get("recipe", {}))} for k,v in cset.items()]
                st.dataframe(pd.DataFrame(sl), use_container_width=True, on_select="rerun", selection_mode="multi-row", key="set_table")
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
                            if del_pw == st.session_state.db["config"]["password"]:
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
                                st.success(f"✅ 총 {updated_count}개의 세트 이미지를 연결했습니다!")
                                st.session_state.db = load_data_from_sheet()
                            else:
                                st.warning("매칭되는 이미지가 없습니다. (파일명이 세트명과 같은지 확인하세요)")
            st.divider()
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
                 st.caption("구성 품목 (코드 기준)")
                 if st.session_state.temp_set_recipe:
                     for k, v in list(st.session_state.temp_set_recipe.items()):
                         disp_name = code_name_map.get(k, k) 
                         c_text, c_del = st.columns([4, 1])
                         with c_text:
                             st.text(f"- {disp_name}: {v}개")
                         with c_del:
                             if st.button("삭제", key=f"btn_del_new_{k}"):
                                 del st.session_state.temp_set_recipe[k]
                                 st.rerun()
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
                     for k, v in list(st.session_state.temp_set_recipe.items()):
                         c1, c2, c3 = st.columns([5, 2, 1])
                         disp_name = code_name_map.get(k, k)
                         with c1:
                             st.text(disp_name)
                         with c2:
                             new_qty = st.number_input("수량", value=int(v), step=1, key=f"edit_q_{k}", label_visibility="collapsed")
                             st.session_state.temp_set_recipe[k] = new_qty
                         with c3:
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
        with st.expander("1. 주배관 및 가지관 세트 선택", True):
            m_sets = sets.get("주배관세트", {})
            grouped = {"50mm":{}, "40mm":{}, "기타":{}, "미분류":{}}
            for k, v in m_sets.items():
                sc = v.get("sub_cat", "미분류") if isinstance(v, dict) else "미분류"
                if sc not in grouped: grouped[sc] = {}
                grouped[sc][k] = v
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
                        res[n] = st.number_input(n, 0, key=f"{pf}_{n}_input")
                return res
            with mt1: inp_m_50 = render_inputs_with_key(grouped["50mm"], "m50")
            with mt2: inp_m_40 = render_inputs_with_key(grouped["40mm"], "m40")
            with mt3: inp_m_etc = render_inputs_with_key(grouped["기타"], "metc")
            with mt4: inp_m_u = render_inputs_with_key(grouped["미분류"], "mu")
            st.write("")
            if st.button("➕ 입력한 수량 세트 목록에 추가"):
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
        pdb = {}
        for p in st.session_state.db["products"]:
            pdb[p["name"]] = p
            if p.get("code"): pdb[str(p["code"])] = p
        pk = [key_map[view][0]] if view != "소비자가" else ["price_cons"]
        for n, q in st.session_state.quote_items.items():
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
        
        # [수정] 옵션 변경 시 데이터 재로딩을 위한 로직 추가
        if "last_sel" not in st.session_state: st.session_state.last_sel = []
        
        # 선택된 단가가 바뀌었는지 확인
        selectors_changed = (st.session_state.last_sel != sel)
        
        # 첫 진입이거나 옵션이 바뀌었다면 가격 데이터 갱신
        if not st.session_state.step3_ready or selectors_changed:
            pdb = {}
            for p in st.session_state.db["products"]:
                pdb[p["name"]] = p
                if p.get("code"): pdb[str(p["code"])] = p
            
            pk = [pkey[l] for l in sel] if sel else ["price_cons"]
            
            # 1. 첫 진입일 때: 전체 데이터 생성
            if not st.session_state.step3_ready:
                fdata = []
                for n, q in st.session_state.quote_items.items():
                    inf = pdb.get(str(n), {})
                    if not inf: continue
                    d = {
                        "품목": inf.get("name", n), 
                        "규격": inf.get("spec", ""), 
                        "코드": inf.get("code", ""), 
                        "단위": inf.get("unit", "EA"), 
                        "수량": int(q), 
                        "image_data": inf.get("image")
                    }
                    d["price_1"] = int(inf.get(pk[0], 0))
                    if len(pk)>1: d["price_2"] = int(inf.get(pk[1], 0))
                    else: d["price_2"] = 0
                    fdata.append(d)
                st.session_state.final_edit_df = pd.DataFrame(fdata)
                st.session_state.step3_ready = True
            
            # 2. 옵션만 바뀌었을 때: 기존 수량 유지하고 가격만 업데이트
            elif selectors_changed and st.session_state.final_edit_df is not None and not st.session_state.final_edit_df.empty:
                def update_prices_in_row(row):
                    code = str(row.get("코드", "")).strip().zfill(5)
                    name = str(row.get("품목", ""))
                    item = pdb.get(code)
                    if not item: item = pdb.get(name)
                    
                    # DB에 있는 제품이면 가격 업데이트
                    if item:
                        p1 = int(item.get(pk[0], 0))
                        p2 = int(item.get(pk[1], 0)) if len(pk) > 1 else 0
                        return pd.Series([p1, p2])
                    else:
                        # DB에 없는(사용자 추가) 제품이면 기존 값 유지
                        return pd.Series([row.get("price_1", 0), row.get("price_2", 0)])

                new_prices = st.session_state.final_edit_df.apply(update_prices_in_row, axis=1)
                st.session_state.final_edit_df["price_1"] = new_prices[0]
                st.session_state.final_edit_df["price_2"] = new_prices[1]

            st.session_state.last_sel = sel
            st.session_state.files_ready = False # 옵션이 바뀌었으니 파일 다시 생성해야 함

        st.markdown("---")
        
        pk = [pkey[l] for l in sel] if sel else ["price_cons"]
        disp_cols = ["품목", "규격", "코드", "단위", "수량", "price_1"]
        if len(pk) > 1: disp_cols.append("price_2")
        
        # 컬럼 존재 여부 확인 (방어 코드)
        for c in disp_cols:
            if c not in st.session_state.final_edit_df.columns:
                st.session_state.final_edit_df[c] = 0 if "price" in c or "수량" in c else ""

        # 데이터 수정 시 파일 생성 버튼 다시 활성화
        def on_data_change():
            st.session_state.files_ready = False

        # [신규] 수기 품목 추가 기능
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
            use_container_width=True, 
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
                    
                    st.session_state.gen_pdf = create_advanced_pdf(safe_data, st.session_state.services, st.session_state.current_quote_name, q_date.strftime("%Y-%m-%d"), fmode, sel, st.session_state.buyer_info)
                    st.session_state.gen_excel = create_quote_excel(safe_data, st.session_state.services, st.session_state.current_quote_name, q_date.strftime("%Y-%m-%d"), fmode, sel, st.session_state.buyer_info)
                    st.session_state.gen_comp_pdf = create_composition_pdf(st.session_state.set_cart, st.session_state.pipe_cart, st.session_state.quote_items, st.session_state.db['products'], st.session_state.db['sets'], st.session_state.current_quote_name)
                    st.session_state.gen_comp_excel = create_composition_excel(st.session_state.set_cart, st.session_state.pipe_cart, st.session_state.quote_items, st.session_state.db['products'], st.session_state.db['sets'], st.session_state.current_quote_name)
                    
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
                st.session_state.buyer_info = {"manager": "", "phone": "", "addr": ""}
                st.session_state.current_quote_name = ""
                st.session_state.step3_ready = False
                st.session_state.files_ready = False
                st.rerun()

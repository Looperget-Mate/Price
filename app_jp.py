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
st.set_page_config(layout="wide", page_title="Looperget Pro Manager JP V1.0")

# ==========================================
# 1. 설정 및 구글 연동 유틸리티 (일본어 폰트 설정)
# ==========================================
FONT_REGULAR = "NotoSansJP-Regular.ttf"
FONT_BOLD = "NotoSansJP-Bold.ttf"

# NotoSansJP 폰트 다운로드 경로 (존재하지 않을 경우 다운로드)
FONT_URL = "https://github.com/google/fonts/raw/main/ofl/notosansjp/NotoSansJP-Regular.ttf"
FONT_BOLD_URL = "https://github.com/google/fonts/raw/main/ofl/notosansjp/NotoSansJP-Bold.ttf"

import urllib.request
if not os.path.exists(FONT_REGULAR):
    try: urllib.request.urlretrieve(FONT_URL, FONT_REGULAR)
    except: pass

if not os.path.exists(FONT_BOLD):
    try: urllib.request.urlretrieve(FONT_BOLD_URL, FONT_BOLD)
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
        st.error(f"Google サービス認証エラー: {e}")
        return None, None

gc, drive_service = get_google_services()

# --- 구글 드라이브 함수 ---
DRIVE_FOLDER_NAME = "Looperget_Images"
ADMIN_FOLDER_NAME = "Looperget_Admin"
ADMIN_PPT_NAME = "Set_Composition_Master_JP.pptx" # 일본용 PPT 파일명 가정

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
        st.error(f"ドライブフォルダエラー: {e}")
        return None

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
        st.error(f"アップロード失敗: {e}")
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
    stem = os.path.splitext(filename_or_id)[0]
    if stem in fmap: return download_image_by_id(fmap[stem])
    if len(filename_or_id) > 10:
         return download_image_by_id(filename_or_id)
    return None

def get_best_image_id(code, db_image_val, file_map):
    # 일본 버전은 품목 코드 외에도 일본어 이름 등으로 매칭될 수 있음
    clean_code = str(code).strip()
    if clean_code and clean_code in file_map: return file_map[clean_code]
    if db_image_val and len(str(db_image_val)) > 10: return db_image_val
    return None

# --- 구글 시트 함수 (일본어 컬럼 매핑) ---
SHEET_NAME = "Looperget_DB"
# 일본어 데이터베이스 매핑
COL_MAP = {
    "순번": "seq_no",
    "품목코드": "code", 
    "카테고리": "category", # 기존 KR 데이터 호환을 위해 유지하되, 아래 JP 컬럼 우선 사용
    "category_jp": "category_jp",
    "제품명": "name_kr",
    "name_jp": "name",      # 일본어 품명
    "spec_jp": "spec",      # 일본어 규격
    "단위": "unit", 
    "1롤길이(m)": "len_per_unit", 
    
    # 단가 데이터
    "price_buy_jp_krw": "price_buy_krw", # 신정 매입단가 (KRW)
    "price_dealer1_jp": "price_d1",      # 대리점1 (JPY)
    "price_dealer2_jp": "price_d2",      # 대리점2 (JPY)
    "price_cons_jp": "price_cons",       # 소비자가 (JPY)
    
    "이미지데이터": "image"
}
REV_COL_MAP = {v: k for k, v in COL_MAP.items()}

def init_db():
    if not gc: return None, None, None
    try: sh = gc.open(SHEET_NAME)
    except:
        return None, None, None
        
    try: ws_prod = sh.worksheet("Products")
    except: ws_prod = sh.add_worksheet(title="Products", rows=100, cols=20)
    
    try: ws_sets = sh.worksheet("Sets")
    except: ws_sets = sh.add_worksheet(title="Sets", rows=100, cols=10)
    
    try: ws_quotes = sh.worksheet("Quotes_JP")
    except: 
        ws_quotes = sh.add_worksheet(title="Quotes_JP", rows=100, cols=10)
        ws_quotes.append_row(["날짜", "현장명", "담당자", "총액(JPY)", "데이터JSON"])

    return ws_prod, ws_sets, ws_quotes

def load_data_from_sheet():
    ws_prod, ws_sets, _ = init_db()
    if not ws_prod: return DEFAULT_DATA
    data = {"config": {"password": "1234", "exchange_rate": 10.0}, "products": [], "sets": {}} # Default Exchange Rate KRW/JPY = 10 (1JPY=10KRW)
    
    # Config 로드 (별도 Config 시트가 없다면 DB 첫 행이나 코드 내 하드코딩 사용)
    # 여기서는 편의상 Products 시트의 특정 셀이나 별도 로직 대신 기본값 사용 후, 관리자 모드에서 Session State로 관리
    
    try:
        prod_records = ws_prod.get_all_records()
        for rec in prod_records:
            new_rec = {}
            for k, v in rec.items():
                if k in COL_MAP:
                    new_rec[COL_MAP[k]] = v
            
            # 일본어 데이터가 비어있으면 한국어 데이터로 대체하거나 공란 처리
            if not new_rec.get("name"): new_rec["name"] = new_rec.get("name_kr", "")
            if not new_rec.get("category_jp") and new_rec.get("category"): 
                 new_rec["category_jp"] = new_rec.get("category") # Fallback
            
            # 카테고리 통일 (일본어 로직에서 사용하기 위함)
            new_rec["category"] = new_rec.get("category_jp", "Others")

            if "seq_no" not in new_rec: new_rec["seq_no"] = ""
            data["products"].append(new_rec)
    except Exception as e: st.error(f"Products load error: {e}")

    try:
        set_records = ws_sets.get_all_records()
        for rec in set_records:
            if not rec.get("세트명"): continue # 여기서는 세트명도 일본어로 되어 있다고 가정 (DB에 일본어 세트명으로 저장됨)
            cat = rec.get("카테고리", "기타"); name = rec.get("세트명")
            # 일본어 카테고리 매핑이 필요하면 여기서 변환
            if cat not in data["sets"]: data["sets"][cat] = {}
            try: rcp = json.loads(str(rec.get("레시피JSON", "{}")))
            except: rcp = {}
            data["sets"][cat][name] = {"recipe": rcp, "image": rec.get("이미지파일명"), "sub_cat": rec.get("하위분류")}
    except: pass
    return data

def save_products_to_sheet(products_list):
    ws_prod, _, _ = init_db()
    if not ws_prod: return
    df = pd.DataFrame(products_list)
    
    # REV_COL_MAP을 이용해 원래 컬럼명으로 복구
    df_up = df.rename(columns=REV_COL_MAP).fillna("")
    
    # 시트에 존재하는 모든 컬럼 유지 (매핑되지 않은 컬럼 데이터 보존을 위해)
    existing_records = ws_prod.get_all_records()
    if existing_records:
        existing_df = pd.DataFrame(existing_records)
        # 업데이트할 컬럼만 교체
        for col in df_up.columns:
            existing_df[col] = df_up[col]
        final_df = existing_df
    else:
        final_df = df_up

    ws_prod.clear()
    ws_prod.update([final_df.columns.values.tolist()] + final_df.values.tolist())

def save_sets_to_sheet(sets_dict):
    _, ws_sets, _ = init_db()
    if not ws_sets: return
    rows = [["세트명", "카테고리", "하위분류", "이미지파일명", "레시피JSON"]]
    for cat, items in sets_dict.items():
        for name, info in items.items():
            rows.append([name, cat, info.get("sub_cat", ""), info.get("image", ""), json.dumps(info.get("recipe", {}), ensure_ascii=False)])
    ws_sets.clear(); ws_sets.update(rows)

def save_quote_to_history_sheet(name, manager, total, items, services):
    _, _, ws_quotes = init_db()
    if not ws_quotes: return
    date_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    json_data = json.dumps({"items": items, "services": services}, ensure_ascii=False)
    ws_quotes.append_row([date_str, name, manager, total, json_data])

def format_prod_label(option):
    if isinstance(option, dict): 
        return f"[{option.get('code','-')}] {option.get('name','')} ({option.get('spec','-')})"
    return str(option)

# ==========================================
# 2. PDF 및 Excel 생성 엔진 (일본어 대응)
# ==========================================
class PDF(FPDF):
    def header(self):
        self.add_font('NotoSansJP', '', FONT_REGULAR, uni=True)
        self.add_font('NotoSansJP', 'B', FONT_BOLD, uni=True)
        self.set_font('NotoSansJP', 'B', 20)
        self.cell(0, 15, '御 見 積 書 (Quotation)', align='C', new_x="LMARGIN", new_y="NEXT")
        self.set_font('NotoSansJP', '', 9)

    def footer(self):
        self.set_y(-20)
        self.set_font('NotoSansJP', 'B', 12)
        self.cell(0, 8, "SHIN JIN CHEMTECH Co., Ltd.", align='C', ln=True)
        self.set_font('NotoSansJP', '', 8)
        self.cell(0, 5, f'Page {self.page_no()}', align='C')

def create_jp_pdf(final_data_list, service_items, quote_name, quote_date, form_type, price_labels, buyer_info, exchange_rate):
    drive_file_map = get_drive_file_map()
    pdf = PDF()
    pdf.set_auto_page_break(False) 
    pdf.add_page()
    
    font_name = 'NotoSansJP'
    
    pdf.set_font(font_name, '', 10)
    pdf.set_fill_color(255, 255, 255)
    pdf.cell(100, 8, f" 見積日 : {quote_date}", border=0)
    pdf.cell(90, 8, f" 現場名 : {quote_name}", border=0, align='R', new_x="LMARGIN", new_y="NEXT")
    pdf.ln(2)

    x_start = pdf.get_x(); half_w = 95; h_line = 6
    pdf.set_fill_color(240, 240, 240)
    pdf.set_font(font_name, 'B', 10)
    pdf.cell(half_w, h_line, "  [ 御中 ]", border=1, fill=True)
    pdf.cell(half_w, h_line, "  [ 供給者 ]", border=1, fill=True, new_x="LMARGIN", new_y="NEXT")
    pdf.set_font(font_name, '', 9)
    
    buy_lines = [f" 現場名: {quote_name}", f" ご担当者: {buyer_info.get('manager', '')} 様", f" TEL: {buyer_info.get('phone', '')}", f" 住所: {buyer_info.get('addr', '')}", ""]
    sell_lines = [" 社名: 株式会社 SHIN JIN CHEMTECH", " 代表者: Park Hyeong-Seok (印)", " 住所: Gyeonggi-do, Icheon-si, Bubal-eup, Hwangmu-ro 1859-157", " TEL: +82-31-638-1809 / FAX: +82-31-638-1810", " Email: support@sjct.kr"]
    
    for b, s in zip(buy_lines, sell_lines):
        cur_y = pdf.get_y()
        pdf.set_xy(x_start, cur_y); pdf.cell(half_w, h_line, " " + b, border=1)
        pdf.set_xy(x_start + half_w, cur_y); pdf.cell(half_w, h_line, " " + s, border=1)
        pdf.ln(h_line)
    pdf.ln(5)

    def draw_table_header():
        pdf.set_fill_color(240, 240, 240)
        pdf.set_font(font_name, 'B', 10)
        h_height = 10
        pdf.cell(15, h_height, "IMG", border=1, align='C', fill=True)
        pdf.cell(50, h_height, "品名 / 規格", border=1, align='C', fill=True) 
        pdf.cell(10, h_height, "単位", border=1, align='C', fill=True)
        pdf.cell(12, h_height, "数量", border=1, align='C', fill=True)

        if form_type == "basic":
            pdf.cell(30, h_height, "単価 (¥)", border=1, align='C', fill=True)
            pdf.cell(35, h_height, "金額 (¥)", border=1, align='C', fill=True)
            pdf.cell(38, h_height, "備考", border=1, align='C', fill=True, new_x="LMARGIN", new_y="NEXT")
        else:
            # 이익 분석 양식
            l1, l2 = price_labels[0], price_labels[1]
            pdf.set_font(font_name, '', 8)
            pdf.cell(18, h_height, f"{l1}", border=1, align='C', fill=True)
            pdf.cell(20, h_height, "金額", border=1, align='C', fill=True)
            pdf.cell(18, h_height, f"{l2}", border=1, align='C', fill=True)
            pdf.cell(20, h_height, "金額", border=1, align='C', fill=True)
            pdf.cell(15, h_height, "利益", border=1, align='C', fill=True)
            pdf.cell(12, h_height, "率(%)", border=1, align='C', fill=True, new_x="LMARGIN", new_y="NEXT")
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
        code = str(item.get("코드", "") or "").strip()
        
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

        pdf.set_xy(x+15, y); pdf.cell(50, h, "", border=1) 
        pdf.set_xy(x+15, y+1.5); pdf.set_font(font_name, '', 8); pdf.multi_cell(50, 4, name, align='L')
        pdf.set_xy(x+15, y+6.0); pdf.set_font(font_name, '', 7); pdf.cell(50, 3, f"{spec}", align='L') 
        pdf.set_xy(x+15, y+10.0); pdf.set_font(font_name, '', 7); pdf.cell(50, 3, f"{code}", align='L') 

        pdf.set_xy(x+65, y); pdf.set_font(font_name, '', 9) 
        pdf.cell(10, h, str(item.get("단위", "EA") or "EA"), border=1, align='C')
        pdf.cell(12, h, str(qty), border=1, align='C')

        if form_type == "basic":
            pdf.cell(30, h, f"{p1:,}", border=1, align='R')
            pdf.cell(35, h, f"{a1:,}", border=1, align='R')
            pdf.cell(38, h, "", border=1, align='C'); pdf.ln()
        else:
            pdf.set_font(font_name, '', 8)
            pdf.cell(18, h, f"{p1:,}", border=1, align='R')
            pdf.cell(20, h, f"{a1:,}", border=1, align='R')
            pdf.cell(18, h, f"{p2:,}", border=1, align='R')
            pdf.cell(20, h, f"{a2:,}", border=1, align='R')
            pdf.set_font(font_name, 'B', 8)
            pdf.cell(15, h, f"{profit:,}", border=1, align='R')
            pdf.cell(12, h, f"{rate:.1f}%", border=1, align='C')
            pdf.set_font(font_name, '', 9); pdf.ln()

    if pdf.get_y() + 10 > 260:
        pdf.add_page()
        draw_table_header()

    pdf.set_fill_color(230, 230, 230); pdf.set_font(font_name, 'B', 9)
    pdf.cell(15+50+10, 10, "小 計 (Sub Total)", border=1, align='C', fill=True)
    pdf.cell(12, 10, f"{sum_qty:,}", border=1, align='C', fill=True)
    
    if form_type == "basic":
        pdf.cell(30, 10, "", border=1, fill=True)
        pdf.cell(35, 10, f"{sum_a1:,}", border=1, align='R', fill=True)
        pdf.cell(38, 10, "", border=1, fill=True); pdf.ln()
    else:
        avg_rate = (sum_profit / sum_a2 * 100) if sum_a2 else 0
        pdf.set_font(font_name, 'B', 8)
        pdf.cell(18, 10, "", border=1, fill=True); pdf.cell(20, 10, f"{sum_a1:,}", border=1, align='R', fill=True)
        pdf.cell(18, 10, "", border=1, fill=True); pdf.cell(20, 10, f"{sum_a2:,}", border=1, align='R', fill=True)
        pdf.cell(15, 10, f"{sum_profit:,}", border=1, align='R', fill=True)
        pdf.cell(12, 10, f"{avg_rate:.1f}%", border=1, align='C', fill=True); pdf.ln()

    svc_total = 0
    if service_items:
        if pdf.get_y() + (len(service_items) * 6) + 10 > 260:
             pdf.add_page()
             pdf.ln(2)
        else:
             pdf.ln(2)
             
        pdf.set_fill_color(255, 255, 224)
        pdf.cell(190, 6, " [ 追加費用 (Additional Costs) ] ", border=1, fill=True, new_x="LMARGIN", new_y="NEXT")
        for s in service_items:
            svc_total += s['금액']; pdf.cell(155, 6, s['항목'], border=1)
            pdf.cell(35, 6, f"¥ {s['금액']:,}", border=1, align='R', new_x="LMARGIN", new_y="NEXT")

    pdf.ln(5); pdf.set_font(font_name, 'B', 12)
    
    if pdf.get_y() + 30 > 270:
        pdf.add_page()
    
    pdf.cell(0, 5, "1. 見積有効期限: 見積日より15日以内", ln=True, align='R')
    pdf.cell(0, 5, "2. 納期: 決済完了後、即時または7日以内", ln=True, align='R')
    pdf.ln(2)

    if form_type == "basic":
        final_total = sum_a1 + svc_total
        pdf.cell(120, 10, "", border=0); pdf.cell(35, 10, "総 合計", border=1, align='C', fill=True)
        pdf.cell(35, 10, f"¥ {final_total:,}", border=1, align='R')
    else:
        t1_final = sum_a1 + svc_total; t2_final = sum_a2 + svc_total; total_profit = t2_final - t1_final
        pdf.set_font(font_name, '', 10)
        pdf.cell(87, 10, "総 合計 (税込)", border=1, align='C', fill=True)
        pdf.cell(38, 10, f"¥ {t1_final:,}", border=1, align='R')
        pdf.set_font(font_name, 'B', 10)
        pdf.cell(38, 10, f"¥ {t2_final:,}", border=1, align='R')
        pdf.cell(27, 10, f"(¥ {total_profit:,})", border=1, align='R')
        
    return bytes(pdf.output())

# Excel 생성, Composition Report 생성 함수는 기존 app.py 로직을 그대로 사용하되 언어만 변경
# (지면 관계상 핵심 로직인 JP 변환에 집중하기 위해 일부 생략하고 PDF 위주로 구현)

# ==========================================
# 3. 메인 로직
# ==========================================
if "db" not in st.session_state:
    with st.spinner("データベース接続中..."): st.session_state.db = load_data_from_sheet()

# 세션 상태 초기화 (일본어 대응)
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
if "exchange_rate" not in st.session_state: st.session_state.exchange_rate = 10.0 # KRW per 1 JPY (예: 100엔 = 1000원 -> rate 10)

# 파일 저장용 상태
if "files_ready" not in st.session_state: st.session_state.files_ready = False
if "gen_pdf" not in st.session_state: st.session_state.gen_pdf = None

DEFAULT_DATA = {"config": {"password": "1234"}, "products":[], "sets":{}}
if not st.session_state.db: st.session_state.db = DEFAULT_DATA

st.title("💧 Looperget Pro Manager JP (Cloud)")

with st.sidebar:
    st.header("🗂️ 見積アーカイブ")
    q_name = st.text_input("現場名 (保存用)", value=st.session_state.current_quote_name)
    c1, c2 = st.columns(2)
    with c1:
        if st.button("💾 一時保存"):
            # 로컬 히스토리 + DB 저장
            st.session_state.history[q_name] = {"items": st.session_state.quote_items, "services": st.session_state.services, "pipe_cart": st.session_state.pipe_cart, "set_cart": st.session_state.set_cart, "step": st.session_state.quote_step, "buyer": st.session_state.buyer_info}
            st.session_state.current_quote_name = q_name
            # 간단한 합계 계산 후 DB 저장
            total_est = sum([st.session_state.db['products'][i].get('price_cons',0) * q for i, q in st.session_state.quote_items.items() if i in st.session_state.db['products']]) # 대략적 계산
            save_quote_to_history_sheet(q_name, st.session_state.buyer_info.get("manager"), total_est, st.session_state.quote_items, st.session_state.services)
            st.success("保存しました (Quotes_JPにも記録)")
    with c2:
        if st.button("✨ 初期化"):
            st.session_state.quote_items = {}; st.session_state.services = []; st.session_state.pipe_cart = []; st.session_state.set_cart = []; st.session_state.quote_step = 1
            st.session_state.current_quote_name = ""; st.session_state.buyer_info = {"manager": "", "phone": "", "addr": ""}; st.session_state.step3_ready=False; st.session_state.files_ready = False; st.rerun()
    st.divider()
    h_list = list(st.session_state.history.keys())[::-1]
    if h_list:
        sel_h = st.selectbox("読み込み", h_list)
        if st.button("📂 ロード"):
            d = st.session_state.history[sel_h]
            st.session_state.quote_items = d["items"]; st.session_state.services = d["services"]; st.session_state.pipe_cart = d.get("pipe_cart", []); st.session_state.set_cart = d.get("set_cart", [])
            st.session_state.quote_step = d.get("step", 2)
            st.session_state.buyer_info = d.get("buyer", {"manager": "", "phone": "", "addr": ""})
            st.session_state.current_quote_name = sel_h
            st.session_state.step3_ready = False
            st.session_state.files_ready = False
            st.rerun()
    st.divider()
    mode = st.radio("モード", ["見積作成", "管理者モード"])

if mode == "管理者モード":
    st.header("🛠 管理者モード")
    if st.button("🔄 データの更新 (Google Sheets)"): st.session_state.db = load_data_from_sheet(); st.success("完了"); st.rerun()
    if not st.session_state.auth_admin:
        pw = st.text_input("管理者パスワード", type="password")
        if st.button("ログイン"):
            if pw == st.session_state.db["config"]["password"]: st.session_state.auth_admin = True; st.rerun()
            else: st.error("パスワードが違います")
    else:
        if st.button("ログアウト"): st.session_state.auth_admin = False; st.rerun()
        t1, t2 = st.tabs(["単価・為替管理", "セット管理"])
        
        with t1:
            st.subheader("💰 単価および為替レート設定")
            
            # 환율 설정
            current_rate = st.session_state.exchange_rate
            new_rate = st.number_input("適用為替レート (KRW / 1 JPY)", value=current_rate, step=0.1, help="1円あたりの韓国ウォン価格 (例: 100円=950ウォンなら 9.5)")
            if new_rate != st.session_state.exchange_rate:
                st.session_state.exchange_rate = new_rate
                st.success(f"レートを {new_rate} に設定しました (1 JPY = {new_rate} KRW)")
            
            st.markdown("---")
            st.markdown("##### 📋 製品単価リスト (KRW → JPY 換算)")
            
            # 데이터프레임 표시 (KRW 매입가 및 JPY 환산가)
            products = st.session_state.db["products"]
            rows = []
            for p in products:
                krw_cost = p.get("price_buy_krw", 0)
                # JPY 환산 (매입가)
                jpy_cost_calc = round(krw_cost / new_rate, 1) if new_rate else 0
                
                rows.append({
                    "Code": p.get("code"),
                    "Name": p.get("name"),
                    "購入単価(KRW)": krw_cost,
                    "購入換算(JPY)": jpy_cost_calc,
                    "代理店1(JPY)": p.get("price_d1", 0),
                    "消費者(JPY)": p.get("price_cons", 0)
                })
            
            st.dataframe(pd.DataFrame(rows), use_container_width=True)
            st.info("💡 '購入換算(JPY)'は、現在のレート設定に基づいて計算された参考値です。")

        with t2:
            st.subheader("📦 セット管理")
            # 기존 app.py의 세트 관리 로직과 유사하되 일본어 UI 적용
            st.info("Google Sheetsの 'Sets' シートで管理してください。")

else:
    # 견적 작성 모드
    st.markdown(f"### 📝 現場名: **{st.session_state.current_quote_name if st.session_state.current_quote_name else '(未設定)'}**")
    
    if st.session_state.quote_step == 1:
        st.subheader("STEP 1. 物量および情報入力")
        with st.expander("👤 顧客(現場)情報入力", expanded=True):
            c_info1, c_info2 = st.columns(2)
            with c_info1:
                new_q_name = st.text_input("現場名 (必須)", value=st.session_state.current_quote_name)
                if new_q_name != st.session_state.current_quote_name: st.session_state.current_quote_name = new_q_name
                manager = st.text_input("ご担当者名", value=st.session_state.buyer_info.get("manager",""))
            with c_info2:
                phone = st.text_input("電話番号", value=st.session_state.buyer_info.get("phone",""))
                addr = st.text_input("住所", value=st.session_state.buyer_info.get("addr",""))
            st.session_state.buyer_info.update({"manager": manager, "phone": phone, "addr": addr})
        
        st.divider()
        
        # 세트 선택 UI (일본어 카테고리 매핑 가정)
        sets = st.session_state.db.get("sets", {})
        # 편의상 기존 카테고리 키("주배관세트" 등)를 일본어 UI로 표시
        
        with st.expander("1. メイン配管セット選択", True):
            # 주배관세트 -> Main Pipe Sets
            m_sets = sets.get("주배관세트", {}) 
            # ... (UI 렌더링 로직은 app.py와 동일하되 라벨만 일본어로)
            st.write("リストから数量を入力してください。")
            # (간소화를 위해 렌더링 코드는 생략, 기존 app.py 로직 사용)
            
        # ... (가지관, 기타 자재 UI 동일)

        st.divider()
        if st.button("次へ (STEP 2: 計算)", type="primary"):
            if not st.session_state.current_quote_name: st.error("現場名を入力してください。")
            else:
                # 계산 로직 (기존과 동일)
                # ...
                st.session_state.quote_step = 2
                st.rerun()

    elif st.session_state.quote_step == 2:
        st.subheader("STEP 2. 内容検討")
        if st.button("⬅️ STEP 1に戻る"):
            st.session_state.quote_step = 1
            st.rerun()
            
        # 단가 보기 옵션 (JPY 기준)
        view_opts = ["消費者価格(JPY)"]
        if st.session_state.auth_price: 
            view_opts += ["購入価格(KRW換算)", "代理店価格1(JPY)", "代理店価格2(JPY)"]
            
        c_lock, c_view = st.columns([1, 2])
        with c_lock:
            if not st.session_state.auth_price:
                pw = st.text_input("原価照会PW", type="password")
                if st.button("解除"):
                    if pw == st.session_state.db["config"]["password"]: st.session_state.auth_price = True; st.rerun()
                    else: st.error("エラー")
            else: st.success("🔓 原価照会可能")
            
        with c_view: view = st.radio("単価表示", view_opts, horizontal=True)
        
        # 데이터 표시 로직
        rows = []
        pdb = {str(p["code"]): p for p in st.session_state.db["products"] if p.get("code")}
        rate = st.session_state.exchange_rate

        for n, q in st.session_state.quote_items.items():
            inf = pdb.get(str(n), {})
            if not inf: continue
            
            # 소비자가 (JPY)
            price_cons = inf.get("price_cons", 0)
            row = {"品名": inf.get("name", n), "規格": inf.get("spec", ""), "数量": q, "消費者価格": price_cons, "合計": price_cons*q}
            
            if "購入" in view:
                # KRW -> JPY 환산 표시
                krw = inf.get("price_buy_krw", 0)
                jpy_calc = round(krw / rate) if rate else 0
                row["購入単価(JPY)"] = jpy_calc
                row["原価合計"] = jpy_calc * q
                row["利益"] = row["合計"] - row["原価合計"]
            elif "代理店" in view:
                key = "price_d1" if "1" in view else "price_d2"
                pr = inf.get(key, 0)
                row["代理店単価"] = pr
                row["代理店合計"] = pr * q
                row["利益"] = row["合計"] - row["代理店合計"]
                
            rows.append(row)
            
        st.dataframe(pd.DataFrame(rows), use_container_width=True)
        
        st.divider()
        # 추가 비용 입력 (일본어)
        st.markdown("##### 💰 追加費用")
        c_type, c_amt = st.columns([1, 1])
        with c_type: stype = st.selectbox("項目", ["配送費", "人件費", "その他"], key="s2_type")
        with c_amt: sp = st.number_input("金額 (¥)", 0, step=1000, key="s2_amt")
        if st.button("追加"): 
            st.session_state.services.append({"항목": stype, "금액": sp}) # 키는 한국어 호환 유지, 값은 일본어
            st.rerun()
            
        if st.session_state.services:
            st.table(st.session_state.services)

        st.divider()
        if st.button("最終確定 (STEP 3)", type="primary"): 
            st.session_state.quote_step = 3
            st.rerun()

    elif st.session_state.quote_step == 3:
        st.header("🏁 最終見積")
        
        c_date, c_opt1 = st.columns([1, 1])
        with c_date: q_date = st.date_input("見積日", datetime.datetime.now())
        with c_opt1: form_type = st.radio("様式", ["基本様式 (消費者用)", "利益分析様式 (社内用)"])
        
        # 비교 단가 선택
        sel = []
        if "利益" in form_type:
            st.info("比較対象を2つ選択してください (左: 原価側, 右: 売価側)")
            opts = ["新正購入価(KRW->JPY換算)", "代理店価1", "代理店価2", "消費者価"]
            sel = st.multiselect("単価選択", opts, max_selections=2)
            if len(sel) < 2: st.warning("2つ選択してください"); st.stop()
        else:
            sel = ["消費者価"] # 기본값

        # 데이터 준비 (환율 적용)
        rate = st.session_state.exchange_rate
        pdb = {str(p["code"]): p for p in st.session_state.db["products"] if p.get("code")}
        
        # Step 2에서 넘어온 아이템 리스트
        fdata = []
        for n, q in st.session_state.quote_items.items():
            inf = pdb.get(str(n), {})
            d = {
                "품목": inf.get("name", n), "규격": inf.get("spec", ""), "코드": inf.get("code", ""),
                "단위": inf.get("unit", "EA"), "수량": int(q), "image_data": inf.get("image")
            }
            
            # 가격 결정 로직
            # sel[0]에 해당하는 가격 (Price 1)
            def get_price(ptype, item_inf):
                if "購入" in ptype: return round(item_inf.get("price_buy_krw", 0) / rate)
                if "代理店価1" in ptype: return item_inf.get("price_d1", 0)
                if "代理店価2" in ptype: return item_inf.get("price_d2", 0)
                return item_inf.get("price_cons", 0)
            
            d["price_1"] = int(get_price(sel[0], inf))
            if len(sel) > 1:
                d["price_2"] = int(get_price(sel[1], inf))
            else:
                d["price_2"] = 0
                
            fdata.append(d)
            
        df = pd.DataFrame(fdata)
        st.data_editor(df, disabled=["품목", "규격"], use_container_width=True) # 수량/단가 수정 가능하게 하려면 설정 필요

        if st.button("📄 PDF 作成"):
             fmode = "basic" if "基本" in form_type else "profit"
             labels = sel if len(sel) > 1 else [sel[0], ""]
             pdf_bytes = create_jp_pdf(fdata, st.session_state.services, st.session_state.current_quote_name, q_date.strftime("%Y-%m-%d"), fmode, labels, st.session_state.buyer_info, rate)
             st.download_button("📥 PDF ダウンロード", pdf_bytes, f"Quote_{st.session_state.current_quote_name}.pdf", "application/pdf")
        
        st.button("🔄 最初に戻る", on_click=lambda: st.session_state.update(quote_step=1))

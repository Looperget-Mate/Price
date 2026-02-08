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
st.set_page_config(layout="wide", page_title="Looperget Pro Manager JP V1.1")

# ==========================================
# [위치 이동] 기본 데이터 정의 (에러 방지용)
# ==========================================
DEFAULT_DATA = {"config": {"password": "1234"}, "products":[], "sets":{}}

# ==========================================
# 1. 설정 및 구글 연동 유틸리티 (일본어 폰트 설정)
# ==========================================
FONT_REGULAR = "NotoSansJP-Regular.ttf"
FONT_BOLD = "NotoSansJP-Bold.ttf"

# NotoSansJP 폰트 다운로드 경로
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
    clean_code = str(code).strip()
    if clean_code and clean_code in file_map: return file_map[clean_code]
    if db_image_val and len(str(db_image_val)) > 10: return db_image_val
    return None

# --- 구글 시트 함수 (일본어 컬럼 매핑) ---
SHEET_NAME = "Looperget_DB"
COL_MAP = {
    "순번": "seq_no",
    "품목코드": "code", 
    "카테고리": "category", 
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
    data = {"config": {"password": "1234"}, "products": [], "sets": {}} 
    
    try:
        prod_records = ws_prod.get_all_records()
        for rec in prod_records:
            new_rec = {}
            for k, v in rec.items():
                if k in COL_MAP:
                    new_rec[COL_MAP[k]] = v
            
            if not new_rec.get("name"): new_rec["name"] = new_rec.get("name_kr", "")
            if not new_rec.get("category_jp") and new_rec.get("category"): 
                 new_rec["category_jp"] = new_rec.get("category")
            
            new_rec["category"] = new_rec.get("category_jp", "Others")

            if "seq_no" not in new_rec: new_rec["seq_no"] = ""
            data["products"].append(new_rec)
    except Exception as e: st.error(f"Products load error: {e}")

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
    ws_prod, _, _ = init_db()
    if not ws_prod: return
    df = pd.DataFrame(products_list)
    
    df_up = df.rename(columns=REV_COL_MAP).fillna("")
    
    existing_records = ws_prod.get_all_records()
    if existing_records:
        existing_df = pd.DataFrame(existing_records)
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
# 2. PDF 및 Excel 생성 엔진
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
            pdf.add_page(); draw_table_header() 

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
        a1 = int(p1 * qty)
        sum_a1 += a1
        
        p2 = 0; a2 = 0; profit = 0; rate = 0
        if form_type == "profit":
            try: p2 = int(float(item.get("price_2", 0)))
            except: p2 = 0
            a2 = int(p2 * qty)
            sum_a2 += a2
            profit = int(a2 - a1)
            sum_profit += profit
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
        pdf.add_page(); draw_table_header()

    pdf.set_fill_color(230, 230, 230); pdf.set_font(font_name, 'B', 9)
    pdf.cell(15+50+10, 10, "小 計 (Sub Total)", border=1, align='C', fill=True)
    pdf.cell(12, 10, f"{sum_qty:,}", border=1, align='C', fill=True)
    
    sum_a1 = int(sum_a1)
    sum_a2 = int(sum_a2)
    sum_profit = int(sum_profit)
    
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
             pdf.add_page(); pdf.ln(2)
        else:
             pdf.ln(2)
        pdf.set_fill_color(255, 255, 224)
        pdf.cell(190, 6, " [ 追加費用 (Additional Costs) ] ", border=1, fill=True, new_x="LMARGIN", new_y="NEXT")
        for s in service_items:
            amt = int(s['금액'])
            svc_total += amt
            pdf.cell(155, 6, s['항목'], border=1)
            pdf.cell(35, 6, f"¥ {amt:,}", border=1, align='R', new_x="LMARGIN", new_y="NEXT")

    pdf.ln(5); pdf.set_font(font_name, 'B', 12)
    if pdf.get_y() + 30 > 270: pdf.add_page()
    
    pdf.cell(0, 5, "1. 見積有効期限: 見積日より15日以内", ln=True, align='R')
    pdf.cell(0, 5, "2. 納期: 決済完了後、即時または7日以内", ln=True, align='R')
    pdf.ln(2)

    svc_total = int(svc_total)

    if form_type == "basic":
        final_total = int(sum_a1 + svc_total)
        pdf.cell(120, 10, "", border=0); pdf.cell(35, 10, "総 合計", border=1, align='C', fill=True)
        pdf.cell(35, 10, f"¥ {final_total:,}", border=1, align='R')
    else:
        t1_final = int(sum_a1 + svc_total)
        t2_final = int(sum_a2 + svc_total)
        total_profit = int(t2_final - t1_final)
        pdf.set_font(font_name, '', 10)
        pdf.cell(87, 10, "総 合計 (税込)", border=1, align='C', fill=True)
        pdf.cell(38, 10, f"¥ {t1_final:,}", border=1, align='R')
        pdf.set_font(font_name, 'B', 10)
        pdf.cell(38, 10, f"¥ {t2_final:,}", border=1, align='R')
        pdf.cell(27, 10, f"(¥ {total_profit:,})", border=1, align='R')
        
    return bytes(pdf.output())

def create_jp_excel(final_data_list, service_items, quote_name, quote_date, form_type, price_labels, buyer_info):
    output = io.BytesIO()
    workbook = xlsxwriter.Workbook(output, {'in_memory': True})
    ws = workbook.add_worksheet("Quotation")
    drive_file_map = get_drive_file_map()

    fmt_title = workbook.add_format({'bold': True, 'font_size': 16, 'align': 'center', 'valign': 'vcenter'})
    fmt_header = workbook.add_format({'bold': True, 'bg_color': '#f0f0f0', 'border': 1, 'align': 'center', 'valign': 'vcenter'})
    fmt_text = workbook.add_format({'border': 1, 'valign': 'vcenter'})
    fmt_num = workbook.add_format({'border': 1, 'num_format': '#,##0', 'valign': 'vcenter'})
    fmt_center = workbook.add_format({'border': 1, 'align': 'center', 'valign': 'vcenter'})

    ws.merge_range('A1:F1', '御 見 積 書', fmt_title)
    ws.write(1, 0, f"現場名: {quote_name}")
    ws.write(1, 4, f"日付: {quote_date}")
    ws.write(2, 0, f"担当者: {buyer_info.get('manager', '')}")
    
    headers = ["画像", "品名", "単位", "数量"]
    if form_type == "basic":
        headers.extend([price_labels[0], "金額", "備考"])
    else:
        headers.extend([price_labels[0], "金額(1)", price_labels[1], "金額(2)", "利益", "率(%)"])
    
    for col, h in enumerate(headers):
        ws.write(4, col, h, fmt_header)
        
    ws.set_column(0, 0, 15); ws.set_column(1, 1, 40)
    
    row = 5
    total_a1 = 0; total_a2 = 0; total_profit = 0
    temp_files = []
    
    for item in final_data_list:
        ws.set_row(row, 60)
        
        try: qty = int(float(item.get("수량", 0)))
        except: qty = 0
        try: p1 = int(float(item.get("price_1", 0)))
        except: p1 = 0
        
        a1 = int(p1 * qty)
        total_a1 += a1
        
        code = str(item.get("코드", "")).strip()
        img_id = get_best_image_id(code, item.get("image_data"), drive_file_map)
        img_b64 = download_image_by_id(img_id)
        
        if img_b64:
            try:
                img_data_str = img_b64.split(",", 1)[1] if "," in img_b64 else img_b64
                img_bytes = base64.b64decode(img_data_str)
                with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as tmp:
                    tmp.write(img_bytes); tmp_path = tmp.name; temp_files.append(tmp_path)
                ws.insert_image(row, 0, tmp_path, {'x_scale': 0.5, 'y_scale': 0.5, 'object_position': 1})
            except: ws.write(row, 0, "No Img", fmt_center)
        else: ws.write(row, 0, "", fmt_center)

        ws.write(row, 1, f"{item.get('품목','')}\n{item.get('규격','')}", fmt_text)
        ws.write(row, 2, item.get("단위", "EA"), fmt_center)
        ws.write(row, 3, qty, fmt_center)
        
        if form_type == "basic":
            ws.write(row, 4, p1, fmt_num)
            ws.write(row, 5, a1, fmt_num)
            ws.write(row, 6, "", fmt_text)
        else:
            try: p2 = int(float(item.get("price_2", 0)))
            except: p2 = 0
            a2 = int(p2 * qty)
            profit = int(a2 - a1)
            rate = (profit / a2) if a2 else 0
            total_a2 += a2; total_profit += profit
            
            ws.write(row, 4, p1, fmt_num)
            ws.write(row, 5, a1, fmt_num)
            ws.write(row, 6, p2, fmt_num)
            ws.write(row, 7, a2, fmt_num)
            ws.write(row, 8, profit, fmt_num)
            ws.write(row, 9, rate, workbook.add_format({'border': 1, 'num_format': '0.0%', 'valign': 'vcenter'}))
        row += 1

    svc_total = 0
    if service_items:
        row += 1; ws.write(row, 1, "[追加費用]", fmt_header); row += 1
        for s in service_items:
            amt = int(s['금액'])
            svc_total += amt
            ws.write(row, 1, s['항목'], fmt_text)
            col_idx = 5 if form_type == "basic" else 7
            ws.write(row, col_idx, amt, fmt_num)
            row += 1
            
    row += 1
    ws.write(row, 1, "総 合計", fmt_header)
    final_sum = int((total_a1 if form_type == "basic" else total_a2) + svc_total)
    col_idx = 5 if form_type == "basic" else 7
    ws.write(row, col_idx, final_sum, fmt_num)
    
    workbook.close()
    for f in temp_files:
        try: os.unlink(f)
        except: pass
    return output.getvalue()

# ==========================================
# 3. 메인 로직
# ==========================================
if "db" not in st.session_state:
    with st.spinner("データベース接続中..."): st.session_state.db = load_data_from_sheet()

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
if "exchange_rate" not in st.session_state: st.session_state.exchange_rate = 10.0 # Default

if "files_ready" not in st.session_state: st.session_state.files_ready = False
if "gen_pdf" not in st.session_state: st.session_state.gen_pdf = None
if "gen_excel" not in st.session_state: st.session_state.gen_excel = None

if not st.session_state.db: st.session_state.db = DEFAULT_DATA

st.title("💧 Looperget Pro Manager JP (Cloud)")

with st.sidebar:
    st.header("🗂️ 見積アーカイブ")
    q_name = st.text_input("現場名 (保存用)", value=st.session_state.current_quote_name)
    c1, c2 = st.columns(2)
    with c1:
        if st.button("💾 一時保存"):
            st.session_state.history[q_name] = {"items": st.session_state.quote_items, "services": st.session_state.services, "pipe_cart": st.session_state.pipe_cart, "set_cart": st.session_state.set_cart, "step": st.session_state.quote_step, "buyer": st.session_state.buyer_info}
            st.session_state.current_quote_name = q_name
            # 간단 합계 (정수화)
            total_est = int(sum([st.session_state.db['products'][i].get('price_cons',0) * q for i, q in st.session_state.quote_items.items() if i in st.session_state.db['products']]))
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
            
            # 1. 환율 설정
            current_rate = st.session_state.exchange_rate
            new_rate = st.number_input("適用為替レート (KRW / 1 JPY)", value=current_rate, step=0.1, help="1円あたりの韓国ウォン価格 (例: 100円=950ウォンなら 9.5)")
            if new_rate != st.session_state.exchange_rate:
                st.session_state.exchange_rate = new_rate
                st.success(f"レートを {new_rate} に設定しました (1 JPY = {new_rate} KRW)")
            
            st.divider()
            
            # 2. 일괄 업데이트 (DB 저장 기능 포함) - [수정됨]
            st.markdown("##### ⚡️ 単価一括更新 (DB保存)")
            st.info("現在のレートとマージン率に基づいて、全ての製品の日本販売価格を計算し、DBに上書きします。")
            
            c_marg1, c_marg2 = st.columns(2)
            with c_marg1: margin_d = st.number_input("代理店マージン (%)", value=20.0, step=1.0)
            with c_marg2: margin_c = st.number_input("消費者マージン (%)", value=30.0, step=1.0)
            
            if st.button("🚨 レートとマージンを適用してDBを更新する", type="primary"):
                products = st.session_state.db["products"]
                updated_count = 0
                for p in products:
                    krw_cost = p.get("price_buy_krw", 0)
                    if krw_cost > 0:
                        # 엔화 원가 (KRW / Rate) -> 정수화
                        base_jp = krw_cost / new_rate
                        # 가격 책정 (반올림하여 정수화)
                        p["price_d1"] = int(base_jp * (1 + margin_d/100)) # 대리점가
                        p["price_cons"] = int(base_jp * (1 + margin_c/100)) # 소비자가
                        updated_count += 1
                
                if updated_count > 0:
                    save_products_to_sheet(products)
                    st.session_state.db = load_data_from_sheet()
                    st.success(f"{updated_count}件の製品単価を更新しました！")
                else:
                    st.warning("更新対象の製品がありません (price_buy_krw データを確認してください)")

            st.markdown("---")
            st.markdown("##### 📋 製品単価リスト (KRW → JPY 換算プレビュー)")
            
            products = st.session_state.db["products"]
            rows = []
            for p in products:
                krw_cost = p.get("price_buy_krw", 0)
                jpy_cost_calc = int(krw_cost / new_rate) if new_rate else 0
                rows.append({
                    "Code": p.get("code"),
                    "Name": p.get("name"),
                    "購入単価(KRW)": krw_cost,
                    "購入換算(JPY)": jpy_cost_calc,
                    "代理店1(JPY)": p.get("price_d1", 0),
                    "消費者(JPY)": p.get("price_cons", 0)
                })
            st.dataframe(pd.DataFrame(rows), use_container_width=True)

        with t2:
            st.subheader("📦 セット管理")
            st.info("Google Sheetsの 'Sets' シートで管理してください。")

else:
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
        sets = st.session_state.db.get("sets", {})
        
        with st.expander("1. メイン配管セット選択", True):
            m_sets = sets.get("주배관세트", {}) 
            grouped = {"50mm":{}, "40mm":{}, "기타":{}, "미분류":{}}
            for k, v in m_sets.items():
                sc = v.get("sub_cat", "미분류") if isinstance(v, dict) else "미분류"
                if sc not in grouped: grouped[sc] = {}
                grouped[sc][k] = v
            mt1, mt2, mt3, mt4 = st.tabs(["50mm", "40mm", "その他", "全て"])
            
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
            
            if st.button("➕ 入力した数量を追加"):
                all_inputs = {**inp_m_50, **inp_m_40, **inp_m_etc, **inp_m_u}
                added_count = 0
                for set_name, qty in all_inputs.items():
                    if qty > 0:
                        st.session_state.set_cart.append({"name": set_name, "qty": qty, "type": "メイン"})
                        added_count += 1
                if added_count > 0: st.success(f"{added_count}項目を追加しました。")

        if st.session_state.set_cart:
            st.info("📋 選択されたセットリスト")
            st.dataframe(pd.DataFrame(st.session_state.set_cart), use_container_width=True, hide_index=True)
            if st.button("🗑️ リストを空にする"): st.session_state.set_cart = []; st.rerun()

        st.divider()
        if st.button("次へ (STEP 2: 計算)", type="primary"):
            if not st.session_state.current_quote_name: st.error("現場名を入力してください。")
            else:
                res = {}
                all_sets_db = {}
                for cat, val in sets.items(): all_sets_db.update(val)
                for item in st.session_state.set_cart:
                    s_name = item['name']; s_qty = item['qty']
                    if s_name in all_sets_db:
                        recipe = all_sets_db[s_name].get("recipe", {})
                        for p_code_or_name, p_qty in recipe.items():
                            res[str(p_code_or_name)] = res.get(str(p_code_or_name), 0) + (p_qty * s_qty)
                st.session_state.quote_items = res; st.session_state.quote_step = 2; st.rerun()

    elif st.session_state.quote_step == 2:
        st.subheader("STEP 2. 内容検討")
        if st.button("⬅️ STEP 1に戻る"): st.session_state.quote_step = 1; st.rerun()
            
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
        
        rows = []
        pdb = {str(p["code"]): p for p in st.session_state.db["products"] if p.get("code")}
        rate = st.session_state.exchange_rate

        for n, q in st.session_state.quote_items.items():
            inf = pdb.get(str(n), {})
            if not inf: continue
            
            # 소비자가 (JPY, 정수)
            price_cons = int(inf.get("price_cons", 0))
            row = {"品名": inf.get("name", n), "規格": inf.get("spec", ""), "数量": q, "消費者価格": price_cons, "合計": price_cons*q}
            
            if "購入" in view:
                # KRW -> JPY 환산 표시 (정수)
                krw = inf.get("price_buy_krw", 0)
                jpy_calc = int(krw / rate) if rate else 0
                row["購入単価(JPY)"] = jpy_calc
                row["原価合計"] = jpy_calc * q
                row["利益"] = row["合計"] - row["原価合計"]
            elif "代理店" in view:
                key = "price_d1" if "1" in view else "price_d2"
                pr = int(inf.get(key, 0))
                row["代理店単価"] = pr
                row["代理店合計"] = pr * q
                row["利益"] = row["合計"] - row["代理店合計"]
            rows.append(row)
            
        st.dataframe(pd.DataFrame(rows), use_container_width=True)
        
        st.divider()
        st.markdown("##### 💰 追加費用")
        c_type, c_amt = st.columns([1, 1])
        with c_type: stype = st.selectbox("項目", ["配送費", "人件費", "その他"], key="s2_type")
        with c_amt: sp = st.number_input("金額 (¥)", 0, step=1000, key="s2_amt")
        if st.button("追加"): 
            st.session_state.services.append({"항목": stype, "금액": int(sp)}) # 정수 저장
            st.rerun()
        if st.session_state.services: st.table(st.session_state.services)

        st.divider()
        if st.button("最終確定 (STEP 3)", type="primary"): 
            st.session_state.quote_step = 3; st.rerun()

    elif st.session_state.quote_step == 3:
        st.header("🏁 最終見積")
        c_date, c_opt1 = st.columns([1, 1])
        with c_date: q_date = st.date_input("見積日", datetime.datetime.now())
        with c_opt1: form_type = st.radio("様式", ["基本様式 (消費者用)", "利益分析様式 (社内用)"])
        
        sel = []
        if "利益" in form_type:
            st.info("比較対象を2つ選択してください (左: 原価側, 右: 売価側)")
            opts = ["新正購入価(KRW->JPY換算)", "代理店価1", "代理店価2", "消費者価"]
            sel = st.multiselect("単価選択", opts, max_selections=2)
            if len(sel) < 2: st.warning("2つ選択してください"); st.stop()
        else:
            sel = ["消費者価"] 

        rate = st.session_state.exchange_rate
        pdb = {str(p["code"]): p for p in st.session_state.db["products"] if p.get("code")}
        
        fdata = []
        for n, q in st.session_state.quote_items.items():
            inf = pdb.get(str(n), {})
            d = {
                "품목": inf.get("name", n), "규격": inf.get("spec", ""), "코드": inf.get("code", ""),
                "단위": inf.get("unit", "EA"), "수량": int(q), "image_data": inf.get("image")
            }
            def get_price(ptype, item_inf):
                if "購入" in ptype: return int(item_inf.get("price_buy_krw", 0) / rate)
                if "代理店価1" in ptype: return int(item_inf.get("price_d1", 0))
                if "代理店価2" in ptype: return int(item_inf.get("price_d2", 0))
                return int(item_inf.get("price_cons", 0))
            
            d["price_1"] = get_price(sel[0], inf)
            if len(sel) > 1: d["price_2"] = get_price(sel[1], inf)
            else: d["price_2"] = 0
            fdata.append(d)
            
        df = pd.DataFrame(fdata)
        st.data_editor(df, disabled=["품목", "규격"], use_container_width=True)

        if st.button("📄 PDF & Excel 作成"):
             fmode = "basic" if "基本" in form_type else "profit"
             labels = sel if len(sel) > 1 else [sel[0], ""]
             st.session_state.gen_pdf = create_jp_pdf(fdata, st.session_state.services, st.session_state.current_quote_name, q_date.strftime("%Y-%m-%d"), fmode, labels, st.session_state.buyer_info, rate)
             st.session_state.gen_excel = create_jp_excel(fdata, st.session_state.services, st.session_state.current_quote_name, q_date.strftime("%Y-%m-%d"), fmode, labels, st.session_state.buyer_info)
             st.session_state.files_ready = True
             st.rerun()

        if st.session_state.files_ready:
            st.success("ファイル生成完了！")
            c1, c2 = st.columns(2)
            with c1: st.download_button("📥 PDF ダウンロード", st.session_state.gen_pdf, f"Quote_{st.session_state.current_quote_name}.pdf", "application/pdf")
            with c2: st.download_button("📊 Excel ダウンロード", st.session_state.gen_excel, f"Quote_{st.session_state.current_quote_name}.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        
        st.button("🔄 最初に戻る", on_click=lambda: st.session_state.update(quote_step=1))

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
st.set_page_config(layout="wide", page_title="Looperget Pro Manager JP V10.0")

# ==========================================
# 1. 설정 및 구글 연동 유틸리티 (일본 현지화: NotoSansJP 폰트 적용)
# ==========================================
FONT_REGULAR = "NotoSansJP-Regular.ttf"
FONT_BOLD = "NotoSansJP-Bold.ttf"

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
        st.error(f"Googleサービス認証に失敗しました: {e}")
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
        st.error(f"ドライブフォルダエラー: {e}")
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
        st.error(f"アップロード失敗: {e}")
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
            st.error("⚠️ Googleドライブの容量/権限により直接アップロードできません。")
            st.info(f"💡 解決策: '{filename}' をGoogleドライブの '{DRIVE_FOLDER_NAME}' に手動でアップロード後、同期ボタンを押してください。")
        else:
            st.error(f"セット画像のアップロード失敗: {e}")
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

# 메모리 누수 방지
def download_image_by_id(file_id):
    if not file_id or not drive_service: return None
    try:
        request = drive_service.files().get_media(fileId=file_id)
        downloader = request.execute()
        with Image.open(io.BytesIO(downloader)) as img:
            img_rgb = img.convert('RGB')
            img_rgb.thumbnail((300, 225))
            buffer = io.BytesIO()
            img_rgb.save(buffer, format="JPEG")
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

# --- 구글 시트 함수 (일본 현지화: COL_MAP 적용) ---
SHEET_NAME = "Looperget_DB"
COL_MAP = {
    "순번": "seq_no",
    "품목코드": "code", "카테고리": "category_jp", "제품명": "name_kr",
    "name_jp": "name", "spec_jp": "spec", "단위": "unit", "1롤길이(m)": "len_per_unit",
    "price_buy_jp_krw": "price_buy", 
    "price_dealer1_jp": "price_d1", "price_dealer2_jp": "price_d2",
    "price_cons_jp": "price_cons", "단가(현장)": "price_site",
    "이미지데이터": "image", "신정공급가": "price_supply_jp"
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
    
    try: ws_jp = sh.worksheet("Quotes_JP")
    except: 
        try: ws_jp = sh.add_worksheet(title="Quotes_JP", rows=100, cols=10); ws_jp.append_row(["날짜", "현장명", "담당자", "총액", "데이터JSON"])
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
    data = {"config": {"app_pwd": "1234", "admin_pwd": "1234"}, "products": [], "sets": {}, "jp_quotes": []}
    
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
            data["sets"][cat][name] = {"recipe": rcp, "image": rec.get("이미지파일명"), "sub_cat": rec.get("하위분류")}
    except: pass
    try:
        sh = gc.open(SHEET_NAME)
        ws_jp = sh.worksheet("Quotes_JP")
        data["jp_quotes"] = ws_jp.get_all_records()
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
    if not gc: return
    try:
        sh = gc.open(SHEET_NAME)
        ws_sets = sh.worksheet("Sets")
        rows = [["세트명", "카테고리", "하위분류", "이미지파일명", "레시피JSON"]]
        for cat, items in sets_dict.items():
            for name, info in items.items():
                rows.append([name, cat, info.get("sub_cat", ""), info.get("image", ""), json.dumps(info.get("recipe", {}), ensure_ascii=False)])
        ws_sets.clear()
        ws_sets.update(rows)
    except Exception as e:
        st.error(f"セット保存エラー: {e}")

def format_prod_label(option):
    if isinstance(option, dict): return f"[{option.get('code','00000')}] {option.get('name','')} ({option.get('spec','-')})"
    return str(option)

def save_quote_to_sheet(timestamp, q_name, manager, total, json_data):
    if not gc: return False
    try:
        sh = gc.open(SHEET_NAME)
        ws_jp = sh.worksheet("Quotes_JP")
        ws_jp.append_row([str(timestamp), str(q_name), str(manager), int(total), json_data])
        return True
    except Exception as e:
        return False

# ==========================================
# 2. PDF 및 Excel 생성 엔진 (일본 현지화: NotoSansJP 및 용어 적용)
# ==========================================
class PDF(FPDF):
    def header(self):
        header_font = 'Helvetica'; header_style = 'B'
        if os.path.exists(FONT_REGULAR):
            self.add_font('NotoSansJP', '', FONT_REGULAR, uni=True)
            header_font = 'NotoSansJP'
            if os.path.exists(FONT_BOLD): self.add_font('NotoSansJP', 'B', FONT_BOLD, uni=True); header_style = 'B'
            else: header_style = ''
        self.set_font(header_font, header_style, 20)
        self.cell(0, 15, '御 見 積 書 (Quotation)', align='C', new_x="LMARGIN", new_y="NEXT")
        self.set_font(header_font, '', 9)

    def footer(self):
        self.set_y(-25) 
        footer_font = 'Helvetica'; footer_style = 'B'
        if os.path.exists(FONT_REGULAR):
            footer_font = 'NotoSansJP'
            if os.path.exists(FONT_BOLD): footer_style = 'B'
            else: footer_style = ''
        self.set_font(footer_font, footer_style, 12)
        self.cell(0, 5, "株式会社 SHIN JIN CHEMTECH", align='C', ln=True)
        self.set_font(footer_font, '', 9)
        self.cell(0, 5, "www.sjct.kr", align='C', ln=True)
        self.cell(0, 5, f'Page {self.page_no()}', align='C')

def create_advanced_pdf(final_data_list, service_items, quote_name, quote_date, form_type, price_labels, buyer_info, remarks):
    drive_file_map = get_drive_file_map()
    pdf = PDF()
    pdf.set_auto_page_break(False) 
    pdf.add_page()
    
    has_font = os.path.exists(FONT_REGULAR)
    has_bold = os.path.exists(FONT_BOLD)
    font_name = 'NotoSansJP' if has_font else 'Helvetica'
    b_style = 'B' if has_bold else ''
    
    pdf.set_font(font_name, '', 10)
    pdf.set_fill_color(255, 255, 255)
    pdf.cell(100, 8, f" 見積日 : {quote_date}", border=0)
    pdf.cell(90, 8, f" 現場名 : {quote_name}", border=0, align='R', new_x="LMARGIN", new_y="NEXT")
    pdf.ln(2)

    x_start = pdf.get_x(); half_w = 95; h_line = 6
    pdf.set_fill_color(240, 240, 240)
    pdf.set_font(font_name, b_style, 10)
    pdf.cell(half_w, h_line, "  [ 御中 ]", border=1, fill=True)
    pdf.cell(half_w, h_line, "  [ 供給者 ]", border=1, fill=True, new_x="LMARGIN", new_y="NEXT")
    pdf.set_font(font_name, '', 9)
    
    buy_lines = [f" 会社名(現場): {quote_name}", f" ご担当者: {buyer_info.get('manager', '')}", f" TEL: {buyer_info.get('phone', '')}", f" 住所: {buyer_info.get('addr', '')}", ""]
    sell_lines = [" 会社名: 株式会社 SHIN JIN CHEMTECH", " 代表者: Park Hyeong-Seok (印)", " 住所: Gyeonggi-do, Icheon-si, Bubal-eup, Hwangmu-ro 1859-157", " TEL: +82-31-638-1809 / FAX: +82-31-635-1801", " Email: support@sjct.kr / Web: www.sjct.kr"]
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
        pdf.cell(45, h_height, "品名 / 規格 / コード", border=1, align='C', fill=True) 
        pdf.cell(10, h_height, "単位", border=1, align='C', fill=True)
        pdf.cell(12, h_height, "数量", border=1, align='C', fill=True)

        if form_type == "기본 양식":
            pdf.cell(35, h_height, f"{price_labels[0]}", border=1, align='C', fill=True)
            pdf.cell(35, h_height, "金額", border=1, align='C', fill=True)
            pdf.cell(38, h_height, "備考", border=1, align='C', fill=True, new_x="LMARGIN", new_y="NEXT")
        else:
            l1, l2 = price_labels[0], price_labels[1]
            pdf.set_font(font_name, '', 8)
            pdf.cell(18, h_height, f"{l1}", border=1, align='C', fill=True)
            pdf.cell(22, h_height, "金額", border=1, align='C', fill=True)
            pdf.cell(18, h_height, f"{l2}", border=1, align='C', fill=True)
            pdf.cell(22, h_height, "金額", border=1, align='C', fill=True)
            pdf.cell(15, h_height, "利益", border=1, align='C', fill=True)
            pdf.cell(13, h_height, "率(%)", border=1, align='C', fill=True, new_x="LMARGIN", new_y="NEXT")
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
        if form_type == "이익 분석 양식":
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
                    tmp.write(img_bytes)
                    tmp_path = tmp.name
                pdf.image(tmp_path, x=x+2, y=y+2, w=11, h=11)
                if os.path.exists(tmp_path):
                    os.unlink(tmp_path)
            except: pass

        pdf.set_xy(x+15, y); pdf.cell(45, h, "", border=1) 
        pdf.set_xy(x+15, y+1.5); pdf.set_font(font_name, '', 8); pdf.multi_cell(45, 4, name, align='L')
        pdf.set_xy(x+15, y+6.0); pdf.set_font(font_name, '', 7); pdf.cell(45, 3, f"{spec}", align='L') 
        pdf.set_xy(x+15, y+10.0); pdf.set_font(font_name, '', 7); pdf.cell(45, 3, f"{code}", align='L') 

        pdf.set_xy(x+60, y); pdf.set_font(font_name, '', 9) 
        pdf.cell(10, h, str(item.get("단위", "EA") or "EA"), border=1, align='C')
        pdf.cell(12, h, str(qty), border=1, align='C')

        if form_type == "기본 양식":
            pdf.cell(35, h, f"¥ {p1:,}", border=1, align='R')
            pdf.cell(35, h, f"¥ {a1:,}", border=1, align='R')
            pdf.cell(38, h, "", border=1, align='C'); pdf.ln()
        else:
            pdf.set_font(font_name, '', 8)
            pdf.cell(18, h, f"¥{p1:,}", border=1, align='R')
            pdf.cell(22, h, f"¥{a1:,}", border=1, align='R')
            pdf.cell(18, h, f"¥{p2:,}", border=1, align='R')
            pdf.cell(22, h, f"¥{a2:,}", border=1, align='R')
            pdf.set_font(font_name, b_style, 8)
            pdf.cell(15, h, f"¥{profit:,}", border=1, align='R')
            pdf.cell(13, h, f"{rate:.1f}%", border=1, align='C')
            pdf.set_font(font_name, '', 9); pdf.ln()

    if pdf.get_y() + 10 > 260:
        pdf.add_page()
        draw_table_header()

    pdf.set_fill_color(230, 230, 230); pdf.set_font(font_name, b_style, 9)
    pdf.cell(15+45+10, 10, "小 計 (Sub Total)", border=1, align='C', fill=True)
    pdf.cell(12, 10, f"{sum_qty:,}", border=1, align='C', fill=True)
    
    if form_type == "기본 양식":
        pdf.cell(35, 10, "", border=1, fill=True)
        pdf.cell(35, 10, f"¥ {sum_a1:,}", border=1, align='R', fill=True)
        pdf.cell(38, 10, "", border=1, fill=True); pdf.ln()
    else:
        avg_rate = (sum_profit / sum_a2 * 100) if sum_a2 else 0
        pdf.set_font(font_name, b_style, 8)
        pdf.cell(18, 10, "", border=1, fill=True); pdf.cell(22, 10, f"¥ {sum_a1:,}", border=1, align='R', fill=True)
        pdf.cell(18, 10, "", border=1, fill=True); pdf.cell(22, 10, f"¥ {sum_a2:,}", border=1, align='R', fill=True)
        pdf.cell(15, 10, f"¥ {sum_profit:,}", border=1, align='R', fill=True)
        pdf.cell(13, 10, f"{avg_rate:.1f}%", border=1, align='C', fill=True); pdf.ln()

    svc_total = 0
    if service_items:
        if pdf.get_y() + (len(service_items) * 6) + 10 > 260:
             pdf.add_page()
             pdf.ln(2)
        else:
             pdf.ln(2)
             
        pdf.set_fill_color(255, 255, 224)
        pdf.cell(190, 6, " [ 追加費用 ] ", border=1, fill=True, new_x="LMARGIN", new_y="NEXT")
        for s in service_items:
            svc_total += s['금액']; pdf.cell(155, 6, s['항목'], border=1)
            pdf.cell(35, 6, f"¥ {s['금액']:,}", border=1, align='R', new_x="LMARGIN", new_y="NEXT")

    pdf.ln(5); pdf.set_font(font_name, b_style, 12)
    
    if pdf.get_y() + 30 > 270:
        pdf.add_page()
    
    pdf.multi_cell(0, 5, remarks, align='R')
    pdf.ln(2)

    if form_type == "기본 양식":
        final_total = sum_a1 + svc_total
        pdf.cell(120, 10, "", border=0); pdf.cell(35, 10, "総 合 計", border=1, align='C', fill=True)
        pdf.cell(35, 10, f"¥ {final_total:,}", border=1, align='R')
    else:
        t1_final = sum_a1 + svc_total; t2_final = sum_a2 + svc_total; total_profit = t2_final - t1_final
        pdf.set_font(font_name, '', 10)
        pdf.cell(82, 10, "総 合 計", border=1, align='C', fill=True)
        pdf.cell(40, 10, f"¥ {t1_final:,}", border=1, align='R')
        pdf.set_font(font_name, b_style, 10)
        pdf.cell(40, 10, f"¥ {t2_final:,}", border=1, align='R')
        pdf.cell(28, 10, f"(¥ {total_profit:,})", border=1, align='R')
        
    return bytes(pdf.output())

def create_quote_excel(final_data_list, service_items, quote_name, quote_date, form_type, price_labels, buyer_info, remarks):
    output = io.BytesIO()
    workbook = xlsxwriter.Workbook(output, {'in_memory': True})
    ws = workbook.add_worksheet("御見積書")
    
    drive_file_map = get_drive_file_map()

    # Formats
    fmt_title = workbook.add_format({'bold': True, 'font_size': 16, 'align': 'center', 'valign': 'vcenter'})
    fmt_header = workbook.add_format({'bold': True, 'bg_color': '#f0f0f0', 'border': 1, 'align': 'center', 'valign': 'vcenter'})
    fmt_text_wrap = workbook.add_format({'border': 1, 'valign': 'vcenter', 'text_wrap': True}) 
    fmt_text = workbook.add_format({'border': 1, 'valign': 'vcenter'})
    fmt_num = workbook.add_format({'border': 1, 'num_format': '¥ #,##0', 'valign': 'vcenter'})
    fmt_center = workbook.add_format({'border': 1, 'align': 'center', 'valign': 'vcenter'})

    ws.merge_range('A1:F1', '御 見 積 書', fmt_title)
    ws.write(1, 0, f"現場名: {quote_name}")
    ws.write(1, 4, f"日付: {quote_date}")
    ws.write(2, 0, f"ご担当者: {buyer_info.get('manager', '')}")
    ws.write(2, 4, f"TEL: {buyer_info.get('phone', '')}")

    headers = ["画像", "品名/規格", "単位", "数量"]
    if form_type == "기본 양식":
        headers.extend([price_labels[0], "金額", "備考"])
    else:
        headers.extend([price_labels[0], "金額(1)", price_labels[1], "金額(2)", "利益", "率(%)"])

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

        if form_type == "기본 양식":
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
        ws.write(row, 1, "[追加費用]", fmt_header)
        row += 1
        for s in service_items:
            ws.write(row, 1, s['항목'], fmt_text)
            price_col = 5 if form_type == "기본 양식" else 7
            ws.write(row, price_col, s['금액'], fmt_num)
            svc_total += s['금액']
            row += 1

    row += 1
    ws.write(row, 1, "総 合 計", fmt_header)
    final_sum = (total_a1 if form_type == "기본 양식" else total_a2) + svc_total
    col_idx = 5 if form_type == "기본 양식" else 7
    ws.write(row, col_idx, final_sum, fmt_num)

    row += 2
    ws.write(row, 1, "特約事項及び備考", fmt_header)
    row += 1
    ws.write(row, 1, remarks, fmt_text_wrap)

    workbook.close()
    
    for f in temp_files:
        try: 
            if os.path.exists(f):
                os.unlink(f)
        except: pass
        
    return output.getvalue()

def create_composition_pdf(set_cart, pipe_cart, final_data_list, db_products, db_sets, quote_name):
    drive_file_map = get_drive_file_map()
    pdf = PDF()
    pdf.set_auto_page_break(False)
    pdf.add_page()
    
    has_font = os.path.exists(FONT_REGULAR)
    has_bold = os.path.exists(FONT_BOLD)
    font_name = 'NotoSansJP' if has_font else 'Helvetica'
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

    pdf.set_font(font_name, b_style, 16)
    pdf.cell(0, 15, "資材構成明細書 (Material Composition Report)", align='C', new_x="LMARGIN", new_y="NEXT")
    pdf.set_font(font_name, '', 10)
    pdf.cell(0, 8, f"現場名: {quote_name}", align='R', new_x="LMARGIN", new_y="NEXT")
    pdf.ln(5)

    def check_page_break(h_needed):
        if pdf.get_y() + h_needed > 270:
            pdf.add_page()

    # 1. 부속 세트 구성 -> 付属セット構成
    pdf.set_fill_color(220, 220, 220)
    pdf.set_font(font_name, b_style, 12)
    pdf.cell(0, 10, "1. 付属セット構成 (Fitting Sets)", border=1, fill=True, new_x="LMARGIN", new_y="NEXT")
    
    pdf.set_font(font_name, '', 10)
    row_h = 35 
    header_h = 8
    
    col_w_img = 50
    col_w_name = 70
    col_w_type = 40
    col_w_qty = 30
    
    pdf.set_fill_color(240, 240, 240)
    pdf.cell(col_w_img, header_h, "IMG", border=1, align='C', fill=True) 
    pdf.cell(col_w_name, header_h, "セット名 (Set Name)", border=1, align='C', fill=True)
    pdf.cell(col_w_type, header_h, "区分", border=1, align='C', fill=True)
    pdf.cell(col_w_qty, header_h, "数量", border=1, align='C', fill=True, new_x="LMARGIN", new_y="NEXT")

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
        pdf.cell(col_w_img, row_h, "", border=1)
        if img_b64:
            try:
                img_data = img_b64.split(",", 1)[1]
                img_bytes = base64.b64decode(img_data)
                with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as tmp:
                    tmp.write(img_bytes)
                    tmp_path = tmp.name
                
                pdf.image(tmp_path, x=x+6.25, y=y+2.5, w=37.5, h=30)
                os.unlink(tmp_path)
            except: pass
            
        pdf.set_xy(x+col_w_img, y)
        pdf.cell(col_w_name, row_h, name, border=1, align='L')
        pdf.cell(col_w_type, row_h, stype, border=1, align='C')
        pdf.cell(col_w_qty, row_h, str(qty), border=1, align='C', new_x="LMARGIN", new_y="NEXT")
    
    pdf.ln(5)

    # 2. 배관 물량 -> 配管数量
    pdf.set_font(font_name, b_style, 12)
    pdf.set_fill_color(220, 220, 220)
    check_page_break(20)
    pdf.cell(0, 10, "2. 配管数量 (Pipe Quantities)", border=1, fill=True, new_x="LMARGIN", new_y="NEXT")
    
    pdf.set_font(font_name, '', 10)
    pdf.set_fill_color(240, 240, 240)
    pdf.cell(20, header_h, "IMG", border=1, align='C', fill=True)
    pdf.cell(100, header_h, "品名 (Product Name)", border=1, align='C', fill=True)
    pdf.cell(40, header_h, "総長さ(m)", border=1, align='C', fill=True)
    pdf.cell(30, header_h, "ロール数(EA)", border=1, align='C', fill=True, new_x="LMARGIN", new_y="NEXT")

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
                    tmp.write(img_bytes)
                    tmp_path = tmp.name
                pdf.image(tmp_path, x=x+2, y=y+2, w=11, h=11)
                if os.path.exists(tmp_path):
                    os.unlink(tmp_path)
            except: pass
            
        pdf.set_xy(x+20, y)
        pdf.cell(100, 15, f"{info['name']} ({info['spec']})", border=1, align='L')
        pdf.cell(40, 15, f"{info['len']} m", border=1, align='C')
        pdf.cell(30, 15, f"{rolls} ﾛｰﾙ", border=1, align='C', new_x="LMARGIN", new_y="NEXT")

    pdf.ln(5)

    # 3. 추가 자재 -> 追加資材
    if additional_items_list:
        pdf.set_font(font_name, b_style, 12)
        pdf.set_fill_color(220, 220, 220)
        check_page_break(20)
        pdf.cell(0, 10, "3. 追加資材 (Additional Components / Spares)", border=1, fill=True, new_x="LMARGIN", new_y="NEXT")
        
        pdf.set_font(font_name, '', 10)
        pdf.set_fill_color(240, 240, 240)
        pdf.cell(20, header_h, "IMG", border=1, align='C', fill=True)
        pdf.cell(130, header_h, "品名 / 規格 (Name/Spec)", border=1, align='C', fill=True)
        pdf.cell(40, header_h, "追加数量", border=1, align='C', fill=True, new_x="LMARGIN", new_y="NEXT")

        for item in additional_items_list:
            check_page_break(15)
            name = item['name']
            spec = item['spec'] if item['spec'] else '-'
            qty = item['qty']
            code = item.get('code')
            img_val = item.get('image')
            
            img_id = get_best_image_id(code, img_val, drive_file_map)
            img_b64 = download_image_by_id(img_id)

            x, y = pdf.get_x(), pdf.get_y()
            pdf.cell(20, 15, "", border=1)
            if img_b64:
                try:
                    img_data = img_b64.split(",", 1)[1]
                    img_bytes = base64.b64decode(img_data)
                    with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as tmp:
                        tmp.write(img_bytes)
                        tmp_path = tmp.name
                    pdf.image(tmp_path, x=x+2, y=y+2, w=11, h=11)
                    if os.path.exists(tmp_path):
                        os.unlink(tmp_path)
                except: pass
                
            pdf.set_xy(x+20, y)
            pdf.cell(130, 15, f"{name} ({spec})", border=1, align='L')
            pdf.cell(40, 15, f"{int(qty)} EA", border=1, align='C', new_x="LMARGIN", new_y="NEXT")
        
        pdf.ln(5)

    # 4. 전체 자재 산출 목록 -> 全体資材一覧
    pdf.set_font(font_name, b_style, 12)
    pdf.set_fill_color(220, 220, 220)
    check_page_break(20)
    idx_num = "4" if additional_items_list else "3"
    pdf.cell(0, 10, f"{idx_num}. 全体資材一覧 (Total Components)", border=1, fill=True, new_x="LMARGIN", new_y="NEXT")
    
    pdf.set_font(font_name, '', 10)
    pdf.set_fill_color(240, 240, 240)
    pdf.cell(20, header_h, "IMG", border=1, align='C', fill=True)
    pdf.cell(130, header_h, "品名 / 規格 (Name/Spec)", border=1, align='C', fill=True)
    pdf.cell(40, header_h, "総数量", border=1, align='C', fill=True, new_x="LMARGIN", new_y="NEXT")

    for item in final_data_list:
        try: qty = int(float(item.get("수량", 0)))
        except: qty = 0
        if qty == 0: continue

        check_page_break(15)
        name = item.get("품목", "")
        spec = item.get("규격", "-")
        code = item.get("코드", "")
        img_val = item.get("image_data")
        
        img_id = get_best_image_id(code, img_val, drive_file_map)
        img_b64 = download_image_by_id(img_id)

        x, y = pdf.get_x(), pdf.get_y()
        pdf.cell(20, 15, "", border=1)
        if img_b64:
            try:
                img_data = img_b64.split(",", 1)[1]
                img_bytes = base64.b64decode(img_data)
                with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as tmp:
                    tmp.write(img_bytes)
                    tmp_path = tmp.name
                pdf.image(tmp_path, x=x+2, y=y+2, w=11, h=11)
                if os.path.exists(tmp_path):
                    os.unlink(tmp_path)
            except: pass
            
        pdf.set_xy(x+20, y)
        pdf.cell(130, 15, f"{name} ({spec})", border=1, align='L')
        pdf.cell(40, 15, f"{int(qty)} EA", border=1, align='C', new_x="LMARGIN", new_y="NEXT")

    return bytes(pdf.output())

def create_composition_excel(set_cart, pipe_cart, final_data_list, db_products, db_sets, quote_name):
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

    ws1 = workbook.add_worksheet("付属セット")
    ws1.write(0, 0, "画像", fmt_header)
    ws1.write(0, 1, "セット名", fmt_header)
    ws1.write(0, 2, "区分", fmt_header)
    ws1.write(0, 3, "数量", fmt_header)
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

    ws2 = workbook.add_worksheet("配管数量")
    ws2.write(0, 0, "画像", fmt_header)
    ws2.write(0, 1, "品名", fmt_header)
    ws2.write(0, 2, "総長さ(m)", fmt_header)
    ws2.write(0, 3, "ロール数", fmt_header)
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
        ws_add = workbook.add_worksheet("追加資材")
        ws_add.write(0, 0, "画像", fmt_header)
        ws_add.write(0, 1, "品名", fmt_header)
        ws_add.write(0, 2, "規格", fmt_header)
        ws_add.write(0, 3, "追加数量", fmt_header)
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

    ws3 = workbook.add_worksheet("全体資材一覧")
    ws3.write(0, 0, "画像", fmt_header)
    ws3.write(0, 1, "品名", fmt_header)
    ws3.write(0, 2, "規格", fmt_header)
    ws3.write(0, 3, "総数量", fmt_header)
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
    with st.spinner("DB連携中..."): 
        st.session_state.db = load_data_from_sheet()

if "app_authenticated" not in st.session_state:
    st.session_state.app_authenticated = False
    st.session_state.failed_attempts = 0
    st.session_state.lockout_time = None

if st.session_state.lockout_time:
    if datetime.datetime.now() < st.session_state.lockout_time:
        remaining_time = (st.session_state.lockout_time - datetime.datetime.now()).seconds // 60
        st.error(f"🚫 セキュリティロック中です。{remaining_time + 1}分後に再度お試しください。")
        st.stop()
    else:
        st.session_state.failed_attempts = 0
        st.session_state.lockout_time = None

if not st.session_state.app_authenticated:
    st.markdown("<h2 style='text-align: center; margin-top: 100px;'>🔒 Looperget Pro Manager JP</h2>", unsafe_allow_html=True)
    col1, col2, col3 = st.columns([1, 1, 1])
    with col2:
        with st.container(border=True):
            pwd = st.text_input("プログラム接続パスワード", type="password", key="app_pwd")
            if st.button("接続", use_container_width=True):
                app_pwd_db = str(st.session_state.db.get("config", {}).get("app_pwd", "1234"))
                if pwd == app_pwd_db:
                    st.session_state.app_authenticated = True
                    st.session_state.failed_attempts = 0
                    st.rerun()
                else:
                    st.session_state.failed_attempts += 1
                    if st.session_state.failed_attempts >= 5:
                        st.session_state.lockout_time = datetime.datetime.now() + datetime.timedelta(minutes=30)
                        st.error("🚫 パスワードを5回間違えました。30分間接続がブロックされます。")
                        time.sleep(2)
                        st.rerun()
                    else:
                        st.error(f"❌ パスワードが違います。 ({st.session_state.failed_attempts}/5)")
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
if "buyer_info" not in st.session_state: st.session_state.buyer_info = {"manager": "", "phone": "", "addr": ""}
if "auth_admin" not in st.session_state: st.session_state.auth_admin = False
if "auth_price" not in st.session_state: st.session_state.auth_price = False
if "final_edit_df" not in st.session_state: st.session_state.final_edit_df = None
if "step3_ready" not in st.session_state: st.session_state.step3_ready = False

if "custom_prices" not in st.session_state: st.session_state.custom_prices = []

if "files_ready" not in st.session_state: st.session_state.files_ready = False
if "gen_pdf" not in st.session_state: st.session_state.gen_pdf = None
if "gen_excel" not in st.session_state: st.session_state.gen_excel = None
if "gen_comp_pdf" not in st.session_state: st.session_state.gen_comp_pdf = None
if "gen_comp_excel" not in st.session_state: st.session_state.gen_comp_excel = None

if "exchange_rate" not in st.session_state: st.session_state.exchange_rate = 10.0 # 기본 환율

if "ui_state" not in st.session_state:
    st.session_state.ui_state = {
        "form_type": "基本様式",
        "print_mode": "個別品目羅列 (既存)",
        "vat_mode": "税込 (基本)",
        "sel": ["消費者価格"]
    }

if "quote_remarks" not in st.session_state: 
    st.session_state.quote_remarks = "1. 見積有効期限: 見積日より15日以内\n2. 納期: 決済完了後、即時または7日以内"

st.title("💧 Looperget Pro Manager JP (Cloud)")

with st.sidebar:
    st.header("🗂️ 見積アーカイブ")
    q_name = st.text_input("現場名 (保存用)", value=st.session_state.current_quote_name)
    
    col_s1, col_s2, col_s3 = st.columns(3)
    with col_s1: btn_save_temp = st.button("💾 一時保存")
    with col_s2: btn_save_off = st.button("✅ 正式保存")
    with col_s3: btn_init = st.button("✨ 初期化")
    
    if btn_save_temp or btn_save_off:
        save_type = "正式" if btn_save_off else "一時"
        if not q_name:
            st.error("現場名を入力してください。")
        else:
            timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            current_custom_prices = st.session_state.final_edit_df.to_dict('records') if st.session_state.final_edit_df is not None else []
            
            form_type_val = st.session_state.get("step3_form_type", st.session_state.ui_state.get("form_type", "基本様式"))
            print_mode_val = st.session_state.get("step3_print_mode", st.session_state.ui_state.get("print_mode", "個別品目羅列 (既存)"))
            vat_mode_val = st.session_state.get("step3_vat_mode", st.session_state.ui_state.get("vat_mode", "税込 (基本)"))
            
            if form_type_val == "基本様式":
                sel_val = st.session_state.get("step3_sel_basic", st.session_state.ui_state.get("sel", ["消費者価格"]))
            else:
                sel_val = st.session_state.get("step3_sel_profit", st.session_state.ui_state.get("sel", ["消費者価格"]))

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
                st.success(f"Googleスプレッドシートに '{save_type}' として保存しました。")
            else:
                st.error("保存失敗 (ネットワークエラー)")

    if btn_init:
        st.session_state.quote_items = {}; st.session_state.services = []; st.session_state.pipe_cart = []; st.session_state.set_cart = []; st.session_state.quote_step = 1
        st.session_state.current_quote_name = ""; st.session_state.buyer_info = {"manager": "", "phone": "", "addr": ""}; st.session_state.step3_ready=False; st.session_state.files_ready = False
        st.session_state.quote_remarks = "1. 見積有効期限: 見積日より15日以内\n2. 納期: 決済完了後、即時または7日以内"
        st.session_state.custom_prices = []
        st.session_state.ui_state = {
            "form_type": "基本様式",
            "print_mode": "個別品目羅列 (既存)",
            "vat_mode": "税込 (基本)",
            "sel": ["消費者価格"]
        }
        st.session_state.last_sel = []
        for k in ["step3_form_type", "step3_print_mode", "step3_vat_mode", "step3_sel_basic", "step3_sel_profit"]:
            if k in st.session_state:
                del st.session_state[k]
        st.rerun()
        
    st.divider()
    
    jp_quotes_history = st.session_state.db.get("jp_quotes", [])
    if jp_quotes_history:
        df_jp_hist = pd.DataFrame(jp_quotes_history).iloc[::-1]
        
        def format_quote_label(i):
            r = df_jp_hist.iloc[i]
            d_json_str = str(r.get("데이터JSON", "{}"))
            try: 
                d_json = json.loads(d_json_str)
                s_type = d_json.get("save_type", "一時")
            except: s_type = "一時"
            return f"[{r.get('날짜','')}] [{s_type}] {r.get('현장명','')} ({r.get('담당자','')})"
            
        sel_idx = st.selectbox("読み込み (Google Sheets)", range(len(df_jp_hist)), format_func=format_quote_label)
        
        c_l1, c_l2, c_l3 = st.columns(3)
        with c_l1: btn_load = st.button("📂 読込")
        with c_l2: btn_copy = st.button("📝 複製/修正")
        with c_l3: btn_del = st.button("🗑️ 削除")
        
        if btn_load or btn_copy:
            try:
                target_row = df_jp_hist.iloc[sel_idx]
                json_str = target_row.get("데이터JSON", "{}")
                d = json.loads(json_str)
                
                st.session_state.quote_items = d.get("items", {})
                st.session_state.services = d.get("services", [])
                st.session_state.pipe_cart = d.get("pipe_cart", [])
                st.session_state.set_cart = d.get("set_cart", [])
                st.session_state.quote_step = d.get("step", 2)
                st.session_state.buyer_info = d.get("buyer", {"manager": "", "phone": "", "addr": ""})
                st.session_state.quote_remarks = d.get("remarks", "1. 見積有効期限: 見積日より15日以内\n2. 納期: 決済完了後、即時または7日以内")
                st.session_state.custom_prices = d.get("custom_prices", [])
                
                st.session_state.ui_state = d.get("ui_state", {
                    "form_type": "基本様式",
                    "print_mode": "個別品目羅列 (既存)",
                    "vat_mode": "税込 (基本)",
                    "sel": ["消費者価格"]
                })
                st.session_state.last_sel = st.session_state.ui_state.get("sel", ["消費者価格"])
                
                for k in ["step3_form_type", "step3_print_mode", "step3_vat_mode", "step3_sel_basic", "step3_sel_profit"]:
                    if k in st.session_state:
                        del st.session_state[k]

                if btn_copy:
                    st.session_state.quote_step = 1
                    st.session_state.current_quote_name = ""
                    st.success("データをコピーして新しい見積を作成します！")
                else:
                    st.session_state.current_quote_name = target_row.get("현장명", "")
                    st.success(f"'{st.session_state.current_quote_name}' 読み込み完了！")
                    
                st.session_state.step3_ready = False
                st.session_state.files_ready = False
                time.sleep(0.5)
                st.rerun()
            except Exception as e:
                st.error(f"読み込み失敗: {e}")
                
        if btn_del:
            try:
                real_idx = len(jp_quotes_history) - sel_idx - 1
                jp_quotes_history.pop(real_idx)
                sh = gc.open(SHEET_NAME)
                ws_jp = sh.worksheet("Quotes_JP")
                ws_jp.clear()
                if jp_quotes_history:
                    header = list(jp_quotes_history[0].keys())
                    rows = [header] + [[str(r.get(k, "")) for k in header] for r in jp_quotes_history]
                    ws_jp.update(rows)
                else:
                    ws_jp.update([['날짜', '현장명', '담당자', '총액', '데이터JSON']])
                st.session_state.db = load_data_from_sheet()
                st.success("削除されました。")
                time.sleep(0.5)
                st.rerun()
            except Exception as e:
                st.error(f"削除失敗: {e}")
    else:
        st.info("保存された見積がありません。")
        
    st.divider()
    mode = st.radio("モード", ["見積作成", "管理者モード", "🇯🇵 日本輸出分析"], key="main_sidebar_mode")

if mode == "管理者モード":
    st.header("🛠 管理者モード")
    if st.button("🔄 データの更新 (Google Sheets)"): st.session_state.db = load_data_from_sheet(); st.success("完了"); st.rerun()
    if not st.session_state.auth_admin:
        pw = st.text_input("管理者パスワード", type="password")
        if st.button("ログイン"):
            admin_pwd_db = str(st.session_state.db.get("config", {}).get("admin_pwd", "1234"))
            if pw == admin_pwd_db: st.session_state.auth_admin = True; st.rerun()
            else: st.error("パスワードが違います")
    else:
        if st.button("ログアウト"): st.session_state.auth_admin = False; st.rerun()
        t1, t2, t3 = st.tabs(["単価・為替管理", "セット管理", "設定"])
        
        with t1:
            st.subheader("💰 単価および為替レート設定")
            
            # 1. 환율 설정
            current_rate = st.session_state.exchange_rate
            new_rate = st.number_input("適用為替レート (KRW / 1 JPY)", value=current_rate, step=0.1, help="1円あたりの韓国ウォン価格 (例: 100円=950ウォンなら 9.5)")
            if new_rate != st.session_state.exchange_rate:
                st.session_state.exchange_rate = new_rate
                st.success(f"レートを {new_rate} に設定しました (1 JPY = {new_rate} KRW)")
            
            st.divider()
            
            # 2. 일괄 업데이트 (DB 저장)
            st.markdown("##### ⚡️ 単価一括更新 (DB保存)")
            st.info("現在のレートとマージン率に基づいて、全ての製品の日本販売価格を計算し、DBに上書きします。")
            
            c_marg1, c_marg2 = st.columns(2)
            with c_marg1: margin_d = st.number_input("代理店マージン (%)", value=20.0, step=1.0)
            with c_marg2: margin_c = st.number_input("消費者マージン (%)", value=30.0, step=1.0)
            
            if st.button("🚨 レートとマージンを適用してDBを更新する", type="primary"):
                products = st.session_state.db["products"]
                updated_count = 0
                for p in products:
                    krw_cost = p.get("price_buy", 0) # price_buy_jp_krw mapped to price_buy
                    if krw_cost and float(krw_cost) > 0:
                        base_jp = float(krw_cost) / new_rate
                        p["price_d1"] = int(base_jp * (1 + margin_d/100))
                        p["price_cons"] = int(base_jp * (1 + margin_c/100))
                        updated_count += 1
                
                if updated_count > 0:
                    save_products_to_sheet(products)
                    st.session_state.db = load_data_from_sheet()
                    st.success(f"{updated_count}件の製品単価を更新しました！")
                else:
                    st.warning("更新対象の製品がありません (price_buy_jp_krw データを確認してください)")

            st.markdown("---")
            st.markdown("##### 📋 製品単価リスト (KRW → JPY 換算プレビュー)")
            
            products = st.session_state.db["products"]
            rows = []
            for p in products:
                krw_cost = p.get("price_buy", 0)
                jpy_cost_calc = int(float(krw_cost) / new_rate) if new_rate and krw_cost else 0
                rows.append({
                    "Code": p.get("code"),
                    "Name": p.get("name"),
                    "購入単価(KRW)": krw_cost,
                    "購入換算(JPY)": jpy_cost_calc,
                    "代理店1(JPY)": p.get("price_d1", 0),
                    "消費者(JPY)": p.get("price_cons", 0)
                })
            st.dataframe(pd.DataFrame(rows), width="stretch")

            st.divider()
            st.markdown("##### 🔄 ドライブ画像一括同期化")
            with st.expander("Googleドライブフォルダの画像と自動リンクする", expanded=False):
                st.info("💡 使い方: 画像ファイル名を '品目コード.jpg' (例: 00200.jpg)で保存し、Googleドライブの 'Looperget_Images' フォルダにアップロードしてください。")
                if st.button("🔄 ドライブ画像自動リンク実行", key="btn_sync_images"):
                    with st.spinner("ドライブフォルダを検索中..."):
                        get_drive_file_map.clear() 
                        file_map = get_drive_file_map() 
                        if not file_map:
                            st.warning("フォルダが空、または見つかりません。")
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
                                st.success(f"✅ 計 {updated_count}件の製品画像をリンクしました！")
                                st.session_state.db = load_data_from_sheet() 
                            else:
                                st.warning("一致する画像がありません。(ファイル名が品目コードと同じか確認してください)")

        with t2:
            st.subheader("📦 セット管理")
            ppt_data = get_admin_ppt_content()
            if ppt_data:
                st.download_button(label="📥 セット構成一覧表(PPT) ダウンロード", data=ppt_data, file_name="Set_Composition_Master.pptx", mime="application/vnd.openxmlformats-officedocument.presentationml.presentation", use_container_width=True)
            else:
                st.warning("⚠️ Googleドライブ 'Looperget_Admin' フォルダに 'Set_Composition_Master.pptx' ファイルがありません。")
            st.divider()
            cat = st.selectbox("分類", ["주배관세트", "가지관세트", "기타자재"])
            cset = st.session_state.db["sets"].get(cat, {})
            if cset:
                sl = [{"セット名": k, "部品数": len(v.get("recipe", {}))} for k,v in cset.items()]
                st.dataframe(pd.DataFrame(sl), width="stretch", on_select="rerun", selection_mode="multi-row", key="set_table")
                sel_rows = st.session_state.set_table.get("selection", {}).get("rows", [])
                if sel_rows:
                    if len(sel_rows) == 1:
                        tg = sl[sel_rows[0]]["セット名"]
                        st.markdown(f"#### 🔧 セット管理: {tg}")
                        col_edit, col_img = st.columns([1, 1])
                        with col_edit:
                            if st.button(f"✏️ '{tg}' 構成品を修正する", use_container_width=True):
                                st.session_state.temp_set_recipe = cset[tg].get("recipe", {}).copy()
                                st.session_state.target_set_edit = tg
                                st.session_state.set_manage_mode = "수정" 
                                st.rerun()
                        with col_img:
                            with st.expander("🖼️ セット画像管理", expanded=True):
                                set_folder_id = get_or_create_set_drive_folder()
                                current_set_data = st.session_state.db["sets"][cat][tg]
                                current_img_id = current_set_data.get("image", "")
                                if current_img_id:
                                    st.image(get_image_from_drive(current_img_id), caption="現在登録されている画像", use_container_width=True)
                                    if st.button("🗑️ 画像削除", key=f"del_img_{tg}"):
                                        st.session_state.db["sets"][cat][tg]["image"] = ""
                                        save_sets_to_sheet(st.session_state.db["sets"])
                                        st.success("画像が削除されました。")
                                        st.rerun()
                                else:
                                    st.info("登録された画像がありません。")
                                set_img_file = st.file_uploader("画像アップロード/変更", type=["png", "jpg", "jpeg"], key=f"uploader_{tg}")
                                if set_img_file:
                                    if st.button("💾 画像保存", key=f"save_img_{tg}"):
                                        with st.spinner("画像アップロード中..."):
                                            file_ext = set_img_file.name.split('.')[-1]
                                            new_filename = f"{tg}_image.{file_ext}"
                                            new_img_id = upload_set_image_to_drive(set_img_file, new_filename)
                                            if new_img_id:
                                                st.session_state.db["sets"][cat][tg]["image"] = new_img_id
                                                save_sets_to_sheet(st.session_state.db["sets"])
                                                st.success("画像が登録されました！")
                                                time.sleep(1)
                                                st.rerun()
                    else:
                        st.caption("💡 修正または画像管理を行うには1つだけ選択してください。")
                    st.markdown("---")
                    with st.expander(f"🗑️ 選択された {len(sel_rows)}個のセットを一括削除", expanded=True):
                        st.warning(f"選択した {len(sel_rows)}個のセットを本当に削除しますか？")
                        del_pw = st.text_input("管理者パスワード確認", type="password", key="bulk_del_pw")
                        if st.button("🚫 一括削除実行", type="primary"):
                            admin_pwd_db = str(st.session_state.db.get("config", {}).get("admin_pwd", "1234"))
                            if del_pw == admin_pwd_db:
                                del_count = 0
                                target_names = [sl[i]["セット名"] for i in sel_rows]
                                for name in target_names:
                                    if name in st.session_state.db["sets"][cat]:
                                        del st.session_state.db["sets"][cat][name]
                                        del_count += 1
                                save_sets_to_sheet(st.session_state.db["sets"])
                                st.success(f"{del_count}個のセットが削除されました。")
                                time.sleep(1)
                                st.rerun()
                            else:
                                st.error("パスワードが一致しません。")
            st.divider()
            st.markdown("##### 🔄 セット画像一括同期 (手動アップロード後)")
            with st.expander("📂 ドライブにアップしたファイルとセットを自動リンク", expanded=False):
                st.info(f"💡 1. Googleドライブの '{DRIVE_FOLDER_NAME}' フォルダに画像を手動でアップロードします。\n2. ファイル名は必ず 'セット名' と同じにしてください。")
                if st.button("🔄 ドライブセット画像自動同期", key="btn_sync_set_images"):
                    with st.spinner("ドライブフォルダを検索中..."):
                        file_map = get_drive_file_map()
                        if not file_map:
                            st.warning("フォルダが見つからないか空です。")
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
                                st.success(f"✅ 計 {updated_count}個のセット画像をリンクしました！")
                                st.session_state.db = load_data_from_sheet()
                            else:
                                st.warning("一致する画像がありません。")

        with t3: 
            st.markdown("##### ⚙️ パスワード設定")
            app_pwd_input = st.text_input("アプリ接続パスワード", value=st.session_state.db.get("config", {}).get("app_pwd", "1234"), key="cfg_app")
            admin_pwd_input = st.text_input("管理者/原価照会パスワード", value=st.session_state.db.get("config", {}).get("admin_pwd", "1234"), key="cfg_admin")
            
            if st.button("💾 パスワード変更保存"):
                try:
                    sh = gc.open(SHEET_NAME)
                    ws_config = sh.worksheet("Config")
                    ws_config.clear()
                    ws_config.update([["항목", "비밀번호"], ["app_pwd", app_pwd_input], ["admin_pwd", admin_pwd_input]])
                    st.session_state.db["config"]["app_pwd"] = app_pwd_input
                    st.session_state.db["config"]["admin_pwd"] = admin_pwd_input
                    st.success("パスワードが正常に変更されました！")
                except Exception as e:
                    st.error(f"パスワード保存失敗: {e}")

elif mode == "🇯🇵 日本輸出分析":
    st.header("🇯🇵 日本輸出見積 収益性分析")
    st.caption("日本現地で保存された見積データを読み込み、予想収益を分析します。")
    
    if st.button("🔄 データ更新"):
        st.session_state.db = load_data_from_sheet()
        st.rerun()

    jp_quotes = st.session_state.db.get("jp_quotes", [])
    
    if not jp_quotes:
        st.warning("保存された見積データがありません。 (Google Sheet: 'Quotes_JP')")
    else:
        df_quotes = pd.DataFrame(jp_quotes)
        if "현장명" in df_quotes.columns:
            selected_quote_idx = st.selectbox(
                "分析する見積を選択してください", 
                range(len(df_quotes)), 
                format_func=lambda i: f"[{df_quotes.iloc[i].get('날짜','')}] {df_quotes.iloc[i].get('현장명','')}"
            )
            
            if selected_quote_idx is not None:
                target_quote = df_quotes.iloc[selected_quote_idx]
                items_json_str = str(target_quote.get("데이터JSON", "{}"))
                try:
                    full_dict = json.loads(items_json_str)
                    items_dict = full_dict.get("items", {})
                except:
                    items_dict = {}
                    st.error("データ形式が正しくありません。")

                if items_dict:
                    st.divider()
                    st.subheader(f"📊 分析結果: {target_quote.get('현장명')}")
                    
                    analysis_rows = []
                    total_revenue = 0 
                    total_cost = 0    
                    
                    db_map = {str(p.get("code")).strip(): p for p in st.session_state.db["products"]}
                    rate = st.session_state.exchange_rate

                    for code, qty in items_dict.items():
                        qty = int(qty)
                        prod = db_map.get(str(code).strip())
                        
                        if prod:
                            name = prod.get("name", "")
                            spec = prod.get("spec", "")
                            # 공급가는 JPY
                            price_supply = int(prod.get("price_supply_jp", 0) or 0)
                            # 매입가는 원화(KRW)이므로 환율 적용 후 정수화
                            krw_buy = int(prod.get("price_buy", 0) or 0)
                            price_buy = int(krw_buy / rate) if rate else 0
                            
                            revenue = price_supply * qty
                            cost = price_buy * qty
                            profit = revenue - cost
                            
                            total_revenue += revenue
                            total_cost += cost
                            
                            analysis_rows.append({
                                "品目コード": code,
                                "品名": name,
                                "規格": spec,
                                "数量": qty,
                                "供給単価(¥)": price_supply,
                                "購入単価(¥)": price_buy,
                                "予想売上(¥)": revenue,
                                "予想原価(¥)": cost,
                                "予想利益(¥)": profit
                            })
                        else:
                            analysis_rows.append({
                                "品目コード": code,
                                "品名": "未登録品目",
                                "規格": "-",
                                "数量": qty,
                                "供給単価(¥)": 0,
                                "購入単価(¥)": 0,
                                "予想売上(¥)": 0,
                                "予想原価(¥)": 0,
                                "予想利益(¥)": 0
                            })

                    total_profit = total_revenue - total_cost
                    profit_margin = (total_profit / total_revenue * 100) if total_revenue > 0 else 0
                    
                    m1, m2, m3, m4 = st.columns(4)
                    m1.metric("総売上 (供給価)", f"¥ {total_revenue:,}")
                    m2.metric("総原価 (購入価)", f"¥ {total_cost:,}")
                    m3.metric("予想利益", f"¥ {total_profit:,}", delta_color="normal")
                    m4.metric("利益率", f"{profit_margin:.1f} %")
                    
                    st.markdown("---")
                    st.write("###### 詳細内訳")
                    st.dataframe(pd.DataFrame(analysis_rows), width="stretch", hide_index=True)
                    
                else:
                    st.info("見積に含まれた品目がありません。")
        else:
            st.error("データ形式が正しくありません。(Quotes_JP シート確認必要)")

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
        with st.expander("1. メイン配管および分岐配管セット選択", True):
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
            with mt1: inp_m_50 = render_inputs_with_key(grouped.get("50mm", {}), "m50")
            with mt2: inp_m_40 = render_inputs_with_key(grouped.get("40mm", {}), "m40")
            with mt3: inp_m_etc = render_inputs_with_key(grouped.get("기타", {}), "metc")
            with mt4: inp_m_all = render_inputs_with_key(m_sets, "mall") 
            
            st.write("")
            if st.button("➕ 入力した数量をセットリストに追加"):
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
                        st.session_state.set_cart.append({"name": set_name, "qty": qty, "type": "メイン配管"})
                        added_count += 1
                if added_count > 0:
                    st.success(f"{added_count}項目をリストに追加しました。")
                else:
                    st.warning("数量を入力してください。")
        with st.expander("2. 分岐配管およびその他セット"):
            c1, c2 = st.tabs(["分岐配管", "その他資材"])
            with c1: inp_b = render_inputs_with_key(sets.get("가지관세트", {}), "b_set")
            with c2: inp_e = render_inputs_with_key(sets.get("기타자재", {}), "e_set")
            if st.button("➕ 分岐配管/その他リスト追加"):
                all_inputs = {**inp_b, **inp_e}
                added_count = 0
                for set_name, qty in all_inputs.items():
                    if qty > 0:
                        st.session_state.set_cart.append({"name": set_name, "qty": qty, "type": "その他"})
                        added_count += 1
                if added_count > 0: st.success("追加しました")
        if st.session_state.set_cart:
            st.info("📋 選択されたセットリスト (合算予定)")
            st.dataframe(pd.DataFrame(st.session_state.set_cart), width="stretch", hide_index=True)
            if st.button("🗑️ セットリストを空にする"):
                st.session_state.set_cart = []
                st.rerun()
        st.divider()
        st.markdown("#### 📏 配管数量算出 (カート)")
        all_products = st.session_state.db["products"]
        
        pipe_type_sel = st.radio("配管区分", ["주배관", "가지관"], horizontal=True, key="pipe_type_radio")
        filtered_pipes = [p for p in all_products if p["category"] == pipe_type_sel]
        c1, c2, c3 = st.columns([3, 2, 1])
        with c1: sel_pipe = st.selectbox(f"配管 選択", filtered_pipes, format_func=format_prod_label, key="pipe_sel")
        with c2: len_pipe = st.number_input("長さ(m)", min_value=1, step=1, format="%d", key="pipe_len")
        with c3:
            st.write(""); st.write("")
            if st.button("➕ リスト追加"):
                if sel_pipe: st.session_state.pipe_cart.append({"type": pipe_type_sel, "name": sel_pipe['name'], "spec": sel_pipe.get("spec", ""), "code": sel_pipe.get("code", ""), "len": len_pipe})
        if st.session_state.pipe_cart:
            st.caption("📋 入力された配管リスト")
            st.dataframe(pd.DataFrame(st.session_state.pipe_cart), width="stretch", hide_index=True)
            if st.button("🗑️ 空にする"): st.session_state.pipe_cart = []; st.rerun()
        st.divider()
        if st.button("計算する (STEP 2)"):
            if not st.session_state.current_quote_name: st.error("現場名を入力してください。")
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
        st.subheader("STEP 2. 内容検討")
        if st.button("⬅️ STEP 1 (数量修正) に戻る"):
            st.session_state.quote_step = 1
            st.rerun()
        view_opts = ["消費者価格"]
        if st.session_state.auth_price: view_opts += ["購入価格", "総販1", "総販2", "代理店1", "代理店2", "現場単価"]
        c_lock, c_view = st.columns([1, 2])
        with c_lock:
            if not st.session_state.auth_price:
                pw = st.text_input("原価照会パスワード", type="password")
                if st.button("解除"):
                    admin_pwd_db = str(st.session_state.db.get("config", {}).get("admin_pwd", "1234"))
                    if pw == admin_pwd_db: st.session_state.auth_price = True; st.rerun()
                    else: st.error("エラー")
            else: st.success("🔓 原価照会可能")
        
        with c_view: view = st.radio("単価表示", view_opts, horizontal=True, key="step2_price_view")
        
        key_map = {
            "購入価格":("price_buy","購入"), 
            "総販1":("price_d1","総販1"), "総販2":("price_d2","総販2"), 
            "代理店1":("price_agy1","代理店1"), "代理店2":("price_agy2","代理店2"),
            "現場単価":("price_site", "現場")
        }
        
        rows = []
        pdb = {}
        for p in st.session_state.db["products"]:
            pdb[p["name"]] = p
            if p.get("code"): pdb[str(p["code"])] = p
        
        rate = st.session_state.exchange_rate
            
        for n, q in st.session_state.quote_items.items():
            inf = pdb.get(str(n), {})
            if not inf: continue
            
            cpr = int(inf.get("price_cons", 0))
            row = {"品名": inf.get("name", n), "規格": inf.get("spec", ""), "数量": q, "消費者価格": cpr, "合計": cpr*q}
            
            if view != "消費者価格":
                k, l = key_map[view]
                # 한국 매입가는 JPY로 환산, 나머지는 DB에 저장된 JPY 값 사용
                if view == "購入価格":
                    krw = inf.get(k, 0)
                    pr = int(krw / rate) if rate else 0
                else:
                    pr = int(inf.get(k, 0))
                    
                row[f"{l}単価"] = pr; row[f"{l}合計"] = pr*q
                row["利益"] = row["合計"] - row[f"{l}合計"]
                row["率(%)"] = (row["利益"]/row["合計"]*100) if row["合計"] else 0
            rows.append(row)
        
        disp = ["品名", "規格", "数量"]
        if view == "消費者価格": disp += ["消費者価格", "合計"]
        else: 
            l = key_map[view][1]
            disp += [f"{l}単価", f"{l}合計", "消費者価格", "合計", "利益", "率(%)"]
            
        if rows:
            df = pd.DataFrame(rows)
        else:
            df = pd.DataFrame(columns=disp)
            
        st.dataframe(df[disp], width="stretch", hide_index=True)
        st.divider()
        col_add_part, col_add_cost = st.columns([1, 1])
        with col_add_part:
            st.markdown("##### ➕ 部品追加")
            with st.container(border=True):
                all_products = st.session_state.db["products"]
                ap_obj = st.selectbox("品目選択", all_products, format_func=format_prod_label, key="step2_add_part")
                c_qty, c_btn = st.columns([2, 1])
                with c_qty: aq = st.number_input("数量", 1, key="step2_add_qty")
                with c_btn:
                    st.write("")
                    if st.button("追加", use_container_width=True): st.session_state.quote_items[str(ap_obj['code'])] = st.session_state.quote_items.get(str(ap_obj['code']), 0) + aq; st.rerun()
        with col_add_cost:
            st.markdown("##### 💰 費用追加")
            with st.container(border=True):
                c_type, c_amt = st.columns([1, 1])
                with c_type: stype = st.selectbox("項目", ["配送費", "人件費", "その他"], key="step2_cost_type")
                with c_amt: sp = st.number_input("金額(¥)", 0, step=1000, key="step2_cost_amt")
                sn = stype
                if stype == "その他": sn = st.text_input("内容入力", key="step2_cost_desc")
                if st.button("費用リストに追加", use_container_width=True): st.session_state.services.append({"항목": sn, "금액": int(sp)}); st.rerun()
        if st.session_state.services:
            st.caption("追加された費用リスト"); st.table(st.session_state.services)
        st.divider()
        if st.button("最終確定 (STEP 3)", type="primary", use_container_width=True): 
            st.session_state.quote_step = 3
            st.session_state.step3_ready = False
            st.session_state.files_ready = False
            st.rerun()

    elif st.session_state.quote_step == 3:
        st.header("🏁 最終見積")
        if not st.session_state.current_quote_name: st.warning("現場名(保存用)を確認してください！")
        st.markdown("##### 🖨️ 出力オプション")
        c_date, c_opt1, c_opt2 = st.columns([1, 1, 1])
        
        with c_date: 
            q_date = st.date_input("見積日", datetime.datetime.now())
            
        with c_opt1: 
            idx_form = 0 if st.session_state.ui_state.get("form_type", "基本様式") == "基本様式" else 1
            form_type = st.radio("様式", ["基本様式", "利益分析様式"], index=idx_form, key="step3_form_type")
            
            idx_print = 0 if st.session_state.ui_state.get("print_mode", "個別品目羅列 (既存)") == "個別品目羅列 (既存)" else 1
            print_mode = st.radio("出力形態", ["個別品目羅列 (既存)", "セット単位まとめ (新規)"], index=idx_print, key="step3_print_mode")
            
            idx_vat = 0 if st.session_state.ui_state.get("vat_mode", "税込 (基本)") == "税込 (基本)" else 1
            vat_mode = st.radio("消費税", ["税込 (基本)", "税抜 (別)"], index=idx_vat, key="step3_vat_mode")
            
        with c_opt2:
            basic_opts = ["消費者価格", "現場単価"]
            admin_opts = ["購入価格", "総販1", "総販2", "代理店1", "代理店2"]
            opts = basic_opts + (admin_opts if st.session_state.auth_price else [])
            
            if "利益" in form_type and not st.session_state.auth_price:
                st.warning("🔒 原価情報を表示するにはパスワードを入力してください。")
                c_pw, c_btn = st.columns([2,1])
                with c_pw: input_pw = st.text_input("パスワード", type="password", key="step3_pw")
                with c_btn: 
                    if st.button("解除", key="step3_btn"):
                        admin_pwd_db = str(st.session_state.db.get("config", {}).get("admin_pwd", "1234"))
                        if input_pw == admin_pwd_db: st.session_state.auth_price = True; st.rerun()
                        else: st.error("不一致")
                st.stop()
                
            saved_sel = st.session_state.ui_state.get("sel", ["消費者価格"])
            valid_sel = [s for s in saved_sel if s in opts]
            if not valid_sel: valid_sel = ["消費者価格"]

            if "基本" in form_type: 
                sel = st.multiselect("出力単価 (1つ選択)", opts, default=valid_sel[:1], max_selections=1, key="step3_sel_basic")
            else: 
                sel = st.multiselect("比較単価 (2つ選択)", opts, default=valid_sel[:2], max_selections=2, key="step3_sel_profit")

        st.session_state.ui_state["form_type"] = form_type
        st.session_state.ui_state["print_mode"] = print_mode
        st.session_state.ui_state["vat_mode"] = vat_mode
        st.session_state.ui_state["sel"] = sel

        if "基本" in form_type and len(sel) != 1: st.warning("出力する単価を1つ選択してください。"); st.stop()
        if "利益" in form_type and len(sel) < 2: st.warning("比較する単価を2つ選択してください。"); st.stop()

        price_rank = {"購入価格": 0, "総販1": 1, "総販2": 2, "代理店1": 3, "代理店2": 4, "現場単価": 5, "消費者価格": 6}
        if sel: sel = sorted(sel, key=lambda x: price_rank.get(x, 7))
        pkey = {
            "購入価格":"price_buy", "総販1":"price_d1", "総販2":"price_d2", 
            "代理店1":"price_agy1", "代理店2":"price_agy2",
            "消費者価格":"price_cons", "現場単価":"price_site"
        }
        
        if "last_sel" not in st.session_state: st.session_state.last_sel = []
        
        selectors_changed = (st.session_state.last_sel != sel)
        
        cp_map = {}
        if st.session_state.get("custom_prices"):
            for cp in st.session_state.custom_prices:
                k = str(cp.get("코드", "")).strip().zfill(5) if str(cp.get("코드", "")).strip() else str(cp.get("품목", "")).strip()
                cp_map[k] = cp

        rate = st.session_state.exchange_rate

        if not st.session_state.step3_ready or selectors_changed:
            pdb = {}
            for p in st.session_state.db["products"]:
                pdb[p["name"]] = p
                if p.get("code"): pdb[str(p["code"])] = p
            
            pk = [pkey[l] for l in sel] if sel else ["price_cons"]
            
            if not st.session_state.step3_ready:
                fdata = []
                processed_keys = set()
                
                for n, q in st.session_state.quote_items.items():
                    inf = pdb.get(str(n), {})
                    if not inf: continue
                    
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
                    
                    # 환율 반영 로직 (매입가만 환율 계산, 나머지는 DB 값)
                    def get_price(price_key, item_inf):
                        if price_key == "price_buy":
                            return int(item_inf.get(price_key, 0) / rate) if rate else 0
                        return int(item_inf.get(price_key, 0))

                    d["price_1"] = get_price(pk[0], inf)
                    if len(pk)>1: d["price_2"] = get_price(pk[1], inf)
                    else: d["price_2"] = 0
                    
                    if code_key in cp_map:
                        d["수량"] = int(cp_map[code_key].get("수량", d["수량"]))
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
            
            elif selectors_changed and st.session_state.final_edit_df is not None and not st.session_state.final_edit_df.empty:
                def update_prices_in_row(row):
                    code = str(row.get("코드", "")).strip().zfill(5)
                    name = str(row.get("품목", ""))
                    item = pdb.get(code)
                    if not item: item = pdb.get(name)
                    
                    if item:
                        def get_price(price_key, item_inf):
                            if price_key == "price_buy":
                                return int(item_inf.get(price_key, 0) / rate) if rate else 0
                            return int(item_inf.get(price_key, 0))
                            
                        p1 = get_price(pk[0], item)
                        p2 = get_price(pk[1], item) if len(pk) > 1 else 0
                        return pd.Series([p1, p2])
                    else:
                        return pd.Series([int(row.get("price_1", 0)), int(row.get("price_2", 0))])

                new_prices = st.session_state.final_edit_df.apply(update_prices_in_row, axis=1)
                st.session_state.final_edit_df["price_1"] = new_prices[0]
                st.session_state.final_edit_df["price_2"] = new_prices[1]

            st.session_state.last_sel = sel
            st.session_state.files_ready = False 

        st.markdown("---")
        
        pk = [pkey[l] for l in sel] if sel else ["price_cons"]
        disp_cols = ["품목", "규격", "코드", "단위", "수량", "price_1"]
        if len(pk) > 1: disp_cols.append("price_2")
        
        for c in disp_cols:
            if c not in st.session_state.final_edit_df.columns:
                st.session_state.final_edit_df[c] = 0 if "price" in c or "수량" in c else ""

        def on_data_change():
            st.session_state.files_ready = False

        with st.expander("➕ 手動品目追加 (DB未登録品目)", expanded=False):
            c1, c2, c3, c4, c5 = st.columns([3, 2, 1, 1, 2])
            m_name = c1.text_input("品名 (必須)", key="m_name")
            m_spec = c2.text_input("規格", key="m_spec")
            m_unit = c3.text_input("単位", "EA", key="m_unit")
            m_qty = c4.number_input("数量", 1, key="m_qty")
            m_price = c5.number_input("単価(¥)", 0, key="m_price")
            
            if st.button("リストに追加", key="btn_add_manual"):
                if m_name:
                    new_row = {
                        "품목": m_name, 
                        "규격": m_spec, 
                        "코드": "", 
                        "단위": m_unit, 
                        "수량": int(m_qty), 
                        "price_1": int(m_price), 
                        "price_2": 0, 
                        "image_data": ""
                    }
                    st.session_state.final_edit_df = pd.concat([st.session_state.final_edit_df, pd.DataFrame([new_row])], ignore_index=True)
                    st.session_state.files_ready = False
                    st.rerun()
                else:
                    st.warning("品名を入力してください。")

        edited = st.data_editor(
            st.session_state.final_edit_df[disp_cols], 
            num_rows="dynamic",
            width="stretch", 
            hide_index=True,
            column_config={
                "품목": st.column_config.TextColumn(label="品名", required=True),
                "규격": st.column_config.TextColumn(label="規格"),
                "코드": st.column_config.TextColumn(label="コード"),
                "단위": st.column_config.TextColumn(label="単位"),
                "수량": st.column_config.NumberColumn(label="数量", step=1, required=True),
                "price_1": st.column_config.NumberColumn(label=sel[0] if sel else "単価", format="%d", required=True),
                "price_2": st.column_config.NumberColumn(label=sel[1] if len(sel)>1 else "", format="%d")
            },
            on_change=on_data_change
        )
        
        st.session_state.final_edit_df = edited

        if sel:
            st.write("")
            if st.button("📄 見積書ファイル作成 (PDF/Excel)", type="primary", use_container_width=True):
                with st.spinner("ファイルを作成しています... (画像ダウンロード及び変換中)"):
                    fmode = "기본 양식" if "基本" in form_type else "이익 분석 양식"
                    safe_data = edited.fillna(0).to_dict('records')
                    
                    pdf_excel_services = []
                    for s in st.session_state.services:
                        pdf_excel_services.append(s.copy())
                        
                    if vat_mode == "税抜 (別)":
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

                    if print_mode == "セット単位まとめ (新規)":
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
                                "규격": "SET",
                                "코드": s_name, 
                                "단위": "SET",
                                "수량": s_qty,
                                "price_1": int(s_price1),
                                "price_2": int(s_price2),
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
                                new_item["수량"] = int(rem_qty)
                                rem_items_out.append(new_item)
                                comp_pool[match_key] = 0
                        
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
                st.success("ファイル作成が完了しました！下のボタンからダウンロードしてください。")
                col_pdf, col_xls = st.columns(2)
                with col_pdf:
                    st.download_button("📥 見積書 PDF", st.session_state.gen_pdf, f"Quote_{st.session_state.current_quote_name}.pdf", "application/pdf", type="primary", use_container_width=True)
                with col_xls:
                    st.download_button("📊 見積書 Excel", st.session_state.gen_excel, f"Quote_{st.session_state.current_quote_name}.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", use_container_width=True)
                
                st.write("")
                st.markdown("##### 📂 資材構成明細書 ダウンロード")
                c_comp_pdf, c_comp_xls = st.columns(2)
                with c_comp_pdf:
                    st.download_button("📥 資材明細 PDF", st.session_state.gen_comp_pdf, f"Composition_{st.session_state.current_quote_name}.pdf", "application/pdf", use_container_width=True)
                with c_comp_xls:
                    st.download_button("📊 資材明細 Excel", st.session_state.gen_comp_excel, f"Composition_{st.session_state.current_quote_name}.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", use_container_width=True)
            else:
                st.info("👆 上のボタンを押してファイルを作成してください。(データ修正時は再作成が必要です)")
        
        st.write("")
        st.markdown("##### 📝 特約事項及び備考 (修正可能)")
        st.session_state.quote_remarks = st.text_area(
            "特約事項", 
            value=st.session_state.quote_remarks, 
            height=100, 
            label_visibility="collapsed"
        )

        c1, c2 = st.columns(2)
        with c1: 
            if st.button("⬅️ 修正 (STEP 2に戻る)"): 
                st.session_state.quote_step = 2
                st.session_state.step3_ready = False
                st.session_state.files_ready = False
                st.rerun()
        with c2:
            if st.button("🔄 最初に戻る"): 
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

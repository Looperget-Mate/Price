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
from googleapiclient.http import MediaIoBaseUpload, MediaIoBaseDownload

# ==========================================
# [중요] 페이지 설정은 반드시 맨 처음에 와야 합니다.
# ==========================================
st.set_page_config(layout="wide", page_title="루퍼젯 프로 매니저 V10.0")

# ==========================================
# 1. 설정 및 구글 연동 유틸리티
# ==========================================
FONT_FILE = "NanumGothic.ttf"
FONT_BOLD_FILE = "NanumGothicBold.ttf"
FONT_URL = "https://github.com/google/fonts/raw/main/ofl/nanumgothic/NanumGothic-Regular.ttf"

# 폰트 파일 검증 및 다운로드
if not os.path.exists(FONT_FILE) or os.path.getsize(FONT_FILE) < 100:
    import urllib.request
    try: 
        urllib.request.urlretrieve(FONT_URL, FONT_FILE)
    except: pass

# --- 구글 인증 ---
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive"
]

@st.cache_resource
def get_google_services():
    try:
        creds_dict = dict(st.secrets["gcp_service_account"])
        creds = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
        gc = gspread.authorize(creds)
        drive_service = build('drive', 'v3', credentials=creds)
        return gc, drive_service
    except Exception as e:
        st.error(f"구글 인증 실패: {e}")
        return None, None

gc, drive_service = get_google_services()

# --- 구글 드라이브 ---
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
    except: return None

def upload_image_to_drive(file_obj, filename):
    folder_id = get_or_create_drive_folder()
    if not folder_id: return None
    try:
        file_metadata = {'name': filename, 'parents': [folder_id]}
        media = MediaIoBaseUpload(file_obj, mimetype=file_obj.type, resumable=True)
        drive_service.files().create(body=file_metadata, media_body=media, fields='id').execute()
        return filename
    except: return None

@st.cache_data(ttl=3600)
def get_image_from_drive(filename):
    if not filename or not drive_service: return None
    try:
        folder_id = get_or_create_drive_folder()
        query = f"name='{filename}' and '{folder_id}' in parents and trashed=false"
        results = drive_service.files().list(q=query, fields="files(id)").execute()
        files = results.get('files', [])
        if not files: return None
        
        file_id = files[0]['id']
        request = drive_service.files().get_media(fileId=file_id)
        
        fh = io.BytesIO()
        downloader = MediaIoBaseDownload(fh, request)
        done = False
        while done is False: status, done = downloader.next_chunk()
        
        fh.seek(0)
        img = Image.open(fh).convert('RGB')
        img.thumbnail((300, 225))
        
        buffer = io.BytesIO()
        img.save(buffer, format="JPEG")
        return f"data:image/jpeg;base64,{base64.b64encode(buffer.getvalue()).decode()}"
    except: return None

def list_files_in_drive_folder():
    folder_id = get_or_create_drive_folder()
    if not folder_id: return {}
    try:
        query = f"'{folder_id}' in parents and trashed=false"
        files = []
        page_token = None
        while True:
            response = drive_service.files().list(q=query, spaces='drive', fields='nextPageToken, files(id, name)', pageToken=page_token).execute()
            files.extend(response.get('files', []))
            page_token = response.get('nextPageToken', None)
            if page_token is None: break
        return {os.path.splitext(f['name'])[0]: f['name'] for f in files}
    except: return {}

# --- 구글 시트 ---
SHEET_NAME = "Looperget_DB"
COL_MAP = {"순번": "order_no", "품목코드": "code", "카테고리": "category", "제품명": "name", "규격": "spec", "단위": "unit", "1롤길이(m)": "len_per_unit", "매입단가": "price_buy", "총판가1": "price_d1", "총판가2": "price_d2", "대리점가": "price_agy", "소비자가": "price_cons", "단가(현장)": "price_site", "이미지데이터": "image"}
REV_COL_MAP = {v: k for k, v in COL_MAP.items()}

def load_data_from_sheet():
    if not gc: return {"config": {"password": "1234"}, "products": [], "sets": {}}
    try:
        sh = gc.open(SHEET_NAME)
    except:
        sh = gc.create(SHEET_NAME)
        sh.add_worksheet("Products", 100, 20)
        sh.add_worksheet("Sets", 100, 10)
        sh.worksheet("Products").append_row(list(COL_MAP.keys()))
        sh.worksheet("Sets").append_row(["세트명", "카테고리", "하위분류", "이미지파일명", "레시피JSON"])

    data = {"config": {"password": "1234"}, "products": [], "sets": {}}
    
    try:
        ws_prod = sh.worksheet("Products")
        records = ws_prod.get_all_records()
        for rec in records:
            new_rec = {}
            for k, v in rec.items():
                if k in COL_MAP:
                    if k == "품목코드": new_rec[COL_MAP[k]] = str(v).zfill(5)
                    else: new_rec[COL_MAP[k]] = v
            
            if "order_no" not in new_rec or new_rec["order_no"] == "": new_rec["order_no"] = 9999
            else: 
                try: new_rec["order_no"] = int(new_rec["order_no"])
                except: new_rec["order_no"] = 9999

            for p in ["price_site", "price_cons", "price_buy", "price_d1", "price_d2", "price_agy"]:
                val = str(new_rec.get(p, 0)).replace(",", "")
                try: new_rec[p] = int(val)
                except: new_rec[p] = 0
            
            data["products"].append(new_rec)
        
        data["products"] = sorted(data["products"], key=lambda x: x["order_no"])

    except Exception: pass 

    try:
        set_records = ws_sets.get_all_records()
        for rec in set_records:
            cat = rec.get("카테고리", "")
            name = rec.get("세트명", "")
            if cat and name:
                if cat not in data["sets"]: data["sets"][cat] = {}
                try: js = json.loads(r.get("레시피JSON", "{}"))
                except: js = {}
                data["sets"][cat][name] = {"recipe": js, "image": r.get("이미지파일명", ""), "sub_cat": r.get("하위분류", "")}
    except: pass
    
    return data

def save_products_to_sheet(products_list):
    if not gc: return
    sh = gc.open(SHEET_NAME)
    ws = sh.worksheet("Products")
    df = pd.DataFrame(products_list)
    if "code" in df.columns: df["code"] = df["code"].astype(str).apply(lambda x: x.zfill(5))
    df_up = df.rename(columns=REV_COL_MAP)
    ws.clear()
    ws.update([df_up.columns.values.tolist()] + df_up.values.tolist())

def save_sets_to_sheet(sets_dict):
    if not gc: return
    sh = gc.open(SHEET_NAME)
    ws = sh.worksheet("Sets")
    rows = [["세트명", "카테고리", "하위분류", "이미지파일명", "레시피JSON"]]
    for c, items in sets_dict.items():
        for n, info in items.items():
            rows.append([n, c, info.get("sub_cat",""), info.get("image",""), json.dumps(info.get("recipe",{}), ensure_ascii=False)])
    ws.clear()
    ws.update(rows)

# ==========================================
# 2. PDF 생성 엔진 (안전한 Latin-1 인코딩)
# ==========================================
class PDF(FPDF):
    def header(self):
        font_ok = False
        if os.path.exists(FONT_FILE):
            try: 
                self.add_font('NanumGothic', '', FONT_FILE, uni=True)
                self.set_font('NanumGothic', '', 20)
                font_ok = True
            except: pass
        
        if not font_ok: self.set_font('Arial', 'B', 20)
        self.cell(0, 15, 'Quotation (Estimate)', align='C', new_x="LMARGIN", new_y="NEXT")
        
        if font_ok: self.set_font('NanumGothic', '', 9)
        else: self.set_font('Arial', '', 9)
        self.ln(2)

    def footer(self):
        self.set_y(-20)
        font_ok = False
        if os.path.exists(FONT_FILE):
            try:
                self.set_font('NanumGothic', '', 8)
                font_ok = True
            except: pass
        if not font_ok: self.set_font('Arial', 'I', 8)
        
        self.cell(0, 5, f'Page {self.page_no()}', align='C')

def create_advanced_pdf(final_data_list, service_items, quote_name, quote_date, form_type, price_labels, recipient_info):
    pdf = PDF()
    pdf.add_page()
    
    font_ok = False
    if os.path.exists(FONT_FILE):
        try:
            pdf.add_font('NanumGothic', '', FONT_FILE, uni=True)
            font_ok = True
        except: pass
    
    font_name = 'NanumGothic' if font_ok else 'Arial'
    pdf.set_font(font_name, '', 10)

    pdf.set_fill_color(255, 255, 255)
    
    # Supply Info
    pdf.set_xy(105, pdf.get_y())
    pdf.cell(90, 8, " [ Supplier ]", border=0, ln=1)
    x = 105; y = pdf.get_y()
    pdf.set_xy(x, y); pdf.cell(20, 6, "Reg.No", 1, 0, 'C'); pdf.cell(75, 6, "123-45-67890", 1, 1, 'C')
    pdf.set_x(x); pdf.cell(20, 6, "Company", 1, 0, 'C'); pdf.cell(35, 6, "(Jur)ShinJin", 1, 0, 'C'); pdf.cell(15, 6, "Rep", 1, 0, 'C'); pdf.cell(25, 6, "Park", 1, 1, 'C')
    pdf.set_x(x); pdf.cell(20, 12, "Addr", 1, 0, 'C'); pdf.multi_cell(75, 6, "1859-157, Hwangmu-ro, Bubal-eup, Icheon-si", 1, 'L')
    pdf.set_xy(x, pdf.get_y()); pdf.cell(20, 6, "Tel", 1, 0, 'C'); pdf.cell(75, 6, "031-638-1809", 1, 1, 'C')

    # Customer Info
    pdf.set_xy(10, y)
    pdf.cell(90, 8, " [ Customer ]", border=0, ln=1)
    pdf.cell(25, 6, "Name:", 0); pdf.cell(65, 6, f"{recipient_info.get('name','')}", "B", 1)
    pdf.cell(25, 6, "Contact:", 0); pdf.cell(65, 6, f"{recipient_info.get('contact','')}", "B", 1)
    pdf.cell(25, 6, "Tel:", 0); pdf.cell(65, 6, f"{recipient_info.get('phone','')}", "B", 1)
    
    pdf.ln(20)
    pdf.cell(0, 5, f"Date: {quote_date}", 0, 1, 'R')
    pdf.ln(2)

    # Table Header
    pdf.set_fill_color(240, 240, 240)
    pdf.cell(15, 10, "IMG", 1, 0, 'C', True)
    pdf.cell(45, 10, "Item/Spec", 1, 0, 'C', True)
    pdf.cell(10, 10, "Unit", 1, 0, 'C', True)
    pdf.cell(12, 10, "Qty", 1, 0, 'C', True)
    if "기본" in form_type:
        pdf.cell(35, 10, "Price", 1, 0, 'C', True)
        pdf.cell(35, 10, "Amount", 1, 0, 'C', True)
        pdf.cell(38, 10, "Note", 1, 1, 'C', True)
    else:
        pdf.cell(18, 10, "P1", 1, 0, 'C', True); pdf.cell(22, 10, "A1", 1, 0, 'C', True)
        pdf.cell(18, 10, "P2", 1, 0, 'C', True); pdf.cell(22, 10, "A2", 1, 0, 'C', True)
        pdf.cell(15, 10, "Gap", 1, 0, 'C', True); pdf.cell(13, 10, "%", 1, 1, 'C', True)

    sum_qty = 0; sum_a1 = 0; sum_a2 = 0; sum_profit = 0
    for item in final_data_list:
        if pdf.get_y() > 250: pdf.add_page()
        
        name = item.get("품목",""); spec = item.get("규격","-"); code = item.get("코드","")
        qty = int(item.get("수량",0))
        p1 = int(item.get("price_1",0)); a1 = p1*qty
        p2 = int(item.get("price_2",0)); a2 = p2*qty
        profit = a2 - a1
        
        sum_qty += qty; sum_a1 += a1; sum_a2 += a2; sum_profit += profit

        img_b64 = None
        if item.get("image_data"):
             img_b64 = get_image_from_drive(item.get("image_data"))
        
        x = pdf.get_x(); y = pdf.get_y()
        pdf.cell(15, 15, "", 1)
        if img_b64:
            try:
                raw = base64.b64decode(img_b64.split(",")[1])
                with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as tf:
                    tf.write(raw); tname = tf.name
                pdf.image(tname, x+1, y+1, 13, 13)
                os.unlink(tname)
            except: pass

        pdf.set_xy(x+15, y)
        pdf.cell(45, 15, "", 1)
        pdf.set_xy(x+15, y+2); pdf.set_font(font_name, '', 8); pdf.multi_cell(45, 4, f"{name}\n{spec}\n[{code}]", align='L')
        pdf.set_xy(x+60, y); pdf.set_font(font_name, '', 10)

        pdf.cell(10, 15, item.get("단위",""), 1, 0, 'C')
        pdf.cell(12, 15, str(qty), 1, 0, 'C')

        if "기본" in form_type:
            pdf.cell(35, 15, f"{p1:,}", 1, 0, 'R')
            pdf.cell(35, 15, f"{a1:,}", 1, 0, 'R')
            pdf.cell(38, 15, "", 1, 1, 'C')
        else:
            pdf.set_font(font_name, '', 8)
            pdf.cell(18, 15, f"{p1:,}", 1, 0, 'R'); pdf.cell(22, 15, f"{a1:,}", 1, 0, 'R')
            pdf.cell(18, 15, f"{p2:,}", 1, 0, 'R'); pdf.cell(22, 15, f"{a2:,}", 1, 0, 'R')
            pdf.cell(15, 15, f"{profit:,}", 1, 0, 'R'); 
            rate = (profit/a2*100) if a2 else 0
            pdf.cell(13, 15, f"{rate:.1f}%", 1, 1, 'C')
            pdf.set_font(font_name, '', 10)

    # 합계
    pdf.set_fill_color(230, 230, 230); pdf.set_font(font_name, 'B' if font_ok else '', 10)
    pdf.cell(70, 10, "Total", 1, 0, 'C', True)
    pdf.cell(12, 10, f"{sum_qty:,}", 1, 0, 'C', True)
    
    if "기본" in form_type:
        pdf.cell(35, 10, "", 1, 0, 'C', True)
        pdf.cell(35, 10, f"{sum_a1:,}", 1, 0, 'R', True)
        pdf.cell(38, 10, "", 1, 1, 'C', True)
    else:
        pdf.cell(40, 10, f"{sum_a1:,}", 1, 0, 'R', True)
        pdf.cell(40, 10, f"{sum_a2:,}", 1, 0, 'R', True)
        pdf.cell(28, 10, f"{sum_profit:,}", 1, 1, 'R', True)

    pdf.ln(10)
    pdf.cell(0, 10, "SHIN JIN CHEMTECH Co., Ltd.", 0, 1, 'C')

    return pdf.output(dest='S').encode('latin-1')

# ==========================================
# 3. 메인 로직
# ==========================================
st.title("💧 루퍼젯 프로 매니저 V10.0")

if "db" not in st.session_state:
    st.session_state.db = load_data_from_sheet()

if "history" not in st.session_state: st.session_state.history = {}
if "quote_step" not in st.session_state: st.session_state.quote_step = 1
if "quote_items" not in st.session_state: st.session_state.quote_items = {} 
if "services" not in st.session_state: st.session_state.services = []
if "temp_set_recipe" not in st.session_state: st.session_state.temp_set_recipe = {}
if "current_quote_name" not in st.session_state: st.session_state.current_quote_name = ""
if "auth_admin" not in st.session_state: st.session_state.auth_admin = False
if "auth_price" not in st.session_state: st.session_state.auth_price = False
if "recipient_info" not in st.session_state: st.session_state.recipient_info = {}

# [복구] 주배관/가지관 목록
if "added_main_pipes" not in st.session_state: st.session_state.added_main_pipes = []
if "added_branch_pipes" not in st.session_state: st.session_state.added_branch_pipes = []

DEFAULT_DATA = {"config": {"password": "1234"}, "products":[], "sets":{}}
if not st.session_state.db: st.session_state.db = DEFAULT_DATA
if "config" not in st.session_state.db: st.session_state.db["config"] = {"password": "1234"}

# 사이드바
with st.sidebar:
    st.header("🗂️ 견적 보관함")
    qn = st.text_input("현장명", value=st.session_state.current_quote_name)
    if st.button("💾 저장"):
        st.session_state.history[qn] = {
            "items": st.session_state.quote_items, 
            "step": st.session_state.quote_step,
            "recipient": st.session_state.recipient_info,
            "main": st.session_state.added_main_pipes,
            "branch": st.session_state.added_branch_pipes
        }
        st.session_state.current_quote_name = qn
        st.success("저장됨")
    
    if st.button("✨ 초기화"):
        st.session_state.quote_items = {}
        st.session_state.quote_step = 1
        st.session_state.added_main_pipes = []
        st.session_state.added_branch_pipes = []
        st.rerun()

    st.divider()
    mode = st.radio("모드", ["견적 작성", "관리자 모드"])

# 관리자 모드
if mode == "관리자 모드":
    st.header("🛠 관리자 모드")
    if st.button("🔄 데이터 새로고침"):
        st.session_state.db = load_data_from_sheet()
        st.rerun()

    if not st.session_state.auth_admin:
        pw = st.text_input("비밀번호", type="password")
        if st.button("로그인") and pw == st.session_state.db["config"]["password"]:
            st.session_state.auth_admin = True
            st.rerun()
    else:
        if st.button("로그아웃"): 
            st.session_state.auth_admin = False
            st.rerun()
        
        t1, t2 = st.tabs(["제품 관리", "세트 관리"])
        with t1:
            df = pd.DataFrame(st.session_state.db["products"])
            if "order_no" not in df.columns: df["order_no"] = 9999
            df = df.sort_values(by="order_no")
            df_disp = df.rename(columns=REV_COL_MAP)
            st.dataframe(df_disp, use_container_width=True)
            
            # [수정] 문법 오류 해결된 엑셀 다운로드
            buf = io.BytesIO()
            with pd.ExcelWriter(buf, engine='xlsxwriter') as w:
                df.to_excel(w, index=False)
            st.download_button("엑셀 다운로드", buf.getvalue(), "products.xlsx")
            
            if st.button("🔄 드라이브 이미지 연결"):
                fmap = list_files_in_drive_folder()
                cnt = 0
                for p in st.session_state.db["products"]:
                    c = str(p.get("code","")).strip()
                    if c in fmap:
                        p["image"] = fmap[c]
                        cnt += 1
                if cnt:
                    save_products_to_sheet(st.session_state.db["products"])
                    st.success(f"{cnt}개 연결 완료")
                    st.session_state.db = load_data_from_sheet()
                    st.rerun()

            c1, c2, c3 = st.columns([2,2,1])
            products = st.session_state.db["products"]
            with c1: 
                sp = st.selectbox("대상 품목", products, format_func=lambda x: f"[{x['code']}] {x['name']}")
            with c2: ifile = st.file_uploader("이미지", ["png","jpg"])
            with c3:
                if st.button("업로드"):
                    if ifile and sp:
                        fn = f"{sp['name']}_{ifile.name}"
                        fid = upload_image_to_drive(ifile, fn)
                        if fid:
                            for p in st.session_state.db["products"]:
                                if p['name'] == sp['name']: p['image'] = fid
                            save_products_to_sheet(st.session_state.db["products"])
                            st.success("완료")

# 견적 모드
else:
    name_to_code = {p['name']: p['code'] for p in st.session_state.db["products"]}
    code_to_p = {p['code']: p for p in st.session_state.db["products"]}

    if st.session_state.quote_step == 1:
        st.subheader("STEP 1. 물량 입력")
        sets = st.session_state.db.get("sets", {})

        def render_inputs(d, pf):
            cols = st.columns(4); res = {}
            for i, (n, v) in enumerate(d.items()):
                with cols[i%4]:
                    res[n] = st.number_input(n, 0, key=f"{pf}_{n}")
            return res

        with st.expander("1. 주배관 세트", True):
             m_sets = sets.get("주배관세트", {})
             grouped = {"50mm":{}, "40mm":{}, "기타":{}, "미분류":{}}
             for k, v in m_sets.items():
                 sc = v.get("sub_cat", "미분류") if isinstance(v, dict) else "미분류"
                 if sc not in grouped: grouped[sc] = {}
                 grouped[sc][k] = v
             t1, t2, t3, t4 = st.tabs(["50mm", "40mm", "기타", "전체"])
             with t1: inp_m_50 = render_inputs(grouped["50mm"], "m50")
             with t2: inp_m_40 = render_inputs(grouped["40mm"], "m40")
             with t3: inp_m_etc = render_inputs(grouped["기타"], "metc")
             with t4: inp_m_u = render_inputs(grouped["미분류"], "mu")

        with st.expander("2. 가지관 세트"): inp_b = render_inputs(sets.get("가지관세트", {}), "b")
        with st.expander("3. 기타 자재"): inp_e = render_inputs(sets.get("기타자재", {}), "e")

        c1, c2 = st.columns(2)
        prods = st.session_state.db["products"]
        mpl = [p for p in prods if p["category"] == "주배관"]
        bpl = [p for p in prods if p["category"] == "가지관"]

        with c1:
            st.markdown("##### 주배관")
            sm = st.selectbox("선택", mpl, format_func=lambda x: f"[{x['code']}] {x['name']}", key="sm")
            lm = st.number_input("길이", key="lm")
            if st.button("➕ 추가", key="am"):
                st.session_state.added_main_pipes.append({"obj": sm, "len": lm})
            if st.session_state.added_main_pipes:
                st.write([f"{i['obj']['name']} {i['len']}m" for i in st.session_state.added_main_pipes])
                if st.button("초기화", key="cm"): st.session_state.added_main_pipes = []; st.rerun()

        with c2:
            st.markdown("##### 가지관")
            sb = st.selectbox("선택", bpl, format_func=lambda x: f"[{x['code']}] {x['name']}", key="sb")
            lb = st.number_input("길이", key="lb")
            if st.button("➕ 추가", key="ab"):
                st.session_state.added_branch_pipes.append({"obj": sb, "len": lb})
            if st.session_state.added_branch_pipes:
                st.write([f"{i['obj']['name']} {i['len']}m" for i in st.session_state.added_branch_pipes])
                if st.button("초기화", key="cb"): st.session_state.added_branch_pipes = []; st.rerun()

        if st.button("계산하기 (STEP 2)", type="primary"):
            res = {}
            all_m = {**inp_m_50, **inp_m_40, **inp_m_etc, **inp_m_u}
            
            def ex(ins, db):
                for k,v in ins.items():
                    if v>0:
                        rec = db[k].get("recipe", db[k])
                        for p_name, q in rec.items(): 
                            p_code = name_to_code.get(p_name)
                            if p_code:
                                res[p_code] = res.get(p_code, 0) + q*v
            ex(all_m, sets.get("주배관세트", {})); ex(inp_b, sets.get("가지관세트", {})); ex(inp_e, sets.get("기타자재", {}))
            
            for item in st.session_state.added_main_pipes:
                p = item['obj']
                qty = math.ceil(item['len'] / (p['len_per_unit'] or 50))
                res[p['code']] = res.get(p['code'], 0) + qty
            for item in st.session_state.added_branch_pipes:
                p = item['obj']
                qty = math.ceil(item['len'] / (p['len_per_unit'] or 50))
                res[p['code']] = res.get(p['code'], 0) + qty
            
            st.session_state.quote_items = res
            st.session_state.quote_step = 2
            st.rerun()

    elif st.session_state.quote_step == 2:
        st.subheader("STEP 2. 견적 확인")
        if st.button("⬅️ 다시 입력"):
            st.session_state.quote_step = 1
            st.rerun()
            
        rows = []
        for code, qty in st.session_state.quote_items.items():
            if code in code_to_p:
                p = code_to_p[code]
                rows.append({
                    "품목": p['name'], "규격": p['spec'], "코드": code, "수량": qty,
                    "소비자가": p['price_cons'], "단가(현장)": p['price_site']
                })
        
        st.dataframe(pd.DataFrame(rows), use_container_width=True)
        
        c1, c2 = st.columns(2)
        with c1:
            all_prods = st.session_state.db["products"]
            ap = st.selectbox("추가 품목", all_prods, format_func=lambda x: f"[{x['code']}] {x['name']}")
            aq = st.number_input("수량", 1)
            if st.button("추가"):
                st.session_state.quote_items[ap['code']] = st.session_state.quote_items.get(ap['code'], 0) + aq
                st.rerun()
        
        if st.button("최종 견적 (STEP 3)"):
            st.session_state.quote_step = 3
            st.rerun()

    elif st.session_state.quote_step == 3:
        st.subheader("최종 견적")
        
        with st.container(border=True):
            c1, c2 = st.columns(2)
            rn = c1.text_input("현장명", value=st.session_state.recipient_info.get("name",""))
            rc = c1.text_input("담당자", value=st.session_state.recipient_info.get("contact",""))
            rp = c2.text_input("연락처", value=st.session_state.recipient_info.get("phone",""))
            ra = c2.text_input("주소", value=st.session_state.recipient_info.get("addr",""))
            st.session_state.recipient_info = {"name":rn, "contact":rc, "phone":rp, "addr":ra}
            
        col1, col2 = st.columns(2)
        with col1: form = st.radio("양식", ["기본", "이익분석"])
        with col2: 
            if form == "기본":
                pr = st.radio("단가", ["소비자가", "단가(현장)"])
                sel = [pr]
            else:
                sel = st.multiselect("비교 단가", ["매입단가", "소비자가"], default=["매입단가", "소비자가"])

        rows = []
        pkey = {"매입단가":"price_buy", "소비자가":"price_cons", "단가(현장)":"price_site"}
        
        for code, qty in st.session_state.quote_items.items():
            if code in code_to_p:
                p = code_to_p[code]
                item = {
                    "품목": p['name'], "규격": p['spec'], "코드": code, "단위": p['unit'],
                    "수량": qty, "image_data": p.get('image'), "order_no": p['order_no']
                }
                if sel:
                    item["price_1"] = p.get(pkey.get(sel[0], "price_cons"), 0)
                    if len(sel) > 1:
                        item["price_2"] = p.get(pkey.get(sel[1], "price_cons"), 0)
                rows.append(item)
        
        rows = sorted(rows, key=lambda x: x["order_no"])
        
        pdf_bytes = create_advanced_pdf(rows, [], q_name, datetime.datetime.now().strftime("%Y-%m-%d"), form, sel, st.session_state.recipient_info)
        
        if pdf_bytes:
            st.download_button("📄 PDF 다운로드", pdf_bytes, file_name="quote.pdf", mime="application/pdf", type="primary")
        else:
            st.error("PDF 생성 실패")
        
        if st.button("처음으로"):
            st.session_state.quote_step = 1
            st.session_state.quote_items = {}
            st.session_state.added_main_pipes = []
            st.session_state.added_branch_pipes = []
            st.rerun()

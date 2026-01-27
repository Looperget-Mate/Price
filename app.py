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
# [필수] 페이지 설정 (가장 먼저 실행)
# ==========================================
st.set_page_config(layout="wide", page_title="루퍼젯 프로 매니저 V10.0")

# ==========================================
# 1. 설정 및 폰트 준비
# ==========================================
FONT_FILE = "NanumGothic.ttf"
FONT_URL = "https://github.com/google/fonts/raw/main/ofl/nanumgothic/NanumGothic-Regular.ttf"

# 폰트 다운로드 (없으면 다운)
if not os.path.exists(FONT_FILE) or os.path.getsize(FONT_FILE) < 100:
    import urllib.request
    try: urllib.request.urlretrieve(FONT_URL, FONT_FILE)
    except: pass

# --- 구글 인증 ---
SCOPES = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]

@st.cache_resource
def get_google_services():
    try:
        creds_dict = dict(st.secrets["gcp_service_account"])
        creds = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
        gc = gspread.authorize(creds)
        drive_service = build('drive', 'v3', credentials=creds)
        return gc, drive_service
    except: return None, None

gc, drive_service = get_google_services()
SHEET_NAME = "Looperget_DB"
DRIVE_FOLDER_NAME = "Looperget_Images"

# --- 드라이브 & 시트 유틸리티 ---
def get_or_create_drive_folder():
    if not drive_service: return None
    try:
        query = f"name='{DRIVE_FOLDER_NAME}' and mimeType='application/vnd.google-apps.folder' and trashed=false"
        res = drive_service.files().list(q=query, fields="files(id)").execute()
        files = res.get('files', [])
        if files: return files[0]['id']
        else:
            meta = {'name': DRIVE_FOLDER_NAME, 'mimeType': 'application/vnd.google-apps.folder'}
            return drive_service.files().create(body=meta, fields='id').execute().get('id')
    except: return None

def upload_image_to_drive(file_obj, filename):
    fid = get_or_create_drive_folder()
    if not fid: return None
    try:
        meta = {'name': filename, 'parents': [fid]}
        media = MediaIoBaseUpload(file_obj, mimetype=file_obj.type, resumable=True)
        drive_service.files().create(body=meta, media_body=media, fields='id').execute()
        return filename
    except: return None

@st.cache_data(ttl=3600)
def get_image_from_drive(filename):
    if not filename or not drive_service: return None
    try:
        fid = get_or_create_drive_folder()
        q = f"name='{filename}' and '{fid}' in parents and trashed=false"
        res = drive_service.files().list(q=q, fields="files(id)").execute()
        files = res.get('files', [])
        if not files: return None
        
        request = drive_service.files().get_media(fileId=files[0]['id'])
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
    fid = get_or_create_drive_folder()
    if not fid: return {}
    try:
        files = []
        token = None
        while True:
            res = drive_service.files().list(q=f"'{fid}' in parents and trashed=false", fields='nextPageToken, files(id, name)', pageToken=token).execute()
            files.extend(res.get('files', []))
            token = res.get('nextPageToken', None)
            if token is None: break
        return {os.path.splitext(f['name'])[0]: f['name'] for f in files}
    except: return {}

COL_MAP = {"순번": "order_no", "품목코드": "code", "카테고리": "category", "제품명": "name", "규격": "spec", "단위": "unit", "1롤길이(m)": "len_per_unit", "매입단가": "price_buy", "총판가1": "price_d1", "총판가2": "price_d2", "대리점가": "price_agy", "소비자가": "price_cons", "단가(현장)": "price_site", "이미지데이터": "image"}
REV_COL_MAP = {v: k for k, v in COL_MAP.items()}

def load_data():
    if not gc: return {"config": {"password": "1234"}, "products": [], "sets": {}}
    try: sh = gc.open(SHEET_NAME)
    except:
        sh = gc.create(SHEET_NAME)
        sh.add_worksheet("Products", 100, 20); sh.add_worksheet("Sets", 100, 10); sh.add_worksheet("Config", 10, 2)
        sh.worksheet("Products").append_row(list(COL_MAP.keys()))
        sh.worksheet("Sets").append_row(["세트명", "카테고리", "하위분류", "이미지파일명", "레시피JSON"])
        sh.worksheet("Config").append_row(["Key", "Value"])
        sh.worksheet("Config").append_row(["password", "1234"])

    data = {"config": {"password": "1234"}, "products": [], "sets": {}}
    
    # Config
    try:
        cfg = sh.worksheet("Config").get_all_records()
        for c in cfg:
            if c['Key'] == 'password': data['config']['password'] = str(c['Value'])
    except: pass

    # Products
    try:
        recs = sh.worksheet("Products").get_all_records()
        for r in recs:
            nr = {}
            for k, v in r.items():
                if k in COL_MAP:
                    if k == "품목코드": nr[COL_MAP[k]] = str(v).zfill(5)
                    else: nr[COL_MAP[k]] = v
            
            # 숫자 처리
            if "order_no" not in nr or nr["order_no"] == "": nr["order_no"] = 9999
            else: 
                try: nr["order_no"] = int(nr["order_no"])
                except: nr["order_no"] = 9999
            
            for p in ["price_site", "price_cons", "price_buy", "price_d1", "price_d2", "price_agy"]:
                try: nr[p] = int(str(nr.get(p,0)).replace(",",""))
                except: nr[p] = 0
            
            data["products"].append(nr)
        data["products"] = sorted(data["products"], key=lambda x: x["order_no"])
    except: pass

    # Sets
    try:
        s_recs = sh.worksheet("Sets").get_all_records()
        for r in s_recs:
            c = r.get("카테고리"); n = r.get("세트명")
            if c and n:
                if c not in data["sets"]: data["sets"][c] = {}
                try: js = json.loads(r.get("레시피JSON", "{}"))
                except: js = {}
                data["sets"][c][n] = {"recipe": js, "image": r.get("이미지파일명", ""), "sub_cat": r.get("하위분류", "")}
    except: pass
    
    return data

def save_all_data(data):
    if not gc: return
    sh = gc.open(SHEET_NAME)
    
    # Products
    ws_p = sh.worksheet("Products")
    df = pd.DataFrame(data["products"])
    if not df.empty:
        if "code" in df.columns: df["code"] = df["code"].astype(str).apply(lambda x: x.zfill(5))
        df_up = df.rename(columns=REV_COL_MAP)
        ws_p.clear()
        ws_p.update([df_up.columns.values.tolist()] + df_up.values.tolist())
    
    # Sets
    ws_s = sh.worksheet("Sets")
    rows = [["세트명", "카테고리", "하위분류", "이미지파일명", "레시피JSON"]]
    for c, items in data["sets"].items():
        for n, info in items.items():
            rows.append([n, c, info.get("sub_cat",""), info.get("image",""), json.dumps(info.get("recipe",{}), ensure_ascii=False)])
    ws_s.clear(); ws_s.update(rows)

    # Config
    ws_c = sh.worksheet("Config")
    ws_c.clear(); ws_c.update([["Key", "Value"], ["password", data["config"]["password"]]])

# ==========================================
# 2. PDF 생성 엔진 (오류 해결 버전)
# ==========================================
class PDF(FPDF):
    def header(self):
        try: self.add_font('NanumGothic', '', FONT_FILE, uni=True); self.set_font('NanumGothic', '', 18)
        except: self.set_font('Arial', 'B', 18)
        self.cell(0, 10, '견 적 서 (Quotation)', 0, 1, 'C')
        self.ln(5)

def create_pdf_final(data_list, service_list, quote_info, recipient):
    pdf = PDF()
    pdf.add_page()
    
    has_font = os.path.exists(FONT_FILE)
    font_name = 'NanumGothic' if has_font else 'Arial'
    if has_font: pdf.add_font(font_name, '', FONT_FILE, uni=True)
    pdf.set_font(font_name, '', 10)

    # 1. 정보 섹션
    pdf.set_fill_color(240, 240, 240)
    pdf.cell(95, 8, " 수신자 (Customer)", 1, 0, 'L', True)
    pdf.cell(95, 8, " 공급자 (Supplier)", 1, 1, 'L', True)
    
    x = pdf.get_x(); y = pdf.get_y()
    
    # 왼쪽 (수신자)
    pdf.cell(25, 8, "상호/성명", 1); pdf.cell(70, 8, f"{recipient.get('name','')}", 1, 1)
    pdf.cell(25, 8, "담당자", 1); pdf.cell(70, 8, f"{recipient.get('contact','')}", 1, 1)
    pdf.cell(25, 8, "연락처", 1); pdf.cell(70, 8, f"{recipient.get('phone','')}", 1, 1)
    pdf.cell(25, 8, "주소", 1); pdf.cell(70, 8, f"{recipient.get('addr','')}", 1, 1)
    
    # 오른쪽 (공급자)
    right_x = 105
    pdf.set_xy(right_x, y)
    pdf.cell(25, 8, "등록번호", 1); pdf.cell(70, 8, "123-45-67890", 1, 1)
    pdf.set_x(right_x); pdf.cell(25, 8, "상호", 1); pdf.cell(70, 8, "(주)신진켐텍", 1, 1)
    pdf.set_x(right_x); pdf.cell(25, 8, "대표자", 1); pdf.cell(70, 8, "박형석", 1, 1)
    pdf.set_x(right_x); pdf.cell(25, 8, "전화", 1); pdf.cell(70, 8, "031-638-1809", 1, 1)

    pdf.ln(5)
    pdf.cell(0, 8, f"견적일: {quote_info['date']} / 유효기간: 15일", 0, 1, 'R')
    pdf.ln(2)

    # 2. 품목 리스트
    pdf.set_fill_color(220, 220, 220)
    pdf.cell(10, 8, "No", 1, 0, 'C', True)
    pdf.cell(60, 8, "품목명 / 규격", 1, 0, 'C', True)
    pdf.cell(15, 8, "단위", 1, 0, 'C', True)
    pdf.cell(15, 8, "수량", 1, 0, 'C', True)
    pdf.cell(30, 8, "단가", 1, 0, 'C', True)
    pdf.cell(30, 8, "금액", 1, 0, 'C', True)
    pdf.cell(30, 8, "비고", 1, 1, 'C', True)

    total_amt = 0
    idx = 1
    
    for item in data_list:
        name = item.get("품목", "")
        spec = item.get("규격", "")
        unit = item.get("단위", "")
        qty = int(item.get("수량", 0))
        price = int(item.get("price_1", 0))
        amt = qty * price
        total_amt += amt
        
        pdf.cell(10, 8, str(idx), 1, 0, 'C')
        disp_name = f"{name} ({spec})"[:30] 
        pdf.cell(60, 8, disp_name, 1, 0, 'L')
        pdf.cell(15, 8, unit, 1, 0, 'C')
        pdf.cell(15, 8, str(qty), 1, 0, 'C')
        pdf.cell(30, 8, f"{price:,}", 1, 0, 'R')
        pdf.cell(30, 8, f"{amt:,}", 1, 0, 'R')
        pdf.cell(30, 8, "", 1, 1, 'C')
        idx += 1
        
    # 3. 추가 비용
    if service_list:
        pdf.ln(2)
        pdf.cell(0, 8, " [ 추가 비용 ]", 1, 1, 'L', True)
        for svc in service_list:
            s_name = svc['항목']
            s_amt = svc['금액']
            total_amt += s_amt
            pdf.cell(130, 8, s_name, 1, 0, 'L')
            pdf.cell(60, 8, f"{s_amt:,}", 1, 1, 'R')
            
    # 4. 총계
    pdf.ln(5)
    pdf.set_font(font_name, 'B' if has_font else '', 12)
    pdf.cell(130, 10, "총 합 계 (VAT 별도)", 1, 0, 'C', True)
    pdf.cell(60, 10, f"{total_amt:,} 원", 1, 1, 'R')
    
    pdf.ln(10)
    pdf.cell(0, 10, "주식회사 신진켐텍", 0, 1, 'C')

    # [수정] 안전한 출력 방식 (Latin-1)
    return pdf.output(dest='S').encode('latin-1')

# ==========================================
# 3. 메인 앱 로직
# ==========================================
if "db" not in st.session_state:
    st.session_state.db = load_data()

# 세션 초기화
for key in ["history", "quote_items", "services", "added_main", "added_branch", "quote_step", "recipient"]:
    if key not in st.session_state:
        if key == "quote_step": st.session_state[key] = 1
        elif key == "recipient": st.session_state[key] = {}
        elif key == "history": st.session_state[key] = {}
        else: st.session_state[key] = [] if key != "quote_items" else {}

# 사이드바
with st.sidebar:
    st.header("🗂️ 견적 관리")
    qn = st.text_input("현장명")
    if st.button("초기화"):
        st.session_state.quote_items = {}
        st.session_state.added_main = []
        st.session_state.added_branch = []
        st.session_state.services = []
        st.session_state.quote_step = 1
        st.rerun()
    st.divider()
    mode = st.radio("모드", ["견적 작성", "관리자 모드"])

# [관리자 모드]
if mode == "관리자 모드":
    st.title("🛠 관리자 모드")
    
    if not st.session_state.get("auth", False):
        pw = st.text_input("비밀번호", type="password")
        if st.button("로그인"):
            if pw == st.session_state.db["config"]["password"]:
                st.session_state.auth = True
                st.rerun()
            else: st.error("틀림")
    else:
        if st.button("로그아웃"): st.session_state.auth = False; st.rerun()
        
        t1, t2, t3 = st.tabs(["제품 관리", "세트 관리", "설정"])
        
        with t1: # 제품
            df = pd.DataFrame(st.session_state.db["products"])
            st.dataframe(df, hide_index=True)
            # [수정] 문법 오류 해결 (3줄로 분리)
            buf = io.BytesIO()
            with pd.ExcelWriter(buf, engine='xlsxwriter') as w:
                df.to_excel(w, index=False)
            st.download_button("엑셀 다운로드", buf.getvalue(), "data.xlsx")
            
        with t2: # 세트
            st.subheader("세트 관리")
            sets_db = st.session_state.db["sets"]
            cat = st.selectbox("카테고리", ["주배관세트", "가지관세트", "기타자재"])
            
            # 세트 표시
            if cat in sets_db:
                st.table(pd.DataFrame([{"세트명": k, "구성": len(v['recipe'])} for k, v in sets_db[cat].items()]))
            
            # 세트 추가/수정
            with st.expander("세트 추가/수정"):
                new_name = st.text_input("세트명 입력")
                
                if "temp_recipe" not in st.session_state: st.session_state.temp_recipe = {}
                
                c1, c2, c3 = st.columns([3,1,1])
                prods = st.session_state.db["products"]
                p_sel = c1.selectbox("부품", prods, format_func=lambda x: f"{x['name']} ({x['spec']})")
                q_sel = c2.number_input("수량", 1)
                if c3.button("담기"):
                    st.session_state.temp_recipe[p_sel['name']] = q_sel
                
                st.write("구성품:", st.session_state.temp_recipe)
                
                if st.button("세트 저장"):
                    if cat not in sets_db: sets_db[cat] = {}
                    sets_db[cat][new_name] = {"recipe": st.session_state.temp_recipe, "image":"", "sub_cat": ""}
                    save_all_data(st.session_state.db)
                    st.success("저장됨")
                    st.session_state.temp_recipe = {}
                    st.rerun()

        with t3: # 설정
            st.subheader("비밀번호 변경")
            new_pw = st.text_input("새 비밀번호")
            if st.button("변경"):
                st.session_state.db["config"]["password"] = new_pw
                save_all_data(st.session_state.db)
                st.success("변경 완료")

# [견적 모드]
else:
    st.title("💧 루퍼젯 프로 매니저")
    
    # STEP 1
    if st.session_state.quote_step == 1:
        st.subheader("1. 물량 입력")
        
        sets = st.session_state.db["sets"]
        with st.expander("세트 입력", True):
            cols = st.columns(3)
            idx = 0
            for cat, items in sets.items():
                for name, info in items.items():
                    with cols[idx%3]:
                        qty = st.number_input(f"{name}", 0, key=f"s_{name}")
                        if qty > 0:
                            for p, q in info['recipe'].items():
                                st.session_state.quote_items[p] = st.session_state.quote_items.get(p, 0) + q * qty
                    idx+=1

        st.divider()
        c1, c2 = st.columns(2)
        prods = st.session_state.db["products"]
        mpl = [p for p in prods if p["category"] == "주배관"]
        bpl = [p for p in prods if p["category"] == "가지관"]
        
        with c1:
            st.markdown("##### 주배관")
            sm = st.selectbox("선택", mpl, format_func=lambda x: f"{x['name']} ({x['spec']})", key='sm')
            lm = st.number_input("길이(m)", step=1, key='lm')
            if st.button("추가", key='am'): st.session_state.added_main.append({"obj": sm, "len": lm})
            for i in st.session_state.added_main: st.text(f"{i['obj']['name']}: {i['len']}m")

        with c2:
            st.markdown("##### 가지관")
            sb = st.selectbox("선택", bpl, format_func=lambda x: f"{x['name']} ({x['spec']})", key='sb')
            lb = st.number_input("길이(m)", step=1, key='lb')
            if st.button("추가", key='ab'): st.session_state.added_branch.append({"obj": sb, "len": lb})
            for i in st.session_state.added_branch: st.text(f"{i['obj']['name']}: {i['len']}m")
        
        if st.button("다음 단계 (계산)", type="primary"):
            for i in st.session_state.added_main:
                p = i['obj']; qty = math.ceil(i['len'] / (p['len_per_unit'] or 50))
                st.session_state.quote_items[p['name']] = st.session_state.quote_items.get(p['name'], 0) + qty
            for i in st.session_state.added_branch:
                p = i['obj']; qty = math.ceil(i['len'] / (p['len_per_unit'] or 50))
                st.session_state.quote_items[p['name']] = st.session_state.quote_items.get(p['name'], 0) + qty
            
            st.session_state.quote_step = 2
            st.rerun()

    # STEP 2
    elif st.session_state.quote_step == 2:
        st.subheader("2. 견적 확인")
        if st.button("뒤로"): st.session_state.quote_step = 1; st.rerun()
        
        rows = []
        name_map = {p['name']: p for p in st.session_state.db["products"]}
        
        for name, qty in st.session_state.quote_items.items():
            if name in name_map:
                p = name_map[name]
                rows.append({"품목": name, "규격": p['spec'], "수량": qty, "단가": p['price_cons']})
        
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
        
        c1, c2 = st.columns(2)
        with c1:
            ap = st.selectbox("부품 추가", st.session_state.db["products"], format_func=lambda x: f"{x['name']} ({x['spec']})")
            aq = st.number_input("수량", 1)
            if st.button("부품 추가"):
                st.session_state.quote_items[ap['name']] = st.session_state.quote_items.get(ap['name'], 0) + aq
                st.rerun()
        with c2:
            sn = st.text_input("비용 항목 (예: 배송비)")
            sa = st.number_input("금액", step=1000)
            if st.button("비용 추가"):
                st.session_state.services.append({"항목": sn, "금액": sa})
                st.rerun()
        
        if st.session_state.services: st.table(st.session_state.services)
        
        if st.button("최종 견적서 발행", type="primary"):
            st.session_state.quote_step = 3
            st.rerun()

    # STEP 3
    elif st.session_state.quote_step == 3:
        st.subheader("3. 최종 견적서")
        
        with st.container(border=True):
            c1, c2 = st.columns(2)
            rn = c1.text_input("수신처(현장명)", value=qn)
            rc = c1.text_input("담당자")
            rp = c2.text_input("연락처")
            ra = c2.text_input("주소")
            recipient = {"name": rn, "contact": rc, "phone": rp, "addr": ra}

        final_rows = []
        name_map = {p['name']: p for p in st.session_state.db["products"]}
        
        for name, qty in st.session_state.quote_items.items():
            if name in name_map:
                p = name_map[name]
                final_rows.append({
                    "품목": name, "규격": p['spec'], "코드": p['code'], "단위": p['unit'],
                    "수량": qty, "price_1": p['price_cons'], "image_data": p.get('image')
                })
        
        st.markdown("##### 견적 내용")
        st.dataframe(pd.DataFrame(final_rows)[["품목", "규격", "수량", "price_1"]], use_container_width=True, hide_index=True)
        if st.session_state.services:
            st.write("추가 비용:", st.session_state.services)

        if st.button("📄 PDF 다운로드 생성"):
            pdf_bytes = create_pdf_final(final_rows, st.session_state.services, {"date": datetime.datetime.now().strftime("%Y-%m-%d")}, recipient)
            st.download_button("⬇️ 다운로드 클릭", pdf_bytes, file_name=f"견적서_{qn}.pdf", mime="application/pdf")
        
        if st.button("처음으로"):
            st.session_state.quote_step = 1; st.session_state.quote_items = {}; st.session_state.services = []; st.session_state.added_main = []; st.session_state.added_branch = []
            st.rerun()

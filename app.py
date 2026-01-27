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
from fpdf import FPDF
from PIL import Image

# 구글 라이브러리
import gspread
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload, MediaIoBaseDownload

# ==========================================
# [0] 기본 설정 (반드시 맨 위)
# ==========================================
st.set_page_config(layout="wide", page_title="루퍼젯 프로 매니저 V10.0")

# ==========================================
# [1] 폰트 및 구글 연동
# ==========================================
FONT_FILE = "NanumGothic.ttf"
FONT_URL = "https://github.com/google/fonts/raw/main/ofl/nanumgothic/NanumGothic-Regular.ttf"

if not os.path.exists(FONT_FILE) or os.path.getsize(FONT_FILE) < 100:
    import urllib.request
    try: urllib.request.urlretrieve(FONT_URL, FONT_FILE)
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
    except: return None, None

gc, drive_service = get_google_services()
SHEET_NAME = "Looperget_DB"
DRIVE_FOLDER_NAME = "Looperget_Images"

# --- 드라이브 함수 ---
def get_or_create_drive_folder():
    if not drive_service: return None
    try:
        q = f"name='{DRIVE_FOLDER_NAME}' and mimeType='application/vnd.google-apps.folder' and trashed=false"
        res = drive_service.files().list(q=q, fields="files(id)").execute()
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
        # 이미지 압축 (속도 향상)
        img = Image.open(fh).convert('RGB')
        img.thumbnail((300, 300)) 
        buffer = io.BytesIO()
        img.save(buffer, format="JPEG", quality=70)
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

# --- 데이터 로드/저장 ---
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
        sh.worksheet("Config").append_row(["Key", "Value"]); sh.worksheet("Config").append_row(["password", "1234"])

    data = {"config": {"password": "1234"}, "products": [], "sets": {}}
    
    # Config
    try:
        cfg = sh.worksheet("Config").get_all_records()
        for c in cfg:
            if c.get('Key') == 'password': data['config']['password'] = str(c.get('Value', '1234'))
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
# 2. PDF 생성 (심플 & 강력 버전)
# ==========================================
class PDF(FPDF):
    def header(self):
        try: self.add_font('NanumGothic', '', FONT_FILE, uni=True); self.set_font('NanumGothic', '', 20)
        except: self.set_font('Arial', 'B', 20)
        self.cell(0, 15, '견 적 서 (Quotation)', 0, 1, 'C')
        self.ln(5)
    def footer(self):
        self.set_y(-15)
        try: self.set_font('NanumGothic', '', 8)
        except: self.set_font('Arial', 'I', 8)
        self.cell(0, 10, f'Page {self.page_no()}', 0, 0, 'C')

def generate_pdf(rows, services, meta_info):
    pdf = PDF()
    pdf.add_page()
    
    try: pdf.add_font('NanumGothic', '', FONT_FILE, uni=True); font='NanumGothic'
    except: font='Arial'
    pdf.set_font(font, '', 10)

    # 정보란
    pdf.set_fill_color(240,240,240)
    pdf.cell(95, 8, " 수신자 (Customer)", 1, 0, 'L', 1)
    pdf.cell(95, 8, " 공급자 (Supplier)", 1, 1, 'L', 1)
    
    # 수신자
    x = pdf.get_x(); y = pdf.get_y()
    r = meta_info['recipient']
    pdf.cell(25, 8, "상호", 1); pdf.cell(70, 8, f"{r.get('name','')}", 1, 1)
    pdf.cell(25, 8, "담당자", 1); pdf.cell(70, 8, f"{r.get('contact','')}", 1, 1)
    pdf.cell(25, 8, "연락처", 1); pdf.cell(70, 8, f"{r.get('phone','')}", 1, 1)
    pdf.cell(25, 8, "주소", 1); pdf.cell(70, 8, f"{r.get('addr','')}", 1, 1)
    
    # 공급자 (오른쪽으로 이동)
    pdf.set_xy(105, y)
    pdf.cell(25, 8, "등록번호", 1); pdf.cell(70, 8, "123-45-67890", 1, 1)
    pdf.set_x(105); pdf.cell(25, 8, "상호", 1); pdf.cell(70, 8, "(주)신진켐텍", 1, 1)
    pdf.set_x(105); pdf.cell(25, 8, "대표자", 1); pdf.cell(70, 8, "박형석", 1, 1)
    pdf.set_x(105); pdf.cell(25, 8, "전화", 1); pdf.cell(70, 8, "031-638-1809", 1, 1)

    pdf.ln(10)
    pdf.cell(0, 8, f"견적일자: {meta_info['date']} (유효기간: 15일)", 0, 1, 'R')
    pdf.ln(2)

    # 표 헤더
    pdf.set_fill_color(230, 230, 230)
    pdf.cell(10, 8, "No", 1, 0, 'C', 1)
    pdf.cell(15, 8, "IMG", 1, 0, 'C', 1)
    pdf.cell(55, 8, "품목명 / 규격", 1, 0, 'C', 1)
    pdf.cell(15, 8, "단위", 1, 0, 'C', 1)
    pdf.cell(15, 8, "수량", 1, 0, 'C', 1)
    pdf.cell(30, 8, "단가", 1, 0, 'C', 1)
    pdf.cell(30, 8, "금액", 1, 0, 'C', 1)
    pdf.cell(20, 8, "비고", 1, 1, 'C', 1)

    total = 0
    idx = 1
    
    for item in rows:
        if pdf.get_y() > 270: pdf.add_page()
        
        # 데이터 추출
        nm = f"{item['품목']}\n{item['규격']}"
        ut = item['단위']; qty = int(item['수량'])
        pr = int(item.get('price', 0))
        amt = qty * pr
        total += amt
        
        # 이미지 준비
        img_path = None
        if item.get('image_data'):
            try:
                b64 = get_image_from_drive(item['image_data'])
                if b64:
                    raw = base64.b64decode(b64.split(",")[1])
                    with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as tf:
                        tf.write(raw); img_path = tf.name
            except: pass

        # 행 그리기 (높이 16 고정)
        h = 16
        x_start = pdf.get_x(); y_start = pdf.get_y()
        
        pdf.cell(10, h, str(idx), 1, 0, 'C')
        
        # 이미지 칸
        pdf.cell(15, h, "", 1, 0)
        if img_path:
            pdf.image(img_path, x=x_start+11, y=y_start+1, w=13, h=14)
            os.unlink(img_path)
            
        # 텍스트 칸
        x_text = pdf.get_x()
        pdf.cell(55, h, "", 1, 0); 
        pdf.set_xy(x_text, y_start+3)
        pdf.set_font(font, '', 8)
        pdf.multi_cell(55, 4, nm, 0, 'L')
        pdf.set_font(font, '', 10)
        pdf.set_xy(x_text+55, y_start)
        
        pdf.cell(15, h, ut, 1, 0, 'C')
        pdf.cell(15, h, str(qty), 1, 0, 'C')
        pdf.cell(30, h, f"{pr:,}", 1, 0, 'R')
        pdf.cell(30, h, f"{amt:,}", 1, 0, 'R')
        pdf.cell(20, h, "", 1, 1)
        idx += 1

    # 추가 비용
    if services:
        pdf.ln(2)
        pdf.cell(0, 8, "[ 추가 비용 ]", 1, 1, 'L', 1)
        for s in services:
            pdf.cell(140, 8, s['항목'], 1)
            pdf.cell(50, 8, f"{s['금액']:,}", 1, 1, 'R')
            total += s['금액']

    # 총계
    pdf.ln(5)
    pdf.set_font(font, 'B', 12)
    pdf.cell(140, 10, "총 합 계 (VAT 별도)", 1, 0, 'C', 1)
    pdf.cell(50, 10, f"{total:,} 원", 1, 1, 'R', 1)
    
    pdf.ln(10)
    pdf.cell(0, 10, "주식회사 신진켐텍", 0, 1, 'C')

    return pdf.output(dest='S').encode('latin-1')


# ==========================================
# 3. 메인 앱
# ==========================================
if "db" not in st.session_state: st.session_state.db = load_data()

# 세션 초기화
for k in ["history", "quote_items", "services", "added_main", "added_branch", "quote_step", "recipient", "auth"]:
    if k not in st.session_state:
        st.session_state[k] = 1 if k == "quote_step" else ({} if k in ["quote_items","recipient","history"] else [])

with st.sidebar:
    st.header("🗂️ 견적 관리")
    qn = st.text_input("현장명")
    if st.button("저장"):
        st.session_state.history[qn] = {
            "items": st.session_state.quote_items, "services": st.session_state.services,
            "main": st.session_state.added_main, "branch": st.session_state.added_branch,
            "recipient": st.session_state.recipient
        }
        st.success("저장됨")
    
    if st.button("초기화"):
        for k in ["quote_items","services","added_main","added_branch","recipient"]: st.session_state[k] = [] if k!="quote_items" and k!="recipient" else {}
        st.session_state.quote_step = 1
        st.rerun()
    
    st.divider()
    mode = st.radio("모드", ["견적 작성", "관리자 모드"])

# --- 관리자 모드 ---
if mode == "관리자 모드":
    st.title("🛠 관리자 모드")
    
    if not st.session_state.auth:
        pw = st.text_input("비밀번호", type="password")
        if st.button("로그인"):
            if pw == st.session_state.db["config"]["password"]: st.session_state.auth = True; st.rerun()
            else: st.error("비밀번호 확인")
    else:
        if st.button("로그아웃"): st.session_state.auth = False; st.rerun()
        
        t1, t2, t3 = st.tabs(["제품 관리", "세트 관리", "설정"])
        
        with t1: # 제품
            if st.button("새로고침"): st.session_state.db = load_data(); st.rerun()
            df = pd.DataFrame(st.session_state.db["products"])
            st.dataframe(df, hide_index=True)
            
            # 엑셀 다운 (안전한 3줄 코딩)
            buf = io.BytesIO()
            with pd.ExcelWriter(buf, engine='xlsxwriter') as w: df.to_excel(w, index=False)
            st.download_button("엑셀 다운로드", buf.getvalue(), "data.xlsx")

            # 이미지 연결
            if st.button("드라이브 이미지 연결"):
                fmap = list_files_in_drive_folder()
                cnt = 0
                for p in st.session_state.db["products"]:
                    c = str(p.get("code","")).strip()
                    if c in fmap: p["image"] = fmap[c]; cnt+=1
                if cnt: save_products_to_sheet(st.session_state.db["products"]); st.success(f"{cnt}건 연결"); st.rerun()

        with t2: # 세트 (기능 복구)
            st.subheader("세트 관리")
            sets = st.session_state.db["sets"]
            cat = st.selectbox("분류", ["주배관세트", "가지관세트", "기타자재"])
            
            if cat in sets:
                st.table(pd.DataFrame([{"세트명":k, "부품수":len(v['recipe'])} for k,v in sets[cat].items()]))
            
            with st.expander("세트 추가/수정"):
                sn = st.text_input("세트명")
                if "tmpr" not in st.session_state: st.session_state.tmpr = {}
                
                c1,c2,c3 = st.columns([3,1,1])
                p_obj = c1.selectbox("부품", st.session_state.db["products"], format_func=lambda x: f"[{x['code']}] {x['name']}")
                pq = c2.number_input("수량", 1)
                if c3.button("담기"): st.session_state.tmpr[p_obj['name']] = pq
                
                st.write(st.session_state.tmpr)
                
                if st.button("세트 저장"):
                    if cat not in sets: sets[cat] = {}
                    sets[cat][sn] = {"recipe": st.session_state.tmpr, "image":"", "sub_cat":""}
                    save_all_data(st.session_state.db)
                    st.session_state.tmpr = {}
                    st.success("저장됨")
                    st.rerun()

        with t3: # 설정 (기능 복구)
            npw = st.text_input("새 비밀번호")
            if st.button("변경"):
                st.session_state.db["config"]["password"] = npw
                save_all_data(st.session_state.db)
                st.success("변경됨")

# --- 견적 모드 ---
else:
    st.title("💧 루퍼젯 프로 매니저")
    
    # 매핑용 딕셔너리
    pmap = {p['name']: p for p in st.session_state.db["products"]}
    cmap = {p['code']: p for p in st.session_state.db["products"]}

    # STEP 1
    if st.session_state.quote_step == 1:
        st.subheader("1. 물량 입력")
        sets = st.session_state.db["sets"]

        # 세트 입력 함수
        def input_sets(cat_key):
            if cat_key not in sets: return
            cols = st.columns(3)
            i = 0
            for name, info in sets[cat_key].items():
                with cols[i%3]:
                    q = st.number_input(f"{name}", 0, key=f"q_{name}")
                    if q > 0:
                        for pname, pqty in info['recipe'].items():
                            pcode = pmap.get(pname, {}).get('code')
                            if pcode: st.session_state.quote_items[pcode] = st.session_state.quote_items.get(pcode, 0) + pqty * q
                i+=1

        with st.expander("세트 입력 (주배관/가지관/기타)", True):
            st.markdown("**주배관 세트**"); input_sets("주배관세트")
            st.markdown("**가지관 세트**"); input_sets("가지관세트")
            st.markdown("**기타 자재**"); input_sets("기타자재")

        st.divider()
        # 파이프 입력
        c1, c2 = st.columns(2)
        prods = st.session_state.db["products"]
        mpl = [p for p in prods if p["category"] == "주배관"]
        bpl = [p for p in prods if p["category"] == "가지관"]
        
        with c1:
            st.markdown("##### 주배관 (길이 산출)")
            sm = st.selectbox("선택", mpl, format_func=lambda x: f"{x['name']} ({x['spec']})", key='sm')
            lm = st.number_input("길이(m)", step=1, key='lm')
            if st.button("추가", key='am'): st.session_state.added_main.append({"obj": sm, "len": lm})
            for i in st.session_state.added_main: st.text(f"{i['obj']['name']}: {i['len']}m")

        with c2:
            st.markdown("##### 가지관 (길이 산출)")
            sb = st.selectbox("선택", bpl, format_func=lambda x: f"{x['name']} ({x['spec']})", key='sb')
            lb = st.number_input("길이(m)", step=1, key='lb')
            if st.button("추가", key='ab'): st.session_state.added_branch.append({"obj": sb, "len": lb})
            for i in st.session_state.added_branch: st.text(f"{i['obj']['name']}: {i['len']}m")
        
        if st.button("다음 단계 (계산)", type="primary"):
            # 파이프 계산
            for x in st.session_state.added_main + st.session_state.added_branch:
                p = x['obj']; l = x['len']
                roll = p.get('len_per_unit', 50) or 50
                qty = math.ceil(l / roll)
                st.session_state.quote_items[p['code']] = st.session_state.quote_items.get(p['code'], 0) + qty
            st.session_state.quote_step = 2
            st.rerun()

    # STEP 2
    elif st.session_state.quote_step == 2:
        st.subheader("2. 견적 확인")
        if st.button("뒤로"): st.session_state.quote_step = 1; st.rerun()
        
        # 목록 표시
        rows = []
        for c, q in st.session_state.quote_items.items():
            if c in cmap:
                p = cmap[c]
                rows.append({"품목": p['name'], "규격": p['spec'], "수량": q, "단가": p['price_cons']})
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

        # 추가 입력
        c1, c2 = st.columns(2)
        with c1:
            ap = st.selectbox("부품 추가", st.session_state.db["products"], format_func=lambda x: f"[{x['code']}] {x['name']} ({x['spec']})")
            aq = st.number_input("수량", 1, key='aq')
            if st.button("부품 추가"):
                st.session_state.quote_items[ap['code']] = st.session_state.quote_items.get(ap['code'], 0) + aq
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
        
        # 수신자
        with st.container(border=True):
            c1, c2 = st.columns(2)
            rn = c1.text_input("수신처(현장명)", value=qn)
            rc = c1.text_input("담당자")
            rp = c2.text_input("연락처")
            ra = c2.text_input("주소")
            st.session_state.recipient = {"name": rn, "contact": rc, "phone": rp, "addr": ra}

        # 데이터 취합
        final_rows = []
        for c, q in st.session_state.quote_items.items():
            if c in cmap:
                p = cmap[c]
                final_rows.append({
                    "품목": p['name'], "규격": p['spec'], "코드": p['code'], "단위": p['unit'],
                    "수량": q, "price_1": p['price_cons'], "image_data": p.get('image'), "order_no": p['order_no']
                })
        final_rows = sorted(final_rows, key=lambda x: x['order_no'])
        
        # 화면 표시
        st.markdown("##### 견적 상세")
        st.dataframe(pd.DataFrame(final_rows)[["품목", "규격", "수량", "단위", "price_1"]], use_container_width=True, hide_index=True)
        if st.session_state.services: st.write("추가 비용:", st.session_state.services)

        # PDF 생성
        if st.button("📄 PDF 다운로드 생성", type="primary"):
            with st.spinner("생성 중..."):
                pdf_data = generate_pdf(final_rows, st.session_state.services, {"date": datetime.datetime.now().strftime("%Y-%m-%d")}, st.session_state.recipient)
                if pdf_data:
                    st.download_button("⬇️ 다운로드 클릭", pdf_data, file_name=f"견적서_{qn}.pdf", mime="application/pdf")
                else:
                    st.error("PDF 생성 실패")
        
        if st.button("처음으로"):
            st.session_state.quote_step = 1; st.session_state.quote_items = {}; st.session_state.services = []; st.session_state.added_main = []; st.session_state.added_branch = []
            st.rerun()

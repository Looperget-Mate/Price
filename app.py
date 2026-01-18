import streamlit as st
import pandas as pd
import math
import os
import json
import io
import base64
import tempfile
import urllib.request  # 폰트 다운로드용
from PIL import Image
from fpdf import FPDF

# ==========================================
# 1. 유틸리티 (폰트 자동설치 & PDF)
# ==========================================
DATA_FILE = "looperget_data.json"
FONT_FILE = "NanumGothic.ttf"
FONT_URL = "https://github.com/google/fonts/raw/main/ofl/nanumgothic/NanumGothic-Regular.ttf"

# 폰트 파일이 없으면 다운로드
if not os.path.exists(FONT_FILE):
    try:
        urllib.request.urlretrieve(FONT_URL, FONT_FILE)
    except Exception:
        pass # 다운로드 실패 시 영문 기본 폰트 사용

def process_image(uploaded_file):
    try:
        image = Image.open(uploaded_file)
        if image.mode != 'RGB':
            image = image.convert('RGB')
        image.thumbnail((300, 225)) 
        buffer = io.BytesIO()
        image.save(buffer, format="JPEG")
        img_str = base64.b64encode(buffer.getvalue()).decode()
        return f"data:image/jpeg;base64,{img_str}"
    except Exception as e:
        st.error(f"이미지 처리 오류: {e}")
        return None

class PDF(FPDF):
    def header(self):
        if os.path.exists(FONT_FILE):
            self.add_font('NanumGothic', '', FONT_FILE, uni=True)
            self.set_font('NanumGothic', '', 20)
        else:
            self.set_font('Helvetica', 'B', 20)
        self.cell(0, 15, '견 적 서 (Quotation)', align='C', new_x="LMARGIN", new_y="NEXT")
        self.ln(5)

    def footer(self):
        self.set_y(-15)
        if os.path.exists(FONT_FILE):
            self.set_font('NanumGothic', '', 8)
        else:
            self.set_font('Helvetica', 'I', 8)
        self.cell(0, 10, f'Page {self.page_no()}', align='C')

def create_pdf(quote_items, service_items, db_products):
    pdf = PDF()
    pdf.add_page()
    
    has_font = os.path.exists(FONT_FILE)
    if has_font:
        pdf.add_font('NanumGothic', '', FONT_FILE, uni=True)
        pdf.set_font('NanumGothic', '', 10)
    else:
        pdf.set_font('Helvetica', '', 10)
        st.warning("⚠️ 한글 폰트가 없어 PDF 글자가 깨질 수 있습니다.")

    # 헤더
    pdf.set_fill_color(240, 240, 240)
    pdf.cell(25, 10, 'IMG', border=1, align='C', fill=True)
    pdf.cell(60, 10, '품목명 (Item)', border=1, align='C', fill=True)
    pdf.cell(30, 10, '규격 (Spec)', border=1, align='C', fill=True)
    pdf.cell(15, 10, '수량', border=1, align='C', fill=True)
    pdf.cell(30, 10, '단가', border=1, align='C', fill=True)
    pdf.cell(30, 10, '금액', border=1, align='C', fill=True, new_x="LMARGIN", new_y="NEXT")

    total_mat_price = 0
    p_map = {p["name"]: p for p in db_products}

    for name, qty in quote_items.items():
        info = p_map.get(name, {})
        price = info.get("price_cons", 0)
        amt = price * qty
        total_mat_price += amt
        spec = info.get("spec", "-")
        
        row_height = 15
        
        # 이미지
        img_data = info.get("image")
        x = pdf.get_x()
        y = pdf.get_y()
        
        pdf.cell(25, row_height, "", border=1)
        if img_data:
            try:
                header, encoded = img_data.split(",", 1)
                data = base64.b64decode(encoded)
                with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as tmp:
                    tmp.write(data)
                    tmp_path = tmp.name
                pdf.image(tmp_path, x=x+2, y=y+2, w=21, h=11)
                os.unlink(tmp_path)
            except: pass

        pdf.set_xy(x + 25, y)
        pdf.cell(60, row_height, name, border=1, align='L')
        pdf.cell(30, row_height, spec, border=1, align='C')
        pdf.cell(15, row_height, str(qty), border=1, align='C')
        pdf.cell(30, row_height, f"{price:,}", border=1, align='R')
        pdf.cell(30, row_height, f"{amt:,}", border=1, align='R', new_x="LMARGIN", new_y="NEXT")

    # 서비스 비용
    total_svc_price = 0
    if service_items:
        pdf.ln(5)
        pdf.set_fill_color(255, 255, 200)
        pdf.cell(190, 8, " [ 추가 비용 ] ", border=1, align='L', fill=True, new_x="LMARGIN", new_y="NEXT")
        for svc in service_items:
            s_name = svc['항목']
            s_price = svc['금액']
            total_svc_price += s_price
            pdf.cell(130, 8, s_name, border=1, align='L')
            pdf.cell(60, 8, f"{s_price:,} 원", border=1, align='R', new_x="LMARGIN", new_y="NEXT")

    grand_total = total_mat_price + total_svc_price
    pdf.ln(5)
    pdf.set_font('NanumGothic', '', 12) if has_font else pdf.set_font('Helvetica', 'B', 12)
    pdf.cell(130, 12, "총 합계 (Total)", border=1, align='R')
    pdf.set_text_color(255, 0, 0)
    pdf.cell(60, 12, f"{grand_total:,} 원", border=1, align='R', new_x="LMARGIN", new_y="NEXT")
    
    return pdf.output(dest='S').encode('latin-1')

# ==========================================
# 2. 데이터 관리 및 메인 로직
# ==========================================
DEFAULT_DATA = {
    "products": [
        {"code": "P001", "category": "부속", "name": "cccT", "spec": "50mm", "unit": "EA", "len_per_unit": 0, "price_buy": 5000, "price_d1": 6000, "price_d2": 7000, "price_agy": 8000, "price_cons": 10000, "image": None},
        {"code": "PIPE01", "category": "주배관", "name": "PVC호스", "spec": "50mm", "unit": "Roll", "len_per_unit": 50, "price_buy": 50000, "price_d1": 60000, "price_d2": 70000, "price_agy": 80000, "price_cons": 100000, "image": None},
    ],
    "sets": {
        "주배관세트": {
            "T분기 A타입": {"recipe": {"cccT": 1}, "image": None}
        }
    }
}
COL_MAP = {"품목코드": "code", "카테고리": "category", "제품명": "name", "규격": "spec", "단위": "unit", "1롤길이(m)": "len_per_unit", "매입단가": "price_buy", "총판가1": "price_d1", "총판가2": "price_d2", "대리점가": "price_agy", "소비자가": "price_cons", "이미지데이터": "image"}
REV_COL_MAP = {v: k for k, v in COL_MAP.items()}

def load_data():
    if not os.path.exists(DATA_FILE): return DEFAULT_DATA
    with open(DATA_FILE, "r", encoding="utf-8") as f: return json.load(f)

def save_data(data):
    with open(DATA_FILE, "w", encoding="utf-8") as f: json.dump(data, f, ensure_ascii=False, indent=4)

if "db" not in st.session_state: st.session_state.db = load_data()
if "temp_set_recipe" not in st.session_state: st.session_state.temp_set_recipe = {}

# UI 시작
st.set_page_config(layout="wide", page_title="루퍼젯 프로 매니저")
st.title("💧 루퍼젯 프로 매니저 V6.1")
mode = st.sidebar.radio("모드", ["견적 모드", "관리자 모드"])

if mode == "관리자 모드":
    st.header("🛠 데이터 관리")
    t1, t2 = st.tabs(["품목 관리", "세트 관리"])
    with t1:
        st.info("이미지는 아래에서 등록")
        c1, c2, c3 = st.columns([2, 2, 1])
        pn = [p["name"] for p in st.session_state.db["products"]]
        with c1: tp = st.selectbox("품목", pn)
        with c2: ifile = st.file_uploader("이미지", ["png", "jpg"], key="pimg")
        with c3:
            st.write(""); st.write("")
            if st.button("이미지저장") and ifile:
                b64 = process_image(ifile)
                for p in st.session_state.db["products"]:
                    if p["name"] == tp: p["image"] = b64
                save_data(st.session_state.db); st.success("저장됨"); st.rerun()
        st.divider()
        with st.expander("엑셀 관리"):
            ec1, ec2 = st.columns(2)
            with ec1:
                df = pd.DataFrame(st.session_state.db["products"]).rename(columns=REV_COL_MAP)
                if "이미지데이터" in df.columns: df["이미지데이터"] = "APP"
                buf = io.BytesIO()
                with pd.ExcelWriter(buf, engine='xlsxwriter') as w: df.to_excel(w, index=False)
                st.download_button("다운로드", buf.getvalue(), "products.xlsx")
            with ec2:
                uf = st.file_uploader("업로드", ["xlsx"])
                if uf and st.button("덮어쓰기"):
                    ndf = pd.read_excel(uf).rename(columns=COL_MAP).fillna(0)
                    oimg = {p["name"]: p.get("image") for p in st.session_state.db["products"]}
                    nrec = ndf.to_dict('records')
                    for p in nrec: 
                        if p["name"] in oimg: p["image"] = oimg[p["name"]]
                    st.session_state.db["products"] = nrec
                    save_data(st.session_state.db); st.success("완료"); st.rerun()
        # 에디터
        dfp = pd.DataFrame(st.session_state.db["products"])
        vcols = [c for c in dfp.columns if c != "image"]
        edf = st.data_editor(dfp[vcols].rename(columns=REV_COL_MAP), use_container_width=True, num_rows="dynamic")
        if st.button("리스트 저장"):
            upd = edf.rename(columns=COL_MAP).to_dict("records")
            oimg = {p["name"]: p.get("image") for p in st.session_state.db["products"]}
            for p in upd:
                if p["name"] in oimg: p["image"] = oimg[p["name"]]
            st.session_state.db["products"] = upd
            save_data(st.session_state.db); st.success("저장"); st.rerun()

    with t2:
        mt = st.radio("작업", ["신규", "수정/삭제"], horizontal=True)
        cat = st.selectbox("분류", ["주배관세트", "가지관세트", "기타자재"])
        pl = [p["name"] for p in st.session_state.db["products"]]
        
        if mt == "신규":
            nn = st.text_input("세트명")
            ni = st.file_uploader("세트이미지", key="nsi")
            c1, c2, c3 = st.columns([3,2,1])
            with c1: sp = st.selectbox("부품", pl, key="nsp")
            with c2: sq = st.number_input("수량", 1, key="nsq")
            with c3: 
                if st.button("담기"): st.session_state.temp_set_recipe[sp] = sq
            st.write(st.session_state.temp_set_recipe)
            if st.button("저장"):
                im = process_image(ni) if ni else None
                if cat not in st.session_state.db["sets"]: st.session_state.db["sets"][cat] = {}
                st.session_state.db["sets"][cat][nn] = {"recipe": st.session_state.temp_set_recipe, "image": im}
                save_data(st.session_state.db); st.session_state.temp_set_recipe = {}; st.rerun()
        else:
            cset = st.session_state.db["sets"].get(cat, {})
            if cset:
                tg = st.selectbox("선택", list(cset.keys()))
                if st.button("불러오기"):
                    st.session_state.temp_set_recipe = cset[tg].get("recipe", cset[tg]).copy()
                    st.toast("로드됨")
                ci = cset[tg].get("image") if isinstance(cset[tg], dict) else None
                if ci: st.image(ci, width=100)
                ei = st.file_uploader("이미지변경")
                
                for k,v in list(st.session_state.temp_set_recipe.items()):
                    c1, c2, c3 = st.columns([3,1,1])
                    c1.text(k); c2.text(v)
                    if c3.button("X", key=f"d{k}"): del st.session_state.temp_set_recipe[k]; st.rerun()
                c1, c2, c3 = st.columns([3,2,1])
                with c1: ap = st.selectbox("추가", pl, key="esp")
                with c2: aq = st.number_input("수량", 1, key="esq")
                with c3: 
                    if st.button("담기", key="esa"): st.session_state.temp_set_recipe[ap] = aq; st.rerun()
                if st.button("수정저장"):
                    fi = process_image(ei) if ei else ci
                    st.session_state.db["sets"][cat][tg] = {"recipe": st.session_state.temp_set_recipe, "image": fi}
                    save_data(st.session_state.db); st.session_state.temp_set_recipe = {}; st.rerun()
                if st.button("삭제"):
                    del st.session_state.db["sets"][cat][tg]
                    save_data(st.session_state.db); st.rerun()

else: # 견적 모드
    if "quote_step" not in st.session_state:
        st.session_state.quote_step = 1; st.session_state.quote_items = {}; st.session_state.services = []

    if st.session_state.quote_step == 1:
        st.subheader("STEP 1. 물량")
        
        def r_inp(d, k):
            if not d: return {}
            r = {}
            cols = st.columns(4)
            for i, (n, v) in enumerate(d.items()):
                with cols[i%4]:
                    img = v.get("image") if isinstance(v, dict) else None
                    if img: st.image(img, use_container_width=True)
                    else: st.markdown("<div style='height:80px;background:#eee'></div>", unsafe_allow_html=True)
                    r[n] = st.number_input(n, 0, key=f"{k}_{n}")
            return r

        sets = st.session_state.db.get("sets", {})
        with st.expander("주배관", True): im = r_inp(sets.get("주배관세트"), "m")
        with st.expander("가지관"): ib = r_inp(sets.get("가지관세트"), "b")
        with st.expander("기타"): ie = r_inp(sets.get("기타자재"), "e")
        
        st.write("배관길이")
        mpl = [p for p in st.session_state.db["products"] if p["category"] == "주배관"]
        bpl = [p for p in st.session_state.db["products"] if p["category"] == "가지관"]
        c1, c2 = st.columns(2)
        with c1: 
            sm = st.selectbox("주배관", [p["name"] for p in mpl]) if mpl else None
            lm = st.number_input("길이m", 0, key="lm")
        with c2: 
            sb = st.selectbox("가지관", [p["name"] for p in bpl]) if bpl else None
            lb = st.number_input("길이m", 0, key="lb")
            
        if st.button("계산"):
            res = {}
            def ex(ins, db):
                for k,v in ins.items():
                    if v>0:
                        rec = db[k].get("recipe", db[k])
                        for p, q in rec.items(): res[p] = res.get(p, 0) + q*v
            ex(im, sets.get("주배관세트")); ex(ib, sets.get("가지관세트")); ex(ie, sets.get("기타자재"))
            
            def cr(n, l, pl):
                if l>0 and n:
                    pi = next((x for x in pl if x["name"]==n), None)
                    if pi and pi["len_per_unit"]: res[n] = res.get(n, 0) + math.ceil(l/pi["len_per_unit"])
            cr(sm, lm, mpl); cr(sb, lb, bpl)
            st.session_state.quote_items = res; st.session_state.quote_step = 2; st.rerun()

    elif st.session_state.quote_step == 2:
        st.subheader("STEP 2. 검토")
        # 데이터프레임 표시 (생략 - V5.0 동일)
        rows = []
        pdb = {p["name"]: p for p in st.session_state.db["products"]}
        for n, q in st.session_state.quote_items.items():
            inf = pdb.get(n, {})
            rows.append({"품목": n, "수량": q, "단가": inf.get("price_cons", 0), "합계": inf.get("price_cons", 0)*q})
        st.dataframe(pd.DataFrame(rows), use_container_width=True)
        
        c1, c2 = st.columns(2)
        with c1:
            ap = st.selectbox("품목추가", list(pdb.keys()))
            aq = st.number_input("수량", 1)
            if st.button("추가"): st.session_state.quote_items[ap] = st.session_state.quote_items.get(ap, 0) + aq; st.rerun()
        with c2:
            stype = st.selectbox("비용", ["배송비", "용역비", "기타"])
            sn = st.text_input("내용") if stype=="기타" else stype
            sp = st.number_input("금액", 0, step=1000)
            if st.button("비용추가"): st.session_state.services.append({"항목": sn, "금액": sp}); st.rerun()
        
        if st.session_state.services: st.table(st.session_state.services)
        if st.button("최종확정"): st.session_state.quote_step = 3; st.rerun()

    elif st.session_state.quote_step == 3:
        st.header("견적 완료")
        # PDF 다운로드
        pdf_byte = create_pdf(st.session_state.quote_items, st.session_state.services, st.session_state.db["products"])
        st.download_button("📥 PDF 다운로드", pdf_byte, "quotation.pdf", "application/pdf")
        if st.button("처음으로"):
            st.session_state.quote_step = 1; st.session_state.quote_items = {}; st.session_state.services = []; st.rerun()

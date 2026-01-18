import streamlit as st
import pandas as pd
import math
import os
import json
import io
import base64
import tempfile
import urllib.request
import datetime
from PIL import Image
from fpdf import FPDF

# ==========================================
# 1. 파일 및 유틸리티 설정
# ==========================================
DATA_FILE = "looperget_data.json"       
HISTORY_FILE = "looperget_history.json" 
FONT_FILE = "NanumGothic.ttf"
FONT_URL = "https://github.com/google/fonts/raw/main/ofl/nanumgothic/NanumGothic-Regular.ttf"

# 폰트 자동 다운로드
if not os.path.exists(FONT_FILE):
    try:
        urllib.request.urlretrieve(FONT_URL, FONT_FILE)
    except: pass 

# 데이터 로드/저장
def load_json(file_path, default_data):
    if not os.path.exists(file_path): return default_data
    with open(file_path, "r", encoding="utf-8") as f: return json.load(f)

def save_json(file_path, data):
    with open(file_path, "w", encoding="utf-8") as f: json.dump(data, f, ensure_ascii=False, indent=4)

# 초기 데이터
DEFAULT_DATA = {
    "products": [
        {"code": "P001", "category": "부속", "name": "cccT", "spec": "50mm", "unit": "EA", "len_per_unit": 0, "price_buy": 5000, "price_d1": 6000, "price_d2": 7000, "price_agy": 8000, "price_cons": 10000, "image": None},
        {"code": "PIPE01", "category": "주배관", "name": "PVC호스", "spec": "50mm", "unit": "Roll", "len_per_unit": 50, "price_buy": 50000, "price_d1": 60000, "price_d2": 70000, "price_agy": 80000, "price_cons": 100000, "image": None},
    ],
    "sets": {"주배관세트": {}, "가지관세트": {}, "기타자재": {}}
}

# 이미지 처리
def process_image(uploaded_file):
    try:
        image = Image.open(uploaded_file).convert('RGB')
        image.thumbnail((300, 225)) 
        buffer = io.BytesIO()
        image.save(buffer, format="JPEG")
        return f"data:image/jpeg;base64,{base64.b64encode(buffer.getvalue()).decode()}"
    except: return None

# PDF 클래스
class PDF(FPDF):
    def header(self):
        if os.path.exists(FONT_FILE):
            self.add_font('NanumGothic', '', FONT_FILE, uni=True)
            self.set_font('NanumGothic', '', 20) 
        else: self.set_font('Helvetica', 'B', 20)
        self.cell(0, 15, '견 적 서 (Quotation)', align='C', new_x="LMARGIN", new_y="NEXT")
        self.ln(5)

    def footer(self):
        self.set_y(-15)
        self.set_font('NanumGothic', '', 8) if os.path.exists(FONT_FILE) else self.set_font('Helvetica', 'I', 8)
        self.cell(0, 10, f'Page {self.page_no()}', align='C')

# [V7.2 수정] PDF 생성 함수가 'DB'가 아니라 '화면에서 수정된 데이터(final_data_list)'를 받도록 변경
def create_pdf(final_data_list, service_items, quote_name=""):
    pdf = PDF()
    pdf.add_page()
    has_font = os.path.exists(FONT_FILE)
    
    if has_font:
        pdf.add_font('NanumGothic', '', FONT_FILE, uni=True)
        pdf.set_font('NanumGothic', '', 10)
    else: pdf.set_font('Helvetica', '', 10)

    # 견적명
    if quote_name:
        pdf.set_font('NanumGothic', '', 12) if has_font else pdf.set_font('Helvetica', 'B', 12)
        pdf.cell(0, 10, f"현장명 : {quote_name}", new_x="LMARGIN", new_y="NEXT")
        pdf.ln(2)
        pdf.set_font('NanumGothic', '', 10) if has_font else pdf.set_font('Helvetica', '', 10)

    # 테이블 헤더
    pdf.set_fill_color(240, 240, 240)
    headers = [("IMG", 25), ("품목명", 60), ("규격", 30), ("수량", 15), ("단가", 30), ("금액", 30)]
    for txt, w in headers: pdf.cell(w, 10, txt, border=1, align='C', fill=True)
    pdf.ln()

    total_mat = 0

    # [V7.2] 수정된 데이터 리스트 순회
    for item in final_data_list:
        name = item.get("품목", "")
        spec = item.get("규격", "-")
        qty = int(item.get("수량", 0))
        price = int(item.get("단가", 0))
        img_data = item.get("image_data", None) # 이미지 데이터 별도 전달
        
        amt = price * qty
        total_mat += amt
        
        h = 15
        x, y = pdf.get_x(), pdf.get_y()
        
        # 이미지
        pdf.cell(25, h, "", border=1)
        if img_data:
            try:
                data = base64.b64decode(img_data.split(",", 1)[1])
                with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as tmp:
                    tmp.write(data); tmp_path = tmp.name
                pdf.image(tmp_path, x=x+2, y=y+2, w=21, h=11)
                os.unlink(tmp_path)
            except: pass
        
        pdf.set_xy(x+25, y)
        pdf.cell(60, h, name, border=1)
        pdf.cell(30, h, spec, border=1, align='C')
        pdf.cell(15, h, str(qty), border=1, align='C')
        pdf.cell(30, h, f"{price:,}", border=1, align='R')
        pdf.cell(30, h, f"{amt:,}", border=1, align='R')
        pdf.ln()

    # 서비스 비용
    total_svc = 0
    if service_items:
        pdf.ln(5)
        pdf.set_fill_color(255, 255, 200)
        pdf.cell(190, 8, " [ 추가 비용 ] ", border=1, fill=True); pdf.ln()
        for s in service_items:
            total_svc += s['금액']
            pdf.cell(130, 8, s['항목'], border=1)
            pdf.cell(60, 8, f"{s['금액']:,} 원", border=1, align='R'); pdf.ln()

    # 총계 (VAT 포함 표기)
    grand_total = total_mat + total_svc
    pdf.ln(5)
    pdf.set_font('NanumGothic', '', 12) if has_font else pdf.set_font('Helvetica', 'B', 12)
    pdf.cell(130, 12, "총 합계 (Total / VAT Incl.)", border=1, align='R')
    pdf.set_text_color(255, 0, 0)
    pdf.cell(60, 12, f"{grand_total:,} 원", border=1, align='R')
    
    return bytes(pdf.output())

# ==========================================
# 2. 메인 앱 로직
# ==========================================

if "db" not in st.session_state: st.session_state.db = load_json(DATA_FILE, DEFAULT_DATA)
if "history" not in st.session_state: st.session_state.history = load_json(HISTORY_FILE, {})
if "quote_step" not in st.session_state: st.session_state.quote_step = 1
if "quote_items" not in st.session_state: st.session_state.quote_items = {}
if "services" not in st.session_state: st.session_state.services = []
if "temp_set_recipe" not in st.session_state: st.session_state.temp_set_recipe = {}
if "current_quote_name" not in st.session_state: st.session_state.current_quote_name = ""

st.set_page_config(layout="wide", page_title="루퍼젯 프로 매니저")
st.title("💧 루퍼젯 프로 매니저 V7.2")

# 사이드바
with st.sidebar:
    st.header("🗂️ 견적 관리")
    st.markdown("##### 1. 저장 / 신규")
    q_name_input = st.text_input("현장명", value=st.session_state.current_quote_name)
    
    c1, c2 = st.columns(2)
    with c1:
        if st.button("💾 저장"):
            if not q_name_input: st.error("이름 입력 필요")
            elif not st.session_state.quote_items: st.warning("내용 없음")
            else:
                st.session_state.history[q_name_input] = {
                    "date": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
                    "items": st.session_state.quote_items,
                    "services": st.session_state.services,
                    "step": st.session_state.quote_step
                }
                save_json(HISTORY_FILE, st.session_state.history)
                st.session_state.current_quote_name = q_name_input
                st.success("저장됨")
    with c2:
        if st.button("✨ 초기화"):
            st.session_state.quote_items = {}; st.session_state.services = []; st.session_state.quote_step = 1; st.session_state.current_quote_name = ""; st.rerun()

    st.divider()
    st.markdown("##### 2. 불러오기")
    h_names = list(st.session_state.history.keys())[::-1]
    if h_names:
        sel_h = st.selectbox("목록", h_names)
        cl1, cl2 = st.columns(2)
        with cl1:
            if st.button("📂 로드"):
                d = st.session_state.history[sel_h]
                st.session_state.quote_items = d["items"]
                st.session_state.services = d["services"]
                st.session_state.quote_step = d.get("step", 2)
                st.session_state.current_quote_name = sel_h
                st.success("로드됨"); st.rerun()
        with cl2:
             if st.button("🗑️ 삭제"):
                 del st.session_state.history[sel_h]
                 save_json(HISTORY_FILE, st.session_state.history); st.rerun()
    
    st.divider()
    mode = st.radio("모드", ["견적 작성", "관리자 모드"])

COL_MAP = {"품목코드": "code", "카테고리": "category", "제품명": "name", "규격": "spec", "단위": "unit", "1롤길이(m)": "len_per_unit", "매입단가": "price_buy", "총판가1": "price_d1", "총판가2": "price_d2", "대리점가": "price_agy", "소비자가": "price_cons", "이미지데이터": "image"}
REV_COL_MAP = {v: k for k, v in COL_MAP.items()}

if mode == "관리자 모드":
    st.header("🛠 데이터 관리")
    t1, t2 = st.tabs(["품목 관리", "세트 관리"])
    
    with t1:
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
                save_json(DATA_FILE, st.session_state.db); st.success("저장됨"); st.rerun()
        
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
                    save_json(DATA_FILE, st.session_state.db); st.success("완료"); st.rerun()
        
        dfp = pd.DataFrame(st.session_state.db["products"])
        vcols = [c for c in dfp.columns if c != "image"]
        edf = st.data_editor(dfp[vcols].rename(columns=REV_COL_MAP), use_container_width=True, num_rows="dynamic")
        if st.button("리스트 저장"):
            upd = edf.rename(columns=COL_MAP).to_dict("records")
            oimg = {p["name"]: p.get("image") for p in st.session_state.db["products"]}
            for p in upd:
                if p["name"] in oimg: p["image"] = oimg[p["name"]]
            st.session_state.db["products"] = upd
            save_json(DATA_FILE, st.session_state.db); st.success("저장"); st.rerun()

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
                save_json(DATA_FILE, st.session_state.db); st.session_state.temp_set_recipe = {}; st.rerun()
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
                    save_json(DATA_FILE, st.session_state.db); st.session_state.temp_set_recipe = {}; st.rerun()
                if st.button("삭제"):
                    del st.session_state.db["sets"][cat][tg]
                    save_json(DATA_FILE, st.session_state.db); st.rerun()

else: # 견적 모드
    st.markdown(f"### 📝 작성 중: **{st.session_state.current_quote_name if st.session_state.current_quote_name else '(제목 없음)'}**")

    if st.session_state.quote_step == 1:
        st.subheader("STEP 1. 물량 입력")
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
        with st.expander("1. 주배관 세트", True): im = r_inp(sets.get("주배관세트"), "m")
        with st.expander("2. 가지관 세트"): ib = r_inp(sets.get("가지관세트"), "b")
        with st.expander("3. 기타 자재"): ie = r_inp(sets.get("기타자재"), "e")
        
        st.markdown("#### 4. 배관 길이")
        mpl = [p for p in st.session_state.db["products"] if p["category"] == "주배관"]
        bpl = [p for p in st.session_state.db["products"] if p["category"] == "가지관"]
        c1, c2 = st.columns(2)
        with c1: 
            sm = st.selectbox("주배관", [p["name"] for p in mpl]) if mpl else None
            lm = st.number_input("길이m", 0, key="lm")
        with c2: 
            sb = st.selectbox("가지관", [p["name"] for p in bpl]) if bpl else None
            lb = st.number_input("길이m", 0, key="lb")
            
        if st.button("계산하기 (STEP 2)"):
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
        st.subheader("STEP 2. 검토 및 비용")
        view = st.radio("단가 보기", ["소비자가", "매입가", "총판1", "총판2", "대리점"], horizontal=True)
        key_map = {"매입가":("price_buy","매입"), "총판1":("price_d1","총판1"), "총판2":("price_d2","총판2"), "대리점":("price_agy","대리점")}
        
        rows = []
        pdb = {p["name"]: p for p in st.session_state.db["products"]}
        for n, q in st.session_state.quote_items.items():
            inf = pdb.get(n, {})
            cpr = inf.get("price_cons", 0)
            row = {"IMG": inf.get("image"), "품목": n, "규격": inf.get("spec"), "수량": q, "소비자가": cpr, "합계": cpr*q}
            if view != "소비자가":
                k, l = key_map[view]
                pr = inf.get(k, 0)
                row[f"{l}단가"] = pr; row[f"{l}합계"] = pr*q
                row["이익"] = row["합계"] - row[f"{l}합계"]
                row["율(%)"] = (row["이익"]/row["합계"]*100) if row["합계"] else 0
            rows.append(row)
        
        df = pd.DataFrame(rows)
        disp = ["IMG", "품목", "규격", "수량"]
        if view == "소비자가": disp += ["소비자가", "합계"]
        else: 
            l = key_map[view][1]
            disp += [f"{l}단가", f"{l}합계", "소비자가", "합계", "이익", "율(%)"]

        st.dataframe(df[disp], use_container_width=True, hide_index=True, column_config={"IMG": st.column_config.ImageColumn("이미지", width="small"), "율(%)": st.column_config.NumberColumn(format="%.1f%%"), "소비자가": st.column_config.NumberColumn(format="%d"), "합계": st.column_config.NumberColumn(format="%d")})
        
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
        
        if st.session_state.services: 
            st.table(st.session_state.services)
            if st.button("마지막 비용 삭제"): st.session_state.services.pop(); st.rerun()

        if st.button("최종 확정 (STEP 3)"): st.session_state.quote_step = 3; st.rerun()

    elif st.session_state.quote_step == 3:
        st.header("🏁 최종 견적 완료 (수정 가능)")
        
        if not st.session_state.current_quote_name: st.warning("⚠️ 왼쪽 사이드바에서 [저장]을 눌러주세요!")

        st.info("💡 아래 표의 '수량'과 '단가'를 클릭하여 수정할 수 있습니다.")

        # [V7.2] DB에서 데이터를 가져오되, DataFrame으로 변환하여 'Editable'하게 만듦
        pdb = {p["name"]: p for p in st.session_state.db["products"]}
        fdata = []
        for n, q in st.session_state.quote_items.items():
            inf = pdb.get(n, {})
            # 이미지 데이터(Base64)는 숨겨서 넘겨야 함 (data_editor에선 이미지 수정 불가하므로)
            fdata.append({
                "품목": n, 
                "규격": inf.get("spec", ""), 
                "수량": int(q), 
                "단가": int(inf.get("price_cons", 0)), 
                "image_data": inf.get("image") # 숨김 데이터
            })
        
        # [V7.2] Data Editor 표시
        # 사용자가 수정한 결과가 edited_df에 저장됨
        edited_df = st.data_editor(
            pd.DataFrame(fdata),
            column_config={
                "품목": st.column_config.TextColumn(disabled=True),
                "규격": st.column_config.TextColumn(disabled=True),
                "image_data": None, # 화면에 안 보이게 숨김
                "수량": st.column_config.NumberColumn(min_value=0, step=1),
                "단가": st.column_config.NumberColumn(min_value=0, step=100, format="%d 원")
            },
            use_container_width=True,
            hide_index=True,
            num_rows="fixed" # 행 추가/삭제 불가 (수정만 가능)
        )
        
        # [V7.2] 합계 재계산 (수정된 edited_df 기준)
        total_mat = (edited_df["수량"] * edited_df["단가"]).sum()
        total_svc = sum(s["금액"] for s in st.session_state.services)
        grand_total = total_mat + total_svc

        st.markdown(f"""
        <div style="text-align:right; font-size:1.5em; padding:10px; background:#f0f2f6; border-radius:10px;">
            <b>총 합계 (VAT 포함): <span style="color:#ff4b4b;">{grand_total:,}</span> 원</b>
        </div>
        """, unsafe_allow_html=True)
        
        # PDF 다운로드 (수정된 데이터를 넘김)
        # edited_df를 dict list로 변환
        final_data_list = edited_df.to_dict('records')
        
        pdf_byte = create_pdf(final_data_list, st.session_state.services, st.session_state.current_quote_name)
        st.download_button("📥 PDF 견적서 다운로드", pdf_byte, f"quotation_{st.session_state.current_quote_name}.pdf", "application/pdf")
        
        # 이동 버튼
        c_btn1, c_btn2 = st.columns(2)
        with c_btn1:
            if st.button("⬅️ 내용 수정하기 (Step 2)"):
                st.session_state.quote_step = 2
                st.rerun()
        with c_btn2:
            if st.button("🔄 처음으로 (새 견적)"):
                st.session_state.quote_step = 1; st.session_state.quote_items = {}; st.session_state.services = []; st.session_state.current_quote_name = ""; st.rerun()

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
# 1. 설정 및 유틸리티
# ==========================================
DATA_FILE = "looperget_data.json"       
HISTORY_FILE = "looperget_history.json" 
FONT_FILE = "NanumGothic.ttf"
FONT_URL = "https://github.com/google/fonts/raw/main/ofl/nanumgothic/NanumGothic-Regular.ttf"

# 폰트 다운로드
if not os.path.exists(FONT_FILE):
    try: urllib.request.urlretrieve(FONT_URL, FONT_FILE)
    except: pass 

# 데이터 I/O
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

# PDF 생성 엔진
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

def create_advanced_pdf(final_data_list, service_items, quote_name, form_type, price_labels):
    pdf = PDF()
    pdf.add_page()
    has_font = os.path.exists(FONT_FILE)
    font_name = 'NanumGothic' if has_font else 'Helvetica'
    if has_font: pdf.add_font(font_name, '', FONT_FILE, uni=True)
    pdf.set_font(font_name, '', 10)

    if quote_name:
        pdf.set_font(font_name, '', 12)
        pdf.cell(0, 10, f"현장명 : {quote_name}", new_x="LMARGIN", new_y="NEXT")
        pdf.set_font(font_name, '', 10)

    pdf.set_fill_color(240, 240, 240)
    h_height = 10
    pdf.cell(15, h_height, "IMG", border=1, align='C', fill=True)
    pdf.cell(45, h_height, "품목정보 (Item)", border=1, align='C', fill=True)
    pdf.cell(10, h_height, "단위", border=1, align='C', fill=True)
    pdf.cell(12, h_height, "수량", border=1, align='C', fill=True)

    if form_type == "basic":
        pdf.cell(35, h_height, f"단가 ({price_labels[0]})", border=1, align='C', fill=True)
        pdf.cell(35, h_height, "금액", border=1, align='C', fill=True)
        pdf.cell(38, h_height, "비고", border=1, align='C', fill=True, new_x="LMARGIN", new_y="NEXT")
    else:
        l1, l2 = price_labels[0], price_labels[1]
        pdf.set_font(font_name, '', 8)
        pdf.cell(18, h_height, f"{l1}단가", border=1, align='C', fill=True)
        pdf.cell(22, h_height, f"{l1}금액", border=1, align='C', fill=True)
        pdf.cell(18, h_height, f"{l2}단가", border=1, align='C', fill=True)
        pdf.cell(22, h_height, f"{l2}금액", border=1, align='C', fill=True)
        pdf.cell(15, h_height, "이익금", border=1, align='C', fill=True)
        pdf.cell(13, h_height, "율(%)", border=1, align='C', fill=True, new_x="LMARGIN", new_y="NEXT")
        pdf.set_font(font_name, '', 9)

    grand_totals = {"t1": 0, "t2": 0}

    for item in final_data_list:
        name = item.get("품목", "")
        spec = item.get("규격", "-")
        qty = int(item.get("수량", 0))
        img_data = item.get("image_data", None)
        p1 = int(item.get("price_1", 0))
        a1 = p1 * qty
        grand_totals["t1"] += a1
        
        p2 = 0; a2 = 0; profit = 0; rate = 0
        if form_type == "profit":
            p2 = int(item.get("price_2", 0))
            a2 = p2 * qty
            grand_totals["t2"] += a2
            profit = a2 - a1
            rate = (profit / a2 * 100) if a2 else 0

        h = 15
        x, y = pdf.get_x(), pdf.get_y()
        
        pdf.cell(15, h, "", border=1)
        if img_data:
            try:
                data = base64.b64decode(img_data.split(",", 1)[1])
                with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as tmp:
                    tmp.write(data); tmp_path = tmp.name
                pdf.image(tmp_path, x=x+2, y=y+2, w=11, h=11)
                os.unlink(tmp_path)
            except: pass

        pdf.set_xy(x+15, y)
        pdf.cell(45, h, "", border=1)
        pdf.set_xy(x+15, y+2)
        pdf.set_font(font_name, '', 9)
        pdf.multi_cell(45, 4, name, align='L')
        pdf.set_xy(x+15, y+9)
        pdf.set_font(font_name, '', 7)
        pdf.cell(45, 4, spec, align='L')
        pdf.set_xy(x+60, y)
        pdf.set_font(font_name, '', 9)

        pdf.cell(10, h, item.get("단위", "EA"), border=1, align='C')
        pdf.cell(12, h, str(qty), border=1, align='C')

        if form_type == "basic":
            pdf.cell(35, h, f"{p1:,}", border=1, align='R')
            pdf.cell(35, h, f"{a1:,}", border=1, align='R')
            pdf.cell(38, h, "", border=1, align='C')
            pdf.ln()
        else:
            pdf.set_font(font_name, '', 8)
            pdf.cell(18, h, f"{p1:,}", border=1, align='R')
            pdf.cell(22, h, f"{a1:,}", border=1, align='R')
            pdf.cell(18, h, f"{p2:,}", border=1, align='R')
            pdf.cell(22, h, f"{a2:,}", border=1, align='R')
            pdf.set_text_color(0, 0, 255)
            pdf.cell(15, h, f"{profit:,}", border=1, align='R')
            pdf.cell(13, h, f"{rate:.1f}%", border=1, align='C')
            pdf.set_text_color(0, 0, 0)
            pdf.ln()

    svc_total = 0
    if service_items:
        pdf.ln(2)
        pdf.set_fill_color(255, 255, 224)
        pdf.cell(190, 6, " [ 추가 비용 ] ", border=1, fill=True, new_x="LMARGIN", new_y="NEXT")
        for s in service_items:
            svc_total += s['금액']
            pdf.cell(155, 6, s['항목'], border=1)
            pdf.cell(35, 6, f"{s['금액']:,} 원", border=1, align='R', new_x="LMARGIN", new_y="NEXT")

    pdf.ln(5)
    pdf.set_font(font_name, '', 12)
    
    if form_type == "basic":
        final_total = grand_totals["t1"] + svc_total
        pdf.cell(120, 10, "", border=0)
        pdf.cell(35, 10, "총 합계", border=1, align='C', fill=True)
        pdf.set_text_color(255, 0, 0)
        pdf.cell(35, 10, f"{final_total:,} 원", border=1, align='R')
    else:
        t1_final = grand_totals["t1"] + svc_total
        t2_final = grand_totals["t2"] + svc_total
        total_profit = t2_final - t1_final
        pdf.set_font(font_name, '', 10)
        pdf.cell(82, 10, "총 합계 (VAT 포함)", border=1, align='C', fill=True)
        pdf.cell(40, 10, f"{t1_final:,}", border=1, align='R')
        pdf.set_text_color(255, 0, 0)
        pdf.cell(40, 10, f"{t2_final:,}", border=1, align='R')
        pdf.set_text_color(0, 0, 255)
        pdf.cell(28, 10, f"(이익 {total_profit:,})", border=1, align='R')
        
    return bytes(pdf.output())

# ==========================================
# 3. 메인 로직
# ==========================================
if "db" not in st.session_state: st.session_state.db = load_json(DATA_FILE, DEFAULT_DATA)
if "history" not in st.session_state: st.session_state.history = load_json(HISTORY_FILE, {})
if "quote_step" not in st.session_state: st.session_state.quote_step = 1
if "quote_items" not in st.session_state: st.session_state.quote_items = {}
if "services" not in st.session_state: st.session_state.services = []
if "temp_set_recipe" not in st.session_state: st.session_state.temp_set_recipe = {}
if "current_quote_name" not in st.session_state: st.session_state.current_quote_name = ""

st.set_page_config(layout="wide", page_title="루퍼젯 프로 매니저")
st.title("💧 루퍼젯 프로 매니저 V8.1")

# --- 사이드바 ---
with st.sidebar:
    st.header("🗂️ 견적 보관함")
    q_name = st.text_input("현장명", value=st.session_state.current_quote_name)
    c1, c2 = st.columns(2)
    with c1:
        if st.button("💾 저장"):
            if not q_name or not st.session_state.quote_items: st.error("이름/내용 확인")
            else:
                st.session_state.history[q_name] = {
                    "date": datetime.datetime.now().strftime("%Y-%m-%d"),
                    "items": st.session_state.quote_items, "services": st.session_state.services, "step": st.session_state.quote_step
                }
                save_json(HISTORY_FILE, st.session_state.history); st.session_state.current_quote_name = q_name; st.success("저장됨")
    with c2:
        if st.button("✨ 초기화"):
            st.session_state.quote_items = {}; st.session_state.services = []; st.session_state.quote_step = 1; st.session_state.current_quote_name = ""; st.rerun()
    st.divider()
    h_list = list(st.session_state.history.keys())[::-1]
    if h_list:
        sel_h = st.selectbox("불러오기", h_list)
        if st.button("📂 로드"):
            d = st.session_state.history[sel_h]
            st.session_state.quote_items = d["items"]; st.session_state.services = d["services"]; st.session_state.quote_step = d.get("step", 2); st.session_state.current_quote_name = sel_h; st.rerun()
        if st.button("🗑️ 삭제"):
            del st.session_state.history[sel_h]; save_json(HISTORY_FILE, st.session_state.history); st.rerun()
    st.divider()
    mode = st.radio("모드", ["견적 작성", "관리자 모드"])

COL_MAP = {"품목코드": "code", "카테고리": "category", "제품명": "name", "규격": "spec", "단위": "unit", "1롤길이(m)": "len_per_unit", "매입단가": "price_buy", "총판가1": "price_d1", "총판가2": "price_d2", "대리점가": "price_agy", "소비자가": "price_cons", "이미지데이터": "image"}
REV_COL_MAP = {v: k for k, v in COL_MAP.items()}

# --- [관리자 모드] ---
if mode == "관리자 모드":
    st.header("🛠 데이터 관리")
    t1, t2 = st.tabs(["부품 관리", "세트 관리"])
    
    with t1: # 부품
        # 1. 이미지
        st.markdown("##### 1. 이미지 등록")
        c1, c2, c3 = st.columns([2, 2, 1])
        pn = [p["name"] for p in st.session_state.db["products"]]
        with c1: tp = st.selectbox("품목", pn)
        with c2: ifile = st.file_uploader("사진", ["png", "jpg"], key="pimg")
        with c3:
            st.write(""); st.write("")
            if st.button("이미지저장") and ifile:
                b64 = process_image(ifile)
                for p in st.session_state.db["products"]:
                    if p["name"] == tp: p["image"] = b64
                save_json(DATA_FILE, st.session_state.db); st.success("저장됨"); st.rerun()
        
        st.divider()
        # 2. 엑셀 관리 (복구됨)
        with st.expander("📂 엑셀 데이터 관리 (클릭)", expanded=True):
            ec1, ec2 = st.columns(2)
            with ec1:
                st.write("▼ 데이터 다운로드")
                df = pd.DataFrame(st.session_state.db["products"]).rename(columns=REV_COL_MAP)
                if "이미지데이터" in df.columns: df["이미지데이터"] = "APP"
                buf = io.BytesIO()
                with pd.ExcelWriter(buf, engine='xlsxwriter') as w: df.to_excel(w, index=False)
                st.download_button("엑셀 다운로드", buf.getvalue(), "products.xlsx")
            with ec2:
                st.write("▼ 엑셀 업로드")
                uf = st.file_uploader("업로드", ["xlsx"])
                if uf and st.button("덮어쓰기"):
                    try:
                        ndf = pd.read_excel(uf).rename(columns=COL_MAP).fillna(0)
                        oimg = {p["name"]: p.get("image") for p in st.session_state.db["products"]}
                        nrec = ndf.to_dict('records')
                        for p in nrec: 
                            if p["name"] in oimg: p["image"] = oimg[p["name"]]
                        st.session_state.db["products"] = nrec
                        save_json(DATA_FILE, st.session_state.db); st.success("완료"); st.rerun()
                    except Exception as e: st.error(e)

        # 3. 에디터
        st.markdown("##### 📝 리스트 직접 수정")
        dfp = pd.DataFrame(st.session_state.db["products"])
        vcols = [c for c in dfp.columns if c != "image"]
        edf = st.data_editor(dfp[vcols].rename(columns=REV_COL_MAP), num_rows="dynamic", use_container_width=True)
        if st.button("리스트 저장"):
            upd = edf.rename(columns=COL_MAP).to_dict("records")
            oimg = {p["name"]: p.get("image") for p in st.session_state.db["products"]}
            for p in upd:
                if p["name"] in oimg: p["image"] = oimg[p["name"]]
            st.session_state.db["products"] = upd
            save_json(DATA_FILE, st.session_state.db); st.success("저장"); st.rerun()

    with t2: # 세트
        mt = st.radio("작업", ["신규", "수정/삭제"], horizontal=True)
        cat = st.selectbox("분류", ["주배관세트", "가지관세트", "기타자재"])
        
        # 하위 분류
        sub_cat = None
        if cat == "주배관세트":
            sub_cat = st.selectbox("주배관 하위 분류", ["50mm", "40mm", "기타"], key="sub_c")

        pl = [p["name"] for p in st.session_state.db["products"]]

        if mt == "신규":
            nn = st.text_input("세트명")
            ni = st.file_uploader("이미지", key="nsi")
            c1, c2, c3 = st.columns([3,2,1])
            with c1: sp = st.selectbox("부품", pl, key="nsp")
            with c2: sq = st.number_input("수량", 1, key="nsq")
            with c3: 
                if st.button("담기"): st.session_state.temp_set_recipe[sp] = sq
            st.write(st.session_state.temp_set_recipe)
            if st.button("저장"):
                im = process_image(ni) if ni else None
                if cat not in st.session_state.db["sets"]: st.session_state.db["sets"][cat] = {}
                st.session_state.db["sets"][cat][nn] = {"recipe": st.session_state.temp_set_recipe, "image": im, "sub_cat": sub_cat}
                save_json(DATA_FILE, st.session_state.db); st.session_state.temp_set_recipe = {}; st.success("저장 완료")
        else:
            cset = st.session_state.db["sets"].get(cat, {})
            if cset:
                tg = st.selectbox("선택", list(cset.keys()))
                if st.button("불러오기"):
                    dat = cset[tg]
                    st.session_state.temp_set_recipe = dat.get("recipe", dat).copy()
                    st.toast("로드됨")
                for k,v in list(st.session_state.temp_set_recipe.items()):
                    st.text(f"{k}: {v}")
                    if st.button(f"del {k}"): del st.session_state.temp_set_recipe[k]; st.rerun()
                ap = st.selectbox("추가", pl, key="esp")
                aq = st.number_input("수량", 1, key="esq")
                if st.button("담기", key="es_add"): st.session_state.temp_set_recipe[ap] = aq; st.rerun()
                if st.button("삭제"): del st.session_state.db["sets"][cat][tg]; save_json(DATA_FILE, st.session_state.db); st.rerun()

# --- [견적 모드] ---
else:
    st.markdown(f"### 📝 현장명: **{st.session_state.current_quote_name if st.session_state.current_quote_name else '(제목 없음)'}**")

    if st.session_state.quote_step == 1:
        st.subheader("STEP 1. 물량 입력")
        sets = st.session_state.db.get("sets", {})

        with st.expander("1. 주배관 세트", expanded=True):
            m_sets = sets.get("주배관세트", {})
            grouped = {"50mm":{}, "40mm":{}, "기타":{}, "미분류":{}}
            for k, v in m_sets.items():
                sc = v.get("sub_cat", "미분류") if isinstance(v, dict) else "미분류"
                if sc not in grouped: grouped[sc] = {}
                grouped[sc][k] = v
            mt1, mt2, mt3, mt4 = st.tabs(["50mm", "40mm", "기타", "전체"])
            def render_inputs(d, pf):
                cols = st.columns(4)
                res = {}
                for i, (n, v) in enumerate(d.items()):
                    with cols[i%4]:
                        img = v.get("image") if isinstance(v, dict) else None
                        if img: st.image(img, use_container_width=True)
                        else: st.markdown("<div style='height:80px;background:#eee'></div>", unsafe_allow_html=True)
                        res[n] = st.number_input(n, 0, key=f"{pf}_{n}")
                return res
            with mt1: inp_m_50 = render_inputs(grouped["50mm"], "m50")
            with mt2: inp_m_40 = render_inputs(grouped["40mm"], "m40")
            with mt3: inp_m_etc = render_inputs(grouped["기타"], "metc")
            with mt4: inp_m_u = render_inputs(grouped["미분류"], "mu")

        with st.expander("2. 가지관 세트"): inp_b = render_inputs(sets.get("가지관세트", {}), "b")
        with st.expander("3. 기타 자재"): inp_e = render_inputs(sets.get("기타자재", {}), "e")
        
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
            all_m = {**inp_m_50, **inp_m_40, **inp_m_etc, **inp_m_u}
            def ex(ins, db):
                for k,v in ins.items():
                    if v>0:
                        rec = db[k].get("recipe", db[k])
                        for p, q in rec.items(): res[p] = res.get(p, 0) + q*v
            ex(all_m, sets.get("주배관세트", {}))
            ex(inp_b, sets.get("가지관세트", {}))
            ex(inp_e, sets.get("기타자재", {}))
            def cr(n, l, pl):
                if l>0 and n:
                    pi = next((x for x in pl if x["name"]==n), None)
                    if pi and pi["len_per_unit"]: res[n] = res.get(n, 0) + math.ceil(l/pi["len_per_unit"])
            cr(sm, lm, mpl); cr(sb, lb, bpl)
            st.session_state.quote_items = res; st.session_state.quote_step = 2; st.rerun()

    elif st.session_state.quote_step == 2:
        st.subheader("STEP 2. 내용 검토")
        st.dataframe(pd.DataFrame([{"품목":k, "수량":v} for k,v in st.session_state.quote_items.items()]), use_container_width=True)
        c1, c2 = st.columns(2)
        pdb = {p["name"]: p for p in st.session_state.db["products"]}
        with c1:
            ap = st.selectbox("추가", list(pdb.keys()))
            aq = st.number_input("수량", 1)
            if st.button("추가"): st.session_state.quote_items[ap] = st.session_state.quote_items.get(ap, 0) + aq; st.rerun()
        with c2:
            stype = st.selectbox("비용", ["배송비", "용역비", "기타"])
            sn = st.text_input("내용") if stype=="기타" else stype
            sp = st.number_input("금액", 0, step=1000)
            if st.button("비용추가"): st.session_state.services.append({"항목": sn, "금액": sp}); st.rerun()
        if st.session_state.services: st.table(st.session_state.services)
        if st.button("최종 확정 (STEP 3)"): st.session_state.quote_step = 3; st.rerun()

    elif st.session_state.quote_step == 3:
        st.header("🏁 최종 견적")
        if not st.session_state.current_quote_name: st.warning("저장해주세요!")
        st.markdown("##### 🖨️ 출력 옵션")
        c_opt1, c_opt2 = st.columns(2)
        with c_opt1:
            form_type = st.radio("양식", ["기본 양식", "이익 분석 양식"])
        with c_opt2:
            opts = ["매입단가", "총판가1", "총판가2", "대리점가", "소비자가"]
            if "기본" in form_type: sel = st.multiselect("단가 (1개)", opts, default=["소비자가"], max_selections=1)
            else: sel = st.multiselect("비교 단가 (2개: 저->고)", opts, default=["매입단가", "소비자가"], max_selections=2)

        pkey = {"매입단가":"price_buy", "총판가1":"price_d1", "총판가2":"price_d2", "대리점가":"price_agy", "소비자가":"price_cons"}
        pdb = {p["name"]: p for p in st.session_state.db["products"]}
        pk = [pkey[l] for l in sel] if sel else ["price_cons"]
        fdata = []
        for n, q in st.session_state.quote_items.items():
            inf = pdb.get(n, {})
            d = {"품목": n, "규격": inf.get("spec", ""), "단위": inf.get("unit", "EA"), "수량": int(q), "image_data": inf.get("image")}
            d["price_1"] = int(inf.get(pk[0], 0))
            if len(pk)>1: d["price_2"] = int(inf.get(pk[1], 0))
            fdata.append(d)
        
        st.markdown("---")
        cc = {"품목": st.column_config.TextColumn(disabled=True), "image_data": None, "수량": st.column_config.NumberColumn(step=1), "price_1": st.column_config.NumberColumn(label=sel[0] if sel else "단가", format="%d")}
        if len(pk)>1: cc["price_2"] = st.column_config.NumberColumn(label=sel[1], format="%d")
        
        edited = st.data_editor(pd.DataFrame(fdata), column_config=cc, use_container_width=True, hide_index=True)
        
        if sel:
            fmode = "basic" if "기본" in form_type else "profit"
            pdf_b = create_advanced_pdf(edited.to_dict('records'), st.session_state.services, st.session_state.current_quote_name, fmode, sel)
            st.download_button("📥 PDF 다운로드", pdf_b, f"quote_{st.session_state.current_quote_name}.pdf", "application/pdf", type="primary")

        c1, c2 = st.columns(2)
        with c1: 
            if st.button("⬅️ 수정"): st.session_state.quote_step = 2; st.rerun()
        with c2:
            if st.button("🔄 처음으로"): st.session_state.quote_step = 1; st.session_state.quote_items = {}; st.session_state.services = []; st.session_state.current_quote_name = ""; st.rerun()

import streamlit as st
import pandas as pd
import math
import os
import json
import io
import base64
import tempfile
from PIL import Image
from fpdf import FPDF

# ==========================================
# 1. 유틸리티 (이미지 & PDF)
# ==========================================
DATA_FILE = "looperget_data.json"
FONT_FILE = "NanumGothic.ttf"  # 폰트 파일명 (같은 폴더에 있어야 함)

def process_image(uploaded_file):
    """이미지를 4:3 비율 썸네일로 변환하여 Base64 리턴"""
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

# PDF 생성 클래스
class PDF(FPDF):
    def header(self):
        # 한글 폰트 등록 (최초 1회)
        if os.path.exists(FONT_FILE):
            self.add_font('NanumGothic', '', FONT_FILE)
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
    
    # 폰트 설정
    has_font = os.path.exists(FONT_FILE)
    if has_font:
        pdf.set_font('NanumGothic', '', 10)
    else:
        pdf.set_font('Helvetica', '', 10)
        st.warning("⚠️ 한글 폰트 파일(NanumGothic.ttf)이 없어 PDF 한글이 깨질 수 있습니다.")

    # 컬럼 헤더
    # 폭 설정: 이미지(25), 품목명(60), 규격(30), 수량(15), 단가(30), 금액(30) = 190 (A4 폭 ~210)
    pdf.set_fill_color(240, 240, 240) # 회색 배경
    pdf.cell(25, 10, 'IMG', border=1, align='C', fill=True)
    pdf.cell(60, 10, '품목명 (Item)', border=1, align='C', fill=True)
    pdf.cell(30, 10, '규격 (Spec)', border=1, align='C', fill=True)
    pdf.cell(15, 10, '수량', border=1, align='C', fill=True)
    pdf.cell(30, 10, '단가', border=1, align='C', fill=True)
    pdf.cell(30, 10, '금액', border=1, align='C', fill=True, new_x="LMARGIN", new_y="NEXT")

    total_mat_price = 0
    p_map = {p["name"]: p for p in db_products}

    # 데이터 루프
    for name, qty in quote_items.items():
        info = p_map.get(name, {})
        price = info.get("price_cons", 0)
        amt = price * qty
        total_mat_price += amt
        spec = info.get("spec", "-")
        
        # 행 높이 설정 (이미지가 있으면 높게)
        row_height = 15
        
        # 1. 이미지 처리 (Base64 -> Temp File)
        img_data = info.get("image")
        x_start = pdf.get_x()
        y_start = pdf.get_y()
        
        # 이미지 칸 그리기
        pdf.cell(25, row_height, "", border=1) 
        
        if img_data:
            try:
                # data:image/jpeg;base64,.... 형식 제거
                header, encoded = img_data.split(",", 1)
                data = base64.b64decode(encoded)
                with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as tmp:
                    tmp.write(data)
                    tmp_path = tmp.name
                
                # 이미지 삽입 (x, y, w, h)
                pdf.image(tmp_path, x=x_start+2, y=y_start+2, w=21, h=11)
                os.unlink(tmp_path) # 임시파일 삭제
            except Exception:
                pass # 이미지 에러 시 무시

        # 2. 텍스트 데이터 그리기
        # 한글 폰트 적용
        if has_font: pdf.set_font('NanumGothic', '', 9)
        
        pdf.set_xy(x_start + 25, y_start)
        pdf.cell(60, row_height, name, border=1, align='L')
        pdf.cell(30, row_height, spec, border=1, align='C')
        pdf.cell(15, row_height, str(qty), border=1, align='C')
        pdf.cell(30, row_height, f"{price:,}", border=1, align='R')
        pdf.cell(30, row_height, f"{amt:,}", border=1, align='R', new_x="LMARGIN", new_y="NEXT")

    # 서비스 비용
    total_svc_price = 0
    if service_items:
        pdf.ln(5)
        pdf.set_fill_color(255, 255, 200) # 연한 노랑
        pdf.cell(190, 8, " [ 추가 비용 / 용역 ] ", border=1, align='L', fill=True, new_x="LMARGIN", new_y="NEXT")
        
        for svc in service_items:
            s_name = svc['항목']
            s_price = svc['금액']
            total_svc_price += s_price
            
            pdf.cell(130, 8, s_name, border=1, align='L')
            pdf.cell(60, 8, f"{s_price:,} 원", border=1, align='R', new_x="LMARGIN", new_y="NEXT")

    # 최종 합계
    grand_total = total_mat_price + total_svc_price
    
    pdf.ln(5)
    if has_font: pdf.set_font('NanumGothic', '', 12)
    pdf.cell(130, 12, "총 합계 (Total Amount)", border=1, align='R')
    pdf.set_text_color(255, 0, 0) # 빨간색
    pdf.cell(60, 12, f"{grand_total:,} 원", border=1, align='R', new_x="LMARGIN", new_y="NEXT")
    pdf.set_text_color(0, 0, 0) # 검정 복귀
    
    # PDF Byte 리턴
    return pdf.output(dest='S').encode('latin-1')

# ==========================================
# 2. 데이터 관리
# ==========================================
# (기존 V5.0의 load_data, save_data 등 동일)
DEFAULT_DATA = {
    "products": [
        {"code": "P001", "category": "부속", "name": "cccT", "spec": "50mm", "unit": "EA", "len_per_unit": 0, "price_buy": 5000, "price_d1": 6000, "price_d2": 7000, "price_agy": 8000, "price_cons": 10000, "image": None},
        {"code": "P002", "category": "부속", "name": "스마트커플러4-2", "spec": "50mm", "unit": "EA", "len_per_unit": 0, "price_buy": 2000, "price_d1": 3000, "price_d2": 4000, "price_agy": 5000, "price_cons": 6000, "image": None},
        {"code": "PIPE01", "category": "주배관", "name": "PVC호스", "spec": "50mm", "unit": "Roll", "len_per_unit": 50, "price_buy": 50000, "price_d1": 60000, "price_d2": 70000, "price_agy": 80000, "price_cons": 100000, "image": None},
    ],
    "sets": {
        "주배관세트": {
            "T분기 A타입": {"recipe": {"cccT": 1, "스마트커플러4-2": 2}, "image": None}
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

# ==========================================
# 3. 화면 구성
# ==========================================
st.set_page_config(layout="wide", page_title="루퍼젯 프로 매니저")
st.title("💧 루퍼젯 프로 매니저 V6.0")

mode = st.sidebar.radio("모드 선택", ["견적 작성 모드", "관리자 모드 (데이터 관리)"])

# ------------------------------------------
# [PAGE 1] 관리자 모드
# ------------------------------------------
if mode == "관리자 모드 (데이터 관리)":
    st.header("🛠 데이터 관리 센터")
    tab1, tab2 = st.tabs(["1. 품목(부품) & 이미지 관리", "2. 세트(Set) 구성 관리"])
    
    with tab1:
        st.info("💡 엑셀은 '텍스트 데이터' 관리용, 이미지는 아래에서 직접 등록해주세요.")
        
        # 이미지 등록
        c1, c2, c3 = st.columns([2, 2, 1])
        p_names = [p["name"] for p in st.session_state.db["products"]]
        with c1: target_p = st.selectbox("이미지 등록할 품목", p_names)
        with c2: img_file = st.file_uploader("사진 업로드", type=["png", "jpg"], key="p_img")
        with c3:
            st.write("") 
            st.write("")
            if st.button("사진 저장"):
                if img_file:
                    b64 = process_image(img_file)
                    for p in st.session_state.db["products"]:
                        if p["name"] == target_p: p["image"] = b64
                    save_data(st.session_state.db)
                    st.success("저장됨!")
                    st.rerun()

        st.divider()
        # 엑셀 I/O
        with st.expander("📂 엑셀 데이터 관리 (클릭)"):
            c_ex1, c_ex2 = st.columns(2)
            with c_ex1:
                df_curr = pd.DataFrame(st.session_state.db["products"])
                df_ex = df_curr.rename(columns=REV_COL_MAP)
                if "이미지데이터" in df_ex.columns: df_ex["이미지데이터"] = "APP_MANAGED"
                buf = io.BytesIO()
                with pd.ExcelWriter(buf, engine='xlsxwriter') as w: df_ex.to_excel(w, index=False)
                st.download_button("엑셀 다운로드", buf.getvalue(), "products.xlsx")
            with c_ex2:
                up_file = st.file_uploader("엑셀 업로드", type=['xlsx'])
                if up_file and st.button("데이터 덮어쓰기"):
                    try:
                        new_df = pd.read_excel(up_file).rename(columns=COL_MAP).fillna(0)
                        old_imgs = {p["name"]: p.get("image") for p in st.session_state.db["products"]}
                        new_recs = new_df.to_dict('records')
                        for p in new_recs:
                            if p["name"] in old_imgs: p["image"] = old_imgs[p["name"]]
                        st.session_state.db["products"] = new_recs
                        save_data(st.session_state.db)
                        st.success("완료!")
                        st.rerun()
                    except Exception as e: st.error(e)

        # 에디터
        df_p = pd.DataFrame(st.session_state.db["products"])
        cols = [c for c in df_p.columns if c != "image"]
        edited = st.data_editor(df_p[cols].rename(columns=REV_COL_MAP), use_container_width=True, num_rows="dynamic")
        if st.button("리스트 저장"):
            updated = edited.rename(columns=COL_MAP).to_dict("records")
            img_map = {p["name"]: p.get("image") for p in st.session_state.db["products"]}
            for p in updated:
                if p["name"] in img_map: p["image"] = img_map[p["name"]]
            st.session_state.db["products"] = updated
            save_data(st.session_state.db)
            st.success("저장됨")

    with tab2:
        # 세트 관리 (V5.0과 동일 로직)
        manage_type = st.radio("작업", ["신규 등록", "수정/삭제"], horizontal=True)
        cate = st.selectbox("카테고리", ["주배관세트", "가지관세트", "기타자재"])
        prod_list = [p["name"] for p in st.session_state.db["products"]]

        if manage_type == "신규 등록":
            c_n1, c_n2 = st.columns(2)
            with c_n1: 
                new_name = st.text_input("세트 명칭")
                new_img = st.file_uploader("세트 이미지", key="ns_img")
            with c_n2:
                s1, s2, s3 = st.columns([3, 2, 1])
                with s1: sel_p = st.selectbox("부품", prod_list, key="ns_p")
                with s2: sel_q = st.number_input("수량", 1, key="ns_q")
                with s3:
                    if st.button("담기", key="ns_add"): st.session_state.temp_set_recipe[sel_p] = sel_q
                st.write(st.session_state.temp_set_recipe)
            
            if st.button("세트 저장"):
                if new_name and st.session_state.temp_set_recipe:
                    if cate not in st.session_state.db["sets"]: st.session_state.db["sets"][cate] = {}
                    img_d = process_image(new_img) if new_img else None
                    st.session_state.db["sets"][cate][new_name] = {"recipe": st.session_state.temp_set_recipe, "image": img_d}
                    save_data(st.session_state.db)
                    st.session_state.temp_set_recipe = {}
                    st.success("저장됨")
                    st.rerun()

        else: # 수정 삭제
            cur_sets = st.session_state.db["sets"].get(cate, {})
            if cur_sets:
                target = st.selectbox("대상 선택", list(cur_sets.keys()))
                if st.button("불러오기"):
                    dat = cur_sets[target]
                    st.session_state.temp_set_recipe = dat.get("recipe", dat).copy()
                    st.toast("불러옴")
                
                ec1, ec2 = st.columns(2)
                with ec1:
                    st.write(f"**{target}** 편집")
                    curr_img = cur_sets[target].get("image") if isinstance(cur_sets[target], dict) else None
                    if curr_img: st.image(curr_img, width=150)
                    edit_img = st.file_uploader("이미지 변경", key="es_img")
                with ec2:
                    for k, v in list(st.session_state.temp_set_recipe.items()):
                        rc1, rc2, rc3 = st.columns([3, 1, 1])
                        rc1.text(k); rc2.text(v)
                        if rc3.button("X", key=f"del_{k}"): 
                            del st.session_state.temp_set_recipe[k]; st.rerun()
                    sc1, sc2, sc3 = st.columns([3, 2, 1])
                    with sc1: add_p = st.selectbox("추가", prod_list, key="es_p")
                    with sc2: add_q = st.number_input("수량", 1, key="es_q")
                    with sc3:
                        if st.button("담기", key="es_add"): 
                            st.session_state.temp_set_recipe[add_p] = add_q; st.rerun()
                
                bc1, bc2 = st.columns(2)
                with bc1:
                    if st.button("수정 저장"):
                        f_img = process_image(edit_img) if edit_img else curr_img
                        st.session_state.db["sets"][cate][target] = {"recipe": st.session_state.temp_set_recipe, "image": f_img}
                        save_data(st.session_state.db)
                        st.session_state.temp_set_recipe = {}
                        st.success("수정됨"); st.rerun()
                with bc2:
                    if st.button("삭제", type="primary"):
                        del st.session_state.db["sets"][cate][target]
                        save_data(st.session_state.db)
                        st.rerun()

# ------------------------------------------
# [PAGE 2] 견적 작성 모드
# ------------------------------------------
else:
    st.header("📑 스마트 견적 작성")
    if "quote_step" not in st.session_state:
        st.session_state.quote_step = 1
        st.session_state.quote_items = {}
        st.session_state.services = []

    # STEP 1, 2 로직은 V5.0과 동일 (생략 없이 사용하시면 됩니다)
    # 지면 관계상 STEP 3 (PDF 부분) 위주로 작성합니다.
    
    # ... (STEP 1 입력 로직: V5.0 코드 복사해서 쓰세요) ...
    # 편의를 위해 간단히 복원합니다.
    def render_inputs(s_dict, pf):
        ins = {}
        if not s_dict: return {}
        cols = st.columns(4)
        for i, (k, v) in enumerate(s_dict.items()):
            with cols[i%4]:
                img = v.get("image") if isinstance(v, dict) else None
                if img: st.image(img, use_container_width=True)
                else: st.markdown("<div style='height:80px;background:#eee;color:#888;text-align:center;line-height:80px;'>No Img</div>", unsafe_allow_html=True)
                ins[k] = st.number_input(k, min_value=0, key=f"{pf}_{k}")
        return ins

    if st.session_state.quote_step == 1:
        st.subheader("STEP 1. 물량 입력")
        db_sets = st.session_state.db.get("sets", {})
        with st.expander("1. 주배관", True): inp_m = render_inputs(db_sets.get("주배관세트"), "m")
        with st.expander("2. 가지관"): inp_b = render_inputs(db_sets.get("가지관세트"), "b")
        with st.expander("3. 기타"): inp_e = render_inputs(db_sets.get("기타자재"), "e")
        
        st.markdown("#### 4. 배관 길이")
        mps = [p for p in st.session_state.db["products"] if p["category"] == "주배관"]
        bps = [p for p in st.session_state.db["products"] if p["category"] == "가지관"]
        c1, c2 = st.columns(2)
        with c1: 
            s_mp = st.selectbox("주배관", [p["name"] for p in mps]) if mps else None
            l_mp = st.number_input("주배관(m)", 0)
        with c2: 
            s_bp = st.selectbox("가지관", [p["name"] for p in bps]) if bps else None
            l_bp = st.number_input("가지관(m)", 0)

        if st.button("계산하기"):
            res = {}
            def expl(ins, db):
                for k, v in ins.items():
                    if v > 0:
                        rec = db[k].get("recipe", db[k])
                        for p, q in rec.items(): res[p] = res.get(p, 0) + q * v
            expl(inp_m, db_sets.get("주배관세트"))
            expl(inp_b, db_sets.get("가지관세트"))
            expl(inp_e, db_sets.get("기타자재"))
            
            def calc_roll(n, l, plist):
                if l > 0 and n:
                    p = next((x for x in plist if x["name"] == n), None)
                    if p and p["len_per_unit"]: res[n] = res.get(n, 0) + math.ceil(l/p["len_per_unit"])
            calc_roll(s_mp, l_mp, mps)
            calc_roll(s_bp, l_bp, bps)
            st.session_state.quote_items = res
            st.session_state.quote_step = 2
            st.rerun()

    elif st.session_state.quote_step == 2:
        st.subheader("STEP 2. 검토")
        # ... (V5.0의 STEP 2 로직 그대로 사용) ...
        # 간단 구현
        rows = []
        p_db = {p["name"]: p for p in st.session_state.db["products"]}
        for n, q in st.session_state.quote_items.items():
            info = p_db.get(n, {})
            rows.append({"품목": n, "수량": q, "단가": info.get("price_cons", 0), "합계": info.get("price_cons", 0)*q})
        st.dataframe(pd.DataFrame(rows), use_container_width=True)
        
        st.divider()
        c1, c2 = st.columns(2)
        with c1:
            st.write("품목 추가")
            ap = st.selectbox("품목", list(p_db.keys()))
            aq = st.number_input("수량", 1)
            if st.button("추가"): st.session_state.quote_items[ap] = st.session_state.quote_items.get(ap, 0) + aq; st.rerun()
        with c2:
            st.write("비용 추가")
            stype = st.selectbox("항목", ["배송비", "용역비", "기타"])
            sname = st.text_input("내용") if stype == "기타" else stype
            sprice = st.number_input("금액", 0, step=1000)
            if st.button("비용추가"): st.session_state.services.append({"항목": sname, "금액": sprice}); st.rerun()
            
        if st.session_state.services: st.table(st.session_state.services)
        if st.button("최종 확정"): st.session_state.quote_step = 3; st.rerun()

    # === STEP 3: 최종 및 PDF 다운로드 ===
    elif st.session_state.quote_step == 3:
        st.divider()
        st.header("🏁 최종 견적서")
        
        # 1. 화면 표시 (Table)
        p_db = {p["name"]: p for p in st.session_state.db["products"]}
        final_data = []
        t_mat = 0
        for n, q in st.session_state.quote_items.items():
            inf = p_db.get(n, {})
            pr = inf.get("price_cons", 0)
            amt = pr * q
            t_mat += amt
            final_data.append({"IMG": inf.get("image"), "품목": n, "규격": inf.get("spec"), "수량": q, "단가": pr, "금액": amt})
            
        st.dataframe(
            pd.DataFrame(final_data), 
            column_config={"IMG": st.column_config.ImageColumn("이미지", width="small"), "단가": st.column_config.NumberColumn(format="%d"), "금액": st.column_config.NumberColumn(format="%d")},
            use_container_width=True, hide_index=True
        )
        
        t_svc = sum(s["금액"] for s in st.session_state.services)
        g_tot = t_mat + t_svc
        
        st.markdown(f"<h2 style='text-align:right; color:blue'>총 합계: {g_tot:,} 원</h2>", unsafe_allow_html=True)
        
        # 2. PDF 다운로드 버튼
        st.markdown("---")
        st.subheader("📄 견적서 다운로드")
        
        if not os.path.exists(FONT_FILE):
            st.error(f"❌ '{FONT_FILE}' 폰트 파일이 없습니다. PDF 한글이 깨집니다. 깃허브에 폰트를 올려주세요.")
        
        pdf_byte = create_pdf(st.session_state.quote_items, st.session_state.services, st.session_state.db["products"])
        
        st.download_button(
            label="📥 PDF 견적서 다운로드 (클릭)",
            data=pdf_byte,
            file_name="looperget_quotation.pdf",
            mime="application/pdf"
        )
        
        if st.button("처음으로"):
            st.session_state.quote_step = 1; st.session_state.quote_items = {}; st.session_state.services = []; st.rerun()

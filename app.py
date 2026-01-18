import streamlit as st
import pandas as pd
import math
import os
import json
import io
import base64
from PIL import Image

# ==========================================
# 1. 유틸리티 및 데이터 초기화
# ==========================================
DATA_FILE = "looperget_data.json"

def process_image(uploaded_file):
    """이미지를 4:3 비율(200x150) 썸네일로 변환하여 Base64 리턴"""
    try:
        image = Image.open(uploaded_file)
        # 4:3 비율 썸네일 (가로 200px, 세로 150px)
        image.thumbnail((200, 150)) 
        
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        img_str = base64.b64encode(buffer.getvalue()).decode()
        return f"data:image/png;base64,{img_str}"
    except Exception as e:
        st.error(f"이미지 처리 중 오류: {e}")
        return None

# 초기 데이터 (구조 변경됨: sets -> {name: {recipe: {}, image: ""}})
DEFAULT_DATA = {
    "products": [
        {"code": "P001", "category": "부속", "name": "cccT", "spec": "50mm", "unit": "EA", "len_per_unit": 0, "price_buy": 5000, "price_d1": 6000, "price_d2": 7000, "price_agy": 8000, "price_cons": 10000, "image": None},
        {"code": "P002", "category": "부속", "name": "스마트커플러4-2", "spec": "50mm", "unit": "EA", "len_per_unit": 0, "price_buy": 2000, "price_d1": 3000, "price_d2": 4000, "price_agy": 5000, "price_cons": 6000, "image": None},
        {"code": "P003", "category": "부속", "name": "e호스밸브", "spec": "50mm", "unit": "EA", "len_per_unit": 0, "price_buy": 5000, "price_d1": 6000, "price_d2": 7000, "price_agy": 8000, "price_cons": 10000, "image": None},
        {"code": "PIPE01", "category": "주배관", "name": "PVC호스", "spec": "50mm", "unit": "Roll", "len_per_unit": 50, "price_buy": 50000, "price_d1": 60000, "price_d2": 70000, "price_agy": 80000, "price_cons": 100000, "image": None},
        {"code": "PIPE02", "category": "가지관", "name": "점적테이프", "spec": "10cm간격", "unit": "Roll", "len_per_unit": 1000, "price_buy": 35000, "price_d1": 40000, "price_d2": 45000, "price_agy": 50000, "price_cons": 60000, "image": None},
    ],
    "sets": {
        "주배관세트": {
            "T분기 A타입": {
                "recipe": {"cccT": 1, "스마트커플러4-2": 2, "e호스밸브": 1},
                "image": None
            },
            "T분기 B타입": {
                "recipe": {"cccT": 1, "스마트커플러4-2": 1, "e호스밸브": 2},
                "image": None
            }
        },
        "가지관세트": {
            "점적연결 세트": {
                "recipe": {"스마트커플러4-2": 1, "e호스밸브": 1},
                "image": None
            }
        },
        "기타자재": {
            "펌프세트": {
                "recipe": {"스마트커플러4-2": 2},
                "image": None
            }
        }
    }
}

COL_MAP = {
    "품목코드": "code", "카테고리": "category", "제품명": "name", "규격": "spec", "단위": "unit",
    "1롤길이(m)": "len_per_unit", "매입단가": "price_buy", "총판가1": "price_d1",
    "총판가2": "price_d2", "대리점가": "price_agy", "소비자가": "price_cons", "이미지데이터": "image"
}
REV_COL_MAP = {v: k for k, v in COL_MAP.items()}

def load_data():
    if not os.path.exists(DATA_FILE):
        return DEFAULT_DATA
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def save_data(data):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)

if "db" not in st.session_state:
    st.session_state.db = load_data()

if "temp_set_recipe" not in st.session_state:
    st.session_state.temp_set_recipe = {}

# ==========================================
# 2. 메인 UI
# ==========================================
st.set_page_config(layout="wide", page_title="루퍼젯 프로 매니저")
st.title("💧 루퍼젯 프로 매니저 V5.0")

mode = st.sidebar.radio("모드 선택", ["견적 작성 모드", "관리자 모드 (데이터 관리)"])

# ------------------------------------------
# [PAGE 1] 관리자 모드
# ------------------------------------------
if mode == "관리자 모드 (데이터 관리)":
    st.header("🛠 데이터 관리 센터")
    
    tab1, tab2 = st.tabs(["1. 품목(부품) & 이미지 관리", "2. 세트(Set) 구성 & 이미지 관리"])
    
    with tab1:
        st.subheader("📦 개별 부품 및 이미지 등록")
        
        # 품목 이미지 등록
        with st.container():
            st.info("개별 부품의 이미지를 등록하세요.")
            c_img1, c_img2, c_img3 = st.columns([2, 2, 1])
            p_names = [p["name"] for p in st.session_state.db["products"]]
            with c_img1:
                target_p = st.selectbox("품목 선택", p_names)
            with c_img2:
                img_file = st.file_uploader("이미지 업로드 (부품)", type=["png", "jpg", "jpeg"], key="p_img_up")
            with c_img3:
                st.write("")
                st.write("")
                if st.button("부품 이미지 저장"):
                    if img_file:
                        b64_img = process_image(img_file)
                        if b64_img:
                            for p in st.session_state.db["products"]:
                                if p["name"] == target_p:
                                    p["image"] = b64_img
                                    break
                            save_data(st.session_state.db)
                            st.success(f"저장 완료!")
                            st.rerun()

        st.divider()
        
        # 엑셀 I/O (기존 유지)
        with st.expander("📂 엑셀 데이터 관리 (클릭)"):
            c1, c2 = st.columns(2)
            with c1:
                df_current = pd.DataFrame(st.session_state.db["products"])
                df_export = df_current.rename(columns=REV_COL_MAP)
                if "이미지데이터" in df_export.columns:
                    df_export["이미지데이터"] = "앱에서 관리"
                buffer = io.BytesIO()
                with pd.ExcelWriter(buffer, engine='xlsxwriter') as writer:
                    df_export.to_excel(writer, index=False, sheet_name='Sheet1')
                st.download_button("엑셀 다운로드", buffer.getvalue(), "products.xlsx")

            with c2:
                uploaded_file = st.file_uploader("엑셀 업로드", type=['xlsx', 'xls'])
                if uploaded_file and st.button("데이터 덮어쓰기"):
                    try:
                        df_upload = pd.read_excel(uploaded_file).rename(columns=COL_MAP).fillna(0)
                        # 기존 이미지 유지 로직
                        old_imgs = {p["name"]: p.get("image") for p in st.session_state.db["products"]}
                        new_data = df_upload.to_dict('records')
                        for p in new_data:
                            if p["name"] in old_imgs: p["image"] = old_imgs[p["name"]]
                        st.session_state.db["products"] = new_data
                        save_data(st.session_state.db)
                        st.success("완료!")
                        st.rerun()
                    except Exception as e:
                        st.error(e)

        # 에디터
        df_products = pd.DataFrame(st.session_state.db["products"])
        display_cols = [c for c in df_products.columns if c != "image"]
        edited_df = st.data_editor(df_products[display_cols].rename(columns=REV_COL_MAP), num_rows="dynamic", use_container_width=True)
        if st.button("부품 리스트 저장"):
            updated = edited_df.rename(columns=COL_MAP).to_dict("records")
            img_map = {p["name"]: p.get("image") for p in st.session_state.db["products"]}
            for p in updated:
                if p["name"] in img_map: p["image"] = img_map[p["name"]]
            st.session_state.db["products"] = updated
            save_data(st.session_state.db)
            st.success("저장됨")

    with tab2:
        st.subheader("🔗 세트(Set) 구성 및 이미지 관리")
        
        manage_type = st.radio("작업 선택", ["신규 세트 등록", "기존 세트 수정/삭제"], horizontal=True)
        set_category = st.selectbox("세트 카테고리", ["주배관세트", "가지관세트", "기타자재"])
        product_list = [p["name"] for p in st.session_state.db["products"]]
        
        # --- 신규 등록 ---
        if manage_type == "신규 세트 등록":
            c_new1, c_new2 = st.columns([1, 1])
            with c_new1:
                new_set_name = st.text_input("신규 세트 명칭")
                
                st.markdown("###### 📷 세트 대표 이미지")
                set_img_file = st.file_uploader("이미지 업로드 (선택)", type=["png", "jpg"], key="new_set_img")
                
            with c_new2:
                st.markdown("###### 🧩 구성품 담기")
                sc1, sc2, sc3 = st.columns([3, 2, 1])
                with sc1: s_comp = st.selectbox("부품", product_list, key="ns_sel")
                with sc2: s_qty = st.number_input("수량", 1, key="ns_qty")
                with sc3: 
                    if st.button("담기", key="ns_add"):
                        st.session_state.temp_set_recipe[s_comp] = s_qty
                
                st.write("▼ 구성품 목록", st.session_state.temp_set_recipe)

            if st.button("신규 세트 최종 저장", type="primary"):
                if new_set_name and st.session_state.temp_set_recipe:
                    if set_category not in st.session_state.db["sets"]:
                        st.session_state.db["sets"][set_category] = {}
                    
                    # 이미지 처리
                    img_data = None
                    if set_img_file:
                        img_data = process_image(set_img_file)
                        
                    st.session_state.db["sets"][set_category][new_set_name] = {
                        "recipe": st.session_state.temp_set_recipe,
                        "image": img_data
                    }
                    save_data(st.session_state.db)
                    st.success("저장 완료!")
                    st.session_state.temp_set_recipe = {}
                    st.rerun()
                else:
                    st.error("이름과 구성품은 필수입니다.")

        # --- 수정/삭제 ---
        else:
            current_sets = st.session_state.db["sets"].get(set_category, {})
            if not current_sets:
                st.warning("등록된 세트가 없습니다.")
            else:
                target_set = st.selectbox("세트 선택", list(current_sets.keys()))
                
                # 데이터 불러오기
                if st.button("불러오기"):
                    set_data = current_sets[target_set]
                    # 구조 호환성 체크
                    if "recipe" in set_data:
                        st.session_state.temp_set_recipe = set_data["recipe"].copy()
                    else:
                        st.session_state.temp_set_recipe = set_data.copy() # 구형 데이터
                    st.toast("불러오기 완료")

                # UI Layout
                col_edit1, col_edit2 = st.columns(2)
                
                with col_edit1:
                    st.markdown(f"#### **{target_set}** 편집")
                    
                    # 이미지 업데이트
                    st.markdown("###### 📷 이미지 변경")
                    # 현재 이미지 확인
                    curr_img = current_sets[target_set].get("image")
                    if curr_img:
                        st.image(curr_img, width=150, caption="현재 이미지")
                    
                    edit_img_file = st.file_uploader("새 이미지 업로드 (변경 시)", key="edit_set_img")

                with col_edit2:
                    st.markdown("###### 🧩 구성품 수정")
                    for comp, qty in list(st.session_state.temp_set_recipe.items()):
                        cc1, cc2, cc3 = st.columns([3, 1, 1])
                        cc1.text(f"• {comp}")
                        cc2.text(f"{qty}개")
                        if cc3.button("❌", key=f"del_{comp}"):
                            del st.session_state.temp_set_recipe[comp]
                            st.rerun()

                    ac1, ac2, ac3 = st.columns([3, 2, 1])
                    with ac1: add_sel = st.selectbox("부품", product_list, key="es_sel")
                    with ac2: add_qty = st.number_input("수량", 1, key="es_qty")
                    with ac3: 
                        if st.button("추가", key="es_add"):
                            st.session_state.temp_set_recipe[add_sel] = add_qty
                            st.rerun()
                
                st.markdown("---")
                bc1, bc2 = st.columns(2)
                with bc1:
                    if st.button("💾 수정사항 저장"):
                        # 이미지 유지 or 업데이트
                        final_img = curr_img
                        if edit_img_file:
                            final_img = process_image(edit_img_file)
                        
                        st.session_state.db["sets"][set_category][target_set] = {
                            "recipe": st.session_state.temp_set_recipe,
                            "image": final_img
                        }
                        save_data(st.session_state.db)
                        st.success("수정 완료!")
                        st.session_state.temp_set_recipe = {}
                        st.rerun()
                with bc2:
                    if st.button("🗑️ 삭제", type="primary"):
                        del st.session_state.db["sets"][set_category][target_set]
                        save_data(st.session_state.db)
                        st.session_state.temp_set_recipe = {}
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

    # === STEP 1: 입력 ===
    st.subheader("STEP 1. 설계 물량 입력")
    
    db_sets = st.session_state.db.get("sets", {})
    
    # 헬퍼 함수: 이미지+입력칸 그리드 생성
    def render_set_inputs(set_dict, key_prefix):
        if not set_dict:
            st.caption("등록된 세트가 없습니다.")
            return {}
        
        inputs = {}
        # 4열 그리드
        cols = st.columns(4)
        for i, (name, data) in enumerate(set_dict.items()):
            with cols[i % 4]:
                # 이미지 표시 (데이터 구조 체크)
                img_data = data.get("image") if isinstance(data, dict) else None
                if img_data:
                    st.image(img_data, use_container_width=True)
                else:
                    st.markdown(f"<div style='height:100px; background:#f0f0f0; display:flex; align-items:center; justify-content:center; color:#888;'>No Image</div>", unsafe_allow_html=True)
                
                # 입력칸
                inputs[name] = st.number_input(f"**{name}**", min_value=0, key=f"{key_prefix}_{name}")
        return inputs

    with st.expander("1️⃣ 주배관 세트 선택", expanded=True):
        input_main = render_set_inputs(db_sets.get("주배관세트", {}), "m")

    with st.expander("2️⃣ 가지관 세트 선택"):
        input_br = render_set_inputs(db_sets.get("가지관세트", {}), "b")
        
    with st.expander("3️⃣ 기타 자재 세트 선택"):
        input_etc = render_set_inputs(db_sets.get("기타자재", {}), "e")
        
    with st.expander("4️⃣ 배관 길이 입력"):
        main_pipes = [p for p in st.session_state.db["products"] if p.get("category") == "주배관"]
        br_pipes = [p for p in st.session_state.db["products"] if p.get("category") == "가지관"]
        c1, c2 = st.columns(2)
        with c1:
            sel_mp = st.selectbox("주배관 종류", [p["name"] for p in main_pipes]) if main_pipes else None
            len_mp = st.number_input("주배관 길이(m)", min_value=0)
        with c2:
            sel_bp = st.selectbox("가지관 종류", [p["name"] for p in br_pipes]) if br_pipes else None
            len_bp = st.number_input("가지관 길이(m)", min_value=0)

    if st.button("계산하기 (STEP 2)"):
        items = {}
        
        # 세트 분해 로직 (데이터 구조 변경 대응)
        def explode(inputs, set_db):
            for k, v in inputs.items():
                if v > 0:
                    set_data = set_db[k]
                    # V5.0: recipe 키 안에 구성품 있음
                    recipe = set_data.get("recipe", set_data) 
                    for part, qty in recipe.items():
                        items[part] = items.get(part, 0) + (qty * v)
                        
        explode(input_main, db_sets.get("주배관세트", {}))
        explode(input_br, db_sets.get("가지관세트", {}))
        explode(input_etc, db_sets.get("기타자재", {}))
        
        # 배관 롤수 계산
        def calc_rolls(p_name, length, p_list):
            if length > 0 and p_name:
                p_info = next((p for p in p_list if p["name"] == p_name), None)
                if p_info and p_info.get("len_per_unit", 0) > 0:
                    rolls = math.ceil(length / p_info["len_per_unit"])
                    items[p_name] = items.get(p_name, 0) + rolls
        
        calc_rolls(sel_mp, len_mp, main_pipes)
        calc_rolls(sel_bp, len_bp, br_pipes)
        
        st.session_state.quote_items = items
        st.session_state.quote_step = 2
        st.rerun()

    # === STEP 2: 검토 ===
    if st.session_state.quote_step >= 2:
        st.divider()
        st.subheader("STEP 2. 견적 상세 검토")
        
        view_option = st.radio(
            "💰 단가 보기 모드",
            ["기본 (소비자가만 노출)", "매입가 분석", "총판가1 분석", "총판가2 분석", "대리점가 분석"],
            horizontal=True
        )
        
        cost_key_map = {
            "매입가 분석": ("price_buy", "매입"),
            "총판가1 분석": ("price_d1", "총판1"),
            "총판가2 분석": ("price_d2", "총판2"),
            "대리점가 분석": ("price_agy", "대리점")
        }
        
        rows = []
        p_db = {p["name"]: p for p in st.session_state.db["products"]}
        
        for name, qty in st.session_state.quote_items.items():
            info = p_db.get(name, {})
            cons_price = info.get("price_cons", 0)
            cons_total = cons_price * qty
            
            row = {
                "제품사진": info.get("image", None),
                "제품명": name,
                "규격": info.get("spec", ""),
                "단위": info.get("unit", ""),
                "수량": qty,
                "소비자가": cons_price,
                "합계(소비자가)": cons_total
            }
            
            if view_option != "기본 (소비자가만 노출)":
                key, label = cost_key_map[view_option]
                cost_price = info.get(key, 0)
                cost_total = cost_price * qty
                profit = cons_total - cost_total
                profit_rate = (profit / cons_total * 100) if cons_total > 0 else 0
                
                row[f"{label}단가"] = cost_price
                row[f"{label}합계"] = cost_total
                row["이익금"] = profit
                row["이익률(%)"] = round(profit_rate, 1)
            
            rows.append(row)
            
        df = pd.DataFrame(rows)
        
        # 컬럼 정의
        base_cols = ["제품사진", "제품명", "규격", "단위", "수량"]
        if view_option == "기본 (소비자가만 노출)":
            final_cols = base_cols + ["소비자가", "합계(소비자가)"]
        else:
            key, label = cost_key_map[view_option]
            final_cols = base_cols + [f"{label}단가", f"{label}합계", "소비자가", "합계(소비자가)", "이익금", "이익률(%)"]
            
        st.dataframe(
            df[final_cols], 
            use_container_width=True, 
            hide_index=True, 
            column_config={
                "제품사진": st.column_config.ImageColumn("이미지", width="small"),
                "이익률(%)": st.column_config.NumberColumn(format="%.1f%%"),
                "소비자가": st.column_config.NumberColumn(format="%d"),
                "합계(소비자가)": st.column_config.NumberColumn(format="%d"),
            },
            height=500
        )
        
        st.markdown("---")
        
        # 추가 품목 & 비용
        c1, c2 = st.columns(2)
        with c1:
            st.markdown("##### ➕ 품목 개별 추가")
            add_p = st.selectbox("제품 선택", list(p_db.keys()), key="add_p")
            add_q = st.number_input("수량", 1, key="add_q")
            if st.button("품목 추가"):
                st.session_state.quote_items[add_p] = st.session_state.quote_items.get(add_p, 0) + add_q
                st.rerun()
                
        with c2:
            st.markdown("##### 🚛 배송비, 용역 등")
            svc_type = st.selectbox("항목 선택", ["배송비", "용역비", "기타"], key="svc_type")
            if svc_type == "기타":
                svc_name = st.text_input("항목명 입력", key="svc_manual")
            else:
                svc_name = svc_type
            svc_price = st.number_input("금액 (원)", 0, step=1000, key="svc_price")
            
            if st.button("비용 추가"):
                if svc_name:
                    st.session_state.services.append({"항목": svc_name, "금액": svc_price})
                    st.rerun()

        if st.session_state.services:
            st.write("▼ 추가 비용 목록")
            for i, s in enumerate(st.session_state.services):
                cols = st.columns([4, 2, 1])
                cols[0].text(s['항목'])
                cols[1].text(f"{s['금액']:,} 원")
                if cols[2].button("삭제", key=f"del_svc_{i}"):
                    st.session_state.services.pop(i)
                    st.rerun()

        if st.button("최종 견적서 발행 (STEP 3)"):
            st.session_state.quote_step = 3
            st.rerun()

    # === STEP 3: 최종 ===
    if st.session_state.quote_step == 3:
        st.divider()
        st.header("🏁 최종 견적서")
        
        p_db = {p["name"]: p for p in st.session_state.db["products"]}
        total_mat = 0
        final_data = []
        
        for name, qty in st.session_state.quote_items.items():
            info = p_db.get(name, {})
            price = info.get("price_cons", 0)
            amt = price * qty
            total_mat += amt
            final_data.append({
                "제품사진": info.get("image", None),
                "품목": name,
                "규격": info.get("spec", ""),
                "수량": qty,
                "단가": price,
                "금액": amt
            })
            
        df_final = pd.DataFrame(final_data)
        st.dataframe(
            df_final,
            use_container_width=True,
            hide_index=True,
            column_config={
                "제품사진": st.column_config.ImageColumn("이미지", width="small"),
                "단가": st.column_config.NumberColumn(format="%d"),
                "금액": st.column_config.NumberColumn(format="%d"),
            }
        )
        
        total_svc = sum([s["금액"] for s in st.session_state.services])
        grand_total = total_mat + total_svc
        
        if st.session_state.services:
            st.write("---")
            st.write("###### [추가 비용]")
            for s in st.session_state.services:
                st.write(f"- {s['항목']}: {s['금액']:,} 원")
        
        st.markdown(f"""
        <div style="text-align:right; margin-top:20px; padding:20px; background-color:#f9f9f9; border-radius:10px;">
            <div style="font-size:1.1em;">자재비 합계 : {total_mat:,} 원</div>
            <div style="font-size:1.1em;">+ 용역/배송 : {total_svc:,} 원</div>
            <hr>
            <div style="font-size:2em; font-weight:bold; color:#0055ff;">총 합계 : {grand_total:,} 원 <span style="font-size:0.5em; color:gray;">(VAT 별도)</span></div>
        </div>
        """, unsafe_allow_html=True)
        
        if st.button("처음으로"):
            st.session_state.quote_step = 1
            st.session_state.quote_items = {}
            st.session_state.services = []
            st.rerun()

import streamlit as st
import pandas as pd
import math
import os
import json

# ==========================================
# 1. 데이터 관리 및 초기화 (File System)
# ==========================================
DATA_FILE = "looperget_data.json"

# 초기 샘플 데이터 (파일이 없을 경우 생성됨)
DEFAULT_DATA = {
    "products": [
        {"code": "P001", "category": "부속", "name": "cccT", "spec": "50mm", "unit": "EA", "len_per_unit": 0, "price_buy": 5000, "price_d1": 6000, "price_d2": 7000, "price_agy": 8000, "price_cons": 10000},
        {"code": "P002", "category": "부속", "name": "스마트커플러4-2", "spec": "50mm", "unit": "EA", "len_per_unit": 0, "price_buy": 2000, "price_d1": 3000, "price_d2": 4000, "price_agy": 5000, "price_cons": 6000},
        {"code": "P003", "category": "부속", "name": "e호스밸브", "spec": "50mm", "unit": "EA", "len_per_unit": 0, "price_buy": 5000, "price_d1": 6000, "price_d2": 7000, "price_agy": 8000, "price_cons": 10000},
        {"code": "PIPE01", "category": "주배관", "name": "PVC호스", "spec": "50mm", "unit": "Roll", "len_per_unit": 50, "price_buy": 50000, "price_d1": 60000, "price_d2": 70000, "price_agy": 80000, "price_cons": 100000},
        {"code": "PIPE02", "category": "가지관", "name": "점적테이프", "spec": "10cm간격", "unit": "Roll", "len_per_unit": 1000, "price_buy": 35000, "price_d1": 40000, "price_d2": 45000, "price_agy": 50000, "price_cons": 60000},
    ],
    "sets": {
        "주배관세트": {
            "T분기 A타입": {"cccT": 1, "스마트커플러4-2": 2, "e호스밸브": 1},
            "T분기 B타입": {"cccT": 1, "스마트커플러4-2": 1, "e호스밸브": 2}
        },
        "가지관세트": {
            "점적연결 세트": {"스마트커플러4-2": 1, "e호스밸브": 1}
        },
        "기타자재": {
            "펌프세트": {"스마트커플러4-2": 2}
        }
    }
}

def load_data():
    if not os.path.exists(DATA_FILE):
        return DEFAULT_DATA
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def save_data(data):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)

# 데이터 로드
if "db" not in st.session_state:
    st.session_state.db = load_data()

# ==========================================
# 2. UI 및 페이지 구성
# ==========================================
st.set_page_config(layout="wide", page_title="루퍼젯 프로 매니저")
st.title("💧 루퍼젯 프로 매니저 (CPQ System)")

# 사이드바 네비게이션
mode = st.sidebar.radio("모드 선택", ["견적 작성 모드", "관리자 모드 (데이터 관리)"])

# ------------------------------------------
# [PAGE 1] 관리자 모드
# ------------------------------------------
if mode == "관리자 모드 (데이터 관리)":
    st.header("🛠 데이터 관리 센터")
    
    tab1, tab2 = st.tabs(["1. 품목(부품) 관리", "2. 세트(Set) 구성 관리"])
    
    with tab1:
        st.subheader("📦 전체 품목 리스트")
        st.caption("아래 표에서 직접 수정, 추가, 삭제가 가능합니다. 'Category'는 부속/주배관/가지관 등으로 구분하세요.")
        st.caption("※ 배관의 경우 '1롤당 길이(m)'를 'len_per_unit'에 반드시 입력해야 자동 계산됩니다.")
        
        # DataFrame으로 변환하여 에디터 표시
        df_products = pd.DataFrame(st.session_state.db["products"])
        edited_df = st.data_editor(df_products, num_rows="dynamic", use_container_width=True)
        
        if st.button("품목 변경사항 저장"):
            # 리스트 딕셔너리로 변환하여 저장
            st.session_state.db["products"] = edited_df.to_dict("records")
            save_data(st.session_state.db)
            st.success("품목 데이터가 저장되었습니다!")

    with tab2:
        st.subheader("🔗 세트(Set) 레시피 관리")
        
        set_category = st.selectbox("세트 카테고리 선택", ["주배관세트", "가지관세트", "기타자재"])
        current_sets = st.session_state.db["sets"].get(set_category, {})
        
        # 새 세트 추가 UI
        col1, col2 = st.columns([3, 1])
        with col1:
            new_set_name = st.text_input("신규/수정할 세트 명칭 (예: T분기 C타입)")
        with col2:
            st.write("") 
            st.write("") 
            
        # 세트 구성품 담기
        product_list = [p["name"] for p in st.session_state.db["products"]]
        
        st.write("▼ 세트 구성품 선택")
        c1, c2, c3 = st.columns([4, 2, 1])
        with c1:
            selected_comp = st.selectbox("추가할 부품", product_list)
        with c2:
            comp_qty = st.number_input("수량", min_value=1, value=1)
        with c3:
            add_comp = st.button("부품 담기")

        # 임시 세트 구성 저장소
        if "temp_set_recipe" not in st.session_state:
            st.session_state.temp_set_recipe = {}
            
        if add_comp:
            st.session_state.temp_set_recipe[selected_comp] = comp_qty
        
        # 현재 구성 중인 세트 보여주기
        st.write("📝 현재 구성중인 레시피:", st.session_state.temp_set_recipe)
        
        if st.button("세트 저장하기"):
            if new_set_name and st.session_state.temp_set_recipe:
                if set_category not in st.session_state.db["sets"]:
                    st.session_state.db["sets"][set_category] = {}
                st.session_state.db["sets"][set_category][new_set_name] = st.session_state.temp_set_recipe
                save_data(st.session_state.db)
                st.success(f"'{new_set_name}' 세트가 저장되었습니다.")
                st.session_state.temp_set_recipe = {} # 초기화
            else:
                st.error("세트 명칭과 구성품을 입력해주세요.")
                
        st.divider()
        st.write("📋 현재 등록된 세트 목록")
        st.json(current_sets)

# ------------------------------------------
# [PAGE 2] 견적 작성 모드
# ------------------------------------------
else:
    st.header("📑 스마트 견적 작성")
    
    # 세션에 견적 진행 단계 저장
    if "quote_step" not in st.session_state:
        st.session_state.quote_step = 1
        st.session_state.quote_items = [] # 계산된 개별 품목 리스트
        st.session_state.services = []    # 배송비, 시공비 등

    # === STEP 1: 필요 자재 입력 ===
    st.subheader("STEP 1. 자재 및 수량 입력")
    
    with st.expander("1️⃣ 주배관 연결 세트 입력", expanded=True):
        main_sets = st.session_state.db["sets"]["주배관세트"]
        input_main_sets = {}
        cols = st.columns(4)
        for i, (name, recipe) in enumerate(main_sets.items()):
            with cols[i % 4]:
                input_main_sets[name] = st.number_input(f"{name}", min_value=0, key=f"main_{name}")

    with st.expander("2️⃣ 가지관 연결 세트 입력"):
        branch_sets = st.session_state.db["sets"]["가지관세트"]
        input_branch_sets = {}
        cols = st.columns(4)
        for i, (name, recipe) in enumerate(branch_sets.items()):
            with cols[i % 4]:
                input_branch_sets[name] = st.number_input(f"{name}", min_value=0, key=f"br_{name}")

    with st.expander("3️⃣ 기타 자재 세트 입력"):
        etc_sets = st.session_state.db["sets"]["기타자재"]
        input_etc_sets = {}
        cols = st.columns(4)
        for i, (name, recipe) in enumerate(etc_sets.items()):
            with cols[i % 4]:
                input_etc_sets[name] = st.number_input(f"{name}", min_value=0, key=f"etc_{name}")

    with st.expander("4️⃣ 배관(Pipe) 길이 입력"):
        # 주배관/가지관 리스트업
        main_pipes = [p for p in st.session_state.db["products"] if p.get("category") == "주배관"]
        branch_pipes = [p for p in st.session_state.db["products"] if p.get("category") == "가지관"]
        
        c1, c2 = st.columns(2)
        with c1:
            sel_main_pipe = st.selectbox("주배관 종류 선택", [p["name"] for p in main_pipes])
            len_main_pipe = st.number_input("주배관 필요 길이 (m)", min_value=0)
        with c2:
            sel_branch_pipe = st.selectbox("가지관 종류 선택", [p["name"] for p in branch_pipes])
            len_branch_pipe = st.number_input("가지관 필요 길이 (m)", min_value=0)

    if st.button("계산 및 중간 검토 (STEP 2로 이동)"):
        # 계산 로직 수행
        calculated_items = {} # {품목명: 수량}

        # 1. 세트 해체 (Explosion)
        def explode_sets(inputs, recipe_db):
            for set_name, count in inputs.items():
                if count > 0:
                    recipe = recipe_db[set_name]
                    for part_name, qty in recipe.items():
                        calculated_items[part_name] = calculated_items.get(part_name, 0) + (qty * count)
        
        explode_sets(input_main_sets, main_sets)
        explode_sets(input_branch_sets, branch_sets)
        explode_sets(input_etc_sets, etc_sets)

        # 2. 배관 롤수 계산
        # 주배관
        if len_main_pipe > 0:
            p_info = next((p for p in main_pipes if p["name"] == sel_main_pipe), None)
            if p_info and p_info["len_per_unit"] > 0:
                rolls = math.ceil(len_main_pipe / p_info["len_per_unit"])
                calculated_items[sel_main_pipe] = calculated_items.get(sel_main_pipe, 0) + rolls
        # 가지관
        if len_branch_pipe > 0:
            p_info = next((p for p in branch_pipes if p["name"] == sel_branch_pipe), None)
            if p_info and p_info["len_per_unit"] > 0:
                rolls = math.ceil(len_branch_pipe / p_info["len_per_unit"])
                calculated_items[sel_branch_pipe] = calculated_items.get(sel_branch_pipe, 0) + rolls

        st.session_state.quote_items = calculated_items
        st.session_state.quote_step = 2
        st.rerun()

    # === STEP 2: 중간 검토 및 추가 ===
    if st.session_state.quote_step >= 2:
        st.divider()
        st.subheader("STEP 2. 견적 상세 검토 및 조정")
        
        # 1. 데이터 프레임 생성
        rows = []
        products_db = {p["name"]: p for p in st.session_state.db["products"]}
        
        for name, qty in st.session_state.quote_items.items():
            info = products_db.get(name, {})
            if info:
                row = {
                    "제품명": name,
                    "규격": info.get("spec", "-"),
                    "단위": info.get("unit", "EA"),
                    "수량": qty,
                    "매입단가": info.get("price_buy", 0),
                    "총판가1": info.get("price_d1", 0),
                    "총판가2": info.get("price_d2", 0),
                    "대리점가": info.get("price_agy", 0),
                    "소비자가": info.get("price_cons", 0),
                    # 초기 합계는 소비자가 기준
                    "합계": info.get("price_cons", 0) * qty
                }
                rows.append(row)
        
        df = pd.DataFrame(rows)

        # 2. 보기 옵션 (가격 공개 범위)
        st.markdown("**👁 가격 정보 노출 설정**")
        c1, c2, c3, c4 = st.columns(4)
        show_buy = c1.checkbox("매입가 보기")
        show_d1 = c2.checkbox("총판가1 보기")
        show_d2 = c3.checkbox("총판가2 보기")
        show_agy = c4.checkbox("대리점가 보기")

        # 컬럼 순서 및 노출 제어
        base_cols = ["제품명", "규격", "단위", "수량"]
        price_cols = []
        if show_buy: price_cols += ["매입단가"]
        if show_d1: price_cols += ["총판가1"]
        if show_d2: price_cols += ["총판가2"]
        if show_agy: price_cols += ["대리점가"]
        price_cols += ["소비자가", "합계"]
        
        # 합계 계산 로직 (매입가가 보이면 매입합계도 보여줄지 등은 여기서 커스텀 가능)
        # 현재 요구사항: 매입단가를 입력(보이게)하면 수량과 소비자가 사이에 노출.
        
        st.dataframe(df[base_cols + price_cols], use_container_width=True, hide_index=True)

        # 3. 추가 품목 및 용역비 입력
        st.markdown("---")
        c_add1, c_add2 = st.columns(2)
        
        with c_add1:
            st.markdown("##### ➕ 품목 개별 추가")
            all_p_names = [p["name"] for p in st.session_state.db["products"]]
            add_p_name = st.selectbox("추가할 제품 선택", all_p_names, key="add_single")
            add_p_qty = st.number_input("추가 수량", min_value=1, value=1, key="add_single_qty")
            if st.button("제품 추가"):
                st.session_state.quote_items[add_p_name] = st.session_state.quote_items.get(add_p_name, 0) + add_p_qty
                st.rerun()

        with c_add2:
            st.markdown("##### 🚛 용역/배송비 추가")
            svc_name = st.text_input("항목명 (예: 화물택배비, 시공비)", key="svc_name")
            svc_price = st.number_input("금액 (원)", min_value=0, step=1000, key="svc_price")
            if st.button("비용 추가"):
                st.session_state.services.append({"항목": svc_name, "금액": svc_price})
                st.success("추가되었습니다.")
                st.rerun()

        # 용역비 리스트 표시
        if st.session_state.services:
            st.write("▼ 추가된 용역/배송비")
            st.table(pd.DataFrame(st.session_state.services))

        if st.button("최종 견적 산출 (STEP 3)"):
            st.session_state.quote_step = 3
            st.rerun()

    # === STEP 3: 최종 금액 산출 ===
    if st.session_state.quote_step == 3:
        st.divider()
        st.header("🏁 최종 견적서")
        
        # 1. 최종 품목 리스트
        final_rows = []
        products_db = {p["name"]: p for p in st.session_state.db["products"]}
        grand_item_total = 0
        
        for name, qty in st.session_state.quote_items.items():
            info = products_db.get(name, {})
            unit_price = info.get("price_cons", 0)
            total_price = unit_price * qty
            grand_item_total += total_price
            
            final_rows.append({
                "품목명": name,
                "규격": info.get("spec", "-"),
                "단위": info.get("unit", "EA"),
                "수량": qty,
                "단가": f"{unit_price:,}",
                "금액": f"{total_price:,}"
            })
            
        df_final = pd.DataFrame(final_rows)
        st.table(df_final)
        
        # 2. 비용 합산
        svc_total = sum([s["금액"] for s in st.session_state.services])
        total_amt = grand_item_total + svc_total
        
        # 3. 최종 집계 보여주기
        st.markdown(f"""
        <div style="background-color:#f0f2f6; padding: 20px; border-radius: 10px;">
            <h3 style="text-align: right;">자재 합계 : {grand_item_total:,} 원</h3>
            <h3 style="text-align: right;">+ 배송/시공비 : {svc_total:,} 원</h3>
            <hr>
            <h1 style="text-align: right; color: #ff4b4b;">총 합계 : {total_amt:,} 원 (VAT 별도)</h1>
        </div>
        """, unsafe_allow_html=True)

        if st.button("처음부터 다시 작성"):
            st.session_state.quote_step = 1
            st.session_state.quote_items = {}
            st.session_state.services = []
            st.rerun()

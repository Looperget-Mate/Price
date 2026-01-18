import streamlit as st
import pandas as pd
import math
import os
import json
import io

# ==========================================
# 1. 데이터 관리 및 초기화
# ==========================================
DATA_FILE = "looperget_data.json"

# 초기 샘플 데이터
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

# 엑셀 컬럼 매핑 (한글 <-> 내부변수)
COL_MAP = {
    "품목코드": "code", "카테고리": "category", "제품명": "name", "규격": "spec", "단위": "unit",
    "1롤길이(m)": "len_per_unit", "매입단가": "price_buy", "총판가1": "price_d1",
    "총판가2": "price_d2", "대리점가": "price_agy", "소비자가": "price_cons"
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

# ==========================================
# 2. UI 구성
# ==========================================
st.set_page_config(layout="wide", page_title="루퍼젯 프로 매니저")
st.title("💧 루퍼젯 프로 매니저 V2.5")

mode = st.sidebar.radio("모드 선택", ["견적 작성 모드", "관리자 모드 (데이터 관리)"])

# ------------------------------------------
# [PAGE 1] 관리자 모드
# ------------------------------------------
if mode == "관리자 모드 (데이터 관리)":
    st.header("🛠 데이터 관리 센터")
    
    tab1, tab2 = st.tabs(["1. 품목(부품) 관리", "2. 세트(Set) 구성 관리"])
    
    with tab1:
        st.subheader("📦 품목 데이터 관리")
        
        # 1) 엑셀 다운로드/업로드 구역
        with st.expander("📂 엑셀로 대량 등록/다운로드 (클릭)", expanded=False):
            c1, c2 = st.columns(2)
            
            # 다운로드
            with c1:
                st.markdown("##### 1. 현재 데이터 다운로드 (백업/수정용)")
                df_current = pd.DataFrame(st.session_state.db["products"])
                # 한글 컬럼명으로 변환
                df_export = df_current.rename(columns=REV_COL_MAP)
                # 필요한 컬럼만 순서대로
                cols_order = list(COL_MAP.keys())
                # 데이터에 없는 컬럼이 있을 수 있으므로 교집합 처리
                valid_cols = [c for c in cols_order if c in df_export.columns]
                df_export = df_export[valid_cols]
                
                buffer = io.BytesIO()
                with pd.ExcelWriter(buffer, engine='xlsxwriter') as writer:
                    df_export.to_excel(writer, index=False, sheet_name='Sheet1')
                
                st.download_button(
                    label="📥 엑셀 파일 다운로드",
                    data=buffer.getvalue(),
                    file_name="looperget_products.xlsx",
                    mime="application/vnd.ms-excel"
                )

            # 업로드
            with c2:
                st.markdown("##### 2. 엑셀 업로드 (일괄 등록)")
                uploaded_file = st.file_uploader("수정한 엑셀 파일을 여기에 드래그하세요", type=['xlsx', 'xls'])
                if uploaded_file is not None:
                    try:
                        df_upload = pd.read_excel(uploaded_file)
                        # 컬럼 확인
                        required_cols = ["제품명", "소비자가"] # 최소 필수
                        if not all(col in df_upload.columns for col in required_cols):
                            st.error(f"엑셀에 필수 컬럼({required_cols})이 없습니다. 다운로드 받은 양식을 사용해주세요.")
                        else:
                            # 한글 -> 영문 변환
                            df_upload = df_upload.rename(columns=COL_MAP)
                            # NaN(빈값) 처리
                            df_upload = df_upload.fillna(0)
                            # 리스트로 변환하여 DB 업데이트
                            new_products = df_upload.to_dict('records')
                            
                            if st.button("데이터 덮어쓰기 (기존 데이터 삭제됨)"):
                                st.session_state.db["products"] = new_products
                                save_data(st.session_state.db)
                                st.success(f"{len(new_products)}건의 품목이 성공적으로 등록되었습니다!")
                                st.rerun()
                    except Exception as e:
                        st.error(f"오류 발생: {e}")

        st.divider()
        st.markdown("##### 📝 직접 수정 (에디터)")
        # DataFrame 에디터 표시
        df_products = pd.DataFrame(st.session_state.db["products"])
        # 보기 좋게 컬럼명 한글로 표시
        df_display = df_products.rename(columns=REV_COL_MAP)
        
        edited_df = st.data_editor(df_display, num_rows="dynamic", use_container_width=True, key="editor")
        
        if st.button("변경사항 저장 (에디터)"):
            # 다시 영문 컬럼으로 변환해서 저장
            df_to_save = edited_df.rename(columns=COL_MAP)
            st.session_state.db["products"] = df_to_save.to_dict("records")
            save_data(st.session_state.db)
            st.success("저장되었습니다!")

    with tab2:
        st.subheader("🔗 세트(Set) 레시피 관리")
        set_category = st.selectbox("세트 카테고리", ["주배관세트", "가지관세트", "기타자재"])
        current_sets = st.session_state.db["sets"].get(set_category, {})
        
        # 세트 추가 UI
        col1, col2 = st.columns([3, 1])
        with col1:
            new_set_name = st.text_input("세트 명칭 (예: T분기 C타입)")
        
        product_list = [p["name"] for p in st.session_state.db["products"]]
        
        c1, c2, c3 = st.columns([4, 2, 1])
        with c1:
            selected_comp = st.selectbox("구성품 선택", product_list)
        with c2:
            comp_qty = st.number_input("개수", min_value=1, value=1)
        with c3:
            add_comp = st.button("담기")

        if "temp_set_recipe" not in st.session_state:
            st.session_state.temp_set_recipe = {}
            
        if add_comp:
            st.session_state.temp_set_recipe[selected_comp] = comp_qty
        
        st.info(f"현재 구성: {st.session_state.temp_set_recipe}")
        
        if st.button("세트 저장"):
            if new_set_name and st.session_state.temp_set_recipe:
                if set_category not in st.session_state.db["sets"]:
                    st.session_state.db["sets"][set_category] = {}
                st.session_state.db["sets"][set_category][new_set_name] = st.session_state.temp_set_recipe
                save_data(st.session_state.db)
                st.success("저장 완료!")
                st.session_state.temp_set_recipe = {}
                st.rerun()

        st.write("📋 등록된 세트 목록")
        st.json(current_sets)

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
    st.subheader("STEP 1. 물량 입력")
    
    with st.expander("1️⃣ 주배관 세트", expanded=True):
        main_sets = st.session_state.db["sets"]["주배관세트"]
        input_main = {name: st.number_input(name, min_value=0, key=f"m_{name}") for name in main_sets}

    with st.expander("2️⃣ 가지관 세트"):
        br_sets = st.session_state.db["sets"]["가지관세트"]
        input_br = {name: st.number_input(name, min_value=0, key=f"b_{name}") for name in br_sets}
        
    with st.expander("3️⃣ 기타 자재"):
        etc_sets = st.session_state.db["sets"]["기타자재"]
        input_etc = {name: st.number_input(name, min_value=0, key=f"e_{name}") for name in etc_sets}
        
    with st.expander("4️⃣ 배관 길이"):
        main_pipes = [p for p in st.session_state.db["products"] if p.get("category") == "주배관"]
        br_pipes = [p for p in st.session_state.db["products"] if p.get("category") == "가지관"]
        
        c1, c2 = st.columns(2)
        with c1:
            sel_mp = st.selectbox("주배관", [p["name"] for p in main_pipes])
            len_mp = st.number_input("주배관 길이(m)", min_value=0)
        with c2:
            sel_bp = st.selectbox("가지관", [p["name"] for p in br_pipes])
            len_bp = st.number_input("가지관 길이(m)", min_value=0)

    if st.button("계산하기 (STEP 2)"):
        # 계산 로직
        items = {}
        def explode(inputs, recipe_db):
            for k, v in inputs.items():
                if v > 0:
                    for part, qty in recipe_db[k].items():
                        items[part] = items.get(part, 0) + (qty * v)
        explode(input_main, main_sets)
        explode(input_br, br_sets)
        explode(input_etc, etc_sets)
        
        # 배관 롤수
        def calc_rolls(p_name, length, p_list):
            if length > 0:
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
        st.subheader("STEP 2. 견적 상세 검토 및 이익률 분석")
        
        # 보기 옵션 (Radio Button으로 중복 선택 방지)
        view_option = st.radio(
            "💰 단가 보기 모드 선택",
            ["기본 (소비자가만 노출)", "매입가 분석", "총판가1 분석", "총판가2 분석", "대리점가 분석"],
            horizontal=True
        )
        
        # Mapping for cost selection
        cost_key_map = {
            "매입가 분석": ("price_buy", "매입"),
            "총판가1 분석": ("price_d1", "총판1"),
            "총판가2 분석": ("price_d2", "총판2"),
            "대리점가 분석": ("price_agy", "대리점")
        }
        
        # 데이터프레임 구성
        rows = []
        p_db = {p["name"]: p for p in st.session_state.db["products"]}
        
        for name, qty in st.session_state.quote_items.items():
            info = p_db.get(name, {})
            cons_price = info.get("price_cons", 0)
            cons_total = cons_price * qty
            
            row = {
                "제품명": name,
                "규격": info.get("spec", ""),
                "단위": info.get("unit", ""),
                "수량": qty,
                "소비자가": cons_price,
                "합계(소비자가)": cons_total
            }
            
            # 원가 분석 모드일 경우 추가 데이터 계산
            if view_option != "기본 (소비자가만 노출)":
                key, label = cost_key_map[view_option]
                cost_price = info.get(key, 0)
                cost_total = cost_price * qty
                profit = cons_total - cost_total
                profit_rate = (profit / cons_total * 100) if cons_total > 0 else 0
                
                # 컬럼 순서 조정을 위해 딕셔너리에 추가
                row[f"{label}단가"] = cost_price
                row[f"{label}합계"] = cost_total
                row["이익금"] = profit
                row["이익률(%)"] = round(profit_rate, 1)
            
            rows.append(row)
            
        df = pd.DataFrame(rows)
        
        # 컬럼 순서 정렬
        base_cols = ["제품명", "규격", "단위", "수량"]
        if view_option == "기본 (소비자가만 노출)":
            final_cols = base_cols + ["소비자가", "합계(소비자가)"]
        else:
            key, label = cost_key_map[view_option]
            # 요청하신 순서: 제품/규격/단위/수량/매입가/매입금/소비자가/소비자금/이익금/이익률
            final_cols = base_cols + [
                f"{label}단가", f"{label}합계", 
                "소비자가", "합계(소비자가)", 
                "이익금", "이익률(%)"
            ]
            
        # 숫자 포맷팅 (천단위 콤마) - 보여주기용 데이터프레임
        df_display = df[final_cols].copy()
        
        st.dataframe(
            df_display, 
            use_container_width=True, 
            hide_index=True,
            column_config={
                "이익률(%)": st.column_config.NumberColumn(format="%.1f%%"),
                # 금액 컬럼들에 콤마 적용은 Streamlit 최신버전 자동 적용되거나 
                # 필요시 format="%.0f" 등으로 지정 가능
            }
        )
        
        # 추가 입력 (이전과 동일)
        st.markdown("---")
        c1, c2 = st.columns(2)
        with c1:
            add_p = st.selectbox("추가 품목", list(p_db.keys()), key="add_p")
            add_q = st.number_input("수량", 1, key="add_q")
            if st.button("추가"):
                st.session_state.quote_items[add_p] = st.session_state.quote_items.get(add_p, 0) + add_q
                st.rerun()
        with c2:
            svc_n = st.text_input("용역/배송비 명", key="svc_n")
            svc_p = st.number_input("금액", 0, step=1000, key="svc_p")
            if st.button("비용 추가"):
                st.session_state.services.append({"항목": svc_n, "금액": svc_p})
                st.rerun()

        if st.session_state.services:
            st.table(pd.DataFrame(st.session_state.services))

        if st.button("최종 견적서 발행 (STEP 3)"):
            st.session_state.quote_step = 3
            st.rerun()

    # === STEP 3: 최종 ===
    if st.session_state.quote_step == 3:
        st.divider()
        st.header("🏁 최종 견적서")
        
        # 최종 산출 (소비자가 기준)
        p_db = {p["name"]: p for p in st.session_state.db["products"]}
        total_mat = 0
        final_data = []
        
        for name, qty in st.session_state.quote_items.items():
            price = p_db.get(name, {}).get("price_cons", 0)
            amt = price * qty
            total_mat += amt
            final_data.append([name, qty, f"{price:,}", f"{amt:,}"])
            
        st.table(pd.DataFrame(final_data, columns=["품목", "수량", "단가", "금액"]))
        
        total_svc = sum([s["금액"] for s in st.session_state.services])
        grand_total = total_mat + total_svc
        
        st.markdown(f"""
        <div style="text-align:right; font-size:1.2em;">
        <b>자재비 합계:</b> {total_mat:,} 원<br>
        <b>배송/시공비:</b> {total_svc:,} 원<br>
        <hr>
        <h1 style="color:blue;">총 합계: {grand_total:,} 원 (VAT 별도)</h1>
        </div>
        """, unsafe_allow_html=True)
        
        if st.button("처음으로"):
            st.session_state.quote_step = 1
            st.session_state.quote_items = {}
            st.session_state.services = []
            st.rerun()

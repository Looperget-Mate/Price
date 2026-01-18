import streamlit as st
import pandas as pd
import math

# --- 1. 데이터베이스 설정 (가격 및 세트 구성) ---
parts_db = {
    "cccT": {"매입": 5000, "총판1": 6000, "총판2": 7000, "대리점": 8000, "소비자": 10000},
    "스마트커플러4-2(50mm)": {"매입": 2000, "총판1": 3000, "총판2": 4000, "대리점": 5000, "소비자": 6000},
    "e호스밸브(50mm)": {"매입": 5000, "총판1": 6000, "총판2": 7000, "대리점": 8000, "소비자": 10000},
    "변형엘보": {"매입": 5000, "총판1": 6000, "총판2": 7000, "대리점": 8000, "소비자": 10000},
    "스마트커플러4-1(50mm)": {"매입": 3000, "총판1": 4000, "총판2": 5000, "대리점": 6000, "소비자": 7000},
    "PVC호스(50mm/1롤)": {"매입": 50000, "총판1": 60000, "총판2": 70000, "대리점": 80000, "소비자": 100000}
}

sets_recipe = {
    "1.T분기 a타입": {"cccT": 1, "스마트커플러4-2(50mm)": 2, "e호스밸브(50mm)": 1},
    "2.T분기 b타입": {"cccT": 1, "스마트커플러4-2(50mm)": 1, "e호스밸브(50mm)": 2},
    "3.각도연결 a타입": {"변형엘보": 1, "스마트커플러4-1(50mm)": 1, "스마트커플러4-2(50mm)": 1},
    "4.각도연결 b타입": {"변형엘보": 1, "스마트커플러4-1(50mm)": 1, "e호스밸브(50mm)": 1}
}

# --- 2. 웹 앱 화면 구성 (UI) ---
st.title("💧 루퍼젯 메이트 스마트 견적 시스템")
st.sidebar.header("1. 설계 물량 입력")

# 사용자 입력 받기
input_counts = {}
for set_name in sets_recipe.keys():
    input_counts[set_name] = st.sidebar.number_input(f"{set_name} 수량", min_value=0, value=0)

st.sidebar.markdown("---")
pipe_len = st.sidebar.number_input("주배관 총 길이(m)", min_value=0, value=0, step=10)
pipe_unit = 50  # 1롤당 길이

price_tier = st.sidebar.radio("2. 적용 단가 선택", ["소비자", "대리점", "총판1", "매입"])

# --- 3. 계산 로직 (백엔드) ---
if st.button("견적 산출하기"):
    total_parts = {}
    
    # (1) 세트 해체 및 부품 합산
    for set_name, count in input_counts.items():
        recipe = sets_recipe[set_name]
        for part, qty in recipe.items():
            total_parts[part] = total_parts.get(part, 0) + (qty * count)
    
    # (2) 호스 롤수 계산 (올림 처리)
    needed_rolls = math.ceil(pipe_len / pipe_unit)
    if needed_rolls > 0:
        total_parts["PVC호스(50mm/1롤)"] = total_parts.get("PVC호스(50mm/1롤)", 0) + needed_rolls

    # (3) 결과표 생성
    if not total_parts:
        st.warning("입력된 물량이 없습니다.")
    else:
        data = []
        grand_total = 0
        
        for part, qty in total_parts.items():
            unit_price = parts_db.get(part, {}).get(price_tier, 0)
            total_price = unit_price * qty
            grand_total += total_price
            data.append([part, qty, f"{unit_price:,}원", f"{total_price:,}원"])
            
        df = pd.DataFrame(data, columns=["부품명", "수량", "단가", "합계"])
        
        st.subheader(f"📊 견적 결과 ({price_tier}가 기준)")
        st.table(df)
        st.markdown(f"### 총 견적 금액: **{grand_total:,}원** (VAT 별도)")
        
        # 여유분 추가 제안 기능 (예시)
        st.info(f"💡 Tip: 호스 {needed_rolls}롤 주문 시, 연결 부속 여유분 5% 추가를 권장합니다.")

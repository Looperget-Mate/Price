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
import xlsxwriter 
from PIL import Image
from fpdf import FPDF
import gspread
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload

# ... (이전 설정 및 구글 연동 코드는 그대로 유지) ...

# ==========================================
# [수정] 자재 구성 명세서 PDF 생성 함수 (이미지 확대 및 추가자재 섹션 반영)
# ==========================================
def create_composition_pdf(set_cart, pipe_cart, quote_items, db_products, db_sets, quote_name):
    drive_file_map = get_drive_file_map()
    pdf = PDF()
    pdf.set_auto_page_break(False)
    pdf.add_page()
    
    has_font = os.path.exists(FONT_REGULAR)
    has_bold = os.path.exists(FONT_BOLD)
    font_name = 'NanumGothic' if has_font else 'Helvetica'
    b_style = 'B' if has_bold else ''
    
    # 0. 기본 계산 (추가 자재 산출용)
    baseline_counts = {}
    
    # 0-1. 세트에서 파생된 물량
    all_sets_db = {}
    for cat, val in db_sets.items():
        all_sets_db.update(val)
    for item in set_cart:
        s_name = item['name']
        s_qty = item['qty']
        if s_name in all_sets_db:
            recipe = all_sets_db[s_name].get("recipe", {})
            for p_code, p_qty in recipe.items():
                baseline_counts[str(p_code)] = baseline_counts.get(str(p_code), 0) + (p_qty * s_qty)
                
    # 0-2. 배관에서 파생된 물량(롤 단위)
    code_sums = {}
    for p_item in pipe_cart:
        c = p_item.get('code')
        if c: code_sums[c] = code_sums.get(c, 0) + p_item['len']
    for p_code, total_len in code_sums.items():
        prod_info = next((item for item in db_products if str(item["code"]) == str(p_code)), None)
        if prod_info:
            unit_len = prod_info.get("len_per_unit", 4)
            if unit_len <= 0: unit_len = 4
            qty = math.ceil(total_len / unit_len)
            baseline_counts[str(p_code)] = baseline_counts.get(str(p_code), 0) + qty

    # 0-3. 추가 자재(여분) 계산: 전체 견적 수량 - (세트+배관 수량)
    additional_items = {}
    for code, total_qty in quote_items.items():
        base_qty = baseline_counts.get(str(code), 0)
        diff = total_qty - base_qty
        if diff > 0:
            additional_items[code] = diff

    # --- PDF 출력 시작 ---
    pdf.set_font(font_name, b_style, 16)
    pdf.cell(0, 15, "자재 구성 명세서 (Material Composition Report)", align='C', new_x="LMARGIN", new_y="NEXT")
    pdf.set_font(font_name, '', 10)
    pdf.cell(0, 8, f"현장명: {quote_name}", align='R', new_x="LMARGIN", new_y="NEXT")
    pdf.ln(5)

    def check_page_break(h_needed):
        if pdf.get_y() + h_needed > 270:
            pdf.add_page()

    # --- 1. 부속 세트별 (이미지 2배 확대 적용) ---
    pdf.set_fill_color(220, 220, 220)
    pdf.set_font(font_name, b_style, 12)
    pdf.cell(0, 10, "1. 부속 세트 구성 (Fitting Sets)", border=1, fill=True, new_x="LMARGIN", new_y="NEXT")
    
    pdf.set_font(font_name, '', 10)
    # [변경] 이미지 컬럼 폭 확대 (20 -> 35), 이름 컬럼 축소 (100 -> 85)
    # [변경] 행 높이 확대 (15 -> 30)
    header_h = 8
    row_h = 30 
    
    pdf.set_fill_color(240, 240, 240)
    pdf.cell(35, header_h, "IMG", border=1, align='C', fill=True)
    pdf.cell(85, header_h, "세트명 (Set Name)", border=1, align='C', fill=True)
    pdf.cell(40, header_h, "구분", border=1, align='C', fill=True)
    pdf.cell(30, header_h, "수량", border=1, align='C', fill=True, new_x="LMARGIN", new_y="NEXT")

    for item in set_cart:
        check_page_break(row_h)
        name = item.get('name')
        qty = item.get('qty')
        stype = item.get('type')
        
        img_id = None
        for cat, sets in db_sets.items():
            if name in sets:
                img_id = sets[name].get('image')
                break
        
        img_b64 = download_image_by_id(img_id)
        
        x, y = pdf.get_x(), pdf.get_y()
        pdf.cell(35, row_h, "", border=1)
        if img_b64:
            try:
                img_data = img_b64.split(",", 1)[1]
                img_bytes = base64.b64decode(img_data)
                with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as tmp:
                    tmp.write(img_bytes); tmp_path = tmp.name
                
                # [변경] 이미지 크기 확대 (25x25 내외로 맞춤)
                pdf.image(tmp_path, x=x+5, y=y+2.5, w=25, h=25)
                os.unlink(tmp_path)
            except: pass
            
        pdf.set_xy(x+35, y)
        pdf.cell(85, row_h, name, border=1, align='L')
        pdf.cell(40, row_h, stype, border=1, align='C')
        pdf.cell(30, row_h, str(qty), border=1, align='C', new_x="LMARGIN", new_y="NEXT")
    
    pdf.ln(5)

    # --- 2. 배관별 ---
    pdf.set_font(font_name, b_style, 12)
    pdf.set_fill_color(220, 220, 220)
    check_page_break(20)
    pdf.cell(0, 10, "2. 배관 물량 (Pipe Quantities)", border=1, fill=True, new_x="LMARGIN", new_y="NEXT")
    
    pdf.set_font(font_name, '', 10)
    pdf.set_fill_color(240, 240, 240)
    pdf.cell(20, header_h, "IMG", border=1, align='C', fill=True)
    pdf.cell(100, header_h, "품목명 (Product Name)", border=1, align='C', fill=True)
    pdf.cell(40, header_h, "총 길이(m)", border=1, align='C', fill=True)
    pdf.cell(30, header_h, "롤 수(EA)", border=1, align='C', fill=True, new_x="LMARGIN", new_y="NEXT")

    pipe_summary = {}
    for p in pipe_cart:
        code = p.get('code')
        if not code: continue
        if code not in pipe_summary:
            pipe_summary[code] = {'len': 0, 'name': p.get('name'), 'spec': p.get('spec')}
        pipe_summary[code]['len'] += p.get('len', 0)

    for code, info in pipe_summary.items():
        check_page_break(15)
        prod_info = next((item for item in db_products if str(item["code"]) == str(code)), None)
        unit_len = prod_info.get("len_per_unit", 4) if prod_info else 4
        if unit_len <= 0: unit_len = 4
        rolls = math.ceil(info['len'] / unit_len)
        img_val = prod_info.get("image") if prod_info else None
        
        img_id = get_best_image_id(code, img_val, drive_file_map)
        img_b64 = download_image_by_id(img_id)

        x, y = pdf.get_x(), pdf.get_y()
        pdf.cell(20, 15, "", border=1)
        if img_b64:
            try:
                img_data = img_b64.split(",", 1)[1]
                img_bytes = base64.b64decode(img_data)
                with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as tmp:
                    tmp.write(img_bytes); tmp_path = tmp.name
                pdf.image(tmp_path, x=x+2, y=y+2, w=11, h=11)
                os.unlink(tmp_path)
            except: pass
            
        pdf.set_xy(x+20, y)
        pdf.cell(100, 15, f"{info['name']} ({info['spec']})", border=1, align='L')
        pdf.cell(40, 15, f"{info['len']} m", border=1, align='C')
        pdf.cell(30, 15, f"{rolls} 롤", border=1, align='C', new_x="LMARGIN", new_y="NEXT")

    pdf.ln(5)

    # --- [신규] 3. 추가 자재 목록 ---
    if additional_items:
        pdf.set_font(font_name, b_style, 12)
        pdf.set_fill_color(220, 220, 220)
        check_page_break(20)
        pdf.cell(0, 10, "3. 추가 자재 (Additional Components / Spares)", border=1, fill=True, new_x="LMARGIN", new_y="NEXT")
        
        pdf.set_font(font_name, '', 10)
        pdf.set_fill_color(240, 240, 240)
        pdf.cell(20, header_h, "IMG", border=1, align='C', fill=True)
        pdf.cell(130, header_h, "품목정보 (Name/Spec)", border=1, align='C', fill=True)
        pdf.cell(40, header_h, "추가 수량", border=1, align='C', fill=True, new_x="LMARGIN", new_y="NEXT")

        for code, qty in additional_items.items():
            check_page_break(15)
            prod_info = next((item for item in db_products if str(item["code"]) == str(code)), None)
            name = prod_info.get('name', code) if prod_info else code
            spec = prod_info.get('spec', '-') if prod_info else '-'
            img_val = prod_info.get('image') if prod_info else None
            
            img_id = get_best_image_id(code, img_val, drive_file_map)
            img_b64 = download_image_by_id(img_id)

            x, y = pdf.get_x(), pdf.get_y()
            pdf.cell(20, 15, "", border=1)
            if img_b64:
                try:
                    img_data = img_b64.split(",", 1)[1]
                    img_bytes = base64.b64decode(img_data)
                    with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as tmp:
                        tmp.write(img_bytes); tmp_path = tmp.name
                    pdf.image(tmp_path, x=x+2, y=y+2, w=11, h=11)
                    os.unlink(tmp_path)
                except: pass
                
            pdf.set_xy(x+20, y)
            pdf.cell(130, 15, f"{name} ({spec})", border=1, align='L')
            pdf.cell(40, 15, f"{int(qty)} EA", border=1, align='C', new_x="LMARGIN", new_y="NEXT")
        
        pdf.ln(5)

    # --- 4. 전체 자재 목록 ---
    pdf.set_font(font_name, b_style, 12)
    pdf.set_fill_color(220, 220, 220)
    check_page_break(20)
    # [변경] 번호 3 -> 4 (또는 3)
    idx_num = "4" if additional_items else "3"
    pdf.cell(0, 10, f"{idx_num}. 전체 자재 산출 목록 (Total Components)", border=1, fill=True, new_x="LMARGIN", new_y="NEXT")
    
    pdf.set_font(font_name, '', 10)
    pdf.set_fill_color(240, 240, 240)
    pdf.cell(20, header_h, "IMG", border=1, align='C', fill=True)
    pdf.cell(130, header_h, "품목정보 (Name/Spec)", border=1, align='C', fill=True)
    pdf.cell(40, header_h, "총 수량", border=1, align='C', fill=True, new_x="LMARGIN", new_y="NEXT")

    for code, qty in quote_items.items():
        check_page_break(15)
        prod_info = next((item for item in db_products if str(item["code"]) == str(code)), None)
        name = prod_info.get('name', code) if prod_info else code
        spec = prod_info.get('spec', '-') if prod_info else '-'
        img_val = prod_info.get('image') if prod_info else None
        
        img_id = get_best_image_id(code, img_val, drive_file_map)
        img_b64 = download_image_by_id(img_id)

        x, y = pdf.get_x(), pdf.get_y()
        pdf.cell(20, 15, "", border=1)
        if img_b64:
            try:
                img_data = img_b64.split(",", 1)[1]
                img_bytes = base64.b64decode(img_data)
                with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as tmp:
                    tmp.write(img_bytes); tmp_path = tmp.name
                pdf.image(tmp_path, x=x+2, y=y+2, w=11, h=11)
                os.unlink(tmp_path)
            except: pass
            
        pdf.set_xy(x+20, y)
        pdf.cell(130, 15, f"{name} ({spec})", border=1, align='L')
        pdf.cell(40, 15, f"{int(qty)} EA", border=1, align='C', new_x="LMARGIN", new_y="NEXT")

    return bytes(pdf.output())

# ==========================================
# [수정] 자재 구성 명세서 엑셀 생성 함수 (이미지 깔끔 정렬 및 추가자재 시트)
# ==========================================
def create_composition_excel(set_cart, pipe_cart, quote_items, db_products, db_sets, quote_name):
    output = io.BytesIO()
    workbook = xlsxwriter.Workbook(output, {'in_memory': True})
    drive_file_map = get_drive_file_map()
    
    fmt_header = workbook.add_format({'bold': True, 'bg_color': '#f0f0f0', 'border': 1, 'align': 'center', 'valign': 'vcenter'})
    fmt_center = workbook.add_format({'border': 1, 'align': 'center', 'valign': 'vcenter'})
    fmt_left = workbook.add_format({'border': 1, 'align': 'left', 'valign': 'vcenter'})

    # 추가 자재 계산 (엑셀용)
    baseline_counts = {}
    all_sets_db = {}
    for cat, val in db_sets.items(): all_sets_db.update(val)
    for item in set_cart:
        recipe = all_sets_db.get(item['name'], {}).get("recipe", {})
        for p, q in recipe.items(): baseline_counts[str(p)] = baseline_counts.get(str(p), 0) + (q * item['qty'])
    
    code_sums = {}
    for p_item in pipe_cart:
        c = p_item.get('code')
        if c: code_sums[c] = code_sums.get(c, 0) + p_item['len']
    for p_code, total_len in code_sums.items():
        prod_info = next((item for item in db_products if str(item["code"]) == str(p_code)), None)
        if prod_info:
            unit_len = prod_info.get("len_per_unit", 4)
            if unit_len <= 0: unit_len = 4
            baseline_counts[str(p_code)] = baseline_counts.get(str(p_code), 0) + math.ceil(total_len / unit_len)

    additional_items = {}
    for code, total_qty in quote_items.items():
        diff = total_qty - baseline_counts.get(str(code), 0)
        if diff > 0: additional_items[code] = diff

    # [중요] 엑셀 이미지 삽입 헬퍼 (깔끔하게 넣기)
    def insert_scaled_image(ws, row, col, img_b64):
        if not img_b64: 
            ws.write(row, col, "", fmt_center)
            return
        try:
            img_data = img_b64.split(",", 1)[1]
            img_bytes = base64.b64decode(img_data)
            
            with Image.open(io.BytesIO(img_bytes)) as pil_img:
                orig_w, orig_h = pil_img.size
            
            with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as tmp:
                tmp.write(img_bytes); tmp_path = tmp.name
            
            # 셀 크기 (대략 Pixel 기준, xlsxwriter 기본값 고려)
            # set_column(width) 15 ~= 110px
            # set_row(height) 80 ~= 106px
            cell_w_px = 110
            cell_h_px = 106
            
            scale_x = cell_w_px / orig_w
            scale_y = cell_h_px / orig_h
            scale = min(scale_x, scale_y) * 0.9 # 90% 채우기
            
            final_w = orig_w * scale
            final_h = orig_h * scale
            
            offset_x = (cell_w_px - final_w) / 2
            offset_y = (cell_h_px - final_h) / 2
            
            ws.insert_image(row, col, tmp_path, {
                'x_scale': scale, 'y_scale': scale,
                'x_offset': offset_x, 'y_offset': offset_y,
                'object_position': 1
            })
            # 파일 삭제는 나중에 일괄 처리 혹은 여기서 안함 (tempfile 이슈 방지 위해 loop 밖에서 삭제 권장되나 편의상 생략)
        except:
            ws.write(row, col, "Err", fmt_center)

    # Sheet 1: Sets
    ws1 = workbook.add_worksheet("부속세트")
    ws1.write(0, 0, "이미지", fmt_header)
    ws1.write(0, 1, "세트명", fmt_header)
    ws1.write(0, 2, "구분", fmt_header)
    ws1.write(0, 3, "수량", fmt_header)
    ws1.set_column(0, 0, 15)
    ws1.set_column(1, 1, 30)
    
    row = 1
    for item in set_cart:
        ws1.set_row(row, 80)
        name = item.get('name')
        img_id = None
        for cat, sets in db_sets.items():
            if name in sets:
                img_id = sets[name].get('image')
                break
        insert_scaled_image(ws1, row, 0, download_image_by_id(img_id))
        ws1.write(row, 1, name, fmt_left)
        ws1.write(row, 2, item.get('type'), fmt_center)
        ws1.write(row, 3, item.get('qty'), fmt_center)
        row += 1

    # Sheet 2: Pipes
    ws2 = workbook.add_worksheet("배관물량")
    ws2.write(0, 0, "이미지", fmt_header)
    ws2.write(0, 1, "품목명", fmt_header)
    ws2.write(0, 2, "총길이(m)", fmt_header)
    ws2.write(0, 3, "롤수", fmt_header)
    ws2.set_column(0, 0, 15)
    ws2.set_column(1, 1, 30)

    pipe_summary = {}
    for p in pipe_cart:
        code = p.get('code')
        if not code: continue
        if code not in pipe_summary:
            pipe_summary[code] = {'len': 0, 'name': p.get('name'), 'spec': p.get('spec')}
        pipe_summary[code]['len'] += p.get('len', 0)

    row = 1
    for code, info in pipe_summary.items():
        ws2.set_row(row, 80)
        prod_info = next((item for item in db_products if str(item["code"]) == str(code)), None)
        unit_len = prod_info.get("len_per_unit", 4) if prod_info else 4
        if unit_len <= 0: unit_len = 4
        rolls = math.ceil(info['len'] / unit_len)
        img_val = prod_info.get("image") if prod_info else None
        
        insert_scaled_image(ws2, row, 0, download_image_by_id(get_best_image_id(code, img_val, drive_file_map)))
        ws2.write(row, 1, f"{info['name']} ({info['spec']})", fmt_left)
        ws2.write(row, 2, info['len'], fmt_center)
        ws2.write(row, 3, rolls, fmt_center)
        row += 1

    # Sheet 3: Additional
    if additional_items:
        ws_add = workbook.add_worksheet("추가자재")
        ws_add.write(0, 0, "이미지", fmt_header)
        ws_add.write(0, 1, "품목명", fmt_header)
        ws_add.write(0, 2, "규격", fmt_header)
        ws_add.write(0, 3, "추가수량", fmt_header)
        ws_add.set_column(0, 0, 15)
        ws_add.set_column(1, 1, 30)
        
        row = 1
        for code, qty in additional_items.items():
            ws_add.set_row(row, 80)
            prod_info = next((item for item in db_products if str(item["code"]) == str(code)), None)
            name = prod_info.get('name', code) if prod_info else code
            spec = prod_info.get('spec', '-') if prod_info else '-'
            img_val = prod_info.get('image') if prod_info else None
            
            insert_scaled_image(ws_add, row, 0, download_image_by_id(get_best_image_id(code, img_val, drive_file_map)))
            ws_add.write(row, 1, name, fmt_left)
            ws_add.write(row, 2, spec, fmt_center)
            ws_add.write(row, 3, qty, fmt_center)
            row += 1

    # Sheet 4: Total
    ws3 = workbook.add_worksheet("전체자재")
    ws3.write(0, 0, "이미지", fmt_header)
    ws3.write(0, 1, "품목명", fmt_header)
    ws3.write(0, 2, "규격", fmt_header)
    ws3.write(0, 3, "총수량", fmt_header)
    ws3.set_column(0, 0, 15)
    ws3.set_column(1, 1, 30)

    row = 1
    for code, qty in quote_items.items():
        ws3.set_row(row, 80)
        prod_info = next((item for item in db_products if str(item["code"]) == str(code)), None)
        name = prod_info.get('name', code) if prod_info else code
        spec = prod_info.get('spec', '-') if prod_info else '-'
        img_val = prod_info.get('image') if prod_info else None
        
        insert_scaled_image(ws3, row, 0, download_image_by_id(get_best_image_id(code, img_val, drive_file_map)))
        ws3.write(row, 1, name, fmt_left)
        ws3.write(row, 2, spec, fmt_center)
        ws3.write(row, 3, qty, fmt_center)
        row += 1

    workbook.close()
    return output.getvalue()

# ... (나머지 메인 로직은 이전과 동일) ...

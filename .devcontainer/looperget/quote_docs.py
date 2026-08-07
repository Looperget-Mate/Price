# -*- coding: utf-8 -*-
"""루퍼젯 프로 매니저 — 견적서·구성표 출력 엔진 (PDF / Excel)

[V72, 2026-08-05] app.py L3852-5048에서 **기계적 추출**. 본문 로직 무변경.
⚠ 배포 단위 = app.py + aquanaris_layout.py + looperget/ 폴더 (셋은 항상 세트).

app.py가 bind()로 주입하는 것:
    FONT_REGULAR, FONT_BOLD    폰트 파일 경로 상수
    get_drive_file_map_deep    하위폴더 재귀 드라이브맵 (V15 §2-8)
    get_best_image_id          이미지 해석 우선순위       (V15 §2-9)
    download_image_by_id       Drive 이미지 다운로드
"""
import os
import io
import math
import base64
import tempfile

import xlsxwriter
from fpdf import FPDF
from PIL import Image

# ── app.py 주입 슬롯 — bind()가 채운다 ──────────────────────────────
FONT_REGULAR = "NanumGothic.ttf"
FONT_BOLD = "NanumGothic-Bold.ttf"
get_drive_file_map_deep = None
get_best_image_id = None
download_image_by_id = None


def bind(**fns):
    """app.py가 Drive·폰트 의존을 주입한다. import 직후 1회 호출."""
    globals().update(fns)


__all__ = [
    "PDF",
    "create_advanced_pdf", "create_quote_excel",
    "create_composition_pdf", "create_composition_excel",
    "bind",
]

# ==========================================
# 2. PDF 및 Excel 생성 엔진
# ==========================================
class PDF(FPDF):
    def header(self):
        header_font = 'Helvetica'; header_style = 'B'
        if os.path.exists(FONT_REGULAR):
            self.add_font('NanumGothic', '', FONT_REGULAR, uni=True)
            header_font = 'NanumGothic'
            if os.path.exists(FONT_BOLD): self.add_font('NanumGothic', 'B', FONT_BOLD, uni=True); header_style = 'B'
            else: header_style = ''
        # 제목 중앙 + 우측에 회사명
        self.set_font(header_font, header_style, 20)
        title_txt = self.title_text if hasattr(self, 'title_text') else '견 적 서'
        self.cell(130, 16, title_txt, align='C', border=0)
        self.set_font(header_font, header_style, 11)
        self.cell(60, 16, 'ShinJinChemTech', align='C', border=0, new_x="LMARGIN", new_y="NEXT")
        # 구분선
        self.set_draw_color(180, 180, 180)
        self.line(self.l_margin, self.get_y(), self.l_margin + 190, self.get_y())
        self.ln(2)
        self.set_draw_color(0, 0, 0)

    def footer(self):
        self.set_y(-25) 
        footer_font = 'Helvetica'; footer_style = 'B'
        if os.path.exists(FONT_REGULAR):
            footer_font = 'NanumGothic'
            if os.path.exists(FONT_BOLD): footer_style = 'B'
            else: footer_style = ''
        self.set_font(footer_font, footer_style, 12)
        self.cell(0, 5, "주식회사 신진켐텍", align='C', ln=True)
        self.set_font(footer_font, '', 9)
        self.cell(0, 5, "www.sjct.kr", align='C', ln=True)
        self.cell(0, 5, f'Page {self.page_no()}', align='C')

def create_advanced_pdf(final_data_list, service_items, quote_name, quote_date, form_type, price_labels, buyer_info, remarks):
    """
    견적서 PDF 생성 — 첨부 이미지 양식과 동일한 레이아웃
    """
    drive_file_map = get_drive_file_map_deep()
    pdf = PDF()
    pdf.title_text = '견 적 서'
    pdf.set_auto_page_break(False)
    pdf.add_page()

    has_font = os.path.exists(FONT_REGULAR)
    has_bold = os.path.exists(FONT_BOLD)
    font_name = 'NanumGothic' if has_font else 'Helvetica'
    b_style = 'B' if has_bold else ''

    L = pdf.l_margin
    PAGE_W = 190

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # [1] 2단 정보 테이블
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    LEFT_W  = 95
    RIGHT_W = 95
    LBL_W   = 24
    VAL_W   = LEFT_W - LBL_W
    H_ROW   = 7.0  # 행 높이 증가

    serial    = buyer_info.get('serial', '')
    recipient = buyer_info.get('recipient', '')
    ref       = buyer_info.get('ref', '')
    tel_buyer = buyer_info.get('phone', '')
    pay_cond  = buyer_info.get('pay_cond', '/')
    valid_period = buyer_info.get('valid_period', '견적 후 15일 이내')

    left_rows = [
        ("일련번호", serial if serial else quote_date.replace('-', '/') if quote_date else '/'),
        ("수  신", recipient or '/'),
        ("참  조", ref or '/'),
        ("TEL / FAX", tel_buyer or '/'),
        ("결재조건", pay_cond),
        ("유효기간", valid_period),
    ]

    RVAL_W = RIGHT_W - LBL_W
    right_rows = [
        ("사업자등록번호", "411-81-91898"),
        ("회사명/대표", "주식회사 신진켐텍 / 박형석"),
        ("주  소", "경기도 이천시 부발읍 황무로 1859-157"),
        ("업태/종목", "제조,도소매/산업용 밸브, 파이프 및 부속품 제조업"),
        ("담당자", buyer_info.get('manager', '문창근 부장')),
        ("TEL/FAX", "031-638-1809 / 031-635-1801"),
    ]

    y_info = pdf.get_y()

    for i, ((lbl, val), (rlbl, rval)) in enumerate(zip(left_rows, right_rows)):
        cy = y_info + i * H_ROW

        pdf.set_xy(L, cy)
        pdf.set_fill_color(240, 240, 240)
        pdf.set_font(font_name, b_style, 9)   # ↑ 8→9
        pdf.cell(LBL_W, H_ROW, f" {lbl}", border=1, fill=True)
        pdf.set_font(font_name, '', 9)         # ↑ 8→9
        pdf.cell(VAL_W, H_ROW, f" {val}", border=1)

        pdf.set_xy(L + LEFT_W, cy)
        pdf.set_fill_color(240, 240, 240)
        pdf.set_font(font_name, b_style, 8)   # ↑ 7→8
        pdf.cell(LBL_W, H_ROW, f" {rlbl}", border=1, fill=True)
        pdf.set_font(font_name, '', 8)         # ↑ 7→8
        pdf.cell(RVAL_W, H_ROW, f" {rval}", border=1)

    pdf.set_y(y_info + len(left_rows) * H_ROW)

    greeting = (
        "1.귀사의 일의 번창을 기원합니다.\n"
        "2.하기와 같이 견적드리오니 검토하기 바랍니다."
    )
    pdf.set_xy(L, pdf.get_y())
    pdf.set_font(font_name, '', 8.5)   # ↑ 7.5→8.5
    pdf.set_fill_color(255, 255, 255)
    pdf.multi_cell(LEFT_W, 5, greeting, border=1)

    pdf.ln(3)

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # [2] 품목 테이블
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    if form_type == "basic":
        COL_IMG  = 25
        COL_INFO = 63
        COL_UNIT = 13
        COL_QTY  = 13
        COL_P1   = 29
        COL_AMT  = 32
        COL_RMK  = 15
    else:
        COL_IMG  = 25
        COL_INFO = 55
        COL_UNIT = 10
        COL_QTY  = 10
        COL_P1   = 18
        COL_AMT1 = 22
        COL_P2   = 18
        COL_AMT2 = 22
        COL_PROF = 10

    def draw_table_header():
        pdf.set_fill_color(240, 240, 240)
        pdf.set_font(font_name, b_style, 9.5)   # ↑ 8.5→9.5
        H_HDR = 10
        pdf.cell(COL_IMG,  H_HDR, "이미지",    border=1, align='C', fill=True)
        pdf.cell(COL_INFO, H_HDR, "품목정보",   border=1, align='C', fill=True)
        pdf.cell(COL_UNIT, H_HDR, "단위",      border=1, align='C', fill=True)
        pdf.cell(COL_QTY,  H_HDR, "수량",      border=1, align='C', fill=True)
        if form_type == "basic":
            pdf.cell(COL_P1,  H_HDR, price_labels[0] if price_labels else "소비자가", border=1, align='C', fill=True)
            pdf.cell(COL_AMT, H_HDR, "금액",   border=1, align='C', fill=True)
            pdf.cell(COL_RMK, H_HDR, "비고",   border=1, align='C', fill=True, new_x="LMARGIN", new_y="NEXT")
        else:
            l1 = price_labels[0] if price_labels else "단가1"
            l2 = price_labels[1] if len(price_labels) > 1 else "단가2"
            pdf.set_font(font_name, b_style, 8)
            pdf.cell(COL_P1,   H_HDR, l1,     border=1, align='C', fill=True)
            pdf.cell(COL_AMT1, H_HDR, "금액",  border=1, align='C', fill=True)
            pdf.cell(COL_P2,   H_HDR, l2,     border=1, align='C', fill=True)
            pdf.cell(COL_AMT2, H_HDR, "금액",  border=1, align='C', fill=True)
            pdf.cell(COL_PROF, H_HDR, "이익율", border=1, align='C', fill=True, new_x="LMARGIN", new_y="NEXT")

    draw_table_header()

    sum_qty = 0; sum_a1 = 0; sum_a2 = 0; sum_profit = 0
    ITEM_H = 18  # ↑ 17→18

    for item in final_data_list:
        if pdf.get_y() + ITEM_H > 265:
            pdf.add_page()
            draw_table_header()

        x, y = pdf.get_x(), pdf.get_y()
        name = str(item.get("품목", "") or "")
        spec = str(item.get("규격", "-") or "-")
        code = str(item.get("코드", "") or "").strip().zfill(5)

        try: qty = int(float(item.get("수량", 0)))
        except: qty = 0

        img_id = get_best_image_id(code, item.get("image_data"), drive_file_map)
        img_b64 = download_image_by_id(img_id)

        sum_qty += qty
        try: p1 = int(float(item.get("price_1", 0)))
        except: p1 = 0
        a1 = p1 * qty
        sum_a1 += a1

        p2 = 0; a2 = 0; profit = 0; rate = 0
        if form_type == "profit":
            try: p2 = int(float(item.get("price_2", 0)))
            except: p2 = 0
            a2 = p2 * qty
            sum_a2 += a2
            profit = a2 - a1
            sum_profit += profit
            rate = (profit / a2 * 100) if a2 else 0

        # 이미지 셀
        pdf.cell(COL_IMG, ITEM_H, "", border=1)
        if img_b64:
            try:
                img_data_str = img_b64.split(",", 1)[1] if "," in img_b64 else img_b64
                img_bytes = base64.b64decode(img_data_str)
                with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as tmp:
                    tmp.write(img_bytes)
                    tmp_path = tmp.name
                img_sz = min(COL_IMG - 4, ITEM_H - 4, 14)
                pdf.image(tmp_path, x=x + (COL_IMG - img_sz) / 2,
                          y=y + (ITEM_H - img_sz) / 2, w=img_sz, h=img_sz)
                if os.path.exists(tmp_path): os.unlink(tmp_path)
            except: pass

        # 품목정보 셀
        pdf.set_xy(x + COL_IMG, y)
        pdf.cell(COL_INFO, ITEM_H, "", border=1)
        # 품목명 — 굵게 9pt
        pdf.set_xy(x + COL_IMG + 1.5, y + 1.5)
        pdf.set_font(font_name, b_style, 9)    # ↑ 7.5→9
        pdf.multi_cell(COL_INFO - 3, 4.2, name, align='L', max_line_height=4.2)
        # 규격
        pdf.set_xy(x + COL_IMG + 1.5, y + ITEM_H - 6.5)
        pdf.set_font(font_name, '', 7.5)        # ↑ 6.5→7.5
        pdf.cell(COL_INFO - 3, 3.2, spec, align='L')
        # 코드
        pdf.set_xy(x + COL_IMG + 1.5, y + ITEM_H - 3.5)
        pdf.set_font(font_name, '', 7.5)        # ↑ 6.5→7.5
        pdf.cell(COL_INFO - 3, 3.2, code, align='L')

        # 단위 / 수량
        pdf.set_xy(x + COL_IMG + COL_INFO, y)
        pdf.set_font(font_name, '', 9.5)        # ↑ 8→9.5
        pdf.cell(COL_UNIT, ITEM_H, str(item.get("단위", "EA") or "EA"), border=1, align='C')
        pdf.cell(COL_QTY,  ITEM_H, str(qty), border=1, align='C')

        # 단가 / 금액
        if form_type == "basic":
            pdf.set_font(font_name, '', 9)      # ↑ 명시 설정
            pdf.cell(COL_P1,  ITEM_H, f"{p1:,}", border=1, align='R')
            pdf.cell(COL_AMT, ITEM_H, f"{a1:,}", border=1, align='R')
            pdf.cell(COL_RMK, ITEM_H, "", border=1)
            pdf.ln()
        else:
            pdf.set_font(font_name, '', 8.5)
            pdf.cell(COL_P1,   ITEM_H, f"{p1:,}", border=1, align='R')
            pdf.cell(COL_AMT1, ITEM_H, f"{a1:,}", border=1, align='R')
            pdf.cell(COL_P2,   ITEM_H, f"{p2:,}", border=1, align='R')
            pdf.cell(COL_AMT2, ITEM_H, f"{a2:,}", border=1, align='R')
            pdf.set_font(font_name, b_style, 8)
            pdf.cell(COL_PROF, ITEM_H, f"{rate:.1f}%", border=1, align='C')
            pdf.ln()

    # 서비스 비용
    svc_total = 0
    if service_items:
        if pdf.get_y() + (len(service_items) * 7) + 10 > 265:
            pdf.add_page()
            pdf.ln(1)
        else:
            pdf.ln(1)
        pdf.set_fill_color(255, 255, 224)
        pdf.set_font(font_name, b_style, 9)
        pdf.cell(PAGE_W, 7, " [ 추가 비용 ]", border=1, fill=True, new_x="LMARGIN", new_y="NEXT")
        for s in service_items:
            svc_total += s['금액']
            pdf.set_font(font_name, '', 9)
            pdf.cell(PAGE_W - 35, 7, f"  {s['항목']}", border=1)
            pdf.cell(35, 7, f"{s['금액']:,} 원", border=1, align='R', new_x="LMARGIN", new_y="NEXT")

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # [3] 자재비 합계 행
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    if pdf.get_y() + 12 > 265:
        pdf.add_page()

    final_total = (sum_a1 if form_type == "basic" else sum_a2) + svc_total
    TOTAL_H = 11

    pdf.set_fill_color(230, 230, 230)
    pdf.set_font(font_name, b_style, 10)   # ↑ 9→10

    if form_type == "basic":
        label_w = COL_IMG + COL_INFO + COL_UNIT + COL_QTY + COL_P1
        pdf.cell(label_w, TOTAL_H, "자재비 합계", border=1, align='C', fill=True)
        pdf.cell(COL_AMT, TOTAL_H, f"{final_total:,}", border=1, align='R', fill=True)
        pdf.cell(COL_RMK, TOTAL_H, "", border=1, fill=True)
        pdf.ln()
    else:
        label_w = COL_IMG + COL_INFO + COL_UNIT + COL_QTY + COL_P1 + COL_AMT1 + COL_P2
        pdf.cell(label_w, TOTAL_H, "자재비 합계", border=1, align='C', fill=True)
        pdf.cell(COL_AMT2, TOTAL_H, f"{final_total:,}", border=1, align='R', fill=True)
        pdf.cell(COL_PROF, TOTAL_H, "", border=1, fill=True)
        pdf.ln()

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # [4] 특약사항 및 비고
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    if remarks:
        pdf.ln(2)
        if pdf.get_y() + 20 > 270:
            pdf.add_page()
        pdf.set_fill_color(240, 240, 240)
        pdf.set_font(font_name, b_style, 9.5)  # ↑ 8.5→9.5
        pdf.cell(PAGE_W, 8, "  특약사항 및 비고", border=1, fill=True, new_x="LMARGIN", new_y="NEXT")
        pdf.set_font(font_name, '', 9)          # ↑ 8→9
        pdf.set_fill_color(255, 255, 255)
        pdf.multi_cell(PAGE_W, 6, remarks, border=1)

    return bytes(pdf.output())

def create_quote_excel(final_data_list, service_items, quote_name, quote_date, form_type, price_labels, buyer_info, remarks):
    """
    견적서 Excel 생성
    ─ 사용자 지정 폰트 크기 기준 ─
    정보 레이블/값(업태 제외): 11pt  |  업태/종목 값: 10pt
    인사말: 11pt  |  헤더행(9행): 12pt
    품목정보: 12pt  |  단위/수량/단가/금액: 14pt
    자재비합계: 16pt  |  특약사항 헤더+내용: 14pt
    """
    output = io.BytesIO()
    workbook = xlsxwriter.Workbook(output, {'in_memory': True})
    ws = workbook.add_worksheet("견적서")
    drive_file_map = get_drive_file_map_deep()

    FN = '맑은 고딕'  # 기본 폰트

    def fmt(**kw):
        base = {'font_name': FN, 'valign': 'vcenter', 'border': 1}
        base.update(kw)
        return workbook.add_format(base)

    # ── 폰트 크기별 포맷 ──
    # 제목
    f_title    = fmt(bold=True, font_size=20, align='center', border=0)

    # 정보 영역 (레이블 굵게, 값 일반) — 11pt 기본
    f_lbl      = fmt(bold=True, bg_color='#F0F0F0', align='center', font_size=11, text_wrap=False)
    f_val_11   = fmt(align='left', font_size=11, text_wrap=False)          # 일반 정보값 11pt
    f_val_10   = fmt(align='left', font_size=10, text_wrap=False)          # 업태/종목 값 10pt (긴 텍스트)

    # 인사말 — 11pt
    f_greet    = fmt(align='left', font_size=11, text_wrap=True, border=1)

    # 테이블 헤더 (9행) — 12pt 굵게
    f_hdr      = fmt(bold=True, bg_color='#F0F0F0', align='center', font_size=12, text_wrap=True)

    # 품목정보 — 12pt (품목명 굵게, 규격·코드 보통)
    f_item_name = fmt(bold=True, align='left', font_size=12, text_wrap=True)

    # 단위 / 수량 / 단가 / 금액 — 14pt
    f_center_14 = fmt(align='center', font_size=14)
    f_num_14    = fmt(align='right',  font_size=14, num_format='#,##0')

    # 이미지 셀
    f_img_cell  = fmt(align='center', font_size=11)

    # 자재비 합계 — 16pt 굵게
    f_total_lbl = fmt(bold=True, bg_color='#E6E6E6', align='center', font_size=16)
    f_total_val = fmt(bold=True, bg_color='#E6E6E6', align='right',  font_size=16, num_format='#,##0')
    f_total_emp = fmt(bold=True, bg_color='#E6E6E6', align='center', font_size=16)

    # 추가비용
    f_svc_hdr  = fmt(bold=True, bg_color='#FFF9C4', align='center', font_size=13)
    f_svc_val  = fmt(align='left', font_size=12)
    f_svc_num  = fmt(align='right', font_size=12, num_format='#,##0')

    # 특약사항 — 14pt
    f_rmk_hdr  = fmt(bold=True, bg_color='#F0F0F0', align='center', font_size=14)
    f_rmk_val  = fmt(align='left', font_size=14, text_wrap=True)

    # ── 컬럼 구성 ──
    # basic : A(이미지) B(품목정보) C(단위) D(수량) E(단가) F(금액) G(비고)  → 7컬럼
    # profit: A B C D E F(금액1) G(단가2) H(금액2) I(이익율)               → 9컬럼
    #
    # 정보 테이블 열 역할 (basic 기준):
    #   col0(A)=좌레이블 | col1(B)=좌값(단독)
    #   col2~3(C~D)=우레이블 병합 | col4~6(E~G)=우값 병합
    if form_type == "basic":
        NUM_COLS = 7
        # A=14, B=25, C=6, D=8, E=10, F=13, G=10
        col_widths = [14, 25, 6, 8, 10, 13, 10]
        COL_IMG, COL_INFO, COL_UNIT, COL_QTY, COL_P1, COL_AMT, COL_RMK = range(7)
        LAST_COL = 6
    else:
        NUM_COLS = 9
        # A=14, B=25, C=6, D=8, E=10, F=13, G=10, H=13, I=10
        col_widths = [14, 25, 6, 8, 10, 13, 10, 13, 10]
        COL_IMG, COL_INFO, COL_UNIT, COL_QTY, COL_P1, COL_AMT1, COL_P2, COL_AMT2, COL_PROF = range(9)
        LAST_COL = 8

    for ci, cw in enumerate(col_widths):
        ws.set_column(ci, ci, cw)

    # 합계 금액 — shrink_to_fit 버전 포맷 (####방지)
    f_total_val_shrink = fmt(bold=True, bg_color='#E6E6E6', align='right',
                             font_size=16, num_format='#,##0', shrink=True)

    # 수량 / 소비자가 / 금액 — 14pt + shrink_to_fit (셀 폭 부족 시 자동 축소)
    f_center_14_shrink = fmt(align='center', font_size=14, shrink=True)
    f_num_14_shrink    = fmt(align='right',  font_size=14, num_format='#,##0', shrink=True)

    # A열(이미지 열) 폭을 픽셀로 환산: 14 chars * 7.5px/char ≈ 105px
    # 이미지가 이 셀 폭을 절대 넘지 않도록 cell_w_px를 A열 실제 폭에 맞춤
    IMG_COL_PX = 100  # A열 14 chars 기준 안전 픽셀 폭

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # ROW 0 : 제목
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    ws.merge_range(0, 0, 0, LAST_COL, '견 적 서', f_title)
    ws.set_row(0, 36)

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # ROW 1~6 : 정보 2단 테이블
    #   좌: col0(A)=레이블 단독 | col1(B)=값 단독
    #   우: col2~3(C~D)=레이블 병합, 가운데 | col4~LAST(E~)=값 병합, 왼쪽
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    serial    = buyer_info.get('serial', quote_date or '')
    recipient = buyer_info.get('recipient', '')
    ref       = buyer_info.get('ref', '')
    tel_buyer = buyer_info.get('phone', '/')
    pay_cond  = buyer_info.get('pay_cond', '/')
    valid_per = buyer_info.get('valid_period', '견적 후 15일 이내')
    manager   = buyer_info.get('manager', '')

    left_rows  = [
        ("일련번호",  serial or '/'),
        ("수  신",    recipient or '/'),
        ("참  조",    ref or '/'),
        ("TEL / FAX", tel_buyer or '/'),
        ("결재조건",  pay_cond),
        ("유효기간",  valid_per),
    ]
    right_rows = [
        ("사업자등록번호", "411-81-91898"),
        ("회사명/대표",   "주식회사 신진켐텍 / 박형석"),
        ("주  소",        "경기도 이천시 부발읍 황무로 1859-157"),
        ("업태/종목",     "제조,도소매/산업용 밸브, 파이프 및 부속품 제조업"),
        ("담당자",        manager),
        ("TEL/FAX",       "031-638-1809 / 031-635-1801"),
    ]

    # 컬럼 인덱스
    L_LBL   = 0          # 좌 레이블: A (단독)
    L_VAL   = 1          # 좌 값:     B (단독)
    R_LBL_S = 2          # 우 레이블 시작: C
    R_LBL_E = 3          # 우 레이블 끝:   D  → C~D 병합
    R_VAL_S = 4          # 우 값 시작: E
    R_VAL_E = LAST_COL   # 우 값 끝:   G(basic) or I(profit) → E~끝 병합

    for i, ((ll, lv), (rl, rv)) in enumerate(zip(left_rows, right_rows)):
        r = i + 1
        ws.set_row(r, 22)

        # 좌측 레이블(단독) / 값(단독)
        ws.write(r, L_LBL, ll, f_lbl)
        ws.write(r, L_VAL, lv, f_val_11)

        # 우측 레이블: C~D 병합, 가운데 정렬
        ws.merge_range(r, R_LBL_S, r, R_LBL_E, rl, f_lbl)

        # 우측 값: E~LAST 병합, 왼쪽 정렬
        # 업태/종목(i==3)은 10pt, 나머지 11pt
        rv_fmt = f_val_10 if i == 3 else f_val_11
        if R_VAL_S < R_VAL_E:
            ws.merge_range(r, R_VAL_S, r, R_VAL_E, rv, rv_fmt)
        else:
            ws.write(r, R_VAL_S, rv, rv_fmt)

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # ROW 7 : 인사말 — 11pt, 행 높이 36.4
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    greeting = "1.귀사의 일의 번창을 기원합니다.\n2.하기와 같이 견적드리오니 검토하기 바랍니다."
    ws.merge_range(7, 0, 7, LAST_COL, greeting, f_greet)
    ws.set_row(7, 36.4)

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # ROW 8 : 테이블 헤더 — 12pt
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    ws.set_row(8, 24)
    ws.write(8, COL_IMG,  "이미지", f_hdr)
    ws.write(8, COL_INFO, "품목정보", f_hdr)
    ws.write(8, COL_UNIT, "단위", f_hdr)
    ws.write(8, COL_QTY,  "수량", f_hdr)
    if form_type == "basic":
        ws.write(8, COL_P1,  price_labels[0] if price_labels else "소비자가", f_hdr)
        ws.write(8, COL_AMT, "금액", f_hdr)
        ws.write(8, COL_RMK, "비고", f_hdr)
    else:
        l1 = price_labels[0] if price_labels else "단가1"
        l2 = price_labels[1] if len(price_labels) > 1 else "단가2"
        ws.write(8, COL_P1,   l1,      f_hdr)
        ws.write(8, COL_AMT1, "금액",   f_hdr)
        ws.write(8, COL_P2,   l2,      f_hdr)
        ws.write(8, COL_AMT2, "금액",   f_hdr)
        ws.write(8, COL_PROF, "이익율", f_hdr)

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # ROW 9~ : 품목 데이터
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    ROW_H_ITEM = 72   # 품목 행 높이(이미지 충분히)
    data_row = 9
    total_a1 = 0; total_a2 = 0; svc_total = 0
    temp_files = []

    for item in final_data_list:
        ws.set_row(data_row, ROW_H_ITEM)

        try: qty = int(float(item.get("수량", 0)))
        except: qty = 0
        try: p1  = int(float(item.get("price_1", 0)))
        except: p1 = 0
        a1 = p1 * qty
        total_a1 += a1

        code = str(item.get("코드", "") or "").strip().zfill(5)
        img_id  = get_best_image_id(code, item.get("image_data"), drive_file_map)
        img_b64 = download_image_by_id(img_id)

        # 이미지 — 셀 안에서만 (가로·세로 침범 없음), 셀 내 최대 크기·중앙 배치
        ws.write(data_row, COL_IMG, "", f_img_cell)
        if img_b64:
            try:
                img_data_str = img_b64.split(",", 1)[1] if "," in img_b64 else img_b64
                img_bytes    = base64.b64decode(img_data_str)
                with Image.open(io.BytesIO(img_bytes)) as pil_img:
                    orig_w, orig_h = pil_img.size
                with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as tmp:
                    tmp.write(img_bytes); tmp_path = tmp.name
                    temp_files.append(tmp_path)

                # 엑셀 행 높이(pt) → 픽셀: 1pt = 4/3 px (96dpi 기준)
                # ROW_H_ITEM=72pt → 96px
                MARGIN = 4  # 상하좌우 여백(px)
                cell_w_px = int(14 * 7.5) - MARGIN * 2   # A열 14chars → ≈105px → 여백 제외 97px
                cell_h_px = int(ROW_H_ITEM * 4 / 3) - MARGIN * 2  # 72pt → 96px → 여백 제외 88px

                scale = min(cell_w_px / orig_w, cell_h_px / orig_h)
                fw = orig_w * scale
                fh = orig_h * scale

                # 중앙 정렬 offset (여백 + 남은 공간의 절반)
                x_off = MARGIN + int((cell_w_px - fw) / 2)
                y_off = MARGIN + int((cell_h_px - fh) / 2)

                ws.insert_image(data_row, COL_IMG, tmp_path, {
                    'x_scale':  scale,
                    'y_scale':  scale,
                    'x_offset': x_off,
                    'y_offset': y_off,
                    'object_position': 2,
                    'url': None
                })
            except:
                ws.write(data_row, COL_IMG, "No Img", f_img_cell)

        # 품목정보 (품목명\n규격\n코드) — 12pt 굵게
        item_text = f"{item.get('품목', '')}\n{item.get('규격', '')}\n{code}"
        ws.write(data_row, COL_INFO, item_text, f_item_name)

        # 단위 — 14pt
        ws.write(data_row, COL_UNIT, item.get("단위", "EA") or "EA", f_center_14)

        # 수량 / 단가 / 금액 — 14pt + shrink_to_fit
        if form_type == "basic":
            ws.write(data_row, COL_QTY,  qty, f_center_14_shrink)
            ws.write(data_row, COL_P1,   p1,  f_num_14_shrink)
            ws.write(data_row, COL_AMT,  a1,  f_num_14_shrink)
            ws.write(data_row, COL_RMK,  "",  f_img_cell)
        else:
            try: p2 = int(float(item.get("price_2", 0)))
            except: p2 = 0
            a2 = p2 * qty
            profit = a2 - a1
            rate = (profit / a2 * 100) if a2 else 0
            total_a2 += a2
            ws.write(data_row, COL_QTY,  qty,            f_center_14_shrink)
            ws.write(data_row, COL_P1,   p1,             f_num_14_shrink)
            ws.write(data_row, COL_AMT1, a1,             f_num_14_shrink)
            ws.write(data_row, COL_P2,   p2,             f_num_14_shrink)
            ws.write(data_row, COL_AMT2, a2,             f_num_14_shrink)
            ws.write(data_row, COL_PROF, f"{rate:.1f}%", f_center_14)

        data_row += 1

    # ── 추가 비용 ──
    if service_items:
        ws.set_row(data_row, 20)
        ws.merge_range(data_row, 0, data_row, LAST_COL, "[ 추가 비용 ]", f_svc_hdr)
        data_row += 1
        for s in service_items:
            ws.set_row(data_row, 20)
            amt_col = COL_AMT if form_type == "basic" else COL_AMT2
            if amt_col > 0:
                ws.merge_range(data_row, 0, data_row, amt_col - 1, s['항목'], f_svc_val)
            else:
                ws.write(data_row, 0, s['항목'], f_svc_val)
            ws.write(data_row, amt_col, s['금액'], f_svc_num)
            for c in range(amt_col + 1, NUM_COLS):
                ws.write(data_row, c, "", f_img_cell)
            svc_total += s['금액']
            data_row += 1

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # 자재비 합계 — 16pt, 행 높이 30
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    final_total = (total_a1 if form_type == "basic" else total_a2) + svc_total
    ws.set_row(data_row, 30)
    if form_type == "basic":
        ws.merge_range(data_row, 0, data_row, COL_P1, "자재비 합계", f_total_lbl)
        ws.write(data_row, COL_AMT, final_total, f_total_val_shrink)
        ws.write(data_row, COL_RMK, "",          f_total_emp)
    else:
        ws.merge_range(data_row, 0, data_row, COL_P2, "자재비 합계", f_total_lbl)
        ws.write(data_row, COL_AMT2, final_total, f_total_val_shrink)
        ws.write(data_row, COL_PROF, "",           f_total_emp)
    data_row += 1

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # 빈 행 (합계 ~ 특약사항 사이)
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    ws.set_row(data_row, 10)
    for c in range(NUM_COLS):
        ws.write(data_row, c, "", fmt(border=0))
    data_row += 1

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # 특약사항 및 비고 — 14pt, 가운데 정렬 헤더
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    if remarks:
        ws.set_row(data_row, 24)
        ws.merge_range(data_row, 0, data_row, LAST_COL, "특약사항 및 비고", f_rmk_hdr)
        data_row += 1
        line_count = max(remarks.count('\n') + 1, 2)
        ws.set_row(data_row, max(20 * line_count, 40))
        ws.merge_range(data_row, 0, data_row, LAST_COL, remarks, f_rmk_val)

    workbook.close()
    for f in temp_files:
        try:
            if os.path.exists(f): os.unlink(f)
        except: pass
    return output.getvalue()

def create_composition_pdf(set_cart, pipe_cart, final_data_list, db_products, db_sets, quote_name):
    drive_file_map = get_drive_file_map_deep()
    pdf = PDF()
    pdf.title_text = "자재 구성 명세서 (Composition Report)"
    pdf.set_auto_page_break(False)
    pdf.add_page()
    
    has_font = os.path.exists(FONT_REGULAR)
    has_bold = os.path.exists(FONT_BOLD)
    font_name = 'NanumGothic' if has_font else 'Helvetica'
    b_style = 'B' if has_bold else ''
    
    baseline_counts = {}
    all_sets_db = {}
    for cat, val in db_sets.items(): all_sets_db.update(val)
    
    for item in set_cart:
        recipe = all_sets_db.get(item['name'], {}).get("recipe", {})
        for p_code, p_qty in recipe.items():
            baseline_counts[str(p_code)] = baseline_counts.get(str(p_code), 0) + (p_qty * item['qty'])
            
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

    additional_items_list = []
    temp_baseline = baseline_counts.copy()

    for item in final_data_list:
        code = str(item.get("코드", "")).strip().zfill(5) if item.get("코드") else ""
        try: total_qty = int(float(item.get("수량", 0)))
        except: total_qty = 0
        name = item.get("품목", "")
        spec = item.get("규격", "")
        img_data = item.get("image_data", "")

        if code and code in temp_baseline:
            base_qty = temp_baseline[code]
            if total_qty > base_qty:
                diff = total_qty - base_qty
                additional_items_list.append({
                    "name": name, "spec": spec, "qty": diff, 
                    "code": code, "image": img_data
                })
                temp_baseline[code] = total_qty
            else:
                temp_baseline[code] -= total_qty
        else:
            if total_qty > 0:
                additional_items_list.append({
                    "name": name, "spec": spec, "qty": total_qty, 
                    "code": code, "image": img_data
                })

    pdf.set_font(font_name, '', 10)
    pdf.cell(0, 8, f"현장명: {quote_name}", align='R', new_x="LMARGIN", new_y="NEXT")
    pdf.ln(5)

    def check_page_break(h_needed):
        if pdf.get_y() + h_needed > 270:
            pdf.add_page()

    # 1. 부속 세트 구성
    pdf.set_fill_color(220, 220, 220)
    pdf.set_font(font_name, b_style, 12)
    pdf.cell(0, 10, "1. 부속 세트 구성 (Fitting Sets)", border=1, fill=True, new_x="LMARGIN", new_y="NEXT")
    
    header_h = 8
    # ── 컬럼 폭 재배분: 구분·수량 줄이고 세트명 늘림 ──
    col_w_img  = 40   # 이미지
    col_w_name = 105  # 세트명 + 구성품 목록 (↑ 70→105)
    col_w_type = 25   # 구분 (↓ 40→25)
    col_w_qty  = 20   # 수량 (↓ 30→20)
    # 합계 = 190

    pdf.set_fill_color(240, 240, 240)
    pdf.set_font(font_name, b_style, 9)
    pdf.cell(col_w_img,  header_h, "IMG",            border=1, align='C', fill=True)
    pdf.cell(col_w_name, header_h, "세트명 (Set Name)", border=1, align='C', fill=True)
    pdf.cell(col_w_type, header_h, "구분",            border=1, align='C', fill=True)
    pdf.cell(col_w_qty,  header_h, "수량",            border=1, align='C', fill=True, new_x="LMARGIN", new_y="NEXT")

    # 품목 코드 → 이름 맵
    prod_code_to_name = {str(p.get("code","")).strip().zfill(5): p.get("name","") for p in db_products}

    for item in set_cart:
        name  = item.get('name')
        qty   = item.get('qty')
        stype = item.get('type')

        # 세트의 레시피(구성품) 가져오기
        recipe = {}
        for cat, sets in db_sets.items():
            if name in sets:
                recipe = sets[name].get('recipe', {})
                break

        # 구성품 텍스트 (코드 → 이름+규격+코드 변환)
        recipe_lines = []
        for p_code, p_qty in recipe.items():
            norm_code = str(p_code).strip().zfill(5)
            p_name = prod_code_to_name.get(norm_code, str(p_code))
            # 규격 조회
            p_prod = next((p for p in db_products if str(p.get("code","")).strip().zfill(5) == norm_code), None)
            p_spec = p_prod.get("spec", "") if p_prod else ""
            spec_str = f" [{p_spec}]" if p_spec and p_spec != "-" else ""
            recipe_lines.append(f"  · {p_name}{spec_str}  ×{p_qty}  (#{norm_code})")
        recipe_text = "\n".join(recipe_lines)

        # 행 높이: 세트명 1줄 + 구성품 줄 수 기준
        n_lines = max(len(recipe_lines), 1)
        # 세트명 11pt(5mm) + 구성품 1줄당 4.5mm + 상하 여백 4mm
        row_h = max(5 + n_lines * 4.5 + 4, 22)

        check_page_break(row_h)

        # 이미지 셀
        img_id = None
        for cat, sets in db_sets.items():
            if name in sets:
                img_id = sets[name].get('image')
                break
        img_b64 = download_image_by_id(img_id)

        x, y = pdf.get_x(), pdf.get_y()
        pdf.cell(col_w_img, row_h, "", border=1)
        if img_b64:
            try:
                img_data = img_b64.split(",", 1)[1]
                img_bytes = base64.b64decode(img_data)
                with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as tmp:
                    tmp.write(img_bytes)
                    tmp_path = tmp.name
                img_sz = min(col_w_img - 6, row_h - 5, 32)
                pdf.image(tmp_path, x=x + (col_w_img - img_sz) / 2,
                          y=y + (row_h - img_sz) / 2, w=img_sz, h=img_sz)
                os.unlink(tmp_path)
            except: pass

        # 세트명 셀 — 세트명(굵게 11pt) + 구성품(9pt)
        pdf.set_xy(x + col_w_img, y)
        pdf.cell(col_w_name, row_h, "", border=1)

        # 세트명 텍스트 (굵게, 크게)
        pdf.set_xy(x + col_w_img + 2, y + 2)
        pdf.set_font(font_name, b_style, 11)
        pdf.cell(col_w_name - 4, 5.5, name, align='L')

        # 구성품 텍스트 (보통, 9pt)
        if recipe_text:
            pdf.set_xy(x + col_w_img + 2, y + 8)
            pdf.set_font(font_name, '', 8.5)
            pdf.multi_cell(col_w_name - 4, 4.5, recipe_text, align='L', max_line_height=4.5)

        # 구분 / 수량 셀
        pdf.set_xy(x + col_w_img + col_w_name, y)
        pdf.set_font(font_name, '', 10)
        pdf.cell(col_w_type, row_h, stype, border=1, align='C')
        pdf.cell(col_w_qty,  row_h, str(qty), border=1, align='C', new_x="LMARGIN", new_y="NEXT")

    pdf.ln(5)

    # 2. 배관 물량
    pdf.set_font(font_name, b_style, 12)
    pdf.set_fill_color(220, 220, 220)
    check_page_break(20)
    pdf.cell(0, 10, "2. 배관 물량 (Pipe Quantities)", border=1, fill=True, new_x="LMARGIN", new_y="NEXT")
    
    pdf.set_fill_color(240, 240, 240)
    pdf.set_font(font_name, b_style, 9)
    pdf.cell(22, header_h, "IMG", border=1, align='C', fill=True)
    pdf.cell(108, header_h, "품목명 (Product Name)", border=1, align='C', fill=True)
    pdf.cell(35, header_h, "총 길이(m)", border=1, align='C', fill=True)
    pdf.cell(25, header_h, "롤 수(EA)", border=1, align='C', fill=True, new_x="LMARGIN", new_y="NEXT")

    pipe_summary = {}
    for p in pipe_cart:
        code = p.get('code')
        if not code: continue
        if code not in pipe_summary:
            pipe_summary[code] = {'len': 0, 'name': p.get('name'), 'spec': p.get('spec')}
        pipe_summary[code]['len'] += p.get('len', 0)

    for code, info in pipe_summary.items():
        check_page_break(16)
        prod_info = next((item for item in db_products if str(item["code"]) == str(code)), None)
        unit_len = prod_info.get("len_per_unit", 4) if prod_info else 4
        if unit_len <= 0: unit_len = 4
        rolls = math.ceil(info['len'] / unit_len)
        img_val = prod_info.get("image") if prod_info else None
        
        img_id = get_best_image_id(code, img_val, drive_file_map)
        img_b64 = download_image_by_id(img_id)

        x, y = pdf.get_x(), pdf.get_y()
        pdf.cell(22, 16, "", border=1)
        if img_b64:
            try:
                img_data = img_b64.split(",", 1)[1]
                img_bytes = base64.b64decode(img_data)
                with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as tmp:
                    tmp.write(img_bytes)
                    tmp_path = tmp.name
                pdf.image(tmp_path, x=x+2, y=y+2, w=13, h=13)
                if os.path.exists(tmp_path):
                    os.unlink(tmp_path)
            except: pass
            
        pdf.set_xy(x+22, y)
        pdf.set_font(font_name, '', 10)
        pdf.cell(108, 16, f"{info['name']} ({info['spec']})", border=1, align='L')
        pdf.cell(35,  16, f"{info['len']} m", border=1, align='C')
        pdf.cell(25,  16, f"{rolls} 롤", border=1, align='C', new_x="LMARGIN", new_y="NEXT")

    pdf.ln(5)

    # 3. 추가 자재
    if additional_items_list:
        pdf.set_font(font_name, b_style, 12)
        pdf.set_fill_color(220, 220, 220)
        check_page_break(20)
        pdf.cell(0, 10, "3. 추가 자재 (Additional Components / Spares)", border=1, fill=True, new_x="LMARGIN", new_y="NEXT")
        
        pdf.set_fill_color(240, 240, 240)
        pdf.set_font(font_name, b_style, 9)
        pdf.cell(22, header_h, "IMG", border=1, align='C', fill=True)
        pdf.cell(133, header_h, "품목정보 (Name/Spec)", border=1, align='C', fill=True)
        pdf.cell(35, header_h, "추가 수량", border=1, align='C', fill=True, new_x="LMARGIN", new_y="NEXT")

        for item in additional_items_list:
            check_page_break(16)
            name = item['name']
            spec = item['spec'] if item['spec'] else '-'
            qty = item['qty']
            code = item.get('code')
            img_val = item.get('image')
            
            img_id = get_best_image_id(code, img_val, drive_file_map)
            img_b64 = download_image_by_id(img_id)

            x, y = pdf.get_x(), pdf.get_y()
            pdf.cell(22, 16, "", border=1)
            if img_b64:
                try:
                    img_data = img_b64.split(",", 1)[1]
                    img_bytes = base64.b64decode(img_data)
                    with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as tmp:
                        tmp.write(img_bytes)
                        tmp_path = tmp.name
                    pdf.image(tmp_path, x=x+2, y=y+2, w=13, h=13)
                    if os.path.exists(tmp_path):
                        os.unlink(tmp_path)
                except: pass
                
            pdf.set_xy(x+22, y)
            pdf.set_font(font_name, '', 10)
            pdf.cell(133, 16, f"{name} ({spec})", border=1, align='L')
            pdf.cell(35,  16, f"{int(qty)} EA", border=1, align='C', new_x="LMARGIN", new_y="NEXT")
        
        pdf.ln(5)

    # 4. 전체 자재
    pdf.set_font(font_name, b_style, 12)
    pdf.set_fill_color(220, 220, 220)
    check_page_break(20)
    idx_num = "4" if additional_items_list else "3"
    pdf.cell(0, 10, f"{idx_num}. 전체 자재 산출 목록 (Total Components)", border=1, fill=True, new_x="LMARGIN", new_y="NEXT")
    
    pdf.set_fill_color(240, 240, 240)
    pdf.set_font(font_name, b_style, 9)
    pdf.cell(22, header_h, "IMG", border=1, align='C', fill=True)
    pdf.cell(133, header_h, "품목정보 (Name/Spec)", border=1, align='C', fill=True)
    pdf.cell(35, header_h, "총 수량", border=1, align='C', fill=True, new_x="LMARGIN", new_y="NEXT")

    for item in final_data_list:
        try: qty = int(float(item.get("수량", 0)))
        except: qty = 0
        if qty == 0: continue

        check_page_break(16)
        name = item.get("품목", "")
        spec = item.get("규격", "-")
        code = item.get("코드", "")
        img_val = item.get("image_data")
        
        img_id = get_best_image_id(code, img_val, drive_file_map)
        img_b64 = download_image_by_id(img_id)

        x, y = pdf.get_x(), pdf.get_y()
        pdf.cell(22, 16, "", border=1)
        if img_b64:
            try:
                img_data = img_b64.split(",", 1)[1]
                img_bytes = base64.b64decode(img_data)
                with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as tmp:
                    tmp.write(img_bytes)
                    tmp_path = tmp.name
                pdf.image(tmp_path, x=x+2, y=y+2, w=13, h=13)
                if os.path.exists(tmp_path):
                    os.unlink(tmp_path)
            except: pass
            
        pdf.set_xy(x+22, y)
        pdf.set_font(font_name, '', 10)
        pdf.cell(133, 16, f"{name} ({spec})", border=1, align='L')
        pdf.cell(35,  16, f"{int(qty)} EA", border=1, align='C', new_x="LMARGIN", new_y="NEXT")

    return bytes(pdf.output())

def create_composition_excel(set_cart, pipe_cart, final_data_list, db_products, db_sets, quote_name):
    output = io.BytesIO()
    workbook = xlsxwriter.Workbook(output, {'in_memory': True})
    drive_file_map = get_drive_file_map_deep()
    
    fmt_header = workbook.add_format({'bold': True, 'bg_color': '#f0f0f0', 'border': 1, 'align': 'center', 'valign': 'vcenter'})
    fmt_center = workbook.add_format({'border': 1, 'align': 'center', 'valign': 'vcenter'})
    fmt_left = workbook.add_format({'border': 1, 'align': 'left', 'valign': 'vcenter'})

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

    additional_items_list = []
    temp_baseline = baseline_counts.copy()

    for item in final_data_list:
        code = str(item.get("코드", "")).strip().zfill(5) if item.get("코드") else ""
        try: total_qty = int(float(item.get("수량", 0)))
        except: total_qty = 0
        name = item.get("품목", "")
        spec = item.get("규격", "")
        img_data = item.get("image_data", "")

        if code and code in temp_baseline:
            base_qty = temp_baseline[code]
            if total_qty > base_qty:
                diff = total_qty - base_qty
                additional_items_list.append({"name": name, "spec": spec, "qty": diff, "code": code, "image": img_data})
                temp_baseline[code] = total_qty
            else:
                temp_baseline[code] -= total_qty
        else:
            if total_qty > 0:
                additional_items_list.append({"name": name, "spec": spec, "qty": total_qty, "code": code, "image": img_data})

    temp_files = []

    def insert_scaled_image(ws, row, col, img_b64):
        if not img_b64: 
            ws.write(row, col, "", fmt_center)
            return
        try:
            img_data = img_b64.split(",", 1)[1] if "," in img_b64 else img_b64
            img_bytes = base64.b64decode(img_data)
            
            with Image.open(io.BytesIO(img_bytes)) as pil_img:
                orig_w, orig_h = pil_img.size
                pil_img.close()
            
            with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as tmp:
                tmp.write(img_bytes)
                tmp_path = tmp.name
                temp_files.append(tmp_path)
            
            cell_w_px = 110
            cell_h_px = 106
            
            scale_x = cell_w_px / orig_w
            scale_y = cell_h_px / orig_h
            scale = min(scale_x, scale_y) * 0.9 
            
            final_w = orig_w * scale
            final_h = orig_h * scale
            
            offset_x = (cell_w_px - final_w) / 2
            offset_y = (cell_h_px - final_h) / 2
            
            ws.insert_image(row, col, tmp_path, {
                'x_scale': scale, 'y_scale': scale,
                'x_offset': offset_x, 'y_offset': offset_y,
                'object_position': 1
            })
        except:
            ws.write(row, col, "Err", fmt_center)

    ws1 = workbook.add_worksheet("부속세트")
    ws1.write(0, 0, "이미지", fmt_header)
    ws1.write(0, 1, "세트명", fmt_header)
    ws1.write(0, 2, "구성품 (품목명 / 규격 / 코드 / 수량)", fmt_header)
    ws1.write(0, 3, "구분", fmt_header)
    ws1.write(0, 4, "수량", fmt_header)
    ws1.set_column(0, 0, 15)
    ws1.set_column(1, 1, 22)
    ws1.set_column(2, 2, 55)
    ws1.set_column(3, 3, 12)
    ws1.set_column(4, 4, 8)

    # 엑셀용 구성품 포맷
    fmt_recipe = workbook.add_format({'border': 1, 'align': 'left', 'valign': 'top', 'text_wrap': True, 'font_size': 9})

    prod_code_to_info = {
        str(p.get("code","")).strip().zfill(5): p
        for p in db_products
    }

    row = 1
    for item in set_cart:
        name = item.get('name')
        # 세트 레시피 조회
        recipe = {}
        for cat, sets in db_sets.items():
            if name in sets:
                recipe = sets[name].get('recipe', {})
                break

        # 구성품 텍스트 조합
        recipe_lines = []
        for p_code, p_qty in recipe.items():
            norm = str(p_code).strip().zfill(5)
            p_info = prod_code_to_info.get(norm, {})
            p_name = p_info.get("name", norm)
            p_spec = p_info.get("spec", "")
            spec_str = f" [{p_spec}]" if p_spec and p_spec != "-" else ""
            recipe_lines.append(f"· {p_name}{spec_str}  #{norm}  ×{p_qty}")
        recipe_text = "\n".join(recipe_lines) if recipe_lines else "-"

        n_lines = max(len(recipe_lines), 1)
        row_h = max(80, n_lines * 18)
        ws1.set_row(row, row_h)

        img_id = None
        for cat, sets in db_sets.items():
            if name in sets:
                img_id = sets[name].get('image')
                break
        insert_scaled_image(ws1, row, 0, download_image_by_id(img_id))
        ws1.write(row, 1, name, fmt_left)
        ws1.write(row, 2, recipe_text, fmt_recipe)
        ws1.write(row, 3, item.get('type'), fmt_center)
        ws1.write(row, 4, item.get('qty'), fmt_center)
        row += 1

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

    if additional_items_list:
        ws_add = workbook.add_worksheet("추가자재")
        ws_add.write(0, 0, "이미지", fmt_header)
        ws_add.write(0, 1, "품목명", fmt_header)
        ws_add.write(0, 2, "규격", fmt_header)
        ws_add.write(0, 3, "추가수량", fmt_header)
        ws_add.set_column(0, 0, 15)
        ws_add.set_column(1, 1, 30)
        
        row = 1
        for item in additional_items_list:
            ws_add.set_row(row, 80)
            img_val = item.get('image')
            code = item.get('code')
            
            insert_scaled_image(ws_add, row, 0, download_image_by_id(get_best_image_id(code, img_val, drive_file_map)))
            ws_add.write(row, 1, item['name'], fmt_left)
            ws_add.write(row, 2, item['spec'], fmt_center)
            ws_add.write(row, 3, item['qty'], fmt_center)
            row += 1

    ws3 = workbook.add_worksheet("전체자재")
    ws3.write(0, 0, "이미지", fmt_header)
    ws3.write(0, 1, "품목명", fmt_header)
    ws3.write(0, 2, "규격", fmt_header)
    ws3.write(0, 3, "총수량", fmt_header)
    ws3.set_column(0, 0, 15)
    ws3.set_column(1, 1, 30)

    row = 1
    for item in final_data_list:
        try: qty = int(float(item.get("수량", 0)))
        except: qty = 0
        if qty == 0: continue
        
        ws3.set_row(row, 80)
        code = item.get("코드", "")
        img_val = item.get("image_data")
        
        insert_scaled_image(ws3, row, 0, download_image_by_id(get_best_image_id(code, img_val, drive_file_map)))
        ws3.write(row, 1, item.get("품목", ""), fmt_left)
        ws3.write(row, 2, item.get("규격", "-"), fmt_center)
        ws3.write(row, 3, qty, fmt_center)
        row += 1

    workbook.close()
    
    for f in temp_files:
        try: 
            if os.path.exists(f):
                os.unlink(f)
        except: pass
        
    return output.getvalue()

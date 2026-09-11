# -*- coding: utf-8 -*-
"""🏪 아쿠나리스 빌더 — 지역농협 관수코너 진열 시스템(Aqunaris®) · 입구 파일.

[AQ1 · 2026-09-11] 루퍼젯 프로매니저(app.py V107)의 「🏪 아쿠나리스」 모드를 별도 앱으로 분리.
  · 화면 본문은 app.py L4050-6133 을 **바이트 그대로** 옮겼다 — `if True:` 로 들여쓰기 보존(V47 방식) · 로직 무변경.
  · 공용(브랜드 UI·구글 연동·DB·로그인) = common/ · 아쿠나리스 전용 = aqunaris/ .
  · 🔴 looperget/(프로매니저 · 설계·견적·제안서)를 import 하지 않는다 — 시험으로 고정.
배포(같은 저장소 Looperget-Mate/Price · Streamlit 앱을 하나 더 만든다 · 메인 파일 = aqunaris_app.py):
  aqunaris_app.py + aqunaris/ + common/  (+ looperget_brand.py · requirements.txt · .streamlit/ 는 저장소에 이미 있음)
실행: streamlit run aqunaris_app.py
"""
import os
import streamlit as st
try:
    from streamlit_js_eval import streamlit_js_eval
    _HAS_JS_EVAL = True
except Exception:
    _HAS_JS_EVAL = False
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

AQ_APP_VER = "AQ1"   # [2026-09-11] 프로매니저 V107 에서 분리

from common.ui import *   # 브랜드 CSS·헤더·푸터 — 프로매니저와 같은 화면
apply_page("Aqunaris 빌더", "🏪")

from common.google import *
from common.db import *
from common.auth import *
gc, drive_service = refresh_services()   # 원본과 같이 매 실행 서비스 확인(캐시 TTL 재인증)

# ── 짝 검증 — 폴더가 없거나 구버전이면 크래시 대신 한국어로 안내하고 정지 ──
try:
    import common as _cm
    import aqunaris as _aqn
    _VERS = (int(getattr(_cm, "COMMON_VER", 0) or 0), int(getattr(_aqn, "AQN_VER", 0) or 0))
except Exception:
    _VERS = (0, 0)
if _VERS[0] < 1 or _VERS[1] < 1:
    st.error("🚨 **`common/`·`aqunaris/` 폴더가 없거나 구버전입니다** — aqunaris_app.py(AQ1)와 짝이 맞지 않습니다.\n\n"
             "GitHub `Looperget-Mate/Price`에 **`common/`·`aqunaris/` 폴더를 통째로** "
             "`aqunaris_app.py`와 함께 올린 뒤 재배포하세요.")
    st.stop()

from aqunaris.sheets import *
from aqunaris.layout import *   # [V66] 배치 엔진
if int(globals().get("AQ_LAYOUT_VER", 0) or 0) < 77:
    st.error("🚨 **aqunaris/layout.py가 구버전입니다** — aqunaris_app.py(AQ1)와 짝이 맞지 않습니다.")
    st.stop()

# [V72] 인쇄물(스티커·가이드북·배치도 PDF) — 시트·Drive·폰트 의존을 주입
from aqunaris import print_docs as _aqp
_aqp.bind(FONT_REGULAR=FONT_REGULAR, FONT_BOLD=FONT_BOLD,
          aq_err_str=aq_err_str,
          aq_load_items=aq_load_items, aq_load_sites=aq_load_sites,
          aq_load_boxes=aq_load_boxes,
          download_image_by_id=download_image_by_id)
from aqunaris.print_docs import *

# ==========================================
# 메인 로직 (DB · 로그인) — 프로매니저와 같은 화면
# ==========================================
if "db" not in st.session_state:
    with st.spinner("DB 연동 중..."): 
        st.session_state.db = load_data_from_sheet()

login_gate("AQUNARIS BUILDER")

render_brand_header("아쿠나리스 빌더")
with st.sidebar:
    st.markdown(f"**🏪 아쿠나리스 빌더** · {AQ_APP_VER}")
    if st.session_state.get("user_id"):
        st.caption(f"👤 {st.session_state.user_id}")
    render_app_switch("aqunaris")

if not aq_can("aqunaris"):
    st.error("🔒 이 계정에는 아쿠나리스 권한이 없습니다 — Users 시트 '권한'에 `aqunaris` 가 필요합니다.")
    st.stop()

if True:   # [분리] app.py(V107) L4050-6133 「🏪 아쿠나리스」 모드 본문 — 들여쓰기 보존(V47 방식) · 로직 무변경
    # ==========================================
    # [V41] 아쿠나리스(농협 관수코너) 모드 — Phase A 골격
    #  현황 / 진열 품목 브라우저 / 진열 공급 간이 견적. 전부 읽기 전용(시트 쓰기 없음).
    # ==========================================
    st.header("🏪 아쿠나리스 — 농협 관수코너")
    st.caption("지역농협 자재센터 진열·관리 시스템 (Aqunaris®) · 단가 정본 = Products 시트 · 진열 속성 = AQ_Items 시트")

    aq_items = aq_load_items()
    if not aq_items:
        _rerr = st.session_state.get("_aq_read_err", "")
        if "429" in _rerr or "Quota" in _rerr:
            st.warning("⏳ 구글 시트 분당 읽기 한도(무료 60회/분)를 잠시 초과했습니다. **약 1분 후 [다시 시도]**를 눌러주세요. 데이터는 안전하며, 다른 화면 사용에는 지장 없습니다.")
        else:
            st.warning("AQ_Items 시트를 읽지 못했습니다. Looperget_DB에 AQ_Items 시트가 있는지 확인하세요." + (f" (오류: {_rerr[:120]})" if _rerr else ""))
        if st.button("🔄 다시 시도", key="aq_retry"):
            aq_load_all.clear(); st.rerun()
    else:
        prod_by_code = {str(p.get("code", "")).zfill(5): p for p in st.session_state.db.get("products", [])}
        aq_groups = sorted({(r.get("진열분류") or "(미지정)") for r in aq_items})
        # [V42] 유연 상자 모델: 상자 마스터·수용량 축적 로드
        aq_boxes = aq_load_boxes()
        aq_box_names = [str(b.get("상자종류", "")).strip() for b in aq_boxes]
        aq_box_price = {}
        for _b in aq_boxes:
            _bn = str(_b.get("상자종류", "")).strip()
            try: aq_box_price[_bn] = int(float(str(_b.get("단가") or 0)))
            except Exception: aq_box_price[_bn] = 0
        aq_itembox = aq_load_itembox()
        aq_caps = aq_capacity_map(aq_itembox)

        if st.button("🔄 아쿠나리스 데이터 새로고침", key="aq_refresh"):
            aq_load_all.clear(); st.rerun()

        tab_stat, tab_items, tab_quote, tab_box, tab_site, tab_print = st.tabs(
            ["📊 현황", "🗄️ 진열 품목", "🧮 진열 공급 견적(간이)", "📦 상자·수용량", "🏗️ 사이트 설계", "🖨️ 인쇄물"])

        # ── [V52] 인쇄물 — 스티커·가이드북 자동 생성 (부속군 색상 중심 v2) ──
        with tab_print:
            st.markdown("##### 🖨️ 스티커 · 가이드북 자동 생성")
            st.caption("카드 = **부속군 색 프레임** + [제품명|규격] / [이미지|QR|농협 바코드] / [제품설명] — 섹션/단/열 표기 없음(색상 구분). "
                       "QR = AQ_Items `QR링크`(제품 사용법 쇼츠). [V73] 촬영 트랙 반영분은 실제 영상으로 열리고, "
                       "아직 촬영 안 된 품목만 자리표시로 남습니다 — `python tools/media_ingest.py`로 채웁니다.")
            _pr_bc_sel = st.radio("바코드 체계 (농협 선택)", ["표준바코드 (880 GS1)", "지역바코드 (21 인스토어)"],
                                  horizontal=True, key="aq_pr_bc")
            _pr_bc_mode = "표준" if _pr_bc_sel.startswith("표준") else "지역"
            _pr_img_on = st.checkbox("제품 이미지 포함 (드라이브에서 로드 — 첫 생성은 오래 걸릴 수 있음, 이후 캐시)",
                                     value=True, key="aq_pr_img")
            _pr_imgof = None
            if _pr_img_on:
                _pr_fmap = get_drive_file_map_deep()
                _pr_by_code = {str(r.get("품목코드", "")).strip().zfill(5): r for r in aq_items}
                def _pr_imgof(code, _fm=_pr_fmap, _bc=_pr_by_code):
                    _c9 = str(code).strip().zfill(5)
                    _iso9 = str((_bc.get(_c9, {}) or {}).get("이미지ISO", "") or "").strip()
                    if _iso9:                                   # [V53] ①등각(ISO)/등재 이미지 우선
                        _im9 = _aq_pil_from_any(download_image_by_id(_iso9))
                        if _im9 is not None: return _aq_trim_white(_im9)   # [V54] 흰 여백 크롭
                    _p9 = prod_by_code.get(_c9, {}) or {}       # ②차순위 — 드라이브 코드명/카탈로그 이미지
                    _fid9 = get_best_image_id(code, str(_p9.get("image_data") or _p9.get("image") or ""), _fm)
                    _im9 = _aq_pil_from_any(download_image_by_id(_fid9)) if _fid9 else None
                    return _aq_trim_white(_im9) if _im9 is not None else None

            # ── [V54] 대상 사이트 (스티커·가이드북 공통) — 농협 선택 시 확정 배치 품목·변경된 상자 기준 ──
            _pr_site_opts = ["(전체 품목)"] + [str(s.get("농협명", "")).strip()
                                           for s in aq_load_sites() if str(s.get("농협명", "")).strip()]
            _pr_site = st.selectbox("대상 사이트 — 농협 선택 시 그 농협의 **확정 배치 품목·상자 기준**으로 스티커·가이드북 생성",
                                    _pr_site_opts, key="aq_pr_site")
            _AQ_BOX2ST = {"6호": "80", "3호": "98", "431-1호": "160", "432호": "160"}   # 상자→스티커 용지
            _sp_items, _sp_assign = {}, {}
            if _pr_site != "(전체 품목)":
                for _srow9 in aq_load_sites():
                    if str(_srow9.get("농협명", "")).strip() == _pr_site:
                        try:
                            _pl9 = json.loads(str(_srow9.get("배치JSON") or "{}"))
                            if isinstance(_pl9, dict):
                                _sp_items = _pl9.get("items", {}) if isinstance(_pl9.get("items", {}), dict) else {}
                                _sp_assign = _pl9.get("assign", {}) if isinstance(_pl9.get("assign", {}), dict) else {}
                        except Exception:
                            pass
                if not _sp_assign:
                    st.info(f"'{_pr_site}'에 저장된 확정 배치가 없어 전체 품목 기준으로 동작합니다 — 사이트 설계에서 배치 후 💾 저장하세요.")

            st.markdown("**📦 부품상자 스티커** — 부속군에서 골라 **체크한 품목만** 생성 · 이미지 ①등각(ISO) ②제품 사진")
            st.caption("용지: " + " / ".join(AQ_STICKER_SPEC[s]["label"] for s in ("80", "98", "160"))
                       + " — 기본 = 품목의 **상자** 기준 자동 결정(농협 선택 시 그 농협에 저장된 변경 상자 기준). "
                         "[V59] 아래 표의 **용지 칸을 품목별로 직접 변경**할 수도 있습니다.")
            _pr_targets = []
            for r in aq_items:
                _c9t = str(r.get("품목코드", "")).strip().zfill(5)
                if _sp_assign:   # 농협 확정 배치 품목만 + 사이트의 상자 오버라이드 반영
                    _a9t = _sp_assign.get(_c9t)
                    if not isinstance(_a9t, dict) or str(_a9t.get("rack", "")).startswith("🅥"):
                        continue
                    _bx9 = str((_sp_items.get(_c9t, {}) or {}).get("box") or r.get("기본상자") or "").strip()
                else:
                    _bx9 = str(r.get("기본상자") or "").strip()
                _sz9 = _AQ_BOX2ST.get(_bx9) or (str(r.get("스티커", "")).strip()
                                                if str(r.get("스티커", "")).strip() in AQ_STICKER_SPEC else "")
                if not _sz9:
                    continue
                _pr_targets.append({"품목코드": _c9t, "품목명": str(r.get("품목명_AQ", "") or ""),
                                    "규격": str(r.get("규격_AQ", "") or ""),
                                    "부속군": str(r.get("진열분류", "") or "(미지정)"),
                                    "상자": _bx9 or "-", "용지": AQ_STICKER_SPEC[_sz9]["label"], "_sz": _sz9})
            if not _pr_targets:
                st.info("스티커 대상 품목이 없습니다 — 상자(6호/3호/431-1호/432호) 또는 AQ_Items 스티커 컬럼을 확인하세요.")
            else:
                _pg_all9 = sorted({t["부속군"] for t in _pr_targets})
                _pr_gsel = st.multiselect("부속군 필터", _pg_all9, default=_pg_all9, key=f"aq_pr_gsel_{_pr_site}")
                _view9 = [t for t in _pr_targets if t["부속군"] in (_pr_gsel or _pg_all9)]
                if "aq_pr_pick_ver" not in st.session_state: st.session_state["aq_pr_pick_ver"] = 0
                _pc1, _pc2, _pc3 = st.columns([1, 1, 4])
                if _pc1.button("✅ 전체 선택", key="aq_pr_all"):
                    st.session_state["aq_pr_pick_def"] = True
                    st.session_state["aq_pr_pick_ver"] += 1
                    st.rerun()
                if _pc2.button("⬜ 전체 해제", key="aq_pr_none"):
                    st.session_state["aq_pr_pick_def"] = False
                    st.session_state["aq_pr_pick_ver"] += 1
                    st.rerun()
                if not _view9:
                    st.info("부속군 필터에 해당하는 품목이 없습니다.")
                    df_pick_ed = None
                else:
                    _def9 = st.session_state.get("aq_pr_pick_def", True)
                    _df_pick = pd.DataFrame([{"선택": _def9, **{k: t[k] for k in ("품목코드", "품목명", "규격", "부속군", "상자", "용지")}}
                                             for t in _view9])
                    df_pick_ed = st.data_editor(
                        _df_pick, hide_index=True, height=290,
                        key=f"aq_pr_pick_{_pr_site}_{st.session_state['aq_pr_pick_ver']}",
                        disabled=["품목코드", "품목명", "규격", "부속군", "상자"],
                        column_config={"선택": st.column_config.CheckboxColumn("선택", help="체크한 품목만 스티커 생성"),
                                       "용지": st.column_config.SelectboxColumn(   # [V59] 품목별 라벨(용지) 변경
                                           "용지", options=[AQ_STICKER_SPEC[k]["label"] for k in ("80", "98", "160")],
                                           help="기본 = 상자 기준 자동. 품목별로 다른 라벨 용지로 바꿔 생성할 수 있습니다.")})
                _sel_codes9 = set()
                _sz_of9 = {t["품목코드"]: t["_sz"] for t in _pr_targets}
                if df_pick_ed is not None:
                    _lbl2sz9 = {AQ_STICKER_SPEC[k]["label"]: k for k in AQ_STICKER_SPEC}
                    for _, _row9 in df_pick_ed.iterrows():
                        _c9p = str(_row9["품목코드"]).strip().zfill(5)
                        if bool(_row9["선택"]): _sel_codes9.add(_c9p)
                        _szp9 = _lbl2sz9.get(str(_row9.get("용지") or "").strip())
                        if _szp9: _sz_of9[_c9p] = _szp9   # [V59] 표에서 바꾼 용지 우선
                st.caption(f"선택 {len(_sel_codes9)} / 표시 {len(_view9)} / 대상 {len(_pr_targets)}품목"
                           + (f" · **{_pr_site} 확정 배치 기준**" if _sp_assign else " · 전체 품목 기준"))
                if st.button("🖨️ 선택 품목 스티커 PDF 생성", key="aq_pr_st_go", type="primary"):
                    with st.spinner("스티커 생성 중..."):
                        try:
                            _by_code9 = {str(r.get("품목코드", "")).strip().zfill(5): r for r in aq_items}
                            _outs9 = {}
                            for _s9 in ("80", "98", "160"):
                                _grp9 = [_by_code9[c] for c in sorted(_sel_codes9)
                                         if _sz_of9.get(c) == _s9 and c in _by_code9]
                                if _grp9:
                                    _outs9[_s9] = (aq_sticker_pdf_bytes(_grp9, _s9, _pr_bc_mode, _pr_imgof), len(_grp9))
                            st.session_state["aq_pr_st_out"] = _outs9
                            if not _outs9:
                                st.warning("선택된 품목이 없습니다 — 체크박스를 확인하세요.")
                        except Exception as e:
                            st.error(f"스티커 생성 실패: {aq_err_str(e)}")
            for _s9, (_b9, _n9) in (st.session_state.get("aq_pr_st_out") or {}).items():
                st.download_button(f"⬇️ {AQ_STICKER_SPEC[_s9]['label']} — {_n9}품목 ({len(_b9) // 1024}KB)", data=_b9,
                                   file_name=f"{AQ_STICKER_SPEC[_s9]['fname']}_{datetime.date.today().strftime('%Y%m%d')}.pdf",
                                   mime="application/pdf", key=f"aq_pr_st_dl_{_s9}")

            st.markdown("---")
            st.markdown("**📖 농협 맞춤 가이드북** — 표지 + **목차(2p)** + **부속군 색상 색인(3p)** + **배치도 펼침면(4·5p~)** + 군별 품목 카드 (위 대상 사이트 기준)")
            st.caption("🗺 [V71] 농협을 고르면 그 농협의 **저장된 배치도가 4페이지부터 펼침면으로** 들어갑니다 — "
                       "펼치면 **왼쪽 면 위 1·2·3 / 오른쪽 면 위 4·5·6 / 왼쪽 아래 7·8·9 / 오른쪽 아래 10·11·12**, "
                       "페이지당 6섹션이고 12섹션이 넘으면 다음 장으로 이어집니다(가상랙 제외). "
                       "표지를 뺀 모든 페이지는 **짝수는 왼쪽·홀수는 오른쪽으로 5mm** 밀어 인쇄해, 책자로 묶었을 때 가운데가 가려지지 않습니다.")
            if st.button("📖 가이드북 PDF 생성", key="aq_pr_gb_go"):
                with st.spinner("가이드북 생성 중..."):
                    try:
                        st.session_state.pop("_aq_gb_layout_note", None)
                        _gb_b, _gb_n, _gb_asg = aq_guidebook_pdf_bytes(aq_items, _pr_site, _pr_bc_mode, _pr_imgof)
                        st.session_state["aq_pr_gb_out"] = (_gb_b, _pr_site, _gb_n, _gb_asg, _pr_bc_mode)
                    except Exception as e:
                        st.error(f"가이드북 생성 실패: {aq_err_str(e)}")
            if st.session_state.get("_aq_gb_layout_note"):   # [V69] 배치도 페이지 생략 사유 노출(조용히 넘어가지 않음)
                st.info(st.session_state["_aq_gb_layout_note"])
            _gb9 = st.session_state.get("aq_pr_gb_out")
            if _gb9:
                st.caption(f"{_gb9[1]} · {_gb9[2]}품목 · {'확정 배치 기준' if _gb9[3] else '진열분류 전체 기준'} · {_gb9[4]}바코드")
                st.download_button(f"⬇️ 가이드북 PDF ({len(_gb9[0]) // 1024}KB)", data=_gb9[0],
                                   file_name=f"가이드북_{_gb9[1]}_{_gb9[4]}_{datetime.date.today().strftime('%Y%m%d')}.pdf",
                                   mime="application/pdf", key="aq_pr_gb_dl")

        # ── 현황 ─────────────────────────────────────────
        with tab_stat:
            st.markdown("##### 🏢 설치 농협 (AQ_Sites)")
            aq_sites = aq_load_sites()
            if aq_sites:
                df_sites = pd.DataFrame(aq_sites)
                cols_show = [c for c in ["농협ID", "농협명", "지역", "상태", "설치일", "비고"] if c in df_sites.columns]
                st.dataframe(df_sites[cols_show].astype(str), hide_index=True)
            else:
                st.info("등록된 농협이 없습니다. (AQ_Sites 시트)")

            st.markdown("##### 📦 진열 품목 DB 요약 (AQ_Items)")
            n_loc = sum(1 for r in aq_items if r.get("섹션"))
            n_88 = sum(1 for r in aq_items if str(r.get("표준바코드", "")).strip())
            n_link = sum(1 for r in aq_items if r["품목코드"] in prod_by_code)
            m1, m2, m3, m4, m5 = st.columns(5)
            m1.metric("품목 수", f"{len(aq_items)}")
            m2.metric("위치 지정", f"{n_loc}")
            m3.metric("88바코드 보유", f"{n_88}")
            m4.metric("Products 연결", f"{n_link}")
            m5.metric("수용량 기록", f"{len(aq_itembox)}건")  # [V42] 축적 현황
            if n_link < len(aq_items):
                miss = [r["품목코드"] for r in aq_items if r["품목코드"] not in prod_by_code]
                st.warning(f"Products에 없는 코드 {len(miss)}건: {', '.join(miss[:10])}{' 외' if len(miss) > 10 else ''}")

            cnt_g = {}
            for r in aq_items:
                g = r.get("진열분류") or "(미지정)"
                cnt_g[g] = cnt_g.get(g, 0) + 1
            cnt_b = {}
            for r in aq_items:
                b = str(r.get("기본상자", "")).strip() or "(미지정)"
                cnt_b[b] = cnt_b.get(b, 0) + 1
            c_g, c_b = st.columns(2)
            with c_g:
                st.caption("진열분류별 품목수")
                st.dataframe(pd.DataFrame(sorted(cnt_g.items(), key=lambda x: -x[1]), columns=["진열분류", "품목수"]), hide_index=True)
            with c_b:
                st.caption("기본상자별 품목수 (기본값 기준 — 실제 배치는 사이트별 조정)")
                st.dataframe(pd.DataFrame(sorted(cnt_b.items(), key=lambda x: -x[1]), columns=["기본상자", "품목수"]), hide_index=True)

        # ── 진열 품목 브라우저 ────────────────────────────
        with tab_items:
            # [V60] 사이트 선택 — 표준(AQ_Items 정본) 외에 저장된 농협·표준v2 등 어느 사이트의 배치든 조회
            _ib_site_opts = ["(표준 — AQ_Items 섹션·단·열)"] + [str(s.get("농협명", "")).strip()
                                                          for s in aq_load_sites() if str(s.get("농협명", "")).strip()]
            # [V69] 사이트 설계 '진열 품목 상세 보기' → 그 농협 기준으로 자동 설정(위젯 생성 전에만 가능)
            if st.session_state.get("_aq_items_jump"):
                _ij9 = st.session_state.pop("_aq_items_jump")
                if _ij9 in _ib_site_opts:
                    st.session_state["aq_items_site"] = _ij9   # '배치된 품목만' 체크는 배치 유무로 자동 기본값
            if st.session_state.pop("_aq_items_tabjump", False):   # 탭도 함께 전환(부모 문서 탭 버튼 클릭)
                import streamlit.components.v1 as _cmp9
                _cmp9.html(   # ⚠ Streamlit 탭은 <button>이 아니라 role="tab" DIV — 태그로 좁히면 못 찾는다
                    "<script>(function(){var n=0;var t=setInterval(function(){try{"
                    "var bs=window.parent.document.querySelectorAll('[role=\"tab\"]');"
                    "for(var i=0;i<bs.length;i++){if((bs[i].innerText||'').indexOf('진열 품목')>-1){"
                    "bs[i].click();clearInterval(t);return;}}}catch(e){}"
                    "if(++n>24)clearInterval(t);},250);})();</script>", height=0)
            c_f0, c_f1, c_f2 = st.columns([2, 1.4, 2.6])
            with c_f0:
                _ib_site = st.selectbox("배치 기준 사이트", _ib_site_opts, key="aq_items_site",
                                        help="농협(또는 표준v2 등 저장 사이트)을 고르면 그 사이트에 저장된 배치·상자 기준으로 표시합니다.")
            with c_f1:
                aq_g_sel = st.selectbox("진열분류", ["전체"] + aq_groups, key="aq_grp_sel")
            with c_f2:
                aq_kw = st.text_input("검색 (코드/품목명/규격)", key="aq_kw")
            _ib_assign, _ib_items = {}, {}
            if not _ib_site.startswith("(표준"):
                for _srow0 in aq_load_sites():
                    if str(_srow0.get("농협명", "")).strip() == _ib_site:
                        try:
                            _pl0 = json.loads(str(_srow0.get("배치JSON") or "{}"))
                            if isinstance(_pl0, dict):
                                _ib_assign = _pl0.get("assign", {}) if isinstance(_pl0.get("assign", {}), dict) else {}
                                _ib_items = _pl0.get("items", {}) if isinstance(_pl0.get("items", {}), dict) else {}
                        except Exception:
                            pass
                if not _ib_assign:
                    st.info(f"'{_ib_site}'에 저장된 확정 배치가 없습니다 — 표준 위치 컬럼으로 표시합니다. (사이트 설계에서 배치 후 💾 저장)")
            _ib_only = st.checkbox("배치된 품목만 보기", value=bool(_ib_assign), key="aq_items_only",
                                   disabled=not _ib_assign) if not _ib_site.startswith("(표준") else False
            rows_view = []
            for r in aq_items:
                if aq_g_sel != "전체" and (r.get("진열분류") or "(미지정)") != aq_g_sel:
                    continue
                hay = f"{r['품목코드']} {r.get('품목명_AQ', '')} {r.get('규격_AQ', '')}".lower()
                if aq_kw and aq_kw.strip() and aq_kw.strip().lower() not in hay:
                    continue
                p = prod_by_code.get(r["품목코드"], {})
                _a0 = _ib_assign.get(r["품목코드"]) if _ib_assign else None
                if _ib_only and not isinstance(_a0, dict):
                    continue
                if isinstance(_a0, dict):   # [V60] 사이트 저장 배치 기준 위치·상자
                    loc = f"{_a0.get('rack', '')}-단{_a0.get('shelf', '')}" + (f"×{_a0.get('n')}" if int(_a0.get("n", 1) or 1) > 1 else "")
                    _bx0 = str((_ib_items.get(r["품목코드"], {}) or {}).get("box") or r.get("기본상자") or "")
                else:
                    loc = "-".join(str(x) for x in [r.get("섹션", ""), r.get("단", ""), r.get("열", "")] if str(x).strip())
                    if _ib_assign: loc = ""   # 사이트 기준인데 미배치 → 빈칸
                    _bx0 = str(r.get("기본상자", "") or "")
                # [V78] 정본 대조 — 품목명_AQ가 Products 제품명과 다르면 그 자리에서 보이게 한다
                _anm78 = str(r.get("품목명_AQ", "") or "")
                _pnm78 = str(p.get("name", "") or "")
                _chk78 = ("미연결" if not p else
                          (f"⚠ {_pnm78}" if _pnm78 and _pnm78 != _anm78 else ""))
                rows_view.append({
                    "품목코드": r["품목코드"], "품목명": _anm78, "정본대조(Products)": _chk78,
                    "규격": str(r.get("규격_AQ", "") or ""),
                    "진열분류": str(r.get("진열분류", "") or ""),
                    ("배치(랙-단)" if _ib_assign else "위치(섹션-단-열)"): loc,
                    "상자": _bx0, "기본수량": str(r.get("기본수량", "") or ""),
                    "수용기록": len(aq_caps.get(r["품목코드"], {})),
                    "스티커": str(r.get("스티커", "") or ""), "지역농협가": str(p.get("price_nh_loc", "") or ""),
                    "소비자가": str(p.get("price_cons", "") or ""), "계통등록": str(r.get("계통등록", "") or ""),
                    "상태": str(r.get("상태", "") or ""),
                })
            st.caption(f"표시 {len(rows_view)}개 품목 · 기준 = {_ib_site}"
                       + (" (저장 배치·사이트 상자 반영)" if _ib_assign else " (AQ_Items 표준 위치)")
                       + " · 매입가 미표시 · 수용기록=축적된 상자별 수용량 데이터 수")
            st.dataframe(pd.DataFrame(rows_view), hide_index=True, height=480)

            # ── [V78] 품목명 정본 대조·동기화 (대표님 승인 2026-08-28) ──
            #  품목명_AQ는 Products 제품명의 복사본이라 정본이 바뀌면 어긋난다. 화면·스티커·가이드북·도면이
            #  전부 이 컬럼을 쓰므로, 어긋난 채 두면 옛 이름이 농협 현장에 인쇄돼 나간다.
            _nm_gap = []
            for r in aq_items:
                _p78 = prod_by_code.get(r["품목코드"]) or {}
                _pn78 = str(_p78.get("name", "") or "")
                _an78 = str(r.get("품목명_AQ", "") or "")
                if _pn78 and _pn78 != _an78:
                    _nm_gap.append((r["품목코드"], _an78, _pn78))
            if _nm_gap:
                with st.expander(f"⚠ 품목명이 정본(Products)과 다른 품목 {len(_nm_gap)}건 — 정본명으로 동기화",
                                 expanded=False):
                    st.caption("품목 정본은 **Looperget_DB(Products)** 입니다. 아쿠나리스 화면·스티커·가이드북·"
                               "진열도면은 모두 AQ_Items `품목명_AQ`를 쓰므로, 여기서 맞춰 두지 않으면 "
                               "옛 이름이 그대로 인쇄됩니다. (Products에 없는 품목은 대상이 아닙니다)")
                    st.dataframe(pd.DataFrame([{"품목코드": c, "현재 (AQ_Items)": a, "정본 (Products)": b}
                                               for c, a, b in _nm_gap]), hide_index=True,
                                 height=min(360, 45 + 35 * len(_nm_gap)))
                    if not aq_can("aqunaris"):   # 같은 탭의 품목 등재와 동일 기준(공용 로그인 허용)
                        st.caption("※ 동기화는 아쿠나리스 권한 계정에서만 실행됩니다.")
                    elif st.button(f"🔄 {len(_nm_gap)}건 정본명으로 동기화", key="aq_nmsync_go", type="primary"):
                        try:
                            _n78 = aq_sync_item_names([(c, b) for c, _a, b in _nm_gap])
                            aq_load_all.clear()
                            st.success(f"{_n78}건 동기화 완료 — 품목명_AQ ← Products 제품명")
                            time.sleep(0.5); st.rerun()
                        except Exception as _e78:
                            st.error(f"동기화 실패: {aq_err_str(_e78)}")

            # ── [V61] Looperget_DB 절대값(대표님 승인 2026-07-23) — Products에서 진열 품목 추가(흡수 1단계) ──
            with st.expander("➕ 진열 품목 추가 — Looperget_DB(Products)에서", expanded=False):
                st.caption("품목 정본은 **Looperget_DB(Products)** 입니다. 여기서 고른 품목이 진열 속성(AQ_Items)에 등재되어 "
                           "부속군 색·사이트 배치·스티커 대상이 됩니다. 상자·수용량은 등재 후 📦 상자·수용량 탭에서 보강하세요.")
                _ex_codes61 = {str(r.get("품목코드", "")).strip().zfill(5) for r in aq_items}
                _cand61 = [p for p in st.session_state.db.get("products", [])
                           if str(p.get("code", "")).strip()
                           and str(p.get("code", "")).strip().zfill(5) not in _ex_codes61]
                _kw61 = st.text_input("Products 검색 (코드/이름/규격)", key="aq_addp_kw")
                if _kw61.strip():
                    _k61 = _kw61.strip().lower()
                    _cand61 = [p for p in _cand61
                               if _k61 in f"{p.get('code', '')} {p.get('name', '')} {p.get('spec', '')}".lower()]
                st.caption(f"추가 가능 {len(_cand61)}개 (이미 등재된 {len(_ex_codes61)}개 제외 · 표시 최대 300)")
                _by61 = {str(p.get("code", "")).zfill(5): p for p in _cand61}
                _opts61 = [f"{str(p.get('code', '')).zfill(5)} | {p.get('name', '')} {p.get('spec', '')}".strip()
                           for p in _cand61[:300]]
                _sel61 = st.multiselect("추가할 품목", _opts61, key="aq_addp_sel")
                _c61a, _c61b = st.columns(2)
                with _c61a:
                    _grp61 = st.selectbox("부속군(진열분류)", [g for g in AQ_GROUP_COLORS if g != "(미지정)"],
                                          key="aq_addp_grp")
                with _c61b:
                    _box61 = st.selectbox("기본상자 (빈칸 = 자유배치로 진열)", [""] + [b for b in aq_box_names if b],
                                          key="aq_addp_box")
                if _sel61 and st.button(f"➕ {len(_sel61)}개 품목 등재", key="aq_addp_go", type="primary"):
                    try:
                        ws61 = _aq_sh().worksheet("AQ_Items")
                        hdr61 = ws61.row_values(1)
                        _rows61 = []
                        for _s61 in _sel61:
                            _cd61 = _s61.split("|")[0].strip()
                            _p61 = _by61.get(_cd61, {})
                            _d61 = {"품목코드": _cd61, "품목명_AQ": str(_p61.get("name", "") or ""),
                                    "규격_AQ": str(_p61.get("spec", "") or ""), "진열분류": _grp61,
                                    "기본상자": _box61,
                                    "비고": f"Products에서 추가 {datetime.date.today().isoformat()}"}
                            _rows61.append([str(_d61.get(h, "")) for h in hdr61])
                        ws61.append_rows(_rows61, value_input_option="RAW")
                        aq_load_all.clear()
                        st.success(f"{len(_rows61)}개 등재 완료 — 부속군 '{_grp61}'")
                        time.sleep(0.5); st.rerun()
                    except Exception as _e61:
                        st.error(f"등재 실패: {aq_err_str(_e61)}")

            # ── [V48] 품목 이미지 2종 체계 — 빌더용(기존 유지)과 등각(ISO: 현장 시연·가이드북·스티커용) ──
            with st.expander("🖼️ 품목 이미지 관리 — 등각(ISO) 등록·미리보기", expanded=False):
                st.caption("빌더용 이미지(2D 배치용)는 기존 관리자 모드에서 그대로 관리합니다. 여기서는 현장 시연·가이드북·스티커 자동생성용 **등각(isometric) 이미지**를 품목별로 추가 등록합니다. (드라이브 파일명 `코드_iso` — 기존 이미지 해석과 충돌 없음)")
                _iso_opts = [f"{r['품목코드']} | {r.get('품목명_AQ', '')} {r.get('규격_AQ', '')}".strip() for r in aq_items]
                _iso_sel = st.selectbox("품목 선택", _iso_opts, key="aq_iso_item")
                _iso_code = _iso_sel.split("|")[0].strip()
                _iso_rec = next((r for r in aq_items if r["품목코드"] == _iso_code), {})
                ci1, ci2 = st.columns(2)
                with ci1:
                    st.markdown("**등각(ISO) 이미지 — 시연·인쇄물용**")
                    _iso_id = str(_iso_rec.get("이미지ISO", "") or "").strip()
                    if _iso_id:
                        try:
                            _img_iso = download_image_by_id(_iso_id)
                            if _img_iso is not None:
                                st.image(_img_iso, width=260)
                            else:
                                st.info("이미지 로드 실패 — 드라이브 파일 확인")
                        except Exception as _e9:
                            st.info(f"이미지 로드 실패: {aq_err_str(_e9)}")
                    else:
                        st.info("등각 이미지 미등록")
                with ci2:
                    st.markdown("**빌더용(기존) 이미지 — 2D 배치용**")
                    _pb = prod_by_code.get(_iso_code, {})
                    _bld_id = str(_pb.get("image", "") or "")
                    if len(_bld_id) > 10:
                        try:
                            _img_b = download_image_by_id(_bld_id)
                            if _img_b is not None:
                                st.image(_img_b, width=260)
                            else:
                                st.caption("등록됨 (미리보기 실패)")
                        except Exception:
                            st.caption("등록됨 (미리보기 실패)")
                    else:
                        st.caption("Products 이미지데이터 기준 미등록 (드라이브 파일명 매칭분은 별도)")
                _up = st.file_uploader("등각 이미지 업로드 (JPG/PNG)", type=["jpg", "jpeg", "png"], key="aq_iso_up")
                if _up is not None and st.button("⬆️ 등각 이미지 등록", key="aq_iso_save", type="primary"):
                    try:
                        _ext = "png" if str(_up.type).endswith("png") else "jpg"
                        _fid = upload_bytes_to_drive(_up.getvalue(), f"{_iso_code}_iso.{_ext}",
                                                     mimetype=_up.type or "image/jpeg")
                        if not _fid:
                            st.error("드라이브 업로드 실패 — 잠시 후 재시도")
                        else:
                            aq_update_item_cell(_iso_code, "이미지ISO", _fid)
                            aq_load_all.clear()
                            st.success(f"{_iso_code} 등각 이미지 등록 완료")
                            time.sleep(0.5); st.rerun()
                    except Exception as _e8:
                        st.error(f"등록 실패: {aq_err_str(_e8)}")

        # ── 진열 공급 간이 견적 ───────────────────────────
        with tab_quote:
            st.caption("선택한 진열분류를 '기본상자·기본수량(폴백 기본값)'으로 채우는 초도 공급 견적 미리보기. 단가 = Products 지역농협가, 계통2(5%) 수수료는 참고 표시. 사이트별 상자·수량 조정은 🏗️ 사이트 설계 탭에서.")
            aq_q_groups = st.multiselect("진열분류 선택", aq_groups, key="aq_q_groups")
            with st.expander("📦 상자(하드웨어) 단가 — AQ_Boxes 시트값, 필요 시 임시 조정", expanded=False):
                aq_box_prices = {}
                if aq_box_names:
                    _cols_bx = st.columns(min(len(aq_box_names), 4))
                    for _i, _bn in enumerate(aq_box_names):
                        with _cols_bx[_i % len(_cols_bx)]:
                            aq_box_prices[_bn] = st.number_input(
                                _bn, value=int(aq_box_price.get(_bn, 0)), step=100, key=f"aq_bxp_{_bn}")
                else:
                    st.info("등록된 상자가 없습니다. '📦 상자·수용량' 탭에서 추가하세요.")
                aq_inc_box = st.checkbox("상자 하드웨어 포함", value=True, key="aq_inc_box")
            if not aq_q_groups:
                st.info("진열분류를 1개 이상 선택하면 견적이 계산됩니다.")
            else:
                det_rows, skipped = [], []
                parts_sum = 0.0
                box_cnt = {}
                for r in aq_items:
                    if (r.get("진열분류") or "(미지정)") not in aq_q_groups:
                        continue
                    p = prod_by_code.get(r["품목코드"])
                    try: q_fill = int(float(str(r.get("기본수량") or 0)))
                    except Exception: q_fill = 0
                    try: unit = float(p.get("price_nh_loc") or 0) if p else 0.0
                    except Exception: unit = 0.0
                    if q_fill <= 0 or unit <= 0:
                        skipped.append(r["품목코드"]); continue
                    amt = unit * q_fill
                    parts_sum += amt
                    bx = str(r.get("기본상자", "")).strip()
                    if bx: box_cnt[bx] = box_cnt.get(bx, 0) + 1
                    det_rows.append({
                        "품목코드": r["품목코드"], "품목명": str(r.get("품목명_AQ", "") or ""), "규격": str(r.get("규격_AQ", "") or ""),
                        "상자": bx, "수량": q_fill, "지역농협가": int(unit), "금액": int(amt),
                    })
                box_sum = sum(aq_box_prices.get(b, 0) * n for b, n in box_cnt.items()) if aq_inc_box else 0
                fee2 = parts_sum * 0.05
                q1, q2, q3, q4 = st.columns(4)
                q1.metric("부속 합계", f"{parts_sum:,.0f}원")
                q2.metric("상자 하드웨어", f"{box_sum:,.0f}원")
                q3.metric("공급 합계", f"{parts_sum + box_sum:,.0f}원")
                q4.metric("계통2 수수료(참고)", f"-{fee2:,.0f}원")
                if box_cnt:
                    st.caption("상자 구성: " + ", ".join(f"{b}×{n}" for b, n in sorted(box_cnt.items())))
                if skipped:
                    st.warning(f"단가/수량 미비로 제외 {len(skipped)}건: {', '.join(skipped[:10])}{' 외' if len(skipped) > 10 else ''}")
                if det_rows:
                    df_det = pd.DataFrame(det_rows)
                    st.dataframe(df_det, hide_index=True, height=420)
                    st.download_button(
                        "⬇️ 간이 견적 CSV 다운로드",
                        df_det.to_csv(index=False).encode("utf-8-sig"),
                        file_name="aqunaris_진열공급_간이견적.csv", mime="text/csv",
                        key="aq_csv_dl",
                    )

        # ── [V42] 상자·수용량 — 유연 상자 모델의 축적 UI ─────────
        with tab_box:
            st.caption("품목↔상자 매핑은 고정이 아닙니다. 농협 상황·랙 크기에 따라 상자가 바뀌고 새 상자가 추가됩니다. '어떤 부속이 어떤 상자에 얼마나 담기는지'를 여기서 계속 축적하세요.")
            c_bm, c_add = st.columns([3, 2])
            with c_bm:
                st.markdown("##### 📦 상자 마스터 (AQ_Boxes) — 표에서 직접 수정")
                # [V43] 치수는 배치 방향 판정의 기초: 세로(표준)=단 깊이≥상자 깊이 / 가로=단 깊이≥상자 폭
                st.caption("치수(폭·깊이)를 채우면 배치 판정에 사용됩니다 — **세로**(표준) 배치는 단 깊이 ≥ 상자 깊이, **가로** 배치는 단 깊이 ≥ 상자 폭. "
                           "[V50] **셀을 고쳐 '상자 정보 저장'을 누르면 반영**됩니다(치수 실측값 입력·단가 변경 등). 상자 **이름 변경은 아래 '✏️ 상자 이름 변경'**(참조처 연쇄 반영).")
                if aq_boxes:
                    _bx_cols = [c for c in ["상자종류", "폭mm", "깊이mm", "높이mm", "단가", "상태", "비고"]
                                if any(c in b for b in aq_boxes)]
                    _df_bx_in = pd.DataFrame([{c: b.get(c, "") for c in _bx_cols} for b in aq_boxes])
                    for _c in ["폭mm", "깊이mm", "높이mm", "단가"]:
                        if _c in _df_bx_in.columns:
                            _df_bx_in[_c] = pd.to_numeric(_df_bx_in[_c], errors="coerce")
                    df_bx_ed = st.data_editor(
                        _df_bx_in, hide_index=True, key="aq_box_ed",
                        disabled=["상자종류"],
                        column_config={
                            "상자종류": st.column_config.TextColumn("상자종류", help="이름 변경은 아래 '상자 이름 변경' 사용 — 참조처까지 함께 바꿔야 안전합니다"),
                            "폭mm": st.column_config.NumberColumn(format="%d", min_value=0),
                            "깊이mm": st.column_config.NumberColumn(format="%d", min_value=0),
                            "높이mm": st.column_config.NumberColumn(format="%d", min_value=0),
                            "단가": st.column_config.NumberColumn(format="%d", min_value=0),
                        })
                    if st.button("💾 상자 정보 저장", type="primary", key="aq_box_save"):
                        try:
                            _out_bx = []
                            for _i, _b in enumerate(aq_boxes):
                                _row = dict(_b)                      # 등록일 등 미표시 컬럼 보존
                                if _i < len(df_bx_ed):
                                    _ed = df_bx_ed.iloc[_i]
                                    for _c in _bx_cols:
                                        if _c == "상자종류": continue
                                        _v = _ed.get(_c)
                                        if _v is None or (isinstance(_v, float) and pd.isna(_v)):
                                            _row[_c] = ""
                                        elif _c in ("폭mm", "깊이mm", "높이mm", "단가"):
                                            _row[_c] = int(_v)
                                        else:
                                            _row[_c] = str(_v)
                                _out_bx.append(_row)
                            aq_save_ws("AQ_Boxes", _out_bx)
                            aq_load_all.clear()
                            st.success(f"상자 {len(_out_bx)}건 저장 완료"); time.sleep(0.5); st.rerun()
                        except Exception as e:
                            st.error(f"저장 실패: {aq_err_str(e)}")
                else:
                    st.info("등록된 상자가 없습니다.")
            with c_add:
                st.markdown("##### ➕ 새 상자 등록")
                with st.form("aq_box_add_form", clear_on_submit=True):
                    nb_name = st.text_input("상자종류(이름) *", help="예: 5호, 대형-A, ○○농협 전용상자")
                    cnb1, cnb2, cnb3 = st.columns(3)
                    nb_w = cnb1.number_input("폭mm", value=0, step=10)
                    nb_d = cnb2.number_input("깊이mm", value=0, step=10)
                    nb_h = cnb3.number_input("높이mm", value=0, step=10)
                    nb_price = st.number_input("단가(원)", value=0, step=100)
                    nb_memo = st.text_input("비고", help="예: ○○농협 기존 랙용")
                    if st.form_submit_button("상자 등록", type="primary"):
                        _nm = nb_name.strip()
                        if not _nm:
                            st.error("상자 이름을 입력하세요.")
                        elif _nm in aq_box_names:
                            st.error(f"'{_nm}' 은 이미 등록된 상자입니다.")
                        else:
                            try:
                                aq_append_row("AQ_Boxes", [_nm, nb_w or "", nb_d or "", nb_h or "",
                                                           nb_price or "", "신규",
                                                           datetime.datetime.now().strftime("%Y-%m-%d"), nb_memo])
                                aq_load_all.clear()
                                st.success(f"'{_nm}' 등록 완료"); time.sleep(0.5); st.rerun()
                            except Exception as e:
                                st.error(f"등록 실패: {aq_err_str(e)}")

            # [V50] 상자 이름 변경 — 참조처(품목 기본상자·수용량 기록·사이트 배치)까지 연쇄 반영
            with st.expander("✏️ 상자 이름 변경 (참조처 연쇄 반영)", expanded=False):
                st.caption("이름만 바꾸면 품목의 기본상자·수용량 기록·사이트 배치가 옛 이름을 가리켜 배치가 깨집니다. "
                           "여기서 바꾸면 **AQ_Boxes·AQ_Items(기본상자)·AQ_ItemBox·AQ_Sites(배치JSON)를 한 번에** 고칩니다.")
                if aq_box_names:
                    _rn1, _rn2 = st.columns(2)
                    _rn_old = _rn1.selectbox("현재 이름", aq_box_names, key="aq_box_rn_old")
                    _rn_new = _rn2.text_input("새 이름", key="aq_box_rn_new")
                    _n_it = sum(1 for r in aq_items if str(r.get("기본상자", "")).strip() == _rn_old)
                    _n_ib = sum(1 for r in aq_itembox if str(r.get("상자종류", "")).strip() == _rn_old)
                    st.caption(f"'{_rn_old}' 참조 현황 — 품목 기본상자 {_n_it}건 · 수용량 기록 {_n_ib}건 (+ 사이트 배치JSON은 실행 시 집계)")
                    if st.button("이름 변경 실행", key="aq_box_rn_go"):
                        _nn = (_rn_new or "").strip()
                        if not _nn:
                            st.error("새 이름을 입력하세요.")
                        elif _nn == _rn_old:
                            st.error("현재 이름과 같습니다.")
                        elif _nn in aq_box_names:
                            st.error(f"'{_nn}' 은 이미 있는 상자입니다. (합치려면 수용량 기록의 상자를 개별 변경하세요)")
                        else:
                            try:
                                _res = aq_rename_box(_rn_old, _nn)
                                aq_load_all.clear()
                                st.success(f"'{_rn_old}' → '{_nn}' 변경 완료 — "
                                           + " · ".join(f"{k} {v}건" for k, v in _res.items()))
                                time.sleep(0.8); st.rerun()
                            except Exception as e:
                                st.error(f"이름 변경 실패: {aq_err_str(e)}")
                else:
                    st.info("등록된 상자가 없습니다.")

            st.divider()
            st.markdown("##### 📝 수용량 기록 추가 — 품목이 이 상자에 몇 개 담기는가")
            _opt_items = [f"{r['품목코드']} | {r.get('품목명_AQ', '')} {r.get('규격_AQ', '')}".strip() for r in aq_items]
            with st.form("aq_cap_add_form", clear_on_submit=True):
                cf1, cf2 = st.columns([3, 2])
                with cf1:
                    cap_item_lbl = st.selectbox("품목", _opt_items)
                with cf2:
                    cap_box = st.selectbox("상자", aq_box_names if aq_box_names else ["(상자 먼저 등록)"])
                cf3, cf4, cf5 = st.columns(3)
                cap_qty = cf3.number_input("수용수량 *", value=0, step=10, min_value=0)
                cap_basis = cf4.selectbox("근거", ["실측", "추정", "카탈로그"])
                cap_src = cf5.text_input("출처", help="예: 부발농협 설치, 창고 실측")
                cap_memo = st.text_input("비고", key="aq_cap_memo")
                if st.form_submit_button("수용량 기록 추가", type="primary"):
                    if cap_qty <= 0:
                        st.error("수용수량을 입력하세요.")
                    elif not aq_box_names:
                        st.error("상자를 먼저 등록하세요.")
                    else:
                        try:
                            _code = cap_item_lbl.split("|")[0].strip()
                            aq_append_row("AQ_ItemBox", [_code, cap_box, int(cap_qty), cap_basis, cap_src,
                                                         datetime.datetime.now().strftime("%Y-%m-%d"), cap_memo])
                            aq_load_all.clear()
                            st.success(f"{_code} × {cap_box} = {int(cap_qty)}개 기록 완료"); time.sleep(0.5); st.rerun()
                        except Exception as e:
                            st.error(f"기록 실패: {aq_err_str(e)}")

            # [V50] 수용량 기록 수정·삭제 — 잘못 기록된 수량·근거·상자를 고칠 수 있어야 한다
            with st.expander(f"🛠 수용량 기록 수정·삭제 (총 {len(aq_itembox)}건)", expanded=False):
                st.caption("셀을 고치거나 행을 지운 뒤 **'기록 저장'**을 누르면 반영됩니다. 같은 품목×상자 기록이 여럿이면 **뒤(나중) 기록이 우선** 적용됩니다. "
                           "품목코드는 잠금(잘못된 매칭 방지) — 품목을 바꾸려면 지우고 위 폼에서 새로 추가하세요. 저장 시 빈 행은 정리됩니다.")
                _nm_by_code = {r["품목코드"]: str(r.get("품목명_AQ", "") or "") for r in aq_items}
                _ib_all = []
                for _i, _r in enumerate(aq_itembox):
                    _ib_all.append({
                        "행": _i, "품목코드": _r["품목코드"], "품목명": _nm_by_code.get(_r["품목코드"], ""),
                        "상자종류": str(_r.get("상자종류", "") or ""),
                        "수용수량": pd.to_numeric(_r.get("수용수량"), errors="coerce"),
                        "근거": str(_r.get("근거", "") or ""), "출처": str(_r.get("출처", "") or ""),
                        "비고": str(_r.get("비고", "") or ""),
                    })
                _fb1, _fb2 = st.columns([2, 3])
                _f_box = _fb1.selectbox("상자 필터", ["(전체)"] + aq_box_names, key="aq_ib_fbox")
                _f_q = _fb2.text_input("품목 검색 (코드·품명)", key="aq_ib_fq").strip()
                _ib_view = [r for r in _ib_all
                            if (_f_box == "(전체)" or r["상자종류"] == _f_box)
                            and (not _f_q or _f_q in r["품목코드"] or _f_q in r["품목명"])]
                if not _ib_view:
                    st.info("조건에 맞는 기록이 없습니다.")
                else:
                    _basis_opts = sorted({r["근거"] for r in _ib_all if r["근거"]} | {"실측", "추정", "카탈로그", "표준설치"})
                    df_ib_ed = st.data_editor(
                        pd.DataFrame(_ib_view), hide_index=True, height=330, num_rows="dynamic",
                        key=f"aq_ib_ed_{_f_box}_{_f_q}",
                        disabled=["행", "품목코드", "품목명"],
                        column_config={
                            "행": st.column_config.NumberColumn("행", format="%d", help="원본 행 번호(수정 위치 추적용)"),
                            "상자종류": st.column_config.SelectboxColumn("상자종류", options=aq_box_names or [""]),
                            "수용수량": st.column_config.NumberColumn(format="%d", min_value=0),
                            "근거": st.column_config.SelectboxColumn("근거", options=_basis_opts),
                        })
                    if st.button("💾 기록 저장 (수정·삭제 반영)", type="primary", key="aq_ib_save"):
                        try:
                            _ed_by_row, _new_rows = {}, []
                            for _, _er in df_ib_ed.iterrows():
                                _rn = _er.get("행")
                                if _rn is None or (isinstance(_rn, float) and pd.isna(_rn)):
                                    _new_rows.append(_er); continue      # 표에서 추가한 행(코드 없음) → 무시
                                _ed_by_row[int(_rn)] = _er
                            _view_rows = {r["행"] for r in _ib_view}
                            _kept = _view_rows & set(_ed_by_row)
                            _deleted = _view_rows - _kept
                            _out_ib = []
                            for _i, _r in enumerate(aq_itembox):
                                if _i in _deleted: continue
                                _row = dict(_r)
                                if _i in _ed_by_row:
                                    _er = _ed_by_row[_i]
                                    _qv = _er.get("수용수량")
                                    if _qv is None or (isinstance(_qv, float) and pd.isna(_qv)):
                                        _row["수용수량"] = ""
                                    else:
                                        _row["수용수량"] = int(_qv)
                                    for _c in ("상자종류", "근거", "출처", "비고"):
                                        _v = _er.get(_c)
                                        _row[_c] = "" if (_v is None or (isinstance(_v, float) and pd.isna(_v))) else str(_v)
                                _out_ib.append(_row)
                            aq_save_ws("AQ_ItemBox", _out_ib)
                            aq_load_all.clear()
                            _msg = f"수용량 기록 저장 완료 — {len(_out_ib)}건 유지"
                            if _deleted: _msg += f" · {len(_deleted)}건 삭제"
                            if len(_new_rows): _msg += f" · 표에서 추가한 {len(_new_rows)}행은 무시(위 폼으로 추가)"
                            st.success(_msg); time.sleep(0.8); st.rerun()
                        except Exception as e:
                            st.error(f"저장 실패: {aq_err_str(e)}")

            c_v1, c_v2 = st.columns(2)
            with c_v1:
                st.markdown("##### 🔎 품목별 수용량 조회")
                _q_item = st.selectbox("품목 선택", _opt_items, key="aq_cap_view_item")
                _q_code = _q_item.split("|")[0].strip()
                _caps = aq_caps.get(_q_code, {})
                if _caps:
                    st.dataframe(pd.DataFrame(
                        [{"상자": b, "수용수량": q, "근거": s} for b, (q, s) in _caps.items()]), hide_index=True)
                else:
                    st.info("이 품목의 수용량 기록이 아직 없습니다.")
            with c_v2:
                st.markdown("##### 🕘 최근 기록")
                if aq_itembox:
                    _recent = aq_itembox[-15:][::-1]
                    st.dataframe(pd.DataFrame(_recent).astype(str), hide_index=True, height=280)
                else:
                    st.info("기록이 없습니다.")

        # ── [V42] 사이트 설계 (Phase B-1) — 농협별 랙 구성·진열 계획·견적 ──
        with tab_site:
            aq_sites_all = aq_load_sites()
            st.markdown("##### 🏢 농협(사이트) 선택")
            _site_names = [str(s.get("농협명", "")).strip() for s in aq_sites_all]
            # [V44] 표준 불러오기 후 자동 선택 점프 (위젯 생성 전에만 키 설정 가능)
            if st.session_state.get("_aq_site_jump"):
                _jump = st.session_state.pop("_aq_site_jump")
                if _jump in _site_names:
                    st.session_state["aq_site_sel"] = _jump
            # [V69] 표준 시스템을 목록 맨 위·강조 표시 — 표준은 계속 다듬어 나가는 '살아있는 기준'이다.
            _has_std9 = AQ_STD_SITE in _site_names
            _opts9 = (["(신규 등록)"] + ([AQ_STD_SITE] if _has_std9 else [])
                      + [n for n in _site_names if n != AQ_STD_SITE])
            def _site_fmt9(n):
                return f"⭐ {n} — 기준 시스템" if n == AQ_STD_SITE else n
            c_sel, c_std = st.columns([3, 2])
            with c_sel:
                sel_site = st.selectbox("사이트", _opts9, key="aq_site_sel", format_func=_site_fmt9)
            with c_std:
                st.caption("표준 시스템 = 계속 다듬어 나가는 **기준 배치**입니다. 아래 버튼으로 바로 열고, "
                           "농협 설계는 **복제 후 수정**하세요.")
                if st.button("📐 표준 시스템 열기", key="aq_std_load", use_container_width=True,
                             help="저장된 표준 시스템 사이트를 즉시 엽니다(없으면 V1 도면 기준으로 처음 한 번 생성)."):
                    try:
                        if _has_std9:                      # [V69] 이미 있으면 '열기'만 — 손질본을 덮어쓰지 않는다
                            st.session_state["_aq_site_jump"] = AQ_STD_SITE
                            st.rerun()
                        _racks_std, _plan_std = aq_std_payload(aq_items)
                        aq_sites_all.append({"농협ID": "S000", "농협명": AQ_STD_SITE, "지역": "-",
                                             "상태": "표준", "설치일": "2023-03",
                                             "랙구성JSON": json.dumps(_racks_std, ensure_ascii=False, separators=(",", ":")),
                                             "배치JSON": json.dumps(_plan_std, ensure_ascii=False, separators=(",", ":")),
                                             "견적ID": "", "담당자": "",
                                             "비고": "V1 도면 역산 표준 시스템 — 검증 기준"})
                        aq_save_sites(aq_sites_all)
                        aq_load_all.clear()
                        st.session_state["_aq_site_jump"] = AQ_STD_SITE
                        st.success("표준 시스템을 새로 만들었습니다"); time.sleep(0.5); st.rerun()
                    except Exception as e:
                        st.error(f"표준 열기 실패: {aq_err_str(e)}")
            if sel_site == AQ_STD_SITE:   # 선택값도 굵게(가능한 경우) — 기준 시스템 작업 중임을 눈에 띄게
                st.markdown('<style>.st-key-aq_site_sel div[data-baseweb="select"] '
                            '{font-weight:800 !important;}</style>', unsafe_allow_html=True)

            # ── [V69] 사이트 복제 — 표준(또는 비슷한 농협)을 복제해 이름만 바꿔 시작 ──
            if sel_site != "(신규 등록)":
                with st.expander(f"📄 '{sel_site}' 복제해서 새 농협 만들기", expanded=False):
                    st.caption("랙 구성·배치·진열 계획을 **그대로 복사**한 새 사이트를 만듭니다. "
                               "A농협이 표준과 거의 같다면 → 복제 → 다른 부분만 수정 → 💾 저장.")
                    _cp1, _cp2 = st.columns([3, 1.4])
                    with _cp1:
                        _cp_nm9 = st.text_input("새 농협명 *", key=f"aq_cp_nm_{sel_site}",
                                                placeholder="예: 여주농협")
                    with _cp2:
                        _cp_rg9 = st.text_input("지역", key=f"aq_cp_rg_{sel_site}")
                    if st.button("📄 복제 실행", key=f"aq_cp_go_{sel_site}"):
                        _nm9 = _cp_nm9.strip()
                        if not _nm9:
                            st.error("새 농협명을 입력하세요.")
                        elif _nm9 in _site_names:
                            st.error("이미 등록된 농협명입니다.")
                        else:
                            try:
                                _src9 = next(s for s in aq_sites_all
                                             if str(s.get("농협명", "")).strip() == sel_site)
                                _ids9 = {str(s.get("농협ID", "")).strip() for s in aq_sites_all}
                                _n9i = len(aq_sites_all) + 1
                                while f"S{_n9i:03d}" in _ids9: _n9i += 1
                                aq_sites_all.append({
                                    "농협ID": f"S{_n9i:03d}", "농협명": _nm9,
                                    "지역": _cp_rg9.strip() or str(_src9.get("지역", "")),
                                    "상태": "제안", "설치일": "",
                                    "랙구성JSON": str(_src9.get("랙구성JSON") or ""),
                                    "배치JSON": str(_src9.get("배치JSON") or ""),
                                    "견적ID": "", "담당자": str(_src9.get("담당자", "")),
                                    "비고": f"'{sel_site}' 복제 ({datetime.date.today().strftime('%Y-%m-%d')})"})
                                aq_save_sites(aq_sites_all)
                                aq_load_all.clear()
                                for _k9 in list(st.session_state.keys()):   # 복제본은 새 세션 상태로 시작
                                    if _k9.startswith((f"aq_inst_{_nm9}", f"aq_rows_{_nm9}")):
                                        st.session_state.pop(_k9, None)
                                st.session_state["_aq_site_jump"] = _nm9
                                st.success(f"'{_nm9}' 복제 완료 — 수정 후 💾 저장하세요.")
                                time.sleep(0.6); st.rerun()
                            except Exception as e:
                                st.error(f"복제 실패: {aq_err_str(e)}")

            # ── [V69] 표준 공장초기화 — 되돌릴 수 없어 깊이 숨긴다(손질본이 날아감) ──
            if sel_site == AQ_STD_SITE:
                with st.expander("⚠ 표준을 V1 도면 원본으로 되돌리기 (공장초기화)", expanded=False):
                    st.caption("코드에 박힌 V1 도면 상수로 랙·배치를 **재생성**합니다 — 그동안 다듬어 온 "
                               "표준 손질본이 사라집니다. 복구는 시트 버전 기록으로만 가능.")
                    _rs_in9 = st.text_input("확인 — '초기화' 입력", key="aq_std_reset_in")
                    if st.button("⚠ 표준 공장초기화 실행", key="aq_std_reset_go"):
                        if _rs_in9.strip() != "초기화":
                            st.error("'초기화'를 정확히 입력하세요.")
                        else:
                            try:
                                _racks_std, _plan_std = aq_std_payload(aq_items)
                                for s in aq_sites_all:
                                    if str(s.get("농협명", "")).strip() == AQ_STD_SITE:
                                        s["랙구성JSON"] = json.dumps(_racks_std, ensure_ascii=False, separators=(",", ":"))
                                        s["배치JSON"] = json.dumps(_plan_std, ensure_ascii=False, separators=(",", ":"))
                                        s["상태"] = "표준"
                                aq_save_sites(aq_sites_all)
                                aq_load_all.clear()
                                for _k9 in (f"aq_inst_{AQ_STD_SITE}", f"aq_rows_{AQ_STD_SITE}"):
                                    st.session_state.pop(_k9, None)
                                st.success("표준을 V1 도면 원본으로 되돌렸습니다"); time.sleep(0.5); st.rerun()
                            except Exception as e:
                                st.error(f"초기화 실패: {aq_err_str(e)}")

            # ── [V55] 사이트 삭제 (대표님 요청 — 테스트 사이트 정리) ──
            if sel_site != "(신규 등록)":
                with st.expander("🗑 사이트 삭제", expanded=False):
                    st.caption("이 사이트 행이 AQ_Sites 시트에서 제거됩니다(랙 구성·배치 포함). "
                               "실수 방지를 위해 농협명을 그대로 입력해야 삭제됩니다. 복구는 시트 버전 기록으로 가능.")
                    _del_in9 = st.text_input(f"삭제 확인 — 농협명 입력: {sel_site}", key=f"aq_del_in_{sel_site}")
                    if st.button("🗑 이 사이트 삭제", key=f"aq_del_go_{sel_site}"):
                        if _del_in9.strip() != sel_site:
                            st.error("농협명이 일치하지 않습니다.")
                        else:
                            try:
                                _rest9 = [s for s in aq_sites_all
                                          if str(s.get("농협명", "")).strip() != sel_site]
                                aq_save_sites(_rest9)
                                aq_load_all.clear()
                                st.success("삭제 완료"); time.sleep(0.5); st.rerun()
                            except Exception as e:
                                st.error(f"삭제 실패: {aq_err_str(e)}")

            if sel_site == "(신규 등록)":
                with st.form("aq_site_add_form", clear_on_submit=True):
                    ns1, ns2, ns3 = st.columns(3)
                    s_name = ns1.text_input("농협명 *")
                    s_region = ns2.text_input("지역")
                    s_mgr = ns3.text_input("담당자")
                    s_memo = st.text_input("비고", key="aq_site_memo")
                    if st.form_submit_button("사이트 등록", type="primary"):
                        _nm = s_name.strip()
                        if not _nm:
                            st.error("농협명을 입력하세요.")
                        elif _nm in _site_names:
                            st.error("이미 등록된 농협입니다.")
                        else:
                            try:
                                _sid = f"S{len(aq_sites_all) + 1:03d}"
                                aq_append_row("AQ_Sites", [_sid, _nm, s_region, "제안", "", "", "", "", s_mgr, s_memo])
                                aq_load_all.clear()
                                st.success(f"'{_nm}' 등록 완료"); time.sleep(0.5); st.rerun()
                            except Exception as e:
                                st.error(f"등록 실패: {aq_err_str(e)}")
            else:
                _site = next(s for s in aq_sites_all if str(s.get("농협명", "")).strip() == sel_site)
                st.caption(f"상태: {_site.get('상태', '')} · 지역: {_site.get('지역', '')} · 설치일: {_site.get('설치일', '')}")

                st.markdown("##### 1️⃣ 공간(랙) 구성 — 현장 실측 입력 (행 추가/삭제 가능)")
                # [V54] 단깊이 컬럼 폐지(대표님 지시 — 랙 깊이만 사용) · 새 행은 첫 랙 값 자동 상속
                st.caption("📋 **새 랙 행은 명칭만 입력하면 첫 랙의 값(폭·깊이·총높이·단수·단두께·단높이)이 자동 적용**됩니다 — 현장 랙은 대부분 같은 규격이므로 다른 부분만 수정하세요. 저장 시 실제 값으로 기록됩니다.")
                # [V49] 단높이 검증 규칙: 총높이mm 입력 시 Σ단높이 + 단두께×(단수−1) = 총높이 여야 배치에 반영.
                st.caption("📐 **총높이mm**를 입력하면 단높이 합을 검증합니다 — Σ단높이 = 총높이 − 단두께×(단높이 개수−1). 예: 총 2000·두께 40·3단 → 단높이 합이 1920('800,800,320' ✓ / '800,700,320' ✗). 불일치 랙은 맞출 때까지 배치에서 제외됩니다.")
                # [V76] 그룹 = 통로 한쪽 줄 · [V77] 통로가 여럿이면 `통로-쪽` 표기 (대표님 지시 2026-08-11)
                st.caption("🛣️ **그룹 = 통로 한쪽 줄**입니다. 통로에 서서 **오른쪽 랙에 같은 값(예 `A`), 왼쪽 랙에 다른 값(예 `B`)**을 적으세요 — "
                           "화면 배치도·배치도 PDF·**가이드북 지면**이 모두 그 줄대로 그려집니다. "
                           "가이드북은 **한 면에 한 줄 최대 3대 · 위/아래 2줄(최대 3×2)**, 통로가 길면 다음 면으로 이어집니다 "
                           "(오른쪽 6대·왼쪽 5대 → 4p 위 1·2·3/아래 7·8·9, 5p 위 4·5·6/아래 10·11). 비워 두면 종전 방식(순서대로 6대씩)입니다.")
                st.caption("🚏 **통로가 둘 이상이거나 어떤 통로는 한 면만 쓸 때**는 그룹을 **`통로-쪽`**으로 적으세요 — "
                           "`1-오른쪽` `1-왼쪽` `2-오른쪽` 처럼요(구분자 `-` `_` `/` 아무거나). "
                           "**앞부분이 같은 그룹끼리 한 통로**가 되고, **한 펼침면에는 한 통로만** 실립니다 "
                           "(통로가 바뀌면 왼쪽 면부터 새로 시작 — 자리가 어긋나면 백지 한 면이 들어갑니다). "
                           "목차와 지면 제목에도 통로가 표기됩니다. 통로가 하나뿐이면 `A`/`B`처럼 그냥 적어도 됩니다.")
                try: _racks_cur = json.loads(str(_site.get("랙구성JSON") or "[]"))
                except Exception: _racks_cur = []
                # [V71] 랙 복제·삭제(그림 더블클릭)로 바뀐 구성은 세션에 남긴다 —
                #  data_editor는 매 실행 base(시트값)로 되돌아가므로, 오버라이드가 없으면
                #  다음 조작 때 복제한 랙이 사라진다. 💾 사이트 저장에 성공하면 이 키를 비운다.
                _rkov_key = f"aq_racks_ov_{sel_site}"
                _rkov9 = st.session_state.get(_rkov_key)
                if isinstance(_rkov9, list) and _rkov9:
                    _racks_cur = _rkov9
                _rack_cols = ["명칭", "그룹", "폭mm", "깊이mm", "총높이mm", "단수", "단두께mm", "단높이mm(콤마구분)", "비고"]   # [V54] 단깊이 폐지 · [V76] 그룹
                _df_racks_in = pd.DataFrame(_racks_cur)
                for _c in _rack_cols:
                    if _c not in _df_racks_in.columns: _df_racks_in[_c] = ""
                _df_racks_in = _df_racks_in[_rack_cols]
                for _c in ["폭mm", "깊이mm", "총높이mm", "단수", "단두께mm"]:
                    _df_racks_in[_c] = pd.to_numeric(_df_racks_in[_c], errors="coerce")
                # [V55] 상속 가시화 — 상속으로 채운 표를 다음 렌더에 실제 데이터로 주입
                _rkv_key = f"aq_rack_ver_{sel_site}"
                if _rkv_key not in st.session_state: st.session_state[_rkv_key] = 0
                _df_over = st.session_state.pop(f"aq_rack_fill_{sel_site}", None)
                if _df_over is not None:
                    _df_racks_in = _df_over

                def _aq_rack_apply9(recs, _site=sel_site, _cols=_rack_cols, _vk=_rkv_key, _ok=_rkov_key):
                    """[V71] 랙 구성 표를 records로 교체 — 랙 복제·삭제와 그 되돌리기 공통 경로.
                    세션 오버라이드(_ok)에 남겨 다음 실행에서도 유지되게 하고, 편집표 키를 새로 발급한다."""
                    if recs is None: return
                    _dfr = pd.DataFrame(recs)
                    for _c in _cols:
                        if _c not in _dfr.columns: _dfr[_c] = ""
                    _dfr = _dfr[_cols].reset_index(drop=True)
                    st.session_state[_ok] = _dfr.to_dict("records")
                    st.session_state[f"aq_rack_fill_{_site}"] = _dfr
                    st.session_state[_vk] += 1
                    # '표시할 랙' 다중선택은 위젯 상태가 남아 새 랙이 자동으로 켜지지 않는다 —
                    #  없어진 랙은 빼고 새 랙은 더해 준다(이 동기화가 없으면 복제한 랙이 그림에 안 보임).
                    _vwk = f"aq_rk_view_{_site}"
                    _vw = st.session_state.get(_vwk)
                    if isinstance(_vw, list):
                        _nms = [str(r.get("명칭") or "").strip() for r in st.session_state[_ok]
                                if str(r.get("명칭") or "").strip()]
                        st.session_state[_vwk] = ([n for n in _vw if n in _nms or n.startswith("🅥")]
                                                  + [n for n in _nms if n not in _vw])

                _aq_rack_restore9 = _aq_rack_apply9   # ↩️/↪️ 되돌리기에서 쓰는 이름
                df_racks_ed = st.data_editor(
                    _df_racks_in, num_rows="dynamic", hide_index=True,
                    key=f"aq_racks_ed_{sel_site}_{st.session_state[_rkv_key]}",
                    column_config={
                        "그룹": st.column_config.TextColumn(   # [V76] 통로 한쪽 줄
                            width="small",
                            help="통로 한쪽 줄의 이름. 마주 보는 두 줄에 서로 다른 값(예 A / B)을 적으면 "
                                 "가이드북에서 위·아래 줄로 나뉘어 실제 배치대로 읽힙니다. 비우면 종전 방식."),
                        "폭mm": st.column_config.NumberColumn(format="%d"),
                        "깊이mm": st.column_config.NumberColumn(format="%d"),
                        "총높이mm": st.column_config.NumberColumn(format="%d", help="랙 최하단~최상단 전체 높이 — 입력 시 단높이 합 검증"),
                        "단수": st.column_config.NumberColumn(format="%d"),
                        "단두께mm": st.column_config.NumberColumn(format="%d", help="선반(단) 판 두께 — 예 40 (빈칸=0)"),
                    })
                # ── [V54] 첫 랙 값 자동 상속 — 이후 모든 검증·배치·저장은 df_racks_eff 기준 ──
                df_racks_eff = df_racks_ed.copy()
                _base_r = None
                for _bi9, _br9 in df_racks_eff.iterrows():
                    if pd.notna(_br9.get("폭mm")) and str(_br9.get("단높이mm(콤마구분)") or "").strip():
                        _base_r = _br9; break
                if _base_r is not None:
                    for _bi9, _br9 in df_racks_eff.iterrows():
                        _has_any9 = bool(str(_br9.get("명칭") or "").strip()) or pd.notna(_br9.get("폭mm"))
                        if not _has_any9 or _bi9 == _base_r.name: continue
                        for _fc9 in ["폭mm", "깊이mm", "총높이mm", "단수", "단두께mm"]:
                            if pd.isna(_br9.get(_fc9)):
                                df_racks_eff.at[_bi9, _fc9] = _base_r.get(_fc9)
                        # 단높이는 단수가 첫 랙과 같을 때만 상속(다른 단수는 직접 입력)
                        if not str(_br9.get("단높이mm(콤마구분)") or "").strip():
                            try: _cnt_b9 = int(float(df_racks_eff.at[_bi9, "단수"] or 0))
                            except Exception: _cnt_b9 = 0
                            try: _cnt_a9 = int(float(_base_r.get("단수") or 0))
                            except Exception: _cnt_a9 = 0
                            if _cnt_b9 == 0 or _cnt_b9 == _cnt_a9:
                                df_racks_eff.at[_bi9, "단높이mm(콤마구분)"] = _base_r.get("단높이mm(콤마구분)")
                # [V55] 상속으로 값이 채워졌으면 편집표에 즉시 반영(가시화) — 사용자가 채워진 값을 보고 수정
                try:
                    _same_fill9 = df_racks_eff.fillna("").astype(str).equals(df_racks_ed.fillna("").astype(str))
                except Exception:
                    _same_fill9 = True
                if not _same_fill9:
                    st.session_state[f"aq_rack_fill_{sel_site}"] = df_racks_eff
                    st.session_state[_rkv_key] += 1
                    st.rerun()
                # [V49] 랙 총높이 검증 — 불일치 랙은 배치(_rk_list)에서 제외
                _rack_errs, _rack_notes, _bad_racks, _rack_reqs = [], [], set(), []   # [V53] 필요 Σ단높이 안내
                for _ri9, _rr in df_racks_eff.iterrows():
                    _nm9 = str(_rr.get("명칭") or "").strip()
                    _lb9 = _nm9 or f"{_ri9 + 1}행"   # [V54] 이름 없는 새 행도 필요합계 안내
                    try: _tot9 = int(float(_rr.get("총높이mm") or 0))
                    except Exception: _tot9 = 0
                    try: _thk9 = int(float(_rr.get("단두께mm") or 0))
                    except Exception: _thk9 = 0
                    try:
                        _hs9 = [int(float(x)) for x in str(_rr.get("단높이mm(콤마구분)") or "").split(",") if str(x).strip()]
                    except Exception:
                        _hs9 = []
                    try: _cnt9 = int(float(_rr.get("단수") or 0))
                    except Exception: _cnt9 = 0
                    if _tot9 > 0 and (_cnt9 or _hs9):   # [V53] 총높이·단수·단두께 입력 → 필요 Σ단높이 즉시 안내
                        _n9c = _cnt9 or len(_hs9)
                        _req9 = _tot9 - _thk9 * max(0, _n9c - 1)
                        _rack_reqs.append(f"{_lb9}: 필요 Σ단높이 {_req9}mm"
                                          + (f" (현재 {sum(_hs9)})" if _hs9 else ""))
                    if not _nm9: continue
                    if _tot9 > 0 and _hs9:
                        _eff9 = _tot9 - _thk9 * (len(_hs9) - 1)
                        if sum(_hs9) != _eff9:
                            _bad_racks.add(_nm9)
                            _rack_errs.append(f"**{_nm9}**: 단높이 합 {sum(_hs9)} ≠ {_eff9} (총 {_tot9} − 두께 {_thk9}×{len(_hs9) - 1})")
                    if _cnt9 and _hs9 and _cnt9 != len(_hs9):
                        _rack_notes.append(f"{_nm9}: 단수 {_cnt9} ≠ 단높이 {len(_hs9)}개")
                if _rack_reqs:
                    st.caption("📐 **필요 단높이 합** — 총높이 − 단두께×(단수−1): " + " · ".join(_rack_reqs))
                if _rack_errs:
                    st.warning("📐 단높이 합이 총높이와 맞지 않는 랙이 있습니다(입력한 단높이로 그대로 그려집니다 — 확인용 안내).\n- " + "\n- ".join(_rack_errs))
                if _rack_notes:
                    st.caption("ℹ️ 단수 확인: " + " · ".join(_rack_notes))
                # ── [V76] 그룹(통로 한쪽 줄) 미리보기 — 가이드북이 실제로 어떻게 나뉘는지 표에서 바로 확인 ──
                def _aq_cell9(v):   # 편집표의 새 행은 NaN이 온다 — 'nan' 문자열이 그룹명이 되지 않게
                    return "" if v is None or (isinstance(v, float) and pd.isna(v)) else str(v).strip()
                _grk9 = []
                for _ri9, _rr in df_racks_eff.iterrows():
                    _n9g = _aq_cell9(_rr.get("명칭"))
                    if _n9g and not _n9g.startswith("🅥"):   # 가상랙은 도면·인쇄물에서 제외
                        _grk9.append({"명칭": _n9g, "그룹": _aq_cell9(_rr.get("그룹"))})
                _ord_pv9 = st.session_state.get(f"aq_rkord_{sel_site}") or []
                if _ord_pv9:   # 그림에서 끌어 바꾼 랙 순서를 미리보기도 따른다(인쇄물과 같은 순서)
                    _oix_pv9 = {n: i for i, n in enumerate(_ord_pv9)}
                    _grk9.sort(key=lambda r: _oix_pv9.get(r["명칭"], len(_ord_pv9) + 1))
                if any(r["그룹"] for r in _grk9):
                    # [V77] 통로 단위로 보여 준다 — 어느 두 줄이 마주 보는 것으로 잡혔는지 바로 확인
                    _ai9 = aq_rack_aisles(_grk9, 2)
                    st.caption("🛣️ 줄 구성 — " + "   |   ".join(
                        (f"**{_al9 or '통로'}** : " if len(_ai9) > 1 else "")
                        + " · ".join(f"{_g9 or '(미지정)'} {len(_rs9)}대" for _g9, _rs9 in _rows9)
                        for _al9, _rows9 in _ai9))
                    _pv9, _pn9 = [], 4   # 가이드북 배치도는 4페이지부터
                    for _pg9 in _aqp._aq_gb_layout_plan(_grk9):
                        _pv9.append(f"{_pn9}p " + (" / ".join(
                            "·".join(rk["명칭"] for rk in _row9) or "—" for _row9 in _pg9)
                            if _pg9 else "(백지 — 다음 통로를 왼쪽 면부터)"))
                        _pn9 += 1
                    if _pv9:
                        st.caption("📖 가이드북 배치도 지면(위 줄 / 아래 줄) — " + "  |  ".join(_pv9[:8])
                                   + (f"  외 {len(_pv9) - 8}면" if len(_pv9) > 8 else ""))
                # [V44] 슬롯·층수 힌트 (상자 치수 기반)
                _dims_hint = aq_box_dims_map(aq_boxes)
                if _dims_hint:
                    _hint = " · ".join(f"{n} {AQ_STD_INNER // wh[0]}칸" for n, wh in sorted(_dims_hint.items()))
                    st.caption(f"표준 랙(W1200, 내측 1162mm) 단당 칸수: {_hint} — 층수 = 단높이 ÷ 상자높이 (예: 단높이 292 → 431-1호(112) 2층, 3호(116) 2층)")

                st.markdown("##### 2️⃣ 진열할 부속군 선택")
                try: _plan_cur = json.loads(str(_site.get("배치JSON") or "{}"))
                except Exception: _plan_cur = {}
                if not isinstance(_plan_cur, dict): _plan_cur = {}
                _plan_items = _plan_cur.get("items", {}) if isinstance(_plan_cur.get("items", {}), dict) else {}
                _g_default = [g for g in (aq_grp_norm(x) for x in _plan_cur.get("groups", [])) if g in aq_groups]   # [V59] 구군 호환
                plan_groups = st.multiselect("진열분류", aq_groups, default=_g_default, key=f"aq_plan_g_{sel_site}")

                edited_plan = None
                if plan_groups:
                    with st.expander("✏️ 상자·방향·수량 조정 (기본값 자동 적용 — 필요할 때만)", expanded=False):
                        _rows_plan = []
                        for r in aq_items:
                            if (r.get("진열분류") or "(미지정)") not in plan_groups: continue
                            _code = r["품목코드"]
                            _ov = _plan_items.get(_code, {}) if isinstance(_plan_items.get(_code, {}), dict) else {}
                            _caps_i = aq_caps.get(_code, {})
                            _cap_txt = " · ".join(f"{b}:{q}({s})" for b, (q, s) in _caps_i.items())
                            _box_def = str(_ov.get("box") or r.get("기본상자") or "")
                            _ori_def = str(_ov.get("ori") or "세로")            # [V43] 방향 기본=세로(표준)
                            if _ori_def not in ("세로", "가로"): _ori_def = "세로"
                            _use_def = (_ov.get("use", True) is not False)      # [V48] 공급 체크(기본 포함)
                            try:
                                _qty_def = int(_ov.get("qty")) if _ov.get("qty") is not None \
                                    else int(float(str(r.get("기본수량") or 0)))
                            except Exception:
                                _qty_def = 0
                            _p = prod_by_code.get(_code, {})
                            try: _unit_i = int(float(_p.get("price_nh_loc") or 0))
                            except Exception: _unit_i = 0
                            _rows_plan.append({
                                "공급": _use_def,
                                "품목코드": _code, "품목명": str(r.get("품목명_AQ", "") or ""), "규격": str(r.get("규격_AQ", "") or ""),
                                "수용정보": _cap_txt, "상자": _box_def, "방향": _ori_def, "수량": _qty_def, "지역농협가": _unit_i,
                            })
                        _box_opts = sorted(set(aq_box_names) | {rp["상자"] for rp in _rows_plan if rp["상자"]})
                        edited_plan = st.data_editor(
                            pd.DataFrame(_rows_plan), hide_index=True, height=420, key=f"aq_plan_ed_{sel_site}",
                            disabled=["품목코드", "품목명", "규격", "수용정보", "지역농협가"],
                            column_config={
                                "공급": st.column_config.CheckboxColumn("공급", help="체크 해제 = 이 농협에는 공급/배치 제외"),
                                "상자": st.column_config.SelectboxColumn("상자", options=[""] + _box_opts),
                                "방향": st.column_config.SelectboxColumn(
                                    "방향", options=["세로", "가로"],
                                    help="세로=표준(상자 폭이 전면, 최대 배치) · 가로=깊이 얕은 단용(상자 깊이가 전면)"),
                                "수량": st.column_config.NumberColumn(format="%d", min_value=0),
                            })
                        _n_excl = int((~edited_plan["공급"].astype(bool)).sum()) if "공급" in edited_plan.columns else 0
                        if _n_excl:
                            st.caption(f"🚫 공급 제외 {_n_excl}개 품목 (배치·견적에서 빠집니다)")
                else:
                    st.info("진열분류를 선택하면 품목별 계획 표가 나타납니다.")

                # [V48] 품목별 공급 여부 (편집표 우선 → 저장값 → 기본 포함)
                def _aq_use(code):
                    if edited_plan is not None and "공급" in edited_plan.columns:
                        _m = edited_plan.loc[edited_plan["품목코드"] == code, "공급"]
                        if len(_m): return bool(_m.iloc[0])
                    _o = _plan_items.get(code, {})
                    return (_o.get("use", True) is not False) if isinstance(_o, dict) else True

                _aq_by_code = {r["품목코드"]: r for r in aq_items}   # [V49] 코드→AQ_Items 레코드

                # ── [V49] 자유 배치 — 상자에 담기지 않는 품목을 도형/등각(ISO) 이미지로 등록 ──
                _free_cur = _plan_cur.get("free", {}) if isinstance(_plan_cur.get("free", {}), dict) else {}
                df_free = None
                with st.expander("🎨 자유 배치 품목 — 상자 없는 제품 (도형/등각 이미지, 크기 직접 지정)", expanded=False):
                    st.caption("상자 미지정 품목(전시품·행잉·공구류)을 **폭×높이(mm)** 직접 지정으로 단에 올립니다. "
                               "형태 = 사각/원/이미지(등각 ISO 등록 품목만). **품명(코드)·수량 매칭 필수** — 수량·크기가 없으면 배치되지 않습니다. "
                               "랙·단 지정은 아래 3️⃣ 세부 조정 표에서(상자란에 '(자유)'로 표시).")
                    _rows_free = []
                    for r in aq_items:
                        _cf = r["품목코드"]
                        if not _aq_use(_cf): continue
                        _boxf = str((_plan_items.get(_cf, {}) or {}).get("box") or r.get("기본상자") or "").strip()
                        if _boxf: continue   # 상자가 있는 품목은 대상 아님
                        _fc = _free_cur.get(_cf, {}) if isinstance(_free_cur.get(_cf, {}), dict) else {}
                        if not _fc and aq_std_free_of(_cf):   # [V58] 표준 자유배치 존(여과기·지주대) 기본 제공
                            _fc = dict(aq_std_free_of(_cf))
                        _has_iso = bool(str(r.get("이미지ISO", "") or "").strip())
                        try: _wdef = int(_fc.get("w") or 0) or int(float(str(r.get("가로") or 0))) or None
                        except Exception: _wdef = None
                        try: _hdef = int(_fc.get("h") or 0) or int(float(str(r.get("높이") or 0))) or None
                        except Exception: _hdef = None
                        _rows_free.append({
                            "사용": (_cf in _free_cur) or bool(aq_std_free_of(_cf)),   # [V58] 표준 존 기본 사용
                            "품목코드": _cf, "품목명": str(r.get("품목명_AQ", "") or ""), "규격": str(r.get("규격_AQ", "") or ""),
                            "형태": str(_fc.get("shape") or ("이미지" if _has_iso else "사각")),
                            "폭mm": _wdef, "높이mm": _hdef,
                            "수량": int(_fc.get("qty") or 0),
                            "ISO": "✓" if _has_iso else "",
                        })
                    if _rows_free:
                        df_free = st.data_editor(
                            pd.DataFrame(_rows_free), hide_index=True, height=280, key=f"aq_free_ed_{sel_site}",
                            disabled=["품목코드", "품목명", "규격", "ISO"],
                            column_config={
                                "사용": st.column_config.CheckboxColumn("사용", help="체크 = 자유 배치 대상으로 등록"),
                                "형태": st.column_config.SelectboxColumn("형태", options=["사각", "원", "이미지"],
                                                                       help="이미지 = 등각(ISO) 이미지 누끼 표시 (ISO ✓ 품목만)"),
                                "폭mm": st.column_config.NumberColumn(format="%d", min_value=0, help="진열 시 차지하는 전면 폭"),
                                "높이mm": st.column_config.NumberColumn(format="%d", min_value=0),
                                "수량": st.column_config.NumberColumn(format="%d", min_value=0, help="이 자리에 진열하는 수량 (필수)"),
                            })
                    else:
                        st.info("상자 미지정 품목이 없습니다 — 모든 품목에 상자가 지정되어 있습니다.")
                _free_live, _free_bad = {}, []
                if df_free is not None:
                    for _, _rf in df_free.iterrows():
                        if not bool(_rf.get("사용")): continue
                        try: _wf = int(_rf.get("폭mm") or 0)
                        except Exception: _wf = 0
                        try: _hf = int(_rf.get("높이mm") or 0)
                        except Exception: _hf = 0
                        try: _qf = int(_rf.get("수량") or 0)
                        except Exception: _qf = 0
                        if _wf <= 0 or _hf <= 0 or _qf <= 0:
                            _free_bad.append(str(_rf["품목코드"])); continue   # 품명·수량 매칭 강제
                        _shf = str(_rf.get("형태") or "사각")
                        if _shf == "이미지" and not str(_rf.get("ISO") or ""):
                            _shf = "사각"   # ISO 미등록 품목의 이미지 선택 → 사각 폴백
                        _free_live[str(_rf["품목코드"])] = {"shape": _shf, "w": _wf, "h": _hf, "qty": _qf}
                if _free_bad:
                    st.warning(f"🎨 자유 배치 제외 {len(_free_bad)}건 — 폭·높이·수량이 모두 입력되어야 배치됩니다: {', '.join(_free_bad[:6])}{' 외' if len(_free_bad) > 6 else ''}")

                # ── [V45] 단(선반) 중심 배치 설계 — 자동배치 + 실척 시각화 + 수동 조정 ──
                st.markdown("##### 3️⃣ 배치 — ⚡ 자동배치 후 전체 그림으로 확인")
                df_asg = None   # [V49] 세부 조정 표 핸들 (랙·치수 없으면 None 유지 — 저장 시 가드)
                if True:   # [V47] expander→상시 표시(내부 들여쓰기 보존)
                    st.caption("배치의 단위는 **단(선반)**입니다. 용도군(진열분류)별로 단에 군집 배치하고, 단 아래 **색상 자석테이프**로 영역을 표시합니다(색=분류별 지정색). 섹션(세로 열) 개념은 표준화 참고 전용입니다.")
                    _rk_list = []
                    for _, _rr in df_racks_eff.iterrows():   # [V54] 상속 적용본
                        _nm3 = str(_rr.get("명칭") or "").strip()
                        if not _nm3: continue
                        # [V64] 단높이 합이 총높이와 안 맞아도 랙을 숨기지 않는다(입력한 단높이로 그대로 렌더·배치).
                        #  총높이는 검증 안내용일 뿐 — 렌더는 Σ단높이+단두께, 패킹은 단별 높이라 총높이에 의존하지 않음.
                        #  (구: _bad_racks 제외 → 단높이 한 칸만 고쳐도 랙이 통째로 사라지던 문제 해소)
                        try: _wv3 = int(float(_rr.get("폭mm") or 0))
                        except Exception: _wv3 = 0
                        try:
                            _hs3 = [int(float(x)) for x in str(_rr.get("단높이mm(콤마구분)") or "").split(",") if str(x).strip()]
                        except Exception: _hs3 = []
                        try:                                # [V49] 탑뷰용 깊이 정보
                            _ds3 = [int(float(x)) for x in str(_rr.get("단깊이mm(콤마구분)") or "").split(",") if str(x).strip()]
                        except Exception: _ds3 = []
                        try: _dp3 = int(float(_rr.get("깊이mm") or 0))
                        except Exception: _dp3 = 0
                        try: _tk3 = int(float(_rr.get("단두께mm") or 0))   # [V62] 단 판 두께
                        except Exception: _tk3 = 0
                        if _wv3 > 0 and _hs3:
                            _rk_list.append({"명칭": _nm3, "내측폭": _wv3 - 38, "단높이": _hs3,
                                             "단깊이": _ds3, "깊이": _dp3 or 450, "단두께": _tk3,
                                             "그룹": _aq_cell9(_rr.get("그룹"))})   # [V76] 통로 한쪽 줄
                    _dims_p = aq_box_dims_map(aq_boxes)
                    _dims_p.update({f"자유:{c}": (fc["w"], fc["h"]) for c, fc in _free_live.items()})   # [V49] 자유 배치 치수
                    if not _rk_list:
                        st.info("랙 구성에 폭mm·단높이가 입력된 랙이 필요합니다. (📐 표준 시스템 불러오기로 예시 구성 가능)")
                    elif not _dims_p:
                        st.info("상자 치수가 필요합니다 — 📦 상자·수용량 탭에서 폭·높이를 등록하세요.")
                    else:
                        _pg = plan_groups if plan_groups else aq_groups
                        # [V67] 상자 인스턴스 모델(2단계) — 정본 상태 = 인스턴스 리스트(각 상자가 좌표 소유).
                        #  구 assign/split/xord/mstack 4중 모델 폐기(로드는 아래에서 1회 마이그레이션).
                        _inst_key = f"aq_inst_{sel_site}"   # [{"id","code","box","rack","shelf","col","layer"}]
                        _rows_key = f"aq_rows_{sel_site}"   # {코드: 깊이 줄수} — 탑뷰 표시용 메타
                        _ver_key = f"aq_asg_ver_{sel_site}"
                        if _ver_key not in st.session_state: st.session_state[_ver_key] = 0
                        # ── [V51] 가상랙(임시 보관 공간) + 배치 그림 드래그/더블클릭 조작 브리지 ──
                        AQ_VIRT = "🅥 가상랙"
                        if "aq_ops_salt" not in st.session_state:   # 세션 고유 논스 — 이전 세션 조작 재적용 방지
                            st.session_state["aq_ops_salt"] = str(int(time.time() * 1000))
                        _vc1, _vc2 = st.columns([3, 1.4])
                        with _vc1:
                            _virt_on = st.checkbox(
                                "🅥 가상랙 표시 — 꽉 찬 랙의 상자를 잠시 옮겨 둘 임시 공간 (견적·적합판정·자동배치와 무관, 배치는 저장됨)",
                                value=True, key=f"aq_virt_{sel_site}")
                        with _vc2:
                            _virt_pos = st.radio("가상랙 위치", ["맨 앞", "맨 뒤"], horizontal=True,
                                                 key=f"aq_virt_pos_{sel_site}")   # [V56] 즉시 이동
                        _vp_prev9 = st.session_state.get(f"aq_vp_prev_{sel_site}")
                        if _vp_prev9 != _virt_pos:   # 위치 선택이 바뀌면 드래그 순서 기록에서 가상랙 제거(라디오 우선)
                            st.session_state[f"aq_vp_prev_{sel_site}"] = _virt_pos
                            _ro9 = st.session_state.get(f"aq_rkord_{sel_site}")
                            if _ro9:
                                st.session_state[f"aq_rkord_{sel_site}"] = [n for n in _ro9 if n != AQ_VIRT]
                        _virt_rk9 = [{"명칭": AQ_VIRT, "내측폭": 900, "단높이": [600, 600, 600],
                                      "단깊이": [], "깊이": 450}]
                        _rk_all = (((_virt_rk9 if _virt_pos == "맨 앞" else []) + _rk_list
                                    + (_virt_rk9 if _virt_pos == "맨 뒤" else [])) if _virt_on else _rk_list)
                        # ── [V67] 인스턴스 상태 로드 — schema 2는 좌표 그대로, v1 레거시는 1회 마이그레이션 ──
                        if _inst_key not in st.session_state:
                            _rows0 = {}
                            _sv_asg0 = _plan_cur.get("assign", {}) if isinstance(_plan_cur.get("assign", {}), dict) else {}
                            for _c0, _d0 in _sv_asg0.items():
                                if isinstance(_d0, dict):
                                    try: _rows0[str(_c0)] = max(1, int(_d0.get("rows") or 1))
                                    except Exception: pass
                            def _box_of0(c):
                                """저장본에는 상자명이 없다([V68] inst2) — items→기본상자→자유배치 순 재해석."""
                                _r0b = _aq_by_code.get(c, {}) or {}
                                _b0b = str((_plan_items.get(c, {}) or {}).get("box") or _r0b.get("기본상자") or "").strip()
                                if not _b0b and c in _free_live: _b0b = "자유:" + c
                                return _b0b
                            _packed0 = _plan_cur.get("inst2")
                            _insts0 = _plan_cur.get("instances")
                            if isinstance(_packed0, dict) and _packed0:
                                # [V68] 압축 저장본(정식 포맷) — 좌표 그대로 복원, 재계산 없음
                                st.session_state[_inst_key] = aq_inst_unpack(_packed0, _box_of0)
                            elif isinstance(_insts0, list):
                                # schema 2 초기(장황) 포맷 — 저장된 좌표를 그대로 신뢰(재계산 없음)
                                _ld0 = []
                                for _x0 in _insts0:
                                    if not isinstance(_x0, dict): continue
                                    try:
                                        _e0 = {"id": str(_x0.get("id") or ""), "code": str(_x0.get("code") or ""),
                                               "box": str(_x0.get("box") or ""), "rack": str(_x0.get("rack") or ""),
                                               "shelf": int(_x0.get("shelf") or 0),
                                               "col": float(_x0.get("col") or 0), "layer": float(_x0.get("layer") or 0)}
                                    except Exception:
                                        continue
                                    if _e0["id"] and _e0["code"] and _e0["rack"] and _e0["shelf"] > 0:
                                        _ld0.append(_e0)
                                aq_inst_normalize(_ld0)
                                st.session_state[_inst_key] = _ld0
                            else:
                                # v1 → 종전 패킹 규칙을 마지막 1회 재현해 좌표 확정(이후 리런·조작은 재계산 없음)
                                _sv_sp0 = _plan_cur.get("splits", {}) if isinstance(_plan_cur.get("splits", {}), dict) else {}
                                _sv_mst0 = _plan_cur.get("mstack")
                                if isinstance(_sv_mst0, dict): _sv_mst0 = {str(k): str(v) for k, v in _sv_mst0.items()}
                                elif isinstance(_sv_mst0, (list, set)): _sv_mst0 = {str(c): str(c) for c in _sv_mst0}
                                else: _sv_mst0 = {}
                                _mig_seqs0 = {}
                                def _mig_add0(c, rack, shelf, n, ordv):
                                    _b0 = _box_of0(c)
                                    _wh0 = _dims_p.get(_b0)
                                    if not _wh0: return
                                    _r0 = _aq_by_code.get(c, {}) or {}
                                    _g0 = str(_r0.get("진열분류") or "(미지정)")
                                    if ordv is not None:
                                        try: _h0 = float(ordv)
                                        except Exception: _h0 = 1
                                    else:
                                        _se0 = str(_r0.get("섹션", "") or "").strip()
                                        try: _sd0 = int(float(_r0.get("단") or 0))
                                        except Exception: _sd0 = 0
                                        _h0 = AQ_COL_ORD.get(str(_r0.get("열", "") or "").strip(), 1) \
                                            if (_se0 and _sd0 == shelf and rack in (f"섹션{_se0}", _se0)) else 1
                                    for _ in range(max(1, int(n or 1))):
                                        _mig_seqs0.setdefault((rack, shelf), []).append(
                                            (c, _g0, _b0, _wh0[0], _wh0[1], _h0))
                                for _c0, _d0 in _sv_asg0.items():
                                    if not isinstance(_d0, dict): continue
                                    _rk0 = str(_d0.get("rack") or "")
                                    try: _sh0 = int(_d0.get("shelf") or 0)
                                    except Exception: _sh0 = 0
                                    if not _rk0 or _sh0 <= 0: continue
                                    _mig_add0(str(_c0), _rk0, _sh0, _d0.get("n") or 1, _d0.get("ord"))
                                for _c0, _lst0 in _sv_sp0.items():
                                    if not isinstance(_lst0, list): continue
                                    for _e0 in _lst0:
                                        try: _mig_add0(str(_c0), str(_e0[0]), int(_e0[1]), int(_e0[2]), None)
                                        except Exception: continue
                                for _k0 in _mig_seqs0:
                                    _mig_seqs0[_k0] = aq_canon_seq(_mig_seqs0[_k0], _pg)
                                st.session_state[_inst_key] = aq_instances_from_seqs(
                                    _mig_seqs0, _rk_all + ([] if _virt_on else _virt_rk9), mstack=_sv_mst0)
                            st.session_state[_rows_key] = _rows0
                        if _HAS_JS_EVAL:
                            # [V55] 근본 수정: streamlit_js_eval 프론트는 js_expressions "문자열이 바뀔 때만"
                            #  재평가한다(index.html: if (new_value !== data_from_streamlit)). 고정 문자열이라
                            #  최초 1회만 읽고 끝 → 조작이 영영 미반영되던 원인.
                            #  '🔄 배치 조작 반영' 클릭(그림에서 자동클릭 포함) 턴에만 시퀀스를 올려 재평가
                            #  (매 실행 변경은 리런 폭풍 유발 — 실브라우저 검증으로 확인).
                            if st.session_state.pop("aq_ops_bump", False):
                                st.session_state["aq_ops_read_seq"] = st.session_state.get("aq_ops_read_seq", 0) + 1
                            _rdseq9 = st.session_state.get("aq_ops_read_seq", 0)
                            try:
                                _ops_raw = streamlit_js_eval(
                                    js_expressions=f"window.parent.localStorage.getItem('AQ_OPS') /*{_rdseq9}*/",
                                    key=f"aq_ops_{sel_site}")
                            except Exception:
                                _ops_raw = None
                            _ops_pl = None
                            if _ops_raw:
                                try: _ops_pl = json.loads(_ops_raw)
                                except Exception: _ops_pl = None
                            # [V67] 배치(batch) 단위 1회 적용 — 처리된 배치는 재적용 금지, 적용 후 ACK를
                            #  iframe에 주입해 localStorage를 정리시킨다(누적 재전송·무한 버퍼링 근본 차단).
                            #  op id 디둡은 유지 — 전송 중 배치가 합쳐져도 같은 조작이 두 번 반영되지 않게.
                            _nonce_cur = f"{st.session_state['aq_ops_salt']}|{sel_site}"
                            _done_b9 = st.session_state.setdefault(f"aq_done_b_{sel_site}", set())
                            _done_ids = st.session_state.setdefault(f"aq_ops_ids_{sel_site}", set())
                            _batch9 = str(_ops_pl.get("batch") or "") if isinstance(_ops_pl, dict) else ""
                            if (isinstance(_ops_pl, dict) and _ops_pl.get("ops") and _batch9
                                    and _ops_pl.get("nonce") == _nonce_cur and _batch9 not in _done_b9):
                                _done_b9.add(_batch9)
                                if len(_done_b9) > 60:
                                    st.session_state[f"aq_done_b_{sel_site}"] = set(list(_done_b9)[-30:])
                                _new_ops = [o for o in _ops_pl["ops"]
                                            if isinstance(o, dict) and o.get("id") and o["id"] not in _done_ids]
                                if _new_ops:
                                    # [V56] 조작 전 상태 스냅샷 → ↩️ 되돌리기 스택(최근 20건), 새 조작 시 redo 비움
                                    _un9 = st.session_state.setdefault(f"aq_undo_{sel_site}", [])
                                    _un9.append({"inst": [dict(x) for x in st.session_state.get(_inst_key, [])],
                                                 "boxov": dict(st.session_state.get(f"aq_boxov_{sel_site}", {})),
                                                 "rkord": list(st.session_state.get(f"aq_rkord_{sel_site}") or []),
                                                 "rows": dict(st.session_state.get(_rows_key, {}) or {}),
                                                 "racks": df_racks_eff.to_dict("records")})   # [V71] 랙 복제·삭제 되돌리기
                                    if len(_un9) > 20:
                                        del _un9[0]
                                    st.session_state[f"aq_redo_{sel_site}"] = []
                                    # [V67] 인스턴스(iid) 단위 적용 — 각 상자가 좌표를 소유하므로
                                    #  이동/복제/삭제가 그 상자에만 영향(품목 전체 재배치 없음).
                                    #  실패는 삼키지 않고 수집해 화면에 노출(무한 재시도 방지 위해 done은 유지).
                                    _ins9s = st.session_state.setdefault(_inst_key, [])
                                    _op_errs9 = []
                                    _rack_edit9 = None   # [V71] 랙 복제·삭제로 바뀐 랙 구성 표(records)
                                    _rk_by9 = {rk["명칭"]: rk for rk in _rk_all}
                                    def _shelf_h9(rk, sh):
                                        _r9h = _rk_by9.get(str(rk))
                                        try:
                                            return _r9h["단높이"][int(sh) - 1] \
                                                if _r9h and 0 < int(sh) <= len(_r9h["단높이"]) else 0
                                        except Exception:
                                            return 0
                                    for _op9 in _new_ops:
                                        try:
                                            _t9 = _op9.get("t")
                                            _c9o = str(_op9.get("code") or "")
                                            if _t9 == "move" and _op9.get("track") and _op9.get("iid"):
                                                _trk9 = str(_op9["track"]); _tsh9 = int(_op9.get("tshelf") or 0)
                                                _e9m = aq_inst_move(
                                                    _ins9s, str(_op9["iid"]), _trk9, _tsh9,
                                                    xr=_op9.get("xr"), onto=_op9.get("onto"),
                                                    dims=_dims_p, shelf_h=_shelf_h9(_trk9, _tsh9),
                                                    inner=(_rk_by9.get(_trk9) or {}).get("내측폭") or 0,
                                                    anchor=_op9.get("anchor"))   # [V70] 놓은 쪽(좌/우)
                                                if _e9m: _op_errs9.append(_e9m)
                                            elif _t9 == "dup" and _op9.get("iid"):
                                                _sd9 = next((x for x in _ins9s
                                                             if str(x.get("id")) == str(_op9["iid"])), None)
                                                _e9m = aq_inst_dup(
                                                    _ins9s, str(_op9["iid"]), dims=_dims_p,
                                                    shelf_h=(_shelf_h9(_sd9.get("rack"), _sd9.get("shelf"))
                                                             if _sd9 else 0))
                                                if _e9m: _op_errs9.append(_e9m)
                                            elif _t9 == "del" and _op9.get("iid"):
                                                _e9m = aq_inst_del(_ins9s, str(_op9["iid"]))
                                                if _e9m: _op_errs9.append(_e9m)
                                            elif _t9 == "box" and _op9.get("box") and _c9o:   # [V54] 상자 변경(코드 단위)
                                                _bx9o = str(_op9["box"])
                                                if _bx9o not in _dims_p:
                                                    _op_errs9.append(f"{_c9o}: 상자 '{_bx9o}' 치수 미등록 — 변경 불가")
                                                else:
                                                    st.session_state.setdefault(f"aq_boxov_{sel_site}", {})[_c9o] = _bx9o
                                                    for _x9 in _ins9s:
                                                        if str(_x9.get("code")) == _c9o: _x9["box"] = _bx9o
                                                    aq_inst_normalize(_ins9s)
                                            elif _t9 == "rord" and _op9.get("rack") and _op9.get("target"):
                                                # [V55] 랙 순서 변경 — 드래그한 랙을 대상 랙 앞/뒤로
                                                _co9 = (st.session_state.get(f"aq_rkord_{sel_site}")
                                                        or [rk["명칭"] for rk in _rk_all])
                                                _co9 = [n for n in _co9 if n != _op9["rack"]]
                                                if _op9["target"] in _co9:
                                                    _ti9 = _co9.index(_op9["target"]) + (1 if _op9.get("after") else 0)
                                                else:
                                                    _ti9 = len(_co9)
                                                _co9.insert(_ti9, str(_op9["rack"]))
                                                st.session_state[f"aq_rkord_{sel_site}"] = _co9
                                            elif _t9 in ("rdup", "rdel") and _op9.get("rack"):
                                                # [V71] 섹션(랙) 더블클릭 → 복제/삭제. 랙 구성 표(1️⃣)·상자
                                                #  인스턴스·랙 순서를 함께 고쳐 배치·견적·저장에 자동 반영.
                                                _rn9 = str(_op9["rack"])
                                                _recs9 = (_rack_edit9 if _rack_edit9 is not None
                                                          else df_racks_eff.to_dict("records"))
                                                _ix9 = next((_i for _i, _r in enumerate(_recs9)
                                                             if str(_r.get("명칭") or "").strip() == _rn9), None)
                                                _ord9r = list(st.session_state.get(f"aq_rkord_{sel_site}")
                                                              or [rk["명칭"] for rk in _rk_all])
                                                if _rn9 == AQ_VIRT:
                                                    _op_errs9.append("🅥 가상랙은 임시 보관 공간이라 복제·삭제할 수 없습니다.")
                                                elif _ix9 is None:
                                                    _op_errs9.append(f"{_rn9}: 랙 구성 표에서 찾지 못해 건너뜁니다.")
                                                elif _t9 == "rdel":
                                                    del _recs9[_ix9]
                                                    _ins9s[:] = [_x for _x in _ins9s
                                                                 if str(_x.get("rack") or "") != _rn9]
                                                    st.session_state[f"aq_rkord_{sel_site}"] = [
                                                        _n for _n in _ord9r if _n != _rn9]
                                                    _rack_edit9 = _recs9
                                                else:
                                                    _used9 = {str(_r.get("명칭") or "").strip() for _r in _recs9}
                                                    _stem9 = _rn9   # 섹션07-2를 다시 복제하면 섹션07-3 (꼬리표 누적 방지)
                                                    if "-" in _stem9 and _stem9.rsplit("-", 1)[1].isdigit():
                                                        _stem9 = _stem9.rsplit("-", 1)[0]
                                                    _k9r = 2
                                                    while f"{_stem9}-{_k9r}" in _used9: _k9r += 1
                                                    _new9r = f"{_stem9}-{_k9r}"
                                                    _row9r = dict(_recs9[_ix9]); _row9r["명칭"] = _new9r
                                                    _recs9.insert(_ix9 + 1, _row9r)
                                                    if _op9.get("deep"):   # 상자까지 복제 — 좌표 그대로 새 랙에
                                                        for _sx9 in [_x for _x in _ins9s
                                                                     if str(_x.get("rack") or "") == _rn9]:
                                                            _cp9r = dict(_sx9)
                                                            _cp9r["rack"] = _new9r
                                                            _cp9r["id"] = aq_inst_new_id(_ins9s, str(_sx9.get("code")))
                                                            _ins9s.append(_cp9r)
                                                    if _rn9 in _ord9r: _ord9r.insert(_ord9r.index(_rn9) + 1, _new9r)
                                                    else: _ord9r.append(_new9r)
                                                    st.session_state[f"aq_rkord_{sel_site}"] = _ord9r
                                                    _rack_edit9 = _recs9
                                        except Exception as _oe9:
                                            _op_errs9.append(f"{_op9.get('t', '?')} {_op9.get('code', '')}: {aq_err_str(_oe9)}")
                                        _done_ids.add(_op9.get("id"))
                                    if _rack_edit9 is not None:
                                        # [V71] 바뀐 랙 구성을 편집표에 반영 — 다음 리런에서 표가 갱신되고,
                                        #  💾 저장 시 랙구성JSON에 그대로 기록된다.
                                        _aq_rack_apply9(_rack_edit9)
                                        aq_inst_normalize(_ins9s)
                                    if _op_errs9:   # [V65] 실패한 조작을 화면에 노출(조용히 사라지지 않게)
                                        st.session_state["aq_op_errs"] = _op_errs9
                                    if len(_done_ids) > 400:   # 세션 메모리 상한
                                        st.session_state[f"aq_ops_ids_{sel_site}"] = set(list(_done_ids)[-200:])
                                # [V67] ACK — 이 배치는 처리 완료. iframe이 다음 로드에서 localStorage 삭제.
                                #  (_new_ops가 비어도 ACK는 기록 — 이미 반영된 배치의 잔재 정리)
                                st.session_state[f"aq_ack_{sel_site}"] = _batch9
                                st.session_state[_ver_key] += 1
                                st.rerun()
                        # [V55] 랙 순서 적용 (세션 → 없으면 저장된 rack_order) — 표시·자동배치·편집표 공통
                        _ord9 = st.session_state.get(f"aq_rkord_{sel_site}")
                        if not _ord9:
                            _ord9 = [n for n in (_plan_cur.get("rack_order") or []) if isinstance(n, str)]
                            if _ord9:
                                st.session_state[f"aq_rkord_{sel_site}"] = _ord9
                        if _ord9:
                            _oidx9 = {n: i for i, n in enumerate(_ord9)}
                            _rk_all = sorted(_rk_all, key=lambda rk: _oidx9.get(rk["명칭"], 999))
                            _rk_list = sorted(_rk_list, key=lambda rk: _oidx9.get(rk["명칭"], 999))
                        ca1, ca0, ca2 = st.columns([2, 1, 3])
                        with ca0:
                            if st.button("🗑 배치 초기화", key=f"aq_clear_{sel_site}"):
                                st.session_state[_inst_key] = []   # [V67] 인스턴스 전부 제거
                                st.session_state[_ver_key] += 1
                                st.session_state[f"aq_unp_{sel_site}"] = []
                                st.rerun()
                        with ca1:
                            if st.button("⚡ 자동배치 (단 중심 군집)", key=f"aq_auto_{sel_site}",
                                         help="[V67] 누를 때만 실행됩니다 — 기존 수동 배치(드래그 이동·적층 포함)를 "
                                              "전부 표준 규칙 배치로 덮어씁니다. 확정 배치는 💾 사이트 저장으로 보존하세요."):
                                _seq = []
                                for g in _pg:
                                    _gi = [r for r in aq_items if (r.get("진열분류") or "(미지정)") == g]
                                    def _eff_box(r):   # [V49] 유효 상자 — 없으면 자유 배치 치수 사용
                                        _b0 = str((_plan_items.get(r["품목코드"], {}) or {}).get("box") or r.get("기본상자") or "")
                                        if not _b0 and r["품목코드"] in _free_live:
                                            _b0 = "자유:" + r["품목코드"]
                                        return _b0
                                    def _bw_key(r):
                                        return (-_dims_p.get(_eff_box(r), (0, 0))[0], r["품목코드"])
                                    for r in sorted(_gi, key=_bw_key):
                                        if not _aq_use(r["품목코드"]): continue   # [V48] 공급 제외 반영
                                        _seq.append((r["품목코드"], g, _eff_box(r)))
                                # [V53] ① 표준 위치(섹션·단) 우선 — 랙 명칭이 '섹션NN'(또는 'NN')과 일치하면 그 자리에
                                _std_pre9 = {}
                                _rk_by_nm9 = {rk["명칭"]: rk for rk in _rk_list}
                                for _c9s, _g9s, _b9s in _seq:
                                    _r9s = _aq_by_code.get(_c9s, {}) or {}
                                    _sec9 = str(_r9s.get("섹션", "") or "").strip()
                                    try: _sh9s = int(float(_r9s.get("단") or 0))
                                    except Exception: _sh9s = 0
                                    if not _sec9 or _sh9s <= 0: continue
                                    for _cand9 in (f"섹션{_sec9}", _sec9):
                                        _rk9s = _rk_by_nm9.get(_cand9)
                                        if _rk9s and _sh9s <= len(_rk9s["단높이"]):
                                            _std_pre9[_c9s] = (_cand9, _sh9s); break
                                # [V53] ② 루퍼젯 본품(루퍼젯팩)은 가운데 랙 중앙 단 우선
                                _ctr9 = [_c9s for _c9s, _g9s, _b9s in _seq
                                         if _b9s == "루퍼젯팩" and _c9s not in _std_pre9]
                                def _ch_auto9(c, rk, sh):   # [V59] 시험 패킹도 렌더와 같은 열힌트 사용
                                    _r0 = _aq_by_code.get(c, {}) or {}
                                    _se0 = str(_r0.get("섹션", "") or "").strip()
                                    try: _sd0 = int(float(_r0.get("단") or 0))
                                    except Exception: _sd0 = 0
                                    if _se0 and _sd0 == sh and rk in (f"섹션{_se0}", _se0):
                                        return AQ_COL_ORD.get(str(_r0.get("열", "") or "").strip(), 1)
                                    return 1
                                # [V67] 기존 상자수 보존 = 현재 인스턴스 총 개수(분할 포함) — 없으면 표준 상자수
                                _cnt_old9 = {}
                                for _x9 in st.session_state.get(_inst_key, []):
                                    _cd9 = str(_x9.get("code"))
                                    _cnt_old9[_cd9] = _cnt_old9.get(_cd9, 0) + 1
                                def _nf_auto9(c):
                                    return _cnt_old9.get(c, 0) or aq_std_n_of(c)
                                _asg_new, _unp = aq_auto_place(_rk_list, _seq, _dims_p, group_order=_pg,
                                                               pre=_std_pre9, center_codes=_ctr9,
                                                               colhint=_ch_auto9, n_of=_nf_auto9)
                                # [V67] 결과를 인스턴스 좌표로 확정(패킹은 지금 1회만) — 이후 리런은 재계산 없음.
                                #  ⚠ 자동배치는 '누를 때만' 기존 수동 배치(드래그·적층 포함)를 전부 덮어쓴다.
                                _meta9 = {c: (g, b) for c, g, b in _seq}
                                _sq_by9 = {}
                                for _c9a, (_rk9a, _sh9a) in _asg_new.items():
                                    _g9a, _b9a = _meta9.get(_c9a, ("(미지정)", ""))
                                    _wh9a = _dims_p.get(_b9a)
                                    if not _wh9a: continue
                                    for _ in range(max(1, int(_nf_auto9(_c9a) or 1))):
                                        _sq_by9.setdefault((_rk9a, _sh9a), []).append(
                                            (_c9a, _g9a, _b9a, _wh9a[0], _wh9a[1],
                                             _ch_auto9(_c9a, _rk9a, _sh9a)))
                                for _k9a in _sq_by9:
                                    _sq_by9[_k9a] = aq_canon_seq(_sq_by9[_k9a], _pg)
                                st.session_state[_inst_key] = aq_instances_from_seqs(_sq_by9, _rk_all)
                                st.session_state[_ver_key] += 1
                                st.session_state[f"aq_unp_{sel_site}"] = _unp
                                st.rerun()
                        with ca2:
                            _unp_l = st.session_state.get(f"aq_unp_{sel_site}", [])
                            if _unp_l:
                                st.warning(f"미배치 {len(_unp_l)}건(상자 미지정·공간 부족): {', '.join(_unp_l[:8])}{' 외' if len(_unp_l) > 8 else ''}")
                        with st.expander("✏️ 세부 조정 — 품목별 랙·단·상자·줄 (자동배치 결과 수정)", expanded=False):
                            # [V67] 이 표는 인스턴스(상자 좌표) 상태의 요약 뷰 — 편집하면 아래 diff가
                            #  그 품목의 본 자리 상자들만 외과적으로 재배치한다(그림 드래그 배치가 정본).
                            _ins_cur9 = st.session_state.get(_inst_key, [])
                            _rows_meta9 = st.session_state.setdefault(_rows_key, {})
                            _bov4 = st.session_state.get(f"aq_boxov_{sel_site}", {})
                            _agg9, _spl9 = aq_inst_derive_assign(_ins_cur9, _rows_meta9)
                            _ibox9 = {}
                            for _x9 in _ins_cur9:   # 코드→배치된 상자(인스턴스가 정본)
                                _ibox9.setdefault(str(_x9.get("code")), str(_x9.get("box") or ""))
                            _rows_asg = []
                            for g in _pg:
                                for r in aq_items:
                                    if (r.get("진열분류") or "(미지정)") != g: continue
                                    if not _aq_use(r["품목코드"]): continue   # [V48] 공급 제외 반영
                                    _c4 = r["품목코드"]
                                    _b4 = _ibox9.get(_c4, "")
                                    if _b4.startswith("자유:"): _b4 = "(자유)"
                                    if not _b4 and _c4 in _bov4: _b4 = str(_bov4[_c4])   # [V54] 더블클릭 상자 변경
                                    if not _b4 and edited_plan is not None:   # [V49] 진열 계획 편집값
                                        _mb4 = edited_plan.loc[edited_plan["품목코드"] == _c4, "상자"]
                                        if len(_mb4): _b4 = str(_mb4.iloc[0] or "").strip()
                                    if not _b4:
                                        _b4 = str((_plan_items.get(_c4, {}) or {}).get("box") or r.get("기본상자") or "")
                                    if not _b4 and _c4 in _free_live: _b4 = "(자유)"   # [V49] 자유 배치 표시
                                    _d4 = _agg9.get(_c4) or {}
                                    _rows_asg.append({"품목코드": _c4, "품목명": str(r.get("품목명_AQ", "") or ""), "분류": g,
                                                      "상자": _b4, "랙": str(_d4.get("rack") or ""),
                                                      "단": int(_d4.get("shelf") or 0),
                                                      "줄": int(_rows_meta9.get(_c4, 1) or 1),
                                                      "상자수": int(_d4.get("n") or 1)})
                            # [V54] 자유 배치 등록 품목은 분류 미선택/미지정이어도 표에 포함 — 랙·단 지정 가능해야 배치됨
                            _added4 = {rp["품목코드"] for rp in _rows_asg}
                            for _cf4 in _free_live:
                                if _cf4 in _added4: continue
                                _rf4 = _aq_by_code.get(_cf4, {}) or {}
                                _df4 = _agg9.get(_cf4) or {}
                                _rows_asg.append({"품목코드": _cf4, "품목명": str(_rf4.get("품목명_AQ", "") or _cf4),
                                                  "분류": str(_rf4.get("진열분류", "") or "(미지정)"),
                                                  "상자": "(자유)", "랙": str(_df4.get("rack") or ""),
                                                  "단": int(_df4.get("shelf") or 0),
                                                  "줄": int(_rows_meta9.get(_cf4, 1) or 1),
                                                  "상자수": int(_df4.get("n") or 1)})
                            _base9 = {rp["품목코드"]: (rp["랙"], rp["단"], rp["줄"], rp["상자수"], rp["상자"])
                                      for rp in _rows_asg}   # [V67] 표 diff 기준선(이 리런의 뷰 원본)
                            _rk_names = [rk["명칭"] for rk in _rk_all]   # [V51] 가상랙 포함
                            _box_opts4 = sorted(set(aq_box_names) | {rp["상자"] for rp in _rows_asg if rp["상자"] and rp["상자"] != "(자유)"})
                            df_asg = st.data_editor(
                                pd.DataFrame(_rows_asg), hide_index=True, height=300,
                                key=f"aq_asg_ed_{sel_site}_{st.session_state[_ver_key]}",
                                disabled=["품목코드", "품목명", "분류"],
                                column_config={
                                    "상자": st.column_config.SelectboxColumn(   # [V49] 농협별 상자 변경
                                        "상자", options=[""] + _box_opts4 + ["(자유)"],
                                        help="농협 상황에 따라 상자 변경 가능 — 변경 즉시 배치 그림·저장에 반영"),
                                    "랙": st.column_config.SelectboxColumn("랙", options=[""] + _rk_names),
                                    "단": st.column_config.SelectboxColumn(   # [V48] 드롭다운 선택
                                        "단", options=list(range(0, (max(len(rk["단높이"]) for rk in _rk_all) if _rk_all else 8) + 1)),
                                        help="0=미배치 · 1=최하단"),
                                    "줄": st.column_config.SelectboxColumn(   # [V49] 깊이 방향 줄수
                                        "줄", options=[1, 2, 3, 4],
                                        help="깊이 방향 줄수 — 탑뷰에 반영 (예: 루퍼젯 팩은 1단 2줄 가능)"),
                                    "상자수": st.column_config.SelectboxColumn(   # [V51] 전면 상자수
                                        "상자수", options=[1, 2, 3, 4, 5, 6, 7, 8],
                                        help="정면(전면)에 놓는 상자 수 — 그림 더블클릭 복제/삭제와 연동"),
                                })
                        # ── [V67] 표 편집 diff → 인스턴스 외과 적용 (표는 뷰 — 리런마다 재계산하지 않음) ──
                        _rk_by9v = {rk["명칭"]: rk for rk in _rk_all}
                        def _shelfh9v(rk, sh):
                            _r9v = _rk_by9v.get(str(rk))
                            try:
                                return _r9v["단높이"][int(sh) - 1] \
                                    if _r9v and 0 < int(sh) <= len(_r9v["단높이"]) else 0
                            except Exception:
                                return 0
                        _tbl_chg9 = False
                        _tbl_errs9 = []
                        for _, _row4 in df_asg.iterrows():
                            _c5 = str(_row4["품목코드"])
                            _bl5 = _base9.get(_c5)
                            if _bl5 is None: continue
                            _rk5 = str(_row4["랙"] or "").strip()
                            try: _sh5 = int(_row4["단"] or 0)
                            except Exception: _sh5 = 0
                            try: _rw5 = max(1, int(_row4.get("줄") or 1))
                            except Exception: _rw5 = 1
                            try: _n5 = max(0, int(_row4.get("상자수") or 0))
                            except Exception: _n5 = 1
                            _b5 = str(_row4["상자"] or "").strip()
                            if (_rk5, _sh5, _rw5, _n5, _b5) == _bl5: continue
                            _tbl_chg9 = True
                            if _rw5 != _bl5[2]:   # 줄수(깊이) — 탑뷰 표시 메타
                                _rows_meta9[_c5] = _rw5
                            if _b5 != _bl5[4] and _b5 and _b5 != "(자유)":   # 상자 변경(코드 단위 속성)
                                if _b5 not in _dims_p:
                                    _tbl_errs9.append(f"{_c5}: 상자 '{_b5}' 치수 미등록 — 변경 불가")
                                else:
                                    st.session_state.setdefault(f"aq_boxov_{sel_site}", {})[_c5] = _b5
                                    for _x5 in _ins_cur9:
                                        if str(_x5.get("code")) == _c5 and not str(_x5.get("box") or "").startswith("자유:"):
                                            _x5["box"] = _b5
                                    aq_inst_normalize(_ins_cur9)
                            if (_rk5, _sh5) != (_bl5[0], _bl5[1]) or _n5 != _bl5[3]:
                                # 본 자리(구 랙·단) 인스턴스만 제거 후 새 자리에 n개 재배치 — 분할 자리는 유지
                                _eff5 = _b5 or _bl5[4]
                                if _eff5 == "(자유)" or (not _eff5 and _c5 in _free_live):
                                    _eff5 = "자유:" + _c5
                                _old5 = [x for x in _ins_cur9 if str(x.get("code")) == _c5
                                         and (str(x.get("rack")), int(x.get("shelf") or 0)) == (_bl5[0], _bl5[1])]
                                if _rk5 and _sh5 > 0 and _n5 > 0:
                                    if _eff5 not in _dims_p:
                                        _tbl_errs9.append(f"{_c5}: 상자 '{_eff5 or '(미지정)'}' 치수 미등록 — 배치 불가")
                                    else:
                                        for _x5 in _old5: _ins_cur9.remove(_x5)
                                        aq_inst_place_code(_ins_cur9, _c5, _eff5, _rk5, _sh5, _n5,
                                                           dims=_dims_p, shelf_h=_shelfh9v(_rk5, _sh5))
                                else:   # 랙 비움·단 0·상자수 0 → 본 자리 제거(미배치)
                                    for _x5 in _old5: _ins_cur9.remove(_x5)
                                    aq_inst_normalize(_ins_cur9)
                        if _tbl_errs9:
                            st.session_state["aq_op_errs"] = (st.session_state.get("aq_op_errs") or []) + _tbl_errs9
                        if _tbl_chg9:
                            st.session_state[_inst_key] = _ins_cur9
                            st.session_state[_ver_key] += 1
                            st.rerun()
                        # ── [V67] 렌더 준비 — 저장된 좌표 그대로 그린다(패킹·재계산 없음) ──
                        _ins_eff9 = st.session_state.get(_inst_key, [])
                        # [V49] 호버 툴팁 정보(품목명·규격·상자·최대수량) + [V67] 분류(색)·자유 도형 메타
                        _info_map = {}
                        for _x9 in _ins_eff9:
                            _c9 = str(_x9.get("code"))
                            if _c9 in _info_map: continue
                            _r9 = _aq_by_code.get(_c9, {})
                            _bx9i = str(_x9.get("box") or "")
                            _m9 = {"name": str(_r9.get("품목명_AQ", "") or _c9),
                                   "spec": str(_r9.get("규격_AQ", "") or ""),
                                   "grp": str(_r9.get("진열분류") or "(미지정)")}
                            _fc9 = _free_live.get(_c9)
                            if _fc9 and _bx9i.startswith("자유:"):
                                _m9["box"] = "자유 배치"
                                _m9["cap"] = str(_fc9.get("qty") or "")
                                _m9["shape"] = _fc9.get("shape") or "사각"
                                if _m9["shape"] == "이미지":
                                    _iso9 = str(_r9.get("이미지ISO", "") or "").strip()
                                    _uri9 = aq_iso_data_uri(_iso9) if _iso9 else ""
                                    if _uri9: _m9["img"] = _uri9
                                    else: _m9["shape"] = "사각"
                            else:
                                _m9["box"] = _bx9i
                                try: _m9["cap"] = str(aq_caps.get(_c9, {}).get(_bx9i, ("", ""))[0] or "")
                                except Exception: _m9["cap"] = ""
                                if not _m9["cap"]:
                                    _m9["cap"] = "없음"   # [V54] 상자 수용량 기록 없음 → '수량정보 없음' 표기
                                if _bx9i == "루퍼젯팩":   # [V53] 루퍼젯 본품 — 박스 전면에 뒷표기 노출
                                    _nm_t9 = str(_r9.get("품목명_AQ", "") or "").split()
                                    _m9["tag"] = _nm_t9[-1] if _nm_t9 else ""
                            _info_map[_c9] = _m9
                        if st.session_state.get("aq_op_errs"):   # [V65] 조작 반영 중 실패한 것 노출(조용히 사라지지 않게)
                            _oe = st.session_state.pop("aq_op_errs")
                            st.error("⚠️ 일부 배치 조작이 반영되지 않았습니다(무시되고 넘어감) — 아래 확인:\n- " + "\n- ".join(_oe[:8]))
                        _view_rks = st.multiselect("표시할 랙 (기본 전체 — V1 도면처럼 나란히)", _rk_names, default=_rk_names, key=f"aq_rk_view_{sel_site}")
                        _rk_show = [rk for rk in _rk_all if rk["명칭"] in (_view_rks or _rk_names)]   # [V51] 가상랙 포함
                        import streamlit.components.v1 as _components9   # [V49] 호버 툴팁은 iframe에서만 동작
                        # [V67] 렌더 = 인스턴스 좌표 그대로 (mstack·seq 패킹 경로 폐기)
                        _svg_all9 = aq_racks_svg_all(_rk_show, {}, info=_info_map,
                                                     instances=_ins_eff9, dims=_dims_p)
                        if _svg_all9:
                            _nonce9 = f"{st.session_state['aq_ops_salt']}|{sel_site}"   # [V53] ver 제외 — 늦은 조작 유실 방지(op id 중복 차단)
                            _ack9 = str(st.session_state.get(f"aq_ack_{sel_site}", "") or "")   # [V67] 마지막 ACK 배치 id
                            _html9, _hpx9 = aq_svg_hover_html(_svg_all9, interactive=True, nonce=_nonce9,
                                                              boxes=_box_opts4, ack=_ack9)   # [V51/V54/V67]
                            _components9.html(_html9, height=min(_hpx9 + 34, 960), scrolling=True)
                            _cb1, _cbU, _cbR, _cb2 = st.columns([3.4, 1, 1, 1.5])
                            with _cb1:
                                st.caption("🖱️ 호버=정보 · **드래그=상자 1개 이동**(각 상자가 자기 좌표를 기억 — 반영 후에도 그 자리 유지) · **빈 곳 드래그=영역 다중선택 · Shift+클릭=추가 선택**(선택 후 드래그=일괄 이동, Delete=일괄 삭제) · "
                                           "**더블클릭=복제/삭제/상자 변경** · **랙 이름(≡)이나 랙 바탕을 더블클릭 = 그 섹션(랙) 복제/삭제**(랙 구성 표·견적·저장에 자동 반영) · "
                                           "**⛶ 전체화면=꽉 차게 확대+전 상자 품명·규격**(전체화면에서도 이동·삭제 가능). "
                                           "🧱 **다른 상자 위에 올려 놓으면 그 열 위에 적층**(좌표로 저장되어 유지 · 단높이 초과 시 오류로 알려줌). "
                                           "조작은 그림에 즉시 표시되고 **4초 뒤(전체화면은 종료 시) 일괄 반영** — 바로 반영하려면 🔄.")
                            _un_st9 = st.session_state.get(f"aq_undo_{sel_site}") or []
                            _rd_st9 = st.session_state.get(f"aq_redo_{sel_site}") or []
                            with _cbU:
                                if st.button(f"↩️ 되돌리기({len(_un_st9)})", key=f"aq_undo_btn_{sel_site}",
                                             disabled=not _un_st9,
                                             help="그림 조작(이동·복제·삭제·상자 변경·랙 순서)을 한 단계 되돌립니다."):
                                    _rd9 = st.session_state.setdefault(f"aq_redo_{sel_site}", [])
                                    _rd9.append({"inst": [dict(x) for x in st.session_state.get(_inst_key, [])],
                                                 "boxov": dict(st.session_state.get(f"aq_boxov_{sel_site}", {})),
                                                 "rkord": list(st.session_state.get(f"aq_rkord_{sel_site}") or []),
                                                 "rows": dict(st.session_state.get(_rows_key, {}) or {}),
                                                 "racks": df_racks_eff.to_dict("records")})   # [V67/V71]
                                    _sn9 = _un_st9.pop()
                                    st.session_state[_inst_key] = [dict(x) for x in _sn9.get("inst", [])]
                                    st.session_state[f"aq_boxov_{sel_site}"] = _sn9["boxov"]
                                    st.session_state[f"aq_rkord_{sel_site}"] = _sn9["rkord"]
                                    st.session_state[_rows_key] = dict(_sn9.get("rows", {}) or {})
                                    _aq_rack_restore9(_sn9.get("racks"))   # [V71] 랙 구성 표 복원
                                    st.session_state[_ver_key] += 1
                                    st.rerun()
                            with _cbR:
                                if st.button(f"↪️ 다시 실행({len(_rd_st9)})", key=f"aq_redo_btn_{sel_site}",
                                             disabled=not _rd_st9,
                                             help="되돌린 조작을 다시 적용합니다."):
                                    _un9b = st.session_state.setdefault(f"aq_undo_{sel_site}", [])
                                    _un9b.append({"inst": [dict(x) for x in st.session_state.get(_inst_key, [])],
                                                  "boxov": dict(st.session_state.get(f"aq_boxov_{sel_site}", {})),
                                                  "rkord": list(st.session_state.get(f"aq_rkord_{sel_site}") or []),
                                                  "rows": dict(st.session_state.get(_rows_key, {}) or {}),
                                                  "racks": df_racks_eff.to_dict("records")})   # [V67/V71]
                                    _sn9 = _rd_st9.pop()
                                    st.session_state[_inst_key] = [dict(x) for x in _sn9.get("inst", [])]
                                    st.session_state[f"aq_boxov_{sel_site}"] = _sn9["boxov"]
                                    st.session_state[f"aq_rkord_{sel_site}"] = _sn9["rkord"]
                                    st.session_state[_rows_key] = dict(_sn9.get("rows", {}) or {})
                                    _aq_rack_restore9(_sn9.get("racks"))   # [V71] 랙 구성 표 복원
                                    st.session_state[_ver_key] += 1
                                    st.rerun()
                            with _cb2:
                                if st.button("🔄 배치 조작 반영", key=f"aq_ops_apply_{sel_site}",
                                             help="그림에서 드래그·더블클릭한 조작을 표와 배치에 반영합니다."):
                                    st.session_state["aq_ops_bump"] = True   # [V55] 다음 턴에 브리지 재평가
                                    st.rerun()
                            # ── [V69] 배치도 파일 저장 — 캡처 대신 벡터로(확대해도 선명) · 가상랙 제외 ──
                            _ins_real9 = [x for x in _ins_eff9 if str(x.get("rack") or "") != AQ_VIRT]
                            _rk_file9 = [rk for rk in _rk_list if rk["명칭"] != AQ_VIRT]
                            _fd1, _fd2, _fd3 = st.columns([1.5, 1.5, 3])
                            _fstem9 = f"아쿠나리스_배치도_{sel_site}_{datetime.date.today().strftime('%Y%m%d')}"
                            with _fd1:
                                _svg_f9 = _aq_svg_for_file(
                                    aq_racks_svg_all(_rk_file9, {}, per_row=6, scale=0.30, info=_info_map,
                                                     instances=_ins_real9, dims=_dims_p)) if _ins_real9 else ""
                                st.download_button("🖼 배치도 SVG 저장", data=(_svg_f9 or "").encode("utf-8"),
                                                   file_name=f"{_fstem9}.svg", mime="image/svg+xml",
                                                   disabled=not _svg_f9, use_container_width=True,
                                                   key=f"aq_dl_svg_{sel_site}",
                                                   help="벡터 원본 — 확대해도 화질 손실 없음(브라우저·일러스트레이터·한글/워드 삽입 가능). 전 상자 품명·규격 표시.")
                            with _fd2:
                                if st.button("📄 배치도 PDF 만들기", key=f"aq_dl_pdf_go_{sel_site}",
                                             disabled=not _ins_real9, use_container_width=True,
                                             help="A4 가로 1장 벡터 도면 — 인쇄·문서 첨부용."):
                                    try:
                                        st.session_state[f"aq_lay_pdf_{sel_site}"] = aq_layout_pdf_bytes(
                                            sel_site, _rk_file9, _ins_real9, _dims_p, _info_map)
                                    except Exception as _pe9:
                                        st.error(f"배치도 PDF 생성 실패: {aq_err_str(_pe9)}")
                            with _fd3:
                                _lp9 = st.session_state.get(f"aq_lay_pdf_{sel_site}")
                                if _lp9:
                                    st.download_button(f"⬇️ 배치도 PDF ({len(_lp9) // 1024}KB)", data=_lp9,
                                                       file_name=f"{_fstem9}.pdf", mime="application/pdf",
                                                       key=f"aq_dl_pdf_{sel_site}")
                                else:
                                    st.caption("💾 저장하면 이 배치도가 **가이드북 2·3페이지 펼침면**에도 들어갑니다(가상랙 제외).")
                        _leg = " ".join(
                            f'<span style="display:inline-block;width:10px;height:10px;background:{AQ_GROUP_COLORS.get(aq_grp_norm(g), "#9AA0A6")};margin-right:4px;"></span>'
                            f'<span style="font-size:12px;margin-right:10px;">{g}</span>' for g in _pg)
                        st.markdown(_leg, unsafe_allow_html=True)
                        _virt_cnt = len({str(x.get("code")) for x in _ins_eff9 if str(x.get("rack")) == AQ_VIRT})   # [V51/V67]
                        if _virt_cnt:
                            st.info(f"🅥 가상랙 보관 {_virt_cnt}건 — 실제 랙이 아닙니다. 설치 확정 전에 실제 랙으로 옮기거나 단 0(미배치)으로 정리하세요.")
                        # [V67] 좌표 기반 검증 — 렌더와 동일한 좌표로 폭·적층높이·치수미상을 판정(숨김 없음)
                        _over = aq_inst_validate([x for x in _ins_eff9 if str(x.get("rack")) != AQ_VIRT],
                                                 _rk_list, _dims_p)
                        if _over:
                            st.warning("⚠ 배치 검증 — 단높이 조정·상자 변경·자리 이동 필요: " + " / ".join(_over[:6])
                                       + (f" 외 {len(_over) - 6}건" if len(_over) > 6 else ""))
                        elif _ins_eff9:
                            st.success("✅ 배치된 모든 단이 실척 좌표 기준 적합합니다. (열폭 합 ≤ 내측폭 · 적층 높이 ≤ 단높이)")

                        # ── [V49] 탑뷰 — 단 위에서 내려다보기 (깊이 방향 줄 배치) ──
                        with st.expander("🔝 탑뷰 — 단 위에서 내려다보기 (깊이 방향 줄 배치)", expanded=False):
                            _tv_keys = sorted({(str(x.get("rack")), int(x.get("shelf") or 0)) for x in _ins_eff9})
                            if not _tv_keys:
                                st.info("배치된 단이 없습니다 — ⚡ 자동배치 또는 세부 조정에서 랙·단을 지정하세요.")
                            else:
                                _bdep9 = aq_box_depth_map(aq_boxes)
                                _tv_sel = st.selectbox("단 선택", _tv_keys,
                                                       format_func=lambda k: f"{k[0]} · 단{k[1]}", key=f"aq_tv_{sel_site}")
                                _rk_tv = next((x for x in _rk_all if x["명칭"] == _tv_sel[0]), None)   # [V51] 가상랙 포함
                                if _rk_tv and 0 < _tv_sel[1] <= len(_rk_tv["단높이"]):
                                    _dlist9 = _rk_tv.get("단깊이") or []
                                    _dp9 = _dlist9[_tv_sel[1] - 1] if 0 < _tv_sel[1] <= len(_dlist9) else _rk_tv.get("깊이", 450)
                                    _rows_map9 = {c: int(v or 1) for c, v in
                                                  (st.session_state.get(_rows_key) or {}).items()}   # [V67] 줄수 메타
                                    # [V67] 정면과 동일한 인스턴스 좌표 열을 탑뷰에 그대로 사용(재패킹 없음)
                                    _ins_tv9 = [x for x in _ins_eff9
                                                if (str(x.get("rack")), int(x.get("shelf") or 0)) == _tv_sel]
                                    _colsTV, _unkTV = aq_inst_cols(_ins_tv9, _dims_p, _rk_tv["내측폭"])   # [V70]
                                    _cols_tv9 = [(_cx9, _cw9,
                                                  [(str(i9.get("code")),
                                                    str((_info_map.get(str(i9.get("code")), {}) or {}).get("grp") or "(미지정)"),
                                                    str(i9.get("box") or ""), wh9[0], wh9[1])
                                                   for i9, wh9 in _st9])
                                                 for _cx9, _cw9, _st9 in _colsTV]
                                    _svg_tv = aq_shelf_top_svg(_tv_sel[0], _tv_sel[1], _rk_tv["내측폭"],
                                                               _rk_tv["단높이"][_tv_sel[1] - 1], _dp9,
                                                               [], rows_by_code=_rows_map9,
                                                               box_depths=_bdep9, info=_info_map,
                                                               cols=_cols_tv9)
                                    _html_tv, _h_tv = aq_svg_hover_html(_svg_tv)
                                    _components9.html(_html_tv, height=min(_h_tv, 500), scrolling=True)
                                    st.caption("정면도는 맨 앞줄만 보입니다 — 깊이 방향 **줄수**는 세부 조정 표의 '줄' 컬럼으로 지정 "
                                               "(예: 루퍼젯 팩 255×95 → 깊이 450 단에 2줄 이상). 상자 깊이 미등록 시 1줄 전체 깊이로 표시.")
                                else:
                                    st.info("선택한 단 정보를 찾을 수 없습니다.")

                st.markdown("##### 4️⃣ 견적 확인 · 저장")
                _parts2 = 0.0   # [V69] 부속 합계 — 저장 버튼 행의 내부 지표에서도 사용
                if plan_groups and (edited_plan is not None):
                    _bcnt2, _skip2 = {}, []
                    for _, _row in edited_plan.iterrows():
                        if not _aq_use(str(_row["품목코드"])): continue   # [V48] 공급 제외
                        try: _q = int(_row["수량"] or 0)
                        except Exception: _q = 0
                        try: _u = int(_row["지역농협가"] or 0)
                        except Exception: _u = 0
                        if _q <= 0 or _u <= 0:
                            _skip2.append(str(_row["품목코드"])); continue
                        _parts2 += _q * _u
                        _bx2 = str(_row["상자"] or "").strip()
                        if _bx2: _bcnt2[_bx2] = _bcnt2.get(_bx2, 0) + 1
                    _bsum2 = sum(aq_box_price.get(b, 0) * n for b, n in _bcnt2.items())
                    sq1, sq2, sq3, sq4 = st.columns(4)
                    sq1.metric("부속 합계", f"{_parts2:,.0f}원")
                    sq2.metric("상자 하드웨어", f"{_bsum2:,.0f}원")
                    sq3.metric("공급 합계", f"{_parts2 + _bsum2:,.0f}원")
                    sq4.metric("계통2 수수료(참고)", f"-{_parts2 * 0.05:,.0f}원")
                    if _bcnt2:
                        st.caption("상자 구성: " + ", ".join(f"{b}×{n}" for b, n in sorted(_bcnt2.items()))
                                   + " (품목 1종=상자 1개 가정, 상자 단가는 AQ_Boxes 기준)")
                    _n_garo = sum(1 for _, _r2 in edited_plan.iterrows() if str(_r2.get("방향", "")) == "가로")
                    if _n_garo:
                        st.caption(f"↔ 가로 배치 {_n_garo}건 — 깊이 얕은 단용 (전면 폭을 상자 깊이만큼 차지)")
                    if _skip2:
                        st.caption(f"수량/단가 0으로 집계 제외 {len(_skip2)}건")
                    _csv_c1, _csv_c2 = st.columns([1.6, 2.4])
                    with _csv_c1:
                        st.download_button(
                            "⬇️ 사이트 진열계획 CSV",
                            edited_plan.to_csv(index=False).encode("utf-8-sig"),
                            file_name=f"aqunaris_{sel_site}_진열계획.csv", mime="text/csv",
                            key=f"aq_site_csv_{sel_site}", use_container_width=True)
                    with _csv_c2:
                        # [V69] 총괄표의 세부 내역 → 진열 품목 탭으로 바로 이동(그 농협 기준으로 자동 설정)
                        if st.button("🗄️ 이 농협 진열 품목 상세 보기 →", key=f"aq_go_items_{sel_site}",
                                     use_container_width=True,
                                     help="진열 품목 탭으로 이동하며, 배치 기준 사이트를 이 농협으로 자동 설정합니다."):
                            st.session_state["_aq_items_jump"] = sel_site
                            st.session_state["_aq_items_tabjump"] = True
                            st.rerun()

                # ── [V44] 표준 배치 검증 — 랙 단높이 × 상자 치수 × 실배치(V1 위치)로 단별 용량 판정 ──
                with st.expander("📏 표준 배치 검증 (V1 섹션 위치 기준 — 표준화 참고 전용)", expanded=(sel_site == AQ_STD_SITE)):
                    _dims_v = aq_box_dims_map(aq_boxes)
                    _rack_h_map, _inner_by_sec = {}, {}
                    for _, _rr in df_racks_eff.iterrows():   # [V54] 상속 적용본
                        _nm2 = str(_rr.get("명칭") or "")
                        if "섹션" not in _nm2: continue
                        _digits = "".join(ch for ch in _nm2 if ch.isdigit())
                        if not _digits: continue
                        _sec2 = _digits.zfill(2)
                        try:
                            _hs = [int(float(x)) for x in str(_rr.get("단높이mm(콤마구분)") or "").split(",") if str(x).strip()]
                        except Exception:
                            _hs = []
                        if _hs: _rack_h_map[_sec2] = _hs
                        try:
                            _wv = int(float(_rr.get("폭mm") or 0))
                            if _wv > 0: _inner_by_sec[_sec2] = _wv - 38
                        except Exception:
                            pass
                    if not _dims_v:
                        st.info("상자 치수가 없습니다. '📦 상자·수용량' 탭에서 폭·높이를 등록하세요.")
                    elif not _rack_h_map:
                        st.info("랙 구성에 '섹션NN' 명칭의 랙이 없습니다. 📐 표준 시스템 불러오기를 누르면 자동 구성됩니다.")
                    else:
                        _pi_live = dict(_plan_items) if isinstance(_plan_items, dict) else {}
                        if edited_plan is not None:
                            for _, _row in edited_plan.iterrows():
                                _pi_live[str(_row["품목코드"])] = {"box": str(_row["상자"] or "").strip()}
                        _vr = aq_capacity_rows(aq_items, _pi_live, _dims_v, _rack_h_map, inner_by_sec=_inner_by_sec)
                        _n_ok = sum(1 for v in _vr if v["판정"].startswith("✓"))
                        _n_unk = sum(v["미지정"] for v in _vr)
                        cv1, cv2, cv3 = st.columns(3)
                        cv1.metric("검증 단(선반)", f"{len(_vr)}")
                        cv2.metric("적합", f"{_n_ok} / {len(_vr)}")
                        cv3.metric("상자 미지정 품목", f"{_n_unk}")
                        if _n_ok == len(_vr) and _vr:
                            st.success("✅ 전 단 적합 — 표준 시스템과 동일한 배치가 재현됩니다. (Σ상자폭÷층수 ≤ 내측폭)")
                        elif _vr:
                            st.warning("⚠ 초과 단이 있습니다. 상자 변경(가로/작은 상자) 또는 단높이 조정을 검토하세요.")
                        _only_bad = st.checkbox("초과 단만 보기", value=False, key=f"aq_v_bad_{sel_site}")
                        _vshow = [v for v in _vr if not _only_bad or v["판정"].startswith("⚠")]
                        st.dataframe(pd.DataFrame(_vshow), hide_index=True, height=300)

                # [V69] 저장 행 — 왼쪽 저장 버튼, 같은 레벨 **오른쪽 끝**에 내부 지표(눈에 띄지 않게)
                _sv_c1, _sv_c2 = st.columns([6, 1])
                with _sv_c2:
                    if aq_can("aq_profit", strict=True) and (edited_plan is not None):
                        with st.expander("⋯", expanded=False):   # 라벨 최소화 — 현장 시연 화면 보호
                            _buy_sum, _n_nobuy = 0.0, 0
                            for _, _row in edited_plan.iterrows():
                                if not _aq_use(str(_row["품목코드"])): continue
                                try: _q9 = int(_row["수량"] or 0)
                                except Exception: _q9 = 0
                                if _q9 <= 0: continue
                                _p9 = prod_by_code.get(str(_row["품목코드"]), {})
                                try: _b9 = float(_p9.get("price_buy") or 0)
                                except Exception: _b9 = 0.0
                                if _b9 <= 0:
                                    _n_nobuy += 1; continue
                                _buy_sum += _b9 * _q9
                            _rev9 = _parts2
                            _profit9 = _rev9 - _buy_sum
                            _net9 = _rev9 * 0.95 - _buy_sum
                            st.caption("내부 지표 (권한 계정 전용)")
                            pm1, pm2, pm3, pm4 = st.columns(4)
                            pm1.metric("매입 합계", f"{_buy_sum:,.0f}원")
                            pm2.metric("이익(수수료 전)", f"{_profit9:,.0f}원 ({(_profit9 / _rev9 * 100 if _rev9 else 0):.1f}%)")
                            pm3.metric("계통2 반영 순이익", f"{_net9:,.0f}원")
                            pm4.metric("매입가 미등록", f"{_n_nobuy}건")
                            st.caption("이익 = 부속 합계(지역농협가) − 매입 합계 · 계통2 반영 = 매출×95% − 매입 (상자·설치·운송비 별도)")
                if _sv_c1.button("💾 사이트 저장 (랙 구성 + 진열 계획)", type="primary",
                                 key=f"aq_site_save_{sel_site}", use_container_width=True):
                    try:
                        _racks_out = []
                        for _, _rr in df_racks_eff.iterrows():   # [V54] 상속 적용본 저장 = 실제 값으로 기록
                            _d = {}
                            for _c in _rack_cols:
                                _v = _rr.get(_c)
                                _d[_c] = "" if (_v is None or (isinstance(_v, float) and pd.isna(_v))) else _v
                            if not any(str(_v).strip() for _v in _d.values()): continue
                            for _c in ["폭mm", "깊이mm", "총높이mm", "단수", "단두께mm"]:   # [V49] 신규 컬럼 포함
                                try: _d[_c] = int(float(_d[_c])) if str(_d[_c]).strip() else ""
                                except Exception: _d[_c] = str(_d[_c])
                            for _c in ["명칭", "단높이mm(콤마구분)", "비고"]:   # [V54] 단깊이 폐지
                                _d[_c] = str(_d[_c])
                            _d["그룹"] = str(_d.get("그룹") or "").strip()   # [V76] 통로 한쪽 줄
                            _racks_out.append(_d)
                        _items_out = {}
                        if edited_plan is not None:
                            for _, _row in edited_plan.iterrows():
                                try: _q = int(_row["수량"] or 0)
                                except Exception: _q = 0
                                _bx3 = str(_row["상자"] or "").strip()
                                _ori3 = str(_row.get("방향") or "세로").strip() or "세로"   # [V43]
                                _use3 = bool(_row.get("공급", True))                       # [V48]
                                if _q > 0 or _bx3 or (not _use3):
                                    _items_out[str(_row["품목코드"])] = {"box": _bx3, "qty": _q, "ori": _ori3, "use": _use3}
                        # [V49] 세부 조정 표의 상자 변경 반영 (진열 계획 편집표에 없던 오버라이드 포함)
                        if df_asg is not None:
                            for _, _row8 in df_asg.iterrows():
                                _c8 = str(_row8["품목코드"]); _b8 = str(_row8["상자"] or "").strip()
                                if _b8 == "(자유)": _b8 = ""
                                if _c8 in _items_out:
                                    if _b8 != str(_items_out[_c8].get("box", "")).strip():
                                        _items_out[_c8]["box"] = _b8
                                else:
                                    _o8 = _plan_items.get(_c8, {}) if isinstance(_plan_items.get(_c8, {}), dict) else {}
                                    _def8 = str(_o8.get("box") or (_aq_by_code.get(_c8, {}) or {}).get("기본상자") or "").strip()
                                    if _b8 != _def8:
                                        try: _q8 = int(_o8.get("qty") or 0)
                                        except Exception: _q8 = 0
                                        _items_out[_c8] = {"box": _b8, "qty": _q8, "ori": str(_o8.get("ori") or "세로"),
                                                           "use": (_o8.get("use", True) is not False)}
                        _new_plan = {"groups": plan_groups, "items": _items_out,
                                     "updated": datetime.datetime.now().strftime("%Y-%m-%d %H:%M")}
                        # [V49] 자유 배치 저장 (편집표가 없던 리런에서는 기존값 보존)
                        _new_plan["free"] = _free_live if df_free is not None else _free_cur
                        # [V67] 배치 저장 = 상자 인스턴스 좌표(schema 2) — 불러오면 저장 시점 모습 그대로.
                        #  [V68] 시트 셀 50,000자 한도 대응: 좌표는 압축 포맷 inst2(상자명 미저장 — items에서
                        #  재해석), assign/splits는 파생 하위호환(진열품목 탭·인쇄물이 읽음).
                        _ins_sv = st.session_state.get(f"aq_inst_{sel_site}", [])
                        if _ins_sv:
                            _new_plan["schema_version"] = AQ_SCHEMA_V
                            _new_plan["inst2"] = aq_inst_pack(_ins_sv)
                            _asg_dv9, _sp_dv9 = aq_inst_derive_assign(
                                _ins_sv, st.session_state.get(f"aq_rows_{sel_site}") or {})
                            _new_plan["assign"] = _asg_dv9
                            if _sp_dv9:
                                _new_plan["splits"] = _sp_dv9
                        _ord_sv = st.session_state.get(f"aq_rkord_{sel_site}")   # [V55] 랙 순서 저장
                        if _ord_sv:
                            _new_plan["rack_order"] = _ord_sv
                        elif isinstance(_plan_cur.get("rack_order"), list):
                            _new_plan["rack_order"] = _plan_cur["rack_order"]
                        # [V68] 시트 셀 한도(50,000자) 가드 — 공백 없는 JSON + 한도 임박 시
                        #  하위호환 필드부터 단계 생략(좌표 inst2는 항상 보존), 그래도 초과면 저장 중단·안내.
                        _SEP9 = (",", ":")
                        _pj9 = json.dumps(_new_plan, ensure_ascii=False, separators=_SEP9)
                        if len(_pj9) > 49500 and "splits" in _new_plan:
                            _new_plan.pop("splits", None)
                            _pj9 = json.dumps(_new_plan, ensure_ascii=False, separators=_SEP9)
                            st.warning("배치JSON이 커서 하위호환 splits를 생략하고 저장합니다 — 배치 좌표는 전부 보존됩니다.")
                        if len(_pj9) > 49500 and "assign" in _new_plan:
                            _new_plan.pop("assign", None)
                            _pj9 = json.dumps(_new_plan, ensure_ascii=False, separators=_SEP9)
                            st.warning("배치JSON이 커서 하위호환 assign을 생략하고 저장합니다 — 배치 좌표는 전부 보존되지만, "
                                       "진열품목·인쇄물의 '확정 배치 기준' 필터가 이 사이트에선 동작하지 않을 수 있습니다.")
                        if len(_pj9) > 50000:
                            st.error(f"저장 불가: 배치JSON {len(_pj9):,}자 — 시트 셀 한도(50,000자) 초과. "
                                     "배치 품목 수를 줄이거나 다음 세션에서 셀 분할 저장을 요청하세요.")
                        else:
                            for s in aq_sites_all:
                                if str(s.get("농협명", "")).strip() == sel_site:
                                    s["랙구성JSON"] = json.dumps(_racks_out, ensure_ascii=False, separators=_SEP9)
                                    s["배치JSON"] = _pj9
                            aq_save_sites(aq_sites_all)
                            aq_load_all.clear()
                            st.session_state.pop(f"aq_racks_ov_{sel_site}", None)   # [V71] 시트와 동기화됨 — 랙 오버라이드 해제
                            st.success(f"저장 완료 (AQ_Sites 시트 · 배치JSON {len(_pj9):,}자/50,000)")
                            time.sleep(0.5); st.rerun()
                    except Exception as e:
                        st.error(f"저장 실패: {aq_err_str(e)}")

render_brand_footer("Aqunaris Builder")

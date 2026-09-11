# -*- coding: utf-8 -*-
"""[공용] 계정 · 권한 · 로그인 화면 — app.py(V107) L853-870 · L2940-2998.
두 앱이 **같은 로그인 화면**을 쓴다(부제만 다르다). 권한 토큰 = Users 시트 '권한'(master/quote/aqunaris/aq_profit/admin/jp).
"""
import time
import datetime
import streamlit as st
from common.ui import LOGO_YELLOW_B64
from common.db import *

# ── [V48] 계정·권한 — Users 시트 기반. 시트가 없거나 공용 비밀번호 로그인이면 기존 동작 100% 보존 ──
@st.cache_data(ttl=300, show_spinner=False)
def load_users():
    """Users 시트 → list[dict] (아이디 있는 행만). 시트 없음/실패 시 []."""
    if not gc: return []
    try:
        return [u for u in _aq_sh().worksheet("Users").get_all_records()
                if str(u.get("아이디", "")).strip()]
    except Exception:
        return []

def aq_can(perm, strict=False):
    """권한 검사. 공용(비아이디) 로그인 세션: strict=False→허용(기존 동작), strict=True→차단(민감 기능 전용).
    권한 토큰: master/quote/aqunaris/aq_profit/admin/jp (Users 시트 '권한' 쉼표 구분)."""
    perms = st.session_state.get("user_perms")
    if perms is None:
        return not strict
    return ("master" in perms) or (perm in perms)

can = aq_can   # 새 이름 — 옛 이름(aq_can)도 그대로 쓴다


def login_gate(subtitle="PRO MANAGER"):
    """로그인 전이면 로그인 화면을 그리고 st.stop(). 원본 app.py L2940-2998 을 함수로 감쌌다(로직 무변경).
    먼저 st.session_state.db 가 로드돼 있어야 한다(공용 비밀번호 = db config app_pwd)."""
    if "app_authenticated" not in st.session_state:
        st.session_state.app_authenticated = False
        st.session_state.failed_attempts = 0
        st.session_state.lockout_time = None

    if st.session_state.lockout_time:
        if datetime.datetime.now() < st.session_state.lockout_time:
            remaining_time = (st.session_state.lockout_time - datetime.datetime.now()).seconds // 60
            st.error(f"🚫 보안 잠금 상태입니다. {remaining_time + 1}분 후에 다시 시도하세요.")
            st.stop()
        else:
            st.session_state.failed_attempts = 0
            st.session_state.lockout_time = None

    if not st.session_state.app_authenticated:
        _logo_tag = (f'<img src="data:image/png;base64,{LOGO_YELLOW_B64}" style="height:58px;width:auto;margin-bottom:2px;"/>'
                     if LOGO_YELLOW_B64 else '<span style="font-size:44px;font-weight:900;color:#F4D624;letter-spacing:1px;">Looperget</span>')
        st.markdown(
            f"<div style='text-align:center; margin-top:80px; margin-bottom:10px;'>{_logo_tag}"
            f"<div style='color:#F2F1EE;font-size:17px;font-weight:800;letter-spacing:4px;margin-top:10px;'>{subtitle}</div>"
            f"<div style='color:#8C8681;font-size:12px;letter-spacing:1px;margin-top:6px;'>🔒 ShinJinChemTech</div></div>",
            unsafe_allow_html=True)
        col1, col2, col3 = st.columns([1, 1, 1])
        with col2:
            with st.form("login_form", border=True):
                login_id = st.text_input("아이디 (계정 로그인 시 — 비우면 공용 비밀번호)", key="app_login_id")
                pwd = st.text_input("프로그램 접속 비밀번호", type="password", key="app_pwd")
                # [V27] 폼: 비밀번호 입력 후 Enter 또는 '접속' 클릭 둘 다 제출
                # [V48] 아이디 입력 시 Users 시트 계정 인증(기능 권한 부여) · 비우면 기존 공용 비번 그대로
                if st.form_submit_button("접속", use_container_width=True, type="primary"):
                    app_pwd_db = str(st.session_state.db.get("config", {}).get("app_pwd", "1234"))
                    _uid = (login_id or "").strip()
                    _urec = None
                    if _uid:
                        _urec = next((u for u in load_users()
                                      if str(u.get("아이디", "")).strip() == _uid
                                      and str(u.get("비밀번호", "")) == pwd), None)
                    if _urec is not None:
                        st.session_state.app_authenticated = True
                        st.session_state.failed_attempts = 0
                        st.session_state.user_id = _uid
                        st.session_state.user_perms = [p.strip() for p in str(_urec.get("권한", "")).split(",") if p.strip()]
                        st.rerun()
                    elif (not _uid) and pwd == app_pwd_db:
                        st.session_state.app_authenticated = True
                        st.session_state.failed_attempts = 0
                        st.session_state.user_id = ""
                        st.session_state.user_perms = None   # 공용 로그인 = 권한 제한 없음(기존 동작)
                        st.rerun()
                    else:
                        st.session_state.failed_attempts += 1
                        if st.session_state.failed_attempts >= 5:
                            st.session_state.lockout_time = datetime.datetime.now() + datetime.timedelta(minutes=30)
                            st.error("🚫 비밀번호를 5회 틀렸습니다. 30분 동안 접속이 차단됩니다.")
                            time.sleep(2)
                            st.rerun()
                        else:
                            st.error(f"❌ 비밀번호가 틀렸습니다. ({st.session_state.failed_attempts}/5)")
        st.stop()


__all__ = [n for n in list(globals()) if not n.startswith("__")]   # star import 로 밑줄 이름까지 넘긴다

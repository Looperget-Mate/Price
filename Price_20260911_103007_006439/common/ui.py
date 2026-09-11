# -*- coding: utf-8 -*-
"""[공용] 브랜드 UI — 두 앱의 기본 화면을 똑같이 만든다. app.py(V107) L20-24 · L35-89 추출.
테마(색) 정본 = .streamlit/config.toml · 이 CSS · looperget_brand.py(로고).
"""
import streamlit as st

# [V27] 브랜드 로고(옐로우, 다크헤더용) — 없으면 텍스트 폴백
try:
    from looperget_brand import LOGO_YELLOW_B64
except Exception:
    LOGO_YELLOW_B64 = ""

# [V27] 루퍼젯 브랜드 디자인 (다크 인더스트리얼) — 판매가이드 규격
#   Yellow #F4D624 · Black #191414 · White #FFFFFF
_BRAND_CSS = """
<style>
:root { --lg-yellow:#F4D624; --lg-ink:#191414; --lg-line:#3A3433; }
.block-container { padding-top: 3.2rem; }

/* 브랜드 헤더 */
.lg-header { display:flex; align-items:center; gap:14px; padding:8px 2px 13px 2px;
    margin-bottom:14px; border-bottom:3px solid var(--lg-yellow); overflow:visible; }
.lg-header img.lg-logo { height:38px; width:auto; display:block; }
.lg-header .lg-sub { color:#F2F1EE; font-size:19px; font-weight:800; letter-spacing:.3px;
    padding-left:16px; border-left:2px solid var(--lg-line); }
.lg-header .lg-corp { margin-left:auto; color:#8C8681; font-size:12px; font-weight:600; letter-spacing:.3px; }
.lg-header .lg-corp b { color:var(--lg-yellow); }

/* 버튼 — 둥근 모서리·볼드 (색상은 테마 primaryColor=옐로우 사용) */
.stButton>button, .stDownloadButton>button, .stFormSubmitButton>button {
    border-radius:8px; font-weight:700; }

/* 탭 활성 강조 */
.stTabs [aria-selected="true"] { color:var(--lg-yellow) !important; }

/* 구분선·사이드바 */
hr { border-color:var(--lg-line); }
[data-testid="stSidebar"] { border-right:1px solid var(--lg-line); }

/* 브랜드 푸터 */
.lg-footer { margin-top:30px; padding-top:11px; border-top:1px solid var(--lg-line);
    color:#7C7773; font-size:11.5px; letter-spacing:.3px; }
.lg-footer b { color:var(--lg-yellow); }
</style>
"""


def apply_page(page_title, page_icon):
    """페이지 설정(최상단) + 브랜드 CSS — 입구 파일이 맨 먼저 부른다."""
    st.set_page_config(layout="wide", page_title=page_title, page_icon=page_icon)
    st.markdown(_BRAND_CSS, unsafe_allow_html=True)


def render_brand_header(subtitle="프로 매니저"):
    """[V27] 브랜드 헤더(로고+부제) 렌더. 로고 없으면 텍스트 폴백."""
    if LOGO_YELLOW_B64:
        logo_html = f'<img class="lg-logo" src="data:image/png;base64,{LOGO_YELLOW_B64}" alt="Looperget"/>'
    else:
        logo_html = '<span style="font-size:26px;font-weight:900;color:#F4D624;letter-spacing:1px;">Looperget</span>'
    st.markdown(
        f'<div class="lg-header">{logo_html}'
        f'<span class="lg-sub">{subtitle}</span>'
        f'<span class="lg-corp">by <b>ShinJin</b>ChemTech</span></div>',
        unsafe_allow_html=True)

def render_brand_footer(product="Pro Manager"):
    """[V27] 브랜드 푸터. [공용] product = 앱 이름(프로매니저 'Pro Manager' · 아쿠나리스 'Aquanaris Builder')."""
    st.markdown(
        f'<div class="lg-footer"><b>Looperget</b> {product} · ShinJinChemTech · © 2026 신진켐텍(주)</div>',
        unsafe_allow_html=True)


APP_URL_KEYS = {"promanager": "PROMANAGER_URL", "aquanaris": "AQUANARIS_URL"}


def render_app_switch(current):
    """[공용] 사이드바의 「다른 앱 열기」 단추. 주소 = secrets 의 PROMANAGER_URL · AQUANARIS_URL (없으면 안내만)."""
    other, label = (("aquanaris", "🏪 아쿠나리스 빌더 열기") if current == "promanager"
                    else ("promanager", "🟡 루퍼젯 프로매니저 열기"))
    try:
        url = str(st.secrets.get(APP_URL_KEYS[other], "") or "").strip()
    except Exception:
        url = ""
    if url:
        st.link_button(label, url, use_container_width=True)
    else:
        st.caption(f"{label} — 주소 미설정 (secrets `{APP_URL_KEYS[other]}`)")

__all__ = [n for n in list(globals()) if not n.startswith("__")]   # star import 로 밑줄 이름까지 넘긴다

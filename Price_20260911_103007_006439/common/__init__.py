# -*- coding: utf-8 -*-
"""공용 모듈 — 🟡 루퍼젯 프로매니저(app.py)와 🏪 아쿠나리스 빌더(aquanaris_app.py)가 **똑같이** 쓴다.

[2026-09-11] app.py(V107)에서 기계적으로 추출(로직 무변경). 두 앱의 기본 UI·구글 연동·DB·로그인은 여기 한 곳이 정본이다.
  ui.py      브랜드 CSS·헤더·푸터·앱 전환 단추       ← app.py L20-24 · L35-89
  google.py  폰트·구글 서비스·드라이브·이미지        ← app.py L100-486
  db.py      Looperget_DB 시트 로드·저장·시트 핸들    ← app.py L91-98 · L489-641 · L820-828
  auth.py    Users 계정·권한·로그인 화면              ← app.py L853-870 · L2940-2998

📌 여기를 고치면 **두 앱이 함께** 바뀐다. COMMON_VER 를 올리고 두 입구 파일의 가드 기준도 함께 올린다.
🔴 looperget(프로매니저 전용)·aquanaris(아쿠나리스 전용)를 import 하지 않는다 — 시험으로 고정.
"""

COMMON_VER = 1   # [2026-09-11] 프로매니저 V108 · 아쿠나리스 AQ1 분리

__all__ = ["COMMON_VER"]

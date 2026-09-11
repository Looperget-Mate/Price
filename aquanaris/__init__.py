# -*- coding: utf-8 -*-
"""🏪 아쿠나리스 빌더 — 전용 모듈 패키지. [2026-09-11] 루퍼젯 프로매니저에서 분리.

  layout.py      배치 엔진(표준 상수·패킹·자동배치·SVG)   ← aquanaris_layout.py (루트엔 호환 껍데기)
  sheets.py      AQ_* 시트 로드·저장·상자 이름 변경        ← app.py L812-851 · L872-1050
  print_docs.py  스티커·가이드북·배치도 PDF                ← looperget/aq_print.py
  fit.py         재단 되먹임(갈 곳 잃은 품목·여유 용량)     ← looperget/aq_fit.py (S1)

📌 배포 단위 = aquanaris_app.py + aquanaris_layout.py + aquanaris/ + common/ (같은 저장소 Looperget-Mate/Price).
📌 모듈을 추가/변경하면 AQN_VER 를 올리고 aquanaris_app.py 가드 기준도 함께 올린다.
🔴 looperget(프로매니저 · 설계 개념)을 import 하지 않는다 — 대표 지시 · 시험으로 고정.
"""

AQN_VER = 1   # [AQ1 · 2026-09-11] 프로매니저 V107 에서 분리 · S1 재단 되먹임(fit) 포함

__all__ = ["AQN_VER"]

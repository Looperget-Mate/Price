# -*- coding: utf-8 -*-
"""루퍼젯 프로 매니저 — 분리 모듈 패키지.

[V72, 2026-08-05] app.py(556KB·9,085줄) 해체의 1단계.
app.py에서 **자립도가 높은 출력 엔진**을 기계적으로 추출해 이 폴더에 모은다.

⚠️ **배포 단위(프로매니저) = `app.py` + `common/` + `looperget/` 폴더** (+ [V117] 제안서 PPTX 용 `tools/agri_overlay.py` ·
   `_디자인정본/표준_pptx.py` · `_설계/_농업제안서_마스터/…_경량.pptx` — 없으면 앱은 살고 PPTX 만 꺼진다). (🏪 아쿠나리스 = `aqunaris_app.py` + `aqunaris/` + `common/` · 2026-09-11 분리)
   셋 중 하나라도 빠지면 앱 전체가 죽는다(2026-07-24 V67 실사고 — app.py만 푸시되어
   Cloud에서 NameError). 그 재발을 막으려고 모듈을 **폴더 하나**로 묶었다.
   앞으로 모듈이 몇 개로 늘어나도 **올리는 것은 여전히 폴더 하나**다.

📌 모듈을 추가/변경할 때는 `PKG_VER`를 올리고, app.py의 가드 기준도 함께 올린다.
"""

PKG_VER = 111  # [2026-10-04 · 대표 A안] design/cad_ports(+cad_ports.json · tools/cad_sync.py) 설계 CAD 끼움 후보 참고 · editor_ui 🧩 접이식 표시
# PKG_VER 110 # [V117 2단계, 2026-09-23] design/segments(대상 종류 🌾/🏛️/🏗️) · design/customer + customer_text.json(고객 전달본/내부 검토본 두 벌 · 연락처 줄 · 반경 표기) · render_pptx 경량 마스터·부속 사진 공급자 · publish 두 벌·대조
# PKG_VER 109 # [V117, 2026-09-23] 1단계 정합·결함 — summary 접점 도장(K-03·K-08)·R5-3 고리·BOM kit(K-04)·관급 확인(K-05)·렌더 전 사진 관문(K-10) · photos 번호 유지·job 내장(K-01·K-09) · connections 링크별 판정(K-06) · render_pptx R/Ø·고정 도해 치환 · editor_ui 비우기·사진 폴더(K-02·K-11)
# PKG_VER 108 # [V116, 2026-09-22] Codex 공통 제안서 인계 — summary 접점 의도(link_intent)·R5-1 차단 · sets 관급 조달 세트 우선 · photos 현장 사진 · render_pptx 연결 도해·R/Ø
# PKG_VER 107 # [V115, 2026-09-22] Codex 재검토 C01~C03 — summary 급수원 도달성(폐회로 포함)·전 품목 무단가 미확정 · render_xlsx 두 단가 합계 미확정 · publish 시공업체용 견적 대조
# PKG_VER 106 # [V114, 2026-09-22] 제안서 정합(감사 F01~F11) — summary 비용·관문·범위·관경별 세트 · render_pptx 현장요약·운전표 · publish consistency/reprice
# PKG_VER 105 # [V113, 2026-09-22] 사양 정본(결정 #93) — HEAD_PROFILES 제조사 성능표·반경 상한·head_flow_lpm · pipes.PIPE_DIMS · design/lines.py(점적 줄)
#              [V112, 2026-09-18] 지도에 연결 상태 표시(초록·빨강 점) · 🧭 고랑 방향은 전용 임시 선(관 선을 세지 않는다)
#              [V111, 2026-09-16] 지도 도형이 늘어도 컴포넌트 키 불변(mapedit.draw_bridge drafts_hex) — 밭·인입관 첫 그리기가 날아가던 것
#              [V110, 2026-09-16] 연결 사슬 · 열별 세트 · 급수원 가동범위/구역별 요구조건
#              [V108, 2026-09-11] 🏪 아쿠나리스 분리 — aq_print·aq_fit → aqunaris/ · 공용 → common/
#              [V107, 2026-09-09] 접점 유형(junctions 일자·엘보·T)과 밸브 · 세트 신설 후보(design.sets)
#              [V106, 2026-09-09] 재질 전환점(transitions) · 파이프 시작엔 호스밴드 없음 · 계통 품목 입구
#              [V105, 2026-09-09] 관수 방식(노지 3종) · 주배관 재질·관경 · 한 접점 T 하나 · 연결 판정 보정
#              [V104, 2026-09-08] 제안서 지면 지연 임포트(배포 서버에서 견적서만이라도) · 유량 숫자+단위 입력
#              [V103, 2026-09-08] 연결 판정을 양쪽 끝으로(중간 T·끝점끼리) · 분배점=받는 자리 · 말단=열린 끝
#              [V102, 2026-09-08] 스프링클러 추가·균등 정렬 · 안쪽 7 m · 작도판 꽉 채우기 · P3→제안서/견적서(publish.job_from_p3)
#              [V101, 2026-09-08] 스프링클러 빼기(layout.drop_heads · mapedit.toggle_heads) · 빈 작물 정규화
#              [V100, 2026-09-08] 연결 판정(from_ref) · 고랑 방향 긴 변 기본·부호 자동(orient_u)
#              [V79, 2026-09-06] design 패키지 — 「설계(P3)」 모드 연결(intake·mapsrc·design·bom)
#              [V77, 2026-08-11] aq_print 가이드북 지면 — 통로 묶음(그룹명 '통로-쪽')·한 펼침면 한 통로

__all__ = ["PKG_VER"]

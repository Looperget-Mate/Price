"""실링재(테프론 00955) 수량 — 나사 이음 수 ÷ 직경별 비율 (2026-10-08 · 결정 #104).

대표 기준: 50 mm 나사 = 3개당 1롤 · 스프링클러 헤드 = 10개당 1롤 · 그 사이는 나사 직경별로 적절히 분배.
  • 25·32·40 A 비율(8·6·5)은 두 기준 사이를 나사 바깥지름에 비례해 나눈 값 — 대표 승인 2026-10-08(결정 #105).
  • 테이프는 숫나사에 감는다 — 품목 하나 = 나사 이음 하나(상대 숫나사가 고객 보유인 암나사 부속도 1).
  • 품목별 나사 호칭 정본은 상품 DB 「나사 호칭」「나사 종류」 열(결정 #103 ③). 그 열이 생기기 전에는 아래 표
    (CAD 끼움 자리로 확인된 카플러류 + 판매 호칭으로 가정한 품목)를 쓰고, 가정한 것은 비고에 밝힌다.
  • 롤 = 직경별 몫을 더한 뒤 한 번 올림(테이프 한 롤은 직경을 가리지 않는다) · 여분 없음.
"""
from __future__ import annotations

import math

# 이음 몇 개당 1롤 — "head" = 스프링클러 헤드
PER_ROLL = {"head": 10, 15: 10, 20: 10, 25: 8, 32: 6, 40: 5, 50: 3}
CONFIRMED = {"head", 15, 20, 25, 32, 40, 50}   # 헤드·50 = 대표 기준 · 25/32/40 = 바깥지름 비례 보간 → 대표 승인 2026-10-08(결정 #105)
# 품목 → (단위당 나사 이음 수, 나사 호칭 A, 근거)
THREAD_ITEMS = {
    "00951": (1, 50, "CAD"), "00926": (1, 50, "CAD"), "00975": (1, 50, "CAD"), "00970": (1, 50, "CAD"), "00959": (1, 50, "CAD"),
    "00946": (1, 40, "CAD"), "00913": (1, 40, "CAD"), "00924": (1, 40, "CAD"), "01199": (1, 40, "CAD"), "00942": (1, 40, "CAD"),
    "01786": (1, 25, "가정"),                # 숫나사송수밸브 25 mm — 판매 호칭으로 가정
    "00771": (1, 25, "가정"),                # 분수숫싱글밸브 25mm*6~7cm — H25 암나사 25 에 물림(2026-10-08 · 판매 호칭 가정)
    "01870": (2, 20, "확인"),                # 압력계 연결세트(압력계+부싱) — 압력계↔부싱 · 부싱↔새들 · 20A 숫나사(대표 2026-10-08)
}
HEAD_CODES = {"01998", "01920"}            # 헤드 구성(heads.KITS)의 헤드 본체 — 두당 1


def rolls(rows, n_heads):
    """rows = BOM 행(code, base) · n_heads = 두수(여분 제외). 반환 (롤 수, 비고). 나사 이음이 없으면 (0, '')."""
    joints = {}
    if n_heads:
        joints["head"] = int(n_heads)
    for r in rows:
        c = str(r.get("code"))
        if c in THREAD_ITEMS:
            per, dia, how = THREAD_ITEMS[c]
            n = int(r.get("base", r.get("qty", 0)) or 0) * per
            if n:
                joints[dia] = joints.get(dia, 0) + n
    if not joints:
        return 0, ""
    share = sum(n / PER_ROLL[d] for d, n in joints.items())
    qty = max(1, math.ceil(share - 1e-9))
    order = sorted(joints, key=lambda d: (d != "head", 0 if d == "head" else -d))
    # 비고는 고객본에도 나간다 — 계산식만(보간·가정 여부는 이 모듈 표와 내부 보고에 둔다)
    parts = ["%s %d개(%d개당 1)" % ("헤드" if d == "head" else "%d mm 나사" % d, joints[d], PER_ROLL[d]) for d in order]
    return qty, "나사 이음 — " + " + ".join(parts) + " → %d롤" % qty

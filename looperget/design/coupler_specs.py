"""확인된 카플러 사양 → 연결 사슬 포트 채움 (2026-10-04 · 대표 승인 「설계 도입」).

데이터 = coupler_specs.json (tools/coupler_spec_sync.py 가 S1 정본에서 만든 사본 · 승인 9 + 대표 확인 27).
판정 규칙(connections.check_ports)은 바꾸지 않는다. 대표가 확인한 성·등급을 카플러 쪽 포트에 넣어
같은 규칙이 「확인됨」을 낼 수 있게 할 뿐이다.
  • 어느 포트가 카플러 쪽인지는 품목만으로 알 수 없다(물 흐름 방향) → 사람이 고른다.
  • 빈 칸만 채운다. 이미 적힌 값이 확인 사양과 다르면 덮지 않고 알린다.
  • 반대쪽이 나사면 암수만 채운다(S1 「상대」 = 그 끝이 가진 나사 · 2026-10-04 통일, 사양표·CAD 10/10 일치).
    나사 호칭(인치)·규격은 근거가 없어 비워 둔다 → 나사 이음은 기존 규칙대로 근거 전까지 「미확정」.
    송수호스·농수관 쪽은 채우지 않는다.
"""
from __future__ import annotations

import json
import os

_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "coupler_specs.json")
_DATA = None
NONE = "채우지 않음"
THREAD_SEX = {"숫나사": "M", "암나사": "F"}


def _data():
    global _DATA
    if _DATA is None:
        try:
            with open(_PATH, encoding="utf-8") as fh:
                _DATA = json.load(fh)
        except (OSError, ValueError):
            _DATA = {"meta": {}, "specs": {}}
    return _DATA


def spec_for(code):
    """판매 코드 → 확인 사양 dict(name·성·등급·상대·형상·근거) 또는 None."""
    code = str(code or "").strip()
    return _data()["specs"].get(code.zfill(5)) if code else None


def describe(spec):
    other = f" · 반대쪽 {spec['상대']}" if spec.get("상대") else ""
    return f"카플러 {spec['성']}{spec['등급']} · {spec.get('형상') or '형상 미기재'}{other} · 근거: {spec['근거']}"


def options(spec, port_ids=("in", "out")):
    """고를 수 있는 채움 방식 → {표시: {포트ID: (성, 등급)}}. 첫 항목은 늘 「채우지 않음」."""
    ids = list(port_ids) or ["in", "out"]
    sex, grade = spec["성"], spec["등급"]
    result = {NONE: {}}
    if sex == "C/E":                                    # CE밸브 · 변형엘보 — 한쪽 C, 한쪽 E
        result[f"in = C{grade} · out = E{grade}"] = {"in": ("coupler", "C", grade), "out": ("coupler", "E", grade)}
        result[f"in = E{grade} · out = C{grade}"] = {"in": ("coupler", "E", grade), "out": ("coupler", "C", grade)}
    elif grade == "中/小":                              # 이경소켓 — 같은 성, 끝마다 크기 다름
        result[f"in = {sex}中 · out = {sex}小"] = {"in": ("coupler", sex, "中"), "out": ("coupler", sex, "小")}
        result[f"in = {sex}小 · out = {sex}中"] = {"in": ("coupler", sex, "小"), "out": ("coupler", sex, "中")}
    else:
        thread = THREAD_SEX.get(spec.get("상대")) if spec.get("형상") in ("직선", "90도") else None
        for pid in ids:
            plan = {pid: ("coupler", sex, grade)}
            other = [q for q in ("in", "out") if q != pid] if pid in ("in", "out") else []
            if thread and other:
                plan[other[0]] = ("thread", thread, None)
                result[f"{pid} 포트 = {sex}{grade} · {other[0]} = {spec['상대']}({thread})"] = plan
            else:
                result[f"{pid} 포트 = {sex}{grade}"] = plan
        if spec.get("형상") == "T" and spec.get("상대") == "카플러":      # CCCT — 세 구멍 모두 카플러
            result[f"모든 포트 = {sex}{grade}"] = {pid: ("coupler", sex, grade) for pid in ids}
    return result


def fill_ports(ports, spec, choice):
    """선택한 방식대로 빈 칸을 채운 새 ports 와 알림 목록을 돌려준다(원본 불변)."""
    plan = options(spec, list(ports) or ["in", "out"]).get(choice)
    if plan is None:
        raise ValueError("알 수 없는 채움 방식: " + str(choice))
    out = {k: dict(v) for k, v in ports.items()}
    notes = []
    for pid, (kind, sex, grade) in plan.items():
        port = out.setdefault(pid, {})
        want = {"kind": kind, "sex": sex, **({"grade": grade} if grade else {})}
        for key, value in want.items():
            have = port.get(key)
            if have in (None, "", "unknown") or (isinstance(have, float) and have != have):   # 표 빈 칸 = NaN
                port[key] = value
            elif have != value and not (key == "sex" and {"coupler": {"암": "C", "수": "E"}, "thread": {"암": "F", "수": "M", "female": "F", "male": "M"}}[kind].get(have) == value):
                notes.append(f"{pid} 포트 {key}: 입력값 {have} ≠ 확인 사양 {value} — 덮지 않았습니다")
        if not port.get("evidence") or port.get("evidence") != port.get("evidence"):
            port["evidence"] = ("S1 카플러 확인 사양 · " if kind == "coupler" else "S1 상대 나사(호칭 미확정) · ") + spec["근거"]
    return out, notes

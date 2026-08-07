# -*- coding: utf-8 -*-
"""루퍼젯 계산 엔진 v0.1 — 관수 수리(hydraulics) 순수 함수.

[2026-08-05 신설] 팀 편성의 하드 블로커였던 **계산 엔진**의 첫 조각.
불변 원칙 1: *유량·압력·관경·살수반경·수량은 코드가 답한다. LLM 추정 금지.*

설계 원칙
- **순수 함수만**: 입력(스칼라/dict) → 출력(dict). 전역 상태·파일·네트워크 접근 없음.
- **단위를 이름에 박는다**: `_lpm` `_mm` `_m` `_bar`. 단위 혼동이 이 도메인 사고의 1순위 원인.
- **모르는 값은 인자로 받는다.** 기본값으로 슬쩍 채우지 않는다 — 그게 '그럴듯하게 틀린 숫자'의 출발점이다.

⚠ 이 모듈은 아직 app.py에 연결되지 않았다(그래서 `PKG_VER`를 올리지 않았다).
   연결 시 `looperget/__init__.py`의 `PKG_VER`와 app.py 가드 기준을 함께 올릴 것.

테스트: `python tests/test_hydro.py`
"""
import math

__all__ = [
    "head_m_to_bar", "bar_to_head_m", "velocity_ms",
    "hazen_williams_loss_m", "christiansen_f", "lateral_loss_m",
    "line_pressure_profile",
    "heads_on_line", "zone_split", "tank_runtime_min",
    "precipitation_mm_h",
    "nozzle_k", "nozzle_flow_lpm", "nozzle_pressure_bar",
    "pipe_volume_l", "fill_time_min", "charge_penalty",
    "pump_hydraulic_kw", "pump_shaft_hp", "pump_max_flow_lpm",
]

# 1 HP = 0.7457 kW · 물 밀도 1000 kg/m³
_KW_PER_HP = 0.7457
_RHO_G = 1000.0 * 9.80665

# 물기둥 1 m = 0.0980665 bar (4℃ 담수, 표준중력)
_BAR_PER_M = 0.0980665


def head_m_to_bar(head_m):
    """수두(m) → 압력(bar)."""
    return head_m * _BAR_PER_M


def bar_to_head_m(bar):
    """압력(bar) → 수두(m)."""
    return bar / _BAR_PER_M


def velocity_ms(q_lpm, d_mm):
    """유속(m/s). 관경은 **내경**을 넣을 것.

    설계 관행: 송수관 1.5~2.0 m/s 이하. 넘으면 마찰손실·수격이 급증한다.
    """
    if d_mm <= 0:
        raise ValueError("d_mm는 0보다 커야 한다")
    area_m2 = math.pi * (d_mm / 1000.0) ** 2 / 4.0
    return (q_lpm / 60000.0) / area_m2


def hazen_williams_loss_m(q_lpm, d_mm, length_m, c=150):
    """Hazen-Williams 마찰손실 수두(m).

        hf = 10.67 · L · Q^1.852 / (C^1.852 · D^4.87)      [Q m³/s, D m, hf m]

    `c` = 조도계수. PE·PVC 신관 150 / 레이플랫 호스는 제조사 값 확인(미상이면 140 보수적).
    ⚠ 적용 범위: 물, 완전난류, D ≥ 50mm 부근. 소구경 점적관에는 쓰지 않는다.
    """
    if d_mm <= 0 or length_m < 0 or c <= 0:
        raise ValueError("d_mm>0, length_m>=0, c>0 이어야 한다")
    if q_lpm <= 0:
        return 0.0
    q = q_lpm / 60000.0
    d = d_mm / 1000.0
    return 10.67 * length_m * q ** 1.852 / (c ** 1.852 * d ** 4.87)


def christiansen_f(n_outlets, m=1.852):
    """Christiansen 다분출 계수 F.

    분출구가 여러 개 달린 관은 말단으로 갈수록 유량이 준다. 전 구간에 최대 유량이
    흐른다고 계산하면 손실을 **2~3배 과대평가**한다. F가 그 보정이다.
    표준표와 일치: F(1)≈1.00 · F(5)=0.457 · F(10)=0.402 · F(20)=0.376 · F(∞)=0.351
    """
    if n_outlets < 1:
        raise ValueError("n_outlets는 1 이상이어야 한다")
    n = float(n_outlets)
    return 1.0 / (m + 1) + 1.0 / (2 * n) + math.sqrt(m - 1) / (6 * n * n)


def lateral_loss_m(q_lpm_total, d_mm, length_m, n_outlets, c=150):
    """분출구가 균등 배치된 관(=층별 송수호스)의 실제 마찰손실 수두(m).

    = 전 구간 최대유량 손실 × Christiansen F
    """
    return hazen_williams_loss_m(q_lpm_total, d_mm, length_m, c) * christiansen_f(n_outlets)


def line_pressure_profile(inlet_bar, q_lpm, d_mm, length_m, elev_drop_m=0.0, c=150):
    """한 구간을 흐른 뒤의 말단 압력.

    elev_drop_m > 0 = **내려간다**(압력 증가), < 0 = 올라간다(압력 감소).
    반환: inlet_bar / friction_loss_bar / elevation_gain_bar / outlet_bar / velocity_ms
    """
    hf = hazen_williams_loss_m(q_lpm, d_mm, length_m, c)
    out = inlet_bar - head_m_to_bar(hf) + head_m_to_bar(elev_drop_m)
    return {
        "inlet_bar": inlet_bar,
        "friction_loss_m": hf,
        "friction_loss_bar": head_m_to_bar(hf),
        "elevation_gain_bar": head_m_to_bar(elev_drop_m),
        "outlet_bar": out,
        "velocity_ms": velocity_ms(q_lpm, d_mm),
    }


def heads_on_line(line_m, spacing_m, include_both_ends=True):
    """선형(울타리) 위에 간격 spacing_m로 헤드를 놓을 때 개수."""
    if spacing_m <= 0:
        raise ValueError("spacing_m는 0보다 커야 한다")
    n = math.floor(line_m / spacing_m)
    return int(n + 1 if include_both_ends else n)


def zone_split(n_heads, max_simultaneous):
    """동시 살수 가능 수로 나눈 구역 수와 1회전 시간 계산용 기본값."""
    if max_simultaneous <= 0:
        raise ValueError("max_simultaneous는 0보다 커야 한다")
    zones = math.ceil(n_heads / max_simultaneous)
    return {"n_heads": n_heads, "max_simultaneous": max_simultaneous,
            "zones": int(zones),
            "heads_per_zone": math.ceil(n_heads / zones) if zones else 0}


def tank_runtime_min(volume_l, q_lpm_total, refill_lpm=0.0):
    """저수조가 버티는 시간(분). refill_lpm = 살수 중 유입되는 보충 유량.

    refill이 소비를 따라잡으면 `None`(무한 — 저수조가 제약이 아님)을 돌려준다.
    """
    net = q_lpm_total - refill_lpm
    if net <= 0:
        return None
    return volume_l / net


def nozzle_k(q_lpm, bar):
    """노즐 유량계수 K (q = K·√P). 매뉴얼의 (압력, 유량) 한 쌍에서 뽑는다."""
    if bar <= 0:
        raise ValueError("bar는 0보다 커야 한다")
    return q_lpm / math.sqrt(bar)


def nozzle_flow_lpm(k, bar):
    """압력에서 노즐 유량(LPM). 오리피스 유출 — **유량은 압력의 제곱근에 비례한다.**

    압력이 2배가 되어도 유량은 1.41배다. 이 비선형성 때문에 층별 압력차를
    '조금 차이 나는 정도'로 넘기면 안 된다.
    """
    if bar < 0:
        raise ValueError("bar는 0 이상이어야 한다")
    return k * math.sqrt(bar)


def nozzle_pressure_bar(k, q_lpm):
    """목표 유량을 내려면 필요한 압력(bar). nozzle_flow_lpm의 역함수."""
    if k <= 0:
        raise ValueError("k는 0보다 커야 한다")
    return (q_lpm / k) ** 2


def pump_hydraulic_kw(q_lpm, head_m):
    """수동력(kW) = ρ·g·Q·H. 축동력이 아니라 물에 실제로 전달되는 힘."""
    if q_lpm < 0 or head_m < 0:
        raise ValueError("q_lpm, head_m은 0 이상이어야 한다")
    return _RHO_G * (q_lpm / 60000.0) * head_m / 1000.0


def pump_shaft_hp(q_lpm, head_m, efficiency=0.60):
    """필요 축동력(HP). 펌프+모터 종합효율 기본 60%(소형 원심펌프 실무값)."""
    if not 0 < efficiency <= 1:
        raise ValueError("efficiency는 0 초과 1 이하")
    return pump_hydraulic_kw(q_lpm, head_m) / efficiency / _KW_PER_HP


def pump_max_flow_lpm(hp, head_m, efficiency=0.60):
    """주어진 마력·양정에서 낼 수 있는 최대 유량(LPM). pump_shaft_hp의 역함수.

    실무 경험칙 대조용: 2 HP·2 bar(20.4 m)면 약 270 LPM = 427B 19~20개.
    """
    if head_m <= 0:
        raise ValueError("head_m는 0보다 커야 한다")
    kw = hp * _KW_PER_HP * efficiency
    return kw * 1000.0 / (_RHO_G * head_m) * 60000.0


def pipe_volume_l(d_mm, length_m):
    """관 내용적(L). **첫 가동 때 여기가 다 차야 스프링클러가 돈다.**

    현장 경험칙("처음 물 틀 때 배관에 채워지는 물이 상당하다")의 정량화 지점이다.
    """
    if d_mm <= 0 or length_m < 0:
        raise ValueError("d_mm>0, length_m>=0 이어야 한다")
    return math.pi * (d_mm / 1000.0) ** 2 / 4.0 * length_m * 1000.0


def fill_time_min(volume_l, q_lpm):
    """빈 관을 채우는 데 걸리는 시간(분). 이 동안 말단은 물이 안 나온다."""
    if q_lpm <= 0:
        raise ValueError("q_lpm는 0보다 커야 한다")
    return volume_l / q_lpm


def charge_penalty(volume_l, q_lpm, run_min, cycles_per_season=1):
    """충수 손실 평가.

    반환: 충수시간(분) · 살수시간 대비 비율 · 시즌 누적 손실(L)
    `cycles_per_season` = 배수했다가 다시 채우는 횟수.
    **관을 채운 채 두면 이 손실은 시즌 1회로 끝난다** — 배수 주기가 곧 비용이다.
    """
    t = fill_time_min(volume_l, q_lpm)
    return {
        "fill_min": t,
        "run_min": run_min,
        "overhead_pct": 100.0 * t / run_min if run_min > 0 else float("inf"),
        "season_loss_l": volume_l * cycles_per_season,
    }


def precipitation_mm_h(q_lpm, spacing_m, row_spacing_m):
    """살수강도(mm/h) = 시간당 유량 ÷ 담당 면적.

    잔디 관수에서 강도가 토양 침투율을 넘으면 **표면 유출**이 생긴다.
    경사지에서는 이게 곧 세굴이므로 파크골프장 3단 지형에서 특히 중요하다.
    """
    if spacing_m <= 0 or row_spacing_m <= 0:
        raise ValueError("간격은 0보다 커야 한다")
    return (q_lpm * 60.0) / (spacing_m * row_spacing_m)

# -*- coding: utf-8 -*-
"""
looperget.design.mapsrc — 지도 공급자 어댑터 (P3 · 신규 · 프로덕션 무수정).

    from looperget.design import mapsrc
    hit    = mapsrc.geocode("논산시 숙진리 211-1")      # 지번 → PNU·좌표
    par    = mapsrc.parcel(pnu=hit[0]["pnu"])           # PNU → 필지 폴리곤
    fr     = mapsrc.frame(par["center"], zoom=18)       # 위성 프레임(순수)
    poly_m = mapsrc.to_local_m(par["rings"][0], fr["origin"])   # 로컬 미터(순수)
    png    = mapsrc.print_tile(fr)                      # 위성 정지영상 PNG

🔴 **필지 폴리곤은 설계 블록이 아니다.** 지적 경계는 소유 경계이고, 설계 블록은
   대표가 위성 위에서 확정하는 **경작 구역**이다(2026-09-05 실측 — 승인본 5필지 중
   숙진리 211-1은 지적 2,280 ㎡ · 승인본 4,351 ㎡, 212-31은 지적 34,084 ㎡ · 승인본 3,955 ㎡).
   어댑터는 **참고 경계와 지리 기준**까지만 준다. `site.blocks[].polygon`은 대표 입력이다.

계층 구분(역할 문서: 계산 엔진은 순수 함수):
  · 순수 함수 — frame · to_px · to_lonlat · to_local_m · ring_area_m2 · webmercator · inv_webmercator
  · 망 호출 — geocode · parcel · parcels_in_box · print_tile  (.secrets/map_keys.json 필요)

확인된 공급자 제약(2026-09-05 실측 · 브이월드):
  · 정지영상 zoom 7~18 · size <= 1024x1024 → **지상 해상도 상한 0.48 m/px**(위도 36도),
    한 장이 덮는 최대 폭 **493 m**. 그보다 넓거나 더 선명해야 하면 frame을 나눠 여러 장 받는다.
  · bbox 모드 없음 — center+zoom이 필수다. 그래서 지리 기준은 웹 메르카토르 해상도로 계산한다.
  · **고도(DEM)는 아직 경로가 없다** — data LT_C_DEM · wcs · req/dem 세 후보 모두 실패. elevation() 참조.
"""
from __future__ import annotations

import json
import math
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

VERSION = "0.1.0"
SCHEMA = "looperget.design.mapsrc/1"

_R = 6378137.0                      # 웹 메르카토르 기준 반경
_TILE = 256
VWORLD_BASE = "https://api.vworld.kr/req"
PARCEL_LAYER = "LP_PA_CBND_BUBUN"   # 지적도 부분(필지)
ZOOM_RANGE = (7, 18)
SIZE_MAX = 1024
RETRIES = 2                         # 502 는 게이트웨이 답 — 되쏜다
RETRY_WAIT_S = 0.8
RETRY_CODES = (429, 500, 502, 503, 504)
CONTROL_HOST = ("pypi.org", 443)    # 「밖으로 나가긴 하는가」를 가르는 대조군
TILE_PX = 256
# 🔴 브이월드가 **배포 서버의 요청만** 거른다(2026-09-07 점검 확정: DNS·TCP·대조군 ✅ · 실호출 🔴).
#    그래서 배경 위성의 정본을 Esri 로 옮겼다(대표 판단 #59). 키가 없고 국경도 없다.
#    잃는 것 = 지적 경계선·지번 라벨·화질(계절이 다르고 이음매가 보인다).
#    잃어도 되는 이유 = **지적은 대상지가 아니다**(대표 확답 2026-09-05 · #43).
ESRI_TILES = ("https://server.arcgisonline.com/ArcGIS/rest/services/"
              "World_Imagery/MapServer/tile/{z}/{y}/{x}")
ESRI_ATTR = "Esri World Imagery"
OSM_GEOCODE = "https://nominatim.openstreetmap.org/search"

# 🔴 브라우저처럼 말한다. 2026-09-07 배포 실사고에서 같은 요청이 **로컬은 성공 · 클라우드는
#    RemoteDisconnected/502** 였다 — 서버가 요청을 받고 **끊는다**. 국외 IP + 스크립트형
#    User-Agent 를 WAF 가 거르는 경우가 흔해서, 값이 없는 쪽부터 지운다(추정이므로 주석에 남긴다).
HTTP_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"),
    "Accept": "application/json,text/javascript,image/png,image/jpeg,*/*;q=0.8",
    "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.8",
    "Connection": "close",
}

_KEYS: Optional[Dict] = None


# ────────────────────────────── 순수 함수 ──────────────────────────────

def webmercator(lon: float, lat: float) -> Tuple[float, float]:
    """위경도 → 웹 메르카토르(m). EPSG:4326 → EPSG:3857."""
    return (math.radians(lon) * _R,
            math.log(math.tan(math.pi / 4 + math.radians(lat) / 2)) * _R)


def inv_webmercator(mx: float, my: float) -> Tuple[float, float]:
    """웹 메르카토르(m) → 위경도."""
    return (math.degrees(mx / _R),
            math.degrees(2 * math.atan(math.exp(my / _R)) - math.pi / 2))


def zoom_resolution(zoom: int) -> float:
    """줌 단계의 메르카토르 해상도(m/px). 지상 해상도는 여기에 cos(위도)를 곱한다."""
    return 2 * math.pi * _R / (_TILE * 2 ** zoom)


def frame(center: Sequence[float], zoom: int = 18,
          size: Sequence[int] = (1024, 1024)) -> Dict:
    """위성 프레임 = 「화소 ↔ 지리」 변환의 정본. 순수 함수 — 망을 타지 않는다.

    center = (lon, lat) · size = (w, h).
    공급자 제약을 넘으면 ValueError — 미확정 입력으로는 진행하지 않는다(불변 원칙 1).
    """
    lon, lat = float(center[0]), float(center[1])
    w, h = int(size[0]), int(size[1])
    if not (ZOOM_RANGE[0] <= zoom <= ZOOM_RANGE[1]):
        raise ValueError(f"zoom {zoom} — 공급자 허용 범위는 {ZOOM_RANGE[0]}~{ZOOM_RANGE[1]}")
    if not (1 <= w <= SIZE_MAX and 1 <= h <= SIZE_MAX):
        raise ValueError(f"size {w}x{h} — 공급자 상한은 {SIZE_MAX}x{SIZE_MAX}")
    res = zoom_resolution(zoom)
    ground = res * math.cos(math.radians(lat))
    mx, my = webmercator(lon, lat)
    sw = inv_webmercator(mx - res * w / 2, my - res * h / 2)
    ne = inv_webmercator(mx + res * w / 2, my + res * h / 2)
    return {
        "schema": SCHEMA, "kind": "vworld_photo", "center": [lon, lat], "zoom": zoom,
        "size": [w, h], "res_mercator": res, "m_per_px": ground,
        "span_m": [ground * w, ground * h],
        "bbox": [sw[0], sw[1], ne[0], ne[1]],
        "origin": [lon, lat],          # 로컬 미터 좌표계의 원점
        "_mxy": [mx, my],
    }


def tile_xy(lon: float, lat: float, zoom: int) -> Tuple[float, float]:
    """위경도 → **타일 좌표**(실수). 표준 XYZ(웹 메르카토르) 규약. 순수 함수."""
    n = 2.0 ** zoom
    x = (lon + 180.0) / 360.0 * n
    y = (1.0 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2.0 * n
    return x, y


def tile_grid(fr: Dict) -> Dict:
    """프레임을 덮는 **타일 격자**(순수). 어느 타일을 어디에 붙일지까지 답한다.

    반환 = {zoom, x0, x1, y0, y1, ox, oy, n} — `ox·oy` 는 격자 좌상단이 프레임에서 밀린 화소.
    """
    z = fr["zoom"]
    w, h = fr["size"]
    tx, ty = tile_xy(fr["center"][0], fr["center"][1], z)
    px0, py0 = tx * TILE_PX - w / 2.0, ty * TILE_PX - h / 2.0
    x0, y0 = int(math.floor(px0 / TILE_PX)), int(math.floor(py0 / TILE_PX))
    x1 = int(math.floor((px0 + w - 1) / TILE_PX))
    y1 = int(math.floor((py0 + h - 1) / TILE_PX))
    return {"zoom": z, "x0": x0, "x1": x1, "y0": y0, "y1": y1,
            "ox": x0 * TILE_PX - px0, "oy": y0 * TILE_PX - py0,
            "n": (x1 - x0 + 1) * (y1 - y0 + 1)}


def fit_frame(pts_m: Sequence[Sequence[float]], origin: Sequence[float],
              size: int = 1024, margin: float = 1.35, pad_m: float = 30.0,
              zoom_max: int = 18, zoom_min: int = 13) -> Dict:
    """**그린 것에 맞춰 판을 잡는다**(순수). 로컬 미터 점들 → 그 전부가 들어가는 frame.

    지도를 손으로 옮겨 그렸으면 원점은 엉뚱한 데 있을 수 있다 — 판의 중심은
    **원점이 아니라 그린 것**이어야 한다(2026-09-07 대표 「애매한 곳으로 지도가 나오네」).
    줌은 **가장 크게 보이는 단계**를 고른다(공급자 상한 18).
    """
    pts = [q for q in (pts_m or []) if q is not None and len(q) >= 2]
    if not pts:
        raise ValueError("맞출 점이 없다 — 먼저 지도에서 그린다")
    xs = [float(q[0]) for q in pts]
    ys = [float(q[1]) for q in pts]
    cx, cy = (min(xs) + max(xs)) / 2.0, (min(ys) + max(ys)) / 2.0
    span = max(max(xs) - min(xs), max(ys) - min(ys)) * margin + pad_m
    lon, lat = from_local_m([[cx, cy]], origin)[0]
    k = math.cos(math.radians(lat))
    zoom = zoom_min
    for z in range(zoom_max, zoom_min - 1, -1):
        if zoom_resolution(z) * k * size >= span:
            zoom = z
            break
    fr = frame((lon, lat), zoom=zoom, size=(size, size))
    fr["fit_span_m"] = round(span, 1)
    return fr


def to_px(fr: Dict, lon: float, lat: float) -> Tuple[float, float]:
    """위경도 → 프레임 화소 좌표(좌상단 원점 · y 아래로 증가)."""
    mx, my = webmercator(lon, lat)
    cx, cy = fr.get("_mxy") or webmercator(*fr["center"])
    r = fr["res_mercator"]
    w, h = fr["size"]
    return ((mx - cx) / r + w / 2, h / 2 - (my - cy) / r)


def to_lonlat(fr: Dict, x: float, y: float) -> Tuple[float, float]:
    """프레임 화소 좌표 → 위경도. to_px의 역."""
    cx, cy = fr.get("_mxy") or webmercator(*fr["center"])
    r = fr["res_mercator"]
    w, h = fr["size"]
    return inv_webmercator(cx + (x - w / 2) * r, cy + (h / 2 - y) * r)


def to_local_m(ring: Sequence[Sequence[float]], origin: Sequence[float]) -> List[List[float]]:
    """위경도 고리 → 로컬 미터 폴리곤(site.blocks[].polygon 형식 · x 동쪽 · y 북쪽).

    원점 부근 등거리 근사 — 대상지 규모(4 km 이하)에서 오차 0.1 % 미만이다.
    닫힌 고리로 들어오면 마지막 중복점을 뗀다(site 스키마는 열린 폴리곤).
    """
    lon0, lat0 = float(origin[0]), float(origin[1])
    kx = 111320.0 * math.cos(math.radians(lat0))
    ky = 110574.0
    pts = [[round((p[0] - lon0) * kx, 2), round((p[1] - lat0) * ky, 2)] for p in ring]
    if len(pts) > 2 and abs(pts[0][0] - pts[-1][0]) < 1e-6 and abs(pts[0][1] - pts[-1][1]) < 1e-6:
        pts.pop()
    return pts


def from_local_m(pts: Sequence[Sequence[float]], origin: Sequence[float]) -> List[List[float]]:
    """로컬 미터 → 위경도. `to_local_m` 의 역. 순수 함수.

    지도에서 **찍은 점을 다시 지도에 얹을 때** 쓴다(④ 지도에서 찍기 · #57).
    같은 등거리 근사를 반대로 쓰므로 왕복 오차는 반올림(0.01 m)뿐이다.
    """
    lon0, lat0 = float(origin[0]), float(origin[1])
    kx = 111320.0 * math.cos(math.radians(lat0))
    ky = 110574.0
    return [[lon0 + float(q[0]) / kx, lat0 + float(q[1]) / ky] for q in pts]


def ring_area_m2(ring: Sequence[Sequence[float]],
                 origin: Optional[Sequence[float]] = None) -> float:
    """고리의 면적(㎡). 위경도면 origin(없으면 첫 점) 기준 로컬 미터로 바꿔 잰다."""
    pts = to_local_m(ring, origin or ring[0])
    return abs(sum(pts[i][0] * pts[i - 1][1] - pts[i - 1][0] * pts[i][1]
                   for i in range(len(pts)))) / 2


# ────────────────────────────── 망 호출 ──────────────────────────────

def set_keys(d: Optional[Dict]) -> None:
    """지도 키를 **주입**한다 — 배포 환경에는 `.secrets/` 가 없다(불변 원칙 4: 키는 저장소에 안 올린다).

    app.py 는 `st.secrets["map_keys"]` 를 그대로 넘긴다. 비우면(`None`) 파일 경로로 되돌아간다.
    """
    global _KEYS
    _KEYS = dict(d) if d else None


def _keys(path: str = ".secrets/map_keys.json") -> Dict:
    """키 적재(1회). 값은 반환만 하고 **로그·예외 문구에 절대 싣지 않는다**(불변 원칙 4)."""
    global _KEYS
    if _KEYS is None:
        p = Path(path)
        if not p.exists():
            raise FileNotFoundError(f"{path} 없음 — 지도 키는 .secrets/ 에만 둔다(불변 원칙 4)")
        _KEYS = json.loads(p.read_text(encoding="utf-8"))
    return _KEYS


def _vworld(kind: str = "vworld") -> Tuple[str, str]:
    k = _keys().get(kind) or {}
    if not k.get("key"):
        raise KeyError(f"map_keys.json 에 '{kind}'.key 없음")
    return k["key"], k.get("service_url", "")


def _err_text(body: bytes) -> str:
    try:
        e = json.loads(body.decode("utf-8", "replace"))["response"]["error"]
        return f"{e.get('code')}: {e.get('text')}"
    except Exception:
        return body[:200].decode("utf-8", "replace")


def _call(path: str, params: Dict, raw: bool = False, timeout: int = 30,
          what: str = "", retries: int = RETRIES):
    """브이월드 호출 1회 + **재시도**. 실패하면 **어느 호출이 왜 죽었는지** 말한다.

    🔴 502/503/504 는 브이월드 게이트웨이의 답이지 우리 잘못이 아니다 — 그래서 **되쏜다**.
      (2026-09-07 배포 실사고: 앱이 「HTTP Error 502」 한 줄만 내서 어느 단계인지 알 수 없었다.
       로컬 재현 0회 · 미국 IP 에서 검색·데이터·이미지 3종 모두 정상 응답 → **국외 차단 아님**.)
    ⚠ 키는 params 안에 있다 — **예외 문구에 url 을 싣지 않는다**(불변 원칙 4).
    """
    url = f"{VWORLD_BASE}/{path}?" + urllib.parse.urlencode(params, encoding="utf-8")
    req = urllib.request.Request(url, headers=dict(HTTP_HEADERS))
    label = what or path
    last = ""
    for attempt in range(retries + 1):
        try:
            with urllib.request.urlopen(req, timeout=timeout,
                                        context=ssl.create_default_context()) as r:
                body = r.read()
            break
        except urllib.error.HTTPError as e:                     # 공급자가 답은 했다
            last = f"HTTP {e.code} {e.reason}"
            if e.code not in RETRY_CODES:
                raise RuntimeError(f"브이월드 {label} 실패 — {last}") from None
        except (urllib.error.URLError, TimeoutError, OSError) as e:   # 답이 없다
            last = f"{type(e).__name__}: {getattr(e, 'reason', e)}"
        if attempt < retries:
            time.sleep(RETRY_WAIT_S * (attempt + 1))
    else:
        raise RuntimeError(
            f"브이월드 {label} 실패 — {last} (재시도 {retries}회). "
            "공급자 게이트웨이 쪽 응답이다 — 잠시 뒤 다시 누르면 대개 통한다.")
    if raw:
        if body[:4] == b"\x89PNG" or body[:2] == b"\xff\xd8":
            return body
        raise RuntimeError("영상 대신 오류 응답 — " + _err_text(body))
    j = json.loads(body.decode("utf-8", "replace"))
    res = j.get("response", {})
    if res.get("status") == "ERROR":
        e = res.get("error") or {}
        raise RuntimeError(f"브이월드 오류 {e.get('code')}: {e.get('text')}")
    return res


def geocode(query: str, size: int = 5, key_kind: str = "vworld") -> List[Dict]:
    """지번 주소 → [{pnu, address, center}] (없으면 빈 목록).

    ⚠ 상위 행정구역을 틀리게 붙이면 NOT_FOUND가 난다(2026-09-05 실측: 「부적면 숙진리」 실패,
      「논산시 숙진리」 성공 → 실제는 **상월면**). **읍·면은 추측해서 붙이지 않는다.**
    """
    key, dom = _vworld(key_kind)
    res = _call("search", {
        "service": "search", "request": "search", "version": "2.0", "crs": "EPSG:4326",
        "size": str(size), "page": "1", "query": query, "type": "address",
        "category": "parcel", "format": "json", "errorformat": "json",
        "key": key, "domain": dom}, what="지번 검색")
    if res.get("status") != "OK":
        return []
    out = []
    for it in ((res.get("result") or {}).get("items") or []):
        pt = it.get("point") or {}
        out.append({"pnu": it.get("id"),
                    "address": (it.get("address") or {}).get("parcel"),
                    "center": [float(pt["x"]), float(pt["y"])]})
    return out


def _feature_to_parcel(f: Dict, origin: Optional[Sequence[float]] = None) -> Dict:
    pr = f.get("properties", {})
    g = f.get("geometry", {})
    coords = g.get("coordinates") or []
    rings = coords if g.get("type") == "Polygon" else [r for poly in coords for r in poly]
    rings = [[[float(p[0]), float(p[1])] for p in ring] for ring in rings]
    outer = rings[0]
    o = origin or outer[0]
    cx = sum(p[0] for p in outer) / len(outer)
    cy = sum(p[1] for p in outer) / len(outer)
    return {
        "schema": SCHEMA, "pnu": pr.get("pnu"), "address": pr.get("addr"),
        "jibun": pr.get("jibun"), "geom_type": g.get("type"),
        "rings": rings, "center": [cx, cy],
        "area_m2": round(ring_area_m2(outer, o), 1),
        "n_pts": len(outer) - 1,
        "source": {"provider": "vworld", "layer": PARCEL_LAYER,
                   "gosi": f"{pr.get('gosi_year')}-{pr.get('gosi_month')}"},
    }


def parcel(pnu: Optional[str] = None, center: Optional[Sequence[float]] = None,
           key_kind: str = "vworld") -> Optional[Dict]:
    """PNU(또는 좌표) → 필지 1개. **설계 블록이 아니라 참고 경계다**(모듈 docstring)."""
    if not pnu and not center:
        raise ValueError("pnu 또는 center 중 하나는 필요하다")
    key, dom = _vworld(key_kind)
    p = {"service": "data", "request": "GetFeature", "data": PARCEL_LAYER,
         "key": key, "domain": dom, "format": "json", "errorformat": "json",
         "crs": "EPSG:4326", "geometry": "true", "attribute": "true",
         "size": "5", "page": "1"}
    if pnu:
        p["attrFilter"] = f"pnu:=:{pnu}"
    else:
        p["geomFilter"] = f"POINT({center[0]} {center[1]})"
    res = _call("data", p, what="필지 조회")
    feats = ((res.get("result") or {}).get("featureCollection") or {}).get("features") or []
    return _feature_to_parcel(feats[0]) if feats else None


def parcels_in_box(center: Sequence[float], radius_m: float = 250.0,
                   max_pages: int = 5, key_kind: str = "vworld") -> List[Dict]:
    """중심에서 반경(정사각 박스) 안의 필지 목록. PNU로 중복을 제거한다.

    ⚠ 페이지를 넘겨도 같은 묶음이 다시 오는 일이 있다(2026-09-05 실측) —
      **새 PNU가 하나도 없으면 멈춘다.**
    """
    key, dom = _vworld(key_kind)
    lon, lat = float(center[0]), float(center[1])
    kx = 111320.0 * math.cos(math.radians(lat))
    dlon, dlat = radius_m / kx, radius_m / 110574.0
    box = f"BOX({lon-dlon:.8f},{lat-dlat:.8f},{lon+dlon:.8f},{lat+dlat:.8f})"
    seen: Dict[str, Dict] = {}
    for page in range(1, max_pages + 1):
        res = _call("data", {
            "service": "data", "request": "GetFeature", "data": PARCEL_LAYER,
            "key": key, "domain": dom, "format": "json", "errorformat": "json",
            "crs": "EPSG:4326", "geometry": "true", "attribute": "true",
            "geomFilter": box, "size": "100", "page": str(page)},
            what=f"주변 필지 {page}쪽")
        feats = ((res.get("result") or {}).get("featureCollection") or {}).get("features") or []
        new = 0
        for f in feats:
            pc = _feature_to_parcel(f, origin=(lon, lat))
            if pc["pnu"] and pc["pnu"] not in seen:
                seen[pc["pnu"]] = pc
                new += 1
        if not feats or new == 0:
            break
    return list(seen.values())


def print_tile(fr: Dict, basemap: str = "PHOTO", fmt: str = "png",
               key_kind: str = "vworld") -> bytes:
    """프레임 그대로의 위성 정지영상(bytes). frame()이 이미 공급자 제약을 지켰다.

    basemap: PHOTO(위성) · PHOTO_HYBRID(위성+주기) · GRAPHIC · BASE.
    """
    key, dom = _vworld(key_kind)
    lon, lat = fr["center"]
    w, h = fr["size"]
    return _call("image", {
        "service": "image", "request": "getmap", "key": key, "domain": dom,
        "format": fmt, "basemap": basemap, "crs": "EPSG:4326",
        "center": f"{lon},{lat}", "zoom": str(fr["zoom"]), "size": f"{w},{h}"},
        raw=True, timeout=90, what=f"위성 영상({basemap}·{fmt}·{w}x{h})")


def wmts_url(layer: str = "Satellite", key_kind: str = "vworld") -> str:
    """**브라우저가 직접 받는** 위성 타일 URL 틀(WMTS). layer = Satellite(jpeg) · Hybrid(png).

    ④ 지도에서 찍기는 타일을 **서버가 아니라 브라우저**가 받는다 — 그래서 ②작도판이 502로 막혀도
    지도는 뜬다(#56·#57). ⚠ 클라이언트 지도는 키가 **브라우저에 노출된다**:
    도메인 제한이 걸린 키만 여기에 쓴다(불변 원칙 4 — 저장소·문서에는 여전히 안 쓴다).
    """
    key, _ = _vworld(key_kind)
    ext = "png" if layer.lower() == "hybrid" else "jpeg"
    return f"{VWORLD_BASE}/wmts/1.0.0/{key}/{layer}/{{z}}/{{y}}/{{x}}.{ext}"


def net_check(timeout: float = 8.0) -> List[Dict]:
    """**전송 계층 점검** — 「키·파라미터 문제」와 「아예 못 닿는다」를 가른다.

    ⓐ DNS ⓑ TCP 443 연결 ⓒ **가짜 키로 실호출**(닿기만 하면 `INVALID_KEY` 가 온다)
    ⓓ 대조군(다른 호스트)으로 **바깥이 되긴 하는가**.
    🔴 ⓒ 는 일부러 **가짜 키**를 쓴다 — 진짜 키는 이 점검에 넣지 않는다(불변 원칙 4).
    """
    import socket
    out: List[Dict] = []
    host = urllib.parse.urlparse(VWORLD_BASE).hostname or "api.vworld.kr"

    t = time.time()
    try:
        infos = socket.getaddrinfo(host, 443, 0, socket.SOCK_STREAM)
        ips = sorted({i[4][0] for i in infos})
        out.append({"step": "ⓐ DNS " + host, "ok": True,
                    "ms": int((time.time() - t) * 1000), "detail": ", ".join(ips)})
    except Exception as e:
        out.append({"step": "ⓐ DNS " + host, "ok": False,
                    "ms": int((time.time() - t) * 1000), "detail": f"{type(e).__name__}: {e}"})
        return out

    t = time.time()
    try:
        socket.create_connection((host, 443), timeout=timeout).close()
        out.append({"step": "ⓑ TCP 443 연결", "ok": True,
                    "ms": int((time.time() - t) * 1000), "detail": "열린다"})
    except Exception as e:
        out.append({"step": "ⓑ TCP 443 연결", "ok": False,
                    "ms": int((time.time() - t) * 1000), "detail": f"{type(e).__name__}: {e}"})

    t = time.time()
    try:
        # 가짜 키 — 닿기만 하면 브이월드가 INVALID_KEY 를 준다. 그러면 망은 문제가 아니다.
        _call("search", {"service": "search", "request": "search", "version": "2.0",
                         "crs": "EPSG:4326", "size": "1", "page": "1", "query": "서울",
                         "type": "address", "format": "json", "errorformat": "json",
                         "key": "NOTAREALKEY000000000"}, what="가짜 키 도달 시험", retries=0)
        out.append({"step": "ⓒ 가짜 키 실호출", "ok": True,
                    "ms": int((time.time() - t) * 1000),
                    "detail": "응답이 왔다(예상 밖 — 가짜 키가 통과했다)"})
    except Exception as e:
        msg = str(e)
        reached = "INVALID_KEY" in msg or "인증키" in msg or "브이월드 오류" in msg
        out.append({"step": "ⓒ 가짜 키 실호출", "ok": reached,
                    "ms": int((time.time() - t) * 1000),
                    "detail": ("✅ 서버까지 닿는다(INVALID_KEY) — 망은 문제가 아니다"
                               if reached else msg)})

    t = time.time()
    try:
        # 🔴 배경 위성의 정본이 여기로 옮겨졌다(#59) — 이게 되면 작도판은 나온다.
        _g = tile_grid(frame((127.0, 36.5), zoom=13, size=(256, 256)))
        _u = (ESRI_TILES.replace("{z}", str(_g["zoom"]))
              .replace("{x}", str(_g["x0"])).replace("{y}", str(_g["y0"])))
        _r = urllib.request.urlopen(urllib.request.Request(_u, headers=dict(HTTP_HEADERS)),
                                    timeout=timeout, context=ssl.create_default_context())
        _b = _r.read()
        out.append({"step": "ⓔ Esri 위성 타일", "ok": len(_b) > 500,
                    "ms": int((time.time() - t) * 1000),
                    "detail": "%s bytes — 작도판 배경은 여기서 온다" % format(len(_b), ",")})
    except Exception as e:
        out.append({"step": "ⓔ Esri 위성 타일", "ok": False,
                    "ms": int((time.time() - t) * 1000),
                    "detail": f"{type(e).__name__}: {e} — 배경도 막혔다"})

    t = time.time()
    try:
        socket.create_connection(CONTROL_HOST, timeout=timeout).close()
        out.append({"step": "ⓓ 대조군 %s:%d" % CONTROL_HOST, "ok": True,
                    "ms": int((time.time() - t) * 1000), "detail": "바깥으로 나간다"})
    except Exception as e:
        out.append({"step": "ⓓ 대조군 %s:%d" % CONTROL_HOST, "ok": False,
                    "ms": int((time.time() - t) * 1000),
                    "detail": f"{type(e).__name__}: {e} — 바깥 자체가 막혔다"})
    return out


def probe(query: str = "논산시 상월면 상도리 482-42", key_kind: str = "vworld") -> List[Dict]:
    """**지도 연결 점검** — 네 호출을 따로따로 찔러 어디가 죽는지 말한다.

    작도판은 지번 검색 → 필지 → 주변 필지 → 위성 영상을 **차례로** 부른다.
    한 줄짜리 「HTTP Error 502」로는 어느 자리인지 알 수 없어서 만든 진단이다(2026-09-07 배포 사고).
    반환 = [{step, ok, ms, detail}] — **키는 절대 싣지 않는다**(불변 원칙 4).
    """
    out: List[Dict] = list(net_check())

    def run(step, fn):
        t = time.time()
        try:
            d = fn()
            out.append({"step": step, "ok": True,
                        "ms": int((time.time() - t) * 1000), "detail": d})
            return True
        except Exception as e:
            out.append({"step": step, "ok": False, "ms": int((time.time() - t) * 1000),
                        "detail": f"{type(e).__name__}: {e}"})
            return False

    hits: List[Dict] = []

    def _geo():
        hits.extend(geocode(query, key_kind=key_kind))
        if not hits:
            raise LookupError("검색 결과 없음")
        return f"{hits[0]['pnu']} · {hits[0]['address']}"

    if not run("① 지번 검색 (search)", _geo):
        return out          # 첫 호출이 죽으면 뒤는 볼 것도 없다 — ⓐ~ⓓ 가 자리를 짚어 준다
    par: List[Dict] = []

    def _par():
        q = parcel(pnu=hits[0]["pnu"], key_kind=key_kind)
        if q is None:
            raise LookupError("필지 폴리곤 없음")
        par.append(q)
        return f"{q['jibun']} · 지적 {round(q['area_m2']):,} ㎡"

    if not run("② 필지 폴리곤 (data)", _par):
        return out
    c = par[0]["center"]
    run("③ 주변 필지 (data · 참고선)",
        lambda: f"{len(parcels_in_box(c, radius_m=150.0, key_kind=key_kind))} 필지")
    fr = frame(c, zoom=18, size=(1024, 1024))
    run("④ 위성 영상 (image · JPEG)",
        lambda: f"{len(print_tile(fr, basemap='PHOTO_HYBRID', fmt='jpeg')):,} bytes")
    run("⑤ 위성 영상 (image · PNG · 무거움)",
        lambda: f"{len(print_tile(fr, basemap='PHOTO_HYBRID', fmt='png')):,} bytes")
    return out


def tile_mosaic(fr: Dict, url_tmpl: str = ESRI_TILES, timeout: int = 20,
                quality: int = 88) -> bytes:
    """XYZ 타일을 **프레임 그대로** 이어 붙인 배경(JPEG bytes).

    브이월드 정지영상(`print_tile`)이 막혔을 때의 길이다 — 타일 서버는 국경이 없다.
    2026-09-07 실측(상도리 482-42 · zoom 18 · 1024²) = **25장 · 0.39 MB · 7.7 초**,
    브이월드와 **정렬 일치**(같은 웹 메르카토르 규약).
    """
    from PIL import Image
    import io as _io
    g = tile_grid(fr)
    w, h = fr["size"]
    im = Image.new("RGB", (w, h), (24, 24, 24))
    got = 0
    ctx = ssl.create_default_context()
    for X in range(g["x0"], g["x1"] + 1):
        for Y in range(g["y0"], g["y1"] + 1):
            url = url_tmpl.replace("{z}", str(g["zoom"])).replace("{x}", str(X)).replace("{y}", str(Y))
            req = urllib.request.Request(url, headers=dict(HTTP_HEADERS))
            try:
                with urllib.request.urlopen(req, timeout=timeout, context=ctx) as r:
                    body = r.read()
                im.paste(Image.open(_io.BytesIO(body)).convert("RGB"),
                         (int(round((X - g["x0"]) * TILE_PX + g["ox"])),
                          int(round((Y - g["y0"]) * TILE_PX + g["oy"]))))
                got += 1
            except Exception:
                continue                     # 한 장이 비어도 판은 나온다
    if got == 0:
        raise RuntimeError("타일 배경 실패 — %d장 중 한 장도 못 받았다" % g["n"])
    buf = _io.BytesIO()
    im.save(buf, "JPEG", quality=quality)
    return buf.getvalue()


def basemap_image(fr: Dict, prefer: str = "auto", basemap: str = "PHOTO_HYBRID") -> Tuple[bytes, str]:
    """작도판 배경 1장 + **무엇으로 받았는지**. prefer = auto · vworld · esri.

    `auto` = 브이월드를 먼저 부르고, 막히면 **말없이 포기하지 않고** Esri 로 간다.
    어느 쪽을 썼는지 반환값에 실어 판·기록에 그대로 적는다(무엇을 보고 확인받았는지가 남아야 한다).
    """
    if prefer != "esri":
        try:
            return print_tile(fr, basemap=basemap, fmt="jpeg"), "vworld"
        except Exception:
            if prefer == "vworld":
                raise
    return tile_mosaic(fr), "esri"


def geocode_osm(query: str, limit: int = 3, timeout: int = 20) -> List[Dict]:
    """**보조** 지오코더(OSM Nominatim). 브이월드가 막힌 자리를 메운다.

    🔴 지번을 못 찾는다 — 2026-09-07 실측: 「상도리 482-42」·「상월면 상도리」 **결과 없음**,
      「논산시 상월면」만 나온다(36.2926, 127.1628 · 실제 밭에서 **약 3 km**).
      그래서 이것은 **출발점**일 뿐이고, 대상지는 지도에서 눈으로 찾아 그린다(#59).
    """
    q = urllib.parse.urlencode({"q": query, "format": "json",
                                "limit": str(limit), "countrycodes": "kr"})
    req = urllib.request.Request(OSM_GEOCODE + "?" + q,
                                 headers=dict(HTTP_HEADERS, **{"Accept-Language": "ko"}))
    with urllib.request.urlopen(req, timeout=timeout, context=ssl.create_default_context()) as r:
        j = json.loads(r.read().decode("utf-8", "replace"))
    return [{"address": x.get("display_name", ""),
             "center": [float(x["lon"]), float(x["lat"])],
             "kind": x.get("type", "")} for x in (j or [])]


def elevation(points=None):
    """고도·낙차 — **어댑터가 답하지 않는다. 소비자가 알려준다**(대표 확답 2026-09-05).

    「낙차는 농민 또는 관급 등 소비자들이 알려줘. 파크골프장이나 건설현장은 왠만하면 실측을 나가려고해.」

    그래서 DEM 소싱은 **트랙에서 뺀다**. 낙차는 인터뷰 문진표의 입력 항목이고,
    파크골프장·건설현장처럼 값이 설계를 좌우하는 현장은 **실측**이 정본이다.
    (참고 — 브이월드에는 쓸 수 있는 DEM 경로가 없다: LT_C_DEM · wcs · req/dem 모두 실패, 2026-09-05.)
    """
    raise NotImplementedError(
        "낙차는 지도에서 뽑지 않는다 — 소비자 고지 또는 실측 입력이다(대표 확답 2026-09-05). "
        "site 입력의 낙차 항목에 넣는다.")


def blocks_from_pixels(fr, drawn, u=None, crop=None):
    """**우리가 또는 농민이 위성 그림 위에 표시한 대상지** → `site.blocks` 폴리곤(로컬 미터).

    `drawn` = {블록 이름: [[x_px, y_px], ...]} — `fr` 프레임으로 받은 위성 영상 위의 화소 좌표.
    `u`(열 방향)는 대표 판단이라 **어댑터가 만들지 않는다.** 주면 얹고, 없으면 자리를 비운 채 낸다.
    `crop`(작물)은 처음에 물어보고 **알면 넣는다** — 지역·작물별 데이터 축적용(대표 지시 2026-09-05).

    🔴 지적 필지와 맞출 필요가 없다 — 대상지는 여러 필지에 걸치거나 필지 일부만 쓴다.
    """
    out = []
    for name, pts in drawn.items():
        if len(pts) < 3:
            raise ValueError(f"블록 '{name}': 점이 3개 미만이다 — 폴리곤이 아니다")
        ring = [to_lonlat(fr, float(x), float(y)) for x, y in pts]
        b = {"name": name, "polygon": to_local_m(ring, fr["origin"]),
             "area_m2": round(ring_area_m2(ring, fr["origin"]), 1),
             "source": {"kind": "drawn_on_satellite", "frame": fr.get("center"),
                        "zoom": fr.get("zoom"), "n_px": len(pts)}}
        if u and name in u:
            b["u"] = list(u[name])
        if crop and crop.get(name):
            b["crop"] = crop[name]
        out.append(b)
    return out


# ────────────────── 작도판 — 우리가 먼저 그려서 확인받는다 ──────────────────
#
# 대표 지시(2026-09-05): 「채팅이나 통화로 일단 주소를 먼저 받아서 통화의 내용을 바탕으로
#   **우리가 선재적으로 그려줄 수도 있어.** 위성지도를 어떻게 캡쳐하는지, 아니면 받은 이미지파일에
#   어떻게 표기해야하는지 **어려워하는 농민들이 대다수**야.」
# 그래서 이 판의 목적은 농민이 그리게 하는 것이 아니라, **우리가 그린 것을 농민이 보고 확인하는 것**이다.

_FONT_CACHE = {}


def _font(size):
    """나눔고딕(저장소 동봉). 없으면 기본 글꼴 — 한글이 깨져도 그림 자체는 나온다."""
    if size not in _FONT_CACHE:
        from PIL import ImageFont
        f = None
        for name in ("NanumGothic.ttf", "NanumGothic-Bold.ttf"):
            try:
                f = ImageFont.truetype(name, size)
                break
            except OSError:
                continue
        _FONT_CACHE[size] = f or ImageFont.load_default()
    return _FONT_CACHE[size]


# 🔴 NanumGothic 에 **㎡(U+33A1)·㎥ 글리프가 없다** — 그리면 **빈칸으로 찍힌다**(2026-09-07 실측:
#    getmask("㎡").getbbox() is None). 작도판이 처음부터 면적 단위 없이 나가고 있었다.
#    화면(브라우저 글꼴)에서는 멀쩡해서 눈에 안 띄었다. **그리는 자리에서만** 바꿔 끼운다.
_GLYPH_FIX = {"㎡": "m²", "㎥": "m³", "㎝": "cm²"}


def _safe(text):
    for k, v in _GLYPH_FIX.items():
        text = text.replace(k, v)
    return text


def _hit(a, b):
    return not (a[2] <= b[0] or b[2] <= a[0] or a[3] <= b[1] or b[3] <= a[1])


def _label(d, xy, text, size, fill, bg, center=False, used=None):
    """이름표 하나. `used` 를 주면 **이미 놓인 이름표를 피해** 위아래로 비켜 앉는다.

    🔴 2026-09-07 실측: 밭 이름표와 급수점·주배관 이름표가 겹쳐 「6 급수 지점 1,963 평)」처럼
      읽을 수 없는 판이 나왔다. **농민이 보고 확인하는 그림**이라 겹침은 결함이다.
    """
    f = _font(size)
    text = _safe(text)
    x, y = xy
    box = d.multiline_textbbox((0, 0), text, font=f)
    w, h = box[2] - box[0], box[3] - box[1]
    if center:
        x, y = x - w / 2, y - h / 2
    if used is not None:
        step = h + 12
        for k in range(0, 10):
            for dy in ((0.0,) if k == 0 else (k * step, -k * step)):
                if not any(_hit((x - 6, y - 5 + dy, x + w + 6, y + h + 7 + dy), u) for u in used):
                    y += dy
                    k = -1
                    break
            if k == -1:
                break
        used.append((x - 6, y - 5, x + w + 6, y + h + 7))
    d.rectangle([x - 6, y - 5, x + w + 6, y + h + 7], fill=bg)
    d.multiline_text((x - box[0], y - box[1]), text, font=f, fill=fill, align="center")
    return (x - 6, y - 5, x + w + 6, y + h + 7)


def _scale_bar(d, fr, W, H):
    """축척 막대 — 「이 밭이 몇 미터인지」를 농민이 눈으로 재게 한다."""
    mpp = fr["m_per_px"]
    m = 20
    for cand in (200, 100, 50, 20):
        if cand / mpp <= W * 0.34:
            m = cand
            break
    px = m / mpp
    x0, y0 = 20, H - 34
    d.rectangle([x0 - 8, y0 - 28, x0 + px + 8, y0 + 12], fill=(0, 0, 0, 165))
    d.line([(x0, y0), (x0 + px, y0)], fill=(255, 255, 255), width=4)
    for x in (x0, x0 + px):
        d.line([(x, y0 - 8), (x, y0 + 8)], fill=(255, 255, 255), width=4)
    d.text((x0, y0 - 26), "%d m" % m, font=_font(17), fill=(255, 255, 255))


def _north(d, W):
    x, y = W - 44, 30
    d.rectangle([x - 22, y - 22, x + 22, y + 44], fill=(0, 0, 0, 165))
    d.polygon([(x, y - 15), (x - 10, y + 13), (x, y + 6), (x + 10, y + 13)], fill=(255, 255, 255))
    d.text((x - 6, y + 16), "N", font=_font(17), fill=(255, 255, 255))


def draft_sheet(fr, parcels=None, blocks_px=None, basemap="PHOTO_HYBRID", title="",
                fmt="jpeg", basemap_bytes=None, blocks_m=None, sources_m=None,
                routes_m=None, note=""):
    """농민 확인용 작도판 PNG — 위성 + (지적 참고선) + 우리가 그린 대상지·급수원·주배관 + 축척 + 방위.

    `blocks_px` = {이름: [[x_px, y_px], ...]} · `blocks_m` = [{name, polygon(미터), crop?}]
    `sources_m` = [{name, pt}] · `routes_m` = [{name, pts, zone?}] — **④ 지도에서 그린 그대로**.
    `basemap_bytes` 를 주면 그 배경을 쓴다(브이월드가 막히면 Esri 모자이크 · `basemap_image`).
    지번을 크게 적는 이유 = 농민이 「우리 밭 211-1」이라고 짚을 수 있어야 하기 때문이다.
    """
    import io as _io
    from PIL import Image, ImageDraw
    # 바탕은 **JPEG 로 받는다** — 같은 장면이 PNG 2.27 MB vs JPEG 0.18 MB(2026-09-07 실측 · 12.8배).
    # 판은 어차피 PNG 로 다시 내므로 최종 산출물은 그대로이고, **해외 서버에서 끊길 확률만 줄어든다**(#56).
    if basemap_bytes is None:
        basemap_bytes = print_tile(fr, basemap=basemap, fmt=fmt)
    im = Image.open(_io.BytesIO(basemap_bytes)).convert("RGB")
    d = ImageDraw.Draw(im, "RGBA")
    W, H = im.size
    # 고정 자리(제목 · 방위 · 축척·각주)를 먼저 막아 둔다 — 이름표가 그 위로 오지 않게.
    used = [(0, 0, 560, 46), (W - 76, 0, W, 76), (0, H - 76, 320, H)]

    # 지적 참고선 — 경계일 뿐 대상지가 아니다. 그래서 얇고 흐리게.
    for pc in (parcels or []):
        pts = [to_px(fr, *q) for q in pc["rings"][0]]
        if max(x for x, _ in pts) < 0 or min(x for x, _ in pts) > W:
            continue
        d.line(pts + [pts[0]], fill=(120, 200, 255, 190), width=2)
        cx = sum(x for x, _ in pts) / len(pts)
        cy = sum(y for _, y in pts) / len(pts)
        if 30 <= cx <= W - 30 and 30 <= cy <= H - 30:
            _label(d, (cx, cy), str(pc.get("jibun") or ""), 16,
                   (235, 245, 255), (0, 0, 0, 130), center=True, used=used)

    # 우리가 그린 대상지 — 굵고 선명하게, 면적을 함께 적는다.
    # 미터로 그린 것(④ 지도에서 그리기)도 여기서 화소로 합류한다 — 그리는 코드는 하나다.
    _px = dict(blocks_px or {})
    for _b in (blocks_m or []):
        _ll = from_local_m(_b.get("polygon") or [], fr["origin"])
        if len(_ll) >= 3:
            _nm = str(_b.get("name") or "대상지")
            if _b.get("crop"):
                _nm += " · " + str(_b["crop"])
            _px[_nm] = [list(to_px(fr, q[0], q[1])) for q in _ll]
    blocks_px = _px
    palette = [(255, 214, 0), (196, 110, 255), (255, 122, 90), (90, 230, 160)]
    for k, (name, pts) in enumerate((blocks_px or {}).items()):
        col = palette[k % len(palette)]
        pp = [(float(x), float(y)) for x, y in pts]
        d.polygon(pp, fill=col + (46,))
        d.line(pp + [pp[0]], fill=col + (255,), width=5)
        area = ring_area_m2([to_lonlat(fr, x, y) for x, y in pp], fr["origin"])
        cx = sum(x for x, _ in pp) / len(pp)
        cy = sum(y for _, y in pp) / len(pp)
        _label(d, (cx, cy), "%s\n%s ㎡ (%s 평)" % (name, format(round(area), ","),
                                                   format(round(area / 3.3058), ",")),
               20, col, (0, 0, 0, 175), center=True, used=used)

    # 주배관 — 굵은 붉은 선. 그린 순서를 알 수 있게 이름을 얹는다.
    for _rt in (routes_m or []):
        _ll = from_local_m(_rt.get("pts") or [], fr["origin"])
        if len(_ll) < 2:
            continue
        _pp = [to_px(fr, q[0], q[1]) for q in _ll]
        d.line(_pp, fill=(255, 75, 75, 255), width=6, joint="curve")
        # 이름은 **1/4 지점 위쪽**에 둔다 — 한가운데 두면 밭 이름표와 겹친다(2026-09-07 실측).
        _at = _pp[max(1, len(_pp) // 4)] if len(_pp) > 2 else (
            ((_pp[0][0] + _pp[1][0]) / 2, (_pp[0][1] + _pp[1][1]) / 2))
        _label(d, (_at[0], _at[1] - 20), str(_rt.get("name") or "주배관"), 16,
               (255, 220, 220), (0, 0, 0, 175), center=True, used=used)

    # 급수원·급수 지점 — 농민이 「저기 물탱크」라고 짚는 자리다. 가장 눈에 띄어야 한다.
    for _sc in (sources_m or []):
        _lo, _la = from_local_m([_sc["pt"]], fr["origin"])[0]
        _x, _y = to_px(fr, _lo, _la)
        d.ellipse([_x - 13, _y - 13, _x + 13, _y + 13], fill=(0, 0, 0, 150),
                  outline=(120, 220, 255, 255), width=4)
        d.ellipse([_x - 4, _y - 4, _x + 4, _y + 4], fill=(120, 220, 255, 255))
        _label(d, (_x, _y - 30), str(_sc.get("name") or "급수점"), 19,
               (170, 235, 255), (0, 0, 0, 180), center=True, used=used)

    _scale_bar(d, fr, W, H)
    _north(d, W)
    if title:
        _label(d, (16, 14), title, 21, (255, 255, 255), (0, 0, 0, 175))
    if note:
        _label(d, (16, H - 34), note, 15, (215, 215, 215), (0, 0, 0, 150))

    buf = _io.BytesIO()
    im.save(buf, "PNG")
    return buf.getvalue()


def draft_from_address(query, zoom=18, size=1024, radius_m=150.0, blocks_px=None):
    """**주소 한 줄 → 작도판.** 통화로 주소를 받은 다음 이 한 번으로 판이 나온다.

    반환 = {frame, parcel, parcels, png, seed}. `png` 를 농민에게 보내 확인받고,
    확인되면 그 위에 그린 화소를 `blocks_from_pixels(frame, ...)` 로 넘긴다.
    """
    seed = site_seed(query, zoom=zoom, size=size, radius_m=radius_m)
    fr = frame(seed["map"]["frame"]["center"], zoom, (size, size))
    main = seed["reference_parcels"][0]
    try:
        near = parcels_in_box(fr["center"], radius_m=radius_m)
    except Exception:
        near = []                      # 참고선 없이 위성만으로도 판은 쓸 수 있다(#56)
    bg, src = basemap_image(fr)        # 브이월드가 막히면 Esri 로 간다(#59)
    png = draft_sheet(fr, parcels=near, blocks_px=blocks_px, basemap_bytes=bg,
                      title="%s  ·  확인 부탁드립니다" % main["address"],
                      note="배경 = %s" % ("브이월드 위성" if src == "vworld" else ESRI_ATTR))
    return {"frame": fr, "parcel": main, "parcels": near, "png": png, "seed": seed,
            "basemap": src}


def draft_from_center(center, zoom=18, size=1024, blocks_m=None, sources_m=None,
                      routes_m=None, title="", prefer="auto", parcels=None):
    """**좌표 한 쌍 → 작도판.** 지번이 없어도, 브이월드가 막혀도 판이 나온다(#59).

    대표 확답 2026-09-07 — 「농민들은 **대표지번이나 일부지번**을 알려주고 통화·미팅으로 대상지를
    알려주는 경우가 대부분이다. **지번으로 특정하기 애매한 경우가 많다.**」
    그래서 입구가 지번이 아니라 **지도**다. 여기 오는 것은 이미 지도에서 그린 결과다.
    """
    fr = frame(center, zoom=zoom, size=(size, size))
    png_bg, src = basemap_image(fr, prefer=prefer)
    note = ("배경 = %s · 축척 %.2f m/화소"
            % ("브이월드 위성" if src == "vworld" else ESRI_ATTR, fr["m_per_px"]))
    png = draft_sheet(fr, parcels=parcels, basemap_bytes=png_bg, blocks_m=blocks_m,
                      sources_m=sources_m, routes_m=routes_m,
                      title=title or "확인 부탁드립니다", note=note)
    return {"frame": fr, "png": png, "basemap": src, "note": note}


# ────────────────────────────── CLI ──────────────────────────────

def site_seed(query: str, zoom: int = 18, size: int = 1024,
              radius_m: float = 150.0) -> Dict:
    """지번 → 「설계 착수 씨앗」. 대표가 위성 위에 블록을 그릴 판을 깔아 준다.

    🔴 blocks 는 **비워서** 낸다 — 경작 구역은 대표 판단이고 지적 경계가 대신할 수 없다.
       (site.validate 는 blocks 가 비면 거부한다. 그것이 맞는 동작이다.)
    """
    hits = geocode(query)
    if not hits:
        raise LookupError(f"지번을 찾지 못했다: {query} — 읍·면을 추측해 붙이지 않는다")
    hit = hits[0]
    par = parcel(pnu=hit["pnu"])
    if par is None:
        raise LookupError(f"필지 폴리곤 없음: {hit['pnu']}")
    fr = frame(par["center"], zoom=zoom, size=(size, size))
    # 🔴 **주변 필지는 참고선일 뿐이다** — 못 받아도 판은 나와야 한다(#56).
    #    이것 하나가 죽어서 작도판 전체가 못 나오는 것은 과하다.
    try:
        near = parcels_in_box(par["center"], radius_m=radius_m)
    except Exception:
        near = [par]
    if not any(p["pnu"] == par["pnu"] for p in near):
        near = [par] + near
    return {
        "schema": "looperget.design.site/1", "name": par["address"],
        "map": {"frame": {k: v for k, v in fr.items() if not k.startswith("_")},
                "query": query, "provider": "vworld",
                "m_per_px": round(fr["m_per_px"], 4)},
        "reference_parcels": [
            {"pnu": p["pnu"], "address": p["address"], "jibun": p["jibun"],
             "area_m2": p["area_m2"], "outline_m": to_local_m(p["rings"][0], fr["origin"]),
             "outline_px": [[round(x, 1), round(y, 1)]
                            for x, y in (to_px(fr, *q) for q in p["rings"][0][:-1])]}
            for p in sorted(near, key=lambda q: q["pnu"] != par["pnu"])],
        "blocks": [], "routes": [], "sources": [],
        "_note": "blocks·routes·sources 는 대표 입력이다(불변 원칙 1 · site.py). "
                 "reference_parcels 는 지적 경계일 뿐 경작 구역이 아니다.",
    }


def _main(argv: List[str]) -> int:
    import argparse
    ap = argparse.ArgumentParser(
        prog="python -m looperget.design.mapsrc",
        description="지번 → 필지 폴리곤·위성 프레임(P3 지도 어댑터). 설계 블록은 만들지 않는다.")
    ap.add_argument("query", help='지번 주소. 예: "논산시 숙진리 211-1" (읍·면은 추측해 붙이지 않는다)')
    ap.add_argument("--zoom", type=int, default=18, help=f"{ZOOM_RANGE[0]}~{ZOOM_RANGE[1]} (기본 18 = 최고 해상도)")
    ap.add_argument("--size", type=int, default=1024, help=f"한 변 화소, 최대 {SIZE_MAX}")
    ap.add_argument("--radius", type=float, default=150.0, help="주변 참고 필지 반경 m")
    ap.add_argument("--out", default=None, help="출력 폴더(주면 site 씨앗 json + 위성 png 를 쓴다)")
    ap.add_argument("--basemap", default="PHOTO_HYBRID", help="PHOTO · PHOTO_HYBRID · GRAPHIC · BASE")
    ap.add_argument("--sheet", action="store_true",
                    help="농민 확인용 작도판(위성 + 지적 참고선 + 지번 + 축척 + 방위)까지 만든다")
    a = ap.parse_args(argv)

    seed = site_seed(a.query, zoom=a.zoom, size=a.size, radius_m=a.radius)
    fr = seed["map"]["frame"]
    main_p = seed["reference_parcels"][0]
    print(f"지번   {a.query}")
    print(f"필지   {main_p['address']} ({main_p['jibun']}) · PNU {main_p['pnu']}")
    print(f"지적   {main_p['area_m2']:,.0f} ㎡ ({main_p['area_m2']/3.3058:,.0f} 평) · 점 {len(main_p['outline_m'])}개")
    print(f"프레임 zoom {fr['zoom']} · {fr['size'][0]}×{fr['size'][1]} px · "
          f"{seed['map']['m_per_px']} m/px · {fr['span_m'][0]:.0f}×{fr['span_m'][1]:.0f} m")
    print(f"참고   반경 {a.radius:.0f} m 안 필지 {len(seed['reference_parcels'])}개")
    print("🔴 blocks 는 비어 있다 — 경작 구역은 대표가 위성 위에서 확정한다(지적 경계 ≠ 설계 블록).")

    if a.out:
        out = Path(a.out)
        out.mkdir(parents=True, exist_ok=True)
        stem = (main_p["pnu"] or "site")
        (out / f"{stem}_site_seed.json").write_text(
            json.dumps(seed, ensure_ascii=False, indent=1), encoding="utf-8")
        f2 = frame(fr["center"], fr["zoom"], fr["size"])
        png = print_tile(f2, basemap=a.basemap)
        (out / f"{stem}_{a.basemap}.png").write_bytes(png)
        if a.sheet:
            near = parcels_in_box(f2["center"], radius_m=a.radius)
            sheet = draft_sheet(f2, parcels=near, basemap=a.basemap,
                                title="%s  ·  확인 부탁드립니다" % main_p["address"])
            (out / f"{stem}_작도판.png").write_bytes(sheet)
            print("     → %s (%s bytes) · 농민 확인용"
                  % (out / (stem + "_작도판.png"), format(len(sheet), ",")))
        print("")
        print(f"저장 → {out / (stem + '_site_seed.json')}")
        print(f"     → {out / (stem + '_' + a.basemap + '.png')} ({len(png):,} bytes)")
    return 0


if __name__ == "__main__":
    import sys as _sys
    _sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(_main(_sys.argv[1:]))


__all__ = ["VERSION", "SCHEMA", "ZOOM_RANGE", "SIZE_MAX",
           "webmercator", "inv_webmercator", "zoom_resolution",
           "frame", "to_px", "to_lonlat", "to_local_m", "ring_area_m2",
           "geocode", "parcel", "parcels_in_box", "print_tile", "elevation", "site_seed",
           "blocks_from_pixels", "draft_sheet", "draft_from_address"]

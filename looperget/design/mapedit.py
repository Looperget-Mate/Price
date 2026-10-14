# -*- coding: utf-8 -*-
"""지도 조작의 순수 계산과 Leaflet ↔ Streamlit 전달. 외부 저장소 접근 없음."""
from copy import deepcopy
import hashlib
import json
import math

from . import geom as G, mapsrc, site
from .layout import DROP_TOL, RowPolicy, rows_from_polygon

HANDLE = "looperget_lateral"
HEAD = "looperget_head"          # 스프링클러 빼기·되살리기 표식(대표 요청 2026-09-08)
HEAD_ADD = "looperget_head_add"  # 스프링클러 더 놓기 — 지도의 빈 자리를 누른 것


def drawing_snapshot(result, saved=None):
    """iframe 초기 응답(None)은 저장 도형을 사용; 명시적인 []는 전부 지운 결과다."""
    incoming = (result or {}).get("all_drawings")
    features = saved if incoming is None else incoming
    return deepcopy([f for f in (features or [])
                     if (f.get("properties") or {}).get("kind") not in (HANDLE, HEAD, HEAD_ADD)])


def map_policy(policy=None):
    """신규 현장 지도: 표시한 첫 여백을 주배관 교점부터 적용. 승인본 엔진 기본값은 유지."""
    out = {"S": 14.0, "lat_gap": 14.0, "std": 7.0, "maxm": 8.0}
    out.update(policy or {})
    out.update(off_fixed=float(out["std"]), start_ref="main")
    out["maxm"] = max(float(out["maxm"]), float(out["std"]) + 1.0)
    return out


def revision(blocks, routes):
    return hashlib.sha256(json.dumps([blocks, routes], sort_keys=True,
                                    ensure_ascii=False).encode("utf-8")).hexdigest()[:20]


def design_blocks(blocks):
    """설계 전달 시 간격·수동 열·두둑을 빠뜨리지 않고 독립된 복사본으로 넘긴다."""
    keys = ("name", "polygon", "u", "policy", "bars", "crop")
    return [deepcopy({k: b[k] for k in keys if k in b}) for b in blocks]


def handles(preview, origin, rev):
    out = []
    for block in preview.get("blocks", []):
        for i, row in enumerate(block.get("row_details", [])):
            xy = [(a + b) / 2 for a, b in zip(row["p0"], row["p1"])]
            lon, lat = mapsrc.from_local_m([xy], origin)[0]
            out.append({"type": "Feature", "geometry": {"type": "Point", "coordinates": [lon, lat]},
                        "properties": {"kind": HANDLE, "revision": rev,
                                       "block_index": block["block_index"], "row_index": i,
                                       "xy": xy}})
    return out


def head_marks(preview, origin, rev):
    """지도에서 누를 수 있는 스프링클러 표식. 놓인 헤드는 `drop`, 뺀 자리는 `restore`."""
    out = []
    for block in preview.get("blocks", []):
        if "block_index" not in block:
            continue
        for action, pts in (("drop", block.get("head_pts") or []),
                            ("restore", block.get("drop_pts") or [])):
            for xy in pts:
                lon, lat = mapsrc.from_local_m([xy], origin)[0]
                out.append({"type": "Feature",
                            "geometry": {"type": "Point", "coordinates": [lon, lat]},
                            "properties": {"kind": HEAD, "revision": rev, "action": action,
                                           "block_index": block["block_index"],
                                           "xy": [round(float(xy[0]), 1), round(float(xy[1]), 1)]}})
    return out


def _rows_of(block, mains):
    """그 밭의 가지관(엔진 그대로). 화면과 설계가 다른 열을 보면 안 된다."""
    return rows_from_polygon(block["polygon"], tuple(block.get("u") or (1, 0)),
                             RowPolicy(**map_policy(block.get("policy"))),
                             bars=block.get("bars"), mains=mains)


def add_head(blocks, routes, features, origin, rev):
    """지도의 빈 자리를 누르면 **가장 가까운 가지관에 스프링클러를 하나 더** 놓는다.

    🔴 어디에 붙일지는 **엔진이 정한다**(`layout.Block.add` 가 열 축에 투영한다) — 여기서는
      누른 자리를 그 밭의 `policy.add_heads` 에 넣고 **두수가 실제로 늘었는지** 다시 돌려서 본다.
      늘지 않으면 놓을 수 없는 자리다 — 조용히 삼키지 않고 이유를 돌려준다.
    """
    out = deepcopy(blocks)
    mains = [r["pts"] for r in (routes or []) if site.route_role(r) == "main"]
    hit = False
    try:
        for feature in features:
            prop = feature.get("properties") or {}
            if prop.get("kind") != HEAD_ADD or prop.get("revision") != rev:
                continue
            xy = mapsrc.to_local_m([feature["geometry"]["coordinates"]], origin)[0]
            if not all(math.isfinite(v) for v in xy):
                raise ValueError("올바르지 않은 지도 좌표입니다")
            pick = None
            for bi, block in enumerate(out):
                if len(block.get("polygon") or []) < 3:
                    continue
                rows = _rows_of(block, mains)
                if not rows:
                    continue
                d = min(G.seg_dist(tuple(xy), r.p0, r.p1) for r in rows)
                if pick is None or d < pick[0]:
                    pick = (d, bi, sum(len(r.heads) for r in rows))
            if pick is None:
                raise ValueError("아직 가지관이 없습니다 — 밭과 주배관을 먼저 그려 주세요")
            _, bi, before = pick
            block = out[bi]
            policy = dict(block.get("policy") or {})
            adds = [[float(q[0]), float(q[1])] for q in (policy.get("add_heads") or [])]
            adds.append([round(xy[0], 1), round(xy[1], 1)])
            policy["add_heads"] = adds
            block["policy"] = policy
            if sum(len(r.heads) for r in _rows_of(block, mains)) <= before:
                raise ValueError("그 자리에는 놓을 수 없습니다 — **가지관 가까이·밭 안쪽**을 눌러 주세요"
                                 "(이미 헤드가 있는 자리이거나 경계에 너무 붙었습니다)")
            hit = True
    except (ValueError, TypeError, KeyError, IndexError, OverflowError) as exc:
        return None, str(exc)
    return (out, "") if hit else (None, "")


def toggle_heads(blocks, features, rev):
    """누른 스프링클러를 빼거나 되살린다. 바뀌면 복사본, 아니면 None + 안내.

    🔴 자리는 **표식이 들고 있던 로컬 좌표**를 쓴다 — 클릭 위경도를 되돌려 계산하면
      투영 오차가 붙어 옆 헤드를 빼는 일이 생긴다.
    """
    out = deepcopy(blocks)
    hit = False
    try:
        for feature in features:
            prop = feature.get("properties") or {}
            if prop.get("kind") != HEAD or prop.get("revision") != rev:
                continue
            xy = [float(v) for v in prop["xy"]]
            if not all(math.isfinite(v) for v in xy):
                raise ValueError("올바르지 않은 지도 좌표입니다")
            block = out[int(prop["block_index"])]
            policy = dict(block.get("policy") or {})
            drops = [[float(q[0]), float(q[1])] for q in (policy.get("drop_heads") or [])]
            near = [q for q in drops if math.dist(q, xy) <= DROP_TOL]
            if prop.get("action") == "restore":
                if not near:
                    continue
                drops = [q for q in drops if q not in near]
            else:
                if near:
                    continue                       # 이미 빠진 자리 — 두 번 넣지 않는다
                drops.append([round(xy[0], 1), round(xy[1], 1)])
            if drops:
                policy["drop_heads"] = drops
            else:
                policy.pop("drop_heads", None)
            block["policy"] = policy
            hit = True
    except (ValueError, TypeError, KeyError, IndexError, OverflowError) as exc:
        return None, str(exc)
    return (out, "") if hit else (None, "")


def move_rows(blocks, routes, preview, features, origin, rev):
    """옮긴 손잡이를 고랑 직각 방향으로 투영. 성공 시 복사본, 실패/무변경 시 None + 안내."""
    out = deepcopy(blocks)
    changes = {}
    details = {b["block_index"]: b.get("row_details", []) for b in preview.get("blocks", [])
               if "block_index" in b}
    try:
        for feature in features:
            prop = feature.get("properties") or {}
            if prop.get("kind") != HANDLE or prop.get("revision") != rev:
                continue
            bi, ri = int(prop["block_index"]), int(prop["row_index"])
            rows = details[bi]
            row = rows[ri]
            old_xy = [(a + b) / 2 for a, b in zip(row["p0"], row["p1"])]
            xy = mapsrc.to_local_m([feature["geometry"]["coordinates"]], origin)[0]
            n = G.perp(G.unit(tuple(out[bi].get("u") or (1, 0))))
            delta = G.dot(G.sub(xy, old_xy), n)
            if not math.isfinite(delta):
                raise ValueError("올바르지 않은 지도 좌표입니다")
            if abs(delta) < 0.2:
                continue
            specs = changes.setdefault(bi, [{"a": r["a"], "deg": r["deg"]} for r in rows])
            specs[ri]["a"] = row["a"] + delta
        mains = [r["pts"] for r in routes if site.route_role(r) == "main"]
        for bi, specs in changes.items():
            block = out[bi]
            policy = map_policy(block.get("policy"))
            policy["manual_rows"] = specs
            rows = rows_from_polygon(block["polygon"], tuple(block.get("u") or (1, 0)),
                                     RowPolicy(**policy), bars=block.get("bars"), mains=mains)
            moved = {i for i, spec in enumerate(specs) if abs(spec["a"] - details[bi][i]["a"]) >= 0.2}
            for i in moved:
                if any(i != j and G.seg_seg_dist(rows[i].p0, rows[i].p1, r.p0, r.p1)
                       < policy.get("min_sep", 6.0) - 0.1 for j, r in enumerate(rows)):
                    raise ValueError("이웃 가지관에 너무 가깝거나 교차합니다. 간격을 더 벌려 주세요.")
            block["policy"] = policy
    except (ValueError, TypeError, KeyError, IndexError, OverflowError) as exc:
        return None, str(exc)
    return (out, "") if changes else (None, "")


def merge_routes(existing, features, origin, default_role="main"):
    """재반영해도 사용자가 정한 역할·관경·구역을 보존. 신규 선만 추가한다."""
    out = deepcopy(existing)
    for f in features:
        pts = mapsrc.to_local_m(f["geometry"]["coordinates"], origin)
        prop = f.get("properties") or {}
        draw_id = prop.get("draw_id")
        match = next((r for r in out if (draw_id and r.get("draw_id") == draw_id)
                      or (len(r.get("pts", [])) == len(pts)
                          and all(math.dist(a, b) < 0.15 for a, b in zip(r["pts"], pts)))), None)
        if match is not None:
            match["pts"] = pts
            if draw_id:
                match["draw_id"] = draw_id
            continue
        role = prop.get("role", default_role)
        role = "feeder" if role == "feeder" else "main"
        num = 1
        ids = {r.get("id") for r in out}
        while "R%d" % num in ids:
            num += 1
        zone = max([int(r.get("zone") or 0) for r in out] or [0]) + 1
        out.append({"id": "R%d" % num, "name": "R%d" % num, "role": role,
                    "zone": None if role == "feeder" else zone,
                    "material": None,   # [2026-10-07] 인입관도 빈칸 — 엔진 기본 송수호스 50 · main_mm 지정 시 같은 호칭(intake) "d_mm": None,
                    "pts": pts, "by_ceo": True, "draw_id": draw_id})
    return out


def draw_bridge(draw, handle_features, role="main", drafts=None, head_features=None,
                mode="none", rev=None):
    """일반 마커 드래그를 draw:edited 이벤트로 전달; 손잡이는 급수원과 구별한다.

    `head_features` = 스프링클러 표식(`head_marks`). **클릭**을 같은 통로로 보낸다.
    """
    from branca.element import MacroElement, Template
    bridge = MacroElement()
    bridge.draw = draw
    # 🔴 [V111] 그려 둔 도형(drafts)은 **컴포넌트 키(해시)에 안 보이게** 싣는다.
    #    streamlit-folium 은 지도 스크립트 전체의 해시를 위젯 키로 쓰고(`generate_js_hash`), 키가 바뀌면 지도를
    #    통째로 다시 만든다. 도형 JSON 을 그대로 넣으면 도형이 하나 늘 때마다 키가 바뀌는데, 그 재생성은 도형이
    #    저장된 **다음** 재실행 — 곧 **다음 그리기의 첫 클릭** — 에서 일어나 그리던 밭·인입관이 날아갔다
    #    (대표 실사용 2026-09-16 「밭을 그리면 잠시 후 깜빡거리고 이전 상태 · 다시 그리면 된다」 · playwright 재현).
    #    해시는 `_[a-z0-9]+` 토막을 지우고 계산하므로, 도형을 `_` + hex 로 넣으면 해시에 안 잡힌다. 살아 있는
    #    지도는 스크립트를 다시 돌리지 않으니 도형은 이미 화면에 있고, 다른 이유로 다시 만들어질 때만 여기서 복원한다.
    drafts_hex = "_" + json.dumps(drafts or [], ensure_ascii=False).encode("utf-8").hex()
    payload = json.dumps({"handles": handle_features, "role": role, "drafts_hex": drafts_hex,
                          "heads": head_features or [], "mode": mode, "rev": rev},
                         ensure_ascii=False).replace("<", "\\u003c")
    bridge._template = Template(r"""
{% macro script(this, kwargs) %}
(function(){
 const map = {{this._parent.get_name()}}, group = drawnItems_{{this.draw.get_name()}};
 const data = __PAYLOAD__;
 (function(){ const h = (data.drafts_hex || "_5b5d").slice(1); const b = new Uint8Array(h.length >> 1);
   for (let i = 0; i < b.length; i++) { b[i] = parseInt(h.substr(i * 2, 2), 16); }
   try { data.drafts = JSON.parse(new TextDecoder('utf-8').decode(b)); } catch (e) { data.drafts = []; } })();
 data.drafts.forEach(function(f){
   L.geoJSON(f, {style: function(x){var r=(x.properties||{}).role;return {color: x.geometry.type==='Polygon'?'#ffd600':
     (r==='feeder'?'#ffa040':(r==='furrow'?'#2E8A4C':'#ff4b4b')), weight:4,
     dashArray:(r==='feeder'?'12,8':(r==='furrow'?'4,6':null))};}})
    .eachLayer(function(layer){group.addLayer(layer);});
 });
 map.on('draw:created', function(e){
   e.layer.feature = e.layer.feature || {type:'Feature', properties:{}};
   const p = e.layer.feature.properties;
   p.draw_id = p.draw_id || String(Date.now())+'-'+String(Math.random()).slice(2);
   if(e.layerType==='polyline'){
     p.role=data.role;                       // [V112] 'furrow' = 🧭 고랑 방향 임시 선(관이 아니다)
     e.layer.setStyle({color:data.role==='feeder'?'#ffa040':(data.role==='furrow'?'#2E8A4C':'#ff4b4b'),
                       dashArray:data.role==='feeder'?'12,8':(data.role==='furrow'?'4,6':null)});
   }
 });
 let p3drawing=false;
 map.on('draw:drawstart', function(){p3drawing=true;});
 map.on('draw:drawstop',  function(){p3drawing=false;});
 if(data.mode==='add'){                       // 빈 자리를 누르면 그 자리에 한 두 더
   map.on('click', function(e){
     if(p3drawing) return;                    // 그리는 중의 클릭은 도형의 것이다
     const f={type:'Feature',geometry:{type:'Point',coordinates:[e.latlng.lng,e.latlng.lat]},
              properties:{kind:'looperget_head_add',revision:data.rev,click_id:String(Date.now())}};
     const m=L.marker(e.latlng,{opacity:0.01});
     m.feature=f; m.addTo(map);
     map.fire('draw:edited',{layer:m,layers:L.featureGroup([m])});
     setTimeout(function(){map.removeLayer(m);},50);
   });
 }
 (data.heads||[]).forEach(function(f){
   const xy=f.geometry.coordinates, back=f.properties.action==='restore';
   const mark=L.marker([xy[1],xy[0]], {
     icon:L.divIcon({className:'p3-head-pick',iconSize:[22,22],iconAnchor:[11,11],
       html:'<div style="background:'+(back?'rgba(60,66,72,.92)':'rgba(6,42,58,.92)')+
            ';color:'+(back?'#d7dde3':'#7ff3ff')+';border:2px solid '+(back?'#9aa4ae':'#00e5ff')+
            ';border-radius:50%;text-align:center;line-height:18px;font-size:12px;cursor:pointer">'+
            (back?'✕':'●')+'</div>'})});
   mark.feature=f;
   mark.bindTooltip(back?'뺀 스프링클러 — 누르면 되살립니다':'누르면 이 스프링클러를 뺍니다');
   mark.on('click', function(e){
     if(e.originalEvent){L.DomEvent.stopPropagation(e.originalEvent);}
     map.fire('draw:edited',{layer:mark,layers:L.featureGroup([mark])});
   });
   mark.addTo(map);
 });
 data.handles.forEach(function(f){
   const xy=f.geometry.coordinates;
   const marker=L.marker([xy[1],xy[0]], {draggable:true,
     icon:L.divIcon({className:'p3-row-handle',iconSize:[26,26],iconAnchor:[13,13],
       html:'<div style="background:#063e35;color:white;border:2px solid #a7ffdd;border-radius:50%;text-align:center;line-height:22px;font-size:18px;cursor:grab">↔</div>'})});
   marker.feature=f;
   marker.bindTooltip('가지관 '+(f.properties.row_index+1)+' — 잡고 옆으로 이동');
   marker.on('dragend', function(){map.fire('draw:edited',{layer:marker,layers:L.featureGroup([marker])});});
   marker.addTo(map);  // 점 편집/지우기의 대상은 사용자가 그린 도형만
 });
})();
{% endmacro %}
""".replace("__PAYLOAD__", payload))
    return bridge


# ── [2026-10-07 봉소리 97 · 대표] 좌표를 숫자로 그리기 — 사람이 화면에 **같은 값**을 넣어 같은 산출물을 낸다.
#    클릭으로는 0.01 m 까지 같은 자리를 찍을 수 없다. 숫자 도형은 지도 그림(drafts)과 **같은 형식**으로 만들어
#    「✅ 그린 것을 목록에 넣기」와 같은 길을 탄다 — 목록·표·엔진 쪽 규칙은 그대로다.
COORD_KINDS = {"밭": "Polygon", "급수원": "Point", "주배관": "main", "인입관": "feeder"}
HEAD_KINDS = {"헤드 빼기": "drop_heads", "헤드 더하기": "add_heads"}


def _xy_list(body):
    out = []
    for tok in body.replace(";", " ").replace("(", " ").replace(")", " ").replace("[", " ").replace("]", " ").split():
        tok = tok.strip().strip(",")
        if not tok:
            continue
        a, sep, b = tok.partition(",")
        if not sep:
            raise ValueError("「%s」 — 점 하나는 「x,y」(쉼표 · 띄어쓰기 없이)로 적습니다" % tok)
        out.append([round(float(a), 2), round(float(b), 2)])
    return out


def parse_coord_text(text):
    """줄마다 「종류 [이름]: x,y x,y …」(m · 원점 기준 · x 동쪽 · y 북쪽).

    종류 = 밭 · 급수원 · 주배관 · 인입관 · 헤드 빼기 · 헤드 더하기. 빈 줄과 # 로 시작하는 줄은 건너뛴다.
    돌려주는 것 = (도형 목록[(종류, 점들)], 헤드 {"drop_heads": [...], "add_heads": [...]}).
    """
    shapes, heads = [], {}
    for n, line in enumerate((text or "").splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        head, sep, body = line.partition(":")
        if not sep:
            raise ValueError("%d번째 줄 — 「종류: x,y x,y」 형식이 아닙니다(쌍점 : 이 없음)" % n)
        head = " ".join(head.split())
        hk = next((k for k in HEAD_KINDS if head.startswith(k)), None)
        kind = None if hk else next((k for k in COORD_KINDS if head.startswith(k)), None)
        if not (hk or kind):
            raise ValueError("%d번째 줄 — 종류 「%s」를 모릅니다(밭·급수원·주배관·인입관·헤드 빼기·헤드 더하기)" % (n, head))
        try:
            pts = _xy_list(body)
        except ValueError as exc:
            raise ValueError("%d번째 줄 — %s" % (n, exc))
        if hk:
            heads.setdefault(HEAD_KINDS[hk], []).extend(pts)
            continue
        need = {"밭": 3, "급수원": 1, "주배관": 2, "인입관": 2}[kind]
        if len(pts) < need or (kind == "급수원" and len(pts) != 1):
            raise ValueError("%d번째 줄 — %s 은(는) 점 %s개가 필요합니다(지금 %d개)"
                             % (n, kind, "1" if kind == "급수원" else "%d개 이상" % need, len(pts)))
        shapes.append((kind, pts))
    return shapes, heads


def coord_features(shapes, origin, stamp="num"):
    """숫자 도형 → 지도 그림(GeoJSON Feature) — 지도에서 그린 것과 같은 모양(역할 · draw_id)."""
    feats = []
    for i, (kind, pts) in enumerate(shapes):
        ll = mapsrc.from_local_m(pts, origin)
        if kind == "밭":
            geom = {"type": "Polygon", "coordinates": [ll + [ll[0]]]}
            prop = {}
        elif kind == "급수원":
            geom = {"type": "Point", "coordinates": ll[0]}
            prop = {}
        else:
            geom = {"type": "LineString", "coordinates": ll}
            prop = {"role": COORD_KINDS[kind]}
        prop["draw_id"] = "%s-%d" % (stamp, i + 1)
        feats.append({"type": "Feature", "geometry": geom, "properties": prop})
    return feats


def coord_text(pins):
    """지금 목록(pins)을 같은 형식의 글로 — 적어 둔 값과 화면 값이 같은지 눈으로 대조한다."""
    fmt = lambda pts: " ".join("%g,%g" % (round(q[0], 2), round(q[1], 2)) for q in pts)
    lines = []
    for b in (pins or {}).get("blocks") or []:
        lines.append("밭 %s: %s" % (b.get("name") or "", fmt(b.get("polygon_raw") or b.get("polygon") or [])))
    for s in (pins or {}).get("sources") or []:
        lines.append("급수원 %s: %s" % (s.get("name") or "", fmt([s["pt"]])))
    for r in (pins or {}).get("routes") or []:
        kind = "인입관" if r.get("role") == "feeder" else "주배관"
        lines.append("%s %s: %s" % (kind, r.get("name") or "", fmt(r.get("pts") or [])))
    for b in (pins or {}).get("blocks") or []:
        pol = b.get("policy") or {}
        for key, label in (("drop_heads", "헤드 빼기"), ("add_heads", "헤드 더하기")):
            if pol.get(key):
                lines.append("%s: %s" % (label, fmt(pol[key])))
    return "\n".join(lines)

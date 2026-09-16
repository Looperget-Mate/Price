"""Shared customer-facing requirement lines; numbers only from supply engine."""
import html

STATUS = {"conditional": "입력조건 기준 가능 · 현장 확인 필요", "insufficient": "공급 부족",
          "unverified": "급수원 확인 필요", "미확정": "미확정"}


def zone_line(zone):
    q, p = zone.get("required_flow_lpm"), zone.get("required_pressure_bar")
    if q is None or p is None:
        return "구역 %s: 요구조건 미확정 — %s" % (zone.get("zone", ""), " · ".join(zone.get("notes") or []))
    return "구역 %s · %s두: %.1f L/분에서 %.2f bar 이상 (양정 %.1f m) — %s" % (
        zone.get("zone", ""), zone.get("heads", ""), q, p, zone["required_head_m"],
        STATUS.get(zone.get("status"), "급수원 확인 필요"))


def lines(summary):
    report = summary.get("supply") or {}
    return ["구역별 필요 공급조건 — 각 구역 순차 운전 기준",
            "표시 유량과 압력을 동시에 확보해야 합니다. 정지압·최대양정만으로 판단하지 않습니다.",
            *[zone_line(z) for z in report.get("zones", [])],
            *report.get("notes", [])]


def html_document(summary):
    esc = lambda value: html.escape(str(value))
    paragraphs = "".join("<p>%s</p>" % esc(line) for line in lines(summary))
    connections = []
    for chain in summary.get("chains") or []:
        route = " → ".join(str(link.get("custom_name") or link.get("code") or (link.get("pipe") or {}).get("label") or link.get("id"))
                           for link in chain.get("links") or [])
        connections.append("<p><b>%s · %s</b><br>%s</p>" % (esc(chain.get("part")), esc(chain.get("connection_id")), esc(route)))
    rows = []
    for group in summary.get("head_groups") or []:
        rows.append("<p>%s열 · %s두 — %s</p>" % (esc(", ".join(map(str, group["rows"]))), group["heads"], esc(group["kit"]["label"])))
    notes = "".join("<li>%s</li>" % esc(w) for w in summary.get("warnings") or [])
    return ('<!doctype html><html lang="ko"><meta charset="utf-8"><title>급수·연결 조건</title>'
            '<style>body{font:16px/1.8 sans-serif;max-width:1000px;margin:40px auto;padding:24px;color:#231815}'
            'h1{border-bottom:6px solid #F3DC18}p{break-inside:avoid}</style>'
            '<h1>%s · 급수·연결 조건</h1>%s<h2>연결 사슬</h2>%s<h2>열별 살수 세트</h2>%s'
            '<h2>확인 사항</h2><ul>%s</ul><p>설계 초안 · 최종 공급조건은 현장에서 확인합니다.</p></html>') % (
                esc(summary.get("name")), paragraphs, "".join(connections) or "<p>사슬 입력 없음</p>",
                "".join(rows) or "<p>밭 전체 기본 세트</p>", notes)

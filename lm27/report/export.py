# -*- coding: utf-8 -*-
r"""내보내기 — 자기완결 HTML · CSV 15종 · JSON · manifest · 보관 정리(R §9.1 · §9.3 · §9.4 · §10.2 · §11, 계약 §1.2 · §3.23 ·
§9.2 · L-19 · G-R1 · G-R4~G-R6 · G-R8).

    export(run_id, formats, variants, out_dir=None) -> ExportResult      `lm27 report export --run … --formats … --variant …`

폴더 `ROOT\out\personal\<from>_<to>_<run8>\`(`Paths.out_personal_file` — CR) 또는 `--out <폴더>`(그 폴더에 바로):

| 파일 | 변형 | 반출 |
|---|---|---|
| `report_full.html` · `report_model.json` · `csv_full\*.csv` | full | **로컬 전용**(머리 배지·안내) |
| `report_redacted.html` · `report_model_redacted.json` · `csv_redacted\*.csv` | redacted(허용 목록으로 다시 만든 모델) | 공유용 |
| `manifest.json` | `lm27.export/1` — `{run_id, report_version, built_at, files[{path, variant, format, bytes, sha256}]}` | — |

- **데이터 섬**(G-R6): `island(obj)` = 정규 JSON 의 `<`·`>`·`&`·U+2028·U+2029 를 `\u003c` 등으로. 인라인하는 JS·CSS 에
  `</script`·`</style` 이 있으면 만들지 않는다(rc 1). HTML 껍데기에 값을 넣는 곳은 `render_html` 하나뿐이다(G-R4) — 넣는 값은 섬
  문자열과 형식을 검사한 run_id·시각·변형 이름뿐이다. 외부 참조 0(G-R5): 아이콘 symbol 을 문서 안 `<svg hidden>` 에 둔다(무늬
  defs 는 `lm27ui.ensureDefs` 가 실행 중 마운트 — WP-28).
- **크기 상한** `report.export.maxHtmlMb`: 넘으면 드릴다운 섬의 ① 날짜 상세 → ② 단위업무 근거 줄 → ③ 단위업무 상세 순으로 빼고
  섬의 `trimmed` 에 적는다(머리 알림 줄). 모델 본체는 빼지 않는다.
- **결정성**(G-R1): 같은 입력이면 HTML 은 `<!-- LM27 report/1 · run … · built … -->` 한 줄만 다르다.
- **가림판 검사**(G-R8): 직렬화 바이트에 사람 사전 이름·로컬 키 모양(·시험 카나리아)이 있으면 가림판을 만들지 않는다(rc 1,
  필드 경로만 — 값은 보이지 않음). 전체판은 만든다.
- **CSV**(계약 §9.2): UTF-8 BOM(`report.csv.bom`) + CRLF, 첫 줄 한글 열 이름, 분은 정수·MM·비율은 `fmt` 표시 함수 글자,
  수식 주입 방어(`= + - @ 탭 CR` 로 시작하는 글자 칸 앞에 `'`), ASCII 파일 이름.
- **보관**: `report.export.keep` 개를 넘으면 `out\personal\` 아래 이 모듈이 만든 이름 형식 폴더만 오래된 것부터 지운다.

표준 라이브러리만 쓴다. 최종 파일 쓰기는 `lm27.util.fsx.atomic_write` 로만(L-07), 나눗셈·반올림은 `lm27.report.fmt` 로만.
"""
from __future__ import annotations

import csv
import io
import os
import re
import shutil
import sys
import types
from collections.abc import Mapping
from dataclasses import dataclass, field

from lm27.report import fmt as F
from lm27.report import vocab as V

__all__ = ["CSV_NAMES", "FORMATS", "VARIANTS", "ExportError", "ExportResult", "csv_bytes", "csv_cell", "csv_tables",
           "export", "fit_html", "hidden_titles", "island", "load_assets", "prune_exports", "render_html"]

FORMATS = ("html", "csv", "json")
VARIANTS = ("full", "redacted")
FOLDER_RX = re.compile(r"^\d{4}-\d{2}-\d{2}_\d{4}-\d{2}-\d{2}_[0-9a-f-]{8}$")
_RUN_RX = re.compile(r"^\d{8}-\d{6}-[0-9a-f]{4}$")
_ISO_RX = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:[+-]\d{2}:\d{2}|Z)$")
FORBIDDEN = ("대체 가능", "절감", "AX 가능 MM")       # RP4 · RPT-33
FILE_NAMES = {("full", "html"): "report_full.html", ("redacted", "html"): "report_redacted.html",
              ("full", "json"): "report_model.json", ("redacted", "json"): "report_model_redacted.json"}
CSV_DIR = {"full": "csv_full", "redacted": "csv_redacted"}
ASSETS = (("css", "common/lm27.css"), ("icons", "common/icons.svg"), ("charts", "common/lm27charts.js"),
          ("ui", "common/lm27ui.js"), ("report", "app/report.js"))
BADGE = {"full": "전체판(로컬 전용)", "redacted": "가림판"}
FULL_NOTICE = "이 파일에는 동료 이름·문서 이름이 들어 있습니다 — 내 PC 밖으로 보내지 마세요(공유는 가림판)."
MB = 1048576
_FORMULA = ("=", "+", "-", "@", "\t", "\r")
BUCKET_NAMES = {"B_GENERIC": "일반 앱", "B_COMM": "소통", "B_MEET": "회의", "B_OFFPC": "PC 밖", "B_UNKNOWN": "미상"}
TAGS = ("regular", "extended", "night", "holiday")
CSV_NAMES = ("monthly.csv", "daily.csv", "units.csv", "alloc_daily.csv", "buckets_daily.csv", "rollup.csv",
             "workflow_steps.csv", "workflow_edges.csv", "reviews.csv", "lead_overrun.csv", "peers.csv",
             "agentic_matches.csv", "agentic_needs.csv", "subagent.csv", "ontology_edges.csv")


class ExportError(ValueError):
    """내보내기를 만들 수 없음(인라인 자원의 `</script` 등 — G-R6)."""


@dataclass
class ExportResult:
    """내보내기 결과 — cli 는 `rc` 를 읽는다(0 · 1). 경로는 ROOT 상대(밖이면 절대)."""
    rc: int
    run_id: str
    out_dir: str = ""
    files: list = field(default_factory=list)       # [{path, variant, format, bytes, sha256}]
    failed: list = field(default_factory=list)      # [{path, variant, format, reason}]
    warnings: list = field(default_factory=list)
    trimmed: dict = field(default_factory=dict)     # 변형 → 줄인 것
    pruned: list = field(default_factory=list)


# ───────────────────────────── 데이터 섬(G-R6) ─────────────────────────────
def island(obj) -> str:
    r"""R §9.4: `canon_bytes(obj)` 를 글자로 바꾼 뒤 `<`·`>`·`&`·U+2028·U+2029 를 `\u003c`·`\u003e`·`\u0026`·`\u2028`·
    `\u2029` 로(JSON 문자열 안에서만 나오는 글자라 JSON 뜻은 그대로)."""
    from lm27.util.fsx import canon_bytes
    s = canon_bytes(obj).decode("utf-8")
    return (s.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
            .replace("\u2028", "\\u2028").replace("\u2029", "\\u2029"))


def load_assets(paths) -> dict[str, str]:
    """인라인할 렌더러 한 벌(RP10) — `</script`·`</style` 이 있으면 ExportError(G-R6). 아이콘은 symbol 들만."""
    from lm27.util import fsx
    out = {}
    for key, rel in ASSETS:
        try:
            text = fsx.read_bytes(paths.web_file(rel)).decode("utf-8-sig")
        except OSError as e:
            raise ExportError(f"화면 자원을 읽지 못했습니다({type(e).__name__}): {rel}") from None
        if re.search(r"(?i)</(?:script|style)", text):
            raise ExportError(f"인라인 자원에 '</script'·'</style' 이 있어 보고서를 만들지 않았습니다(G-R6): {rel}")
        if key == "icons":
            text = "\n".join(re.findall(r"<symbol\b.*?</symbol>", text, flags=re.S))
        out[key] = text
    return out


def render_html(model_isl: str, drill_isl: str, *, variant: str, run_id: str, built_at: str,
                assets: Mapping[str, str]) -> str:
    """자기완결 HTML(R §9.4) — 값을 HTML 껍데기에 넣는 **유일한** 함수(G-R4). 섬은 `island()` 결과만, 그 밖 값은 형식 검사."""
    if variant not in VARIANTS:
        raise ExportError("변형 이름 오류")
    if not _RUN_RX.match(str(run_id)) or not _ISO_RX.match(str(built_at)):
        raise ExportError("run_id · built_at 형식 오류")
    if re.search(r"[<>&\u2028\u2029]", model_isl + drill_isl):
        raise ExportError("데이터 섬에 이스케이프되지 않은 글자가 있습니다(G-R6)")
    notice = ('<p class="alert alert-warn" role="note">' + FULL_NOTICE + "</p>\n") if variant == "full" else ""
    parts = [
        '<!doctype html>\n<html lang="ko">\n<head>\n<meta charset="utf-8">\n',
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n',
        '<meta name="color-scheme" content="light">\n<title>LM27 개인 보고서</title>\n<style>\n', assets["css"],
        "\n</style>\n</head>\n", '<body data-variant="', variant, '" data-kind="personal">\n',
        "<!-- LM27 report/1 · run ", run_id, " · built ", built_at, " -->\n",
        '<svg hidden aria-hidden="true" focusable="false"><defs>\n', assets["icons"], "\n</defs></svg>\n",
        '<header class="app-head"><strong>LM27 개인 보고서</strong> <span class="badge">', BADGE[variant],
        '</span><span class="spacer"></span></header>\n', notice,
        '<main id="app" tabindex="-1"></main>\n',
        '<script type="application/json" id="lm27-data">', model_isl, "</script>\n",
        '<script type="application/json" id="lm27-drill">', drill_isl, "</script>\n",
        "<script>\n", assets["charts"], "\n</script>\n<script>\n", assets["ui"], "\n</script>\n<script>\n",
        assets["report"], "\n</script>\n</body>\n</html>\n"]
    return "".join(parts)


def fit_html(model: Mapping, drill: dict, cap_bytes: int, render) -> tuple[str, list[str]]:
    """크기 상한(R §9.4): ① 드릴다운 날짜 상세 → ② 단위업무 근거 줄 → ③ 단위업무 상세 순으로 섬에서 빼고 `trimmed` 에 적는다.
    모델 본체는 빼지 않는다. 반환 (HTML, 줄인 것 이름 목록) — 다 빼도 넘으면 그대로(호출자가 경고)."""
    m_isl = island(model)
    d = {"units": dict(drill.get("units") or {}), "days": dict(drill.get("days") or {}),
         "trimmed": list(drill.get("trimmed") or [])}
    html = render(m_isl, island(d))
    if len(html.encode("utf-8")) <= cap_bytes:
        return html, d["trimmed"]

    def drop_days(x):
        x["days"] = {}
        return "근거 › 날짜 상세"

    def drop_evidence(x):
        x["units"] = {k: {kk: vv for kk, vv in v.items() if kk not in ("evidence", "evidence_more")}
                      for k, v in x["units"].items()}
        return "단위업무 근거 줄"

    def drop_units(x):
        x["units"] = {}
        return "단위업무 근거 상세"
    for step in (drop_days, drop_evidence, drop_units):
        d["trimmed"].append(step(d))
        html = render(m_isl, island(d))
        if len(html.encode("utf-8")) <= cap_bytes:
            break
    return html, d["trimmed"]


# ───────────────────────────── CSV(R §9.3) ─────────────────────────────
def csv_cell(v):
    """한 칸: None → '' · 수(int·float)는 그대로 · 글자는 `= + - @ 탭 CR` 로 시작하면 앞에 `'`(수식 주입 방어)."""
    if v is None:
        return ""
    if isinstance(v, bool):
        return "Y" if v else ""
    if isinstance(v, (int, float)):
        return v
    s = str(v)
    return "'" + s if s.startswith(_FORMULA) else s


def csv_bytes(cols, rows, *, bom: bool = True) -> bytes:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\r\n", quoting=csv.QUOTE_MINIMAL)
    w.writerow([csv_cell(c) for c in cols])
    for r in rows:
        w.writerow([csv_cell(c) for c in r])
    return (("\ufeff" if bom else "") + buf.getvalue()).encode("utf-8")


def _sp(s) -> str:
    return "" if s is None else str(s).replace("T", " ")


def _num(v, d: int) -> str:
    s = F.fmt_num(v, d)
    return "" if s is None else s


def _share(v) -> str:
    return "" if v is None else F.share_text(v)


def csv_tables(model: Mapping, registry=None) -> dict[str, tuple[list, list]]:
    """R §9.3.2 개인 CSV 15종(변형 모델에서 — 가림판 CSV 는 가림판 모델에서)."""
    dom = {d["code"]: d["name"] for d in model.get("domains") or ()}
    proj = {p["key"]: p.get("label") or p["key"] for p in model.get("projects") or ()}
    roles = {r["role_id"]: r for r in model.get("roles") or ()}
    units = model.get("units") or []
    umap = {u["unit_id"]: u for u in units}
    months = model.get("months") or []
    denom = {m["m"]: m["denom_min"] for m in months}
    t: dict[str, tuple[list, list]] = {}
    t["monthly.csv"] = (
        ["월", "근무일", "분모(분)", "근무(분)", "정규", "연장", "야간", "휴일", "귀속", "미귀속", "관측", "추정", "MM",
         "로드율(%)", "가용일", "초과(근무창 밖)", "초과(일 8시간)", "부분월", "측정 품질", "품질 사유"],
        [[m["m"], m["workdays"], m["denom_min"], m["env_min"], *[m["by_tag"].get(x, 0) for x in TAGS],
          m["attributed_min"], m["unattr_min"], m["obs_min"], m["est_min"], F.fmt_mm(m["env_min"], m["denom_min"]),
          F.fmt_pct(m["env_min"], m["avail_min"]) if m.get("avail_min") else "", _num(m.get("avail_days"), 1),
          m["overtime_window_min"], m["overtime_daily8h_min"],
          f"{m['partial']['workdays']}/{m['partial']['of']}" if m.get("partial") else "",
          V.GRADE_NAMES.get((m.get("quality") or {}).get("grade", ""), ""),
          " ".join((m.get("quality") or {}).get("reasons", ()))] for m in months])
    t["daily.csv"] = (
        ["날짜", "휴일", "정규", "연장", "야간", "휴일근무", "근무", "신뢰 높음", "중간", "낮음", "관측", "추정", "미귀속",
         "휴가", "표식"],
        [[d["d"], bool(d["hol"]), *[d["by_tag"].get(x, 0) for x in TAGS], d["env_min"], d["conf_min"].get("high", 0),
          d["conf_min"].get("mid", 0), d["conf_min"].get("low", 0), d["obs_min"], d["est_min"], d["unattr_min"],
          _num(d.get("leave"), 1) if d.get("leave") else "", " ".join(d.get("flags") or ())]
         for d in model.get("days") or ()])
    urows = []
    for u in units:
        r = roles.get(u["role_id"], {})
        cyc = u.get("cycles") or [{}]
        last = cyc[-1]
        urows.append([u["unit_id"], u.get("title"), V.LABEL_BY.get(u.get("title_by"), u.get("title_by")),
                      dom.get(u["domain"], u["domain"]), proj.get(u["project_key"], u["project_key"]), u["role_id"],
                      u["field"], r.get("field_name", u["field"]), u["function"], r.get("function_name", u["function"]),
                      u["activity_type"], V.wtype_name(u["activity_type"], registry), u.get("stance"),
                      u.get("label_level"), bool(u.get("ax_link")), u.get("kind"), cyc[0].get("sb"), _sp(cyc[0].get("s")),
                      last.get("eb") if last.get("e") else "OPEN", _sp(last.get("e")), u.get("grade"), u.get("status"),
                      u.get("lead_min"), u.get("biz_lead_min"), u["effort_min"], u["obs_min"], u["est_min"],
                      _num(u.get("parallel"), 1), u.get("machine_min"), u.get("pre_request_min"),
                      len(u.get("cycles") or ()), len(u.get("peers") or ()), " | ".join(u.get("flags") or ())])
    t["units.csv"] = (["단위업무 ID", "제목", "제목 출처", "업무 영역", "과제", "역할 ID", "분야 코드", "분야", "기능 코드",
                       "기능", "업무 유형 코드", "업무 유형", "참여 방식", "분류 신뢰", "AX 연계", "종류", "시작 근거", "시작",
                       "종료 근거", "종료", "등급", "상태", "리드(분)", "영업 리드(분)", "투입", "관측", "추정", "병행도",
                       "기계 시간", "선행 착수", "차수", "동료 수", "표식"], urows)
    tables = model.get("tables") or {}
    t["alloc_daily.csv"] = (["날짜", "단위업무 ID", "꼬리표", "분"],
                            [list(r) for r in (tables.get("alloc_daily") or {}).get("rows") or ()])
    t["buckets_daily.csv"] = (["날짜", "버킷", "꼬리표", "분"],
                              [list(r) for r in (tables.get("buckets_daily") or {}).get("rows") or ()])
    t["rollup.csv"] = (["월", "수준", "키", "이름", "분", "MM"], _rollup_rows(model, units, dom, proj, roles, denom,
                                                                           registry))
    srows, erows = [], []
    for rid, rw in sorted(((model.get("workflows") or {}).get("roles") or {}).items()):
        bn: dict[int, list[str]] = {}
        for b in rw.get("bottlenecks") or ():
            bn.setdefault(b["no"], []).append("대기" if b["kind"] == "wait" else "작업")
        for s in rw.get("steps") or ():
            srows.append([rid, s["no"], s["code"], s.get("name"), s.get("label"),
                          V.LABEL_BY.get(s.get("label_by"), s.get("label_by")), "점" if s.get("kind") == "M" else "구간",
                          s.get("n"), _num(s.get("freq_month"), 1), s.get("median_min"), s.get("p75_min"),
                          _share(s.get("obs_share")), s.get("wait_in_median_min"), _share(s.get("work_share")),
                          "·".join(bn.get(s["no"], ())), s.get("agent_grade"), s.get("subagent")])
        waits = {(e[0], e[1]): e[2] for e in rw.get("edge_waits") or ()}
        for e in list(rw.get("edges") or ()) + list(rw.get("edges_rest") or ()):
            erows.append([rid, e[0], e[1], e[2], waits.get((e[0], e[1])), e[0] > e[1]])
    t["workflow_steps.csv"] = (["역할 ID", "번호", "단계 코드", "한글명", "라벨", "라벨 출처", "종류", "지지도", "월 빈도",
                                "중앙 소요", "75% 소요", "관측 비율", "들어오는 대기 중앙", "작업 비중", "병목",
                                "Agentic 등급", "서브에이전트"], srows)
    t["workflow_edges.csv"] = (["역할 ID", "앞 번호", "뒤 번호", "횟수", "대기 중앙", "되돌림"], erows)
    rrows, orows = [], []
    rv = model.get("reviews") or {}
    for kind, name in (("weeks", "주"), ("months", "월")):
        for r in rv.get(kind) or ():
            ai = r.get("ai") or {}
            rrows.append([name, r["key"], r.get("from"), r.get("to"), r.get("env_min"), r.get("attributed_min"),
                          len(r.get("started") or ()), len(r.get("finished") or ()), len(r.get("unstarted") or ()),
                          sum(1 for x in r.get("lead_table") or () if x.get("overrun")),
                          V.LABEL_BY.get(ai.get("by"), ai.get("by") or "") if ai else ""])
            if kind == "months":
                for x in r.get("lead_table") or ():
                    ov = x.get("overrun")
                    orows.append([r["key"], x["unit_id"], (umap.get(x["unit_id"]) or {}).get("title"), x.get("role_id"),
                                  x.get("biz_lead_min"), x.get("baseline_biz_min"), _num(x.get("ratio"), 2),
                                  "판정 안 함" if ov is None else ("초과" if ov else "아님"),
                                  "·".join(x.get("cause_names") or ())])
    t["reviews.csv"] = (["종류", "기간 키", "시작", "끝", "근무", "귀속", "새로 시작", "끝냄", "미착수", "초과", "요약 출처"],
                        rrows)
    t["lead_overrun.csv"] = (["기간 키", "단위업무 ID", "제목", "역할 ID", "영업 리드", "기준", "배수", "초과", "원인"], orows)
    t["peers.csv"] = (["번호", "이름", "사내", "공동 단위업무", "공유 투입", "의뢰", "보고", "대화", "회의", "과제", "처음", "마지막"],
                      [[p["k"], p.get("name"), "사내" if p.get("internal") else "미확인", p["units"], p["shared_effort_min"],
                        p["roles"].get("requester", 0), p["roles"].get("reporter", 0), p["roles"].get("thread", 0),
                        p["roles"].get("meeting", 0), " ".join(p.get("projects") or ()), p.get("first"), p.get("last")]
                       for p in (model.get("peers") or {}).get("internal") or ()])
    ag = model.get("agentic") or {}
    an = {a["id"]: a.get("name", a["id"]) for a in ag.get("catalog") or ()}
    t["agentic_matches.csv"] = (
        ["에이전트 ID", "이름", "단계 유형", "등급", "출처", "규칙과 다름", "역할", "단위업무 수", "관련 투입", "AI 근거", "규칙 근거"],
        [[m["agent_id"], an.get(m["agent_id"], m["agent_id"]), m["step_type"], m.get("grade"),
          V.LABEL_BY.get(m.get("by"), m.get("by")), bool(m.get("disagree")), " ".join(m.get("roles") or ()),
          len(m.get("units") or ()), m.get("related_min"), m.get("why_ai"),
          "·".join(V.RULE_WHY.get(w, w) for w in m.get("why_rule") or ())] for m in ag.get("matches") or ()])
    t["agentic_needs.csv"] = (
        ["니즈 ID", "이름", "로직", "입력", "출력", "단계 유형", "월 빈도", "등급", "출처", "팀 제외"],
        [[n["need_id"], n.get("name"), n.get("logic"), n.get("in"), n.get("out"), n.get("step_type"),
          _num(n.get("freq_per_month"), 1), n.get("grade"), V.LABEL_BY.get(n.get("by"), n.get("by")),
          bool(n.get("dropped"))] for n in ag.get("needs") or ()])
    sa_rows = []
    for r in (model.get("subagent") or {}).get("roles") or ():
        checks: dict[int, str] = {}
        for sub in ((r.get("ai") or {}).get("subs") or ()):
            for n in sub.get("steps") or ():
                checks.setdefault(n, sub.get("check") or "")
        for s in r.get("steps") or ():
            sa_rows.append([r["role_id"], s["no"], s["code"], s.get("label"), s.get("REP"), s.get("IO"), s.get("TOOL"),
                            s.get("VER"), s.get("RISK"), s.get("score"), s.get("rule"), s.get("final"),
                            "·".join(V.SUB_WHY.get(w, w) for w in s.get("why") or ()), checks.get(s["no"], "")])
    t["subagent.csv"] = (["역할 ID", "번호", "단계 코드", "라벨", "반복성", "입출력", "도구 접근", "검증", "위험", "점수",
                          "규칙 판정", "최종", "근거", "확인 지점"], sa_rows)
    t["ontology_edges.csv"] = (["출발 종류", "출발", "관계", "도착 종류", "도착", "근거 수", "분", "추론"],
                               _onto_rows(model.get("ontology") or {}))
    return t


def _rollup_rows(model, units, dom, proj, roles, denom, registry) -> list[list]:
    agg: dict[tuple[str, str, str], int] = {}
    order = {"영역": 0, "과제": 1, "역할": 2, "유형": 3, "미귀속": 4}
    for u in units:
        for m, v in (u.get("by_month") or {}).items():
            for lvl, key in (("영역", u["domain"]), ("과제", u["project_key"]), ("역할", u["role_id"]),
                             ("유형", u["activity_type"])):
                agg[(m, lvl, key)] = agg.get((m, lvl, key), 0) + int(v)
    for mrow in model.get("months") or ():
        for b, v in (mrow.get("buckets") or {}).items():
            if v:
                agg[(mrow["m"], "미귀속", b)] = int(v)

    def name(lvl, key):
        if lvl == "영역":
            return dom.get(key, key)
        if lvl == "과제":
            return proj.get(key, key)
        if lvl == "역할":
            return (roles.get(key) or {}).get("label", key)
        if lvl == "유형":
            return V.wtype_name(key, registry)
        return BUCKET_NAMES.get(key, key)
    return [[m, lvl, key, name(lvl, key), v, F.fmt_mm(v, denom.get(m, 0)) or ""]
            for (m, lvl, key), v in sorted(agg.items(), key=lambda kv: (kv[0][0], order[kv[0][1]], -kv[1], kv[0][2]))]


def _onto_rows(onto: Mapping) -> list[list]:
    seen = set()
    rows = []
    graphs = [onto] + [g for _k, g in sorted((onto.get("graphs") or {}).items())]
    for g in graphs:
        nodes = {n["id"]: n for n in g.get("nodes") or ()}
        for e in g.get("edges") or ():
            k = (e["from"], e["to"], e["rel"])
            if k in seen:
                continue
            seen.add(k)
            a, b = nodes.get(e["from"], {}), nodes.get(e["to"], {})
            rows.append([V.ONTO_NODES.get(a.get("type"), ("", ""))[0], a.get("label") or e["from"], e["rel"],
                         V.ONTO_NODES.get(b.get("type"), ("", ""))[0], b.get("label") or e["to"], e.get("w"), e.get("h"),
                         bool(e.get("inferred"))])
    return rows


# ───────────────────────────── 보관 정리(R §9.1.1) ─────────────────────────────
def prune_exports(root, keep: int, protect=()) -> list[str]:
    r"""`out\personal\` 아래 이 모듈이 만든 이름 형식(`<from>_<to>_<run8>`) 폴더만, 만든 시각 순으로 `keep` 개를 넘는 오래된
    것을 지운다. 다른 폴더·파일은 건드리지 않는다. 반환 = 지운 폴더 이름."""
    try:
        entries = [e for e in os.scandir(os.fspath(root)) if e.is_dir(follow_symlinks=False) and FOLDER_RX.match(e.name)]
    except OSError:
        return []
    prot = {os.path.normcase(os.path.abspath(os.fspath(p))) for p in protect}

    def born(e):
        try:
            return e.stat(follow_symlinks=False).st_ctime_ns
        except OSError:
            return 0
    entries.sort(key=lambda e: (born(e), e.name))
    out = []
    for e in entries[: max(0, len(entries) - max(1, int(keep)))]:
        if os.path.normcase(os.path.abspath(e.path)) in prot:
            continue
        shutil.rmtree(e.path, ignore_errors=True)
        if not os.path.exists(e.path):
            out.append(e.name)
    return out


# ───────────────────────────── 내보내기 ─────────────────────────────
def _choose(given, default, allowed, what: str) -> list[str]:
    vals = list(given) if given else list(default)
    bad = [v for v in vals if v not in allowed]
    if bad or not vals:
        raise ValueError(f"내보내기 {what} 오류 — {', '.join(allowed)} 중에서 고르세요")
    return [v for v in allowed if v in vals]


def export(run_id: str, formats=None, variants=None, out_dir=None, **kw) -> ExportResult:
    r"""R §9.1 `lm27 report export --run … --formats … --variant … [--out <폴더>]`(계약 §7.1 — rc 0 · 1). 분석 폴더·내보내기
    폴더의 경로 메서드가 아직 `lm27.paths` 에 없거나(CR), 내보내기를 만들 수 없으면(`ExportError` — 화면 자원 없음·읽기 실패·
    인라인 자원의 `</script` 등 G-R6) 만들지 않고 rc 1 + 한국어 한 줄(예외로 올리지 않는다 — W2 검토 L05)."""
    from lm27.report.inputs import PathsMethodMissing
    try:
        return _export(run_id, formats, variants, out_dir, **kw)
    except (PathsMethodMissing, ExportError) as e:
        return ExportResult(rc=1, run_id=run_id, failed=[{"path": "", "variant": "", "format": "", "reason": str(e)}])


def _export(run_id: str, formats=None, variants=None, out_dir=None, *, paths=None, cfg=None, inputs=None, model=None,
            now=None, fallback=None, extra_needles=()) -> ExportResult:
    r"""R §9.1 `lm27 report export`. formats·variants 를 주지 않으면 `report.export.formats`·`variants`. out_dir = 그 폴더에 바로
    (주지 않으면 `out\personal\<from>_<to>_<run8>\` + 보관 정리). 키워드는 시험 주입점(model·inputs·now·fallback·
    extra_needles = 가림판 검사에 더할 값 — 시험 카나리아)."""
    from lm27.report import _now_iso, _rel, build_report, load_model, model_status
    from lm27.report.drill import drill_island
    from lm27.report.inputs import load_inputs, out_personal_file
    from lm27.report.model import redact_model, redaction_violations
    from lm27.report.resolve import Resolver
    from lm27.util import fsx
    if paths is None:
        from lm27.paths import Paths
        paths = Paths()
    if cfg is None:
        from lm27.config import load_config
        cfg = load_config(paths)
    fmts = _choose(formats, cfg["report.export.formats"], FORMATS, "형식")
    vrs = _choose(variants, cfg["report.export.variants"], VARIANTS, "변형")
    res = ExportResult(rc=0, run_id=run_id)
    if model is None:
        if model_status(run_id, paths=paths) != "ok":
            br = build_report(run_id, paths=paths, cfg=cfg, inputs=inputs, now=now, fallback=fallback)
            if br.rc == 1:
                res.rc = 1
                res.failed.append({"path": "", "variant": "", "format": "", "reason": br.message})
                return res
        model = load_model(run_id, paths=paths)
    run = model.get("run") or {}
    d0, d1 = run.get("from"), run.get("to")
    if not out_dir and not (d0 and d1):
        res.rc = 1
        res.failed.append({"path": "", "variant": "", "format": "", "reason": "분석 기간을 알 수 없어 내보낼 폴더를 정하지 못했습니다"})
        return res
    inp = inputs if inputs is not None else load_inputs(run_id, paths=paths, cfg=cfg, bundle_state=False,
                                                        evidence=("html" in fmts and "full" in vrs))
    built_at = _now_iso(cfg, now)
    from lm27.report.inputs import analysis_time, chosen_of
    analyzed_at = analysis_time(paths, run_id, int(cfg["time.tzOffsetMin"]))
    chosen = chosen_of(paths, run_id)
    if out_dir:
        base = os.path.abspath(os.fspath(out_dir))

        def target(rel):
            return os.path.join(base, *rel.split("/"))
    else:
        base = os.fspath(paths.out_personal(d0, d1, run_id))

        def target(rel):
            return out_personal_file(paths, d0, d1, run_id, rel)
    res.out_dir = _rel(paths, base)
    assets = load_assets(paths) if "html" in fmts else {}
    title_mode = str(cfg["team.unitTitleMode"])
    bom = bool(cfg["report.csv.bom"])
    cap = int(cfg["report.export.maxHtmlMb"]) * MB
    model_cap = int(cfg["report.export.maxModelMb"]) * MB
    refs = model.get("refs") or {}
    people = {v["key"]: int(k) for k, v in (refs.get("people") or {}).items() if v.get("key")}
    docs = {v["key"]: int(k) for k, v in (refs.get("docs") or {}).items() if v.get("key")}
    res_full = Resolver("full", inp.person_dir, inp.registry, inp.evidence, people_ref=people, doc_ref=docs,
                        proposals=(inp.hier or {}).get("proposals"))

    def write(rel, data: bytes, variant, fmt):
        try:
            fsx.atomic_write(target(rel), data)
        except OSError as e:
            res.failed.append({"path": rel, "variant": variant, "format": fmt, "reason": type(e).__name__})
            return
        res.files.append({"path": rel, "variant": variant, "format": fmt, "bytes": len(data),
                          "sha256": fsx.sha256_hex(data)})
        text = data.decode("utf-8", errors="replace")
        hits = [p for p in FORBIDDEN if p in text]
        if hits:
            res.warnings.append({"code": "forbidden_phrase", "path": rel, "phrases": hits})

    for variant in vrs:
        if variant == "full":
            vm = model
        else:
            vm = redact_model(model, inp.registry, person_dir=inp.person_dir, title_mode=title_mode)
            hidden = hidden_titles(model, vm)
            bad = redaction_violations(vm, inp.person_dir, extra=[*extra_needles, *hidden])
            if bad:
                for fmt in fmts:
                    res.failed.append({"path": FILE_NAMES.get((variant, fmt), CSV_DIR[variant]), "variant": variant,
                                       "format": fmt, "reason": "가림판에서 지워지지 않은 이름이 발견되어 만들지 않았습니다"
                                       f"(필드: {', '.join(bad[:3])})"})
                continue
        if "json" in fmts:
            data = fsx.canon_bytes(vm)
            if len(data) > model_cap:
                res.warnings.append({"code": "model_over_cap", "path": FILE_NAMES[(variant, "json")]})
            write(FILE_NAMES[(variant, "json")], data, variant, "json")
        if "csv" in fmts:
            for name, (cols, rows) in csv_tables(vm, inp.registry).items():
                write(f"{CSV_DIR[variant]}/{name}", csv_bytes(cols, rows, bom=bom), variant, "csv")
        if "html" in fmts:
            drill = drill_island(inp, vm, variant, cfg, res=res_full if variant == "full" else None)
            if variant != "full":
                bad = redaction_violations(drill, inp.person_dir, extra=[*extra_needles, *hidden])
                if bad:
                    res.failed.append({"path": FILE_NAMES[(variant, "html")], "variant": variant, "format": "html",
                                       "reason": f"가림판 근거 섬 검사 실패(필드: {', '.join(bad[:3])})"})
                    continue

            def render(m_isl, d_isl, _v=variant):
                return render_html(m_isl, d_isl, variant=_v, run_id=run_id, built_at=built_at, assets=assets)
            html, trimmed = fit_html(_with_analysis_time(vm, analyzed_at, chosen), drill, cap, render)
            if trimmed:
                res.trimmed[variant] = trimmed
            if len(html.encode("utf-8")) > cap:
                res.warnings.append({"code": "html_over_cap", "path": FILE_NAMES[(variant, "html")]})
            write(FILE_NAMES[(variant, "html")], html.encode("utf-8"), variant, "html")
    man = {"schema": "lm27.export/1", "run_id": run_id, "report_version": str((model.get("generator") or {})
                                                                               .get("report_version", "report/1")),
           "built_at": built_at, "files": sorted(res.files, key=lambda f: f["path"])}
    try:
        fsx.atomic_write(target("manifest.json"), fsx.canon_bytes(man))
    except OSError as e:
        res.failed.append({"path": "manifest.json", "variant": "", "format": "json", "reason": type(e).__name__})
    if not out_dir:
        res.pruned = prune_exports(os.path.dirname(base), int(cfg["report.export.keep"]), protect=(base,))
    res.rc = 1 if res.failed else 0
    return res


HIDDEN_TITLE_MIN = 8          # 가린 원래 제목을 검사 바늘로 쓸 최소 글자 수(공백 제외 — 짧은 낱말이 다른 글과 엇갈리지 않게)


def hidden_titles(full: Mapping, red: Mapping) -> list[str]:
    """가림판에서 일반 제목으로 바꾼 단위업무(`title_mode=generic`)의 원래 제목 — 가림판 검사(G-R8)의 추가 바늘. 원래 제목이
    가림판 어디에든 남으면(리뷰 AI 문장 등) 가림판을 만들지 않는다(fail-closed — W2 검토 C13)."""
    gen = {u.get("unit_id") for u in red.get("units") or () if u.get("title_mode") == "generic"}
    out = set()
    for u in full.get("units") or ():
        t = " ".join(str(u.get("title") or "").split())
        if u.get("unit_id") in gen and len(t.replace(" ", "")) >= HIDDEN_TITLE_MIN:
            out.add(t)
    return sorted(out)


def _with_analysis_time(vm: Mapping, analyzed_at: str | None, chosen: str | None = None) -> Mapping:
    """자기완결 HTML 섬의 모델에만 ``run.built_at``(그 실행의 분석 시각 — 머리 띠 '분석 MM-DD HH:MM')과 ``run.chosen``
    (지금 화면 결과일 때만 '자동/직접 선택' — `inputs.chosen_of`)을 덧붙인 얕은 사본. 모델 파일·JSON 내보내기는 그대로다
    (G-R1 — current.json 은 보고서 입력이 아니다, W2 검토 C01)."""
    run = dict(vm.get("run") or {})
    add = {}
    if analyzed_at and not run.get("built_at"):
        add["built_at"] = analyzed_at
    if chosen in ("auto", "explicit") and not run.get("chosen"):
        add["chosen"] = chosen
    if not add:
        return vm
    run.update(add)
    return {**vm, "run": run}


class _ExportModule(types.ModuleType):
    """`lm27.report.export` 는 하위 모듈 이름과 공개 함수 이름이 같다(R §2.2 재수출). 하위 모듈을 import 하면 패키지 속성이
    이 모듈로 바뀌므로, 모듈 객체를 불러도 같은 `export(...)` 가 돌게 한다."""

    def __call__(self, *a, **kw):
        return export(*a, **kw)


sys.modules[__name__].__class__ = _ExportModule

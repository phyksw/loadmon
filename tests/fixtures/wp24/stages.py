# -*- coding: utf-8 -*-
"""시험 전용 단계(G-B4 '시험 전용 단계로') — B §8.0.2 한눈표의 모양(묶음 크기·답 추정·반분·채팅 정책)을 흉내 낸다.

실제 단계 11종(WP-25)과 이름이 겹치지 않게 ``t_`` 접두를 쓴다. 조회형만 능력 기록 시험을 위해 ``lookup_mail``·
``lookup_teams`` id 를 쓴다. 문구는 B §8 예시를 줄인 것 — 사람 이름·주소·시간 수치 없음.
"""
from __future__ import annotations

import re
from datetime import date, timedelta
from types import SimpleNamespace

from lm27.bridge.stages.base import F, StageSpec

ACTS = ("request", "ack", "question", "report", "info", "social", "notice")


class ActStage(StageSpec):
    """speech_act 모양 — 분류형, 빠른 모델, 이어 쓰는 채팅, 묶음 40."""
    id = "t_act"
    title_ko = "화행 분류"
    prompt_ver = "t_act/1.0"
    kind = "items"
    model_class = "fast"
    chat_policy = "continue"
    max_items = 40
    min_split = 0
    est_out_per_item = 45
    send_fields = ("ch", "dir", "chat", "prev", "text")
    text_fields = ("text",)
    content_key_fields = ("ch", "dir", "chat", "text")
    item_schema = (F("act", "enum", enum=ACTS), F("conf", "enum", enum=("h", "m", "l")))
    stub = {"act": "info", "conf": "m"}

    def header(self, ctx, compact=False):
        return ("당신은 업무 메시지의 말하기 의도(화행)를 분류합니다. 각 메시지를 읽고 아래 7가지 중 하나를 고르세요.\n"
                "- request : 나에게 일을 맡기거나 요청함\n- ack : 요청을 받아들이거나 확인함\n"
                "- question : 정보를 묻지만 일을 맡기지는 않음\n- report : 결과·완료·공유를 알림\n"
                "- info : 그 밖의 업무 대화\n- social : 인사·감사 등\n- notice : 여러 사람에게 보내는 공지\n"
                "규칙: 메시지에 쓰인 것만 보고 판단합니다.")

    def columns(self):
        return "[항목] 번호 | 채널 | 방향 | 대화 | 앞 화행 | 내용"

    def item_line(self, it, n):
        f = it.fields
        return f"{n} | {f.get('ch', '')} | {f.get('dir', '')} | {f.get('chat', '')} | {f.get('prev', '-')} | " \
               f"{f.get('text', '')}"

    def format_line(self):
        return ('{"rid": <요청번호>, "n": <항목 수>, "items": [ {"id": <번호>, "act": <request|ack|question|report|info|'
                'social|notice>, "conf": <h|m|l>} ]}')

    def unknown_rule(self):
        return "act 는 info, conf 는 l 로 씁니다"

    def shrink(self, it, max_chars):
        nf = dict(it.fields)
        nf["text"] = str(nf.get("text", ""))[:60]
        return nf if len(self.item_line(SimpleNamespace(fields=nf), 99)) <= max_chars else None

    def fallback(self, it, ctx, why):
        a = (it.rule or {}).get("act")
        return {"act": a if a in ACTS else "info", "conf": "l"}


class LabelStage(StageSpec):
    """task_label 모양 — 레지스트리 코드 고르기, 이름 필드(앞서 쓴 이름·겹침), 상대 도메인은 웹 노출이면 보내지 않음."""
    id = "t_label"
    title_ko = "단위업무 이름·과제 고르기"
    prompt_ver = "t_label/1.0"
    kind = "items"
    model_class = "fast"
    chat_policy = "continue"
    max_items = 30
    min_split = 5
    est_out_per_item = 120
    est_out_fixed = 80
    send_fields = ("kinds", "subjects", "files", "apps", "domains", "cands")
    text_fields = ("subjects", "files", "apps", "domains")
    web_drop_fields = ("domains",)
    content_key_fields = ("kinds", "subjects", "files", "apps", "domains")
    uses_registry = True
    names_field = "title"
    item_schema = (F("project", "code", codes="projects", extra_codes=("NONE", "NEW")),
                   F("field", "code", codes="vocab.field"), F("func", "code", codes="vocab.func"),
                   F("title", "str", min_len=2, max_len=30, hard_max=80), F("new", "str", required=False, max_len=20),
                   F("conf", "enum", enum=("h", "m", "l")))
    stub = {"project": "NONE", "field": "ETC", "func": "ETC", "title": "공통 업무", "new": "", "conf": "m"}

    def header(self, ctx, compact=False):
        projects = sorted(ctx.codes("projects") or ()) if ctx is not None else []
        if compact:
            projects = projects[:5]
        descs = ((ctx.data or {}).get("desc") or {}) if ctx is not None else {}
        lines = ["당신은 업무 흔적 묶음을 팀 과제 목록에 맞춰 분류합니다.",
                 "- project : [과제 목록]의 코드 하나. 공통 업무면 NONE, 새 과제가 분명하면 NEW.",
                 "- field·func : 목록의 코드 하나 / title : 짧은 이름(명사구)",
                 "[과제 목록] 코드 · 설명"]
        lines += [f"{p} · {descs.get(p, '설명 없음')}" for p in projects]
        lines.append("[분야] " + " · ".join(sorted(ctx.codes("vocab.field") or ())) if ctx is not None else "")
        return "\n".join(x for x in lines if x)

    def columns(self):
        return "[항목] 번호 | 흔적 | 제목 요지 | 파일 | 앱 | 상대 | 후보"

    def item_line(self, it, n):
        f = it.fields
        cands = ", ".join(f"{p} {s:.2f}" for p, s in (f.get("cands") or []))
        return " | ".join([str(n), str(f.get("kinds", "")), " / ".join(f.get("subjects") or []),
                           ", ".join(f.get("files") or []), ", ".join(f.get("apps") or []),
                           ", ".join(f.get("domains") or []), cands])

    def format_line(self):
        return ('{"rid": <요청번호>, "n": <항목 수>, "items": [ {"id": <번호>, "project": <코드|NONE|NEW>, '
                '"field": <분야 코드>, "func": <기능 코드>, "title": <짧은 이름>, "new": <새 과제명 또는 "">, '
                '"conf": <h|m|l>} ]}')     # B §8.3 의 '이름 또는' 은 정제기 이름 탐지에 걸린다(완료 보고 CR)

    def unknown_rule(self):
        return "project 는 NONE, conf 는 l 로 씁니다"

    def validate(self, ans, it, ctx):
        if ans.get("project") == "NEW" and len(str(ans.get("new") or "")) < 2:
            return "missing:new"
        return ""

    def shrink(self, it, max_chars):
        nf = dict(it.fields)
        nf["subjects"] = list(nf.get("subjects") or [])[:1]
        nf["files"] = list(nf.get("files") or [])[:2]
        nf["domains"] = []
        return nf

    def fallback(self, it, ctx, why):
        r = it.rule or {}
        return {"project": r.get("project") or "NONE", "field": r.get("field") or "ETC", "func": r.get("func") or "ETC",
                "title": r.get("title") or "미분류 업무", "new": "", "conf": "l"}


class FlowStage(StageSpec):
    """workflow_label 모양 — 생성형, 깊은 모델, 묶음 6, 같은 과제끼리(group_strict), 답 추정 = 200 + 110 × 단계 수."""
    id = "t_flow"
    title_ko = "워크플로우 단계 라벨 붙이기"      # B §8.4 '이름 붙이기' 는 정제기 이름 탐지에 걸린다(완료 보고 CR)
    prompt_ver = "t_flow/1.0"
    model_class = "deep"
    max_items = 6
    min_split = 1
    est_out_per_item = 200
    group_strict = True
    send_fields = ("project", "func", "steps", "tasks")
    text_fields = ("tasks",)
    item_schema = (F("role", "str", max_len=40, hard_max=120), F("summary", "str", max_len=160, hard_max=400),
                   F("steps", "list", max_items=8, item=(F("s", "str", pattern=r"S\d{1,2}"),
                                                         F("label", "str", max_len=20, hard_max=60))))
    stub = {"role": "판단 유보", "summary": "흐름 요약", "steps": [{"s": "S1", "label": "의뢰 접수"}]}

    def header(self, ctx, compact=False):
        return ("당신은 업무 프로세스 분석가입니다. 각 항목은 역할 업무 하나의 단계 순서입니다.\n"
                "항목마다 role·summary 와 단계 코드마다 label 을 씁니다. 주어진 코드만 씁니다.")

    def columns(self):
        return "[항목] 번호 | 과제·기능 | 단계 | 단위업무 예"

    def item_line(self, it, n):
        f = it.fields
        steps = " → ".join(f"{s} {t}" for s, t in (f.get("steps") or []))
        return f"{n} | {f.get('project', '')} · {f.get('func', '')} | {steps} | " + " / ".join(f.get("tasks") or [])

    def format_line(self):
        return ('{"rid": <요청번호>, "n": <항목 수>, "items": [ {"id": <번호>, "role": <한 줄>, "summary": <요약>, '
                '"steps": [ {"s": <단계 코드>, "label": <단계 이름>} ]} ]}')

    def unknown_rule(self):
        return 'role 은 "판단 유보" 로 씁니다'

    def est_out(self, it):
        return 200 + 110 * len(it.fields.get("steps") or [])

    def key_material(self, fields):
        return {"project": fields.get("project"), "func": fields.get("func"),
                "steps_types": [[s, t] for s, t in (fields.get("steps") or [])], "tasks": fields.get("tasks")}

    def fallback(self, it, ctx, why):
        return {"role": "판단 유보", "summary": "", "steps": [{"s": s, "label": t}
                                                         for s, t in (it.fields.get("steps") or [])]}


class ReviewStage(StageSpec):
    """review_text 모양 — 단건형(반분 없음), 질의마다 새 채팅."""
    id = "t_review"
    title_ko = "주간 리뷰 문장"
    prompt_ver = "t_review/1.0"
    kind = "single"
    model_class = "deep"
    chat_policy = "fresh_each"
    max_items = 1
    est_out_per_item = 1200
    send_fields = ("kind", "period", "facts")
    text_fields = ()
    item_schema = (F("summary", "str", max_len=300, hard_max=800),
                   F("next", "list", required=False, max_items=3))
    stub = {"summary": "이번 기간 요약", "next": []}

    def header(self, ctx, compact=False):
        return "당신은 한 엔지니어의 주간 업무 리뷰를 씁니다. [사실 목록]에 있는 사실만 씁니다."

    def columns(self):
        return "[항목] 번호 | 기간"

    def item_line(self, it, n):
        facts = " / ".join(f"{a} {b}" for a, b in (it.fields.get("facts") or []))
        return f"{n} | {it.fields.get('period', '')} | {facts}"

    def format_line(self):
        return '{"rid": <요청번호>, "n": 1, "items": [ {"id": 1, "summary": <요약>, "next": [<문장>]} ]}'

    def unknown_rule(self):
        return "summary 를 짧게 씁니다"

    def fallback(self, it, ctx, why):
        return {"summary": "규칙 요약", "next": []}


class AgentStage(StageSpec):
    """agentic_match 모양 — 카탈로그 코드, 목록 안 객체, null 허용 객체."""
    id = "t_agent"
    title_ko = "에이전트 매칭"
    prompt_ver = "t_agent/1.0"
    model_class = "deep"
    max_items = 15
    min_split = 5
    est_out_per_item = 260
    send_fields = ("type", "label", "freq")
    text_fields = ("label",)
    item_schema = (F("m", "list", max_items=3, item=(F("a", "code", codes="catalog"),
                                                     F("fit", "enum", enum=("상", "중", "하")),
                                                     F("why", "str", max_len=40, hard_max=120))),
                   F("need", "nullable_obj", item=(F("name", "str", max_len=20, min_len=2),
                                                   F("logic", "str", max_len=80))))
    stub = {"m": [], "need": None}

    def header(self, ctx, compact=False):
        cat = sorted(ctx.codes("catalog") or ()) if ctx is not None else []
        return "[에이전트 목록] " + " · ".join(cat)

    def columns(self):
        return "[항목] 번호 | 단계 유형 | 대표 라벨 | 빈도"

    def format_line(self):
        return ('{"rid": <요청번호>, "n": <항목 수>, "items": [ {"id": <번호>, "m": [ {"a": <에이전트 코드>, '
                '"fit": <상|중|하>, "why": <근거>} ], "need": <null 또는 {"name": <이름>, "logic": <로직>}>} ]}')

    def unknown_rule(self):
        return "m 은 빈 목록, need 는 null 로 씁니다"

    def fallback(self, it, ctx, why):
        return {"m": [], "need": None}


class SubStage(StageSpec):
    """subagent_review 모양 — 생성형, 묶음 5, 답 추정 600."""
    id = "t_sub"
    title_ko = "서브에이전트 도입 검토"
    prompt_ver = "t_sub/1.0"
    model_class = "deep"
    max_items = 5
    min_split = 1
    est_out_per_item = 600
    send_fields = ("project", "role", "steps")
    text_fields = ("role",)
    item_schema = (F("verdict", "enum", enum=("적합", "부분", "부적합")), F("risk", "str", max_len=80, hard_max=200))
    stub = {"verdict": "부분", "risk": "사람 검토 필요"}

    def header(self, ctx, compact=False):
        return "당신은 업무 흐름에 AI 서브에이전트를 넣을 수 있는지 검토합니다."

    def columns(self):
        return "[항목] 번호 | 과제 · 역할 | 단계"

    def item_line(self, it, n):
        f = it.fields
        return f"{n} | {f.get('project', '')} · {f.get('role', '')} | " + " → ".join(f.get("steps") or [])

    def format_line(self):
        return ('{"rid": <요청번호>, "n": <항목 수>, "items": [ {"id": <번호>, "verdict": <적합|부분|부적합>, '
                '"risk": <주의점>} ]}')

    def unknown_rule(self):
        return "verdict 는 부분 으로 씁니다"

    def fallback(self, it, ctx, why):
        return {"verdict": "부분", "risk": "규칙 판정"}


_T_RX = re.compile(r"^(\d{4}-\d{2}-\d{2})( \d{1,2}:\d{2})?$")


class LookupStage(StageSpec):
    """조회형 모양(B §8.1) — 구간 1개 = 항목 1개, 행 검사(날짜만 남김·구간 밖 버림), 가득 차면 구간 쪼개기."""
    id = "lookup_mail"
    title_ko = "메일 조회"
    prompt_ver = "lookup_mail/1.0"
    kind = "lookup"
    chat_policy = "fresh_each"
    want_work_mode = True
    max_items = 1
    est_out_per_item = 130
    allow_time = True
    send_fields = ("d0", "d1")
    text_fields = ()
    item_schema = (F("t", "str"), F("d", "enum", enum=("in", "out")), F("who", "str", required=False),
                   F("s", "str", required=False, max_len=60))
    stub = {"t": "2026-09-01", "d": "in", "who": "-", "s": "업무 메일"}

    def title_line(self, rid, n, batch, ctx):
        f = batch[0].fields if batch else {}
        return f"[LM27 요청 {rid} · {self.title_ko} · 구간 {f.get('d0', '')}~{f.get('d1', '')}]"

    def header(self, ctx, compact=False):
        return ("내 Outlook 메일에서 주어진 기간(양 끝 포함)에 주고받은 업무 메일을 검색해 주세요.\n"
                "규칙:\n- 실제로 검색된 메일만 씁니다.\n- 날짜만 씁니다. 시각은 쓰지 않습니다.")

    def columns(self):
        return ""

    def format_line(self):
        return ('{"rid": <요청번호>, "n": <쓴 행 수>, "more": <true|false>, "items": [ {"id": <1부터>, '
                '"t": <"YYYY-MM-DD">, "d": <"in"|"out">, "who": <상대 도메인 또는 "-">, "s": <제목 요지>} ]}')

    def unknown_rule(self):
        return "이 기간에 메일이 정말 없으면 items 를 빈 목록, n 을 0 으로 씁니다"

    def rephrase(self):
        return "내 Outlook 메일에서 이 기간의 업무 메일을 검색해서, 찾은 것만 아래 형식으로 정리해 주세요."

    def normalize_row(self, row, it, ctx):
        m = _T_RX.match(str(row.get("t") or ""))
        if not m:
            return None, ("bad_time",)
        codes = ("time_dropped",) if m.group(2) else ()
        d = m.group(1)
        if it is not None and not (it.fields.get("d0", "") <= d <= it.fields.get("d1", "")):
            return None, ("out_of_window",)
        return dict(row, t=d), codes

    def max_rows(self, ctx):
        cfg = ctx.cfg
        return min(cfg.lookup.max_rows, max(1, (int(ctx.pack_out or cfg.answer_max_chars) - 200) // 130))

    def is_full(self, ans, status, ctx):
        if status == "truncated" or (isinstance(ans, dict) and ans.get("more") is True):
            return True
        n = len((ans or {}).get("rows") or [])
        return n >= int(self.max_rows(ctx) * ctx.cfg.lookup.full_ratio)

    def split(self, it, ctx):
        d0, d1 = date.fromisoformat(it.fields["d0"]), date.fromisoformat(it.fields["d1"])
        days = (d1 - d0).days + 1
        if days <= ctx.cfg.lookup.min_window_days:
            return None
        mid = d0 + timedelta(days=days // 2 - 1 if days > 1 else 0)
        out = []
        for a, b in ((d0, mid), (mid + timedelta(days=1), d1)):
            out.append({"key": f"{self.id}:{a.isoformat()}:{b.isoformat()}",
                        "fields": {"d0": a.isoformat(), "d1": b.isoformat()}})
        return out


class LookupTeams(LookupStage):
    id = "lookup_teams"
    title_ko = "팀즈 조회"
    prompt_ver = "lookup_teams/1.0"


ALL = (ActStage, LabelStage, FlowStage, ReviewStage, AgentStage, SubStage, LookupStage)

# -*- coding: utf-8 -*-
r"""``taxonomy_bootstrap`` — 레지스트리가 빈 초기의 과제 체계 제안 1회차(**H §8.2 ``taxonomy_bootstrap/1.0``** · H X6 ·
계약 X-253). 결과는 제안 큐로만 간다(``lm27.hier.bootstrap.apply_bootstrap`` — 과제를 만들지 않는다, H-I6).

ai_in(H §8.2 — ``lm27.hier.copilot_io.build_bootstrap_samples``): 표본 1줄 = 항목 1개 ``{key: grp:…, fields{dom, title,
files, subject, peer}, rule{title, domain}}``. 상류가 입력 예산에 맞춰 줄 수를 고른다(``copilot_io.fit_lines``) — 한
질의에 표본 전부(``max_items`` = ``hier.bootstrap.maxLines`` 기본값)를 싣는다.

**단건형 행 봉투**(``kind="single"``, ``row_envelope=True`` — H X6 · X-253): 답의 ``items`` 는 입력 항목에 대한 답이 아니라
제안 과제 행이다 ``{name, code, dom, kind, match[], obs[]}``(``obs`` = 근거 [표본] 번호). 검증은 조회형과 같은 행 규칙
(``n == len(items)``, 행마다 ``normalize_row``, 전체 ``normalize`` — 이름 ukey 중복은 뒤의 것 버림, ``max_models`` 초과 행은
버리고 셈)에 웹 검색 금지 줄을 더한다. 접은 답 = ``{"rows": [...], "n": 행 수, "more": false}``.

L2·L3(WP-24)가 단건형 행 봉투를 아직 모르면(항목형 검증으로 행 번호를 표본 번호에 잘못 맞춘다) ``validate`` 가 그 경로의
답을 모두 무효(``bad_type:rows``)로 돌려 잘못된 커밋을 막는다 — 몇 번 묻고 규칙 커밋(빈 제안)으로 끝난다(완료 보고 CR).

문구(H §8.2 실물): 정제기가 '이름 조각'·'이름 하나로' 를 사람 이름으로 잡는 두 줄만 같은 뜻으로 바꿨다(완료 보고 CR).
"""
from __future__ import annotations

import re
from types import SimpleNamespace

from lm27.bridge.stages import (as_text, current_batch, cut, fields_of, has_effective, registry_of, remember_batch,
                                str_list)
from lm27.bridge.stages.base import F, StageSpec, registry_codes

__all__ = ["BOOT_MAX_MODELS", "TaxonomyBootstrap"]

BOOT_MAX_MODELS = 15              # hier.bootstrap.maxModels 기본값(H §8.2 '과제는 많아야 15개')
BOOT_MAX_LINES = 100              # hier.bootstrap.maxLines 기본값(표본 상한 — 한 질의)
ROW_OUT = 150                     # 행당 답 추정(H §8.2)
NAME_MAX = 20
MATCH_MAX = 5
MATCH_LEN = 20
OBS_MAX = 5
DOMAINS = ("DEV", "MP", "EXT", "COM", "AX")
KINDS = ("project", "common", "nonwork")
_MONEY_RX = re.compile(r"\d[\d,]*\s?(?:원|만원|억|달러|USD|KRW)")

BOOT_TITLE_TEMPLATE = "[LM27 요청 {rid} · 과제 체계 제안 · 표본 {n}줄]"
BOOT_HEAD_TEMPLATE = (
    "당신은 한 엔지니어의 업무 흔적을 팀 과제 체계로 정리하는 설계자입니다. 아래 [표본]은 이 사람의 단위업무 묶음을 투입이 큰 "
    "순서로 고른 것입니다.",
    "이 사람의 업무를 묶는 '상위 과제' 목록을 제안하세요.",
    "규칙(계층 규율):",
    "- 과제는 제품·프로젝트·과제 코드·고객 대응 건처럼 여러 업무를 묶는 상위 대상만입니다.",
    "- 'OO 설계'·'OO 보고서 작성'·'OO 검토' 같은 활동 이름은 과제가 아닙니다. 그 활동이 속한 상위 과제를 세우고 활동은 쓰지 "
    "않습니다.",
    "- 파일명 조각·코드 모듈명·확장자·날짜·버전은 과제가 아닙니다. 한 도구의 여러 부품은 그 도구명 하나로 묶습니다.",
    "- 같은 대상의 표기 변형(띄어쓰기·대소문자·한영·약칭)은 한 가지 표기로 씁니다. 괄호 꼬리((양산)·(선행))나 차수 숫자가 "
    "다르면 따로 씁니다.",
    "- 과제가 아닌 팀 운영·사무는 kind 를 common 으로, 업무가 아닌 것은 nonwork 로 씁니다.",
    "- 과제마다 업무영역 dom 을 [업무영역] 코드 하나로 고릅니다.",
    "- [이미 있는 과제]와 같은 대상이면 새로 만들지 말고 그 코드를 code 에 씁니다(이름은 비워도 됩니다).",
    "- obs 에는 근거가 된 [표본] 번호를 최대 5개, match 에는 그 과제를 알아볼 낱말을 최대 5개(각 20자 이내) 씁니다.",
    "- 과제는 많아야 {max_models}개입니다. [표본]에 흔적이 없는 것은 넣지 않습니다.",
)
BOOT_COLUMNS_PROMPT = "[표본] 번호 | 영역후보 | 이름안 | 파일 | 제목 요지 | 상대"
BOOT_FORMAT_PROMPT = ('{"rid": <요청번호>, "n": <과제 수>, "items": [ {"id": <1부터>, "name": <과제 이름 20자 이내>, '
                      '"code": <이미 있는 과제 코드 또는 "">, "dom": <업무영역 코드>, "kind": <project|common|nonwork>, '
                      '"match": [<낱말>], "obs": [<표본 번호>]} ]}')
BOOT_UNKNOWN_PROMPT = "그 과제를 빼고 씁니다"
BOOT_EXISTING_PROMPT = "[이미 있는 과제] 코드 · 업무영역 · 설명"
BOOT_NONE_PROMPT = "(없음)"


class TaxonomyBootstrap(StageSpec):
    id = "taxonomy_bootstrap"
    title_ko = "과제 체계 제안"
    prompt_ver = "taxonomy_bootstrap/1.0"
    schema_major = 1
    kind = "single"
    row_envelope = True               # 단건형 행 봉투(H X6 · X-253) — L2 가 행 규칙으로 검증한다
    allow_time = False
    model_class = "deep"
    chat_policy = "fresh_each"
    max_items = BOOT_MAX_LINES
    est_out_per_item = 0              # 답 크기는 표본 수와 무관 — 묶음당 고정분
    est_out_fixed = ROW_OUT * BOOT_MAX_MODELS + 80
    group_strict = False
    send_fields = ("dom", "title", "files", "subject", "peer")
    text_fields = ("title", "files", "subject", "peer")
    content_key_fields = ("dom", "title", "files", "subject", "peer")
    names_field = ""
    uses_registry = True
    max_models = BOOT_MAX_MODELS
    item_schema = (F("name", "str", required=False, max_len=NAME_MAX, hard_max=80),
                   F("code", "code", required=False, codes="projects_nonreserved", extra_codes=("",)),
                   F("dom", "enum", enum=DOMAINS),
                   F("kind", "enum", enum=KINDS),
                   F("match", "list", required=False, max_items=MATCH_MAX),
                   F("obs", "list", required=False, max_items=OBS_MAX))
    stub = {"name": "팀 운영 사무", "code": "", "dom": "COM", "kind": "common", "match": ["운영"], "obs": [1]}

    # ── 프롬프트(H §8.2 실물) ──
    def title_line(self, rid, n, batch, ctx) -> str:
        remember_batch(self, ctx, batch)
        return BOOT_TITLE_TEMPLATE.format(rid=rid, n=n)

    def header(self, ctx, compact: bool = False) -> str:
        lines = [t.format(max_models=self.max_models) for t in BOOT_HEAD_TEMPLATE]
        return "\n".join(lines + self.context_lines(registry_of(ctx)))

    @staticmethod
    def context_lines(reg) -> list[str]:
        """[업무영역]·[이미 있는 과제](개인 과제 포함, 없으면 '(없음)') — ``copilot_io.prompt_context`` 한 벌."""
        if has_effective(reg):
            from lm27.hier.copilot_io import prompt_context
            return list(prompt_context(reg, "taxonomy_bootstrap"))
        from lm27.hier import vocab as V
        ids = sorted(c for c in registry_codes(reg).get("projects", frozenset()) if c not in V.RESERVED)
        return [V.domain_prompt_line(), BOOT_EXISTING_PROMPT] + ([f"{p} · - · (설명 없음)" for p in ids]
                                                                  or [BOOT_NONE_PROMPT])

    def columns(self) -> str:
        return BOOT_COLUMNS_PROMPT

    def item_line(self, it, n) -> str:
        f = fields_of(it)
        return " | ".join([str(n), as_text(f.get("dom")) or "-", as_text(f.get("title")) or "-",
                           ", ".join(str_list(f.get("files"))) or "-", as_text(f.get("subject")) or "-",
                           as_text(f.get("peer")) or "-"])

    def format_line(self) -> str:
        return BOOT_FORMAT_PROMPT

    def unknown_rule(self) -> str:
        return BOOT_UNKNOWN_PROMPT

    def shrink(self, it, max_chars: int):
        """표본 줄이 예산보다 크면 파일 1개 → 제목 요지 30자 → 그래도 크면 None."""
        nf = fields_of(it)
        nf["files"] = str_list(nf.get("files"))[:1]
        if len(self.item_line(SimpleNamespace(fields=nf), 99)) <= max_chars:
            return nf
        nf["subject"] = cut(nf.get("subject"), 30)
        return nf if len(self.item_line(SimpleNamespace(fields=nf), 99)) <= max_chars else None

    # ── 검증(H §8.2 행 스키마) ──
    def code_sets(self, ctx) -> dict:
        reg = registry_of(ctx)
        if has_effective(reg):
            from lm27.hier.copilot_io import codes_for
            return {k: frozenset(v) for k, v in codes_for(reg).items()}
        from lm27.hier import vocab as V
        out = dict(registry_codes(reg))
        out["projects_nonreserved"] = frozenset(c for c in out.get("projects", frozenset()) if c not in V.RESERVED)
        return out

    def validate(self, ans: dict, it, ctx) -> str:
        """항목형 검증으로 불렸다(행 봉투를 모르는 L2) — 행을 표본에 잘못 맞춘 커밋을 막는다."""
        if isinstance(ans, dict) and isinstance(ans.get("rows"), list):
            return ""
        return "bad_type:rows"

    def normalize_row(self, row: dict, it, ctx):
        """행 하나(H §8.2 validate): code 가 없으면 이름 2자 이상, 이름에 금액·사람 토큰이 있으면 무효, match 각 20자, obs 는
        정수만(범위 1~표본 줄 수는 전체 ``normalize`` 가 이 질의의 묶음으로 자른다)."""
        out = dict(row)
        name = as_text(out.get("name"))
        code = as_text(out.get("code"))
        out["code"] = code
        out["name"] = cut(name, NAME_MAX)
        if not code and len(name) < 2:
            return None, ("bad_name",)
        if _MONEY_RX.search(name) or "[사람" in name:
            return None, ("bad_name",)
        out["match"] = [cut(w, MATCH_LEN) for w in str_list(out.get("match"))][:MATCH_MAX]
        obs = []
        for x in out.get("obs") or ():
            try:
                v = int(x)
            except (TypeError, ValueError):
                continue
            if v >= 1 and v not in obs:
                obs.append(v)
        out["obs"] = obs[:OBS_MAX]
        return out, ()

    def normalize(self, ans: dict, it, ctx) -> dict:
        """행 봉투 전체 — 이름 ukey 중복은 뒤의 것 버림, ``max_models`` 를 넘는 행은 버림(``dropped`` 셈은 L2 몫)."""
        rows = ans.get("rows") if isinstance(ans, dict) and isinstance(ans.get("rows"), list) else []
        from lm27.hier.names import ukey
        n_samples = len(current_batch(self, ctx))
        seen, out = set(), []
        for r in rows:
            if not isinstance(r, dict):
                continue
            k = ukey(as_text(r.get("name"))) if as_text(r.get("name")) else "code:" + as_text(r.get("code"))
            if k in seen:
                continue
            seen.add(k)
            if n_samples:
                r = dict(r, obs=[x for x in r.get("obs") or () if isinstance(x, int) and 1 <= x <= n_samples])
            out.append(r)
        capped = len(out) > self.max_models
        res = {"rows": out[:self.max_models], "n": len(out[:self.max_models]), "more": False}
        if capped:
            res["capped"] = True
        return res

    def fallback(self, it, ctx, why: str = "") -> dict:
        """규칙으로는 과제 체계를 제안하지 않는다 — 빈 제안(H §8.4: 제안은 사람이 확인)."""
        return {"rows": [], "n": 0, "more": False}

# -*- coding: utf-8 -*-
r"""설정 › 개인정보 API(PRIVACY §15.5 · R §5.6.3) — 정제 감사 표·정제 시험대(메모리만)·광고 의심 큐.

    GET  /api/privacy/audit?from&to         기간·출처별 가린 범주 건수·버린 행 사유·사적·광고 판정·키 없음(privacy_audit 합계)
    POST /api/privacy/testbench {text}      정제 전후 비교와 걸린 범주 — **저장·로그 없음**(메모리에서만, 응답에만)
    GET  /api/privacy/ad-suspects           광고 의심 큐(정제 제목 + 건수)
    POST /api/privacy/ad-decision {id, decision: block|allow}

- 감사 이벤트는 건수·범주 코드·경로 ID 뿐이다(P §15.2 — 원문·정제문·예시 0). 화면도 그 값만 보인다.
- 시험대 입력 원문은 이 처리기 지역 변수로만 다루고 끝나면 버린다(요청 로그는 메서드·경로·상태만 — server).
- 광고 결정은 ``data\local_only\ad_lists.json``(로컬 전용 — 반출 금지)의 ``block_senders``·``allow_senders``(보낸 사람 키
  w+16hex — 정제기 ``RecordContext.ad_lists`` 가 읽는 형)에만 남긴다. 다음 [수집]부터 정제기가 반영한다.
"""
from __future__ import annotations

import re
from datetime import date, timedelta

from lm27.ui.server import ApiError

__all__ = ["ROUTES"]

CATEGORY_KO = {"money": "금액", "phone": "전화", "email": "이메일", "person": "사람", "path": "경로", "url": "URL",
               "rrn": "주민번호", "card": "카드", "account": "계좌", "ip": "IP", "customer": "고객사", "partner": "협력사",
               "project": "과제", "biz": "사업자번호", "corp": "법인번호", "passport": "여권", "license": "운전면허",
               "birth": "생년월일", "ratio": "비율", "company": "회사", "self": "나", "frn": "외국인등록번호"}
AUDIT_DAYS_MAX = 400
TESTBENCH_MAX = 4000
AD_FILE = "ad_lists.json"
_WKEY_RX = re.compile(r"^w[0-9a-f]{16}$")


def _ym(ts) -> str:
    return str(ts or "")[:7]


def get_audit(app, req):
    from lm27.bundle import loader
    today = app.deps.now().date()
    try:
        d1 = date.fromisoformat(req.q("to", today.isoformat()))
        d0 = date.fromisoformat(req.q("from", (d1 - timedelta(days=89)).isoformat()))
    except ValueError:
        raise ApiError(400, "bad_date", "날짜는 YYYY-MM-DD 입니다") from None
    if d1 < d0 or (d1 - d0).days + 1 > AUDIT_DAYS_MAX:
        raise ApiError(400, "bad_range", f"기간은 최대 {AUDIT_DAYS_MAX}일입니다")
    agg: dict = {}
    keyless = 0
    try:
        rows = loader.iter_records(app.paths, "privacy_audit", d0, d1, cfg=app.cfg())
        for ev in rows:
            if not isinstance(ev, dict):
                continue
            per, src = _ym(ev.get("ts_utc")), str(ev.get("path_id") or ev.get("stage") or "")
            for part in ("masked", "dropped", "priv", "ad"):
                d = ev.get(part)
                if not isinstance(d, dict):
                    continue
                for cat, n in d.items():
                    if not isinstance(n, int) or isinstance(n, bool):
                        continue
                    k = (per, src, part, str(cat))
                    agg[k] = agg.get(k, 0) + n
            err = ev.get("err") if isinstance(ev.get("err"), dict) else {}
            keyless += sum(int(v) for k, v in err.items() if "no_key" in str(k) and isinstance(v, int))
    except (OSError, ValueError):
        pass
    out = [{"period": p, "src": s, "part": part, "category": c, "category_ko": CATEGORY_KO.get(c, c), "n": n}
           for (p, s, part, c), n in sorted(agg.items())]
    return {"rows": out[:2000], "no_key": keyless, "from": d0.isoformat(), "to": d1.isoformat()}


def post_testbench(app, req):
    text = req.body.get("text")
    if not isinstance(text, str) or not text.strip():
        raise ApiError(400, "no_text", "시험할 글을 넣어 주세요")
    if len(text) > TESTBENCH_MAX:
        raise ApiError(413, "too_long", f"{TESTBENCH_MAX}자 이하로 넣어 주세요")
    from lm27.privacy import SanitizeContext
    from lm27.privacy import sanitize as P
    ctx = _context(app) or SanitizeContext()
    res = P.sanitize(text, "text", ctx)
    hits = {str(k): int(v) for k, v in (res.hits or {}).items() if isinstance(v, int)}
    return {"ok": True, "after": "" if res.drop else res.text, "dropped": bool(res.drop),
            "drop_reason": res.drop_reason, "hits": [{"category": k, "category_ko": CATEGORY_KO.get(k, k), "n": n}
                                                     for k, n in sorted(hits.items())],
            "rules_ver": res.rules_ver}


def _context(app):
    """이 PC 의 정제 문맥(레지스트리 사전·설정). 만들지 못하면 None(기본 규칙만으로 정제)."""
    try:
        from lm27.privacy import build_context
        from lm27.ui.api_team import registry_view
        reg, _st = registry_view(app)
        return build_context(app.cfg(), reg.privacy_dict() if reg is not None else {}, None, None)
    except Exception:                                    # 키링·로컬 사전이 없음 — 기본 규칙
        return None


def _ad_lists(app) -> dict:
    from lm27.util import fsx
    obj = fsx.read_json(app.paths.local_only_file(AD_FILE), None, want=dict) or {}
    return obj if isinstance(obj, dict) else {}


def get_ad_suspects(app, req):
    """광고 의심 큐 — 최근 30일 받은 메일 중 정제기가 '의심(suspect)' 띠로 둔 것을 보낸 사람 키별로(정제 제목 1개 + 건수).
    이미 차단·허용한 보낸 사람은 뺀다(``ad_lists.json`` 의 ``block_senders``·``allow_senders`` — 정제기 형식)."""
    from lm27.bundle import loader
    decided = _ad_lists(app)
    done = set(decided.get("block_senders") or ()) | set(decided.get("allow_senders") or ())
    today = app.deps.now().date()
    seen: dict = {}
    try:
        for r in loader.iter_records(app.paths, "mail", today - timedelta(days=30), today, cfg=app.cfg()):
            fl = r.get("flags") if isinstance(r.get("flags"), dict) else {}
            if r.get("ad_band") != "suspect" and not fl.get("ad"):
                continue
            sk = r.get("sender_key")
            if not isinstance(sk, str) or not _WKEY_RX.match(sk) or sk in done:
                continue
            ent = seen.setdefault(sk, {"id": sk, "title": str(r.get("subject_masked") or "")[:80], "n": 0})
            ent["n"] += 1
    except (OSError, ValueError):
        pass
    items = sorted(seen.values(), key=lambda x: (-x["n"], x["id"]))[:100]
    return {"items": items}


def post_ad_decision(app, req):
    from lm27.util import fsx
    sk, dec = req.body.get("id"), req.body.get("decision")
    if not isinstance(sk, str) or not _WKEY_RX.match(sk) or dec not in ("block", "allow"):
        raise ApiError(400, "bad_decision", "항목과 결정(차단·허용)을 고르세요")
    cur = _ad_lists(app)
    mine, other = ("block_senders", "allow_senders") if dec == "block" else ("allow_senders", "block_senders")
    new = dict(cur)
    new[mine] = sorted(set(cur.get(mine) or ()) | {sk})
    new[other] = sorted(set(cur.get(other) or ()) - {sk})
    fsx.atomic_write(app.paths.local_only_file(AD_FILE), fsx.canon_bytes(new))
    return {"ok": True, "decision": dec}


ROUTES = (("GET", r"/api/privacy/audit", get_audit),
          ("POST", r"/api/privacy/testbench", post_testbench),
          ("GET", r"/api/privacy/ad-suspects", get_ad_suspects),
          ("POST", r"/api/privacy/ad-decision", post_ad_decision))

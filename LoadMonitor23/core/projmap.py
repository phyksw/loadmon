# -*- coding: utf-8 -*-
"""
projmap.py — 사용자 지정 과제 (LoadMonitor23)

사용자가 UI에서 지정한 프로젝트는 config\\projects.json 에 저장된다:
  [{"name": "프로젝트A", "match": ["proja", "간섭계"], "desc": "무엇에 관한 과제인지 설명"}]

역할 구분:
  · 지정 프로젝트 = 고정 엔티티 — AI 체계 수립에 **항상 포함**(힌트가 아님), 판정 목록에 노출
  · 지정 안 된 영역 = 기존 AI 자동 발견이 그대로 분류
  · 재분류(retag) = 이미 분류된 신호 중 '공통'·자동발견 귀속을, 추후 지정된 프로젝트와
    유사성이 높으면 재귀속. 규칙이 결정적이라 Copilot 왕복 없이 몇 초에 끝나고 근거가 남는다.

유사성 규칙 (보수적 — 확실할 때만 옮긴다):
  1.0  이름 또는 식별 키워드가 신호 텍스트에 직접 등장
  0.67 설명(desc) 토큰 중 2개 이상이 신호 텍스트에 등장
  그 외 0 — 재귀속하지 않음 (임계 RETAG_THRESHOLD=0.5)
사용자가 지정한 다른 프로젝트로 이미 판정된 신호는 존중하고 건드리지 않는다.
"""
import difflib
import json
import os
import re

RETAG_THRESHOLD = 0.5
_WORD = re.compile(r"[\s_\-\.\\/\[\]()<>:,·|~!?\"'+§]+")
_STOP = {"관련", "업무", "프로젝트", "과제", "내용", "설명", "개발", "진행", "관리", "the", "and", "for"}


def _path(root):
    return os.path.join(root, "config", "projects.json")


def load_user_projects(root):
    """config\\projects.json → [{name, match[], desc}].
    주의: config.projects(문자열 배열)는 '힌트'라서 여기로 승격하지 않는다 —
    지정(항상 포함·재분류 강제)은 사용자가 UI 카드에서 명시한 것만."""
    p = _path(root)
    if not os.path.exists(p):
        return []
    try:
        raw = json.load(open(p, encoding="utf-8-sig"))
        out = []
        for it in raw if isinstance(raw, list) else []:
            if isinstance(it, dict) and str(it.get("name") or "").strip():
                out.append({"name": str(it["name"]).strip(),
                            "match": [str(k).strip().lower() for k in (it.get("match") or [])
                                      if str(k).strip()],
                            "desc": str(it.get("desc") or "").strip()})
        return out
    except (OSError, ValueError):
        return []


def save_user_projects(root, projects):
    """검증 후 저장. 반환: 저장된 목록"""
    clean, seen = [], set()
    for it in projects if isinstance(projects, list) else []:
        if not isinstance(it, dict):
            continue
        name = str(it.get("name") or "").strip()[:40]
        if not name or name.lower() in seen or name == "공통":
            continue
        seen.add(name.lower())
        clean.append({"name": name,
                      "match": [str(k).strip().lower()[:30] for k in (it.get("match") or [])
                                if str(k).strip()][:12],
                      "desc": str(it.get("desc") or "").strip()[:200]})
    with open(_path(root), "w", encoding="utf-8") as f:
        json.dump(clean, f, ensure_ascii=False, indent=1)
    return clean


def _desc_tokens(p):
    toks = set()
    for tok in _WORD.split((p.get("desc") or "").lower()):
        tok = tok.strip()
        if len(tok) >= 2 and tok not in _STOP and not tok.isdigit():
            toks.add(tok)
    return toks


def _text_tokens(text):
    return {t for t in (x.strip() for x in _WORD.split((text or "").lower()))
            if len(t) >= 2 and not t.isdigit()}


def _kw_hit(k, toks):
    """키워드 ↔ 텍스트 토큰: 완전일치, 또는 4자 이상 키워드의 접두/접미 합성만 인정.
    부분문자열 전면 허용은 오탐('정렬'⊂'재정렬', 'ai'⊂'email')이 실측돼 금지.
    'lidar-x' 같은 구분자 포함 키워드는 같은 규칙으로 조각내 모든 조각 일치를 요구한다."""
    def one(p):
        if p in toks:
            return True
        if len(p) >= 4 and any(t.startswith(p) or t.endswith(p) for t in toks):
            return True
        if len(p) >= 5:
            # 오탈자·표기 변형 흡수 — stdlib difflib, 임계 0.9 라 '정렬/재정렬'류 오탐 없음
            return any(len(t) >= 4
                       and difflib.SequenceMatcher(None, p, t).ratio() >= 0.9 for t in toks)
        return False
    parts = [p for p in _WORD.split(k) if len(p) >= 2]
    if not parts:
        return False
    return all(one(p) for p in parts)


def match_score(text, p):
    """신호 텍스트 ↔ 지정 프로젝트 유사도 (0 / 0.67 / 1.0) — 토큰 경계 기준"""
    low = (text or "").lower()
    if not low:
        return 0.0
    toks = _text_tokens(low)
    name = p["name"].lower()
    # 이름: 공백 포함 멀티워드(5자 이상)는 원문 부분일치 허용, 짧은 단일어는 토큰 일치만
    if (len(name) >= 5 and name in low) or _kw_hit(name, toks):
        return 1.0
    for k in p.get("match") or []:
        if len(k) >= 2 and _kw_hit(k, toks):
            return 1.0
    hits = sum(1 for t in _desc_tokens(p) if t in toks)
    return 0.67 if hits >= 2 else 0.0


def retag_rows(rows, projects):
    """판정된 신호 행을 지정 프로젝트로 재귀속.
    rows: dict 목록 (model/text 키 사용, model 없으면 project로 초기화)
    반환: (변경 건수, {프로젝트: 건수}, {프로젝트: [근거 텍스트 표본]})"""
    user_names_l = {p["name"].lower() for p in projects}
    n, by, ev = 0, {}, {}
    for r in rows:
        if not r.get("model") or r.get("model") == "미지정":
            pj = r.get("project")
            r["model"] = pj if pj not in ("", "미지정", None) else "공통"
        cur = str(r.get("model") or "").strip()
        if cur.lower() in user_names_l:      # 이미 사용자 지정 프로젝트로 판정됨 → 존중
            continue
        text = r.get("text") or ""           # who(발신자명)는 오귀속 위험이라 매칭에서 제외
        best, best_p = 0.0, None
        for p in projects:
            s = match_score(text, p)
            if s > best:
                best, best_p = s, p
        if best_p and best >= RETAG_THRESHOLD:
            r["model"] = best_p["name"]
            r["project"] = best_p["name"]
            r["judge"] = (r.get("judge") or "") + "+지정재분류"
            n += 1
            by[best_p["name"]] = by.get(best_p["name"], 0) + 1
            ev.setdefault(best_p["name"], []).append((r.get("text") or "")[:60])
    return n, by, {k: v[:5] for k, v in ev.items()}

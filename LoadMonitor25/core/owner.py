# -*- coding: utf-8 -*-
r"""owner.py — '이름'(팀 취합의 폴더 키) 규칙 한 곳에 모으기.

팀 서버는 owner 를 그대로 폴더명으로 쓰므로 경로 문자와 점을 거부한다(teamserver.py OWNER_BAD).
그런데 config.owner 를 비워 두면 %USERNAME% 이 쓰이고, 회사 AD 계정은 'cs.kim' 처럼 점이 흔하다 —
그대로 보내면 서버가 400(owner 이름 불량)으로 거부해 그 사람의 묶음이 영원히 안 올라간다(검증 확정).

그래서 보내는 쪽(teamup/export)은 항상 safe_owner() 로 정규화하고, 받는 쪽(teamserver)은 계속
거부한다 — 정규화는 편의, 거부는 경로 이탈 방어라서 둘 다 필요하다.
정규화 규칙이 서로 어긋나면 같은 사람이 두 폴더로 갈라져 팀 MM 이 중복 계상되므로, 규칙은 이 파일 하나뿐이다.
"""
import re
import hashlib
import unicodedata

# teamserver.py 와 같은 규칙 (경로 구분자·윈도우 금지문자·점·공백만)
OWNER_BAD = re.compile(r'[\\/:*?"<>|.]|^\s*$')
MAX_LEN = 40


def safe_owner(v):
    """'cs.kim' → 'cs_kim' · 빈 값 → '이름미상' · 40자 절단 (서버가 받아 주는 형태로)"""
    s = re.sub(r'[\\/:*?"<>|.]', "_", str(v or "").strip())
    s = re.sub(r"\s+", " ", s).strip()[:MAX_LEN].strip()
    return s or "이름미상"


def owner_of(cfg, env_user=""):
    """설정 → 윈도우 계정 순으로 이름을 정하고 정규화한다"""
    return safe_owner((cfg or {}).get("owner") or env_user)


def identity_fields(cfg, env_user=""):
    """Keep the original identity before lossy folder normalization.

    This detects punctuation/truncation collisions; a personal name is still not
    an organization-wide employee identifier and renames need deliberate review.
    """
    raw = unicodedata.normalize("NFKC", str((cfg or {}).get("owner") or env_user or "이름미상"))
    raw = "".join(c for c in raw if unicodedata.category(c) not in {"Cc", "Cf"})
    raw = " ".join(raw.split())
    return {"owner_source": raw, "member_id": hashlib.sha256(raw.casefold().encode("utf-8")).hexdigest()}

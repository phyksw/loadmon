# -*- coding: utf-8 -*-
r"""owner.py — 공유할 때 적는 표시 이름 규칙 한 곳.

개인 리포트를 조직장에게 공유할 때(공유 탭에서 구성원이 직접 고른 경우만) 표시 이름을 함께 보낸다. 팀 서버는 이 이름을 파일
이름·화면 글자로 쓰지 않고 owner_id 로 저장하지만, 경로 문자·점·윈도우 금지 문자가 섞이면 받는 쪽이 거부한다.
그래서 보내는 쪽(teamup)은 늘 safe_owner() 로 정규화하고, 받는 쪽(teamserver)은 계속 거부한다 — 정규화는 편의, 거부는
경로 이탈 방어라 둘 다 필요하다. 규칙은 이 파일 하나뿐이다.
"""
import re

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

# -*- coding: utf-8 -*-
r"""★ 수집기 단일 관문(facade — P §3.1 · §3.4 · 계약 §2.2 · L-10). 수집기 파이썬은 ``lm27.privacy`` 에서 **이 모듈만**
import 한다(``from lm27.privacy.detect import …`` 같은 우회 금지 — lint L-10).

    from lm27.privacy.sanitize import make_record_context, sanitize_record
    rc = make_record_context(paths.root, "pc.git", pc_id)          # 프로그램 폴더 모드(에이전트는 root=None)
    out = sanitize_record("pc_git", raw, rc)                      # 원시(메모리) → RecordOutcome(stored 면 봉인 행)
    if out.status == "stored": writer.append(out.row)              # lm27.store.SegmentWriter 만 저장한다

원문은 메모리에서만 다루고, 디스크에는 ``sanitize_record`` 를 통과한 열 허용 목록 행(봉인)만 간다(I1·I2).

이름 ``lm27.privacy.sanitize`` 는 두 가지를 뜻한다 — 이 모듈(L-10)과 P §3.3 이 패키지에서 재수출하는 ``sanitize()`` 함수.
파이썬은 하위 모듈을 처음 import 할 때 패키지 속성을 그 모듈로 덮어쓰므로(import 순서에 따라 함수였다 모듈이 된다),
이 모듈 객체를 **부를 수 있게** 해 두 용법이 언제나 같게 한다: ``lm27.privacy.sanitize(text, …)`` = ``detect.sanitize``,
``lm27.privacy.sanitize.sanitize_record`` = 관문. 패키지 ``__init__`` 이 이 모듈을 직접 import 해 속성을 고정한다.
"""
import sys
import types

from .context import make_record_context
from .detect import sanitize
from .records import RecordOutcome, SanitizedRow, sanitize_record
from .scan import scan

__all__ = ["RecordOutcome", "SanitizedRow", "make_record_context", "sanitize", "sanitize_record", "scan"]


class _CallableFacade(types.ModuleType):
    """모듈 자체를 ``sanitize(text, field_name="text", ctx=None, max_len=None)`` 처럼 부를 수 있는 모듈 형."""

    def __call__(self, *args, **kwargs):
        return sanitize(*args, **kwargs)


sys.modules[__name__].__class__ = _CallableFacade

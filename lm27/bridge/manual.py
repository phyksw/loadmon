# -*- coding: utf-8 -*-
r"""수동 붙여넣기 대체 경로(B §10) — 프롬프트 파일 내보내기 · 목록(manifest) · ``ManualTransport`` · 답 반입.

  · 같은 L3·L2 를 쓴다 — 바뀌는 것은 L1(``ManualTransport``)뿐. 패킹·rid 봉투·게이트·검증·상태 분류·커밋·재개가 자동
    경로와 완전히 같다. 수동 경로에서는 화면을 읽지 못하므로 ``CopilotEnv`` 가 모두 unknown, ``web_exposed=true``
    (엄격 규칙이 늘 걸린다 — B §10.6).
  · 파일: ``%LOCALAPPDATA%\LoadMonitor27\agent\copilot_manual\<seq:03d>_<stage>_<rid>.prompt.txt`` — 조립된 프롬프트 그대로
    (게이트 통과본), UTF-8 BOM + CRLF. ``bridge.manual.ttlDays`` 가 지나면 지운다(``fsio.write_text_ttl`` — 원문이 디스크에
    닿는 두 경우 중 하나, B §9.5). 목록 ``manifest.json`` = ``{schema:1, batches:[{seq, stage, rid, file, items[{n,key,ck}],
    in_chars, created, state(open|answered|expired|superseded), answered, result, run, depth, resent}]}``.
  · 반입(``import_text``): 붙여넣은 글의 rid 봉투를 전부 찾아(순서 무관, 여러 답 한꺼번에) 열린 묶음과 맞춘다. 목록에 없는
    rid 는 반입하지 않는다(BR-MANUAL-RID — 저장소 변화 없음). 반입한 묶음의 프롬프트 파일은 지운다. 빠진·무효 항목은 다음
    수동 묶음으로 자동으로 나간다(사람에게 '같은 것을 다시 붙여넣으세요' 이상을 요구하지 않는다).
  · ``inbox\*.txt`` — 브리지가 시작할 때마다 훑고, 반입한 파일은 지운다.
"""
from __future__ import annotations

from pathlib import Path

from lm27.bridge import fsio
from lm27.bridge.clock import iso_now, iso_to_epoch
from lm27.bridge.transport import SendResult, norm

SCHEMA = 1
STATES = ("open", "answered", "expired", "superseded")
MANIFEST_NAME = "manifest.json"
INBOX_NAME = "inbox"
PROMPT_SUFFIX = ".prompt.txt"
CLIPBOARD_TIMEOUT_S = 15.0


def manual_dir(paths) -> Path:
    return Path(paths.copilot_manual())


class Manifest:
    """수동 묶음 목록(원문 없음 — 번호·key·ck·길이·상태만)."""

    def __init__(self, paths, clock):
        self.paths = paths
        self.clock = clock
        self.dir = manual_dir(paths)
        self.path = fsio.child(self.dir, MANIFEST_NAME)
        self.doc = {"schema": SCHEMA, "batches": []}
        self.load()

    def load(self) -> Manifest:
        d = fsio.read_json(self.path, None)
        if isinstance(d, dict) and isinstance(d.get("batches"), list):
            self.doc = {"schema": SCHEMA, "batches": [b for b in d["batches"] if isinstance(b, dict)]}
        else:
            self.doc = {"schema": SCHEMA, "batches": []}
        return self

    def save(self) -> None:
        fsio.write_atomic(self.path, self.doc)

    @property
    def batches(self) -> list:
        return self.doc["batches"]

    def next_seq(self) -> int:
        return max((int(b.get("seq") or 0) for b in self.batches), default=0) + 1

    def open_batches(self, stage: str | None = None) -> list:
        return [b for b in self.batches if b.get("state") == "open" and (stage is None or b.get("stage") == stage)]

    def open_count(self) -> int:
        return len(self.open_batches())

    def by_rid(self, rid: str) -> dict | None:
        return next((b for b in self.batches if b.get("rid") == rid), None)

    def awaiting_cks(self, stage: str) -> set:
        """열린 묶음에 든 항목(대기열에서 뺀다 — B §10.3 awaiting)."""
        return {i.get("ck") for b in self.open_batches(stage) for i in b.get("items") or [] if i.get("ck")}

    def asked(self, stage: str) -> dict:
        """ck → 답을 받은(반입한) 묶음 수 — 수동 경로의 항목 질문 횟수(bridge.maxAsksPerItem)."""
        out: dict = {}
        for b in self.batches:
            if b.get("stage") == stage and b.get("state") == "answered":
                for i in b.get("items") or []:
                    ck = i.get("ck")
                    if ck:
                        out[ck] = out.get(ck, 0) + 1
        return out

    def _drop_file(self, b: dict) -> None:
        name = b.get("file")
        if isinstance(name, str) and name:
            try:
                fsio.remove(fsio.child(self.dir, name))
            except (OSError, ValueError):
                pass

    def add(self, *, seq: int, stage: str, rid: str, file: str, items: list, in_chars: int, run: str,
            depth: int = 0, resent: int = 0) -> dict:
        cks = {i.get("ck") for i in items if i.get("ck")}
        for b in self.open_batches(stage):
            if cks & {i.get("ck") for i in b.get("items") or []}:
                b["state"] = "superseded"                         # 같은 항목이 새 묶음으로 다시 나감
                self._drop_file(b)
        b = {"seq": seq, "stage": stage, "rid": rid, "file": file, "items": items, "in_chars": int(in_chars),
             "created": iso_now(self.clock), "state": "open", "answered": None, "result": None, "run": run,
             "depth": int(depth), "resent": int(resent)}
        self.batches.append(b)
        return b

    def answer(self, b: dict, status: str, counts: dict) -> None:
        b["state"] = "answered"
        b["answered"] = iso_now(self.clock)
        b["result"] = {"status": status, **{k: int(v) for k, v in counts.items()}}
        self._drop_file(b)

    def expire(self, ttl_days: int) -> int:
        """TTL 이 지난 열린 묶음 → expired(프롬프트 파일도 지운다). 반환: 바꾼 수."""
        limit = self.clock.now() - max(0, int(ttl_days)) * 86400
        n = 0
        for b in self.open_batches():
            t = iso_to_epoch(str(b.get("created") or ""))
            if t is not None and t < limit:
                b["state"] = "expired"
                self._drop_file(b)
                n += 1
        return n


class ManualTransport:
    """L1 대체 — 프롬프트 파일 + 목록을 쓰고 ``manual_pending`` 을 돌려준다(B §10.2). 답은 나중에 반입."""

    kind = "manual"

    def __init__(self, paths, cfg, clock, *, run_id: str = "", manifest: Manifest | None = None):
        self.paths = paths
        self.cfg = cfg
        self.clock = clock
        self.run_id = run_id
        self.manifest = manifest or Manifest(paths, clock)
        self.ck_of: dict = {}             # key → ck(러너가 단계마다 채운다)
        self.hint: dict = {}              # 다음 묶음의 {depth, resent}(러너가 질의마다 채운다)
        self.exported = 0
        self.chat_seq = 0

    def open(self) -> str:
        self.manifest.expire(self.cfg.manual.ttl_days)
        self.manifest.save()
        return "ready"

    def new_chat(self) -> bool:
        return True

    def close(self) -> None:
        self.manifest.save()

    def open_count(self) -> int:
        return self.manifest.open_count()

    def roundtrip(self, req) -> SendResult:
        seq = self.manifest.next_seq()
        name = f"{seq:03d}_{req.stage}_{req.rid}{PROMPT_SUFFIX}"
        fsio.write_text_ttl(fsio.child(self.manifest.dir, name), req.text, ttl_days=self.cfg.manual.ttl_days,
                            clock=self.clock)
        items = [{"n": i, "key": k, "ck": self.ck_of.get(k, "")} for i, k in enumerate(req.item_keys, 1)]
        n = len(norm(req.text))
        self.manifest.add(seq=seq, stage=req.stage, rid=req.rid, file=name, items=items, in_chars=n, run=self.run_id,
                          depth=int(self.hint.get("depth", 0)), resent=int(self.hint.get("resent", 0)))
        self.manifest.save()
        self.exported += 1
        return SendResult(phase="manual_pending", pick="manual", in_chars=n, injected_chars=n, model_note="manual",
                          chat_seq=self.chat_seq)


def inbox_dir(paths) -> Path:
    r"""``copilot_manual\inbox``(붙여넣은 답을 사람이 떨어뜨리는 곳)."""
    return fsio.child(manual_dir(paths), INBOX_NAME)


def scan_inbox(paths) -> list:
    r"""``copilot_manual\inbox\*.txt`` → [(경로, 글 | None, 상태)] — 상태는 ``fsio.read_text_any``(ok · enc · io).
    UTF-8 이 아니면 CP949(메모장 'ANSI' 저장)로 다시 읽는다. 훑은 파일은 반입 시도 뒤 호출자가 지운다(``fsio.remove``)."""
    d = inbox_dir(paths)
    if not d.is_dir():
        return []
    out = []
    for p in sorted(d.iterdir()):
        if p.is_file() and p.suffix.lower() == ".txt":
            t, st = fsio.read_text_any(p)
            out.append((p, t, st))
    return out


def read_clipboard(run=None) -> str:
    """클립보드 글(PowerShell ``Get-Clipboard -Raw``, -NoProfile -NonInteractive). 못 읽으면 ''."""
    if run is None:
        from lm27.util.proc import run_child as run
    cmd = ["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command",
           "[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false); Get-Clipboard -Raw"]
    try:
        r = run(cmd, timeout_s=CLIPBOARD_TIMEOUT_S)
    except OSError:
        return ""
    if getattr(r, "rc", 1) != 0 or getattr(r, "timed_out", False):
        return ""
    out = r.out_text() if hasattr(r, "out_text") else str(getattr(r, "stdout", "") or "")
    return out or ""


def import_text(text: str, **kw) -> dict:
    """붙여넣은 답 반입(B §10.4) — 러너의 같은 분류·커밋·재질의 규칙으로(``runner.manual_import``)."""
    from lm27.bridge import runner
    return runner.manual_import(text, **kw)

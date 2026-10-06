# -*- coding: utf-8 -*-
r"""팀 서버 저장소(TAB §3.7 · §3.8 · §3.10 · 계약 §1.4) — 받은 바이트 그대로의 불변 묶음 + 사람별 색인 한 파일.

    store = open_store(cfg)                       # teamServer.storeDir(비면 %LOCALAPPDATA%\LoadMonitor27\teamserver)
    r = ingest_bytes(store, raw, source="http", claimed_sha=sha, client="0.1.0", ip="127.0.0.1")

배치(서버가 만든 이름만 — person_key 형식이 경로 문자·장치 예약어 충돌을 원천 차단):
    store.json · secrets\pepper.json · registry.json · registry_history\vNNNN.json · roster.json ·
    members\<person_key>\{current.json, current.json.bak, bundles\<period_key>__<sha12>.json} ·
    inbox\{done,rejected}\ · out\gen_<N>\… · out\current.json · run\{server.lock, server.json, port_diag.json,
    inbox_seen.json, firewall_diag.json} · logs\{server_YYYYMMDD.log, uploads.jsonl, aggregate_YYYYMMDD.log}

원칙
  · 사람 × 기간 원자 교체: 새 묶음은 새 이름으로 쓰고 '무엇이 현재인가'는 ``current.json`` 한 파일의 교체로만 바뀐다.
    같은 기간의 옛 묶음은 보관(``teamServer.historyKeep``), 늦게 온 옛 빌드는 ``stale_kept``(current 불변).
  · 서버는 묶음을 고치지 않고 거절한다(422). 응답·로그에는 경로·코드·키·크기·상태만 — 값·라벨·경로·토큰 0.
  · 쓰기는 ``lm27.util.fsx`` 만(L-07). 이 저장소는 프로그램 폴더 밖(``data\`` 아님)이며 이 모듈이 그 배치의 단일원이다.
"""
from __future__ import annotations

import hmac
import os
import re
import secrets
import threading
import unicodedata
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from lm27 import LM27_VERSION
from lm27.team import schema
from lm27.util import fsx

STORE_SCHEMA = "lm27.teamstore/1"
REGISTRY_SCHEMA = "lm27.registry/1"
REGISTRY_MAX = 2 * 1024 * 1024
MB = 1024 * 1024
DRAIN_MAX = 64 * MB
PK_RX = re.compile(r"p_[0-9a-f]{12}")
GEN_RX = re.compile(r"gen_(\d{1,9})")
PERIOD_RX = re.compile(r"\d{4}-\d{2}-\d{2}_\d{4}-\d{2}-\d{2}")
LOG_DATE_RX = re.compile(r"(?:server|aggregate)_(\d{8})\.log")


def now_local() -> datetime:
    """이 PC 의 로컬 시각(오프셋 포함). IANA 시간대 DB 를 쓰지 않는다(OS 오프셋)."""
    return datetime.now(UTC).astimezone().replace(microsecond=0)


def iso(dt: datetime) -> str:
    return dt.isoformat()


def _sha12(sha: str) -> str:
    return sha[:12]


def _norm_label(s, maxlen=20) -> str:
    """사람이 넣은 라벨 — NFKC · Cc/Cf 제거 · 공백 접기 · 자르기."""
    s = unicodedata.normalize("NFKC", str(s or ""))
    s = "".join(ch for ch in s if unicodedata.category(ch) not in ("Cc", "Cf"))
    return " ".join(s.split())[:maxlen]


@dataclass
class IngestResult:
    ok: bool
    http: int = 200
    code: str = ""
    msg: str = ""
    detail: list = field(default_factory=list)
    status: str = ""                 # stored · already_have · stale_kept
    person_key: str | None = None
    period_key: str | None = None
    sha: str | None = None
    replaced: str | None = None
    warnings: list = field(default_factory=list)

    def body(self) -> dict:
        if not self.ok:
            return {"ok": False, "code": self.code, "error": self.msg, "detail": list(self.detail)[:20]}
        return {"ok": True, "status": self.status, "person_key": self.person_key, "period_key": self.period_key,
                "sha256": self.sha, "replaced": self.replaced}


def _fail(http, code, msg, detail=()) -> IngestResult:
    return IngestResult(ok=False, http=http, code=code, msg=msg, detail=list(detail)[:20])


_FAIL_MSG = {
    "sha_missing": "X-LM27-Bundle-SHA256 헤더가 없습니다",
    "sha_mismatch": "본문 sha256 이 헤더와 다릅니다 — 전송 중 바뀌었습니다",
    "bad_json": "JSON 으로 읽을 수 없습니다",
    "dup_key": "같은 객체 안에 중복 키가 있습니다",
    "not_object": "최상위가 JSON 객체가 아닙니다",
    "too_large": "묶음이 서버 상한보다 큽니다 — 기간을 나눠 다시 만드세요",
    "schema": "팀 묶음 형식이 맞지 않습니다",
    "unknown_major": "이 서버가 받지 않는 묶음 판입니다 — LM27 을 같은 판으로 맞추세요",
    "forbidden_content": "팀 업로드에 넣을 수 없는 내용이 있습니다(값은 표시하지 않습니다)",
    "integrity": "시간 수치가 서로 맞지 않습니다(봉투·귀속·요약) — 다시 만드세요",
    "ref_missing": "묶음 안 참조가 끊겼습니다(역할·단위업무·과제)",
    "store_failed": "저장에 실패했습니다(디스크·권한)",
}


class TeamStore:
    """팀 서버 저장소 하나. 같은 저장소를 쓰는 서버는 하나(``run\\server.lock``)."""

    def __init__(self, root, cfg, *, payload_check=None, registry_validator=None, clock=None, paths=None):
        self.dir = Path(os.path.abspath(os.fspath(root)))
        self.cfg = cfg
        self.payload_check = payload_check
        self.registry_validator = registry_validator
        self.clock = clock or now_local
        self.paths = paths
        self._plocks: dict[str, threading.Lock] = {}
        self._glock = threading.Lock()
        self._reg_lock = threading.Lock()     # PUT /api/registry 판 확인~원자 쓰기 직렬화(요청 스레드 병렬 — W1 통합 창)
        self._lock_fh = None
        self._cal_cache = None
        self.store_id = ""
        self.pepper = ""
        self.pepper_id = ""

    # ── 배치 ────────────────────────────────────────────────────────────
    def p(self, *parts) -> Path:
        return self.dir.joinpath(*parts)

    def store_json(self):
        return self.p("store.json")

    def pepper_json(self):
        return self.p("secrets", "pepper.json")

    def registry_json(self):
        return self.p("registry.json")

    def registry_history(self, version: int):
        return self.p("registry_history", f"v{int(version):04d}.json")

    def roster_json(self):
        return self.p("roster.json")

    def members_dir(self):
        return self.p("members")

    def member(self, pk: str) -> Path:
        if not isinstance(pk, str) or not PK_RX.fullmatch(pk):
            raise ValueError("person_key 형식이 아닙니다")
        return self.members_dir() / pk

    def current_json(self, pk):
        return self.member(pk) / "current.json"

    def bundles_dir(self, pk):
        return self.member(pk) / "bundles"

    def inbox(self, *sub):
        return self.p("inbox", *sub)

    def out_dir(self):
        r"""취합 산출 폴더 ``<store>\out``(TAB §3.7 — ROOT 밖 저장소 안. 프로그램 폴더 out\ 과 무관, L-08 예외 v1.2 C22)."""
        return self.p("out")

    def gen_dir(self, n: int):
        return self.out_dir() / f"gen_{int(n)}"

    def out_current(self):
        return self.out_dir() / "current.json"

    def run_dir(self):
        return self.p("run")

    def run_file(self, name: str):
        if name not in ("server.lock", "server.json", "port_diag.json", "inbox_seen.json", "firewall_diag.json"):
            raise ValueError("run 파일 이름이 아닙니다")
        return self.run_dir() / name

    def logs_dir(self):
        return self.p("logs")

    # ── 설정 ────────────────────────────────────────────────────────────
    def c(self, key):
        return self.cfg[key]

    # ── 초기화 ──────────────────────────────────────────────────────────
    def ensure(self) -> TeamStore:
        """폴더·store.json·pepper 를 만든다(이미 있으면 읽기만). pepper = 32B 난수(64hex) — 정적 제공 금지."""
        for d in (self.dir, self.members_dir(), self.inbox(), self.inbox("done"), self.inbox("rejected"),
                  self.out_dir(), self.run_dir(), self.logs_dir()):
            fsx.ensure_dir(d)
        st = fsx.read_json(self.store_json(), None)
        if not (isinstance(st, dict) and isinstance(st.get("store_id"), str) and re.fullmatch(r"[0-9a-f]{16}",
                                                                                                st["store_id"])):
            st = {"schema": STORE_SCHEMA, "store_id": secrets.token_hex(8), "created_at": iso(self.clock())}
            fsx.atomic_write(self.store_json(), fsx.canon_bytes(st))
        self.store_id = st["store_id"]
        pj = fsx.read_json(self.pepper_json(), None)
        if not (isinstance(pj, dict) and isinstance(pj.get("pepper"), str) and re.fullmatch(r"[0-9a-f]{64}", pj["pepper"])):
            pep = secrets.token_hex(32)
            pj = {"pepper": pep, "pepper_id": schema.pepper_id_of(pep), "created_at": iso(self.clock())}
            fsx.atomic_write(self.pepper_json(), fsx.canon_bytes(pj))
        self.pepper = pj["pepper"]
        self.pepper_id = schema.pepper_id_of(self.pepper)
        return self

    # ── 서버 잠금(같은 저장소 서버 하나) ────────────────────────────────────
    def lock_server(self) -> bool:
        """``run\\server.lock`` 1바이트 잠금(msvcrt). 성공 True, 다른 프로세스가 쥐었으면 False. 죽으면 OS 가 푼다."""
        import msvcrt
        if self._lock_fh is not None:
            return True
        lp = self.run_file("server.lock")
        if not lp.exists():
            try:
                fsx.atomic_write(lp, b"\0")
            except PermissionError:
                pass                                   # 다른 프로세스가 막 만들고 쥐었다 — 아래 잠금이 판정한다
        fh = open(fsx.longp(lp), "rb")                 # noqa: SIM115 — 잠금 동안 핸들을 쥔다
        try:
            msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            fh.close()
            return False
        self._lock_fh = fh
        return True

    def release_server(self) -> None:
        import msvcrt
        fh, self._lock_fh = self._lock_fh, None
        if fh is None:
            return
        try:
            fh.seek(0)
            msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
        except OSError:
            pass
        fh.close()

    def server_info(self) -> dict | None:
        return fsx.read_json(self.run_file("server.json"), None)

    def write_server_json(self, *, pid, port, host, instance_id, exe) -> None:
        fsx.atomic_write(self.run_file("server.json"), fsx.canon_bytes({
            "pid": pid, "port": port, "bind_host": host, "started_at": iso(self.clock()), "instance_id": instance_id,
            "store_id": self.store_id, "version": LM27_VERSION, "exe": exe}))

    def clear_server_json_if_mine(self, pid, instance_id) -> bool:
        """자기 pid·instance 일 때만 지운다(뒤에 뜬 인스턴스 기록을 지우지 않게 — LM24 clear_pid 계승)."""
        info = self.server_info()
        if not isinstance(info, dict) or info.get("pid") != pid or info.get("instance_id") != instance_id:
            return False
        try:
            os.remove(self.run_file("server.json"))
        except FileNotFoundError:
            pass
        return True

    def person_lock(self, pk: str) -> threading.Lock:
        """같은 사람 동시 업로드 직렬화(LM24 OWNER_LOCKS 계승)."""
        with self._glock:
            return self._plocks.setdefault(pk, threading.Lock())

    # ── 레지스트리 ──────────────────────────────────────────────────────
    def registry(self) -> dict | None:
        """저장된 팀 레지스트리(pepper 없음). 없으면 None."""
        return fsx.read_json(self.registry_json(), None)

    def registry_version(self) -> int:
        r = self.registry()
        v = r.get("version") if isinstance(r, dict) else None
        return v if isinstance(v, int) and not isinstance(v, bool) else 0

    def registry_for_client(self) -> dict:
        """``GET /api/registry`` 본문 — 저장본 + 응답 때 합성하는 pepper·pepper_id(TAB §3.10, X-238)."""
        r = self.registry() or {"schema": REGISTRY_SCHEMA, "version": 0, "projects": [], "members": [],
                                "vocab": {}, "agents": [], "internal_domains": [], "customers": [], "partners": []}
        out = {k: v for k, v in r.items() if k not in ("pepper", "pepper_id")}
        out["pepper"] = self.pepper
        out["pepper_id"] = self.pepper_id
        return out

    def put_registry(self, obj, *, ukey=None) -> tuple[int, dict]:
        """``PUT /api/registry``: 판 = 현재 + 1(아니면 409), 운반 검증(TAB §3.10) + 의미 검증(H ``validate_registry``,
        side="server") → 보관(``registry_history``) → 원자 교체. 반환 (HTTP, 본문). 게시·재취합은 호출자."""
        if not isinstance(obj, dict):
            return 400, err_body("not_object", "레지스트리는 JSON 객체여야 합니다")
        cur = self.registry_version()
        ver = obj.get("version")
        if not isinstance(ver, int) or isinstance(ver, bool) or ver != cur + 1:
            return 409, err_body("registry_version_conflict",
                                 f"다른 곳에서 레지스트리가 바뀌었습니다(현재 v{cur}) — 최신 판을 불러와 다시 저장하세요")
        body = {k: v for k, v in obj.items() if k not in ("pepper", "pepper_id")}   # pepper 는 PUT 으로 못 바꾼다
        problems = list(dict.fromkeys(registry_transport_errors(body, ukey=ukey) + self._semantic_registry_errors(body)))
        if problems:
            return 422, err_body(problems[0][1], "레지스트리 검증 실패 — 칸 옆 사유를 확인하세요",
                                 [f"{p}: {c}" for p, c in problems])
        raw = fsx.canon_bytes(body)
        # 판 확인과 쓰기를 한 잠금 안에서(검증은 느릴 수 있어 잠금 밖) — 동시 PUT 두 개가 모두 200 을 받고 한쪽 변경이
        # 사라지던 결함(W1 통합 창): 쓰기 직전에 판을 다시 보고 그새 바뀌었으면 409.
        with self._reg_lock:
            now_ver = self.registry_version()
            if now_ver != cur:
                return 409, err_body("registry_version_conflict",
                                     f"다른 곳에서 레지스트리가 바뀌었습니다(현재 v{now_ver}) — 최신 판을 불러와 다시 저장하세요")
            fsx.atomic_write(self.registry_history(ver), raw)
            fsx.atomic_write(self.registry_json(), raw)
            self._cal_cache = None
        return 200, {"ok": True, "version": ver}

    def _semantic_registry_errors(self, body) -> list[tuple[str, str]]:
        """H ``validate_registry(obj, side="server")``(주입 또는 지연 import). 막는 항목만 (경로, 코드)."""
        fn = self.registry_validator
        if fn is None:
            import importlib.util
            if importlib.util.find_spec("lm27.hier") is None or                     importlib.util.find_spec("lm27.hier.registry_schema") is None:
                return [("$", "validator_unavailable")]          # 의미 검증기 없이 저장하지 않는다(fail-closed)
            from lm27.hier.registry_schema import validate_registry   # 서버도 H 검증기를 쓴다(H §3.6, X-234)
            fn = validate_registry
        out = []
        for e in fn(body, side="server") or ():
            get = e.get if isinstance(e, dict) else (lambda k, _e=e: getattr(_e, k, None))
            lv, blk = get("level"), get("blocking")
            if (lv is not None and lv != "reject") or (lv is None and blk is not None and not blk):
                continue                                          # H Err.level: reject 만 막는다(drop·warn 은 통과)
            path = e.get("path") if isinstance(e, dict) else getattr(e, "path", "")
            code = e.get("code") if isinstance(e, dict) else getattr(e, "code", "invalid")
            out.append((str(path or ""), str(code or "invalid")))
        return out

    def calendar(self):
        """취합·검증 달력: 팀 레지스트리 ``calendar`` > ``config\\calendar.json``(계약 §3.21, CR-15). (Calendar, 경고)."""
        rv = self.registry_version()
        if self._cal_cache is not None and self._cal_cache[0] == rv:
            return self._cal_cache[1]
        from lm27.paths import Paths
        from lm27.time.calendar import load_calendar
        cal = load_calendar(self.paths or Paths(), self.registry())
        self._cal_cache = (rv, cal)
        return cal

    # ── 명단(roster) ────────────────────────────────────────────────────
    def roster(self) -> dict:
        r = fsx.read_json(self.roster_json(), {}) or {}
        return {"labels": dict(r.get("labels") or {}), "links": dict(r.get("links") or {}),
                "retired": list(r.get("retired") or []), "member_of": dict(r.get("member_of") or {})}

    def patch_member(self, pk: str, patch) -> tuple[int, dict]:
        """``PATCH /api/members/<person_key>``: label · member_id · retired · link_to · drop_period."""
        if not PK_RX.fullmatch(pk or ""):
            return 404, err_body("not_found", "그 사람 키가 없습니다")
        if not isinstance(patch, dict) or set(patch) - {"label", "member_id", "retired", "link_to", "drop_period"}:
            return 400, err_body("not_object", "label·member_id·retired·link_to·drop_period 만 바꿀 수 있습니다")
        if not self.member(pk).is_dir():
            return 404, err_body("not_found", "그 사람 키가 없습니다")
        with self._glock:
            r = self.roster()
            if "label" in patch:
                lab = _norm_label(patch["label"])
                if lab:
                    r["labels"][pk] = lab
                else:
                    r["labels"].pop(pk, None)
            if "member_id" in patch:
                mid = patch["member_id"]
                if mid is None or mid == "":
                    r["member_of"].pop(pk, None)
                elif isinstance(mid, str) and schema.RX["REG_ID"].fullmatch(mid) and mid.startswith("M"):
                    r["member_of"][pk] = mid
                else:
                    return 422, err_body("schema", "구성원 ID 형식이 아닙니다", ["member_id: schema"])
            if "retired" in patch:
                ret = set(r["retired"])
                (ret.add if patch["retired"] else ret.discard)(pk)
                r["retired"] = sorted(ret)
            if "link_to" in patch:
                tgt = patch["link_to"]
                if tgt in (None, ""):
                    r["links"].pop(pk, None)
                elif isinstance(tgt, str) and PK_RX.fullmatch(tgt) and tgt != pk and self.member(tgt).is_dir():
                    r["links"][pk] = tgt
                else:
                    return 422, err_body("ref_missing", "연결할 사람 키가 없습니다", ["link_to: ref_missing"])
            fsx.atomic_write(self.roster_json(), fsx.canon_bytes(r))
        if "drop_period" in patch:
            per = patch["drop_period"]
            if not isinstance(per, str) or not PERIOD_RX.fullmatch(per):
                return 422, err_body("schema", "기간 키 형식이 아닙니다", ["drop_period: schema"])
            with self.person_lock(pk):
                cur = self.read_current(pk)
                if per in cur:
                    new = {k: v for k, v in cur.items() if k != per}
                    self._write_current(pk, cur, new)
        return 200, {"ok": True}

    # ── 사람별 색인 ─────────────────────────────────────────────────────
    def member_keys(self) -> list[str]:
        try:
            names = os.listdir(fsx.longp(self.members_dir()))
        except FileNotFoundError:
            return []
        return sorted(n for n in names if PK_RX.fullmatch(n) and self.p("members", n).is_dir())

    def read_current(self, pk: str, warnings: list | None = None) -> dict:
        """``current.json`` — 깨졌으면 ``.bak``, 그것도 깨졌으면 ``bundles\\`` 에서 기간별 built_at 최신으로 재구성(경고)."""
        cp = self.current_json(pk)
        if not cp.exists():
            return {}
        cur = fsx.read_json(cp, None)
        if _valid_current(cur):
            return cur
        bak = fsx.read_json(cp.with_name("current.json.bak"), None)
        if _valid_current(bak):
            if warnings is not None:
                warnings.append(f"{pk}: current.json 손상 — 예비본(.bak)으로 복구")
            fsx.atomic_write(cp, fsx.canon_bytes(bak))
            return bak
        rebuilt = self._rebuild_current(pk)
        if warnings is not None:
            warnings.append(f"{pk}: current.json·예비본 손상 — 저장 묶음에서 기간별 최신으로 재구성")
        fsx.atomic_write(cp, fsx.canon_bytes(rebuilt))
        return rebuilt

    def _rebuild_current(self, pk: str) -> dict:
        best: dict[str, tuple] = {}
        bd = self.bundles_dir(pk)
        for fn in sorted(os.listdir(fsx.longp(bd))) if bd.is_dir() else ():
            m = re.fullmatch(r"(\d{4}-\d{2}-\d{2}_\d{4}-\d{2}-\d{2})__([0-9a-f]{12})\.json", fn)
            if not m:
                continue
            raw = fsx.read_bytes(bd / fn)
            try:
                obj = schema.loads_bundle(raw)
                built = schema.parse_dt(obj["built_at"])
            except (ValueError, KeyError, TypeError):
                continue
            if built is None:
                continue
            sha = fsx.sha256_hex(raw)
            key = (built.astimezone(UTC), sha)
            if m.group(1) not in best or key > best[m.group(1)][0]:
                best[m.group(1)] = (key, {"sha256": sha, "file": fn, "received_at": "", "built_at": obj["built_at"],
                                          "client": "", "via": "rebuild", "meta": _entry_meta(obj)})
        return {k: v[1] for k, v in sorted(best.items())}

    def _write_current(self, pk, old: dict, new: dict) -> None:
        cp = self.current_json(pk)
        if cp.exists():
            fsx.atomic_write(cp.with_name("current.json.bak"), fsx.read_bytes(cp))
        fsx.atomic_write(cp, fsx.canon_bytes(new))

    def bundle_bytes(self, pk: str, fn: str) -> bytes:
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}_\d{4}-\d{2}-\d{2}__[0-9a-f]{12}\.json", fn or ""):
            raise ValueError("묶음 파일 이름 형식이 아닙니다")
        return fsx.read_bytes(self.bundles_dir(pk) / fn)

    def prune_history(self, pk: str, period_key: str, keep: int) -> int:
        """current 가 가리키지 않는 같은 기간 옛 묶음 중 최근 ``keep`` 개만 남긴다. 지운 수."""
        cur = self.read_current(pk)
        live = {e.get("file") for e in cur.values() if isinstance(e, dict)}
        bd = self.bundles_dir(pk)
        olds = []
        for fn in os.listdir(fsx.longp(bd)) if bd.is_dir() else ():
            if fn.startswith(period_key + "__") and fn.endswith(".json") and fn not in live:
                try:
                    olds.append((os.path.getmtime(fsx.longp(bd / fn)), fn))
                except OSError:
                    continue
        olds.sort(reverse=True)
        n = 0
        for _t, fn in olds[max(keep, 0):]:
            try:
                os.remove(fsx.longp(bd / fn))
                n += 1
            except OSError:
                pass                                     # 열려 있으면 다음 회차에
        return n

    # ── /api/members ────────────────────────────────────────────────────
    def members_view(self, td: dict | None = None) -> dict:
        """TAB §3.11 — 경로·pid·호스트명 없이 사람 키·라벨·기간·표식만."""
        roster = self.roster()
        reg = self.registry() or {}
        reg_labels = {m.get("id"): m.get("label") for m in reg.get("members") or () if isinstance(m, dict)}
        people = {p.get("person_key"): p for p in (td or {}).get("people") or () if isinstance(p, dict)}
        linked_to = {}
        for p in people.values():
            for k in p.get("linked") or ():
                linked_to[k] = p.get("person_key")
        out = []
        for pk in self.member_keys():
            cur = self.read_current(pk)
            ents = [(per, e) for per, e in sorted(cur.items()) if isinstance(e, dict)]
            meta = [e.get("meta") or {} for _p, e in ents]
            rep = linked_to.get(pk, pk)
            tp = people.get(rep) or {}
            used = {}
            for mo in tp.get("months") or ():
                used.setdefault(mo.get("src12"), []).append(mo.get("m"))
            mid = roster["member_of"].get(pk) or next((m.get("member_id") for m in meta if m.get("member_id")), None)
            self_label = next((m.get("self_label") for m in reversed(meta) if m.get("self_label")), "")
            label, src = display_label(pk, mid, self_label, roster, reg_labels)
            flags = sorted({w for e in (e for _p, e in ents) for w in e.get("warn") or ()} | set(tp.get("flags") or ()))
            out.append({
                "i": tp.get("i"), "person_key": pk, "label": label, "label_source": src, "member_id": mid,
                "linked": [k for k in (tp.get("linked") or ()) if k != pk] if rep == pk else [rep],
                "retired": pk in roster["retired"],
                "periods": [{"period_key": per, "sha12": _sha12(e.get("sha256", "")), "received_at": e.get("received_at"),
                             "built_at": e.get("built_at"), "via": _via_kind(e.get("via")),
                             "used_months": sorted(used.get(_sha12(e.get("sha256", "")), [])),
                             "schema_version": (e.get("meta") or {}).get("schema_version")} for per, e in ents],
                "last_upload_at": max((e.get("received_at") or "" for _p, e in ents), default="") or None,
                "client": next((e.get("client") for _p, e in reversed(ents) if e.get("client")), ""),
                "quality": tp.get("quality") or next((m.get("quality") for m in reversed(meta) if m.get("quality")), ""),
                "flags": flags})
        return {"members": out}

    # ── 로그(키·크기·상태·IP 만) ──────────────────────────────────────────
    def log_line(self, kind: str, text: str) -> None:
        d = self.clock()
        fsx.append_line(self.logs_dir() / f"server_{d:%Y%m%d}.log", f"{iso(d)} [{kind}] {text}")

    def log_upload(self, **rec) -> None:
        rec.setdefault("ts", iso(self.clock()))
        fsx.append_line(self.logs_dir() / "uploads.jsonl", fsx.canon_bytes(rec).decode("utf-8"))
        kb = max(1, (rec.get("bytes") or 0) // 1024)
        self.log_line("upload", f"{rec.get('person_key') or '-'} {rec.get('period_key') or '-'} "
                                f"{(rec.get('sha') or '')[:12] or '-'} {kb}KB {rec.get('status')} {rec.get('ip') or '-'}")

    def log_aggregate(self, text: str) -> None:
        d = self.clock()
        fsx.append_line(self.logs_dir() / f"aggregate_{d:%Y%m%d}.log", f"{iso(d)} {text}")

    def cleanup_logs(self, keep_days: int | None = None) -> int:
        days = self.c("teamServer.logKeepDays") if keep_days is None else keep_days
        cut = self.clock().date() - timedelta(days=days)
        n = 0
        for fn in os.listdir(fsx.longp(self.logs_dir())) if self.logs_dir().is_dir() else ():
            m = LOG_DATE_RX.fullmatch(fn)
            if not m:
                continue
            try:
                d = date(int(m.group(1)[:4]), int(m.group(1)[4:6]), int(m.group(1)[6:]))
            except ValueError:
                continue
            if d < cut:
                try:
                    os.remove(fsx.longp(self.logs_dir() / fn))
                    n += 1
                except OSError:
                    pass
        return n

    def uploads_today(self) -> tuple[int, str | None]:
        """오늘 업로드 수와 마지막 업로드 시각(logs\\uploads.jsonl)."""
        try:
            raw = fsx.read_bytes(self.logs_dir() / "uploads.jsonl")
        except FileNotFoundError:
            return 0, None
        today = self.clock().date().isoformat()
        n, last = 0, None
        for ln in raw.decode("utf-8", "replace").splitlines()[-5000:]:
            try:
                r = fsx.loads_strict(ln)
            except ValueError:
                continue
            if isinstance(r, dict) and r.get("status") == "stored":
                ts = str(r.get("ts") or "")
                last = ts or last
                if ts[:10] == today:
                    n += 1
        return n, last

    # ── 세대(취합 산출) ─────────────────────────────────────────────────
    def gens(self) -> list[int]:
        out = []
        root = self.out_dir()
        for fn in os.listdir(fsx.longp(root)) if root.is_dir() else ():
            m = GEN_RX.fullmatch(fn)
            if m and root.joinpath(fn).is_dir():
                out.append(int(m.group(1)))
        return sorted(out)

    def current_gen(self) -> dict | None:
        cur = fsx.read_json(self.out_current(), None)
        return cur if isinstance(cur, dict) and isinstance(cur.get("gen"), int) else None

    def next_gen(self) -> int:
        cur = self.current_gen()
        return max([0, *self.gens(), (cur or {}).get("gen", 0)]) + 1

    def publish_gen(self, gen: int, result: dict) -> None:
        """성공한 세대를 현재로(``out\\current.json`` 원자 교체 — 디렉터리 rename 없음) + 보관 수 초과분 정리."""
        fsx.atomic_write(self.out_current(), fsx.canon_bytes({
            "gen": int(gen), "dir": f"gen_{int(gen)}", "at": iso(self.clock()), "members": result.get("members", 0),
            "warnings": list(result.get("warnings") or [])[:50], "registry_version": self.registry_version()}))
        self.prune_gens(self.c("teamServer.genKeep"))

    def prune_gens(self, keep: int) -> int:
        cur = (self.current_gen() or {}).get("gen")
        gs = [g for g in self.gens() if g != cur]
        n = 0
        import shutil
        for g in gs[: max(0, len(gs) - max(keep - 1, 0))]:
            try:
                shutil.rmtree(fsx.longp(self.gen_dir(g)))
                n += 1
            except OSError:
                pass                                     # 서빙 중 열려 있으면 다음 회차에
        return n

    def current_file(self, name: str) -> bytes | None:
        """현재 세대의 산출 파일 바이트(team_data.json · details.json · team_report.html · team_report_share.html)."""
        if name not in ("team_data.json", "details.json", "team_report.html", "team_report_share.html", "result.json"):
            raise ValueError("산출 파일 이름이 아닙니다")
        cur = self.current_gen()
        if cur is None:
            return None
        try:
            return fsx.read_bytes(self.gen_dir(cur["gen"]) / name)
        except FileNotFoundError:
            return None


def display_label(pk: str, member_id, self_label, roster: dict, reg_labels: dict) -> tuple[str, str]:
    """표시 라벨 우선순위(TAB §3.11): roster(팀장) > 레지스트리 members[member_id].label > 묶음 self_label > 팀원-<KEY4>.
    반환 (라벨, 출처 roster|member|self|auto)."""
    if (roster.get("labels") or {}).get(pk):
        return roster["labels"][pk], "roster"
    if member_id and reg_labels.get(member_id):
        return reg_labels[member_id], "member"
    if self_label:
        return self_label, "self"
    return "팀원-" + pk[2:6].upper(), "auto"


def _via_kind(v) -> str:
    v = str(v or "")
    return "inbox" if v.startswith("inbox") else (v or "http")


def _valid_current(cur) -> bool:
    if not isinstance(cur, dict):
        return False
    for k, e in cur.items():
        if not (isinstance(k, str) and PERIOD_RX.fullmatch(k) and isinstance(e, dict)
                and isinstance(e.get("sha256"), str) and isinstance(e.get("file"), str)):
            return False
    return True


def _entry_meta(obj: dict) -> dict:
    """current.json 항목에 함께 두는 묶음 요약(사람 연결·명단 표시용 — 팀 묶음에 이미 있는 값만)."""
    pe = obj.get("person") or {}
    q = obj.get("quality") or {}
    return {"self_label": pe.get("self_label") or "", "member_id": pe.get("member_id"),
            "self_peer_key": pe.get("self_peer_key"), "pepper_id": pe.get("pepper_id"),
            "schema_version": obj.get("schema_version"), "quality": q.get("grade") or ""}


def err_body(code: str, msg: str, detail=()) -> dict:
    """오류 응답 형식(TAB §3.6) — 경로·코드만, 값 없음."""
    return {"ok": False, "code": code, "error": msg, "detail": list(detail)[:20]}


def token_ok(given, want_sha: str) -> bool:
    """토큰은 sha256 만 저장 — 비교는 상수 시간."""
    return bool(given) and bool(want_sha) and hmac.compare_digest(fsx.sha256_hex(str(given).encode("utf-8")), want_sha)


# ───────────────────────────── 레지스트리 운반 검증(TAB §3.10) ─────────────────────────────
def _fallback_ukey(s) -> str:
    return " ".join(unicodedata.normalize("NFKC", str(s or "")).split()).casefold()


def resolve_ukey(ukey=None):
    """별칭 정규화 함수 — 주입 > ``lm27.hier.names.ukey``(X-233). 모듈이 아직 없으면 (단순 정규화, 경고 문구)."""
    if ukey is not None:
        return ukey, None
    import importlib.util
    if importlib.util.find_spec("lm27.hier") is not None and importlib.util.find_spec("lm27.hier.names") is not None:
        from lm27.hier.names import ukey as hk
        return hk, None
    return _fallback_ukey, "분류 모듈(lm27.hier.names)이 없어 별칭을 단순 정규화로 비교했습니다"


def registry_transport_errors(reg: dict, *, ukey=None) -> list[tuple[str, str]]:
    """운반·버전 최소 검증 → [(경로, 코드)]. ID 형식·중복·영역 5종·예약 과제(P-99xx → reserved_id)·별칭 중복(ukey)·
    병합 사슬(존재·순환)·달력(날짜·중복·근거 URL·확인일)·크기 ≤ 2MB."""
    out: list[tuple[str, str]] = []
    if reg.get("schema") != REGISTRY_SCHEMA:
        out.append(("schema", "schema"))
    try:
        if len(fsx.canon_bytes(reg)) > REGISTRY_MAX:
            out.append(("", "too_large"))
    except (TypeError, ValueError):
        out.append(("", "schema"))
        return out
    if schema.depth(reg) > schema.MAX_DEPTH:
        out.append(("", "schema"))
        return out
    uk, _w = resolve_ukey(ukey)
    projects = reg.get("projects", [])
    if not isinstance(projects, list):
        out.append(("projects", "schema"))
        projects = []
    ids, alias_owner = {}, {}
    for i, pr in enumerate(projects):
        p = f"projects[{i}]"
        if not isinstance(pr, dict):
            out.append((p, "schema"))
            continue
        pid = pr.get("id")
        if not isinstance(pid, str) or not schema.RX["PROJECT_ID"].fullmatch(pid):
            out.append((f"{p}.id", "bad_id"))
            continue
        if pid.startswith("P-99"):
            out.append((f"{p}.id", "reserved_id"))
            continue
        if pid in ids:
            out.append((f"{p}.id", "dup_id"))
        ids[pid] = pr
        if pr.get("domain") not in schema.DOMAINS:
            out.append((f"{p}.domain", "bad_domain"))
        names = [pr.get("name")] + list(pr.get("aliases") or [])
        for nm in names:
            if not isinstance(nm, str) or not nm.strip():
                continue
            k = uk(nm)
            if k in alias_owner and alias_owner[k] != pid:
                out.append((f"{p}.aliases", "dup_alias"))
                break
            alias_owner[k] = pid
    for i, pr in enumerate(projects):
        if not isinstance(pr, dict) or pr.get("merged_into") in (None, ""):
            continue
        tgt = pr.get("merged_into")
        if tgt not in ids:
            out.append((f"projects[{i}].merged_into", "ref_missing"))
            continue
        seen, cur = {pr.get("id")}, tgt
        while cur in ids and ids[cur].get("merged_into") not in (None, ""):
            if cur in seen:
                break
            seen.add(cur)
            cur = ids[cur].get("merged_into")
        if cur in seen:
            out.append((f"projects[{i}].merged_into", "cycle_merge"))
    for key, prefix in (("members", "M"), ("customers", "C"), ("partners", "V"), ("agents", "AG")):
        lst = reg.get(key, [])
        if not isinstance(lst, list):
            out.append((key, "schema"))
            continue
        seen = set()
        for i, x in enumerate(lst):
            xid = x.get("id") if isinstance(x, dict) else None
            if not isinstance(xid, str) or not schema.RX["REG_ID"].fullmatch(xid) or not xid.startswith(prefix):
                out.append((f"{key}[{i}].id", "bad_id"))
            elif xid in seen:
                out.append((f"{key}[{i}].id", "dup_id"))
            seen.add(xid)
    cal = reg.get("calendar")
    if cal is not None:
        out += _calendar_errors(cal)
    return out


def _calendar_errors(cal) -> list[tuple[str, str]]:
    if not isinstance(cal, dict) or not isinstance(cal.get("years"), list):
        return [("calendar", "schema")]
    out, seen = [], set()
    for yi, y in enumerate(cal["years"]):
        if not isinstance(y, dict) or not isinstance(y.get("holidays"), list):
            out.append((f"calendar.years[{yi}]", "schema"))
            continue
        for hi, h in enumerate(y["holidays"]):
            p = f"calendar.years[{yi}].holidays[{hi}]"
            d = schema.parse_date(h.get("date")) if isinstance(h, dict) else None
            if d is None:
                out.append((p, "bad_date"))
                continue
            if d in seen:
                out.append((p, "dup_date"))
            seen.add(d)
            src, conf = h.get("source_url"), h.get("confirmed")
            if not (isinstance(src, str) and src.startswith("https://")) or schema.parse_date(conf) is None:
                out.append((p, "bad_holiday_source"))
    if not out:
        from lm27.time.calendar import Calendar
        try:
            Calendar.from_obj(cal)
        except ValueError:
            out.append(("calendar", "schema"))
    return out


# ───────────────────────────── 열기·수신 ─────────────────────────────
def open_store(cfg, *, payload_check=None, registry_validator=None, clock=None, paths=None) -> TeamStore:
    """``teamServer.storeDir``(비면 ``%LOCALAPPDATA%\\LoadMonitor27\\teamserver``) 를 연다(없으면 만든다).
    서버 잠금은 잡지 않는다 — ``serve`` 가 ``lock_server()`` 로 따로 잡는다(반입 CLI 는 잠금 여부로 경로를 고른다)."""
    from lm27.paths import Paths
    d = cfg["teamServer.storeDir"] or str((paths or Paths()).teamserver_default())
    pc = payload_check if payload_check is not None else schema.privacy_payload_check(cfg)
    return TeamStore(d, cfg, payload_check=pc, registry_validator=registry_validator, clock=clock,
                     paths=paths).ensure()


def ingest_bytes(store: TeamStore, raw: bytes, *, source: str, claimed_sha: str | None = None, client: str = "",
                 ip: str = "") -> IngestResult:
    """팀 묶음 바이트 하나를 받는다 — HTTP 와 오프라인 반입이 같은 함수(TAB §3.8).

    검증 → 사람 잠금 안에서: 같은 바이트면 already_have · 불변 파일 쓰기 · 늦게 온 옛 빌드면 stale_kept(current 불변) ·
    아니면 current.json 원자 교체(.bak) + 옛 묶음 보관 정리. 응답·로그에 값 없음."""
    sha = fsx.sha256_hex(raw)
    client = _norm_label(client, 20)
    if source == "http" and not claimed_sha:
        return _fail(400, "sha_missing", _FAIL_MSG["sha_missing"])
    if claimed_sha and str(claimed_sha).strip().lower() != sha:
        return _fail(400, "sha_mismatch", _FAIL_MSG["sha_mismatch"])
    if len(raw) > store.c("teamServer.maxBodyMb") * MB:
        return _fail(413, "too_large", _FAIL_MSG["too_large"])
    try:
        obj = schema.loads_bundle(raw)
    except ValueError as e:
        code = "dup_key" if "dup key" in str(e) else "bad_json"
        return _fail(400, code, _FAIL_MSG[code])
    if not isinstance(obj, dict):
        return _fail(400, "not_object", _FAIL_MSG["not_object"])
    if schema.depth(obj) > schema.MAX_DEPTH:
        return _fail(422, "schema", "중첩이 너무 깊습니다", ["$: schema"])
    hits = schema.bytes_guard_hits(raw)
    if hits:
        return _fail(422, "forbidden_content", _FAIL_MSG["forbidden_content"], [f"$bytes: {h}" for h in hits])
    reg = store.registry()
    try:
        cal = store.calendar()
    except (OSError, ValueError):
        cal = None                                       # 달력을 못 읽으면 달력 대조 경고만 빠진다(검증은 계속)
    try:
        errs = schema.validate_team_bundle(obj, reg, "server", calendar=cal, payload_check=store.payload_check,
                                           gap=store.c("teamServer.ganttMergeGapDays"), pepper_id=store.pepper_id)
    except Exception as e:                               # 정제 검사기 실패 = 저장하지 않는다(fail-closed)
        store.log_line("error", f"검사기 실패 {type(e).__name__}")
        return _fail(500, "store_failed", "정제 검사기를 실행하지 못해 저장하지 않았습니다(fail-closed)")
    blk = schema.blocking(errs)
    if blk:
        code = schema.first_code(blk)
        return _fail(422, code, _FAIL_MSG.get(code, "형식 오류"), [e.as_detail() for e in blk])
    warn = sorted({e.code for e in errs if not e.blocking})
    pk, per = obj["person"]["person_key"], schema.period_key_of(obj)
    built = schema.parse_dt(obj["built_at"])
    try:
        with store.person_lock(pk):
            fsx.ensure_dir(store.bundles_dir(pk))
            cur = store.read_current(pk)
            old = cur.get(per) or {}
            if old.get("sha256") == sha:
                store.log_upload(person_key=pk, period_key=per, sha=sha, bytes=len(raw), ip=ip, client=client,
                                 source=source, status="already_have", replaced=None)
                return IngestResult(ok=True, status="already_have", person_key=pk, period_key=per, sha=sha,
                                    warnings=warn)
            fn = f"{per}__{sha[:12]}.json"
            fsx.atomic_write(store.bundles_dir(pk) / fn, raw)                     # ① 불변 묶음(새 이름)
            ob = schema.parse_dt(old.get("built_at")) if old else None
            if ob is not None and built is not None and ob > built:            # ② 옛 빌드 역전 방지
                store.log_upload(person_key=pk, period_key=per, sha=sha, bytes=len(raw), ip=ip, client=client,
                                 source=source, status="stale_kept", replaced=None)
                return IngestResult(ok=True, status="stale_kept", person_key=pk, period_key=per, sha=sha,
                                    warnings=warn)
            new = dict(cur)
            new[per] = {"sha256": sha, "file": fn, "received_at": iso(store.clock()), "built_at": obj["built_at"],
                        "client": client, "via": source, "warn": warn, "meta": _entry_meta(obj)}
            store._write_current(pk, cur, new)                                   # ③ 색인 한 파일 교체
            store.prune_history(pk, per, store.c("teamServer.historyKeep"))
    except OSError as e:
        store.log_line("error", f"저장 실패 {type(e).__name__}")
        return _fail(500, "store_failed", _FAIL_MSG["store_failed"])
    rep = _sha12(old["sha256"]) if old.get("sha256") else None
    store.log_upload(person_key=pk, period_key=per, sha=sha, bytes=len(raw), ip=ip, client=client, source=source,
                     status="stored", replaced=rep)
    return IngestResult(ok=True, status="stored", person_key=pk, period_key=per, sha=sha, replaced=rep, warnings=warn)

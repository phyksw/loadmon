# -*- coding: utf-8 -*-
r"""lint 관문 11 — 팀 서버 주소(서버 IP·포트) 단일원 계약 (LM24 v5).

사용자 지시(2026-10-05): 서버 IP·포트를 따로 빼고, 바꾸는 곳은 별도 bat(LoadMonitor28-팀서버주소.bat) 하나,
폴더를 그대로 옮기면 바뀐 주소가 유지되어 팀원은 분석 후 그 IP 로 올리고 팀 서버는 그 IP 로 취합한다.
계약(어느 하나가 깨지면 패키징 전에 실패한다):
  ① 단일원(정적): 기본 IP 리터럴은 core\teamaddr.py 밖 코드·설정 어디에도 없다 · 파이썬 코드에 기본 포트 숫자
     리터럴이 없다(문서 문자열 제외) · 옛 키(config.teamServerUrl)를 teamaddr 밖에서 읽지 않고 배포 설정에도 없다 ·
     주소를 저장·초기화하는 호출(teamaddr.save/reset)은 teamaddr 밖 어디에도 없다 — 화면은 보여 주기만 한다 ·
     대시보드에 주소를 쓰는 길(/api/teamaddr·/api/teamport)이 없다 · bat 은 입력값을 % 확장으로 명령줄에 끼우지 않는다.
  ② 읽기·쓰기(임시 폴더): 기본값 → 옛 teamServerUrl 이어받기 → 따로 둔 파일이 이김(값마다) · 전각 숫자 정리 ·
     틀린 값은 저장하지 않음(파일 바이트 불변) · 깨진 파일·틀린 값 하나는 경고만 · 초기화 · CLI(--show/--set/--set-env).
  ③ 폴더 이동: 설치 폴더를 통째로 복사하면 같은 주소가 그대로 읽힌다(설정이 폴더 안에만 있다).
  ④ 끝단 연결: 팀 서버(teamserver.py)는 설정된 포트로 모든 네트워크에 연다 · 팀원 PC(teamup.py --ping)는 자기 설치
     폴더의 설정 주소로 그 서버에 닿는다 · --port 일회성 인자는 설정을 바꾸지 않는다.
  ⑤ 배포: .gitignore 에 config/team_server.json · NEED 에 새 파일 · 배포본·PC 이동 묶음이 주소 파일을 담는다.
사용: python tools/check_teamaddr.py   (exit 0/1 · 저장소 무변경 — 임시 폴더에서 돈다. 서버는 이 프로세스 안에서
     루프백에만 실제로 열어 방화벽 허용 창을 띄우지 않는다 — 요청한 주소가 (0.0.0.0, 설정 포트)인지는 따로 본다)
"""
import ast
import contextlib
import importlib.util
import io
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
fail = 0


def _say(msg):
    os.write(1, (msg + chr(10)).encode("utf-8", "replace"))


def bad(msg):
    global fail
    fail = 1
    _say("[teamaddr] " + msg)


def _load_teamaddr(root):
    spec = importlib.util.spec_from_file_location(f"lm_teamaddr_{abs(hash(root))}", os.path.join(root, "core", "teamaddr.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


TA = _load_teamaddr(ROOT)
HOST0, PORT0, LEGACY, BAT = TA.DEFAULT_HOST, TA.DEFAULT_PORT, TA.LEGACY_KEY, TA.EDIT_BAT
PORT_RX = re.compile(r"(?<![\d.])" + str(PORT0) + r"(?!\d)")
SKIP_DIRS = {"python", "data", "report", "teamdata", ".git", "__pycache__", ".ruff_cache", "samples", "lm20_ref"}
CODE_EXT = {".py", ".bat", ".cmd", ".ps1", ".js", ".json", ".html"}
OWN = {os.path.join("core", "teamaddr.py"), os.path.join("tools", "check_teamaddr.py")}


# ── ① 단일원(정적) ────────────────────────────────────────────────────────────
def _files():
    for r, ds, fs in os.walk(ROOT):
        ds[:] = [d for d in ds if d not in SKIP_DIRS]
        for f in fs:
            if os.path.splitext(f)[1].lower() in CODE_EXT:
                p = os.path.join(r, f)
                yield p, os.path.relpath(p, ROOT)


def _read_text(p):
    b = open(p, "rb").read()
    for enc in ("utf-8-sig", "cp949"):
        try:
            return b.decode(enc)
        except UnicodeDecodeError:
            continue
    return b.decode("utf-8", "replace")


def _docstrings(tree):
    ids = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            body = getattr(node, "body", [])
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) \
                    and isinstance(body[0].value.value, str):
                ids.add(id(body[0].value))
    return ids


def _comment_line(rel, ln):
    t = ln.strip().lower()
    ext = os.path.splitext(rel)[1].lower()
    if ext in (".bat", ".cmd"):
        return t.startswith("rem ") or t == "rem" or t.startswith("::")
    if ext == ".ps1":
        return t.startswith("#")
    if ext == ".js":
        return t.startswith("//") or t.startswith("*") or t.startswith("/*")
    return False


SAVE_RX = re.compile(r"\b(?:teamaddr|_ta\(\)|ta)\s*\.\s*(?:save|reset)\s*\(")


def check_static():
    n = 0
    for p, rel in _files():
        n += 1
        txt = _read_text(p)
        own = rel in OWN
        if not own and HOST0 in txt:
            ln = next(i for i, x in enumerate(txt.splitlines(), 1) if HOST0 in x)
            bad(f"{rel}:{ln}: 기본 서버 IP 리터럴 — core\\teamaddr.py(DEFAULT_HOST)만 가진다")
        if rel.split(os.sep)[0] == "tests":
            continue        # 시험은 계약 값(기본 포트 등)을 단언한다 — 기본 IP 리터럴 검사(위)만 받는다
        ext = os.path.splitext(rel)[1].lower()
        if ext == ".py" and not own:
            try:
                tree = ast.parse(txt)
            except SyntaxError as e:
                bad(f"{rel}: 파이썬 구문 오류 — {e}")
                continue
            docs = _docstrings(tree)
            for node in ast.walk(tree):
                if not isinstance(node, ast.Constant):
                    continue
                v = node.value
                if isinstance(v, int) and not isinstance(v, bool) and v == PORT0:
                    bad(f"{rel}:{node.lineno}: 기본 포트 숫자 리터럴 {PORT0} — teamaddr.DEFAULT_PORT 를 쓴다")
                elif isinstance(v, str) and id(node) not in docs:
                    if PORT_RX.search(v):
                        bad(f"{rel}:{node.lineno}: 문자열 안 기본 포트 {PORT0} — teamaddr 에서 받아 쓴다")
                    if LEGACY in v:
                        bad(f"{rel}:{node.lineno}: 옛 키 {LEGACY} 를 teamaddr 밖에서 읽는다 — teamaddr.load() 를 쓴다")
            for i, ln in enumerate(txt.splitlines(), 1):
                if SAVE_RX.search(ln) and not ln.lstrip().startswith("#"):
                    bad(f"{rel}:{i}: 주소 저장·초기화 호출 — 바꾸는 곳은 {BAT} 하나다")
        elif ext in (".bat", ".cmd", ".ps1", ".js", ".html"):
            for i, ln in enumerate(txt.splitlines(), 1):
                if _comment_line(rel, ln):
                    continue
                if LEGACY in ln:
                    bad(f"{rel}:{i}: 옛 키 {LEGACY} — 주소는 teamaddr 가 준다")
                if PORT_RX.search(ln):
                    bad(f"{rel}:{i}: 기본 포트 {PORT0} 하드코딩 — teamaddr 에서 받아 쓴다")
        elif ext == ".json":
            if re.search(r'"' + LEGACY + r'"\s*:', txt):
                bad(f"{rel}: 배포 설정에 옛 키 {LEGACY} 가 있다 — 주소는 config\\team_server.json(teamaddr)")
    app = _read_text(os.path.join(ROOT, "ui", "app.py"))
    for route in ('"/api/teamaddr"', '"/api/teamport"'):
        if route in app:
            bad(f"ui\\app.py: 주소를 바꾸는 길 {route} — 화면은 보여 주기만 한다({BAT} 하나)")
    bp = os.path.join(ROOT, BAT)
    if not os.path.exists(bp):
        bad(f"{BAT} 가 없다 — 서버 IP·포트를 바꾸는 유일한 길")
    else:
        bt = open(bp, "rb").read().decode("cp949")
        if "core\\teamaddr.py --set-env" not in bt:
            bad(f"{BAT}: core\\teamaddr.py --set-env 로 저장하지 않는다")
        for v in ("%LM28_TA_HOST%", "%LM28_TA_PORT%"):
            if v in bt:
                bad(f"{BAT}: 입력값 {v} 를 % 확장으로 명령줄에 끼운다 — 환경변수로만 넘긴다")
    return n


# ── ② 읽기·쓰기 ───────────────────────────────────────────────────────────────
def _tmp_root():
    d = tempfile.mkdtemp(prefix="lm28_ta_")
    os.makedirs(os.path.join(d, "config"))
    return d


def _write(p, obj):
    with open(p, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False)


def _eq(what, got, want):
    if got != want:
        bad(f"{what}: {got!r} != {want!r}")


def check_rw():
    d = _tmp_root()
    try:
        a = TA.load(d)
        _eq("빈 폴더 기본값", (a.host, a.port, a.source, a.file), (HOST0, PORT0, {"host": "default", "port": "default"}, ""))
        cfgp = os.path.join(d, "config", "config.json")
        _write(cfgp, {LEGACY: "http://10.1.2.3:19310"})
        a = TA.load(d)
        _eq("옛 키 이어받기", (a.host, a.port, a.source["host"], a.source["port"]), ("10.1.2.3", 19310, "legacy", "legacy"))
        _write(cfgp, {LEGACY: "http://10.1.2.3"})
        a = TA.load(d)
        _eq("옛 키(포트 없음)", (a.host, a.port, a.source["port"]), ("10.1.2.3", PORT0, "default"))
        _write(cfgp, {LEGACY: "zz::/"})
        a = TA.load(d)
        _eq("깨진 옛 키 → 기본값", (a.host, a.port), (HOST0, PORT0))
        if not a.warnings:
            bad("깨진 옛 키에 경고가 없다")
        _write(cfgp, {LEGACY: "http://10.1.2.3:19310"})
        ok, err, a = TA.save(d, host="１０．０．０．５", port="９４００")
        _eq("전각 입력 저장", (ok, a.host, a.port, a.source["host"], a.source["port"]), (True, "10.0.0.5", 9400, "file", "file"))
        fp = os.path.join(d, "config", TA.FILE_NAME)
        doc = json.load(open(fp, encoding="utf-8"))
        extra = set(doc) - {"_설명", "host", "port", "saved_at"}
        if extra:
            bad(f"주소 파일에 주소 밖 키: {sorted(extra)}")
        _write(fp, {"port": 9555})
        a = TA.load(d)
        _eq("부분 파일(포트만) — 서버 IP 는 옛 키", (a.host, a.port, a.source["host"], a.source["port"]),
            ("10.1.2.3", 9555, "legacy", "file"))
        TA.save(d, host="10.0.0.5", port=9400)
        before = open(fp, "rb").read()
        for kw in ({"port": 70000}, {"port": "abc"}, {"port": True}, {"host": "10.0.0.256"}, {"host": "a&b"},
                   {"host": "10.0.0.5:9310"}, {"host": "١٠.0.0.5"}, {"host": ""}, {"host": "010.0.0.5"}):
            ok, err, _a = TA.save(d, **kw)
            if ok or not err:
                bad(f"틀린 값을 저장했다: {kw}")
            if open(fp, "rb").read() != before:
                bad(f"틀린 값 {kw} 에 주소 파일이 바뀌었다")
        _eq("split_input(URL)", TA.split_input("http://192.168.1.20:9555/", ""), ("192.168.1.20", 9555, ""))
        _eq("split_input(포트 칸 우선)", TA.split_input("10.0.0.5:9555", "9600"), ("10.0.0.5", 9600, ""))
        _eq("split_input(빈 칸)", TA.split_input("", ""), (None, None, ""))
        open(fp, "w", encoding="utf-8").write("{깨짐")
        a = TA.load(d)
        _eq("깨진 파일 → 옛 키", (a.host, a.port), ("10.1.2.3", 19310))
        if not a.warnings:
            bad("깨진 주소 파일에 경고가 없다")
        _write(fp, {"host": "10.0.0.7", "port": "x"})
        a = TA.load(d)
        _eq("틀린 값 하나만 버림", (a.host, a.port), ("10.0.0.7", 19310))
        if not any("port" in w for w in a.warnings):
            bad("틀린 포트 값에 경고가 없다")
        ok, _e = TA.reset(d)
        a = TA.load(d)
        _eq("초기화 → 옛 키", (ok, os.path.exists(fp), a.host, a.port), (True, False, "10.1.2.3", 19310))
        # CLI — bat 이 부르는 그대로
        env = dict(os.environ, PYTHONIOENCODING="utf-8")
        env.pop("LM28_TA_HOST", None)
        env.pop("LM28_TA_PORT", None)

        def cli(*args, extra_env=None):
            r = subprocess.run([sys.executable, "-X", "utf8", "-B", os.path.join(ROOT, "core", "teamaddr.py"),
                                "--root", d, *args], capture_output=True, timeout=60,
                               env=dict(env, **(extra_env or {})))
            return r.returncode, r.stdout.decode("utf-8", "replace")
        rc, out = cli("--show", "--json")
        try:
            js = json.loads(out.strip().splitlines()[-1])
        except (ValueError, IndexError):
            js = {}
        _eq("CLI --show --json", (rc, js.get("host"), js.get("port")), (0, "10.1.2.3", 19310))
        _eq("CLI --set --port abc → rc 1", cli("--set", "--port", "abc")[0], 1)
        _eq("CLI --set(값 없음) → rc 2", cli("--set")[0], 2)
        rc, out = cli("--set-env", "--json", extra_env={"LM28_TA_HOST": "http://10.9.9.9:9411"})
        a = TA.load(d)
        _eq("CLI --set-env(bat 경로)", (rc, a.host, a.port), (0, "10.9.9.9", 9411))
        rc, out = cli("--set-env", "--json")
        _eq("CLI --set-env(빈 입력 → 그대로)", (rc, TA.load(d).url), (0, "http://10.9.9.9:9411"))
        rc, out = cli("--set-env", extra_env={"LM28_TA_HOST": "a&echo X"})
        _eq("CLI --set-env(특수문자 거부)", (rc, TA.load(d).url), (1, "http://10.9.9.9:9411"))
        # ③ 폴더 이동 — 설치 폴더를 통째로 복사하면 같은 주소가 그대로 읽힌다
        moved = d + "_moved"
        shutil.copytree(d, moved)
        try:
            b = TA.load(moved)
            _eq("폴더 이동 후 주소 유지", (b.host, b.port, b.source["host"]), ("10.9.9.9", 9411, "file"))
        finally:
            shutil.rmtree(moved, ignore_errors=True)
    finally:
        shutil.rmtree(d, ignore_errors=True)


# ── ④ 끝단 연결: 팀 서버 ↔ 팀원 업로드 ─────────────────────────────────────────
def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _copy_program(dst):
    os.makedirs(os.path.join(dst, "config"), exist_ok=True)
    shutil.copytree(os.path.join(ROOT, "core"), os.path.join(dst, "core"),
                    ignore=shutil.ignore_patterns("__pycache__"))
    for f in ("teamserver.py", "teamup.py"):
        shutil.copy2(os.path.join(ROOT, f), os.path.join(dst, f))


def check_end_to_end():
    srv_root, mem_root = tempfile.mkdtemp(prefix="lm28_srv_"), tempfile.mkdtemp(prefix="lm28_mem_")
    th, mod, port = None, None, _free_port()
    try:
        _copy_program(srv_root)
        _copy_program(mem_root)
        ta_s, ta_m = _load_teamaddr(srv_root), _load_teamaddr(mem_root)
        ta_s.save(srv_root, host="127.0.0.1", port=port)          # 서버 PC: 이 PC(루프백)의 port
        ta_m.save(mem_root, host="127.0.0.1", port=port)          # 팀원 PC: 같은 주소 파일을 받은 상태
        spec = importlib.util.spec_from_file_location("lm28_teamserver_probe", os.path.join(srv_root, "teamserver.py"))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        asked = []

        # LM28 의 teamserver 는 배타 bind 서버(ExclusiveServer — ThreadingHTTPServer 하위)로 연다. 실제로 만드는 클래스를 바꿔 끼운다
        base_name = "ExclusiveServer" if hasattr(mod, "ExclusiveServer") else "ThreadingHTTPServer"
        base = getattr(mod, base_name)

        class LoopbackOnly(base):
            def __init__(self, addr, handler):
                asked.append(tuple(addr))
                super().__init__(("127.0.0.1", addr[1]), handler)
        setattr(mod, base_name, LoopbackOnly)
        buf = io.StringIO()
        result = {}

        def run():
            old = sys.argv
            sys.argv = ["teamserver.py"]
            try:
                with contextlib.redirect_stdout(buf):
                    result["rc"] = mod.main()
            except Exception as e:      # 서버가 죽은 사유를 관문 출력으로 옮긴다
                result["exc"] = repr(e)
            finally:
                sys.argv = old
        th = threading.Thread(target=run, daemon=True)
        th.start()
        up = False
        for _ in range(100):
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                    up = True
                    break
            except OSError:
                time.sleep(0.05)
        if not up:
            bad(f"팀 서버가 설정 포트 {port} 로 뜨지 않았다 — {result} {buf.getvalue()[-300:]}")
            return
        _eq("팀 서버가 요청한 주소(모든 네트워크·설정 포트)", asked[:1], [("0.0.0.0", port)])
        if f"팀원 업로드 주소(설정): http://127.0.0.1:{port}" not in buf.getvalue():
            bad("팀 서버가 시작할 때 설정된 팀원 업로드 주소를 알리지 않았다")
        env = dict(os.environ, PYTHONIOENCODING="utf-8", NO_PROXY="127.0.0.1,localhost", no_proxy="127.0.0.1,localhost")

        def ping(*extra):
            r = subprocess.run([sys.executable, "-X", "utf8", "-B", os.path.join(mem_root, "teamup.py"),
                                "--ping", "--json", *extra], capture_output=True, timeout=60, env=env, cwd=mem_root)
            try:
                return json.loads(r.stdout.decode("utf-8", "replace").strip().splitlines()[-1])
            except (ValueError, IndexError):
                return {"raw": r.stdout.decode("utf-8", "replace")[-300:], "err": r.stderr.decode("utf-8", "replace")[-300:]}
        j = ping()
        _eq("팀원 PC → 설정 주소로 팀 서버에 닿음", (j.get("ok"), j.get("url")), (True, f"http://127.0.0.1:{port}"))
        other = _free_port()
        before = open(ta_m.path(mem_root), "rb").read()
        j = ping("--port", str(other))
        _eq("--port 일회성 인자", j.get("url"), f"http://127.0.0.1:{other}")
        if open(ta_m.path(mem_root), "rb").read() != before:
            bad("teamup.py --port 일회성 인자가 주소 설정을 바꿨다")
    finally:
        if mod is not None and getattr(mod, "SRV", [None])[0] is not None:
            try:
                mod.SRV[0].shutdown()
            except OSError:
                pass
        if th is not None:
            th.join(10)
        shutil.rmtree(srv_root, ignore_errors=True)
        shutil.rmtree(mem_root, ignore_errors=True)


# ── ⑤ 배포 ───────────────────────────────────────────────────────────────────
def check_dist():
    gi = _read_text(os.path.join(ROOT, ".gitignore"))
    if "config/team_server.json" not in gi.splitlines():
        bad(".gitignore 에 config/team_server.json 이 없다 — 개발 PC 의 주소가 저장소에 들어간다")
    src = _read_text(os.path.join(ROOT, "자가점검.py"))
    need = []
    for node in ast.parse(src).body:
        if isinstance(node, ast.Assign) and getattr(node.targets[0], "id", "") == "NEED":
            need = list(ast.literal_eval(node.value))
    for f in (BAT, "core/teamaddr.py", "tools/check_teamaddr.py"):
        if f not in need:
            bad(f"자가점검.py NEED 에 {f} 가 없다 — 배포본에 빠진다")
    if "config/team_server.json" in need:
        bad("NEED 에 config/team_server.json — 없는 PC 도 있는 선택 파일이라 NEED 에 두면 자가점검이 실패한다")
    mp = _read_text(os.path.join(ROOT, "tools", "Make-Package.ps1"))
    if "config\\team_server.json" not in mp or "팀 서버 주소 동봉" not in mp:
        bad("Make-Package.ps1 이 config\\team_server.json 을 담지 않는다 — 나눠 준 배포본이 기본 주소로 올린다")
    mv = _read_text(os.path.join(ROOT, "tools", "Make-MovePack.py"))
    if 'for rel in ("data", "config"):' not in mv:
        bad("Make-MovePack.py 가 config\\ 를 통째로 담지 않는다 — PC 이동 후 주소가 사라진다")


def main():
    n = check_static()
    check_rw()
    check_end_to_end()
    check_dist()
    if not fail:
        _say(f"[teamaddr] OK — 단일원(파일 {n}개)·읽기쓰기·폴더 이동·서버↔업로드 끝단·배포")
    return fail


if __name__ == "__main__":
    sys.exit(main())

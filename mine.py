# -*- coding: utf-8 -*-
r"""
mine.py — 정제된 메일·일정에서 업무 분류 초안을 만든다(AgentFinder32 분석 첫 단계 · Agentic AI 전환 과제 발굴용).

  python mine.py <수집데이터폴더> [--from 2026-08-01] [--to 2026-10-31]

  · 시작 검사: 설치 위치·옛 LoadMonitor 파일(core\install.startup_check — 막히면 종료 4) → 내 자료인지(core\consent.require —
    다른 사용자의 자료면 종료 4 · 지우는 중이면 3) → 제한 고객 목록(core\privacy.load_restricted — 없으면 종료 4).
  · 기간은 core\period.clamp 로 맞춘다(어제까지 · 최대 period.maxDays 일). 잘렸으면 한 줄로 알린다.
  · --name · --func 는 받기만 하고 쓰지 않는다(Function 은 config.function).

출력(report\ — 날짜만, 시각 없음)
  work_rows_<기간>.csv   Function,Level 1,유형,Level 2,Level 3,상세설명,근거건수,근거,확신도,ax,field,share
  evidence_<기간>.md     '## 과제 / 세부업무 — 근거 N건' + '- MM-DD 글' 줄
  signals_<기간>.csv     time,source,who,project,activity,weight,text,flag
  run_meta_<기간>.json   {"product","tag","period","clamped","generated","signals","counted","excluded","weights",
                          "restricted_sha256","config_warnings"}

종료 코드: 0 정상 · 1 오류 · 2 신호 0건 · 3 지우는 중 · 4 시작 거부(다른 사용자의 자료·설치 위치·옛 파일·제한 고객 목록) · 5 결과 파일이 열려 있음
"""
import csv
import io
import json
import os
import sys
from datetime import date

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(ROOT, "core"))
from progress import progress  # noqa: E402
import afcfg  # noqa: E402
import consent  # noqa: E402
import details  # noqa: E402  - 과제명 관문(사람·공지)·지난 체계(entities)·상위 채움
import extract  # noqa: E402
import install  # noqa: E402
import lmname  # noqa: E402
import period  # noqa: E402
import privacy  # noqa: E402

RC_OK, RC_FAIL, RC_EMPTY, RC_CONSENT, RC_REFUSED, RC_LOCKED = 0, 1, 2, 3, 4, 5
WORK_COLS = ["Function", "Level 1", "유형", "Level 2", "Level 3", "상세설명", "근거건수", "근거", "확신도", "ax", "field",
             "share"]
SIGNAL_COLS = ["time", "source", "who", "project", "activity", "weight", "text", "flag"]


def _wrap_stdout():
    """콘솔(bat)=콘솔 코드페이지 · 파이프(UI)=utf-8. 스크립트로 돌 때만 바꿔 끼운다(임포트만으로 sys.stdout 을 바꾸지 않는다)."""
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, errors="replace", encoding=(
        (sys.stdout.encoding or "utf-8") if sys.stdout.isatty() else "utf-8"))


def arg(flag, dflt=""):
    return sys.argv[sys.argv.index(flag) + 1] if flag in sys.argv[:-1] else dflt


def positional(argv):
    """플래그와 그 값을 뺀 위치 인자(--name·--func 의 값이 수집 폴더로 잡히지 않게)."""
    out, skip = [], False
    for a in argv:
        if skip:
            skip = False
            continue
        if a.startswith("--"):
            skip = a in ("--from", "--to", "--name", "--func")
            continue
        out.append(a)
    return out


def known_projects(cfg, people=()):
    """규칙 기준선이 쓸 과제 — config 지정 + 화면 지정(projects.json) + **이전 판정에서 발견된 과제**.
    entities 는 최신부터 훑어 규칙 폴백 산출물을 건너뛰고(details.newest_entities), 거기서 온 이름이 사람 이름·공지류면 버린다.
    returns [{"name", "match"[], "l1", "pinned"}] — l1 = 상위(지정 level1 > entities l1, 고정 범주로 스냅, 없으면 "")."""
    out, idx = [], {}

    def add(name, match=(), l1="", pinned=False):
        name = str(name or "").strip()
        if not name or name == "공통":
            return
        alts = [str(k).strip() for k in (match or []) if str(k).strip()]
        l1 = details.snap1(l1) if l1 else ""
        key = details.ukey2(name)
        if key in idx:                    # 같은 과제가 여러 출처면 별칭을 합친다
            cur = out[idx[key]]
            for a in alts:
                if a.lower() not in {x.lower() for x in cur["match"]}:
                    cur["match"].append(a)
            if l1 and (pinned or not cur["l1"]):       # 사람이 정한 상위가 이긴다
                cur["l1"] = l1
            cur["pinned"] = cur["pinned"] or pinned
            return
        idx[key] = len(out)
        out.append({"name": name, "match": alts, "l1": l1, "pinned": pinned})

    for p in extract.cfg_list(cfg, "projects"):
        if isinstance(p, dict):
            add(p.get("name"), p.get("match") or [])
        else:
            add(p)
    try:
        import projmap
        for p in projmap.load_user_projects(ROOT):
            add(p.get("name"), p.get("match") or [], p.get("level1") or "", pinned=True)
    except Exception as e:  # noqa: BLE001
        print(f"[mine] 지정 과제 로드 건너뜀({type(e).__name__})")
    try:
        ent, _fp = details.newest_entities(os.path.join(ROOT, "report"))
        for m in ent.get("models") or []:
            if not isinstance(m, dict):
                continue
            nm = str(m.get("name") or "").strip()
            if details.ukey2(nm) not in idx and not details.task_name_ok(nm, people):
                continue                      # 사람 이름·공지류 — 과제가 아니다
            add(nm, m.get("match") or [], m.get("l1") or "")
    except (OSError, ValueError, AttributeError, TypeError):
        pass
    return out


def _locked_writes(jobs):
    """결과 파일을 임시파일에 쓴 뒤 교체한다. Excel 등이 파일을 열어 두면(Windows 잠금) 교체가 실패한다 — 잠긴 파일은
    건너뛰고 나머지는 마저 쓴 뒤 잠긴 이름 목록을 돌려준다. 임시파일 이름에 pid 를 붙인다(같은 폴더의 동시 실행 대비)."""
    import glob as _glob
    import time as _time
    locked = []
    for path, writer in jobs:
        for old in _glob.glob(_glob.escape(path) + ".*.tmp"):     # 죽은 실행이 남긴 임시파일만(10분 이상)
            try:
                if _time.time() - os.path.getmtime(old) > 600:
                    os.remove(old)
            except OSError:
                pass
        tmp = f"{path}.{os.getpid()}.tmp"
        with open(tmp, "w", encoding=("utf-8-sig" if path.endswith(".csv") else "utf-8"),
                  newline=("" if path.endswith(".csv") else None)) as f:
            writer(f)
        try:
            os.replace(tmp, path)
        except OSError:
            locked.append(os.path.basename(path))
            try:
                os.remove(tmp)
            except OSError:
                pass
    return locked


def collect_excluded(data_dir):
    r"""data\outlook\collect_summary.json(§5.3)의 수집 때 제외 건수 — 없거나 깨졌으면 0."""
    out = dict.fromkeys(extract.COLLECT_EXCLUDED_KEYS, 0)
    try:
        with open(os.path.join(data_dir, "outlook", "collect_summary.json"), encoding="utf-8-sig") as f:
            doc = json.load(f)
        ex = doc.get("excluded") if isinstance(doc, dict) else None
    except (OSError, ValueError):
        ex = None
    if isinstance(ex, dict):
        for k in out:
            try:
                out[k] = max(0, int(ex.get(k) or 0))
            except (TypeError, ValueError):
                out[k] = 0
    return out


def excluded_doc(collected, analysed):
    """run_meta.excluded — 수집 때 칸(§5.3)은 수집 건수 + 분석 때 같은 규칙으로 다시 뺀 건수, 그 뒤 분석 때만 생기는 칸."""
    out = {k: int(collected.get(k, 0)) + int(analysed.get(k, 0)) for k in extract.COLLECT_EXCLUDED_KEYS}
    out.update({k: int(analysed.get(k, 0)) for k in extract.ANALYSIS_EXCLUDED_KEYS})
    return out


def meta_doc(d0, d1, info, sig, meta, excluded, restricted_sha256, cfg_warns, *, today=None):
    """run_meta_<기간>.json 본문(spec §5.6) — 시간·MM·가용·부하·날짜 목록은 없다."""
    return {"product": lmname.PRODUCT, "tag": period.tag_of(d0, d1),
            "period": {"from": d0.isoformat(), "to": d1.isoformat()},
            "clamped": info if (isinstance(info, dict) and info.get("clamped")) else None,
            "generated": (today or date.today()).isoformat(),
            "signals": len(sig),
            "counted": {k: int(meta["counted"].get(k, 0)) for k in ("mail_in", "mail_out", "meetings")},
            "excluded": excluded,
            "weights": dict(meta["weights"]),
            "restricted_sha256": restricted_sha256,
            "config_warnings": list(cfg_warns)}


def run_clamp(info):
    """run.py 가 이미 줄인 기간을 넘기면(환경 AF32_CLAMP = period.clamp 의 info JSON) 그 줄임 정보를 쓴다 —
    넘겨받은 날짜로 다시 재면 늘 '안 줄임'이 되어 run_meta.clamped 가 비었다(D2)."""
    raw = os.environ.get("AF32_CLAMP") or ""
    if not raw:
        return info
    try:
        got = json.loads(raw)
    except ValueError:
        return info
    if isinstance(got, dict) and got.get("clamped") and isinstance(got.get("requested"), dict):
        return got
    return info


def main():
    args = positional(sys.argv[1:])
    if not args:
        print(__doc__)
        return RC_EMPTY
    data_dir = os.path.abspath(args[0])
    # ── 시작 검사 ─────────────────────────────────────────────────────────────────────
    msg = install.startup_check(ROOT)
    if msg:
        print(f"[mine] {msg}")
        return RC_REFUSED
    cfg_raw = afcfg.load(ROOT)
    cfg, eff_warns = afcfg.effective(cfg_raw)
    try:
        consent.require(ROOT, cfg_raw)
    except consent.ConsentRequired as e:
        print(f"[mine] {e.message}")
        return RC_REFUSED if getattr(e, "code", RC_CONSENT) == RC_REFUSED else RC_CONSENT
    try:
        d0, d1, info = period.clamp(arg("--from") or None, arg("--to") or None, cfg)
    except ValueError as e:
        print(f"[mine] {e}")
        return RC_FAIL
    from_run = bool(os.environ.get("AF32_CLAMP"))
    info = run_clamp(info)
    note = period.notice_text(info, d0, d1, cfg)
    if note and not from_run:                # run.py 가 넘긴 기간이면 run.py 가 이미 알렸다
        print(f"[기간] {note}")
    try:
        restricted = privacy.load_restricted(cfg, ROOT)
    except privacy.RestrictedListError as e:
        print(f"[mine] {e.message}")
        return RC_REFUSED

    progress("신호 수집", 0, 3)
    sig, meta = extract.load_signals(data_dir, d0, d1, privacy.excluded_keywords(cfg), cfg, restricted=restricted)
    cfg_warns = list(dict.fromkeys(list(eff_warns) + list(meta.get("config_warnings") or [])))
    for w in cfg_warns:
        print(f"[설정] {w}")
    if meta.get("unreadable"):
        print(f"[mine] 날짜를 읽지 못한 행 {meta['unreadable']}개는 건너뛰었습니다")
    if not sig:
        print(f"[mine] 신호 0건 — {d0}~{d1} 기간의 메일·일정이 없습니다(수집 폴더: {data_dir})")
        return RC_EMPTY
    c = meta["counted"]
    print(f"[mine] {d0}~{d1} · 신호 {len(sig)}건 (받은 메일 {c['mail_in']} · 보낸 메일 {c['mail_out']} · 회의 {c['meetings']})")
    ex = excluded_doc(collect_excluded(data_dir), meta["excluded"])
    if any(ex.values()):
        print("[출처] 제외: " + ", ".join(f"{k} {v}" for k, v in ex.items() if v))
    progress("신호 수집", 1, 3)

    # 과제명 관문 — 사람 키는 신호 who(가명·'나' 뿐이라 대개 비어 있다)와 G1 이 남긴 이름 해시(data\cache\name_hashes.json)에서
    # 얻는다. 상위는 지정 > 지난 체계 > 규칙.
    people = details.person_keys((s[4] for s in sig), ROOT)
    kp = known_projects(cfg, people)
    progress("신호 수집", 2, 3)
    items, assigns = extract.build_items2(sig, kp)
    rows = extract.to_rows(items, str(afcfg.get(cfg, "function") or ""),
                           l1_map={details.ukey2(p["name"]): p["l1"] for p in kp if p.get("l1")},
                           pin={details.ukey2(p["name"]): p["l1"] for p in kp if p.get("pinned") and p.get("l1")})
    progress("신호 수집", 3, 3)
    print(f"[mine] 업무 항목 {len(rows)}개\n")
    print(f"{'Level 2 (과제)':26s} {'Level 3 (세부업무)':18s} {'근거':>5s} 확신 근거 갈래")
    print("-" * 80)
    for r in rows[:20]:
        print(f"{r['Level 2'][:25]:26s} {r['Level 3'][:17]:18s} {r['근거건수']:5d}  {r['확신도']}  {r['근거'][:30]}")

    out_dir = os.path.join(ROOT, "report")
    os.makedirs(out_dir, exist_ok=True)
    tag = period.tag_of(d0, d1)
    out = os.path.join(out_dir, f"work_rows_{tag}.csv")
    ev = os.path.join(out_dir, f"evidence_{tag}.md")
    sp = os.path.join(out_dir, f"signals_{tag}.csv")
    meta_path = os.path.join(out_dir, f"run_meta_{tag}.json")

    def _w_rows(f):
        w = csv.DictWriter(f, fieldnames=WORK_COLS, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in WORK_COLS})

    def _w_ev(f):
        for r in rows:
            f.write(f"## {r['Level 2']} / {r['Level 3']} — 근거 {r['근거건수']}건\n")
            for x in r["evidence"]:
                f.write(f"- {x}\n")
            f.write("\n")

    def _w_sig(f):
        w = csv.writer(f)
        w.writerow(SIGNAL_COLS)
        for t, src, text, wt, who, proj, act in assigns:
            w.writerow([t.strftime("%Y-%m-%d"), src, who, proj, extract._one_line(act), round(wt, 3),
                        extract._one_line(text, 100), ""])

    def _w_meta(f):
        json.dump(meta_doc(d0, d1, info, sig, meta, ex, restricted.sha256, cfg_warns), f, ensure_ascii=False, indent=1)

    locked = _locked_writes([(out, _w_rows), (ev, _w_ev), (sp, _w_sig), (meta_path, _w_meta)])
    if locked:
        print(f"[mine] 저장 실패(다른 프로그램에서 열려 있음 — Excel 등, 또는 같은 폴더에서 다른 분석이 "
              f"동시에 실행 중): {', '.join(locked)}")
        print("       그 파일을 닫거나 다른 분석이 끝난 뒤 다시 실행하세요 — 닫지 않으면 화면이 낡은 값을 보여줍니다.")
        return RC_LOCKED
    print(f"\n[mine] 행 → {out}\n[mine] 근거 → {ev}\n[mine] 실행 정보 → {meta_path}")
    return RC_OK


if __name__ == "__main__":
    _wrap_stdout()
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except Exception:                # 어떤 예외든 '신호 0건'으로 오진되지 않게 코드를 구분한다
        import traceback
        traceback.print_exc()        # 전문은 UI 로그로
        print(f"[mine] 오류로 중단: {sys.exc_info()[0].__name__}: {sys.exc_info()[1]}")
        sys.exit(RC_FAIL)

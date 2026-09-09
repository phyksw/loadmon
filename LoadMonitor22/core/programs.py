# -*- coding: utf-8 -*-
"""프로그램 사용 이력 — 작업창 샘플러가 적은 process 이름을 '무슨 프로그램인가' 로 옮기는 표.

무엇을 위한 표인가
    data\\activity\\activity_YYYYMMDD.csv 의 process 열(맨 앞 창의 실행 파일 이름, 소문자,
    확장자 없음)은 그 사람이 실제로 무엇을 띄워 놓고 일했는지의 직접 증거다. 파일 확장자
    (EXT_ACT)는 '무슨 산출물을 냈나' 를 말해 주지만, 라이선스가 비싼 상용 해석기를 몇 시간
    붙잡고 있었는지는 말해 주지 못한다 — 해석 한 번에 결과 파일 한 개인 경우가 흔하다.

이 표는 시간 계산에 쓰지 않는다
    ★ 여기서 나온 값은 MM 배분·로드율에 절대 들어가지 않는다. load_signals 의 신호로 만들면
      to_rows 의 가중치 비율이 바뀌어 지금까지의 MM 이 통째로 달라지고, 점심 공제·주간 추이
      막대까지 오염되며 Copilot 프롬프트로도 나간다. 집계 결과는 mm_meta 의 tool_usage 로만
      실어 화면·보고서에 '참고 지표' 로 보여 준다.

이름 맞히는 규칙
    · exact  : 이름이 정확히 같을 때만 — 짧고 흔한 이름(code · edge · fred · ads)
    · prefix : 이름이 이 문자열로 시작할 때 — 버전이 뒤에 붙는 것(ansys231 · pycharm64)
    · 긴 접두사가 이긴다 — ansysedt(Electronics Desktop)가 ansys(MAPDL)보다 먼저 잡힌다.
    · EXCLUDE 가 무엇보다 먼저다 — ansysli_client(라이선스 대리자)는 로그온 내내 떠 있어서
      이것을 솔버로 세면 '해석을 하루 종일 돌렸다' 가 된다.

kind(상용/비상용)
    라이선스를 사서 쓰는 것이 상용, 무료·오픈소스·사내 제작이 비상용이다. 조직이 어느 쪽에
    얼마나 시간을 쓰는지가 도구 투자·라이선스 정산의 근거가 된다. 확실하지 않으면 넣지 않는다
    (미상으로 남는 편이 틀린 이름표보다 낫다 — 화면에는 '미상' 상위 목록으로 보여 준다).
"""

# 무엇을 해도 프로그램으로 세지 않는다 — 라이선스 대리자·OS 서비스는 사람이 쓴 시간이 아니다.
EXCLUDE = (
    "ansysli", "lmgrd", "lmadmin", "flexlm", "flexnet", "msc_licensing", "dsls",
    "nxlmd", "ugslmd", "armlmd", "ptcflexlm", "cdslmd", "alterad", "xilinxd",
    "svchost", "dwm", "csrss", "winlogon", "sihost", "taskhostw", "runtimebroker",
    "searchhost", "startmenuexperiencehost", "shellexperiencehost", "textinputhost",
    "applicationframehost", "systemsettings", "lockapp", "ctfmon", "conhost",
    "backgroundtaskhost", "smartscreen", "securityhealthservice", "msmpeng",
    "wmiprvse", "audiodg", "fontdrvhost", "sppsvc", "dllhost", "sedsvc",
)

# (이름들, 표시 이름, 공급사, 상용/비상용, 분류, 맞히는 방식)
_CATALOG = (
    # ── 기구·CAD ──────────────────────────────────────────────────────────────
    (("xtop", "creo", "parametric", "proe", "pro_comm_msg"), "Creo Parametric", "PTC", "상용", "CAD", "prefix"),
    (("cnext", "catia", "catstart", "3dexperience"), "CATIA", "Dassault", "상용", "CAD", "prefix"),
    (("ugraf", "ugii", "nxmanager"), "NX", "Siemens", "상용", "CAD", "prefix"),
    (("sldworks", "swspmanager"), "SOLIDWORKS", "Dassault", "상용", "CAD", "prefix"),
    (("edge",), "Solid Edge", "Siemens", "상용", "CAD", "exact"),   # MS Edge 는 msedge — 정확 일치라야 안 섞인다
    (("inventor",), "Inventor", "Autodesk", "상용", "CAD", "prefix"),
    (("acad", "acadlt"), "AutoCAD", "Autodesk", "상용", "CAD", "prefix"),
    (("spaceclaim", "scdm"), "SpaceClaim", "Ansys", "상용", "CAD", "prefix"),
    (("ansysdiscovery", "discovery"), "Ansys Discovery", "Ansys", "상용", "CAD", "prefix"),
    (("freecad",), "FreeCAD", "오픈소스", "비상용", "CAD", "prefix"),
    (("blender",), "Blender", "오픈소스", "비상용", "CAD", "prefix"),
    # ── 해석·시뮬레이션(상용) ─────────────────────────────────────────────────
    (("ansysedt", "hfss", "maxwell", "simplorer", "q3d"), "Ansys Electronics Desktop", "Ansys", "상용", "해석", "prefix"),
    (("ansyswb", "runwb2", "ansysfw", "workbench"), "Ansys Workbench", "Ansys", "상용", "해석", "prefix"),
    (("ansys", "mapdl"), "Ansys Mechanical APDL", "Ansys", "상용", "해석", "prefix"),
    (("fluent", "cortex", "fl_mpi", "fluentbench"), "Ansys Fluent", "Ansys", "상용", "해석", "prefix"),
    (("cfx5", "cfx"), "Ansys CFX", "Ansys", "상용", "해석", "prefix"),
    (("icepak",), "Ansys Icepak", "Ansys", "상용", "해석", "prefix"),
    (("floefd", "flotherm", "efdlite", "swflow", "flowsim"), "FloEFD / FloTHERM", "Siemens", "상용", "해석", "prefix"),
    (("abaqus", "abq", "smasimutility"), "Abaqus", "Dassault", "상용", "해석", "prefix"),
    (("comsol",), "COMSOL Multiphysics", "COMSOL", "상용", "해석", "prefix"),
    (("nastran", "patran", "femap", "mscnastran"), "MSC Nastran / Patran / FEMAP", "Hexagon", "상용", "해석", "prefix"),
    (("hypermesh", "hyperview", "hypergraph", "hwsolver", "optistruct", "radioss", "hstudy"),
     "Altair HyperWorks", "Altair", "상용", "해석", "prefix"),
    (("lsdyna", "ls-dyna", "lsprepost", "lspp"), "LS-DYNA", "Ansys", "상용", "해석", "prefix"),
    (("starccm", "star-ccm"), "Simcenter STAR-CCM+", "Siemens", "상용", "해석", "prefix"),
    (("moldflow", "synergy"), "Moldflow", "Autodesk", "상용", "해석", "prefix"),
    (("recurdyn",), "RecurDyn", "FunctionBay", "상용", "해석", "prefix"),
    (("adams",), "Adams", "Hexagon", "상용", "해석", "prefix"),
    (("matlab", "simulink", "mathworks"), "MATLAB / Simulink", "MathWorks", "상용", "해석", "prefix"),
    (("mathcad", "maple", "mathematica"), "수식 해석기", "각사", "상용", "해석", "prefix"),
    # ── 해석·시뮬레이션(비상용·오픈소스) ──────────────────────────────────────
    (("paraview", "pvserver", "pvpython"), "ParaView", "오픈소스", "비상용", "해석", "prefix"),
    (("salome",), "SALOME", "오픈소스", "비상용", "해석", "prefix"),
    (("gmsh",), "Gmsh", "오픈소스", "비상용", "해석", "prefix"),
    (("elmergui", "elmersolver"), "Elmer", "오픈소스", "비상용", "해석", "prefix"),
    (("su2_",), "SU2", "오픈소스", "비상용", "해석", "prefix"),
    (("ccx", "cgx"), "CalculiX", "오픈소스", "비상용", "해석", "prefix"),
    (("aster", "code_aster"), "Code_Aster", "오픈소스", "비상용", "해석", "prefix"),
    (("simplefoam", "pimplefoam", "interfoam", "foamrun", "blockmesh", "snappyhexmesh", "chtmultiregionfoam"),
     "OpenFOAM", "오픈소스", "비상용", "해석", "prefix"),
    (("openradioss",), "OpenRadioss", "오픈소스", "비상용", "해석", "prefix"),
    # ── 광학 ──────────────────────────────────────────────────────────────────
    (("opticstudio", "zemax"), "Zemax OpticStudio", "Ansys", "상용", "광학", "prefix"),
    (("codev",), "CODE V", "Synopsys", "상용", "광학", "prefix"),
    (("lighttools",), "LightTools", "Synopsys", "상용", "광학", "prefix"),
    (("tracepro",), "TracePro", "Lambda", "상용", "광학", "prefix"),
    (("fred",), "FRED", "Photon Engineering", "상용", "광학", "exact"),
    (("asap",), "ASAP", "Breault", "상용", "광학", "exact"),
    (("fdtd-solutions", "mode-solutions", "lumerical", "interconnect"), "Lumerical", "Ansys", "상용", "광학", "prefix"),
    (("virtuallab",), "VirtualLab Fusion", "LightTrans", "상용", "광학", "prefix"),
    (("rsoft", "fullwave", "beamprop"), "RSoft", "Synopsys", "상용", "광학", "prefix"),
    # ── 회로·EDA ──────────────────────────────────────────────────────────────
    (("dxp", "altium"), "Altium Designer", "Altium", "상용", "EDA", "prefix"),
    (("allegro", "orcad", "pspice", "sigrity"), "Cadence Allegro / OrCAD", "Cadence", "상용", "EDA", "prefix"),
    (("pads", "xpedition", "expedition", "hyperlynx"), "Siemens PADS / Xpedition", "Siemens", "상용", "EDA", "prefix"),
    (("hpeesofsim", "adsmain"), "Keysight ADS", "Keysight", "상용", "EDA", "prefix"),
    (("ads",), "Keysight ADS", "Keysight", "상용", "EDA", "exact"),
    (("saber",), "Saber", "Synopsys", "상용", "EDA", "prefix"),
    (("kicad", "pcbnew", "eeschema"), "KiCad", "오픈소스", "비상용", "EDA", "prefix"),
    (("ltspice", "xviix", "scad3"), "LTspice", "Analog Devices", "비상용", "EDA", "prefix"),
    (("qucs", "ngspice"), "Qucs / ngspice", "오픈소스", "비상용", "EDA", "prefix"),
    # ── FPGA·펌웨어·차량 ──────────────────────────────────────────────────────
    (("vivado", "vitis", "xsdb"), "Vivado / Vitis", "AMD Xilinx", "상용", "FPGA·펌웨어", "prefix"),
    (("quartus", "qsys"), "Quartus", "Intel Altera", "상용", "FPGA·펌웨어", "prefix"),
    (("uv4", "uvision"), "Keil MDK", "Arm", "상용", "FPGA·펌웨어", "prefix"),
    (("iaridepm", "iarideipm", "iarbuild"), "IAR Embedded Workbench", "IAR", "상용", "FPGA·펌웨어", "prefix"),
    (("stm32cube", "stm32"), "STM32Cube", "ST", "비상용", "FPGA·펌웨어", "prefix"),
    (("t32m",), "Lauterbach TRACE32", "Lauterbach", "상용", "FPGA·펌웨어", "prefix"),
    (("canoe", "canalyzer", "canape", "vteststudio", "candela"), "Vector CANoe 계열", "Vector", "상용", "FPGA·펌웨어", "prefix"),
    (("modelsim", "questasim"), "ModelSim / Questa", "Siemens", "상용", "FPGA·펌웨어", "prefix"),
    # ── SW 개발 ───────────────────────────────────────────────────────────────
    (("devenv",), "Visual Studio", "Microsoft", "상용", "SW개발", "prefix"),
    (("code",), "Visual Studio Code", "Microsoft", "비상용", "SW개발", "exact"),
    (("pycharm", "idea", "clion", "webstorm", "rider", "datagrip"), "JetBrains IDE", "JetBrains", "상용", "SW개발", "prefix"),
    (("python", "ipython", "jupyter", "conda", "anaconda", "spyder"), "Python", "오픈소스", "비상용", "SW개발", "prefix"),
    (("eclipse",), "Eclipse", "오픈소스", "비상용", "SW개발", "prefix"),
    (("git", "sourcetree", "tortoisegit", "gitextensions"), "Git 도구", "각사", "비상용", "SW개발", "prefix"),
    (("windowsterminal", "powershell", "pwsh", "putty", "mobaxterm", "xshell", "wsl", "ubuntu"),
     "터미널·원격 셸", "각사", "비상용", "SW개발", "prefix"),
    (("docker",), "Docker", "Docker", "비상용", "SW개발", "prefix"),
    (("vmware", "virtualbox", "vmconnect"), "가상 머신", "각사", "비상용", "SW개발", "prefix"),
    # ── 계측·데이터 ───────────────────────────────────────────────────────────
    (("labview",), "LabVIEW", "NI", "상용", "계측", "prefix"),
    (("benchvue", "keysight", "tekscope", "signalvu"), "계측 장비 도구", "각사", "상용", "계측", "prefix"),
    (("origin",), "Origin", "OriginLab", "상용", "계측", "prefix"),
    (("minitab", "jmp"), "통계 도구", "각사", "상용", "계측", "prefix"),
    # ── 사무·소통 ─────────────────────────────────────────────────────────────
    (("excel",), "Excel", "Microsoft", "상용", "사무", "prefix"),
    (("winword",), "Word", "Microsoft", "상용", "사무", "prefix"),
    (("powerpnt",), "PowerPoint", "Microsoft", "상용", "사무", "prefix"),
    (("onenote",), "OneNote", "Microsoft", "상용", "사무", "prefix"),
    (("msaccess", "mspub", "winproj", "visio"), "Office 기타", "Microsoft", "상용", "사무", "prefix"),
    (("hwp", "hword", "hcell", "hshow", "hoffice"), "한컴오피스", "한글과컴퓨터", "상용", "사무", "prefix"),
    (("acrobat", "acrord32", "foxit", "sumatrapdf"), "PDF 도구", "각사", "상용", "사무", "prefix"),
    (("outlook",), "Outlook", "Microsoft", "상용", "소통", "prefix"),
    (("teams", "ms-teams"), "Teams", "Microsoft", "상용", "소통", "prefix"),
    (("chrome", "msedge", "firefox", "whale", "iexplore", "brave", "opera"), "웹 브라우저", "각사", "비상용", "소통", "prefix"),
    (("mstsc", "teamviewer", "anydesk", "vncviewer", "rdcman"), "원격 접속", "각사", "비상용", "소통", "prefix"),
    (("explorer", "7zfm", "winrar", "bandizip", "notepad", "everything"), "파일·유틸", "각사", "비상용", "기타", "prefix"),
)

# 배경에서 '돌려 놓고 기다리는' 솔버 이름 — collect\Start-ActivitySampler.ps1 의 solvers_running 과
# config.solverProcesses 기본값이 여기서 나온다. GUI 만 있는 것(hypermesh·patran)은 넣지 않는다.
SOLVER_HINTS = ("ansys", "mapdl", "fluent", "cortex", "fl_mpi", "cfx5solve", "abaqus", "nastran",
                "comsol", "lsdyna", "starccm", "optistruct", "radioss", "hwsolver", "moldflow",
                "floefd", "icepak", "ansysedt", "simplefoam", "pimplefoam", "interfoam",
                "ccx", "su2_cfd", "elmersolver", "aster")

_EXACT = {}
_PREFIX = []          # (접두사, 항목) — 긴 것부터 본다
for _names, _disp, _vendor, _kind, _cat, _how in _CATALOG:
    _item = {"name": _disp, "vendor": _vendor, "kind": _kind, "cat": _cat}
    for _nm in _names:
        if _how == "exact":
            _EXACT.setdefault(_nm, _item)
        else:
            _PREFIX.append((_nm, _item))
_PREFIX.sort(key=lambda x: -len(x[0]))


def _norm(proc):
    p = (proc or "").strip().lower()
    if p.endswith(".exe"):
        p = p[:-4]
    return p


def is_noise(proc):
    """사람이 '쓴' 프로그램이 아닌 것 — 라이선스 대리자·OS 서비스."""
    p = _norm(proc)
    return not p or any(p.startswith(x) for x in EXCLUDE)


def classify(proc, extra=()):
    """process 이름 → {"name","vendor","kind","cat"} · 모르면 None.

    extra: config.programsExtra — [{"match": "myfea", "name": "사내 해석기",
           "kind": "비상용", "cat": "해석", "vendor": "사내"}] · 카탈로그보다 먼저 본다.
    사내에서 만든 도구는 이름을 알 길이 없으니 이 통로로 넣는다."""
    p = _norm(proc)
    if not p or is_noise(p):
        return None
    for e in (extra or ()):
        if not isinstance(e, dict):
            continue
        m = str(e.get("match") or "").strip().lower()
        if m and (p == m or p.startswith(m)):
            return {"name": str(e.get("name") or m), "vendor": str(e.get("vendor") or "사내"),
                    "kind": str(e.get("kind") or "비상용"), "cat": str(e.get("cat") or "기타")}
    it = _EXACT.get(p)
    if it:
        return dict(it)
    for pre, it in _PREFIX:
        if p.startswith(pre):
            return dict(it)
    return None


def solver_names():
    """config.solverProcesses 기본값 — 배경에서 돌아가는 솔버 이름."""
    return list(SOLVER_HINTS)

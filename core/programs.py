# -*- coding: utf-8 -*-
"""프로그램 사용 이력 — 실행 파일 이름·파일 확장자를 '무슨 프로그램인가' 로 옮기는 표.

무엇을 위한 표인가
    사용자 요청: 상용(Ansys·Creo 등 각종 시뮬레이션)과 비상용(무료·오픈소스·자체 개발·프로토타입) 프로그램을 쓴 이력을
    보고 싶다. 증거는 세 곳에서 온다(core\\extract.tool_usage 가 한 표로 합친다).
      · 창기록   — 옛 창 샘플러의 data\\activity\\activity_*.csv process 열(LM28 에는 샘플러가 없다 — 옛 기록만).
      · 실행기록 — collect\\Get-ProgramUsage.py 가 수집 때마다 찍는 Windows 실행 흔적 스냅샷(UserAssist·작업 표시줄 횟수·BAM).
      · 파일     — 파일·Recent 수집기가 이미 모은 산출물의 확장자(EXT_PROGRAM — .wbpj 면 Workbench, .prt.3 이면 Creo).
    파일 확장자(core\\extract.EXT_ACT)는 '무슨 산출물을 냈나' 를 말해 주지만 '무슨 도구로' 는 이 표가 말한다.

이 표는 시간 계산에 쓰지 않는다
    ★ 여기서 나온 값은 MM 배분·로드율에 절대 들어가지 않는다. load_signals 의 신호로 만들면
      to_rows 의 가중치 비율이 바뀌어 지금까지의 MM 이 통째로 달라지고, 점심 공제·주간 추이
      막대까지 오염되며 Copilot 프롬프트로도 나간다. 집계 결과는 mm_meta 의 tool_usage 로만
      실어 화면·보고서에 '참고 지표' 로 보여 준다.

이름 맞히는 규칙
    · exact  : 이름이 정확히 같을 때만 — 짧고 흔한 이름(code · edge · fred · ads · psim · nx)
    · prefix : 이름이 이 문자열로 시작할 때 — 버전이 뒤에 붙는 것(ansys231 · pycharm64)
    · 긴 접두사가 이긴다 — ansysedt(Electronics Desktop)가 ansys(MAPDL)보다 먼저 잡힌다.
    · EXCLUDE 가 무엇보다 먼저다 — ansysli_client(라이선스 대리자)는 로그온 내내 떠 있어서
      이것을 솔버로 세면 '해석을 하루 종일 돌렸다' 가 된다. Adobe 의 ccxprocess 는 CalculiX(ccx)로 읽히던 이름이다.
    · 공급사 폴더 한정(_QUALIFIED) — synergy·flux·capture·x2 처럼 다른 프로그램과 겹치는 이름은 실행 기록이 알려 준
      Program Files 바로 아래 폴더(autodesk·altair·cadence·altium)가 맞을 때만 그 도구로 본다. 그 폴더의 모르는
      실행 파일은 '<공급사> 기타 도구'(VENDOR_DIRS — 상용)로 — 시뮬레이션 공급사의 실행 파일 이름을 다 알 수는 없다.
    · 바로 가기(.lnk) 이름은 lnk_key 로 판번호·공백을 걷어 같은 표로 맞힌다('Workbench 2023 R1' → workbench).

kind(상용/비상용)
    라이선스를 사서 쓰는 것이 상용, 무료·오픈소스·사내 제작이 비상용이다. 조직이 어느 쪽에
    얼마나 시간을 쓰는지가 도구 투자·라이선스 정산의 근거가 된다. 확실하지 않으면 넣지 않는다
    (미상으로 남는 편이 틀린 이름표보다 낫다 — 화면에는 '미상' 상위 목록으로 보여 준다).
    표에 없는 실행 파일이 사용자 폴더·다른 드라이브·네트워크에서 돌았으면 INHOUSE_KIND('자체·프로토타입(추정)') —
    사내에서 만든 도구·시험판은 이름을 미리 알 길이 없어서다. 설치·갱신·런처 소음은 뺀다. '추정' 은 지우지 않는다
    (무료 휴대용 도구도 같은 자리에서 돈다).
"""
import re

# 무엇을 해도 프로그램으로 세지 않는다 — 라이선스 대리자·OS 서비스·상주 대리자는 사람이 쓴 시간이 아니다.
EXCLUDE = (
    "ansysli", "ansyslm", "lmgrd", "lmadmin", "lmutil", "lmtools", "flexlm", "flexnet", "msc_licensing", "dsls",
    "nxlmd", "ugslmd", "armlmd", "ptcflexlm", "cdslmd", "alterad", "xilinxd",
    "mathworksservicehost", "ccxprocess", "adsklicensing", "adskaccess", "adskidentity", "creoagent",
    "svchost", "dwm", "csrss", "winlogon", "sihost", "taskhostw", "runtimebroker",
    "searchhost", "startmenuexperiencehost", "shellexperiencehost", "textinputhost",
    "applicationframehost", "systemsettings", "lockapp", "ctfmon", "conhost",
    "backgroundtaskhost", "smartscreen", "securityhealthservice", "msmpeng",
    "wmiprvse", "audiodg", "fontdrvhost", "sppsvc", "dllhost", "sedsvc",
)

# 설치·갱신·제거 프로그램·드라이버 — 실행 기록에는 남지만 '그 도구를 썼다' 가 아니다(ansys_setup 이 MAPDL 로 읽히지 않게).
_INSTALL_RX = re.compile(r"setup|install|uninst|unins\d|updat|upgrad|redist|bootstrap|crashpad|crashhandler|crashreport"
                         r"|driver")
# 자체·프로토타입 판정에서만 더 빼는 것 — 런처·도우미·패치·임시 이름·세 마디 판번호(motiv-mix-windows-1.6.1 처럼 내려받은
# 배포본 이름)(카탈로그 판정에는 쓰지 않는다: ABQLauncher 는 Abaqus 다). temp·patch 를 부분 일치로 두면 temperature_logger·
# job_dispatcher 같은 사내 도구가 빠진다 — 임시 이름은 앞·끝으로만 본다(개발 PC 실측으로 고른 목록).
_INHOUSE_NOISE_RX = re.compile(r"launcher|helper|elevat|(?<![a-z])patch|^tmp|^~|\.tmp$|\d+\.\d+\.\d+")

INHOUSE_KIND = "자체·프로토타입(추정)"
INHOUSE_CLS = ("user", "other_drive", "network")       # 사용자 폴더 · 다른 드라이브(표준 밖 폴더) · 네트워크 — 설치된 자리가 아니다
GENERAL_CATS = ("사무", "소통", "기타")                    # 정렬에서 뒤로 — 전문 도구(해석·CAD·EDA …)가 표 위에 오게
TOOL_NOTE = ("참고 지표 — 투입 MM·로드율과 무관 · 실행 기록은 Windows 가 사용자 계정에 남긴 실행 흔적"
             "(관리자 권한 불필요)")

# (이름들, 표시 이름, 공급사, 상용/비상용, 분류, 맞히는 방식)
_CATALOG = (
    # ── 기구·CAD ──────────────────────────────────────────────────────────────
    (("xtop", "creo", "parametric", "proe", "pro_comm_msg"), "Creo Parametric", "PTC", "상용", "CAD", "prefix"),
    (("productview", "creoview"), "Creo View", "PTC", "상용", "CAD", "prefix"),
    (("cnext", "catia", "catstart", "3dexperience"), "CATIA", "Dassault", "상용", "CAD", "prefix"),
    (("ugraf", "ugii", "nxmanager"), "NX", "Siemens", "상용", "CAD", "prefix"),
    (("nx",), "NX", "Siemens", "상용", "CAD", "exact"),                    # 바로 가기 'NX 2212'
    (("sldworks", "swspmanager", "solidworks"), "SOLIDWORKS", "Dassault", "상용", "CAD", "prefix"),
    (("edge",), "Solid Edge", "Siemens", "상용", "CAD", "exact"),   # MS Edge 는 msedge — 정확 일치라야 안 섞인다
    (("solidedge",), "Solid Edge", "Siemens", "상용", "CAD", "prefix"),
    (("inventor",), "Inventor", "Autodesk", "상용", "CAD", "prefix"),
    (("acad", "acadlt", "autocad"), "AutoCAD", "Autodesk", "상용", "CAD", "prefix"),
    (("fusion360", "autodeskfusion"), "Fusion 360", "Autodesk", "상용", "CAD", "prefix"),
    (("fusion",), "Fusion 360", "Autodesk", "상용", "CAD", "exact"),       # 바로 가기 'Fusion 360' → 판번호처럼 360 이 빠진다
    (("zwcad",), "ZWCAD", "ZWSOFT", "상용", "CAD", "prefix"),
    (("spaceclaim", "scdm"), "Ansys SpaceClaim", "Ansys", "상용", "CAD", "prefix"),
    (("ansysdiscovery",), "Ansys Discovery", "Ansys", "상용", "CAD", "prefix"),
    (("discovery",), "Ansys Discovery", "Ansys", "상용", "CAD", "exact"),  # 흔한 낱말 — 접두로 두면 남의 discovery* 를 잡는다
    (("freecad",), "FreeCAD", "오픈소스", "비상용", "CAD", "prefix"),
    (("blender",), "Blender", "오픈소스", "비상용", "CAD", "prefix"),
    (("openscad",), "OpenSCAD", "오픈소스", "비상용", "CAD", "prefix"),
    (("librecad",), "LibreCAD", "오픈소스", "비상용", "CAD", "prefix"),
    (("meshlab",), "MeshLab", "오픈소스", "비상용", "CAD", "prefix"),
    # ── 해석·시뮬레이션 — Ansys ──────────────────────────────────────────────
    # HFSS·Maxwell·Q3D 는 Electronics Desktop(ansysedt) 안에서 돈다 — 실행 파일로는 갈라지지 않는다(옛 단독판 이름만 둔다)
    (("ansysedt", "ansyselectronics", "hfss", "q3d"), "Ansys Electronics Desktop", "Ansys", "상용", "해석", "prefix"),
    (("siwave",), "Ansys SIwave", "Ansys", "상용", "해석", "prefix"),
    (("simplorer", "twinbuilder"), "Ansys Twin Builder", "Ansys", "상용", "해석", "prefix"),
    (("ansyswbu", "ansysmechanical"), "Ansys Mechanical", "Ansys", "상용", "해석", "prefix"),
    (("mechanical",), "Ansys Mechanical", "Ansys", "상용", "해석", "exact"),          # 바로 가기 'Mechanical 2023 R1'
    (("ansyswb", "runwb2", "ansysfw", "workbench"), "Ansys Workbench", "Ansys", "상용", "해석", "prefix"),
    (("ansys", "mapdl", "mechanicalapdl"), "Ansys Mechanical APDL", "Ansys", "상용", "해석", "prefix"),
    (("fluent", "cortex", "fl_mpi", "fluentbench"), "Ansys Fluent", "Ansys", "상용", "해석", "prefix"),
    (("cfx5", "cfx"), "Ansys CFX", "Ansys", "상용", "해석", "prefix"),
    (("icepak",), "Ansys Icepak", "Ansys", "상용", "해석", "prefix"),
    (("icemcfd",), "Ansys ICEM CFD", "Ansys", "상용", "해석", "prefix"),
    (("optislang",), "Ansys optiSLang", "Ansys", "상용", "해석", "prefix"),
    (("motorcad", "motor-cad"), "Ansys Motor-CAD", "Ansys", "상용", "해석", "prefix"),
    (("granta",), "Ansys Granta", "Ansys", "상용", "해석", "prefix"),
    (("ensight",), "Ansys EnSight", "Ansys", "상용", "해석", "prefix"),
    (("lsdyna", "ls-dyna", "lsprepost", "ls-prepost", "lspp"), "LS-DYNA", "Ansys", "상용", "해석", "prefix"),
    # ── 해석·시뮬레이션 — 그 밖의 상용 ───────────────────────────────────────
    (("msengine",), "Creo Simulate", "PTC", "상용", "해석", "prefix"),               # Mechanica 엔진
    (("abaqus", "abq", "smasimutility"), "Abaqus", "Dassault", "상용", "해석", "prefix"),
    (("cst design environment", "cstdesignenvironment", "cst studio", "cststudio"),
     "CST Studio Suite", "Dassault", "상용", "해석", "prefix"),
    (("simpack",), "Simpack", "Dassault", "상용", "해석", "prefix"),
    (("isight",), "Isight", "Dassault", "상용", "해석", "prefix"),
    (("fe-safe", "fesafe"), "fe-safe", "Dassault", "상용", "해석", "prefix"),
    (("dymola",), "Dymola", "Dassault", "상용", "해석", "prefix"),
    (("swflow", "flowsim"), "SOLIDWORKS Flow Simulation", "Dassault", "상용", "해석", "prefix"),
    (("starccm", "star-ccm", "simcenterstarccm"), "Simcenter STAR-CCM+", "Siemens", "상용", "해석", "prefix"),
    (("amesim", "simcenteramesim"), "Simcenter Amesim", "Siemens", "상용", "해석", "prefix"),
    (("floefd", "efdlite", "simcenterfloefd"), "Simcenter FloEFD", "Siemens", "상용", "해석", "prefix"),
    (("flotherm", "simcenterflotherm"), "Simcenter FloTHERM", "Siemens", "상용", "해석", "prefix"),
    (("flomaster",), "Simcenter Flomaster", "Siemens", "상용", "해석", "prefix"),
    (("femap",), "Simcenter Femap", "Siemens", "상용", "해석", "prefix"),
    (("prescan",), "Simcenter Prescan", "Siemens", "상용", "해석", "prefix"),
    (("comsol",), "COMSOL Multiphysics", "COMSOL", "상용", "해석", "prefix"),
    (("nastran", "mscnastran"), "Nastran", "Hexagon·Siemens", "상용", "해석", "prefix"),   # MSC·Simcenter 모두 nastran.exe
    (("patran",), "MSC Patran", "Hexagon", "상용", "해석", "prefix"),
    (("adams",), "MSC Adams", "Hexagon", "상용", "해석", "prefix"),
    (("aview",), "MSC Adams", "Hexagon", "상용", "해석", "exact"),
    (("mentat", "marcmentat"), "MSC Marc / Mentat", "Hexagon", "상용", "해석", "prefix"),
    (("simufact",), "Simufact", "Hexagon", "상용", "해석", "prefix"),
    (("digimat",), "Digimat", "Hexagon", "상용", "해석", "prefix"),
    (("actran",), "Actran", "Hexagon", "상용", "해석", "prefix"),
    (("easy5",), "MSC Easy5", "Hexagon", "상용", "해석", "prefix"),
    (("dytran",), "MSC Dytran", "Hexagon", "상용", "해석", "prefix"),
    (("romax",), "Romax", "Hexagon", "상용", "해석", "prefix"),
    (("scflow", "scstream", "sctetra"), "Cradle CFD", "Hexagon", "상용", "해석", "prefix"),
    (("glyphworks", "designlife", "ncode"), "nCode", "Hexagon", "상용", "해석", "prefix"),
    (("hypermesh", "hmopengl", "hyperview", "hypergraph", "hyperworks", "hwsolver", "hstudy"),
     "Altair HyperWorks", "Altair", "상용", "해석", "prefix"),
    (("optistruct",), "Altair OptiStruct", "Altair", "상용", "해석", "prefix"),
    (("radioss",), "Altair Radioss", "Altair", "상용", "해석", "prefix"),
    (("cadfeko", "postfeko", "editfeko", "runfeko", "feko"), "Altair Feko", "Altair", "상용", "해석", "prefix"),
    (("simlab",), "Altair SimLab", "Altair", "상용", "해석", "prefix"),
    (("acusolve", "acuconsole"), "Altair AcuSolve", "Altair", "상용", "해석", "prefix"),
    (("psim",), "PSIM", "Altair", "상용", "해석", "exact"),
    (("plecs",), "PLECS", "Plexim", "상용", "해석", "prefix"),
    (("moldflow",), "Autodesk Moldflow", "Autodesk", "상용", "해석", "prefix"),
    (("moldex",), "Moldex3D", "CoreTech", "상용", "해석", "prefix"),
    (("recurdyn",), "RecurDyn", "FunctionBay", "상용", "해석", "prefix"),
    (("gtise", "gtpost", "gt-suite", "gtsuite"), "GT-SUITE", "Gamma Technologies", "상용", "해석", "prefix"),
    (("tec360", "tecplot"), "Tecplot 360", "Tecplot", "상용", "해석", "prefix"),
    (("fieldview",), "FieldView", "Intelligent Light", "상용", "해석", "prefix"),
    (("flow3d", "flow-3d"), "FLOW-3D", "Flow Science", "상용", "해석", "prefix"),
    (("jmag",), "JMAG", "JSOL", "상용", "해석", "prefix"),
    (("procast",), "ESI ProCAST", "ESI", "상용", "해석", "prefix"),
    (("vaone",), "ESI VA One", "ESI", "상용", "해석", "prefix"),
    (("simulationx",), "SimulationX", "ESI", "상용", "해석", "prefix"),
    (("kisssoft",), "KISSsoft", "Gleason", "상용", "해석", "prefix"),
    (("masta",), "MASTA", "SMT", "상용", "해석", "prefix"),
    (("carmaker", "ipgmovie"), "IPG CarMaker", "IPG", "상용", "해석", "prefix"),
    (("xfdtd",), "Remcom XFdtd", "Remcom", "상용", "해석", "prefix"),
    (("xgeom",), "Sonnet", "Sonnet", "상용", "해석", "prefix"),
    (("sonnet",), "Sonnet", "Sonnet", "상용", "해석", "exact"),
    (("empro",), "Keysight EMPro", "Keysight", "상용", "해석", "prefix"),
    (("sentaurus", "sdevice"), "Synopsys Sentaurus", "Synopsys", "상용", "해석", "prefix"),
    (("clarity3d", "celsius3d"), "Cadence Clarity / Celsius", "Cadence", "상용", "해석", "prefix"),
    (("matlab", "simulink", "mathworks"), "MATLAB / Simulink", "MathWorks", "상용", "해석", "prefix"),
    (("maplesim",), "MapleSim", "Maplesoft", "상용", "해석", "prefix"),
    (("mathcad", "maple", "mathematica"), "수식 해석기", "각사", "상용", "해석", "prefix"),
    # ── 해석·시뮬레이션(비상용·오픈소스) ──────────────────────────────────────
    (("paraview", "pvserver", "pvpython"), "ParaView", "오픈소스", "비상용", "해석", "prefix"),
    (("salome",), "SALOME", "오픈소스", "비상용", "해석", "prefix"),
    (("gmsh",), "Gmsh", "오픈소스", "비상용", "해석", "prefix"),
    (("elmergui", "elmersolver"), "Elmer", "오픈소스", "비상용", "해석", "prefix"),
    (("su2_",), "SU2", "오픈소스", "비상용", "해석", "prefix"),
    (("ccx", "cgx"), "CalculiX", "오픈소스", "비상용", "해석", "exact"),     # 접두로 두면 Adobe ccxprocess 를 잡았다
    (("ccx_", "cgx_"), "CalculiX", "오픈소스", "비상용", "해석", "prefix"),
    (("aster", "code_aster"), "Code_Aster", "오픈소스", "비상용", "해석", "prefix"),
    (("simplefoam", "pimplefoam", "interfoam", "foamrun", "blockmesh", "snappyhexmesh", "chtmultiregionfoam", "openfoam"),
     "OpenFOAM", "오픈소스", "비상용", "해석", "prefix"),
    (("openradioss",), "OpenRadioss", "오픈소스", "비상용", "해석", "prefix"),
    (("octave",), "GNU Octave", "오픈소스", "비상용", "해석", "prefix"),
    (("wscilex", "scilex", "scilab"), "Scilab", "오픈소스", "비상용", "해석", "prefix"),
    (("omedit", "openmodelica"), "OpenModelica", "오픈소스", "비상용", "해석", "prefix"),
    (("femm",), "FEMM", "오픈소스", "비상용", "해석", "prefix"),
    (("netgen",), "Netgen", "오픈소스", "비상용", "해석", "prefix"),
    (("freefem",), "FreeFEM", "오픈소스", "비상용", "해석", "prefix"),
    (("gnuplot", "wgnuplot"), "gnuplot", "오픈소스", "비상용", "해석", "prefix"),
    (("lammps", "lmp_"), "LAMMPS", "오픈소스", "비상용", "해석", "prefix"),
    # ── 광학 ──────────────────────────────────────────────────────────────────
    (("opticstudio", "zemax"), "Zemax OpticStudio", "Ansys", "상용", "광학", "prefix"),
    (("speos",), "Ansys Speos", "Ansys", "상용", "광학", "prefix"),
    (("codev",), "CODE V", "Synopsys", "상용", "광학", "prefix"),
    (("lighttools",), "LightTools", "Synopsys", "상용", "광학", "prefix"),
    (("lucidshape",), "LucidShape", "Synopsys", "상용", "광학", "prefix"),
    (("tracepro",), "TracePro", "Lambda", "상용", "광학", "prefix"),
    (("oslo",), "OSLO", "Lambda", "상용", "광학", "exact"),
    (("fred",), "FRED", "Photon Engineering", "상용", "광학", "exact"),
    (("asap",), "ASAP", "Breault", "상용", "광학", "exact"),
    (("fdtd-solutions", "mode-solutions", "fdtdsolutions", "modesolutions", "fdtd-engine", "lumerical", "interconnect"),
     "Ansys Lumerical", "Ansys", "상용", "광학", "prefix"),
    (("virtuallab",), "VirtualLab Fusion", "LightTrans", "상용", "광학", "prefix"),
    (("rsoft", "fullwave", "beamprop"), "RSoft", "Synopsys", "상용", "광학", "prefix"),
    (("optisystem", "optifdtd", "optibpm", "optiwave"), "Optiwave", "Optiwave", "상용", "광학", "prefix"),
    (("fimmwave", "omnisim", "picwave"), "Photon Design", "Photon Design", "상용", "광학", "prefix"),
    # ── 회로·EDA ──────────────────────────────────────────────────────────────
    (("dxp", "altium"), "Altium Designer", "Altium", "상용", "EDA", "prefix"),
    (("allegro", "orcad", "pspice", "psp_cmd", "sigrity", "powersi"), "Cadence Allegro / OrCAD", "Cadence", "상용", "EDA", "prefix"),
    (("virtuoso", "spectre"), "Cadence Virtuoso / Spectre", "Cadence", "상용", "EDA", "prefix"),
    (("mwoffice", "awrde"), "Cadence AWR Microwave Office", "Cadence", "상용", "EDA", "prefix"),
    (("pads", "powerpcb", "powerlogic", "xpedition", "expedition"), "Siemens PADS / Xpedition", "Siemens", "상용", "EDA", "prefix"),
    (("hyperlynx",), "Siemens HyperLynx", "Siemens", "상용", "EDA", "prefix"),
    (("hpeesofsim", "adsmain", "advanceddesignsystem"), "Keysight ADS", "Keysight", "상용", "EDA", "prefix"),
    (("ads",), "Keysight ADS", "Keysight", "상용", "EDA", "exact"),
    (("hspice", "hspui"), "Synopsys HSPICE", "Synopsys", "상용", "EDA", "prefix"),
    (("saber",), "Saber", "Synopsys", "상용", "EDA", "prefix"),
    (("multisim",), "NI Multisim", "NI", "상용", "EDA", "prefix"),
    (("simetrix",), "SIMetrix", "SIMetrix", "상용", "EDA", "prefix"),
    (("kicad", "pcbnew", "eeschema"), "KiCad", "오픈소스", "비상용", "EDA", "prefix"),
    (("ltspice", "xviix", "scad3"), "LTspice", "Analog Devices", "비상용", "EDA", "prefix"),
    (("qucs", "ngspice"), "Qucs / ngspice", "오픈소스", "비상용", "EDA", "prefix"),
    # ── FPGA·펌웨어·차량 ──────────────────────────────────────────────────────
    (("vivado", "vitis", "xsdb"), "Vivado / Vitis", "AMD Xilinx", "상용", "FPGA·펌웨어", "prefix"),
    (("quartus", "qsys"), "Quartus", "Intel Altera", "상용", "FPGA·펌웨어", "prefix"),
    (("uv4", "uvision", "keil"), "Keil MDK", "Arm", "상용", "FPGA·펌웨어", "prefix"),
    (("iaridepm", "iarideipm", "iarbuild"), "IAR Embedded Workbench", "IAR", "상용", "FPGA·펌웨어", "prefix"),
    (("stm32cube", "stm32"), "STM32Cube", "ST", "비상용", "FPGA·펌웨어", "prefix"),
    (("t32m",), "Lauterbach TRACE32", "Lauterbach", "상용", "FPGA·펌웨어", "prefix"),
    (("canoe", "canalyzer", "canape", "vteststudio", "candela"), "Vector CANoe 계열", "Vector", "상용", "FPGA·펌웨어", "prefix"),
    (("controldesk", "configurationdesk", "modeldesk", "targetlink"), "dSPACE", "dSPACE", "상용", "FPGA·펌웨어", "prefix"),
    (("modelsim", "questasim"), "ModelSim / Questa", "Siemens", "상용", "FPGA·펌웨어", "prefix"),
    (("arduino",), "Arduino IDE", "오픈소스", "비상용", "FPGA·펌웨어", "prefix"),
    # ── SW 개발 ───────────────────────────────────────────────────────────────
    (("devenv", "visualstudio"), "Visual Studio", "Microsoft", "상용", "SW개발", "prefix"),
    (("code", "visualstudiocode"), "Visual Studio Code", "Microsoft", "비상용", "SW개발", "exact"),
    (("pycharm", "idea", "intellij", "clion", "webstorm", "rider", "datagrip"), "JetBrains IDE", "JetBrains", "상용", "SW개발", "prefix"),
    (("python", "ipython", "jupyter", "conda", "anaconda", "spyder"), "Python / Jupyter", "오픈소스", "비상용", "SW개발", "prefix"),
    (("py", "pyw", "idle"), "Python / Jupyter", "오픈소스", "비상용", "SW개발", "exact"),
    (("rstudio", "rgui", "rscript", "rterm"), "R / RStudio", "오픈소스", "비상용", "SW개발", "prefix"),
    (("r",), "R / RStudio", "오픈소스", "비상용", "SW개발", "exact"),
    (("julia",), "Julia", "오픈소스", "비상용", "SW개발", "prefix"),
    (("qtcreator",), "Qt Creator", "Qt", "비상용", "SW개발", "prefix"),
    (("eclipse",), "Eclipse", "오픈소스", "비상용", "SW개발", "prefix"),
    (("git", "sourcetree", "tortoisegit", "gitextensions"), "Git 도구", "각사", "비상용", "SW개발", "prefix"),
    (("windowsterminal", "powershell", "windowspowershell", "pwsh", "putty", "mobaxterm", "xshell", "wsl", "ubuntu"),
     "터미널·원격 셸", "각사", "비상용", "SW개발", "prefix"),
    (("cmd", "terminal", "commandprompt"), "터미널·원격 셸", "각사", "비상용", "SW개발", "exact"),
    (("postman", "insomnia", "dbeaver", "heidisql", "winscp", "filezilla", "wireshark", "ttermpro", "teraterm", "realterm"),
     "개발·통신 도구(무료)", "각사", "비상용", "SW개발", "prefix"),
    (("docker",), "Docker", "Docker", "비상용", "SW개발", "prefix"),
    (("vmware", "virtualbox", "oraclevm", "vmconnect"), "가상 머신", "각사", "비상용", "SW개발", "prefix"),
    # ── 계측·데이터 ───────────────────────────────────────────────────────────
    (("labview",), "LabVIEW", "NI", "상용", "계측", "prefix"),
    (("seqedit", "teststand"), "NI TestStand", "NI", "상용", "계측", "prefix"),
    (("diadem",), "NI DIAdem", "NI", "상용", "계측", "prefix"),
    (("benchvue", "keysight", "tekscope", "signalvu", "nimax"), "계측 장비 도구", "각사", "상용", "계측", "prefix"),
    (("origin64", "origin9", "origin20", "originpro"), "Origin", "OriginLab", "상용", "계측", "prefix"),
    (("origin",), "Origin", "OriginLab", "상용", "계측", "exact"),
    (("minitab", "jmp"), "통계 도구", "각사", "상용", "계측", "prefix"),
    # ── 사무·소통 ─────────────────────────────────────────────────────────────
    (("excel",), "Excel", "Microsoft", "상용", "사무", "prefix"),
    (("winword",), "Word", "Microsoft", "상용", "사무", "prefix"),
    (("word",), "Word", "Microsoft", "상용", "사무", "exact"),
    (("powerpnt",), "PowerPoint", "Microsoft", "상용", "사무", "prefix"),
    (("powerpoint",), "PowerPoint", "Microsoft", "상용", "사무", "exact"),
    (("onenote",), "OneNote", "Microsoft", "상용", "사무", "prefix"),
    (("msaccess", "mspub", "winproj", "visio"), "Office 기타", "Microsoft", "상용", "사무", "prefix"),
    (("hwp", "hword", "hcell", "hshow", "hoffice", "한컴"), "한컴오피스", "한글과컴퓨터", "상용", "사무", "prefix"),
    (("한글", "한셀", "한쇼"), "한컴오피스", "한글과컴퓨터", "상용", "사무", "exact"),
    (("acrobat", "adobeacrobat", "acrord32", "foxit", "sumatrapdf"), "PDF 도구", "각사", "상용", "사무", "prefix"),
    (("outlook",), "Outlook", "Microsoft", "상용", "소통", "prefix"),
    (("teams", "ms-teams", "msteams", "microsoftteams"), "Teams", "Microsoft", "상용", "소통", "prefix"),
    (("slack", "webex", "ciscowebex"), "메신저·화상회의(상용)", "각사", "상용", "소통", "prefix"),
    (("zoom",), "메신저·화상회의(상용)", "각사", "상용", "소통", "exact"),      # 접두로 두면 zoomit(화면 확대 도구)을 잡는다
    (("kakaotalk", "discord"), "메신저(무료)", "각사", "비상용", "소통", "prefix"),
    (("카카오톡",), "메신저(무료)", "각사", "비상용", "소통", "exact"),
    (("chrome", "googlechrome", "msedge", "microsoftedge", "firefox", "whale", "iexplore", "brave"),
     "웹 브라우저", "각사", "비상용", "소통", "prefix"),
    (("opera",), "웹 브라우저", "각사", "비상용", "소통", "exact"),            # 접두로 두면 operation_*·operator_* 사내 도구를 잡는다
    (("mstsc", "remotedesktop", "teamviewer", "anydesk", "vncviewer", "rdcman"), "원격 접속", "각사", "비상용", "소통", "prefix"),
    (("explorer", "7zfm", "7zip", "winrar", "bandizip", "notepad", "everything", "winmerge", "greenshot", "sharex",
      "irfanview", "keepass", "procexp", "procmon", "autoruns", "cpuz", "cpu-z", "hwinfo"), "파일·유틸", "각사", "비상용", "기타", "prefix"),
    (("fileexplorer",), "파일·유틸", "각사", "비상용", "기타", "exact"),
)

# 공급사 폴더(Program Files 바로 아래 폴더 소문자 · 앞부분 일치)가 맞을 때만 그 도구로 보는 이름 — 이름만으로는 남의 프로그램과 겹친다
#   synergy(Moldflow GUI ↔ 키보드 공유 Synergy) · flux(Altair Flux ↔ f.lux) · capture(OrCAD Capture) · x2(Altium Designer 20+)
_QUALIFIED = (
    ("autodesk", ("synergy",), "Autodesk Moldflow"),
    ("autodesk", ("cfd",), "Autodesk CFD"),
    ("altair", ("flux",), "Altair Flux"),
    ("altair", ("inspire",), "Altair Inspire"),
    ("msc", ("apex",), "MSC Apex"),
    ("msc", ("marc",), "MSC Marc / Mentat"),
    ("cadence", ("capture",), "Cadence Allegro / OrCAD"),
    ("altium", ("x2",), "Altium Designer"),
    ("ansys", ("maxwell",), "Ansys Electronics Desktop"),
    ("ansys", ("launcher",), "Ansys Mechanical APDL"),     # Mechanical APDL Product Launcher
    ("ptc", ("simulate",), "Creo Simulate"),
    ("originlab", ("origin",), "Origin"),
)
# 표에 따로 없는 공급사 한정 프로그램의 신원(_QUALIFIED 의 표시 이름 중 카탈로그에 없는 것)
_EXTRA_IDENT = {
    "Autodesk CFD": ("Autodesk", "상용", "해석"),
    "Altair Flux": ("Altair", "상용", "해석"),
    "Altair Inspire": ("Altair", "상용", "해석"),
    "MSC Apex": ("Hexagon", "상용", "해석"),
}

# 공급사 폴더 → (공급사, 분류) — Program Files 바로 아래(또는 C:\SIMULIA 처럼 드라이브 바로 아래) 폴더의 앞부분(소문자).
# 이 폴더의 모르는 실행 파일은 '<공급사> 기타 도구'(상용)로 센다. 수집기는 Program Files 밖에서는 이 표에 있는 폴더만 남긴다
# (D:\홍길동\과제\… 의 첫 폴더는 사람·과제 이름일 수 있다). Microsoft·Common Files 처럼 넓은 것은 넣지 않는다.
VENDOR_DIRS = (
    ("ansys", "Ansys", "해석"), ("altair", "Altair", "해석"), ("msc", "Hexagon", "해석"), ("hexagon", "Hexagon", "해석"),
    ("simulia", "Dassault", "해석"), ("dassault systemes", "Dassault", "CAD"), ("solidworks", "Dassault", "CAD"),
    ("ptc", "PTC", "CAD"), ("siemens", "Siemens", "기타"), ("cd-adapco", "Siemens", "해석"), ("comsol", "COMSOL", "해석"),
    ("matlab", "MathWorks", "해석"), ("mathworks", "MathWorks", "해석"), ("avl", "AVL", "해석"),
    ("gti", "Gamma Technologies", "해석"), ("esi group", "ESI", "해석"), ("coretech", "CoreTech", "해석"),
    ("moldex3d", "CoreTech", "해석"), ("zemax", "Ansys", "광학"), ("lumerical", "Ansys", "광학"), ("cst", "Dassault", "해석"),
    ("synopsys", "Synopsys", "기타"), ("cadence", "Cadence", "EDA"), ("mentor graphics", "Siemens", "EDA"),
    ("mentorgraphics", "Siemens", "EDA"), ("altium", "Altium", "EDA"), ("keysight", "Keysight", "EDA"),
    ("national instruments", "NI", "계측"), ("functionbay", "FunctionBay", "해석"), ("tecplot", "Tecplot", "해석"),
    ("plexim", "Plexim", "해석"), ("powersim", "Altair", "해석"), ("jsol", "JSOL", "해석"), ("flow science", "Flow Science", "해석"),
    ("intelligent light", "Intelligent Light", "해석"), ("convergent science", "Convergent Science", "해석"),
    ("remcom", "Remcom", "해석"), ("ipg", "IPG", "해석"), ("dspace", "dSPACE", "FPGA·펌웨어"), ("vector", "Vector", "FPGA·펌웨어"),
    ("xilinx", "AMD Xilinx", "FPGA·펌웨어"), ("intelfpga", "Intel Altera", "FPGA·펌웨어"), ("keil", "Arm", "FPGA·펌웨어"),
    ("iar systems", "IAR", "FPGA·펌웨어"), ("autodesk", "Autodesk", "CAD"), ("bentley", "Bentley", "CAD"),
)
_VENDOR_DIRS = sorted(VENDOR_DIRS, key=lambda x: -len(x[0]))

# 배경에서 '돌려 놓고 기다리는' 솔버 이름 — activity CSV 의 solvers_running(옛 창 기록)과
# config.solverProcesses 기본값이 여기서 나온다. GUI 만 있는 것(hypermesh·patran)은 넣지 않는다.
SOLVER_HINTS = ("ansys", "mapdl", "fluent", "cortex", "fl_mpi", "cfx5solve", "abaqus", "nastran",
                "comsol", "lsdyna", "starccm", "optistruct", "radioss", "hwsolver", "moldflow",
                "floefd", "icepak", "ansysedt", "simplefoam", "pimplefoam", "interfoam",
                "ccx", "su2_cfd", "elmersolver", "aster")

_EXACT = {}
_PREFIX = []          # (접두사, 항목) — 긴 것부터 본다
_BY_NAME = {}         # 표시 이름 → 항목(파일 흔적·모호한 확장자 풀이가 이름으로 찾는다)
for _names, _disp, _vendor, _kind, _cat, _how in _CATALOG:
    _item = {"name": _disp, "vendor": _vendor, "kind": _kind, "cat": _cat}
    _BY_NAME.setdefault(_disp, _item)
    for _nm in _names:
        if _how == "exact":
            _EXACT.setdefault(_nm, _item)
        else:
            _PREFIX.append((_nm, _item))
_PREFIX.sort(key=lambda x: -len(x[0]))
for _disp, (_vendor, _kind, _cat) in _EXTRA_IDENT.items():
    _BY_NAME.setdefault(_disp, {"name": _disp, "vendor": _vendor, "kind": _kind, "cat": _cat})

# ── 파일 흔적: 확장자 → 그 파일을 만드는 도구(표시 이름 — _CATALOG 와 같은 이름이어야 실행 기록과 한 줄로 합쳐진다) ──
# 이 확장자만 보고도 도구가 사실상 하나인 것만 둔다. 둘 이상이 쓰는 것은 AMBIGUOUS_EXT — 실행 기록에 후보가 하나만
# 보일 때만 그 도구로 돌리고, 아니면 '도구 불명' 건수로만 보인다. 사무 문서(.docx .xlsx .pdf)는 도구를 말해 주지 않아 넣지
# 않는다(Office 사용은 실행 기록이 말한다). Creo 판번호(bracket.prt.3)는 이름 끝으로 따로 본다(_CREO_RE).
EXT_PROGRAM = {}
for _disp, _exts in (
    ("Ansys Workbench", ".wbpj .wbpz .agdb"),
    ("Ansys Mechanical", ".mechdb .mechdat"),
    ("Ansys Mechanical APDL", ".cdb .anf .rth .rmg"),
    ("Ansys Electronics Desktop", ".aedt .aedtz .hfss .mxwl .q3dx"),
    ("Ansys SIwave", ".siw"),
    ("Ansys Fluent", ".cas .cas.h5 .dat.h5 .cas.gz .dat.gz .msh.h5 .flprj"),
    ("Ansys SpaceClaim", ".scdoc .scdocx"),
    ("Ansys Lumerical", ".fsp .lms .ldev .icp .lsf"),
    ("Zemax OpticStudio", ".zmx .zos .zar .zpl .zrd .zbf .zda .zdf .zsc"),
    ("CODE V", ".seq .len"),       # .seq 는 NI TestStand 순서 파일과도 겹친다 — 광학 조직의 수집 목록(watchExtensions)을 따른다
    ("LightTools", ".lts"),
    ("TracePro", ".oml"),
    ("ASAP", ".inr"),
    ("RSoft", ".ind"),
    ("LS-DYNA", ".k .dyn"),
    ("SOLIDWORKS", ".sldprt .sldasm .slddrw"),
    ("CATIA", ".catpart .catproduct .catdrawing .catanalysis .cgr"),
    ("Inventor", ".ipt .iam .idw .ipn"),
    ("Solid Edge", ".psm"),
    ("FreeCAD", ".fcstd"),
    ("Abaqus", ".cae .odb .sta .jnl"),
    ("Nastran", ".bdf .nas .op2 .f06 .f04 .xdb"),
    ("Simcenter Femap", ".modfem"),
    ("Altair HyperWorks", ".hm .h3d .mvw"),
    ("Altair Feko", ".fek"),
    ("COMSOL Multiphysics", ".mph"),
    ("MATLAB / Simulink", ".slx .mdl .mlx .mlapp .sldd"),
    ("LabVIEW", ".vi .lvproj .lvlib .lvclass .ctl"),
    ("CST Studio Suite", ".cst"),
    ("Cadence Allegro / OrCAD", ".brd .dsn"),
    ("Altium Designer", ".pcbdoc .schdoc .prjpcb .schlib .pcblib"),
    ("KiCad", ".kicad_pcb .kicad_sch .kicad_pro .kicad_sym .kicad_mod"),
    ("LTspice", ".asy"),
    ("GT-SUITE", ".gtm"),
    ("MSC Adams", ".adm"),
    ("RecurDyn", ".rdyn"),
    ("Simcenter Amesim", ".ame"),
    ("PSIM", ".psimsch"),
    ("PLECS", ".plecs"),
    ("Autodesk Moldflow", ".mpi"),
    ("Tecplot 360", ".lpk"),
    ("ParaView", ".pvsm"),
    ("OpenFOAM", ".foam"),
    ("Elmer", ".sif"),
    ("SU2", ".su2"),
    ("Code_Aster", ".comm"),
    ("Scilab", ".sce .sci .zcos .xcos"),
    ("R / RStudio", ".r .rmd .rproj"),
    ("Python / Jupyter", ".ipynb .py"),
    ("Julia", ".jl"),
    ("Vivado / Vitis", ".xpr .xdc"),
    ("Quartus", ".qpf .qsf .sof"),
    ("STM32Cube", ".ioc"),
    ("Keil MDK", ".uvprojx .uvproj"),
    ("IAR Embedded Workbench", ".ewp .eww"),
    ("Visual Studio", ".sln .vcxproj .csproj"),
):
    for _e in _exts.split():
        EXT_PROGRAM[_e] = _disp

# 둘 이상의 도구가 쓰는 확장자 → 후보. 실행 기록(어느 스냅샷이든)·창 기록에 후보가 하나만 보이면 그 도구로 돌린다.
# programsExtra 에 {"name": "Simcenter STAR-CCM+", "ext": [".sim"]} 처럼 적으면 그 조직의 뜻으로 바로 정한다.
AMBIGUOUS_EXT = {
    ".prt": ("NX", "Creo Parametric"),            # 판번호 없는 .prt — NX 기본 형식 · 판번호 없이 내보낸 Creo
    ".asm": ("Creo Parametric", "Solid Edge"),    # 판번호 없는 어셈블리 — 어셈블리 언어 소스도 .asm
    ".drw": ("Creo Parametric",),
    ".lay": ("Creo Parametric", "Tecplot 360"),
    ".neu": ("Simcenter Femap", "Creo Parametric"),
    ".sim": ("Simcenter STAR-CCM+", "NX"),        # STAR-CCM+ 시뮬레이션 · NX/Simcenter 3D 시뮬레이션 파일
    ".fem": ("NX", "Altair OptiStruct"),          # Simcenter 3D FE 모델 · OptiStruct 입력
    ".afm": ("NX",),
    ".inp": ("Abaqus", "CalculiX"),
    ".frd": ("FRED", "CalculiX"),
    ".cfx": ("Ansys CFX", "Altair Feko"),         # CFX-Pre 케이스 · CADFEKO 모델
    ".def": ("Ansys CFX",),                       # C/C++ 모듈 정의 파일과 겹친다
    ".res": ("Ansys CFX",),                       # 컴파일된 리소스와 겹친다
    ".msh": ("Ansys Fluent", "Gmsh"),
    ".msh.gz": ("Ansys Fluent",),
    ".jou": ("Ansys Fluent",),                    # Gambit·Cubit 저널과 겹친다
    ".trn": ("Ansys Fluent",),
    ".rst": ("Ansys Mechanical APDL",),           # reStructuredText 문서
    ".pch": ("Nastran",),                         # C/C++ 미리 컴파일된 헤더
    ".dwg": ("AutoCAD", "ZWCAD"),
    ".par": ("Solid Edge",),
    ".dft": ("Solid Edge",),
    ".m": ("MATLAB / Simulink", "GNU Octave"),
    ".mat": ("MATLAB / Simulink",),               # 파이썬(scipy)·계측 장비도 쓴다
    ".opj": ("Cadence Allegro / OrCAD", "Origin"),
    ".sdy": ("Autodesk Moldflow", "Creo Simulate"),
    ".mfr": ("Autodesk Moldflow", "Creo Simulate"),
    ".plt": ("Tecplot 360",),                     # HPGL 플롯과 겹친다
    ".asc": ("LTspice",),                         # 점군·격자 ASCII 와 겹친다
    ".tdms": ("LabVIEW",),
    ".lvm": ("LabVIEW",),
}
# Creo 판번호 파일 bracket.prt.3 — core\extract._CREO_RE·수집기(creoRe)와 같은 목록이어야 한다
_CREO_RE = re.compile(r"\.(prt|asm|drw|frm|sec|lay|mfg|gph|neu)\.\d{1,4}$", re.I)
_COMPOUND = (".cas.gz", ".dat.gz", ".cas.h5", ".dat.h5", ".msh.h5", ".msh.gz")


def _norm(proc):
    p = (proc or "").strip().lower()
    if p.endswith(".exe"):
        p = p[:-4]
    return p


def is_noise(proc):
    """사람이 '쓴' 프로그램이 아닌 것 — 라이선스 대리자·OS 서비스."""
    p = _norm(proc)
    return not p or any(p.startswith(x) for x in EXCLUDE)


def install_noise(proc):
    """설치·갱신·제거 프로그램인가(실행 기록 전용 — 창 기록 판정은 예전 그대로 is_noise 만 본다)."""
    return bool(_INSTALL_RX.search(_norm(proc)))


def inhouse_noise(proc):
    """자체·프로토타입으로 세지 않을 이름 — 설치·갱신·런처·도우미·임시 이름, 두 글자 미만."""
    p = _norm(proc)
    return len(p) < 2 or install_noise(p) or bool(_INHOUSE_NOISE_RX.search(p))


def vendor_of_folder(vf):
    """공급사 폴더 이름(소문자) → (공급사, 분류) · 모르면 None. 앞부분 일치 — 'ansys inc'·'msc.software'."""
    v = str(vf or "").strip().lower()
    if not v:
        return None
    for pre, vendor, cat in _VENDOR_DIRS:
        if v.startswith(pre):
            return vendor, cat
    return None


def _extra_hit(p, extra):
    for e in (extra or ()):
        if not isinstance(e, dict):
            continue
        m = str(e.get("match") or "").strip().lower()
        if m and (p == m or p.startswith(m)):
            return m, e
    return None, None


def _extra_item(e, m):
    return {"name": str(e.get("name") or m), "vendor": str(e.get("vendor") or "사내"),
            "kind": str(e.get("kind") or "비상용"), "cat": str(e.get("cat") or "기타")}


def classify(proc, extra=(), vf=""):
    """process(실행 파일) 이름 → {"name","vendor","kind","cat"} · 모르면 None.

    extra: config.programsExtra — [{"match": "myfea", "name": "사내 해석기",
           "kind": "비상용", "cat": "해석", "vendor": "사내"}] · 카탈로그보다 먼저 본다.
    사내에서 만든 도구는 이름을 알 길이 없으니 이 통로로 넣는다.
    vf: 실행 기록이 알려 준 공급사 폴더(Program Files 바로 아래, 소문자) — 겹치는 이름(_QUALIFIED)과
        '<공급사> 기타 도구'(VENDOR_DIRS) 판정에만 쓴다. 창 기록(옛 샘플러)은 폴더를 몰라 빈 값이다."""
    p = _norm(proc)
    if not p or is_noise(p):
        return None
    m, e = _extra_hit(p, extra)
    if e is not None:
        return _extra_item(e, m)
    it = _EXACT.get(p)
    if it:
        return dict(it)
    for pre, it in _PREFIX:
        if p.startswith(pre):
            return dict(it)
    v = str(vf or "").strip().lower()
    if v:
        for vpre, names, disp in _QUALIFIED:
            if v.startswith(vpre) and any(p == n or p.startswith(n) for n in names):
                return dict(_BY_NAME[disp])
        vv = vendor_of_folder(v)
        if vv:
            return {"name": f"{vv[0]} 기타 도구", "vendor": vv[0], "kind": "상용", "cat": vv[1]}
    return None


def match_key(proc, extra=()):
    """classify 와 같은 규칙으로 맞힌 '별칭'(카탈로그의 이름 조각 · programsExtra 의 match) — 못 맞히면 None.
    바로 가기 이름처럼 그대로 남기면 안 되는 문자열(문서·폴더 이름일 수 있다)을 맞힌 별칭으로 바꿔 저장한다(수집기).
    classify(match_key(x)) 는 classify(x) 와 같은 프로그램이다."""
    p = _norm(proc)
    if not p or is_noise(p):
        return None
    m, e = _extra_hit(p, extra)
    if e is not None:
        return m
    if p in _EXACT:
        return p
    for pre, _it in _PREFIX:
        if p.startswith(pre):
            return pre
    return None


_LNK_VER = re.compile(r"(?<![a-z])(?:r?\d[\d.]*[a-z]?|x64|x86|64-?bit|32-?bit|sp\d+)(?![a-z])")


def lnk_key(name):
    """바로 가기 이름 → 맞히기용 열쇠: 소문자·'.lnk' 와 괄호·판번호(2023 R1·9.0.2.0·R2023a·x64) 제거·공백/하이픈/밑줄/점 제거.
    'Workbench 2023 R1' → workbench · 'LS-PrePost 4.10 (64-bit)' → lsprepost · 'Visual Studio Code' → visualstudiocode."""
    s = str(name or "").strip().lower()
    if s.endswith(".lnk"):
        s = s[:-4]
    s = re.sub(r"\([^)]*\)", " ", s)
    s = _LNK_VER.sub(" ", s)
    return re.sub(r"[\s\-_.]+", "", s)


def program_info(name):
    """표시 이름 → 항목(복사본) · 모르면 None."""
    it = _BY_NAME.get(str(name or ""))
    return dict(it) if it else None


def file_program(name, ext, extra=()):
    """파일 이름·확장자(수집기 ext 열 — Creo 판번호는 .prt 로 적힌다) → 그 파일을 만드는 도구.
    → ("prog", 항목) · ("amb", 확장자, 후보 표시 이름들) · None(도구를 말해 주지 않는 확장자).
    programsExtra 의 "ext": [".sim"] 이 무엇보다 먼저다(조직이 모호한 확장자의 도구를 정한다)."""
    n = str(name or "").strip().lower()
    e = str(ext or "").strip().lower()
    for ce in _COMPOUND:
        if n.endswith(ce):
            e = ce
            break
    if e and not e.startswith("."):
        e = "." + e
    for x in (extra or ()):
        if not isinstance(x, dict) or not str(x.get("name") or "").strip():
            continue
        exts = x.get("ext")
        exts = [exts] if isinstance(exts, str) else (exts if isinstance(exts, list) else [])
        if e and e in {str(y).strip().lower() for y in exts}:
            nm = str(x.get("name")).strip()
            base = program_info(nm) or {}
            return "prog", {"name": nm, "vendor": str(x.get("vendor") or base.get("vendor") or "사내"),
                            "kind": str(x.get("kind") or base.get("kind") or "비상용"),
                            "cat": str(x.get("cat") or base.get("cat") or "기타")}
    if _CREO_RE.search(n):
        return "prog", program_info("Creo Parametric")
    if e in EXT_PROGRAM:
        return "prog", program_info(EXT_PROGRAM[e])
    if e in AMBIGUOUS_EXT:
        return "amb", e, AMBIGUOUS_EXT[e]
    return None


def registry_item(it, extra=()):
    """실행 기록 스냅샷 항목(collect\\Get-ProgramUsage.py — exe·cls·vf·k) → 판정.
    → ("prog", 항목) · ("inhouse", 이름) · ("unknown", 이름) · None(세지 않는다).
      · 카탈로그(programsExtra 먼저)·공급사 폴더로 맞히면 prog. 바로 가기(k=lnk)는 수집기가 카탈로그 별칭으로만 남겼다.
      · 못 맞힌 것 중 사용자 폴더·다른 드라이브·네트워크(INHOUSE_CLS)에서 돈 것은 자체·프로토타입(추정) — 설치·런처 소음 제외.
        그 폴더에 제거 프로그램이 있던 것(수집기가 inst=1 — D:\\ 에 설치한 게임·방송·편집 도구)은 설치본이라 unknown.
      · Program Files·ProgramData·AppData 의 미상은 unknown(설치된 프로그램 — 카탈로그·programsExtra 에 보탤 후보).
      · Windows·스토어·출처 모름의 미상은 None(OS 구성 요소·앱 — 자체 도구가 아니다)."""
    if not isinstance(it, dict):
        return None
    exe = _norm(str(it.get("exe") or ""))
    if not exe or is_noise(exe) or install_noise(exe):
        return None
    c = classify(exe, extra, vf=it.get("vf") or "")
    if c:
        return "prog", c
    if it.get("k") == "lnk":
        return None
    cls = str(it.get("cls") or "unknown")
    if cls in INHOUSE_CLS:
        if it.get("inst"):
            return "unknown", exe               # 제거 프로그램과 함께 깔린 설치본 — 자체 도구가 아니다
        return None if inhouse_noise(exe) else ("inhouse", exe)
    if cls in ("pf", "pf86", "appdata"):
        return "unknown", exe
    return None


def solver_names():
    """config.solverProcesses 기본값 — 배경에서 돌아가는 솔버 이름."""
    return list(SOLVER_HINTS)

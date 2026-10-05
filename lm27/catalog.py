# -*- coding: utf-8 -*-
r"""프로그램 카탈로그 단일원(계약 §2.8 · X-245, CP §6) — 실행 파일 이름 → 무슨 프로그램인가.

이전 판 ``core/programs.py`` 를 옮겨 다시 설계했다. 바뀐 점:
  · **프로그램 사용은 1급 업무 신호다**(CP §6.1). 이전 판의 '시간 계산에 쓰지 않는다' 규칙은 폐기 — 그 규칙의 원인이던
    가중치 비율 MM 배분은 구간 귀속 모델로 대체됐다.
  · 행마다 ``app_id``(계약 §3.1 형식 ``^[a-z0-9_.:\-]{1,48}$`` 의 slug)와 ``app_class``(정제기 창 분류 입력 18값)를 갖는다.
  · 범주 ``cat`` 은 한글 9종(CAD·해석·광학·EDA·FPGA·SW·계측·사무·소통)만. 그 밖(파일 도구·미디어·게임)은 ``""``.
  · 카탈로그에 없는 exe 는 ``classify()`` 가 None → ``app_id = "unknown:<exe 소문자>"``(fg_exe 열과 같은 표기).
    공급사·서명자 휴리스틱(``guess_meta``)은 미지 exe 의 **추정 범주**만 준다(CP §6.3) — app_id 는 바꾸지 않는다.

맞히는 규칙(이전 판 그대로):
  · ``EXCLUDE``(라이선스 대리자·OS 서비스) 접두가 무엇보다 먼저 — 앱으로 세지 않는다.
  · ``pc.programsExtra``(설정 — 사내 도구 라벨) → exact → 긴 접두 우선.

이 모듈은 에이전트 bin 사본에 들어간다(계약 §1.3) — **표준 라이브러리만** import 하고 ``lm27.config`` 를 부르지 않는다.
설정 값은 호출자가 넘긴다(``cfg`` = ``lm27.config.Cfg`` 또는 ``agent_config.json`` 의 dict — ``key in cfg``·``cfg[key]`` 만 쓴다).
"""
from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass

CATALOG_VERSION = "2026.10.0"

# 계약 §2.8 · H X10 — 범주 9종(분석 모듈이 읽는 한 곳). 값이 바뀌면 H 의 CAT_FIELD·CAT_FUNC·TECH_CATS 와 같은 커밋.
CATEGORIES = ("CAD", "해석", "광학", "EDA", "FPGA", "SW", "계측", "사무", "소통")
# 계약 §3.2 pc_session.app_class — P §10.2 16값 + remote·meeting
APP_CLASSES = ("office", "cad", "sim", "eda", "ide", "pdf", "viewer", "browser", "chat_work", "mail_work",
               "messenger_private", "media", "game", "system", "idle", "other", "remote", "meeting")
KINDS = ("상용", "비상용")
APP_ID_RX = re.compile(r"^[a-z0-9_.:\-]{1,48}$")
UNKNOWN_PREFIX = "unknown:"
EXTRA_PREFIX = "x."

# 설정 키(계약 §5.2 — 읽는 곳 lm27.catalog). 값은 호출자가 넘긴 cfg 에서 읽는다.
KEY_EXTRA = "pc.programsExtra"
KEY_SOLVERS = "pc.solverProcesses"
KEY_SOLVERS_EXCLUDE = "pc.solverProcessesExclude"

# 이전 판·명세 표기 → 범주 9종(그 밖은 "")
_CAT_ALIAS = {
    "cad": "CAD", "기구": "CAD", "해석": "해석", "시뮬레이션": "해석", "sim": "해석", "광학": "광학", "eda": "EDA",
    "회로": "EDA", "fpga": "FPGA", "fpga·펌웨어": "FPGA", "펌웨어": "FPGA", "sw": "SW", "sw개발": "SW", "개발": "SW",
    "계측": "계측", "사무": "사무", "소통": "소통",
}
# 범주 → 기본 app_class(항목이 따로 정하지 않았을 때)
_CAT_CLASS = {"CAD": "cad", "해석": "sim", "광학": "sim", "EDA": "eda", "FPGA": "eda", "SW": "ide", "계측": "other",
              "사무": "office", "소통": "other", "": "other"}

# 무엇을 해도 프로그램으로 세지 않는다 — 라이선스 대리자·OS 서비스는 사람이 쓴 시간이 아니다(접두 일치).
EXCLUDE = (
    "ansysli", "lmgrd", "lmadmin", "flexlm", "flexnet", "msc_licensing", "dsls",
    "nxlmd", "ugslmd", "armlmd", "ptcflexlm", "cdslmd", "alterad", "xilinxd",
    "svchost", "dwm", "csrss", "winlogon", "sihost", "taskhostw", "runtimebroker",
    "searchhost", "startmenuexperiencehost", "shellexperiencehost", "textinputhost",
    "applicationframehost", "systemsettings", "lockapp", "ctfmon", "conhost",
    "backgroundtaskhost", "smartscreen", "securityhealthservice", "msmpeng",
    "wmiprvse", "audiodg", "fontdrvhost", "sppsvc", "dllhost", "sedsvc",
)

# 배경에서 '돌려 놓고 기다리는' 솔버 이름 — pc.solverProcesses 기본값의 원천. GUI 만 있는 것(hypermesh·patran)은 넣지 않는다.
SOLVER_HINTS = ("ansys", "mapdl", "fluent", "cortex", "fl_mpi", "cfx5solve", "abaqus", "nastran",
                "comsol", "lsdyna", "starccm", "optistruct", "radioss", "hwsolver", "moldflow",
                "floefd", "icepak", "ansysedt", "simplefoam", "pimplefoam", "interfoam",
                "ccx", "su2_cfd", "elmersolver", "aster")
# pc.solverProcessesExclude 기본값 — 로그온 내내 떠 있는 라이선스 대리자(이전 판 '하루 종일 해석' 오탐)
SOLVER_EXCLUDE = ("ansysli", "lmgrd", "lmadmin", "flexlm", "flexnet", "msc_licensing", "dsls", "nxlmd", "ugslmd",
                  "armlmd", "ptcflexlm", "cdslmd", "alterad", "xilinxd")

# (이름들, app_id, 표시 이름, 공급사, 상용/비상용, 범주, app_class, 맞히는 방식)
_CATALOG = (
    # ── 기구·CAD ──────────────────────────────────────────────────────────────
    (("xtop", "creo", "parametric", "proe", "pro_comm_msg"), "creo_parametric", "Creo Parametric", "PTC", "상용", "CAD",
     "cad", "prefix"),
    (("cnext", "catia", "catstart", "3dexperience"), "catia", "CATIA", "Dassault", "상용", "CAD", "cad", "prefix"),
    (("ugraf", "ugii", "nxmanager"), "nx", "NX", "Siemens", "상용", "CAD", "cad", "prefix"),
    (("sldworks", "swspmanager"), "solidworks", "SOLIDWORKS", "Dassault", "상용", "CAD", "cad", "prefix"),
    (("edge",), "solid_edge", "Solid Edge", "Siemens", "상용", "CAD", "cad", "exact"),   # MS Edge 는 msedge
    (("inventor",), "inventor", "Inventor", "Autodesk", "상용", "CAD", "cad", "prefix"),
    (("acad", "acadlt"), "autocad", "AutoCAD", "Autodesk", "상용", "CAD", "cad", "prefix"),
    (("spaceclaim", "scdm"), "spaceclaim", "SpaceClaim", "Ansys", "상용", "CAD", "cad", "prefix"),
    (("ansysdiscovery", "discovery"), "ansys_discovery", "Ansys Discovery", "Ansys", "상용", "CAD", "cad", "prefix"),
    (("freecad",), "freecad", "FreeCAD", "오픈소스", "비상용", "CAD", "cad", "prefix"),
    (("blender",), "blender", "Blender", "오픈소스", "비상용", "CAD", "cad", "prefix"),
    # ── 해석·시뮬레이션(상용) ─────────────────────────────────────────────────
    (("ansysedt", "hfss", "maxwell", "simplorer", "q3d"), "ansys_electronics_desktop", "Ansys Electronics Desktop",
     "Ansys", "상용", "해석", "sim", "prefix"),
    (("ansyswb", "runwb2", "ansysfw", "workbench"), "ansys_workbench", "Ansys Workbench", "Ansys", "상용", "해석", "sim",
     "prefix"),
    (("ansys", "mapdl"), "ansys_mechanical_apdl", "Ansys Mechanical APDL", "Ansys", "상용", "해석", "sim", "prefix"),
    (("fluent", "cortex", "fl_mpi", "fluentbench"), "ansys_fluent", "Ansys Fluent", "Ansys", "상용", "해석", "sim",
     "prefix"),
    (("cfx5", "cfx"), "ansys_cfx", "Ansys CFX", "Ansys", "상용", "해석", "sim", "prefix"),
    (("icepak",), "ansys_icepak", "Ansys Icepak", "Ansys", "상용", "해석", "sim", "prefix"),
    (("floefd", "flotherm", "efdlite", "swflow", "flowsim"), "floefd_flotherm", "FloEFD / FloTHERM", "Siemens", "상용",
     "해석", "sim", "prefix"),
    (("abaqus", "abq", "smasimutility"), "abaqus", "Abaqus", "Dassault", "상용", "해석", "sim", "prefix"),
    (("comsol",), "comsol_multiphysics", "COMSOL Multiphysics", "COMSOL", "상용", "해석", "sim", "prefix"),
    (("nastran", "patran", "femap", "mscnastran"), "msc_nastran_patran_femap", "MSC Nastran / Patran / FEMAP",
     "Hexagon", "상용", "해석", "sim", "prefix"),
    (("hypermesh", "hyperview", "hypergraph", "hwsolver", "optistruct", "radioss", "hstudy"), "altair_hyperworks",
     "Altair HyperWorks", "Altair", "상용", "해석", "sim", "prefix"),
    (("lsdyna", "ls-dyna", "lsprepost", "lspp"), "ls_dyna", "LS-DYNA", "Ansys", "상용", "해석", "sim", "prefix"),
    (("starccm", "star-ccm"), "simcenter_star_ccm", "Simcenter STAR-CCM+", "Siemens", "상용", "해석", "sim", "prefix"),
    (("moldflow", "synergy"), "moldflow", "Moldflow", "Autodesk", "상용", "해석", "sim", "prefix"),
    (("recurdyn",), "recurdyn", "RecurDyn", "FunctionBay", "상용", "해석", "sim", "prefix"),
    (("adams",), "adams", "Adams", "Hexagon", "상용", "해석", "sim", "prefix"),
    (("matlab", "simulink", "mathworks"), "matlab_simulink", "MATLAB / Simulink", "MathWorks", "상용", "해석", "sim",
     "prefix"),
    (("mathcad", "maple", "mathematica"), "math_solvers", "수식 해석기", "각사", "상용", "해석", "sim", "prefix"),
    # ── 해석·시뮬레이션(비상용·오픈소스) ──────────────────────────────────────
    (("paraview", "pvserver", "pvpython"), "paraview", "ParaView", "오픈소스", "비상용", "해석", "sim", "prefix"),
    (("salome",), "salome", "SALOME", "오픈소스", "비상용", "해석", "sim", "prefix"),
    (("gmsh",), "gmsh", "Gmsh", "오픈소스", "비상용", "해석", "sim", "prefix"),
    (("elmergui", "elmersolver"), "elmer", "Elmer", "오픈소스", "비상용", "해석", "sim", "prefix"),
    (("su2_",), "su2", "SU2", "오픈소스", "비상용", "해석", "sim", "prefix"),
    (("ccx", "cgx"), "calculix", "CalculiX", "오픈소스", "비상용", "해석", "sim", "prefix"),
    (("aster", "code_aster"), "code_aster", "Code_Aster", "오픈소스", "비상용", "해석", "sim", "prefix"),
    (("simplefoam", "pimplefoam", "interfoam", "foamrun", "blockmesh", "snappyhexmesh", "chtmultiregionfoam"),
     "openfoam", "OpenFOAM", "오픈소스", "비상용", "해석", "sim", "prefix"),
    (("openradioss",), "openradioss", "OpenRadioss", "오픈소스", "비상용", "해석", "sim", "prefix"),
    # ── 광학 ──────────────────────────────────────────────────────────────────
    (("opticstudio", "zemax"), "zemax_opticstudio", "Zemax OpticStudio", "Ansys", "상용", "광학", "sim", "prefix"),
    (("codev",), "code_v", "CODE V", "Synopsys", "상용", "광학", "sim", "prefix"),
    (("lighttools",), "lighttools", "LightTools", "Synopsys", "상용", "광학", "sim", "prefix"),
    (("tracepro",), "tracepro", "TracePro", "Lambda", "상용", "광학", "sim", "prefix"),
    (("fred",), "fred", "FRED", "Photon Engineering", "상용", "광학", "sim", "exact"),
    (("asap",), "asap", "ASAP", "Breault", "상용", "광학", "sim", "exact"),
    (("fdtd-solutions", "mode-solutions", "lumerical", "interconnect"), "lumerical", "Lumerical", "Ansys", "상용", "광학",
     "sim", "prefix"),
    (("virtuallab",), "virtuallab_fusion", "VirtualLab Fusion", "LightTrans", "상용", "광학", "sim", "prefix"),
    (("rsoft", "fullwave", "beamprop"), "rsoft", "RSoft", "Synopsys", "상용", "광학", "sim", "prefix"),
    # ── 회로·EDA ──────────────────────────────────────────────────────────────
    (("dxp", "altium"), "altium_designer", "Altium Designer", "Altium", "상용", "EDA", "eda", "prefix"),
    (("allegro", "orcad", "pspice", "sigrity"), "cadence_allegro_orcad", "Cadence Allegro / OrCAD", "Cadence", "상용",
     "EDA", "eda", "prefix"),
    (("pads", "xpedition", "expedition", "hyperlynx"), "siemens_pads_xpedition", "Siemens PADS / Xpedition", "Siemens",
     "상용", "EDA", "eda", "prefix"),
    (("hpeesofsim", "adsmain"), "keysight_ads", "Keysight ADS", "Keysight", "상용", "EDA", "eda", "prefix"),
    (("ads",), "keysight_ads", "Keysight ADS", "Keysight", "상용", "EDA", "eda", "exact"),
    (("saber",), "saber", "Saber", "Synopsys", "상용", "EDA", "eda", "prefix"),
    (("kicad", "pcbnew", "eeschema"), "kicad", "KiCad", "오픈소스", "비상용", "EDA", "eda", "prefix"),
    (("ltspice", "xviix", "scad3"), "ltspice", "LTspice", "Analog Devices", "비상용", "EDA", "eda", "prefix"),
    (("qucs", "ngspice"), "qucs_ngspice", "Qucs / ngspice", "오픈소스", "비상용", "EDA", "eda", "prefix"),
    # ── FPGA·펌웨어·차량 ──────────────────────────────────────────────────────
    (("vivado", "vitis", "xsdb"), "vivado_vitis", "Vivado / Vitis", "AMD Xilinx", "상용", "FPGA", "eda", "prefix"),
    (("quartus", "qsys"), "quartus", "Quartus", "Intel Altera", "상용", "FPGA", "eda", "prefix"),
    (("uv4", "uvision"), "keil_mdk", "Keil MDK", "Arm", "상용", "FPGA", "ide", "prefix"),
    (("iaridepm", "iarideipm", "iarbuild"), "iar_embedded_workbench", "IAR Embedded Workbench", "IAR", "상용", "FPGA",
     "ide", "prefix"),
    (("stm32cube", "stm32"), "stm32cube", "STM32Cube", "ST", "비상용", "FPGA", "ide", "prefix"),
    (("t32m",), "trace32", "Lauterbach TRACE32", "Lauterbach", "상용", "FPGA", "eda", "prefix"),
    (("canoe", "canalyzer", "canape", "vteststudio", "candela"), "vector_canoe", "Vector CANoe 계열", "Vector", "상용",
     "FPGA", "eda", "prefix"),
    (("modelsim", "questasim"), "modelsim_questa", "ModelSim / Questa", "Siemens", "상용", "FPGA", "eda", "prefix"),
    # ── SW 개발 ───────────────────────────────────────────────────────────────
    (("devenv",), "visual_studio", "Visual Studio", "Microsoft", "상용", "SW", "ide", "prefix"),
    (("code",), "vscode", "Visual Studio Code", "Microsoft", "비상용", "SW", "ide", "exact"),
    (("pycharm", "idea", "clion", "webstorm", "rider", "datagrip"), "jetbrains_ide", "JetBrains IDE", "JetBrains", "상용",
     "SW", "ide", "prefix"),
    (("python", "ipython", "jupyter", "conda", "anaconda", "spyder"), "python", "Python", "오픈소스", "비상용", "SW",
     "ide", "prefix"),
    (("eclipse",), "eclipse", "Eclipse", "오픈소스", "비상용", "SW", "ide", "prefix"),
    (("git", "sourcetree", "tortoisegit", "gitextensions", "githubdesktop"), "git_tools", "Git 도구", "각사", "비상용",
     "SW", "ide", "prefix"),
    (("windowsterminal", "powershell", "pwsh", "putty", "mobaxterm", "xshell", "wsl", "ubuntu", "cmd"),
     "terminal", "터미널·원격 셸", "각사", "비상용", "SW", "other", "prefix"),
    (("docker",), "docker", "Docker", "Docker", "비상용", "SW", "other", "prefix"),
    (("vmware", "virtualbox", "vmconnect"), "virtual_machine", "가상 머신", "각사", "비상용", "SW", "remote", "prefix"),
    # ── 계측·데이터 ───────────────────────────────────────────────────────────
    (("labview",), "labview", "LabVIEW", "NI", "상용", "계측", "ide", "prefix"),
    (("benchvue", "keysight", "tekscope", "signalvu"), "instrument_tools", "계측 장비 도구", "각사", "상용", "계측",
     "other", "prefix"),
    (("origin",), "origin", "Origin", "OriginLab", "상용", "계측", "viewer", "prefix"),
    (("minitab", "jmp"), "stat_tools", "통계 도구", "각사", "상용", "계측", "viewer", "prefix"),
    # ── 사무 ──────────────────────────────────────────────────────────────────
    (("excel",), "excel", "Excel", "Microsoft", "상용", "사무", "office", "prefix"),
    (("winword",), "word", "Word", "Microsoft", "상용", "사무", "office", "prefix"),
    (("powerpnt",), "powerpoint", "PowerPoint", "Microsoft", "상용", "사무", "office", "prefix"),
    (("onenote",), "onenote", "OneNote", "Microsoft", "상용", "사무", "office", "prefix"),
    (("msaccess", "mspub", "winproj", "visio"), "office_other", "Office 기타", "Microsoft", "상용", "사무", "office",
     "prefix"),
    (("hwp", "hword", "hcell", "hshow", "hoffice"), "hancom_office", "한컴오피스", "한글과컴퓨터", "상용", "사무", "office",
     "prefix"),
    (("acrobat", "acrord32", "foxit", "sumatrapdf"), "pdf_tools", "PDF 도구", "각사", "상용", "사무", "pdf", "prefix"),
    # ── 소통 ──────────────────────────────────────────────────────────────────
    (("outlook", "olk"), "outlook", "Outlook", "Microsoft", "상용", "소통", "mail_work", "prefix"),
    (("teams", "ms-teams"), "teams", "Teams", "Microsoft", "상용", "소통", "chat_work", "prefix"),
    (("slack",), "slack", "Slack", "Slack", "상용", "소통", "chat_work", "prefix"),
    (("zoom", "webex", "ciscowebex"), "web_meeting", "화상 회의", "각사", "상용", "소통", "meeting", "prefix"),
    (("msedge",), "edge", "Microsoft Edge", "Microsoft", "비상용", "소통", "browser", "prefix"),
    (("chrome",), "chrome", "Chrome", "Google", "비상용", "소통", "browser", "prefix"),
    (("firefox", "whale", "iexplore", "brave", "opera"), "web_browser", "웹 브라우저", "각사", "비상용", "소통",
     "browser", "prefix"),
    (("mstsc", "teamviewer", "anydesk", "vncviewer", "rdcman", "msrdc"), "remote_access", "원격 접속", "각사", "비상용",
     "소통", "remote", "prefix"),
    (("kakaotalk", "telegram", "discord", "whatsapp", "line"), "private_messenger", "개인 메신저", "각사", "비상용",
     "소통", "messenger_private", "exact"),
    # ── 그 밖(범주 없음) ──────────────────────────────────────────────────────
    (("explorer",), "explorer", "파일 탐색기", "Microsoft", "비상용", "", "system", "exact"),
    (("7zfm", "winrar", "bandizip", "everything", "notepad"), "file_utils", "파일·유틸", "각사", "비상용", "", "other",
     "prefix"),
    (("vlc", "potplayer", "spotify", "wmplayer", "music.ui", "video.ui"), "media_player", "미디어 재생", "각사",
     "비상용", "", "media", "prefix"),
    (("steam", "epicgameslauncher", "battle.net", "leagueclient", "riotclientservices"), "game", "게임", "각사", "비상용",
     "", "game", "prefix"),
)

# 미지 exe 의 공급사 휴리스틱(CP §6.3) — (낱말, 공급사 표시, 추정 범주). 낱말은 회사·서명자 문자열에서 단어 경계로 찾는다.
VENDOR_HINTS = (
    ("ansys", "Ansys", "해석"), ("dassault", "Dassault", "CAD"), ("autodesk", "Autodesk", "CAD"),
    ("ptc", "PTC", "CAD"), ("parametric technology", "PTC", "CAD"), ("siemens", "Siemens", ""),
    ("mentor graphics", "Siemens", "EDA"), ("hexagon", "Hexagon", "해석"), ("msc software", "Hexagon", "해석"),
    ("altair", "Altair", "해석"), ("comsol", "COMSOL", "해석"), ("mathworks", "MathWorks", "해석"),
    ("functionbay", "FunctionBay", "해석"), ("esi group", "ESI", "해석"),
    ("zemax", "Ansys", "광학"), ("lighttrans", "LightTrans", "광학"), ("lambda research", "Lambda", "광학"),
    ("photon engineering", "Photon Engineering", "광학"), ("breault", "Breault", "광학"),
    ("synopsys", "Synopsys", ""), ("cadence", "Cadence", "EDA"), ("altium", "Altium", "EDA"),
    ("keysight", "Keysight", "계측"), ("agilent", "Keysight", "계측"), ("national instruments", "NI", "계측"),
    ("tektronix", "Tektronix", "계측"), ("rohde", "Rohde & Schwarz", "계측"), ("originlab", "OriginLab", "계측"),
    ("minitab", "Minitab", "계측"),
    ("xilinx", "AMD Xilinx", "FPGA"), ("altera", "Intel Altera", "FPGA"), ("lattice semiconductor", "Lattice", "FPGA"),
    ("microchip", "Microchip", "FPGA"), ("arm limited", "Arm", "FPGA"), ("iar systems", "IAR", "FPGA"),
    ("lauterbach", "Lauterbach", "FPGA"), ("vector informatik", "Vector", "FPGA"),
    ("stmicroelectronics", "ST", "FPGA"), ("texas instruments", "TI", "FPGA"),
    ("jetbrains", "JetBrains", "SW"), ("python software foundation", "PSF", "SW"), ("github", "GitHub", "SW"),
    ("hancom", "한글과컴퓨터", "사무"), ("adobe", "Adobe", "사무"), ("foxit", "Foxit", "사무"),
    ("zoom video", "Zoom", "소통"), ("cisco", "Cisco", "소통"), ("slack", "Slack", "소통"),
)
_MS_OFFICE_WORDS = ("office", "word", "excel", "powerpoint", "onenote", "visio", "project", "access", "publisher")
_MS_COMM_WORDS = ("outlook", "teams", "skype", "lync")
_FREE_WORDS = ("open source", "opensource", "community", "free software", "foundation", "gnu ")


@dataclass(frozen=True)
class Prog:
    """카탈로그 한 항목(``classify`` 결과). ``cat`` 은 범주 9종 또는 ``""``."""

    app_id: str
    name: str
    vendor: str
    kind: str
    cat: str
    app_class: str

    def as_dict(self) -> dict:
        return asdict(self)


# ───────────────────────────── 색인(가져올 때 1회) ─────────────────────────────
def _build():
    exact, prefix, by_id = {}, [], {}
    for names, app_id, disp, vendor, kind, cat, app_class, how in _CATALOG:
        item = Prog(app_id, disp, vendor, kind, cat, app_class)
        by_id.setdefault(app_id, item)
        for nm in names:
            if how == "exact":
                exact.setdefault(nm, item)
            else:
                prefix.append((nm, item))
    prefix.sort(key=lambda x: (-len(x[0]), x[0]))
    return exact, tuple(prefix), by_id


_EXACT, _PREFIX, _BY_ID = _build()


# ───────────────────────────── 이름 정규화 ─────────────────────────────
def exe_norm(proc) -> str:
    """프로세스·실행 파일 이름 → 비교용 이름(소문자, 경로·확장자 ``.exe`` 제거, NFKC). 빈 값이면 ""."""
    p = unicodedata.normalize("NFKC", str(proc or "")).strip().strip('"').lower()
    p = re.split(r"[\\/]", p)[-1]
    if p.endswith(".exe"):
        p = p[:-4]
    return p.strip()


def exe_name(proc) -> str:
    """fg_exe 열 표기(계약 §3.2 ``^[a-z0-9_.\\-]{1,64}\\.exe$``)로 맞춘 이름. 허용 밖 글자는 ``_``. 빈 값이면 ""."""
    p = exe_norm(proc)
    if not p:
        return ""
    p = re.sub(r"[^a-z0-9_.\-]", "_", p)[:60]
    return p + ".exe"


def slug(s) -> str:
    """표시 이름·사내 도구 이름 → app_id 조각(ASCII 소문자·숫자·``_``, 최대 40자). ASCII 가 하나도 없으면 ""."""
    t = unicodedata.normalize("NFKC", str(s or "")).lower()
    t = re.sub(r"[^a-z0-9]+", "_", t).strip("_")
    return t[:40].strip("_")


def norm_cat(cat) -> str:
    """범주 표기 → 범주 9종 중 하나 또는 ""(이전 판 'FPGA·펌웨어'·'SW개발'·'기타' 등 흡수)."""
    c = str(cat or "").strip()
    if c in CATEGORIES:
        return c
    return _CAT_ALIAS.get(c.lower(), "")


def _norm_kind(kind) -> str:
    k = str(kind or "").strip()
    return k if k in KINDS else ""


# ───────────────────────────── 판정 ─────────────────────────────
def is_noise(proc) -> bool:
    """사람이 '쓴' 프로그램이 아닌 것(라이선스 대리자·OS 서비스) 또는 빈 이름."""
    p = exe_norm(proc)
    return not p or any(p.startswith(x) for x in EXCLUDE)


def _extra_items(extra) -> list:
    """pc.programsExtra 항목 → [(match, Prog)] — 형이 틀린 항목은 건너뛴다(설정 레지스트리가 형을 먼저 거른다)."""
    out = []
    for e in extra or ():
        if not isinstance(e, Mapping):
            continue
        m = exe_norm(e.get("match"))
        if not m:
            continue
        sid = slug(e.get("id") or m) or slug(m)
        if not sid:
            continue
        app_id = (EXTRA_PREFIX + sid)[:48]
        cat = norm_cat(e.get("cat"))
        ac = str(e.get("app_class") or "").strip()
        if ac not in APP_CLASSES:
            ac = _CAT_CLASS.get(cat, "other")
        name = str(e.get("name") or m)[:60]
        out.append((m, Prog(app_id, name, str(e.get("vendor") or "사내")[:40], _norm_kind(e.get("kind")) or "비상용",
                            cat, ac)))
    return out


def classify(proc, extra: Iterable = ()) -> Prog | None:
    """프로세스 이름 → ``Prog`` · 모르면 None. 판정 순서: EXCLUDE(None) → ``extra``(pc.programsExtra) → exact → 긴 접두.

    extra 항목 모양: ``{"match": "myfea", "name": "사내 해석기", "kind": "비상용", "cat": "해석", "vendor": "사내",
    "id"?: "myfea", "app_class"?: "sim"}`` — app_id 는 ``x.<id 또는 match slug>``(내장 항목과 겹치지 않게)."""
    p = exe_norm(proc)
    if not p or is_noise(p):
        return None
    for m, item in _extra_items(extra):
        if p == m or p.startswith(m):
            return item
    it = _EXACT.get(p)
    if it is not None:
        return it
    for pre, it in _PREFIX:
        if p.startswith(pre):
            return it
    return None


def unknown_app_id(proc) -> str:
    """카탈로그에 없는 exe 의 app_id — ``unknown:<exe 소문자>``(계약 §3.1 형식, 최대 48자)."""
    ex = exe_name(proc)
    if not ex:
        return ""
    return (UNKNOWN_PREFIX + ex)[:48]


def app_id_for(proc, extra: Iterable = ()) -> str | None:
    """프로세스 이름 → app_id. 잡음(EXCLUDE)·빈 이름은 None, 카탈로그 밖은 ``unknown:<exe>``."""
    if is_noise(proc):
        return None
    it = classify(proc, extra)
    return it.app_id if it is not None else (unknown_app_id(proc) or None)


def _lookup(app_id, extra) -> Prog | None:
    a = str(app_id or "")
    if a.startswith(EXTRA_PREFIX):
        for _m, item in _extra_items(extra):
            if item.app_id == a:
                return item
        return None
    return _BY_ID.get(a)


def cat_of(app_id, extra: Iterable = ()) -> str:
    """app_id → 범주(한글 9종: CAD·해석·광학·EDA·FPGA·SW·계측·사무·소통). 카탈로그 밖·미지 exe·범주 없는 항목은 ""."""
    it = _lookup(app_id, extra)
    return it.cat if it is not None else ""


def app_class_of(app_id, extra: Iterable = ()) -> str:
    """app_id → 정제기 창 분류 입력 ``app_class``(18값). 카탈로그 밖·미지 exe 는 ``other``."""
    it = _lookup(app_id, extra)
    return it.app_class if it is not None else "other"


def entries() -> list[Prog]:
    """내장 카탈로그 항목(app_id 순, 같은 app_id 는 하나) — 화면·팀 카탈로그 제안 대조용."""
    return [_BY_ID[k] for k in sorted(_BY_ID)]


# ───────────────────────────── 솔버 ─────────────────────────────
def solver_names() -> list[str]:
    """pc.solverProcesses 기본값 — 배경에서 돌아가는 솔버 이름(설정 누락 시 이것을 쓴다 — 이전 판 '솔버 열 통째 빔' 수정)."""
    return list(SOLVER_HINTS)


def _cfg_get(cfg, key, default):
    if cfg is None:
        return default
    try:
        if key in cfg:
            v = cfg[key]
            return default if v is None else v
    except TypeError:
        return default
    return default


def programs_extra(cfg=None) -> tuple:
    """설정 pc.programsExtra(사내 도구 라벨) — cfg 가 없거나 키가 없으면 빈 튜플."""
    v = _cfg_get(cfg, KEY_EXTRA, ())
    return tuple(x for x in v if isinstance(x, Mapping)) if isinstance(v, (list, tuple)) else ()


def solver_set(cfg=None) -> frozenset:
    """솔버 이름 집합 = pc.solverProcesses(기본 SOLVER_HINTS) − pc.solverProcessesExclude(기본 SOLVER_EXCLUDE, 접두 일치)."""
    names = _cfg_get(cfg, KEY_SOLVERS, SOLVER_HINTS)
    excl = _cfg_get(cfg, KEY_SOLVERS_EXCLUDE, SOLVER_EXCLUDE)
    names = [exe_norm(n) for n in (names if isinstance(names, (list, tuple)) else SOLVER_HINTS)]
    excl = [exe_norm(n) for n in (excl if isinstance(excl, (list, tuple)) else SOLVER_EXCLUDE)]
    return frozenset(n for n in names if n and not any(e and n.startswith(e) for e in excl))


def is_solver(proc, cfg=None, *, solvers: frozenset | None = None) -> bool:
    """프로세스가 솔버인가 — 솔버 이름 접두 일치, 단 pc.solverProcessesExclude 접두(상주 대리자)는 아니다."""
    p = exe_norm(proc)
    if not p:
        return False
    excl = _cfg_get(cfg, KEY_SOLVERS_EXCLUDE, SOLVER_EXCLUDE)
    excl = [exe_norm(n) for n in (excl if isinstance(excl, (list, tuple)) else SOLVER_EXCLUDE)]
    if any(e and p.startswith(e) for e in excl):
        return False
    s = solvers if solvers is not None else solver_set(cfg)
    return any(p.startswith(n) for n in s)


# ───────────────────────────── 미지 프로그램 휴리스틱(CP §6.3) ─────────────────────────────
def _has_word(hay: str, needle: str) -> bool:
    return re.search(r"(?<![a-z0-9])" + re.escape(needle) + r"(?![a-z0-9])", hay) is not None


def guess_meta(company="", product="", desc="", signer="") -> dict:
    """미지 exe 의 공개 메타(회사·제품·설명·Authenticode 서명자) → 추정 ``{guess_cat, guess_kind, source, vendor}``.

    판정 순서(CP §6.3): 서명자 → 회사 → 제품·설명 순으로 알려진 공급사를 찾는다. 서명자·회사가 Microsoft 면 OS/Office 류
    (제품명에 Office 앱 낱말이 있으면 '사무', Outlook·Teams 류면 '소통', 아니면 범주 없음). 못 찾으면 범주·종류 빈 값,
    ``source = "none"``. 반환값은 범주 9종·종류(상용/비상용)·출처 열거뿐이며 원문 문자열을 담지 않는다(vendor 는 이 표의 표시 이름)."""
    fields = (("signer", signer), ("company", company), ("product", product), ("desc", desc))
    low = {k: unicodedata.normalize("NFKC", str(v or "")).lower() for k, v in fields}
    for src in ("signer", "company"):
        if "microsoft" in low[src]:
            pd = low["product"] + " " + low["desc"]
            cat = "소통" if any(_has_word(pd, w) for w in _MS_COMM_WORDS) else \
                ("사무" if any(_has_word(pd, w) for w in _MS_OFFICE_WORDS) else "")
            return {"guess_cat": cat, "guess_kind": "상용", "source": src, "vendor": "Microsoft"}
    for src in ("signer", "company", "product", "desc"):
        hay = low[src]
        if not hay:
            continue
        for needle, vendor, cat in VENDOR_HINTS:
            if _has_word(hay, needle):
                kind = "비상용" if any(w in hay for w in _FREE_WORDS) else "상용"
                return {"guess_cat": cat, "guess_kind": kind, "source": src, "vendor": vendor}
    if any(w in (low["company"] + " " + low["product"]) for w in _FREE_WORDS):
        return {"guess_cat": "", "guess_kind": "비상용", "source": "company", "vendor": ""}
    return {"guess_cat": "", "guess_kind": "", "source": "none", "vendor": ""}

"""Select only Edge processes using this installation's dedicated profile."""
import ctypes
from ctypes import wintypes
import ntpath
import os


def windows_arguments(command):
    if os.name != "nt" or not isinstance(command, str) or not command:
        return []
    shell = ctypes.WinDLL("shell32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    shell.CommandLineToArgvW.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(ctypes.c_int)]
    shell.CommandLineToArgvW.restype = ctypes.POINTER(wintypes.LPWSTR)
    kernel.LocalFree.argtypes = [wintypes.HLOCAL]
    kernel.LocalFree.restype = wintypes.HLOCAL
    count = ctypes.c_int()
    values = shell.CommandLineToArgvW(command, ctypes.byref(count))
    if not values:
        return []
    try:
        return [values[i] for i in range(count.value)]
    finally:
        kernel.LocalFree(ctypes.cast(values, wintypes.HLOCAL))


def edge_pids(root, processes):
    """No substring matching, relative paths, or profiles from other installs."""
    expected = ntpath.normcase(ntpath.normpath(ntpath.join(root, "data", "copilot_profile")))
    selected = []
    for process in processes if isinstance(processes, list) else [processes]:
        if not isinstance(process, dict) or str(process.get("Name", "")).lower() != "msedge.exe":
            continue
        args = windows_arguments(process.get("CommandLine"))
        profiles = []
        for i, value in enumerate(args):
            if value.startswith("--user-data-dir="):
                profiles.append(value.split("=", 1)[1])
            elif value == "--user-data-dir" and i + 1 < len(args):
                profiles.append(args[i + 1])
        if len(profiles) != 1:
            continue
        profile = profiles[0]
        drive, tail = ntpath.splitdrive(profile)
        if not drive or not tail.startswith(("\\", "/")):
            continue
        if ntpath.normcase(ntpath.normpath(profile)) != expected:
            continue
        pid = process.get("ProcessId")
        if isinstance(pid, int) and not isinstance(pid, bool) and pid > 0:
            selected.append(pid)
    return sorted(set(selected))

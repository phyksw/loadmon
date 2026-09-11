"""Windows command-line parsing against synthetic process records; no kills."""
import importlib.util
import os
from pathlib import Path
import unittest


APP = Path(__file__).resolve().parents[1] / "LoadMonitor25"
SPEC = importlib.util.spec_from_file_location("process_scope_test", APP / "core" / "process_scope.py")
SCOPE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SCOPE)


@unittest.skipUnless(os.name == "nt", "CommandLineToArgvW is Windows-only")
class ProcessScopeTests(unittest.TestCase):
    def test_only_exact_installation_profile_is_selected(self):
        root = r"D:\Synthetic Folder\LoadMonitor25"
        profiles = [root + r"\data\copilot_profile",
                    root + r" backup\data\copilot_profile",
                    r"D:\Synthetic Folder\LoadMonitor24\data\copilot_profile",
                    root + r"\data\copilot_profile-other", r"data\copilot_profile",
                    r"D:LoadMonitor25\data\copilot_profile"]
        records = [{"Name": "msedge.exe", "ProcessId": i + 1,
                    "CommandLine": 'msedge.exe "--user-data-dir=' + p + '"'} for i, p in enumerate(profiles)]
        records.extend([{"Name": "msedge.exe", "ProcessId": 10,
                         "CommandLine": 'msedge.exe --user-data-dir "' + profiles[0].upper() + '"'},
                        {"Name": "msedge.exe", "ProcessId": 11, "CommandLine": "msedge.exe --title=copilot_profile"},
                        {"Name": "python.exe", "ProcessId": 12, "CommandLine": records[0]["CommandLine"]},
                        {"Name": "msedge.exe", "ProcessId": 13, "CommandLine": None}])
        self.assertEqual(SCOPE.edge_pids(root, records), [1, 10])

    def test_ambiguous_duplicate_profile_options_are_rejected(self):
        root = r"D:\Synthetic\LoadMonitor25"
        command = 'edge.exe --user-data-dir="' + root + r'\data\copilot_profile" --user-data-dir="D:\other"'
        self.assertEqual(SCOPE.edge_pids(root, [{"Name": "msedge.exe", "ProcessId": 1, "CommandLine": command}]), [])


if __name__ == "__main__":
    unittest.main()

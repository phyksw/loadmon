"""Real loopback transport contracts; optional fresh-profile Edge smoke test.

The Edge test is opt-in and visits about:blank only. Normal project verification
does not launch a browser or read any existing account/profile.
"""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import tempfile
import threading
import time
import unittest
from unittest import mock
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


APP = Path(__file__).resolve().parents[1] / "LoadMonitor25"


class BrowserBootstrapTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="lm25-browser-bootstrap-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        (self.root / "tools").mkdir()
        target = self.root / "tools/copilot_auto.py"
        shutil.copyfile(APP / "tools/copilot_auto.py", target)
        spec = importlib.util.spec_from_file_location("synthetic_bootstrap", target)
        self.driver = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.driver)

    def server(self, status, payload):
        requests = []

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                requests.append(self.path)
                content = json.dumps(payload).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(content)))
                self.end_headers()
                self.wfile.write(content)

            do_PUT = do_GET

            def log_message(self, *_args):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        server.daemon_threads = True
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        return server.server_address[1], requests

    def test_loopback_debugger_does_not_use_inherited_http_proxy(self):
        port, direct = self.server(200, {"local_debugger": True})
        proxy_port, proxied = self.server(502, {"proxy_refused_loopback": True})
        proxy = f"http://127.0.0.1:{proxy_port}"
        with mock.patch.dict(os.environ, {"http_proxy": proxy, "HTTP_PROXY": proxy,
                                          "no_proxy": "", "NO_PROXY": ""}, clear=True), \
                mock.patch.object(urllib.request, "_opener", None):
            result = self.driver.http_json(port, "/json/version", timeout=2)
            self.assertIsNone(urllib.request._opener, "The process-wide proxy opener must remain unchanged")
        self.assertEqual(result, {"local_debugger": True})
        self.assertEqual(direct, ["/json/version"])
        self.assertEqual(proxied, [])

    def test_local_new_tab_put_is_preserved(self):
        port, direct = self.server(200, {"id": "synthetic-tab"})
        result = self.driver.http_json(port, "/json/new?about%3Ablank", method="PUT", timeout=2)
        self.assertEqual(result["id"], "synthetic-tab")
        self.assertEqual(direct, ["/json/new?about%3Ablank"])

    @unittest.skipUnless(os.environ.get("LM_TEST_REAL_EDGE_BOOTSTRAP") == "1",
                         "Requires explicit isolated about:blank Edge authorization")
    def test_fresh_headless_edge_profile_and_real_cdp(self):
        self.assert_real_bootstrap(automation=True)

    @unittest.skipUnless(os.environ.get("LM_TEST_REAL_EDGE_BOOTSTRAP") == "1",
                         "Requires explicit isolated about:blank Edge authorization")
    def test_legacy_headless_edge_profile_uses_windows_owner_fallback(self):
        self.assert_real_bootstrap(automation=False)

    def assert_real_bootstrap(self, automation):
        driver = self.driver
        self.assertTrue(driver.find_edge(), "Edge executable is required for this explicit smoke test")
        with socket.socket() as reservation:
            reservation.bind(("127.0.0.1", 0))
            port = reservation.getsockname()[1]
        profile = self.root / "fresh-profile"
        self.assertTrue(profile.is_relative_to(Path(tempfile.gettempdir()).resolve()))
        cfg = {"port": port, "profileDir": str(profile), "url": "about:blank",
               "_collection_deadline": time.monotonic() + 30}
        launched = []
        original_popen, original_http = subprocess.Popen, driver.http_json
        original_owner = driver._windows_listener_arguments
        owner_checks = []

        def read_test_owner(candidate, timeout):
            self.assertEqual(candidate, port)
            result = original_owner(candidate, timeout)
            owner_checks.append(bool(result))
            return result

        def isolated_launch(args, **kwargs):
            if Path(args[0]).name.lower() in ("powershell", "powershell.exe"):
                # The driver's read-only listener ownership fallback is not an
                # Edge launch; subprocess.run also uses this patched Popen.
                return original_popen(args, **kwargs)
            self.assertEqual(driver._argument_value(args, "--user-data-dir"), str(profile))
            self.assertEqual(driver._argument_value(args, "--remote-debugging-port"), str(port))
            self.assertEqual(args[-1], "about:blank")
            if not automation:
                args = [arg for arg in args if arg != "--enable-automation"]
            args = [*args[:-1], "--headless=new", "--disable-gpu", "--disable-background-networking",
                    "--disable-component-update", "--disable-sync", "--disable-default-apps",
                    "--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE localhost", args[-1]]
            process = original_popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **kwargs)
            launched.append(process)
            return process

        def isolated_http(candidate, *args, **kwargs):
            if candidate != port:
                raise OSError("Only this test's freshly reserved port may be contacted")
            return original_http(candidate, *args, **kwargs)

        started = time.monotonic()
        owned = False
        try:
            with mock.patch.object(driver.subprocess, "Popen", side_effect=isolated_launch), \
                    mock.patch.object(driver, "http_json", side_effect=isolated_http), \
                    mock.patch.object(driver, "_windows_listener_arguments", side_effect=read_test_owner):
                self.assertEqual(driver.ensure_edge(cfg), "launched", cfg.get("_edge_reason"))
                owned = True
                self.assertEqual(driver.ensure_edge(cfg), "reused")
                self.assertEqual(len(launched), 1)
                if not automation:
                    self.assertTrue(owner_checks and all(owner_checks), "Legacy ownership must use the real Windows listener fallback")
                version = driver.http_json(port, "/json/version", timeout=3)
                tabs = driver.http_json(port, "/json", timeout=3)
                blank = next(tab for tab in tabs if tab.get("type") == "page" and tab.get("url") == "about:blank")
                connection = driver.CDP(blank["webSocketDebuggerUrl"], timeout=3)
                try:
                    self.assertEqual(connection.eval("({title:document.title,href:location.href})", timeout=3),
                                     {"title": "", "href": "about:blank"})
                finally:
                    connection.close()
                print(json.dumps({"isolated_edge": version.get("Browser"), "bootstrap_seconds": round(time.monotonic()-started, 3),
                                  "launch_reuse_real_cdp": True, "legacy_flags": not automation,
                                  "windows_owner_checks": len(owner_checks), "account_data_accessed": False}))
        finally:
            if owned:
                try:
                    version = original_http(port, "/json/version", timeout=2)
                    connection = driver.CDP(version["webSocketDebuggerUrl"], timeout=2)
                    try:
                        connection.call("Browser.close", timeout=2)
                    finally:
                        connection.close()
                except (OSError, ValueError, RuntimeError, KeyError):
                    pass
            for process in launched:
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.terminate()  # Only the Popen PID this test started.
                    process.wait(timeout=5)


if __name__ == "__main__":
    unittest.main()

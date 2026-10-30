"""用隔离工程目录验证 Shell 生命周期，不启停任何真实业务服务。"""

import fcntl
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tempfile
from unittest import TestCase

from scripts.release_site_ports import listeners


SCRIPT = Path(__file__).resolve().parents[2] / "site.sh"


class SiteScriptTests(TestCase):
    def setUp(self):
        self.project = Path(self.enterContext(tempfile.TemporaryDirectory(prefix="design-ai-site-test-")))
        for folder in ("backend", "frontend", ".runtime"):
            (self.project / folder).mkdir()
        shutil.copyfile(SCRIPT, self.project / "site.sh")

    def run_site(self, operation="start", **environment):
        return subprocess.run(
            ["bash", str(self.project / "site.sh"), operation], cwd=self.project,
            env={**os.environ, **environment}, capture_output=True, text=True, timeout=20,
        )

    def test_invalid_or_duplicate_ports_fail_before_runtime_and_stop(self):
        for frontend, backend in (("80", "80"), ("0", "8000"), ("65536", "8000"),
                                  ("0080", "8000"), ("abc", "8000")):
            with self.subTest(frontend=frontend, backend=backend):
                result = self.run_site(DESIGN_AI_FRONTEND_PORT=frontend, DESIGN_AI_BACKEND_PORT=backend)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("操作失败", result.stderr)
                self.assertNotIn("未运行", result.stdout)

    def test_duplicate_start_does_not_run_preflight_or_touch_pid_files(self):
        lock = self.enterContext((self.project / ".runtime/site.lock").open("w"))
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        pid_file = self.project / ".runtime/backend.pid"
        pid_file.write_text("999999999\n")
        result = self.run_site()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("无需重复启动", result.stdout)
        self.assertEqual(pid_file.read_text(), "999999999\n")

    def test_stale_pid_with_same_command_in_other_project_is_not_stopped(self):
        process = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(30)", "uvicorn app.main:app"],
            cwd=self.project,
        )
        try:
            (self.project / ".runtime/backend.pid").write_text(f"{process.pid}\n")
            result = self.run_site("stop")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("不属于本工程", result.stderr)
            self.assertIsNone(process.poll())
            self.assertFalse((self.project / ".runtime/backend.pid").exists())
        finally:
            process.terminate()
            process.wait(timeout=3)

    def assert_group_stopped(self, ignore_term=False):
        child_code = (
            ("import signal; signal.signal(signal.SIGTERM, signal.SIG_IGN); " if ignore_term else "") +
            "from http.server import HTTPServer, SimpleHTTPRequestHandler; "
            "server = HTTPServer(('127.0.0.1', 0), SimpleHTTPRequestHandler); "
            "print(server.server_port, flush=True); server.serve_forever()"
        )
        parent_code = (
            "import subprocess, sys, time; "
            f"child = subprocess.Popen([sys.executable, '-u', '-c', {child_code!r}], stdout=subprocess.PIPE, text=True); "
            "print(child.stdout.readline().strip(), flush=True); time.sleep(30)"
        )
        process = subprocess.Popen(
            [sys.executable, "-u", "-c", parent_code, "uvicorn app.main:app"],
            cwd=self.project / "backend", start_new_session=True,
            stdout=subprocess.PIPE, text=True,
        )
        try:
            port = int(process.stdout.readline())
            (self.project / ".runtime/backend.pid").write_text(f"{process.pid}\n")
            result = self.run_site("stop")
            self.assertEqual(result.returncode, 0, result.stderr)
            if ignore_term:
                self.assertIn("已强制停止", result.stdout)
            self.assertEqual(process.wait(timeout=3), -signal.SIGTERM)
            self.assertEqual(listeners(port), set())
        finally:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait(timeout=3)
            process.stdout.close()

    def test_stop_cleans_descendant_listener_in_private_process_group(self):
        self.assert_group_stopped()

    def test_stubborn_descendant_is_stopped_even_after_parent_exits(self):
        self.assert_group_stopped(ignore_term=True)

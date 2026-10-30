"""离线验证端口接管边界；真实检查仅使用测试自行创建的临时 HTTP 监听者。"""

from pathlib import Path
import signal
import subprocess
import sys
from unittest import TestCase
from unittest.mock import call, patch

from scripts import release_site_ports as ports


class PortOwnershipTests(TestCase):
    def test_docker_cgroup_v1_and_v2(self):
        container = "b" * 64
        for cgroup in (f"0::/system.slice/docker-{container}.scope\n",
                       f"12:memory:/docker/{container}\n"):
            with self.subTest(cgroup=cgroup), patch.object(Path, "read_text", return_value=cgroup):
                self.assertEqual(ports.process_owner(42), ("docker", container))

    def test_systemd_owner(self):
        with patch.object(Path, "read_text", return_value="0::/system.slice/nginx.service\n"):
            self.assertEqual(ports.process_owner(42), ("systemd", "nginx.service"))

    def test_unmanaged_session_and_missing_process(self):
        with patch.object(Path, "read_text", return_value="0::/user.slice/session-42.scope\n"):
            self.assertIsNone(ports.process_owner(42))
        with patch.object(Path, "read_text", side_effect=FileNotFoundError):
            self.assertIsNone(ports.process_owner(42))
            self.assertIsNone(ports.process_identity(42))

    def test_proc_stat_command_may_contain_parentheses(self):
        fields = ["S", "12"] + ["0"] * 17 + ["999"] + ["0"] * 5
        with patch.object(Path, "read_text", return_value="42 (name ) with space) " + " ".join(fields)):
            self.assertEqual(ports.process_identity(42), (12, 999))

    def test_lsof_empty_and_failure_are_distinct(self):
        with patch.object(subprocess, "run", return_value=subprocess.CompletedProcess([], 1, "", "")):
            self.assertEqual(ports.listeners(8000), set())
        with patch.object(subprocess, "run", return_value=subprocess.CompletedProcess([], 1, "", "permission denied")):
            with self.assertRaisesRegex(RuntimeError, "无法检查端口"):
                ports.listeners(8000)

    def test_only_exact_host_port_matches_container(self):
        def output(*args):
            if args[1] == "ps":
                return "one\ntwo"
            return "8080" if args[-1] == "one" else "80\n443"
        with patch.object(ports.shutil, "which", return_value="/usr/bin/docker"), \
                patch.object(ports, "command", side_effect=output):
            self.assertEqual(ports.published_containers(80), {"two"})

    def test_invalid_ports_do_not_stop_anything(self):
        with patch.object(ports, "command") as command:
            for values in ([], [0], [65536], [80, -1]):
                with self.subTest(values=values), self.assertRaises(ValueError):
                    ports.release_ports(values)
            command.assert_not_called()


class StopListenerTests(TestCase):
    def setUp(self):
        self.patches = [
            patch.object(ports, "process_identity", return_value=(1, 999)),
            patch.object(ports, "listeners", return_value={42}),
            patch.object(ports, "process_owner", return_value=None),
            patch.object(ports, "wait_until_released", return_value=True),
            patch.object(ports.os, "kill"),
            patch.object(ports, "command"),
        ]
        self.identity, self.listeners, self.owner, self.wait, self.kill, self.command = [
            self.enterContext(item) for item in self.patches
        ]

    def test_graceful_stop_first(self):
        ports.stop_listener(8000, 42, set())
        self.kill.assert_called_once_with(42, signal.SIGTERM)

    def test_stubborn_listener_is_forced_after_waiting(self):
        self.wait.side_effect = [False, True]
        ports.stop_listener(8000, 42, set())
        self.assertEqual(self.kill.call_args_list, [call(42, signal.SIGTERM), call(42, signal.SIGKILL)])

    def test_reused_pid_is_not_forced(self):
        self.wait.side_effect = [False, True]
        self.identity.side_effect = [(1, 999), (1, 999), (1, 1000)]
        ports.stop_listener(8000, 42, set())
        self.kill.assert_called_once_with(42, signal.SIGTERM)

    def test_disappeared_process_is_ignored(self):
        self.identity.return_value = None
        ports.stop_listener(8000, 42, set())
        self.kill.assert_not_called()

    def test_current_launch_chain_is_protected(self):
        with self.assertRaisesRegex(RuntimeError, "祖先进程"):
            ports.stop_listener(8000, 42, {42})
        self.kill.assert_not_called()

    def test_container_is_stopped_via_docker_not_killed(self):
        self.owner.return_value = ("docker", "b" * 64)
        ports.stop_listener(80, 42, set())
        self.command.assert_called_once_with("docker", "stop", "--time", "10", "b" * 64)
        self.kill.assert_not_called()

    def test_managed_service_is_stopped_via_systemctl(self):
        self.owner.return_value = ("systemd", "nginx.service")
        ports.stop_listener(80, 42, set())
        self.command.assert_called_once_with("systemctl", "stop", "nginx.service")
        self.kill.assert_not_called()

    def test_docker_daemon_and_ssh_are_never_stopped(self):
        for unit in ports.PROTECTED_UNITS:
            self.owner.return_value = ("systemd", unit)
            with self.subTest(unit=unit), self.assertRaisesRegex(RuntimeError, "基础服务"):
                ports.stop_listener(80, 42, set())
        self.command.assert_not_called()
        self.kill.assert_not_called()

    def test_no_longer_listening_is_not_signalled(self):
        self.listeners.return_value = set()
        ports.stop_listener(8000, 42, set())
        self.kill.assert_not_called()


class ReleasePortsTests(TestCase):
    def test_nat_only_mapping_is_stopped_without_listener_pid(self):
        with patch.object(ports.shutil, "which", return_value="available"), \
                patch.object(ports, "protected_pids", return_value={1}), \
                patch.object(ports, "published_containers", return_value={"container"}), \
                patch.object(ports, "listeners", return_value=set()), \
                patch.object(ports, "command") as command:
            ports.release_ports([80])
            command.assert_called_once_with("docker", "stop", "--time", "10", "container")

    def test_respawning_listener_fails_after_bounded_retries(self):
        with patch.object(ports.shutil, "which", return_value="available"), \
                patch.object(ports, "protected_pids", return_value={1}), \
                patch.object(ports, "published_containers", return_value=set()), \
                patch.object(ports, "listeners", return_value={42}), \
                patch.object(ports, "wait_until_released", return_value=True), \
                patch.object(ports, "stop_listener") as stop:
            with self.assertRaisesRegex(RuntimeError, "自动重启"):
                ports.release_ports([80])
            self.assertEqual(stop.call_count, 3)

    def test_real_listener_is_released_and_unrelated_port_survives(self):
        servers = []
        try:
            for _ in range(2):
                server = subprocess.Popen(
                    [sys.executable, "-u", "-c",
                     "from http.server import HTTPServer, SimpleHTTPRequestHandler; "
                     "server = HTTPServer(('127.0.0.1', 0), SimpleHTTPRequestHandler); "
                     "print(server.server_port, flush=True); server.serve_forever()"],
                    stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
                )
                servers.append((server, int(server.stdout.readline())))
            target, port = servers[0]
            unrelated, other_port = servers[1]
            # 此测试明确不访问 Docker，也不接触固定业务端口。
            with patch.object(ports, "published_containers", return_value=set()):
                ports.release_ports([port])
            self.assertEqual(target.wait(timeout=3), -signal.SIGTERM)
            self.assertEqual(ports.listeners(port), set())
            self.assertIsNone(unrelated.poll())
            self.assertIn(unrelated.pid, ports.listeners(other_port))
        finally:
            for server, _ in servers:
                if server.poll() is None:
                    server.terminate()
                server.wait(timeout=3)
                server.stdout.close()

"""按 site.sh 的显式端口接管策略停止监听者，不扩大到无关端口或整个 Docker 服务。"""

import argparse
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import time


PROTECTED_UNITS = {"docker.service", "containerd.service", "ssh.service", "sshd.service"}


def command(*args: str) -> str:
    result = subprocess.run(args, capture_output=True, text=True, timeout=30)
    if result.returncode:
        raise RuntimeError(f"{args[0]} 执行失败：{result.stderr.strip()}")
    return result.stdout.strip()


def listeners(port: int) -> set[int]:
    result = subprocess.run(
        ["lsof", "-nP", "-t", f"-iTCP:{port}", "-sTCP:LISTEN"],
        capture_output=True, text=True, timeout=10,
    )
    # lsof 在没有监听者时返回 1；不能把工具失败或权限错误也当成端口空闲。
    if result.returncode not in (0, 1) or result.stderr.strip():
        raise RuntimeError(f"无法检查端口 {port}：{result.stderr.strip()}")
    return {int(value) for value in result.stdout.split()}


def process_identity(pid: int) -> tuple[int, int] | None:
    """使用内核启动时刻识别进程，避免等待期间 PID 复用后误杀新进程。"""
    try:
        fields = Path(f"/proc/{pid}/stat").read_text().rsplit(") ", 1)[1].split()
    except FileNotFoundError:
        return None
    return int(fields[1]), int(fields[19])


def protected_pids() -> set[int]:
    result = {1}
    pid = os.getpid()
    while pid > 1 and pid not in result:
        result.add(pid)
        identity = process_identity(pid)
        if identity is None:
            break
        pid = identity[0]
    return result


def process_owner(pid: int) -> tuple[str, str] | None:
    try:
        cgroup = Path(f"/proc/{pid}/cgroup").read_text()
    except FileNotFoundError:
        return None
    match = re.search(r"docker[-/]([0-9a-f]{64})(?:\.scope)?(?:/|$)", cgroup, re.M)
    if match:
        return "docker", match[1]
    match = re.search(r"/system\.slice/([^/\n]+\.service)(?:/[^\n]*)?$", cgroup, re.M)
    if match:
        return "systemd", match[1]
    return None


def published_containers(port: int) -> set[str]:
    """兼容 Docker 端口映射；禁用 docker-proxy 时也可能不存在可见监听 PID。"""
    if not shutil.which("docker"):
        return set()
    result = set()
    # 不用 publish 过滤器推断宿主端口：它也可能命中容器内端口，必须核对 HostPort。
    for container in command("docker", "ps", "-q").split():
        bindings = command(
            "docker", "inspect", "--format",
            "{{range .NetworkSettings.Ports}}{{range .}}{{println .HostPort}}{{end}}{{end}}",
            container,
        )
        if str(port) in bindings.split():
            result.add(container)
    return result


def wait_until_released(port: int, pids: set[int], seconds: float = 10) -> bool:
    deadline = time.monotonic() + seconds
    while True:
        if not (listeners(port) & pids):
            return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.1)


def stop_listener(port: int, pid: int, protected: set[int]) -> None:
    identity = process_identity(pid)
    if identity is None or pid not in listeners(port):
        return
    if pid in protected:
        raise RuntimeError(f"端口 {port} 的 PID {pid} 属于当前启动链，拒绝终止自身或祖先进程")
    owner = process_owner(pid)
    if owner is not None:
        kind, name = owner
        if kind == "docker":
            print(f"端口 {port} 被 Docker 容器占用，正在停止容器 {name[:12]}…", flush=True)
            command("docker", "stop", "--time", "10", name)
            return
        if name in PROTECTED_UNITS:
            raise RuntimeError(f"端口 {port} 属于基础服务 {name}，不能为释放单个端口停止整个基础服务")
        print(f"端口 {port} 被系统服务 {name} 占用，正在停止该服务…", flush=True)
        command("systemctl", "stop", name)
        return
    print(f"端口 {port} 被进程 PID {pid} 占用，正在停止…", flush=True)
    if process_identity(pid) != identity:
        return
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    if wait_until_released(port, {pid}):
        return
    # 只升级终止仍在监听同一端口且启动时刻未变化的原进程，不向整个进程组发信号。
    if process_identity(pid) == identity and pid in listeners(port):
        print(f"PID {pid} 未正常释放端口，正在强制停止…", flush=True)
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            return
    if not wait_until_released(port, {pid}, seconds=2):
        raise RuntimeError(f"PID {pid} 仍未释放端口 {port}")


def release_ports(ports: list[int]) -> None:
    if not ports or any(not 1 <= port <= 65535 for port in ports):
        raise ValueError("端口必须在 1–65535 之间")
    if not shutil.which("lsof"):
        raise RuntimeError("缺少 lsof，无法安全识别端口占用者")
    protected = protected_pids()
    for port in dict.fromkeys(ports):
        # 服务由管理器停止而不是只杀子进程；有限复查也覆盖残留 worker 与短暂重启。
        for _ in range(3):
            for container in sorted(published_containers(port)):
                print(f"端口 {port} 被映射容器 {container} 占用，正在停止该容器…", flush=True)
                command("docker", "stop", "--time", "10", container)
            pids = listeners(port)
            if not pids:
                print(f"端口 {port} 已就绪。", flush=True)
                break
            for pid in sorted(pids):
                stop_listener(port, pid, protected)
            if wait_until_released(port, pids, seconds=2):
                # 下一轮重新检查，不能把换了一批 PID 的自动拉起误报为空闲。
                continue
        else:
            if listeners(port) or published_containers(port):
                raise RuntimeError(f"端口 {port} 仍被自动重启的服务占用，请检查其进程管理器")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("ports", metavar="PORT", nargs="+", type=int)
    args = parser.parse_args()
    try:
        release_ports(args.ports)
    except (RuntimeError, ValueError, OSError, subprocess.SubprocessError) as exc:
        print(f"端口接管失败：{exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""为图片下载提供仅作用于当前 opener 的 HTTPS 域名解析覆盖。"""

from __future__ import annotations

from collections.abc import Callable
import http.client
import ipaddress
import re
import socket
from typing import Any
import urllib.request


_HOST_LABEL = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?")


def _validated_resolutions(resolutions: dict[str, str]) -> dict[str, str]:
    normalized: dict[str, str] = {}
    for host, address in resolutions.items():
        if not isinstance(host, str) or not host or host != host.strip():
            raise ValueError("解析覆盖的主机名必须是非空域名，不能包含空白或 URL")
        hostname = host.removesuffix(".")
        if len(hostname) > 253 or not all(
            _HOST_LABEL.fullmatch(label) for label in hostname.split(".")
        ):
            raise ValueError("解析覆盖的主机名必须是域名，不能包含 URL、端口或路径")
        if not isinstance(address, str):
            raise ValueError("解析覆盖的目标必须是 IPv4 或 IPv6 地址字符串")
        try:
            ip = ipaddress.ip_address(address)
        except ValueError as exc:
            raise ValueError("解析覆盖的目标必须是有效 IPv4 或 IPv6 地址") from exc
        # 带接口标识的 IPv6 依赖本地网络接口，不作为可移植的 DNS 查询结果接受。
        if isinstance(ip, ipaddress.IPv6Address) and ip.scope_id is not None:
            raise ValueError("解析覆盖的 IPv6 地址不能包含接口标识")
        hostname = hostname.lower()
        canonical_address = str(ip)
        if hostname in normalized and normalized[hostname] != canonical_address:
            raise ValueError("同一主机名不能配置多个不同的解析覆盖地址")
        normalized[hostname] = canonical_address
    return normalized


class _ResolvedHTTPSHandler(urllib.request.HTTPSHandler):
    def __init__(self, resolutions: dict[str, str]) -> None:
        # 标准 HTTPSHandler 创建的默认上下文保留证书链校验与主机名校验。
        super().__init__()
        self._resolutions = resolutions

    def https_open(self, request: urllib.request.Request) -> Any:
        def connection_factory(host: str, **kwargs: Any) -> http.client.HTTPSConnection:
            connection = http.client.HTTPSConnection(host, **kwargs)
            original_create_connection = connection._create_connection

            def create_connection(
                address: tuple[str, int], *args: Any, **connect_kwargs: Any,
            ) -> socket.socket:
                target_host, port = address
                target_ip = self._resolutions.get(target_host.lower().removesuffix("."))
                return original_create_connection(
                    (target_ip or target_host, port), *args, **connect_kwargs,
                )

            # 只替换本连接的 TCP 目标；原 connect 继续处理隧道、SNI 和证书校验。
            # 使用代理时 address 是代理地址，未配置该地址就沿用代理的解析行为。
            connection._create_connection = create_connection
            return connection

        return self.do_open(connection_factory, request, context=self._context)


def create_resolved_opener(resolutions: dict[str, str]) -> Callable[..., Any]:
    """返回兼容 urllib 的 open(Request, timeout=...)，仅覆盖指定 HTTPS 主机的 TCP 解析。

    输入为域名到真实 DNS IP 的映射；本函数校验格式，不执行或推测 DNS 查询。
    返回值保留标准 urllib 的重定向、代理、Host、TLS SNI 与默认证书验证，
    不修改全局 socket、系统 DNS 或其他 opener。映射在创建时复制并规范化。
    """
    return urllib.request.build_opener(
        _ResolvedHTTPSHandler(_validated_resolutions(resolutions)),
    ).open

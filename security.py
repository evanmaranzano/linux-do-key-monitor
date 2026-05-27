import ipaddress
import socket
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from urllib.parse import urlparse


def is_safe_url(url: str) -> bool:
    """拒绝指向内网/回环地址的 URL。仅允许 http/https 协议。"""
    try:
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            return False
        host = (parsed.hostname or "").strip("[]")
        if not host or host in ("localhost", "127.0.0.1", "0.0.0.0", "::1"):
            return False
        try:
            ip = ipaddress.ip_address(host)
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
                return False
        except ValueError:
            # hostname，非字面 IP — 做 DNS 解析验证
            def _resolve():
                return socket.getaddrinfo(host, None, socket.AF_UNSPEC, socket.SOCK_STREAM)

            try:
                with ThreadPoolExecutor(max_workers=1) as pool:
                    future = pool.submit(_resolve)
                    resolved = future.result(timeout=5)
                for _, _, _, _, sockaddr in resolved:
                    ip = ipaddress.ip_address(sockaddr[0])
                    if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
                        return False
            except (socket.gaierror, OSError, FuturesTimeoutError):
                return False
        return True
    except Exception:
        return False

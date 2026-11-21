"""ОБЩИЙ запуск HTTP-сервера воркера для Salad — слушает `::` с двойным стеком (IPv6 + IPv4).

Зачем: шлюз и пробы Salad ходят к ноде по IPv6; сервер только на 0.0.0.0 им НЕ отвечает → «running, started=false, 503» (урок 724; 18.11 trellis, 19.11 comfy,
21.11 UltraTex — три раза деньги впустую). Воркеры живут в образах одним файлом, поэтому блок между метками ниже КОПИРУЕТСЯ в воркер дословно (`# dualstack:begin … end`),
а `tests_dualstack.py` сверяет копии с этим файлом побайтно и падает на любом `worker*.py`, который слушает только 0.0.0.0 (чинить блок — только здесь, потом копировать).
"""
import socket
from http.server import ThreadingHTTPServer


# dualstack:begin
class _DualStackServer(ThreadingHTTPServer):
    """Слушает `::` и принимает И IPv6, И IPv4: шлюз и пробы Salad ходят по IPv6 — сервер только на 0.0.0.0 им не отвечает («running, started=false, 503», урок 724)."""
    address_family = socket.AF_INET6

    def server_bind(self):
        try:
            self.socket.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 0)
        except (AttributeError, OSError):
            pass
        super().server_bind()


def make_server(port: int, handler, host: str | None = None) -> ThreadingHTTPServer:
    """Двойной стек (`::`), если в системе есть IPv6; иначе обычный 0.0.0.0. `host` — для тестов."""
    if host is not None:
        return (_DualStackServer if ':' in host else ThreadingHTTPServer)((host, port), handler)
    if socket.has_ipv6:
        try:
            return _DualStackServer(('::', port), handler)
        except OSError:                                        # IPv6 в контейнере выключен — откат на IPv4
            pass
    return ThreadingHTTPServer(('0.0.0.0', port), handler)
# dualstack:end

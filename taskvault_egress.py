"""Loopback allowlist proxy for the read-only browser worker.

The proxy accepts HTTPS CONNECT tunnels for explicitly allowlisted hostnames
only. It resolves every target itself and refuses private, loopback, link-local,
reserved, or multicast addresses before opening an upstream socket. Because the
browser is pointed at this proxy, redirects and subresources are revalidated
instead of being trusted from the original source URL.
"""

import ipaddress
import select
import socket
import socketserver
import threading
import urllib.parse


MAX_HEADER_BYTES = 16 * 1024
MAX_BLOCKED_EVENTS = 50
ALLOWED_PORT = 443
HANDSHAKE_TIMEOUT = 10
RELAY_TIMEOUT = 30
BLOCKED_SCHEMES = ("http", "ftp", "file", "data", "javascript")


class EgressBlocked(ValueError):
    pass


def normalize_host(value):
    host = (value or "").strip().rstrip(".").lower()
    if not host or len(host) > 253:
        raise EgressBlocked("The target hostname is invalid.")
    if any(character in host for character in ("/", "\\", "@", " ", "\t", "\r", "\n")):
        raise EgressBlocked("The target hostname is invalid.")
    return host


def normalize_allowlist(hosts):
    normalized = set()
    for host in hosts or []:
        try:
            normalized.add(normalize_host(host))
        except EgressBlocked:
            continue
    if not normalized:
        raise EgressBlocked("At least one allowlisted host is required.")
    return normalized


def host_allowed(host, allowlist):
    try:
        candidate = normalize_host(host)
    except EgressBlocked:
        return False
    for allowed in allowlist:
        if candidate == allowed:
            return True
        if allowed.startswith("www.") and candidate == allowed[4:]:
            return True
        if candidate == "www." + allowed:
            return True
    return False


def resolve_public(host, port=ALLOWED_PORT):
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        address = None
    if address is not None:
        if not address.is_global or address.is_multicast:
            raise EgressBlocked("Private and reserved network addresses are blocked.")
        return [(socket.AF_INET6 if address.version == 6 else socket.AF_INET, str(address))]

    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror as error:
        raise EgressBlocked("The target hostname could not be resolved.") from error
    addresses = []
    for family, _socktype, _proto, _canonname, sockaddr in infos:
        candidate = ipaddress.ip_address(sockaddr[0])
        if not candidate.is_global or candidate.is_multicast:
            raise EgressBlocked("The target resolves to a private or reserved address.")
        addresses.append((family, sockaddr[0]))
    if not addresses:
        raise EgressBlocked("The target hostname did not resolve to a public address.")
    return addresses


def _read_headers(client):
    buffer = b""
    while b"\r\n\r\n" not in buffer:
        chunk = client.recv(4096)
        if not chunk:
            raise EgressBlocked("The browser closed the proxy connection.")
        buffer += chunk
        if len(buffer) > MAX_HEADER_BYTES:
            raise EgressBlocked("The proxy request headers are too large.")
    return buffer.split(b"\r\n", 1)[0].decode("latin-1", errors="replace")


def _parse_connect(line):
    parts = line.split()
    if len(parts) != 3 or parts[0].upper() != "CONNECT" or not parts[2].startswith("HTTP/"):
        raise EgressBlocked("Only HTTPS CONNECT tunnels are allowed.")
    authority = parts[1]
    if authority.startswith("["):
        host, _, remainder = authority[1:].partition("]")
        if not remainder.startswith(":"):
            raise EgressBlocked("The proxy target is malformed.")
        port_text = remainder[1:]
    else:
        try:
            host, port_text = authority.rsplit(":", 1)
        except ValueError as error:
            raise EgressBlocked("The proxy target is malformed.") from error
    try:
        port = int(port_text)
    except ValueError as error:
        raise EgressBlocked("The proxy target port is invalid.") from error
    if port != ALLOWED_PORT:
        raise EgressBlocked("Only HTTPS port 443 is allowed.")
    return normalize_host(host), port


class _ProxyServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


class _ProxyHandler(socketserver.BaseRequestHandler):
    def handle(self):
        client = self.request
        client.settimeout(HANDSHAKE_TIMEOUT)
        allowlist = self.server.allowlist
        try:
            line = _read_headers(client)
            host, port = _parse_connect(line)
            if not host_allowed(host, allowlist):
                raise EgressBlocked("The host is not on this task's allowlist.")
            addresses = resolve_public(host, port)
            upstream = None
            last_error = None
            for family, address in addresses:
                candidate = socket.socket(family, socket.SOCK_STREAM)
                candidate.settimeout(HANDSHAKE_TIMEOUT)
                try:
                    candidate.connect((address, port))
                    upstream = candidate
                    break
                except OSError as error:
                    last_error = error
                    candidate.close()
            if upstream is None:
                raise EgressBlocked("The allowlisted host could not be reached.") from last_error
            client.sendall(b"HTTP/1.1 200 Connection Established\r\n\r\n")
            client.settimeout(RELAY_TIMEOUT)
            upstream.settimeout(RELAY_TIMEOUT)
            self._relay(client, upstream)
        except EgressBlocked as error:
            self.server.record_blocked(host if "host" in locals() else "", str(error))
            try:
                client.sendall(
                    b"HTTP/1.1 403 Forbidden\r\n"
                    b"Content-Type: text/plain; charset=utf-8\r\n"
                    b"Content-Length: 20\r\n"
                    b"Connection: close\r\n\r\n"
                    b"Blocked by policy.\r\n"
                )
            except OSError:
                pass
        except OSError:
            pass
        finally:
            try:
                client.close()
            except OSError:
                pass

    @staticmethod
    def _relay(client, upstream):
        sockets = [client, upstream]
        try:
            while True:
                readable, _, _ = select.select(sockets, [], [], RELAY_TIMEOUT)
                if not readable:
                    return
                for source in readable:
                    data = source.recv(65536)
                    if not data:
                        return
                    destination = upstream if source is client else client
                    destination.sendall(data)
        finally:
            upstream.close()


class EgressProxy:
    def __init__(self, allowlist):
        self.allowlist = normalize_allowlist(allowlist)
        self.server = _ProxyServer(("127.0.0.1", 0), _ProxyHandler)
        self.server.allowlist = self.allowlist
        self.server.blocked = []
        self.server.record_blocked = self._record_blocked
        self._lock = threading.Lock()
        self._thread = None

    def _record_blocked(self, host, reason):
        with self._lock:
            if len(self.server.blocked) < MAX_BLOCKED_EVENTS:
                self.server.blocked.append({"host": host, "reason": reason})

    @property
    def port(self):
        return self.server.server_address[1]

    @property
    def url(self):
        return "http://127.0.0.1:{}".format(self.port)

    @property
    def blocked(self):
        with self._lock:
            return list(self.server.blocked)

    def __enter__(self):
        self._thread = threading.Thread(
            target=self.server.serve_forever,
            kwargs={"poll_interval": 0.05},
            name="taskvault-egress-proxy",
            daemon=True,
        )
        self._thread.start()
        return self

    def __exit__(self, exc_type, exc, traceback):
        self.server.shutdown()
        self.server.server_close()
        if self._thread:
            self._thread.join(timeout=2)
        return False

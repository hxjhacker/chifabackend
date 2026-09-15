"""Accept HTTP, TLS, or PROXY protocol on :8000 and forward HTTP/1.1 to uvicorn."""

from __future__ import annotations

import asyncio
import socket
import ssl
import subprocess
import sys
import tempfile
from pathlib import Path

import uvicorn

INNER_HOST = "127.0.0.1"
INNER_PORT = 8001
OUTER_HOST = "0.0.0.0"
OUTER_PORT = 8000
PROXY_V2_SIG = b"\r\n\r\n\x00\r\nQUIT\n"


def _make_tls_context() -> ssl.SSLContext | None:
    tmp = Path(tempfile.gettempdir())
    cert = tmp / "chifaglow-gate.crt"
    key = tmp / "chifaglow-gate.key"
    try:
        subprocess.run(
            [
                "openssl",
                "req",
                "-x509",
                "-newkey",
                "rsa:2048",
                "-sha256",
                "-keyout",
                str(key),
                "-out",
                str(cert),
                "-days",
                "3650",
                "-nodes",
                "-subj",
                "/CN=api.chifaglow.com",
                "-addext",
                "subjectAltName=DNS:api.chifaglow.com,DNS:localhost,DNS:*.chifaglow.com,IP:127.0.0.1",
            ],
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        print(f"[GATE] openssl cert skipped: {exc}", flush=True)
        return None
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    ctx.load_cert_chain(str(cert), str(key))
    print("[GATE] TLS context verify_mode=CERT_NONE check_hostname=False", flush=True)
    return ctx


def _peek(sock: socket.socket, n: int = 256) -> bytes:
    sock.settimeout(15)
    return sock.recv(n, socket.MSG_PEEK)


def _consume(sock: socket.socket, n: int) -> bytes:
    buf = b""
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            break
        buf += chunk
    return buf


def _strip_proxy(sock: socket.socket) -> None:
    peek = _peek(sock, 256)
    if not peek:
        return
    if peek.startswith(b"PROXY "):
        idx = peek.find(b"\r\n")
        if idx == -1:
            _consume(sock, len(peek))
            return
        _consume(sock, idx + 2)
        print("[GATE] stripped PROXY v1", flush=True)
        _strip_proxy(sock)
        return
    if peek.startswith(PROXY_V2_SIG) or peek[:12] == PROXY_V2_SIG:
        header = peek if len(peek) >= 16 else _peek(sock, 16)
        length = int.from_bytes(header[14:16], "big")
        _consume(sock, 16 + length)
        print("[GATE] stripped PROXY v2", flush=True)
        _strip_proxy(sock)


async def _pipe(src: asyncio.StreamReader, dst: asyncio.StreamWriter) -> None:
    try:
        while True:
            data = await src.read(65536)
            if not data:
                break
            dst.write(data)
            await dst.drain()
    except (ConnectionError, asyncio.CancelledError, ssl.SSLError, OSError):
        pass
    finally:
        try:
            if not dst.is_closing():
                dst.close()
            await dst.wait_closed()
        except Exception:
            pass


async def _streams(sock: socket.socket, tls_ctx: ssl.SSLContext | None = None):
    loop = asyncio.get_running_loop()
    reader = asyncio.StreamReader(loop=loop)
    protocol = asyncio.StreamReaderProtocol(reader, loop=loop)
    transport, _ = await loop.connect_accepted_socket(
        lambda: protocol,
        sock,
        ssl=tls_ctx,
    )
    writer = asyncio.StreamWriter(transport, protocol, reader, loop)
    return reader, writer


_GATE_SESSIONS: set[asyncio.Task] = set()


async def _session(client: socket.socket, tls_ctx: ssl.SSLContext | None) -> None:
    loop = asyncio.get_running_loop()
    writer = None
    inner_w = None
    try:
        await loop.run_in_executor(None, _strip_proxy, client)
        peek = await loop.run_in_executor(None, lambda: _peek(client, 16))
        if not peek:
            return
        is_tls = peek[:1] == b"\x16"
        if peek.startswith(b"PRI "):
            print("[GATE] HTTP/2 preface — disable HTTP/2 to origin in Cloudflare/Easypanel", flush=True)
            return
        if is_tls:
            print("[GATE] TLS ClientHello — terminating locally", flush=True)
            if tls_ctx is None:
                print("[GATE] no TLS cert; set Easypanel domain scheme to HTTP", flush=True)
                return
        else:
            method = peek.split(b" ", 1)[0].decode("ascii", "replace")
            print(f"[GATE] HTTP {method}", flush=True)

        client.setblocking(False)
        reader, writer = await _streams(client, tls_ctx if is_tls else None)
        inner_r, inner_w = await asyncio.open_connection(INNER_HOST, INNER_PORT)
        await asyncio.gather(_pipe(reader, inner_w), _pipe(inner_r, writer), return_exceptions=True)
    except asyncio.CancelledError:
        print("[GATE] session cancelled", flush=True)
        raise
    except Exception as exc:
        print(f"[GATE] session error: {type(exc).__name__}: {exc}", flush=True)
    finally:
        for stream in (inner_w, writer):
            if stream is None:
                continue
            try:
                if not stream.is_closing():
                    stream.close()
                await stream.wait_closed()
            except Exception:
                pass
        try:
            client.close()
        except Exception:
            pass


def _forget_gate_session(task: asyncio.Task) -> None:
    _GATE_SESSIONS.discard(task)
    try:
        exc = task.exception()
    except (asyncio.CancelledError, asyncio.InvalidStateError):
        return
    if exc:
        print(f"[GATE] session task failed: {type(exc).__name__}: {exc}", flush=True)


async def _accept(tls_ctx: ssl.SSLContext | None) -> None:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind((OUTER_HOST, OUTER_PORT))
    sock.listen(128)
    sock.setblocking(False)
    loop = asyncio.get_running_loop()
    print(f"[GATE] listening on {OUTER_HOST}:{OUTER_PORT} -> {INNER_HOST}:{INNER_PORT}", flush=True)
    try:
        while True:
            client, addr = await loop.sock_accept(sock)
            print(f"[GATE] accept {addr[0]}:{addr[1]}", flush=True)
            task = asyncio.create_task(_session(client, tls_ctx), name=f"gate-{addr[0]}-{addr[1]}")
            _GATE_SESSIONS.add(task)
            task.add_done_callback(_forget_gate_session)
    finally:
        pending = list(_GATE_SESSIONS)
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        try:
            sock.close()
        except Exception:
            pass


async def _wait_inner() -> None:
    for _ in range(100):
        try:
            _, w = await asyncio.open_connection(INNER_HOST, INNER_PORT)
            w.close()
            await w.wait_closed()
            return
        except OSError:
            await asyncio.sleep(0.1)
    raise RuntimeError("uvicorn did not start on inner port")


async def _amain() -> None:
    tls_ctx = _make_tls_context()
    config = uvicorn.Config(
        "app.main:app",
        host=INNER_HOST,
        port=INNER_PORT,
        http="h11",
        proxy_headers=True,
        forwarded_allow_ips="*",
        access_log=True,
        log_level="info",
        timeout_keep_alive=30,
        server_header=True,
    )
    server = uvicorn.Server(config)
    uv_task = asyncio.create_task(server.serve())
    await _wait_inner()
    gate_task = asyncio.create_task(_accept(tls_ctx))
    done, pending = await asyncio.wait({uv_task, gate_task}, return_when=asyncio.FIRST_COMPLETED)
    for task in pending:
        task.cancel()
    for task in done:
        exc = task.exception()
        if exc:
            raise exc


def main() -> None:
    try:
        asyncio.run(_amain())
    except KeyboardInterrupt:
        sys.exit(0)


if __name__ == "__main__":
    main()

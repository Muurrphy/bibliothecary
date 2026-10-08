"""A local HTTPS certificate, because browsers only give a web page the microphone over HTTPS.

The e-reader keeps using plain HTTP. The tablet that listens opens the HTTPS port.
The certificate is made once with the ``openssl`` command (built into macOS and most
Linux systems) and signed by a small certificate authority of your own, kept in
``~/.margin/tls``. The browser will warn the first time; you can either continue
anyway, or install ``/margin-ca.crt`` on the tablet so it trusts the page for good.
"""

from __future__ import annotations

import shutil
import socket
import subprocess
from pathlib import Path

HOME = Path.home() / ".margin" / "tls"


def _run(*args: str) -> None:
    subprocess.run(["openssl", *args], check=True, capture_output=True, timeout=60)


def local_hostname() -> str:
    """The name the computer answers to on the local network (``<name>.local``), if known.

    Addresses from the router can change; the .local name does not, so a tablet that keeps
    the page on its home screen should use it."""
    if shutil.which("scutil"):   # macOS
        out = subprocess.run(["scutil", "--get", "LocalHostName"], capture_output=True, text=True, check=False)
        if out.returncode == 0 and out.stdout.strip():
            return out.stdout.strip()
    return ""


def ensure_certificate(ip: str, host: str = "", directory: Path = HOME) -> tuple[Path, Path, Path] | None:
    """(certificate chain, key, CA certificate) for ``ip`` and ``host``.local; None without openssl."""
    if not shutil.which("openssl"):
        return None
    directory.mkdir(parents=True, exist_ok=True)
    ca_key, ca_crt = directory / "ca.key", directory / "margin-ca.crt"
    key, crt, chain = directory / "server.key", directory / "server.crt", directory / "server-chain.crt"
    stamp = directory / "server.ip"
    if not (ca_key.exists() and ca_crt.exists()):
        cnf = directory / "ca.cnf"
        cnf.write_text(
            "[req]\ndistinguished_name=dn\nprompt=no\nx509_extensions=ext\n"
            "[dn]\nCN=Margin local CA\nO=Margin\n"
            "[ext]\nbasicConstraints=critical,CA:TRUE\nkeyUsage=critical,keyCertSign,cRLSign\n"
            "subjectKeyIdentifier=hash\n")
        _run("req", "-x509", "-newkey", "rsa:2048", "-nodes", "-sha256", "-days", "3650",
             "-keyout", str(ca_key), "-out", str(ca_crt), "-config", str(cnf))
        stamp.unlink(missing_ok=True)
    host = host or socket.gethostname().split(".")[0] or "margin"
    want = f"{ip} {host}"
    if not (key.exists() and chain.exists() and stamp.exists() and stamp.read_text() == want):
        ext = directory / "server.cnf"
        ext.write_text(
            "[req]\ndistinguished_name=dn\nprompt=no\n[dn]\nCN=" + ip + "\n"
            "[ext]\nbasicConstraints=CA:FALSE\nkeyUsage=critical,digitalSignature,keyEncipherment\n"
            "extendedKeyUsage=serverAuth\nsubjectAltName=IP:" + ip + ",IP:127.0.0.1,DNS:localhost,DNS:" + host + ".local\n")
        csr = directory / "server.csr"
        _run("req", "-newkey", "rsa:2048", "-nodes", "-sha256", "-keyout", str(key), "-out", str(csr), "-config", str(ext))
        _run("x509", "-req", "-in", str(csr), "-CA", str(ca_crt), "-CAkey", str(ca_key), "-CAcreateserial",
             "-days", "397", "-sha256", "-extfile", str(ext), "-extensions", "ext", "-out", str(crt))
        chain.write_bytes(crt.read_bytes() + ca_crt.read_bytes())
        stamp.write_text(want)
        key.chmod(0o600)
        ca_key.chmod(0o600)
    return chain, key, ca_crt

"""Base research collector with SSRF defense and untrusted content sanitization (IP-6)."""

from __future__ import annotations

import hashlib
import http.client
import ipaddress
import logging
import os
import re
import socket
from typing import Dict, Optional, Set
import urllib.error
import urllib.parse
import urllib.request

logger = logging.getLogger(__name__)

# Strictly whitelisted domain suffixes for automated research collection
ALLOWED_DOMAIN_SUFFIXES: Set[str] = {
    "ishares.com",
    "blackrock.com",
    "ssga.com",
    "statestreet.com",
    "vanguard.com",
    "sec.gov",
    "ecb.europa.eu",
    "europa.eu",
    "data.ecb.europa.eu",
    "data-api.ecb.europa.eu",
    "finance.yahoo.com",
    "yahoo.com",
    "boerse-frankfurt.de",
    "deutsche-boerse.com",
    "msci.com",
    "spglobal.com",
}


class SSRFSecurityError(ValueError):
    """Raised when an unwhitelisted or private/loopback destination is requested."""


def is_ip_prohibited(ip: str | ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """Check whether IP belongs to private, loopback, link-local, multicast, or reserved ranges."""
    if isinstance(ip, str):
        try:
            ip = ipaddress.ip_address(ip)
        except ValueError:
            return True
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        return is_ip_prohibited(ip.ipv4_mapped)
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )


def validate_research_url(url: str, resolve_dns: bool = True) -> str:
    """Validate URL against SSRF boundaries, permitted public domain whitelist, and DNS resolution."""
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https":
        raise SSRFSecurityError(f"Yalnızca HTTPS şemasına izin verilir; güvensiz şema engellendi: {parsed.scheme}")

    hostname = (parsed.hostname or "").lower().strip()
    if not hostname:
        raise SSRFSecurityError("URL ana makine adı (hostname) içeremedi.")

    # 1. Direct IP literal checks
    try:
        ip = ipaddress.ip_address(hostname)
        if is_ip_prohibited(ip):
            raise SSRFSecurityError(f"Yerel / özel IP adreslerine erişim engellendi: {hostname}")
        # Direct IP connections without whitelisted domain are strictly prohibited
        raise SSRFSecurityError(f"Doğrudan IP adresiyle erişim yasaktır; alan adı kullanılmalıdır: {hostname}")
    except ValueError:
        pass  # Hostname is a domain name

    if hostname in ("localhost", "127.0.0.1", "::1", "0.0.0.0"):
        raise SSRFSecurityError(f"Yerel makineye erişim engellendi: {hostname}")

    # 2. Port restrictions: only standard HTTPS port (443) permitted
    port = parsed.port or 443
    if port != 443:
        raise SSRFSecurityError(f"Yalnızca standart HTTPS portuna (443) izin verilir: {port}")

    # 3. Domain whitelist verification
    domain_allowed = any(
        hostname == allowed or hostname.endswith("." + allowed)
        for allowed in ALLOWED_DOMAIN_SUFFIXES
    )
    if not domain_allowed:
        raise SSRFSecurityError(
            f"Erişilmek istenen alan adı ('{hostname}') araştırma beyaz listesinde bulunamadı."
        )

    # 4. Pre-connection DNS check (Defense against DNS Rebinding & Split-Horizon DNS)
    if resolve_dns:
        try:
            addr_info = socket.getaddrinfo(hostname, port, type=socket.SOCK_STREAM)
            for item in addr_info:
                sockaddr = item[4]
                ip_str = sockaddr[0]
                resolved_ip = ipaddress.ip_address(ip_str)
                if is_ip_prohibited(resolved_ip):
                    raise SSRFSecurityError(
                        f"DNS Rebinding / Özel IP tespiti: '{hostname}' çözümlendiğinde özel/yerel IP üretti ({ip_str})."
                    )
        except socket.gaierror as e:
            raise SSRFSecurityError(f"DNS çözümleme hatası ('{hostname}'): {e}") from e

    return url


class NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Custom HTTPRedirectHandler that stops automatic uninspected redirects."""
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class SecureHttpFetcher:
    """SSRF-hardened HTTP client enforcing domain whitelist, DNS checks, and safe redirects."""

    def __init__(self, offline: Optional[bool] = None) -> None:
        self.offline = offline if offline is not None else (os.environ.get("MASA_OFFLINE") == "1")

    def fetch(
        self,
        url: str,
        headers: Optional[Dict[str, str]] = None,
        timeout: float = 10.0,
        max_size: int = 10 * 1024 * 1024,  # 10 MB limit
        max_redirects: int = 3,
    ) -> bytes:
        """Fetch URL with strict SSRF defense, DNS pre-checks, and safe manual redirect following."""
        if self.offline:
            raise RuntimeError("Ağ erişimi çevrimdışı (MASA_OFFLINE=1) modunda engellendi.")

        current_url = url
        req_headers = {
            "User-Agent": "Mozilla/5.0 (compatible; MasaResearch/1.0; +https://github.com/Akifulutas/FinanceCockpit)",
            "Accept": "text/html,application/xhtml+xml,application/json,text/plain;q=0.9,*/*;q=0.8",
        }
        if headers:
            req_headers.update(headers)

        opener = urllib.request.build_opener(NoRedirectHandler)

        for hop in range(max_redirects + 1):
            valid_url = validate_research_url(current_url, resolve_dns=True)
            req = urllib.request.Request(valid_url, headers=req_headers)

            try:
                with opener.open(req, timeout=timeout) as resp:
                    status = resp.status
                    if status in (301, 302, 303, 307, 308):
                        if hop >= max_redirects:
                            raise SSRFSecurityError(f"Maksimum yönlendirme sınırı ({max_redirects}) aşıldı.")
                        location = resp.headers.get("Location")
                        if not location:
                            raise SSRFSecurityError("Yönlendirme yanıtında Location başlığı bulunamadı.")
                        current_url = urllib.parse.urljoin(current_url, location)
                        continue

                    # Read body with size guard
                    body = resp.read(max_size + 1)
                    if len(body) > max_size:
                        raise ValueError(f"Yanıt boyutu izin verilen sınırı ({max_size} bayt) aştı.")
                    return body
            except urllib.error.HTTPError as exc:
                if exc.code in (301, 302, 303, 307, 308):
                    if hop >= max_redirects:
                        raise SSRFSecurityError(f"Maksimum yönlendirme sınırı ({max_redirects}) aşıldı.")
                    location = exc.headers.get("Location")
                    if not location:
                        raise SSRFSecurityError("Yönlendirme yanıtında Location başlığı bulunamadı.")
                    current_url = urllib.parse.urljoin(current_url, location)
                    continue
                raise

        raise SSRFSecurityError(f"Maksimum yönlendirme sayısı ({max_redirects}) aşıldı.")


def sanitize_extracted_text(text: str) -> str:
    """Sanitize extracted document text; defense against hidden injection tags."""
    if not text:
        return ""
    # Strip HTML tags
    clean = re.sub(r"<[^>]+>", " ", text)
    # Remove control characters except standard whitespace
    clean = "".join(ch for ch in clean if ch.isprintable() or ch in "\n\r\t")
    # Normalize multiple whitespace
    clean = re.sub(r"[ \t]+", " ", clean)
    clean = re.sub(r"\n{3,}", "\n\n", clean)
    return clean.strip()


def wrap_untrusted_source(
    source_id: str,
    source_type: str,
    publisher: str,
    content: str,
) -> str:
    """Enclose extracted web/filing text inside strict <untrusted_source_document> tags."""
    sanitized = sanitize_extracted_text(content)
    # Defense against CDATA escaping tricks
    sanitized = sanitized.replace("]]>", "]] >")
    return (
        f'<untrusted_source_document id="{source_id}" type="{source_type}" publisher="{publisher}">\n'
        f'<![CDATA[\n'
        f'{sanitized}\n'
        f']]>\n'
        f'</untrusted_source_document>'
    )


def compute_content_sha256(content: str | bytes) -> str:
    """Compute standard SHA-256 hex digest for document payload."""
    if isinstance(content, str):
        content = content.encode("utf-8")
    return hashlib.sha256(content).hexdigest()

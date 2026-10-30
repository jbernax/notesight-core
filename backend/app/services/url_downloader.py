import ipaddress
import logging
from pathlib import Path
import re
import socket
from urllib.parse import urlparse
import httpx
from fastapi import HTTPException, status
from app.config import settings
from app.api.helpers import save_upload_file_safely

logger = logging.getLogger(__name__)

# Strict list of blocked private / reserved / loopback IP networks to prevent SSRF
BLOCKED_IP_NETWORKS = [
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("169.254.0.0/16"),  # Link-local & cloud instance metadata (AWS/GCP/Azure)
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("100.64.0.0/10"),  # Carrier-grade NAT
    ipaddress.ip_network("198.18.0.0/15"),  # Benchmarking
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),        # IPv6 Unique Local
    ipaddress.ip_network("fe80::/10"),       # IPv6 Link-Local
]


def validate_safe_target_url(target_url: str) -> str:
    """
    Validate target URL structure and ensure target does not resolve to private or loopback networks.
    Raises HTTPException(400) or HTTPException(403) on SSRF attempts.
    """
    if not target_url or not isinstance(target_url, str):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="URL is required.",
        )

    clean_url = target_url.strip()
    parsed = urlparse(clean_url)

    if parsed.scheme.lower() not in ("http", "https"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only HTTP and HTTPS URLs are supported for score import.",
        )

    hostname = parsed.hostname
    if not hostname:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid URL: missing hostname.",
        )

    # Disallow known localhost aliases
    if hostname.lower() in ("localhost", "127.0.0.1", "0.0.0.0", "::1", "metadata.google.internal"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access to private or local network resources is strictly prohibited.",
        )

    # Resolve IP addresses and verify none are in private or internal subnets
    try:
        addr_infos = socket.getaddrinfo(hostname, None)
    except socket.gaierror as e:
        logger.warning(f"Failed to resolve URL hostname {hostname}: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Could not resolve hostname '{hostname}'. Please check the URL.",
        )

    for _, _, _, _, sockaddr in addr_infos:
        ip_str = sockaddr[0]
        try:
            ip_obj = ipaddress.ip_address(ip_str)
            if (
                ip_obj.is_private
                or ip_obj.is_loopback
                or ip_obj.is_link_local
                or ip_obj.is_multicast
                or ip_obj.is_reserved
                or any(ip_obj in net for net in BLOCKED_IP_NETWORKS)
            ):
                logger.warning(f"SSRF attempt blocked for target {clean_url} resolving to private IP {ip_str}")
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Access to private or restricted network addresses is strictly prohibited.",
                )
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid IP address resolved: {ip_str}",
            )

    return clean_url


def infer_filename_from_url(url: str, content_disposition: str | None = None) -> str:
    """Infer a safe filename from Content-Disposition header or the URL path."""
    if content_disposition:
        match = re.search(r'filename\*?=(?:UTF-8\'\')?["\']?([^";\r\n]+)["\']?', content_disposition, re.IGNORECASE)
        if match:
            candidate = Path(match.group(1).strip().strip('"\'')).name
            if candidate and "." in candidate:
                return candidate

    parsed = urlparse(url)
    path_name = Path(parsed.path).name
    if path_name and "." in path_name:
        return path_name

    return "imported_score.pdf"


async def download_file_from_url(target_url: str, destination_dir: Path) -> tuple[Path, str, int]:
    """
    Safely download a score file from a verified public URL into destination_dir.
    Returns (saved_path, inferred_filename, file_size_bytes).
    """
    safe_url = validate_safe_target_url(target_url)

    destination_dir.mkdir(parents=True, exist_ok=True)
    temp_path = destination_dir / f"download_staging_{Path(urlparse(safe_url).path).name or 'score'}.tmp"

    total_bytes = 0
    max_bytes = settings.MAX_UPLOAD_SIZE_BYTES

    headers = {
        "User-Agent": "NoteSight-OMR/1.0 (score import)",
        "Accept": "application/pdf,image/png,image/jpeg,image/tiff,image/bmp,*/*",
    }

    try:
        async with httpx.AsyncClient(timeout=20.0, follow_redirects=False) as client:
            # We explicitly do not auto-follow redirects blindly to prevent open-redirect SSRF
            req_url = safe_url
            max_redirects = 3
            redirect_count = 0

            while redirect_count < max_redirects:
                async with client.stream("GET", req_url, headers=headers) as resp:
                    if resp.status_code in (301, 302, 303, 307, 308):
                        redirect_location = resp.headers.get("location")
                        if not redirect_location:
                            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid redirect from remote server.")
                        # Validate the redirected URL against SSRF policy!
                        req_url = validate_safe_target_url(str(httpx.URL(req_url).join(redirect_location)))
                        redirect_count += 1
                        continue

                    if resp.status_code >= 400:
                        raise HTTPException(
                            status_code=status.HTTP_400_BAD_REQUEST,
                            detail=f"Failed to fetch file: remote server returned HTTP {resp.status_code}.",
                        )

                    inferred_name = infer_filename_from_url(req_url, resp.headers.get("content-disposition"))
                    ext = Path(inferred_name).suffix.lower()
                    if ext not in settings.ALLOWED_EXTENSIONS:
                        # Fallback: check content-type
                        ctype = resp.headers.get("content-type", "").lower()
                        if "pdf" in ctype:
                            inferred_name = Path(inferred_name).stem + ".pdf"
                        elif "png" in ctype:
                            inferred_name = Path(inferred_name).stem + ".png"
                        elif "jpeg" in ctype or "jpg" in ctype:
                            inferred_name = Path(inferred_name).stem + ".jpg"
                        else:
                            raise HTTPException(
                                status_code=status.HTTP_400_BAD_REQUEST,
                                detail=f"Unsupported format '{ext or ctype}'. NoteSight supports PDF, PNG, JPG, TIFF, and BMP.",
                            )

                    with open(temp_path, "wb") as f:
                        async for chunk in resp.aiter_bytes(chunk_size=65536):
                            total_bytes += len(chunk)
                            if total_bytes > max_bytes:
                                f.close()
                                if temp_path.exists():
                                    temp_path.unlink()
                                raise HTTPException(
                                    status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                                    detail=f"The remote score exceeds NoteSight's size limit of {max_bytes // (1024 * 1024)} MB.",
                                )
                            f.write(chunk)

                    break

            if redirect_count >= max_redirects:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Too many redirects encountered while fetching score URL.",
                )

    except HTTPException:
        if temp_path.exists():
            temp_path.unlink()
        raise
    except httpx.TimeoutException:
        if temp_path.exists():
            temp_path.unlink()
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail="Connection timed out while downloading the score from the provided URL.",
        )
    except Exception as e:
        if temp_path.exists():
            temp_path.unlink()
        logger.error(f"Unexpected error downloading score from URL: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Could not download file from URL: {str(e)}",
        )

    if total_bytes == 0:
        if temp_path.exists():
            temp_path.unlink()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="The downloaded score file was empty (0 bytes).",
        )

    return temp_path, inferred_name, total_bytes

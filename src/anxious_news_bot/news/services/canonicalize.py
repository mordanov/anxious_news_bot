from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import (
    parse_qsl,
    quote,
    urlencode,
    urljoin,
    urlsplit,
    urlunsplit,
)

_UNRESERVED = frozenset(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~"
)
_PERCENT_ESCAPE = re.compile(r"%[0-9A-Fa-f]{2}")
_INVALID_PERCENT = re.compile(r"%(?![0-9A-Fa-f]{2})")


class InvalidURL(ValueError):
    pass


def _normalize_percent_encoding(value: str) -> str:
    def replace(match: re.Match[str]) -> str:
        byte = bytes.fromhex(match.group()[1:])
        try:
            character = byte.decode("ascii")
        except UnicodeDecodeError:
            return match.group().upper()
        return character if character in _UNRESERVED else match.group().upper()

    return _INVALID_PERCENT.sub("%25", _PERCENT_ESCAPE.sub(replace, value))


def _normalize_path(path: str) -> str:
    decoded = _normalize_percent_encoding(path or "/")
    output: list[str] = []
    for segment in decoded.split("/"):
        if segment == ".":
            continue
        if segment == "..":
            if output and output[-1] not in {"", ".."}:
                output.pop()
            continue
        output.append(segment)
    normalized = "/".join(output)
    if decoded.startswith("/") and not normalized.startswith("/"):
        normalized = f"/{normalized}"
    if not normalized:
        normalized = "/"
    if decoded.endswith(("/.", "/..")) and not normalized.endswith("/"):
        normalized += "/"
    return quote(normalized, safe="/:@!$&'()*+,;=-._~%")


@dataclass(frozen=True, slots=True)
class CanonicalURLPolicy:
    version: str = "1.0"
    tracking_parameters: tuple[str, ...] = (
        "fbclid",
        "gclid",
        "mc_cid",
        "mc_eid",
        "utm_campaign",
        "utm_content",
        "utm_medium",
        "utm_source",
        "utm_term",
    )

    def canonicalize(self, value: str, *, base_url: str | None = None) -> str:
        candidate = urljoin(base_url, value.strip()) if base_url else value.strip()
        if not candidate:
            raise InvalidURL("URL is empty")
        if any(ord(character) < 32 for character in candidate):
            raise InvalidURL("URL contains control characters")
        try:
            parsed = urlsplit(candidate)
            port = parsed.port
        except ValueError as exc:
            raise InvalidURL("URL is malformed") from exc
        scheme = parsed.scheme.lower()
        if scheme not in {"http", "https"}:
            raise InvalidURL("URL scheme must be HTTP or HTTPS")
        if not parsed.hostname:
            raise InvalidURL("URL host is required")
        if parsed.username is not None or parsed.password is not None:
            raise InvalidURL("URL credentials are not allowed")
        try:
            host = parsed.hostname.rstrip(".").encode("idna").decode("ascii").lower()
        except UnicodeError as exc:
            raise InvalidURL("URL host is invalid") from exc
        if not host or any(character.isspace() for character in host):
            raise InvalidURL("URL host is invalid")
        if ":" in host and not host.startswith("["):
            host = f"[{host}]"
        default_port = (scheme == "http" and port == 80) or (
            scheme == "https" and port == 443
        )
        netloc = host if port is None or default_port else f"{host}:{port}"
        tracking = {name.casefold() for name in self.tracking_parameters}
        query_pairs = [
            (key, item)
            for key, item in parse_qsl(parsed.query, keep_blank_values=True)
            if key.casefold() not in tracking
        ]
        query_pairs.sort(key=lambda pair: (pair[0], pair[1]))
        query = urlencode(query_pairs, doseq=True, quote_via=quote, safe="~")
        return urlunsplit((scheme, netloc, _normalize_path(parsed.path), query, ""))


def canonicalize_url(
    value: str,
    *,
    base_url: str | None = None,
    version: str = "1.0",
    tracking_parameters: tuple[str, ...] | None = None,
) -> str:
    policy = CanonicalURLPolicy(
        version=version,
        tracking_parameters=tracking_parameters
        if tracking_parameters is not None
        else CanonicalURLPolicy().tracking_parameters,
    )
    return policy.canonicalize(value, base_url=base_url)

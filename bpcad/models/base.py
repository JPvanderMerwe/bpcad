"""
The Backend protocol, and the local-only enforcement behind it.

WHY THIS MODULE EXISTS
----------------------
"No cloud inference" is worth nothing as a policy and everything as a property
of the code. Every backend calls assert_local_endpoint() at CONSTRUCTION time,
so a misconfigured host fails immediately and loudly with the offending URL in
the message, rather than quietly shipping a prompt off the machine.

There are exactly two backends in this project: ollama and null. Do not add an
OpenAI-compatible backend, an API-key config field, or a hosted-provider option.

A NOTE ON DNS
-------------
The check is LITERAL. It reads the host out of the URL and tests that text; it
never resolves a name. Two reasons, and both matter:

  * bpcad must work with the network cable out. A DNS lookup at construction
    would either hang or fail on an offline machine.
  * A literal check is strictly more conservative than a resolving one. A name
    that happens to resolve to 127.0.0.1 today could resolve elsewhere
    tomorrow, and a resolving check would let it through both times. This one
    refuses anything that is not plainly a loopback literal or an explicitly
    whitelisted host, so the failure mode is a false refusal, never a false
    allow.
"""

from __future__ import annotations

import ipaddress
from typing import Iterable, Protocol, runtime_checkable
from urllib.parse import urlsplit


class NonLocalEndpointError(RuntimeError):
    """
    Raised when a model endpoint is anything but a permitted local host.

    The offending URL is always in the message. That is deliberate: when this
    fires you want to see immediately which config value did it.
    """


# "localhost" is permitted by name because the brief names it explicitly.
LOOPBACK_NAMES = frozenset({"localhost"})

# Anything else is a hosted endpoint by another name.
ALLOWED_SCHEMES = frozenset({"http", "https"})


def _normalise_allowed(allowed_hosts: Iterable[str] | None) -> frozenset[str]:
    """Whitelisted hosts from config, lowercased, blanks dropped."""
    if not allowed_hosts:
        return frozenset()
    return frozenset(
        h.strip().lower() for h in allowed_hosts if h and h.strip()
    )


def host_of(url: str) -> str:
    """
    Pull the hostname out of a URL, or raise NonLocalEndpointError explaining
    why the URL is unusable. Never resolves anything.
    """
    if not isinstance(url, str) or not url.strip():
        raise NonLocalEndpointError(
            "model endpoint refused: the host is empty. "
            "Set a loopback URL such as http://127.0.0.1:11434"
        )

    try:
        parts = urlsplit(url.strip())
    except ValueError as exc:                      # malformed IPv6 literal, etc.
        raise NonLocalEndpointError(
            "model endpoint refused: %r could not be parsed as a URL (%s)"
            % (url, exc)
        ) from exc

    scheme = parts.scheme.lower()
    if scheme not in ALLOWED_SCHEMES:
        raise NonLocalEndpointError(
            "model endpoint refused: %r has scheme %r. "
            "Only %s are understood, and only on a loopback host."
            % (url, parts.scheme, " and ".join(sorted(ALLOWED_SCHEMES)))
        )

    try:
        host = parts.hostname
    except ValueError as exc:
        raise NonLocalEndpointError(
            "model endpoint refused: %r has an unreadable host (%s)" % (url, exc)
        ) from exc

    if not host:
        raise NonLocalEndpointError(
            "model endpoint refused: %r carries no host. "
            "Set a loopback URL such as http://127.0.0.1:11434" % url
        )
    return host.lower()


def is_local_host(host: str, allowed_hosts: Iterable[str] | None = None) -> bool:
    """
    True if `host` is a loopback literal, the name "localhost", or a host the
    config explicitly whitelists. No DNS, no network, no exceptions raised.
    """
    h = (host or "").strip().lower()
    if not h:
        return False
    if h in _normalise_allowed(allowed_hosts):
        return True
    if h in LOOPBACK_NAMES:
        return True
    try:
        # Covers the whole of 127.0.0.0/8 and ::1, which is what loopback means.
        return ipaddress.ip_address(h).is_loopback
    except ValueError:
        # Not an IP literal and not whitelisted. Refuse it.
        return False


def assert_local_endpoint(
    url: str, allowed_hosts: Iterable[str] | None = None
) -> str:
    """
    Gate every backend construction through this. Returns the host on success,
    raises NonLocalEndpointError with the offending URL on failure.
    """
    host = host_of(url)
    if is_local_host(host, allowed_hosts):
        return host

    extra = ""
    allowed = sorted(_normalise_allowed(allowed_hosts))
    if allowed:
        extra = " Whitelisted hosts are: %s." % ", ".join(allowed)

    raise NonLocalEndpointError(
        "non-local model endpoint refused: %r (host %r).%s "
        "bpcad runs local inference only - there is no cloud model, no API key "
        "and no hosted endpoint at any tier. Use a loopback host such as "
        "http://127.0.0.1:11434, or add this host to allowed_model_hosts in "
        "config/default.toml if it really is a machine you control."
        % (url, host, extra)
    )


@runtime_checkable
class Backend(Protocol):
    """
    The whole model interface. Anything a backend cannot express through these
    four methods does not belong in the model layer.
    """

    def complete(self, system: str, user: str, schema: dict | None) -> str:
        """Return the model's raw text. `schema` constrains output when given."""
        ...

    def name(self) -> str:
        """The model tag actually in use, for the run log and the report."""
        ...

    def available(self) -> bool:
        """True if this backend can serve a request right now. Never raises."""
        ...

    def endpoint(self) -> str:
        """The resolved endpoint URL, already proven local."""
        ...

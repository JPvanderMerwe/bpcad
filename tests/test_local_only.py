"""
The local-inference-only guarantee.

If any of these fail, bpcad can send a prompt off the machine. That is the one
thing this project must never do, so these are the first tests in the repo.
"""

import pytest

from bpcad.models.base import (
    NonLocalEndpointError,
    assert_local_endpoint,
    is_local_host,
)


LOOPBACK_URLS = [
    "http://127.0.0.1:11434",
    "http://127.0.0.1:11434/api/generate",
    "http://localhost:11434",
    "http://LOCALHOST:11434",
    "http://[::1]:11434",
    "http://127.0.0.2:11434",       # the whole of 127.0.0.0/8 is loopback
    "https://127.0.0.1:11434",
]

NON_LOCAL_URLS = [
    "https://api.anthropic.com/v1/messages",
    "https://api.openai.com/v1/chat/completions",
    "http://8.8.8.8:11434",
    "http://192.168.1.50:11434",     # LAN is not loopback
    "http://10.0.0.5:11434",
    "http://100.64.0.1:11434",       # a Tailscale address, not whitelisted
    "http://ollama.example.com:11434",
    "http://127.0.0.1.evil.com:11434",   # loopback-looking name, still a name
]


@pytest.mark.parametrize("url", LOOPBACK_URLS)
def test_loopback_is_accepted(url):
    assert assert_local_endpoint(url)


@pytest.mark.parametrize("url", NON_LOCAL_URLS)
def test_non_loopback_is_rejected(url):
    with pytest.raises(NonLocalEndpointError):
        assert_local_endpoint(url)


@pytest.mark.parametrize("url", NON_LOCAL_URLS)
def test_rejection_message_names_the_offending_url(url):
    """When this fires you must be able to see which config value did it."""
    with pytest.raises(NonLocalEndpointError) as exc:
        assert_local_endpoint(url)
    assert url in str(exc.value)


@pytest.mark.parametrize(
    "url",
    [
        "ftp://127.0.0.1",
        "file:///etc/passwd",
        "127.0.0.1:11434",      # no scheme
        "http://:11434",        # no host
        "",
        "   ",
    ],
)
def test_unusable_urls_are_rejected(url):
    with pytest.raises(NonLocalEndpointError):
        assert_local_endpoint(url)


def test_explicit_whitelist_is_the_only_way_past_loopback():
    url = "http://100.64.0.1:11434"
    with pytest.raises(NonLocalEndpointError):
        assert_local_endpoint(url)
    assert assert_local_endpoint(url, allowed_hosts=["100.64.0.1"]) == "100.64.0.1"


def test_whitelist_does_not_leak_to_other_hosts():
    with pytest.raises(NonLocalEndpointError):
        assert_local_endpoint(
            "https://api.openai.com/v1", allowed_hosts=["100.64.0.1"]
        )


def test_no_dns_resolution_happens(monkeypatch):
    """
    The check must never resolve a name. It has to work with the network cable
    out, and a resolving check would let through a name that points at loopback
    today and somewhere else tomorrow.
    """
    import socket

    def explode(*args, **kwargs):
        raise AssertionError("the local-host check must not touch DNS")

    monkeypatch.setattr(socket, "gethostbyname", explode)
    monkeypatch.setattr(socket, "getaddrinfo", explode)

    assert assert_local_endpoint("http://127.0.0.1:11434")
    with pytest.raises(NonLocalEndpointError):
        assert_local_endpoint("http://ollama.example.com")


def test_is_local_host_never_raises():
    for value in ["", "   ", "not a host", "::1", "127.0.0.1", None]:
        assert is_local_host(value) in (True, False)

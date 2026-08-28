"""
The Ollama backend. The only real one in this project.

Talks to a local Ollama daemon over HTTP. The host is asserted loopback at
CONSTRUCTION time - see bpcad.models.base - so a misconfigured endpoint fails
immediately and loudly rather than quietly shipping a prompt off the machine.

STRUCTURED OUTPUT
-----------------
Ollama accepts a JSON schema in its `format` field and constrains generation to
match. That is far more reliable than asking a small model to produce JSON and
hoping, so it is used whenever a schema is supplied. Older daemons only accept
the string "json", and some accept neither; both fallbacks exist and WHICH
MECHANISM WAS USED IS RECORDED ON EVERY CALL, because "the model got it wrong"
and "the daemon ignored the schema" need different fixes and look identical
from the outside.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any, Iterable

import httpx

from bpcad.models.base import assert_local_endpoint

# How the output was constrained on a given call.
SCHEMA_NATIVE = "schema"        # daemon enforced our JSON schema
JSON_MODE = "json"              # daemon enforced "valid JSON", not our shape
PROMPT_ONLY = "prompt"          # nothing enforced, the schema went in the prompt
UNCONSTRAINED = "none"          # no schema was requested

# Pass this instead of a schema to ask for valid JSON and nothing more.
#
# WHY THIS IS SOMETIMES BETTER THAN A SCHEMA. Ollama accepts a JSON Schema
# containing a oneOf with a discriminator, and then does not enforce it: it
# constrains the outer object and lets array items through as minimal stubs. On
# the level-2 operations list that is not merely unhelpful, it is destructive -
# qwen2.5-coder:7b answered {"op": "rounded_prism"} with no dimensions at all,
# five attempts running, while the SAME model on the SAME prompt in plain JSON
# mode produced a complete and correct answer first time. Measured 2026-08-28.
#
# So: a schema for a flat object, JSON mode for anything with a union in it.
JSON_ONLY = "__json_only__"


class OllamaError(RuntimeError):
    """The daemon could not be reached, or refused the request."""


class OllamaTimeout(OllamaError):
    """
    The daemon did not answer in time.

    Its own message carries the elapsed seconds and the profile's timeout,
    because on a CPU-only machine the usual cause is simply that the model is
    slow, and the fix is a bigger timeout or a smaller model rather than
    anything being broken.
    """


@dataclass
class CallRecord:
    """
    What one generation actually cost. Every field here ends up in run.json.

    The timings are the daemon's own nanosecond counters, not wall-clock around
    the request, so they separate model load from prompt processing from
    generation. On a slow machine that distinction is the difference between
    "the model is too big" and "the context is too long".
    """

    model: str
    mechanism: str
    elapsed_s: float
    load_s: float = 0.0
    prompt_tokens: int = 0
    gen_tokens: int = 0
    processor: str = "unknown"
    error: str = ""

    @property
    def tokens_per_s(self) -> float:
        gen_time = self.elapsed_s - self.load_s
        return self.gen_tokens / gen_time if gen_time > 0 and self.gen_tokens else 0.0

    def summary(self) -> str:
        if self.error:
            return "%s  FAILED after %.1fs: %s" % (self.model, self.elapsed_s, self.error)
        return (
            "%s  %.1fs (load %.1fs, %d prompt + %d gen tokens, %.1f tok/s, "
            "constraint=%s)"
            % (self.model, self.elapsed_s, self.load_s, self.prompt_tokens,
               self.gen_tokens, self.tokens_per_s, self.mechanism)
        )


@dataclass
class OllamaBackend:
    """Implements the Backend protocol against a local Ollama daemon."""

    model: str
    host: str = "http://127.0.0.1:11434"
    timeout_s: float = 120.0
    num_ctx: int = 8192
    temperature: float = 0.0
    allowed_hosts: tuple[str, ...] = ()
    calls: list[CallRecord] = field(default_factory=list)

    def __post_init__(self) -> None:
        # The whole local-only guarantee, enforced here at construction.
        self._host_name = assert_local_endpoint(self.host, self.allowed_hosts)

    # -- Backend protocol --------------------------------------------------

    def name(self) -> str:
        return self.model

    def endpoint(self) -> str:
        return self.host

    def available(self) -> bool:
        """
        True if the daemon answers AND has this model. Never raises - a caller
        asking "is this usable" must not have to guard the question.
        """
        try:
            with httpx.Client(timeout=5.0) as client:
                r = client.get("%s/api/tags" % self.host.rstrip("/"))
                r.raise_for_status()
                tags = {m.get("name", "") for m in r.json().get("models", [])}
        except Exception:
            return False
        return self.model in tags or any(t.split(":")[0] == self.model.split(":")[0] for t in tags)

    def complete(self, system: str, user: str, schema: dict | None) -> str:
        """
        Generate once. Returns the model's raw text.

        Every call appends a CallRecord to self.calls, including failures.
        """
        payload: dict[str, Any] = {
            "model": self.model,
            "prompt": user,
            "system": system,
            "stream": False,
            "options": {
                "temperature": self.temperature,
                "num_ctx": self.num_ctx,
            },
        }

        mechanism = UNCONSTRAINED
        if schema is JSON_ONLY or schema == JSON_ONLY:
            payload["format"] = "json"
            mechanism = JSON_MODE
        elif schema is not None:
            payload["format"] = schema
            mechanism = SCHEMA_NATIVE

        started = time.monotonic()
        try:
            data = self._post(payload)
        except OllamaError as exc:
            # A daemon too old for schema constraint rejects the request
            # outright. Step down rather than fail, and record that we did.
            if mechanism == SCHEMA_NATIVE and _is_format_rejection(exc):
                payload["format"] = "json"
                mechanism = JSON_MODE
                try:
                    data = self._post(payload)
                except OllamaError as exc2:
                    if _is_format_rejection(exc2):
                        payload.pop("format", None)
                        payload["system"] = _schema_in_prompt(system, schema)
                        mechanism = PROMPT_ONLY
                        data = self._post(payload)
                    else:
                        self._record(mechanism, started, {}, error=str(exc2))
                        raise
            else:
                self._record(mechanism, started, {}, error=str(exc))
                raise

        self._record(mechanism, started, data)
        return data.get("response", "")

    # -- internals ---------------------------------------------------------

    def _post(self, payload: dict[str, Any]) -> dict[str, Any]:
        url = "%s/api/generate" % self.host.rstrip("/")
        try:
            with httpx.Client(timeout=self.timeout_s) as client:
                response = client.post(url, json=payload)
        except httpx.TimeoutException as exc:
            raise OllamaTimeout(
                "%s did not answer within %.0fs. On a CPU-only machine this "
                "usually means the model is simply slow rather than broken - "
                "raise timeout_s for this machine profile, or drop to the "
                "smaller model." % (self.model, self.timeout_s)
            ) from exc
        except httpx.ConnectError as exc:
            raise OllamaError(
                "cannot reach the Ollama daemon at %s. Start it with `ollama "
                "serve`, or check the host in your machine profile. bpcad does "
                "not fall back to anything remote - local inference or none."
                % self.host
            ) from exc
        except httpx.HTTPError as exc:
            raise OllamaError("HTTP error talking to %s: %s" % (self.host, exc)) from exc

        if response.status_code == 404:
            raise OllamaError(
                "Ollama has no model named %r. Pull it with `ollama pull %s`, "
                "or set a model this machine actually has - `ollama list` shows "
                "them." % (self.model, self.model)
            )
        if response.status_code >= 400:
            raise OllamaError(
                "Ollama returned %d: %s" % (response.status_code, response.text[:400])
            )

        try:
            return response.json()
        except ValueError as exc:
            raise OllamaError(
                "Ollama returned something that is not JSON: %r" % response.text[:200]
            ) from exc

    def _record(
        self,
        mechanism: str,
        started: float,
        data: dict[str, Any],
        error: str = "",
    ) -> CallRecord:
        record = CallRecord(
            model=self.model,
            mechanism=mechanism,
            elapsed_s=time.monotonic() - started,
            load_s=(data.get("load_duration") or 0) / 1e9,
            prompt_tokens=data.get("prompt_eval_count") or 0,
            gen_tokens=data.get("eval_count") or 0,
            error=error,
        )
        self.calls.append(record)
        return record

    # -- diagnostics -------------------------------------------------------

    def processor(self) -> str:
        """
        Whether the daemon is running this model on CPU or GPU, as it reports it.

        Worth checking rather than assuming: on the work laptop this comes back
        "100% CPU" despite the machine having both an Intel iGPU and an NPU.
        Neither is used by this Ollama build, so CPU speed is the constraint and
        the timeouts are set accordingly.
        """
        try:
            with httpx.Client(timeout=5.0) as client:
                r = client.get("%s/api/ps" % self.host.rstrip("/"))
                r.raise_for_status()
                for m in r.json().get("models", []):
                    if m.get("name") == self.model:
                        total = m.get("size") or 0
                        gpu = m.get("size_vram") or 0
                        if not total:
                            return "unknown"
                        if gpu == 0:
                            return "100% CPU"
                        if gpu >= total:
                            return "100% GPU"
                        return "%d%% GPU" % round(100 * gpu / total)
        except Exception:
            return "unknown"
        return "not loaded"


def _is_format_rejection(exc: Exception) -> bool:
    """Does this error look like the daemon refusing a `format` value?"""
    text = str(exc).lower()
    return "format" in text and ("invalid" in text or "unsupported" in text or "400" in text)


def _schema_in_prompt(system: str, schema: dict | None) -> str:
    """Last resort: describe the schema in the system prompt and parse-and-retry."""
    if schema is None:
        return system
    return (
        "%s\n\nReply with JSON only - no prose, no markdown fences. It must "
        "validate against this JSON schema:\n%s"
        % (system, json.dumps(schema, indent=2))
    )

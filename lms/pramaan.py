"""All outside service calls go through this server-side module."""

import copy
import json
import math
import os
import time
import uuid
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener


class PramaanError(RuntimeError):
    """Normalized error: never expose an upstream body, provider or secret."""

    def __init__(self, code="unavailable", *, uncertain=False, job_id=None):
        self.code = code
        self.uncertain = uncertain
        self.job_id = job_id
        super().__init__(
            "The action may already have completed. Check its status before trying again."
            if uncertain else "Pramaan could not complete this request."
        )


MISSING_KEY_MESSAGE = "Add PRAMAAN_API_KEY to .env"


class MissingPramaanKey(PramaanError):
    http_status_code = 422

    def __init__(self):
        super().__init__("missing_api_key")
        self.args = (MISSING_KEY_MESSAGE,)


class InvalidGenerationRequest(PramaanError):
    http_status_code = 422

    def __init__(self, label, path, reason):
        super().__init__("invalid_request")
        self.args = (f"{label} schema at {path}: {reason}",)


class IncompleteGeneration(PramaanError):
    http_status_code = 422

    def __init__(self):
        super().__init__("incomplete_reply")
        self.args = ("The reply is incomplete because it reached the reply limit. Retry this step manually with a larger reply limit.",)


class GenerationConfigurationError(PramaanError):
    http_status_code = 422

    def __init__(self):
        super().__init__("reply_limit_configuration")
        self.args = ("The reply limit is too small to produce an answer. Ask your administrator to increase the reply limit before retrying.",)


class PublicCheckoutAddressRequired(PramaanError):
    http_status_code = 422

    def __init__(self):
        super().__init__("public_checkout_address_required")
        self.args = ("Checkout needs a public site address. Ask your administrator to finish payment setup.",)


def generation_result(capability, inputs, result):
    if capability in {"llm.chat", "llm.complete"} and result.get("finishReason") == "length":
        if inputs.get("jsonSchema") or inputs.get("tools") or result.get("toolCalls"):
            raise IncompleteGeneration()
    return result


SURFACES = {
    "email.": "Email",
    "meetings.": "Live class conferencing",
    "calendar.": "Calendars",
    "payments.": "Payments",
    "finance.exchange-rate.": "Currency rates",
    "code.": "The code runner",
    "security.ip.": "Address lookup",
    "auth.social.": "Connected sign-in",
    "apps.": "Connected apps",
    "llm.": "Writing help",
}


class PramaanNotAvailable(PramaanError):
    http_status_code = 503

    def __init__(self, capability):
        super().__init__("not_available_yet")
        surface = next(
            (name for prefix, name in SURFACES.items() if capability.startswith(prefix)),
            "This feature",
        )
        self.args = (f"{surface} is not available yet.",)


class ConnectionRequired(PramaanError):
    """The platform can run this only on the person's own connected account.

    Plain on purpose: the message names no provider and no slot key.
    """

    http_status_code = 503

    def __init__(self):
        super().__init__("connection_required")
        self.args = ("Connect your account in settings first.",)


SCHEMA_KEYS = frozenset({"type", "properties", "required", "additionalProperties", "items",
    "enum", "const", "anyOf", "$defs", "$ref", "title", "description", "default", "examples",
    "minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum", "minLength", "maxLength",
    "minItems", "maxItems"})
SCHEMA_TYPES = frozenset({"object", "array", "string", "number", "integer", "boolean", "null"})
SCHEMA_BOUNDS = frozenset({"minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum",
    "minLength", "maxLength", "minItems", "maxItems"})
UNAVAILABLE_CODES = frozenset({"upstream_unavailable", "not_available_yet", "not_available",
    "capability_unavailable", "not_implemented", "unsupported_capability"})


def _schema_path(path, key):
    return path + "/" + str(key).replace("~", "~0").replace("/", "~1")


def _schema_json(value, label, path="#", stack=None, depth=0):
    stack = set() if stack is None else stack
    if depth > 32:
        raise InvalidGenerationRequest(label, path, "JSON value is too deep")
    if value is None or isinstance(value, str | bool | int):
        return
    if isinstance(value, float) and math.isfinite(value):
        return
    if not isinstance(value, dict | list) or id(value) in stack:
        raise InvalidGenerationRequest(label, path, "must contain finite JSON values without cycles")
    stack.add(id(value))
    for key, item in (value.items() if isinstance(value, dict) else enumerate(value)):
        if not isinstance(key, str | int) or isinstance(value, dict) and not isinstance(key, str):
            raise InvalidGenerationRequest(label, path, "property names must be strings")
        _schema_json(item, label, _schema_path(path, key), stack, depth + 1)
    stack.remove(id(value))


def validate_json_schema(value, label="Response"):
    """Validate the platform's bounded subset, including acyclic local references."""
    if not isinstance(value, dict):
        raise InvalidGenerationRequest(label, "#", "root must be a JSON Schema object")
    _schema_json(value, label)
    try:
        size = len(json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode())
    except (ValueError, TypeError, OverflowError):
        raise InvalidGenerationRequest(label, "#", "must be serializable JSON") from None
    if size > 65536:
        raise InvalidGenerationRequest(label, "#", "exceeds 64 KB")
    nodes = set()
    count = 0

    def children(node, path):
        for key in ("properties", "$defs"):
            for name, child in node.get(key, {}).items():
                yield child, _schema_path(_schema_path(path, key), name)
        for key in ("items", "additionalProperties"):
            if isinstance(node.get(key), dict):
                yield node[key], _schema_path(path, key)
        for index, child in enumerate(node.get("anyOf", [])):
            yield child, f"{path}/anyOf/{index}"

    def walk(node, path, depth):
        nonlocal count
        def fail(key, reason):
            raise InvalidGenerationRequest(label, _schema_path(path, key) if key else path, reason)
        if not isinstance(node, dict):
            fail("", "must be a schema object")
        if depth > 16:
            fail("", "exceeds depth 16")
        count += 1
        if count > 256:
            fail("", "exceeds 256 schema nodes")
        nodes.add(id(node))
        for key, item in node.items():
            if key not in SCHEMA_KEYS:
                fail(key, "unsupported keyword " + key)
            if key == "type":
                items = item if isinstance(item, list) else [item]
                if not items or any(not isinstance(t, str) or t not in SCHEMA_TYPES for t in items) or len(set(items)) != len(items):
                    fail(key, "invalid type")
            if key in {"properties", "$defs", "items"} and not isinstance(item, dict):
                fail(key, "must be an object")
            if key == "required" and (not isinstance(item, list) or any(not isinstance(t, str) for t in item) or len(set(item)) != len(item)):
                fail(key, "must be distinct property names")
            if key == "additionalProperties" and not isinstance(item, bool | dict):
                fail(key, "must be boolean or a schema")
            if key in {"anyOf", "enum"} and (not isinstance(item, list) or not 1 <= len(item) <= (16 if key == "anyOf" else 256)):
                fail(key, "exceeds branch or value limit")
            if key in {"title", "description", "$ref"} and not isinstance(item, str):
                fail(key, "must be a string")
            if key == "examples" and not isinstance(item, list):
                fail(key, "must be an array")
            if key in SCHEMA_BOUNDS and (isinstance(item, bool) or not isinstance(item, int | float) or isinstance(item, float) and not math.isfinite(item) or key in {"minLength", "maxLength", "minItems", "maxItems"} and (not isinstance(item, int) or item < 0)):
                fail(key, "invalid bound")
        for child, child_path in children(node, path):
            walk(child, child_path, depth + 1)

    walk(value, "#", 0)
    expanded = 0

    def references(node, path, stack, depth):
        nonlocal expanded
        expanded += 1
        if id(node) in stack or depth > 32 or expanded > 4096:
            raise InvalidGenerationRequest(label, path, "recursive or excessive reference expansion")
        next_stack = stack | {id(node)}
        if "$ref" in node:
            ref, target = node["$ref"], value
            import re
            if not ref.startswith("#/") or re.search(r"~(?![01])", ref):
                raise InvalidGenerationRequest(label, path + "/$ref", "only local #/... references are allowed")
            for key in ref[2:].split("/"):
                key = key.replace("~1", "/").replace("~0", "~")
                if not isinstance(target, dict) or key not in target:
                    raise InvalidGenerationRequest(label, path + "/$ref", "reference does not resolve")
                target = target[key]
            if not isinstance(target, dict) or id(target) not in nodes:
                raise InvalidGenerationRequest(label, path + "/$ref", "reference must resolve to a schema")
            references(target, path + "/$ref", next_stack, depth + 1)
        for child, child_path in children(node, path):
            references(child, child_path, next_stack, depth + 1)

    references(value, "#", set(), 0)
    return value


def normalise_json_schema(value, label="Response"):
    """Strip only refused annotations; unexpressible constraints are rejected."""
    if not isinstance(value, dict):
        raise InvalidGenerationRequest(label, "#", "root must be a JSON Schema object")
    _schema_json(value, label)
    def convert(node, path, depth=0):
        if not isinstance(node, dict) or depth > 16:
            raise InvalidGenerationRequest(label, path, "must be a schema object within depth 16")
        result = {}
        for key, item in node.items():
            if key in {"$schema", "format"}:
                continue
            if key not in SCHEMA_KEYS:
                raise InvalidGenerationRequest(label, _schema_path(path, key), "unsupported keyword " + key)
            if key in {"properties", "$defs"} and isinstance(item, dict):
                result[key] = {name: convert(child, _schema_path(_schema_path(path, key), name), depth + 1) for name, child in item.items()}
            elif key in {"items", "additionalProperties"} and isinstance(item, dict):
                result[key] = convert(item, _schema_path(path, key), depth + 1)
            elif key == "anyOf" and isinstance(item, list):
                result[key] = [convert(child, f"{path}/anyOf/{index}", depth + 1) for index, child in enumerate(item)]
            else:
                result[key] = copy.deepcopy(item)
        return result
    return validate_json_schema(convert(value, "#"), label)


def generation_request(inputs, *, normalise=True):
    """One boundary for chat/completion messages, token limits and schemas."""
    if not isinstance(inputs, dict) or "prompt" in inputs or not isinstance(inputs.get("messages"), list) or not inputs["messages"]:
        raise InvalidGenerationRequest("Generation", "#/messages", "send nonempty messages instead of prompt")
    for index, message in enumerate(inputs["messages"]):
        if not isinstance(message, dict) or not isinstance(message.get("role"), str) or message.get("role") not in {"system", "user", "assistant", "tool"} or not (
                isinstance(message.get("content"), str) or message.get("role") == "assistant" and isinstance(message.get("toolCalls"), list)):
            raise InvalidGenerationRequest("Generation", f"#/messages/{index}", "must be a message with a supported role and text or assistant tool calls")
    request = dict(inputs)
    maximum = inputs.get("maxTokens", 1024) if normalise else inputs.get("maxTokens")
    if isinstance(maximum, bool) or not isinstance(maximum, int) or maximum < 64:
        raise InvalidGenerationRequest("Generation", "#/maxTokens", "must be an integer of 64 or more")
    request["maxTokens"] = maximum
    validate = normalise_json_schema if normalise else validate_json_schema
    if "jsonSchema" in inputs:
        request["jsonSchema"] = validate(inputs["jsonSchema"], "Response")
    if "tools" in inputs:
        if not isinstance(inputs["tools"], list):
            raise InvalidGenerationRequest("Generation", "#/tools", "must be a list")
        request["tools"] = []
        for tool in inputs["tools"]:
            if not isinstance(tool, dict) or not isinstance(tool.get("name"), str):
                raise InvalidGenerationRequest("Generation", "#/tools", "each tool needs a name")
            request["tools"].append({**tool, "parameters": validate(tool.get("parameters"), "Tool " + tool["name"])})
    return request


class NoRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class PramaanClient:
    """Single server-side HTTP client. Mutating requests are never retried."""

    CAPABILITIES = frozenset({
        "email.send", "email.status", "email.message.send", "email.message.reply",
        "email.account.connect.start", "email.account.connect.status",
        "email.inboxes.list", "calendar.calendars.list",
        "meetings.room.create", "meetings.room.get", "meetings.room.delete",
        "meetings.recordings.list", "meetings.recording.get",
        "calendar.event.create", "calendar.event.update", "calendar.event.delete",
        "calendar.free-busy.get", "calendar.calendar.update",
        "payments.checkout.create", "payments.checkout.get", "payments.payment-link.create",
        "finance.exchange-rate.get", "code.run", "code.languages.list",
        "security.ip.lookup", "auth.social.exchange", "llm.complete", "llm.chat",
        "text.translate", "audio.transcribe",
        "apps.connections.list", "apps.connection.start",
    })
    ACTIONS = frozenset({
        "email.send", "email.message.send", "email.message.reply",
        "email.account.connect.start",
        "meetings.room.create", "meetings.room.delete",
        "calendar.event.create", "calendar.event.update", "calendar.event.delete",
        "calendar.calendar.update",
        "payments.checkout.create", "payments.payment-link.create",
        "code.run", "apps.connection.start",
    })

    def __init__(self, *, api_key=None, base_url=None, transport=None, sleep=time.sleep):
        self._api_key = api_key if api_key is not None else os.environ.get("PRAMAAN_API_KEY", "")
        self._base_url = (base_url or os.environ.get("PRAMAAN_BASE_URL") or "https://api.pramaan.dev").rstrip("/")
        parsed = urlparse(self._base_url)
        if parsed.scheme != "https" and not (
            parsed.scheme == "http" and parsed.hostname in {"localhost", "127.0.0.1", "fake-pramaan"}
        ):
            raise PramaanError("invalid_configuration")
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise PramaanError("invalid_configuration")
        self._transport = transport or (self._fake if os.environ.get("PRAMAAN_FAKE") == "1" else self._http)
        self._sleep = sleep

    @property
    def configured(self):
        return bool(self._api_key.strip())

    def require_configured(self):
        if not self.configured:
            raise MissingPramaanKey()

    @staticmethod
    def _fake(method, url, headers, body):
        # Explicit local fixture mode has no network transport or outside effects.
        return 503, {"error": {"code": "upstream_unavailable", "retryable": False}}

    def _http(self, method, url, headers, body):
        if isinstance(body, bytes):
            payload = body
        elif body is not None:
            payload = json.dumps(body).encode()
        else:
            payload = None
        request = Request(url, data=payload, headers=headers, method=method)
        try:
            with build_opener(NoRedirects()).open(request, timeout=30) as response:
                raw = response.read(16_000_001)
                if len(raw) > 16_000_000:
                    raise PramaanError("invalid_response")
                return response.status, json.loads(raw)
        except HTTPError as error:
            # Read only bounded, recognized error codes; never surface the upstream body.
            try:
                payload = json.loads(error.read(16_001))
                code = payload.get("error") if isinstance(payload, dict) else None
                message = code.get("message", "") if isinstance(code, dict) else (payload.get("message", "") if isinstance(payload, dict) else "")
                if isinstance(code, dict):
                    code = code.get("code")
                if not code and isinstance(payload, dict):
                    code = payload.get("code")
                if error.code == 400 and code == "invalid_request" and isinstance(message, str) and "maxtokens" in message.lower():
                    return 400, {"error": {"code": "invalid_request", "message": "maxTokens"}}
                if error.code == 400 and code == "invalid_request" and message == "Must be a public http or https URL.":
                    return 400, {"error": {"code": "invalid_request", "message": "public-return-url"}}
            except (ValueError, OSError):
                code = None
            preserved = isinstance(code, str) and code in UNAVAILABLE_CODES
            return error.code, {"error": code if preserved else None}
        except (URLError, OSError, ValueError):
            raise PramaanError("unavailable", uncertain=method == "POST") from None

    def _request(self, method, path, body=None, *, idempotency_key=None, capability=None):
        self.require_configured()
        headers = {"Authorization": "Bearer " + self._api_key, "Accept": "application/json"}
        if body is not None:
            headers["Content-Type"] = "application/json"
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        try:
            status, result = self._transport(method, self._base_url + path, headers, body)
        except PramaanError:
            raise
        except Exception:
            raise PramaanError("unavailable", uncertain=method == "POST") from None
        if status >= 400:
            remote_error = result.get("error") if isinstance(result, dict) else None
            if isinstance(remote_error, dict):
                remote_code = remote_error.get("code")
            elif isinstance(remote_error, str):
                remote_code = remote_error
            else:
                remote_code = None
            if not remote_code and isinstance(result, dict):
                remote_code = result.get("code")
            remote_message = remote_error.get("message", "") if isinstance(remote_error, dict) else (result.get("message", "") if isinstance(result, dict) else "")
            if status == 400 and capability in {"llm.chat", "llm.complete"} and remote_code == "invalid_request" and isinstance(remote_message, str) and "maxtokens" in remote_message.lower():
                raise GenerationConfigurationError()
            if status == 400 and capability == "payments.checkout.create" and remote_code == "invalid_request" and isinstance(remote_message, str) and remote_message in {"public-return-url", "Must be a public http or https URL."}:
                raise PublicCheckoutAddressRequired()
            if capability and (status == 501 or isinstance(remote_code, str) and remote_code in UNAVAILABLE_CODES):
                raise PramaanNotAvailable(capability)
            code = "request_rejected"
            uncertain = method == "POST" and status >= 500
            raise PramaanError(code, uncertain=uncertain)
        if status not in {200, 201, 202} or not isinstance(result, dict):
            raise PramaanError("invalid_response", uncertain=method == "POST")
        return status, result

    def run(self, capability, inputs, *, idempotency_key=None):
        self.require_configured()
        if capability not in self.CAPABILITIES:
            raise PramaanError("unsupported_capability")
        if capability in self.ACTIONS and not idempotency_key:
            raise PramaanError("missing_idempotency_key")
        if capability in {"payments.payment-link.create", "payments.checkout.create"}:
            inputs = {**inputs, "taxCategory": os.environ.get("PRAMAAN_TAX_CATEGORY", "").strip() or "edtech"}
        if capability in {"llm.chat", "llm.complete"}:
            inputs = generation_request(inputs)
        status, result = self._request("POST", "/v1/capabilities/" + quote(capability, safe=""), inputs,
                                       idempotency_key=idempotency_key, capability=capability)
        if status == 202:
            if not isinstance(result.get("job_id"), str) or result.get("status") not in {"running", "done", "failed", "cancelled"}:
                raise PramaanError("invalid_response", uncertain=capability in self.ACTIONS)
        if isinstance(result, dict) and result.get("can_run") is False and result.get("reason") == "connection_required":
            raise ConnectionRequired()
        return generation_result(capability, inputs, result)

    def job(self, job_id):
        _, result = self._request("GET", "/v1/jobs/" + quote(job_id, safe=""))
        return result

    def call(self, capability, inputs, *, idempotency_key=None, max_polls=60):
        result = self.run(capability, inputs, idempotency_key=idempotency_key)
        if "job_id" not in result:
            return result
        job_id = result["job_id"]
        for _ in range(max_polls):
            state = result.get("status")
            if state == "done":
                completed = result.get("result")
                if not isinstance(completed, dict):
                    raise PramaanError("invalid_response", uncertain=capability in self.ACTIONS)
                if completed.get("can_run") is False and completed.get("reason") == "connection_required":
                    raise ConnectionRequired()
                return generation_result(capability, inputs, completed)
            if state in {"failed", "cancelled"}:
                raise PramaanError("job_failed", uncertain=capability in self.ACTIONS)
            if state != "running":
                raise PramaanError("invalid_response")
            self._sleep(2)
            result = self.job(job_id)
        raise PramaanError("job_pending", uncertain=capability in self.ACTIONS, job_id=job_id)

    def upload_file(self, content: bytes, kind: str, content_type: str) -> dict:
        """Upload one bounded file as transcription input; it is kept 24 hours."""
        self.require_configured()
        if kind not in {"audio", "video", "document", "data", "image"}:
            raise PramaanError("invalid_request")
        headers = {
            "Authorization": "Bearer " + self._api_key,
            "Content-Type": content_type,
            "Idempotency-Key": str(uuid.uuid4()),
        }
        try:
            status, result = self._transport(
                "POST", f"{self._base_url}/v1/files?kind={quote(kind, safe='')}",
                headers, content,
            )
        except PramaanError:
            raise
        except Exception:
            raise PramaanError("unavailable", uncertain=True) from None
        if status == 404:
            raise PramaanNotAvailable("audio.transcribe")
        if status != 201 or not isinstance(result, dict) or not result.get("fileId"):
            raise PramaanError("invalid_response", uncertain=True)
        return result

    def delete_file(self, file_id: str) -> None:
        """Remove one uploaded file at once."""
        self.require_configured()
        try:
            self._transport(
                "DELETE", f"{self._base_url}/v1/files/{quote(file_id, safe='')}",
                {"Authorization": "Bearer " + self._api_key, "Accept": "application/json",
                 "Idempotency-Key": str(uuid.uuid4())},
                None,
            )
        except PramaanError:
            raise
        except Exception:
            raise PramaanError("unavailable", uncertain=False) from None

    def exchange_social_sign_in(self, *, provider_key: str | None = None, code: str,
                                redirect_uri: str, pkce_verifier: str | None = None,
                                expected_nonce: str | None = None) -> dict:
        """Redeem a single-use sign-in code for verified identity claims.

        Upstream credentials never pass through here: the platform returns
        claims only, and the application keeps no authorization secrets.
        """
        inputs = {"code": code, "redirectUri": redirect_uri}
        if provider_key:
            inputs["providerKey"] = provider_key
        if pkce_verifier:
            inputs["pkceVerifier"] = pkce_verifier
        if expected_nonce:
            inputs["expectedNonce"] = expected_nonce
        _, result = self._request("POST", "/v1/capabilities/auth.social.exchange", inputs,
                                  capability="auth.social.exchange")
        if not isinstance(result.get("subjectId"), str) or not result.get("subjectId"):
            raise PramaanError("invalid_response")
        claims = {
            "subject_id": result["subjectId"],
            "email": result.get("email") or "",
            "email_verified": result.get("emailVerified") is True,
            "display_name": result.get("displayName") or "",
        }
        if not claims["email"] or not claims["email_verified"]:
            raise PramaanError("identity_unverified")
        return claims

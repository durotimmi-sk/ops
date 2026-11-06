import json
import logging
import os
import socket
import urllib.error
import urllib.parse
import urllib.request


LOG = logging.getLogger("taskvault.inference")
VULTR_INFERENCE_HOST = "api.vultrinference.com"

DEFAULT_SYSTEM = (
    "You are TaskVault, a careful procurement assistant. You do not have a live browser, "
    "supplier-page content, product images, or external-action tools in this request, even if "
    "the user included URLs. Never claim to have opened, checked, compared, or verified a page. "
    "Never invent suppliers, prices, stock, delivery times, certifications, citations, or links. "
    "Separate information provided by the user from general guidance and unknown facts. Ask the "
    "user to paste relevant page details when evidence is needed. You may help structure a "
    "comparison or draft a quote request, but cannot send messages, place orders, or make other "
    "external changes. Keep the answer clear, concise, and specific."
)


class InferenceError(Exception):
    def __init__(self, message, status=502, code="inference_error"):
        super().__init__(message)
        self.status = status
        self.code = code


def inference_configured():
    return all(
        os.environ.get(key, "").strip()
        for key in ("VULTR_INFERENCE_URL", "VULTR_INFERENCE_API_KEY", "VULTR_INFERENCE_MODEL")
    ) and inference_provider_allowed()


def competition_track():
    return os.environ.get("TASKVAULT_COMPETITION_TRACK", "development").strip().lower() or "development"


def inference_provider_allowed(endpoint=None):
    track = competition_track()
    if track not in ("development", "blast_radius_zero", "future_of_work"):
        return False
    if track != "blast_radius_zero":
        return True
    endpoint = endpoint if endpoint is not None else os.environ.get("VULTR_INFERENCE_URL", "")
    parsed = urllib.parse.urlsplit(endpoint.strip())
    return parsed.scheme == "https" and parsed.hostname == VULTR_INFERENCE_HOST


def inference_policy_status():
    track = competition_track()
    endpoint = os.environ.get("VULTR_INFERENCE_URL", "").strip()
    required_provider = "Vultr Serverless Inference" if track == "blast_radius_zero" else None
    return {
        "track": track,
        "required_provider": required_provider,
        "provider_allowed": inference_provider_allowed(endpoint) if endpoint else None,
    }


def inference_endpoint():
    endpoint = os.environ.get("VULTR_INFERENCE_URL", "").strip()
    parsed = urllib.parse.urlsplit(endpoint)
    if (
        parsed.scheme not in ("https", "http")
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise InferenceError(
            "VULTR_INFERENCE_URL must be a full HTTPS chat-completions endpoint.",
            status=503,
            code="inference_not_configured",
        )
    if parsed.scheme != "https" and parsed.hostname not in ("127.0.0.1", "::1", "localhost"):
        raise InferenceError(
            "The inference endpoint must use HTTPS.",
            status=503,
            code="inference_not_configured",
        )
    track = competition_track()
    if track not in ("development", "blast_radius_zero", "future_of_work"):
        raise InferenceError(
            "TASKVAULT_COMPETITION_TRACK must be development, blast_radius_zero, or future_of_work.",
            status=503,
            code="inference_track_invalid",
        )
    if track == "blast_radius_zero" and parsed.hostname != VULTR_INFERENCE_HOST:
        raise InferenceError(
            "Blast Radius Zero requires Vultr Serverless Inference for agent LLM calls.",
            status=503,
            code="inference_provider_not_allowed",
        )
    return endpoint


def infer(history, system_message=None, temperature=0.2, max_tokens=None, timeout=90):
    endpoint = inference_endpoint()
    api_key = os.environ.get("VULTR_INFERENCE_API_KEY", "").strip()
    model = os.environ.get("VULTR_INFERENCE_MODEL", "").strip()
    if not api_key or not model:
        raise InferenceError(
            "Vultr Serverless Inference is not configured. Set its endpoint, API key, and model.",
            status=503,
            code="inference_not_configured",
        )
    messages = [{"role": "system", "content": system_message or DEFAULT_SYSTEM}] + history
    body = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
    }
    if max_tokens:
        body["max_tokens"] = max_tokens
    payload = json.dumps(body).encode("utf-8")
    request = urllib.request.Request(
        endpoint,
        data=payload,
        headers={
            "Authorization": "Bearer " + api_key,
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            result = json.loads(response.read(4 * 1024 * 1024).decode("utf-8"))
    except urllib.error.HTTPError as error:
        LOG.warning("Inference provider returned HTTP %s", error.code)
        raise InferenceError(
            "Vultr Serverless Inference returned an error (HTTP {}).".format(error.code)
        ) from error
    except (urllib.error.URLError, socket.timeout, TimeoutError) as error:
        LOG.warning("Inference provider could not be reached: %s", type(error).__name__)
        raise InferenceError("Could not reach Vultr Serverless Inference.") from error
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        raise InferenceError("Vultr Serverless Inference returned invalid JSON.") from error
    except OSError as error:
        LOG.warning("Inference transport failed: %s", type(error).__name__)
        raise InferenceError("Could not reach Vultr Serverless Inference.") from error

    try:
        content = result["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as error:
        raise InferenceError("Vultr Serverless Inference returned an unexpected response.") from error
    if not isinstance(content, str) or not content.strip():
        raise InferenceError("Vultr Serverless Inference returned an empty response.")
    return content.strip()


def request_inference(history, system_message=None):
    return infer(history, system_message=system_message)


def narrative_for_research(payload):
    if not inference_configured():
        return None
    from taskvault_research import build_narrative_messages

    try:
        return infer(build_narrative_messages(payload), temperature=0.15, max_tokens=360, timeout=12)
    except InferenceError as error:
        LOG.warning("Falling back to the deterministic sourcing summary: %s", error)
        return None

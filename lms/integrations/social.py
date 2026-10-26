"""Hosted sign-in with visitor-bound state; local password sessions remain."""
import base64
import hashlib
import secrets
import time
from urllib.parse import urlparse

import frappe
from frappe import _

from lms.pramaan import PramaanClient, PramaanError


def providers():
    return [p for p in frappe.conf.get("pramaan_social_providers", []) if p in {"google", "microsoft"}]


@frappe.whitelist(allow_guest=True, methods=["GET"])
def status():
    return {"enabled": bool(providers()), "not_live_verified": True}


@frappe.whitelist(allow_guest=True, methods=["POST"])
def start(provider_key: str):
    if provider_key not in providers():
        frappe.throw(_("Connected sign-in is not configured."), frappe.PermissionError)
    redirect_uri = frappe.utils.get_url("/api/method/lms.integrations.social.callback")
    if not redirect_uri.startswith("https://"):
        frappe.throw(_("Connected sign-in needs a registered HTTPS site address."))
    state, nonce, verifier = (secrets.token_urlsafe(32) for _ in range(3))
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    try:
        result = PramaanClient().call("auth.social.start", {
            "providerKey": provider_key, "redirectUri": redirect_uri, "state": state,
            "nonce": nonce, "codeChallenge": challenge,
        }, idempotency_key=secrets.token_hex(16))
        target = urlparse(result.get("authorizationUrl", ""))
        if result.get("state") != state or target.scheme != "https" or target.hostname != urlparse(PramaanClient()._base_url).hostname or not target.path.startswith("/connect/link/"):
            raise PramaanError("invalid_response")
    except PramaanError as error:
        frappe.throw(str(error))
    binding = secrets.token_urlsafe(32)
    frappe.local.cookie_manager.set_cookie("social_binding", binding, secure=True, httponly=True, samesite="Lax", max_age=600)
    frappe.cache.set_value("social:" + binding, {
        "state": state, "nonce": nonce, "verifier": verifier, "start_ref": result["startRef"],
        "redirect_uri": redirect_uri, "created": time.time(),
    }, expires_in_sec=600)
    return {"url": result["authorizationUrl"]}


@frappe.whitelist(allow_guest=True, methods=["GET"])
def callback(code: str = "", state: str = "", error: str = "", redirect_to: str = ""):
    binding = frappe.request.cookies.get("social_binding", "")
    key = "social:" + binding
    with frappe.cache.lock(key + ":lock", timeout=30):
        saved = frappe.cache.get_value(key)
        frappe.cache.delete_value(key)
    location = "/login?signin=unavailable"
    try:
        if error or not code or not saved or not secrets.compare_digest(saved["state"], state) or time.time() - saved["created"] > 600:
            raise PramaanError("invalid_state")
        claims = PramaanClient().exchange_social_sign_in(
            code=code, redirect_uri=saved["redirect_uri"], pkce_verifier=saved["verifier"],
            expected_nonce=saved["nonce"], start_ref=saved["start_ref"], state=state,
        )
        user = frappe.db.get_value("User", {"email": claims["email"], "enabled": 1}, "name")
        if not user or user in {"Guest", "Administrator"}:
            raise PramaanError("account_required")
        frappe.local.login_manager.login_as(user)
        location = "/lms"
    except PramaanError:
        pass
    frappe.local.response.update(type="redirect", location=location)

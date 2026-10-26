"""Invitations create local accounts, never managed identities."""
import hashlib
import re
import secrets

import frappe
from frappe import _

from lms.pramaan import PramaanClient, PramaanError

ALLOWED_ROLES = {"LMS Student", "Course Creator", "Batch Evaluator"}


@frappe.whitelist(methods=["POST"])
def create(email: str, role: str = "LMS Student"):
    frappe.only_for(["System Manager", "Moderator"])
    if role not in ALLOWED_ROLES:
        frappe.throw(_("Choose a learner, course creator or batch evaluator role."))
    try:
        return PramaanClient().call("auth.app-invitation.create", {
            "email": email, "role": role, "returnUrl": frappe.utils.get_url("/invitation"),
        }, idempotency_key=secrets.token_hex(16))
    except PramaanError as error:
        frappe.throw(str(error))


@frappe.whitelist(allow_guest=True, methods=["POST"])
def accept(token: str):
    if not re.fullmatch(r"[A-Za-z0-9_-]{43}", token):
        frappe.throw(_("This invitation is invalid or expired."))
    try:
        invitation = PramaanClient().call("auth.app-invitation.accept", {"token": token}, idempotency_key=secrets.token_hex(16))
    except PramaanError as error:
        frappe.throw(str(error))
    if invitation.get("role") not in ALLOWED_ROLES or not invitation.get("invitationRef"):
        frappe.throw(_("This invitation has an unsupported role."))
    # Serialize retries, including concurrent accepts. The unique user email is
    # the durable boundary; an existing account is never granted a new role.
    email = frappe.utils.validate_email_address(invitation["email"], throw=True)
    invitation_key = hashlib.sha256(invitation["invitationRef"].encode()).hexdigest()
    with frappe.cache.lock("app-invitation:" + invitation_key, timeout=30):
        if frappe.db.exists("LMS App Invitation", {"invitation_ref": invitation_key}):
            return {"status": "accepted"}
        if not frappe.db.exists("User", email):
            user = frappe.get_doc({
                "doctype": "User", "email": email, "first_name": email.split("@")[0],
                "send_welcome_email": 0, "user_type": "Website User",
                "roles": [{"role": invitation["role"]}],
            })
            user.insert(ignore_permissions=True)
        frappe.get_doc({"doctype": "LMS App Invitation", "invitation_ref": invitation_key, "member": email, "role": invitation["role"]}).insert(ignore_permissions=True)
        frappe.db.commit()
    return {"status": "accepted", "message": _("Your account is ready. Use Forgot password on the sign-in page to set your password.")}

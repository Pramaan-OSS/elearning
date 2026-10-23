"""Durable mail delivery through the application's single Pramaan client."""
import base64
import json
import mimetypes
import uuid
from email.utils import getaddresses
from importlib import import_module

import frappe
from frappe import _

from lms.pramaan import PramaanClient, PramaanError


def client():
    return PramaanClient()


def default_sender():
    """One site setting holds the complete outgoing name and address."""
    configured = frappe.db.get_single_value("LMS Settings", "outgoing_sender_email")
    if configured:
        return configured
    return frappe.get_meta("LMS Settings").get_field("outgoing_sender_email").default


def addresses(value):
    values = value if isinstance(value, list | tuple) else [value or ""]
    return list(dict.fromkeys(address for _name, address in getaddresses(values) if address))


def install_transport(*args, **kwargs):
    """Route every frappe.sendmail call through the single client."""
    frappe.sendmail = sendmail
    import_module("frappe.email").sendmail = sendmail


def render_message(kwargs):
    if kwargs.get("template"):
        return frappe.render_template(
            "templates/emails/" + kwargs["template"] + ".html", kwargs.get("args") or {}
        )
    return kwargs.get("message") or kwargs.get("content") or ""


def attachments_payload(attachments):
    out = []
    for attachment in attachments or []:
        if isinstance(attachment, str):
            attachment = {"file_url": attachment}
        if attachment.get("file_url"):
            file_doc = frappe.get_doc("File", {"file_url": attachment["file_url"]})
            file_doc.check_permission("read")
            content = file_doc.get_content()
            filename = file_doc.file_name
        else:
            content = attachment.get("fcontent") or attachment.get("content") or b""
            filename = attachment.get("fname") or attachment.get("filename") or "attachment"
        if isinstance(content, str):
            content = content.encode()
        out.append({
            "filename": filename,
            "content": base64.b64encode(content).decode(),
            "mimeType": mimetypes.guess_type(filename)[0] or "application/octet-stream",
        })
    return out


def sendmail(recipients=None, sender=None, subject=None, message=None, **kwargs):
    """Queue a supported send atomically; the worker runs only after commit.

    Never retries: an accepted request is not sent twice, and an uncertain one
    must be checked before any new attempt.
    """
    if frappe.flags.mute_emails or frappe.flags.in_test:
        return None
    to = addresses(recipients)
    cc = addresses(kwargs.get("cc"))
    bcc = addresses(kwargs.get("bcc"))
    if not (to or cc or bcc):
        return None
    payload = {
        "from": default_sender(),
        "to": to,
        "cc": cc,
        "bcc": bcc,
        "subject": subject or "Message",
        "html": render_message({**kwargs, "message": message}),
    }
    attachments = attachments_payload(kwargs.get("attachments"))
    for image in kwargs.get("inline_images") or []:
        attachments.append({
            "filename": image.get("filename") or "inline",
            "content": base64.b64encode(image.get("content") or b"").decode(),
            "mimeType": mimetypes.guess_type(image.get("filename") or "")[0]
            or "application/octet-stream",
        })
    if attachments:
        payload["attachments"] = attachments
    if kwargs.get("reply_to"):
        payload["replyTo"] = addresses(kwargs["reply_to"])[0]
    outbox = frappe.get_doc({
        "doctype": "Pramaan Outbox",
        "capability": "email.send",
        "payload": json.dumps(payload),
        "idempotency_key": str(uuid.uuid4()),
        "state": "Pending",
        "communication": kwargs.get("communication"),
        "requested_by": frappe.session.user,
    }).insert(ignore_permissions=True)
    frappe.enqueue(deliver, name=outbox.name, enqueue_after_commit=True)
    return frappe._dict(name=outbox.name, messageId=None, status="queued")


def deliver(name):
    """Persist intent before sending; uncertain outcomes never auto-retry."""
    outbox = frappe.get_doc("Pramaan Outbox", name)
    frappe.db.sql("select name from `tabPramaan Outbox` where name=%s for update", name)
    outbox.reload()
    if outbox.state not in ("Pending", "Sending"):
        return
    outbox.db_set("state", "Sending")
    frappe.db.commit()
    try:
        result = client().call(outbox.capability, json.loads(outbox.payload),
                               idempotency_key=outbox.idempotency_key)
    except PramaanError as error:
        outbox.db_set({"state": "Failed", "error": str(error)})
        _link_message_id(outbox)
        return
    outbox.db_set({
        "state": "Sent",
        "message_id": result.get("rfcMessageId") or "",
        "acceptance": result.get("acceptance") or result.get("status") or "",
        "platform_ref": result.get("ref") or "",
    })
    _link_message_id(outbox, result.get("rfcMessageId"))


def _link_message_id(outbox, message_id=None):
    """Keep the conversation record's threading id equal to the sent one."""
    if not (outbox.communication and message_id):
        return
    try:
        communication = frappe.get_doc("Communication", outbox.communication)
        if not communication.message_id:
            communication.db_set("message_id", message_id)
    except Exception:
        frappe.log_error(title="Could not store the message id of a sent email")


def drain():
    """Scheduled. Sends queued mail after a worker restart left it behind.

    Idempotency keys make a second delivery attempt safe; failures are
    recorded, never retried again.
    """
    for name in frappe.get_all(
        "Pramaan Outbox", {"state": "Pending"}, pluck="name", limit=200
    ):
        deliver(name)

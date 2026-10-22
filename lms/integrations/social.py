"""Local sign-in stays available while hosted social authorization is absent.

The exchange capability alone cannot start a sign-in. Sending a visitor to a
vendor authorization URL would restore an outside flow, so the old entry points
stay closed. Existing bookmarks return to the working password form.
"""
import frappe
from frappe import _


@frappe.whitelist(allow_guest=True, methods=["GET"])
def status():
    return {"enabled": False}


@frappe.whitelist(allow_guest=True, methods=["GET"])
def start():
    frappe.throw(_("Connected sign-in is not available yet. Use password sign-in."), frappe.PermissionError)


@frappe.whitelist(allow_guest=True, methods=["GET"])
def callback(code: str = "", state: str = "", error: str = "", redirect_to: str = ""):
    frappe.local.response["type"] = "redirect"
    frappe.local.response["location"] = "/login?signin=unavailable"

"""Local password completion using the retained account backend."""
import frappe
from frappe.sessions import get_csrf_token

no_cache = 1


def get_context(context):
    context.no_cache = 1
    context.key = frappe.form_dict.get("key") or ""
    context.signed_in = frappe.session.user != "Guest"
    context.csrf_token = get_csrf_token()

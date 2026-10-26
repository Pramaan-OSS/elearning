import frappe
from frappe.sessions import get_csrf_token

no_cache = 1


def get_context(context):
    context.no_cache = 1
    context.csrf_token = get_csrf_token()

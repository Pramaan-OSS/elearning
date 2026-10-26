"""Local password sign-in, using the application's retained session backend."""
import frappe
from frappe.sessions import get_csrf_token

no_cache = 1


def get_context(context):
    context.no_cache = 1
    context.title = "Sign in to eLearning"
    from frappe.website.utils import is_signup_disabled
    settings = frappe.get_single("LMS Settings")
    context.signup_enabled = not settings.disable_signup and not is_signup_disabled()
    context.user_category = settings.user_category
    context.signup_consent = frappe.utils.sanitize_html(settings.custom_signup_content or "")
    context.csrf_token = get_csrf_token()
    from lms.integrations.social import providers
    context.social_providers = providers()
    if frappe.session.user != "Guest":
        frappe.local.flags.redirect_location = "/lms"
        raise frappe.Redirect

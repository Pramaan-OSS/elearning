"""Production server entry point for this installation's single local site."""
import os

import frappe.app

# Match the site's explicit selection in the development server, including
# local asset and public file handling. Private files still use signed sessions.
frappe.app._site = os.environ["ELEARNING_SITE_NAME"]
application = frappe.app.application_with_statics()

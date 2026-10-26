"""Licensed photo search; source credits are intentional attribution."""
from urllib.parse import urlparse

import frappe
from frappe import _

from lms.pramaan import PramaanClient, PramaanError


@frappe.whitelist(methods=["POST"])
def search(query: str, page: int = 1):
    if frappe.session.user == "Guest":
        frappe.throw(_("Sign in to choose a cover image."), frappe.PermissionError)
    if not query.strip() or len(query) > 300 or not 1 <= int(page) <= 10000:
        frappe.throw(_("Enter photo keywords and a valid page."))
    try:
        result = PramaanClient().call("media.stock-photos.search", {"query": query.strip(), "page": int(page), "limit": 10})
        for row in result["results"]:
            for field in ("url", "previewUrl", "authorUrl", "sourceUrl", "licenceUrl", "sourceCreditUrl"):
                address = urlparse(row[field])
                if address.scheme != "https" or not address.hostname or address.username or address.password:
                    raise PramaanError("invalid_response")
        return result
    except (KeyError, TypeError):
        frappe.throw(_("Photo search returned incomplete data. Try again later."))
    except PramaanError as error:
        frappe.throw(str(error))

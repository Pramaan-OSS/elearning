import frappe
from frappe import _
from frappe.utils import flt

from lms.lms.utils import (
	complete_enrollment,
	get_lms_route,
	get_order_summary,
)


def client():
	from lms.pramaan import PramaanClient

	return PramaanClient()


def to_minor_units(amount: float, currency: str) -> int:
	"""A whole number in the currency's smallest unit (cents, paise)."""
	zero_decimal = {"bhd", "iqd", "jod", "kwd", "lyd", "omr", "tnd"}
	exponent = 3 if currency.lower() in zero_decimal else 2
	return int((flt(amount, exponent) + 1e-9) * (10**exponent))


@frappe.whitelist()
def get_payment_link(
	doctype: str,
	docname: str,
	address: dict,
	payment_for_certificate: int,
	coupon_code: str | None = None,
	country: str | None = None,
):
	address = frappe._dict(address)
	redirect_to = get_redirect_url(doctype, docname, payment_for_certificate)

	details = frappe._dict(get_order_summary(doctype, docname, coupon=coupon_code, country=country))
	title = details.title
	currency = details.currency
	original_amount = details.original_amount
	discount_amount = details.get("discount_amount", 0)
	gst_amount = details.get("gst_applied", 0)
	amount = original_amount - discount_amount
	amount_with_gst = get_amount_with_gst(amount, gst_amount)
	coupon = details.get("coupon")
	total_amount = amount_with_gst if amount_with_gst else amount

	# Checkout is reachable from a stale tab or the back button. Paying again for
	# access the learner already has would charge them twice, count another
	# coupon redemption, and grant nothing. The billing details they typed are
	# still worth keeping.
	if already_has_access(doctype, docname, payment_for_certificate):
		save_address(address)
		return redirect_to

	payment = record_payment(
		address,
		doctype,
		docname,
		amount,
		original_amount,
		currency,
		amount_with_gst,
		discount_amount,
		payment_for_certificate,
		coupon_code,
		coupon,
	)

	if total_amount <= 0:
		mark_payment_free(payment.name, doctype, docname)
		return redirect_to

	from lms.pramaan import PramaanError

	app_base = frappe.utils.get_url().rstrip("/")
	success_url = f"{app_base}{get_lms_route('billing')}/{doctype.split(' ')[-1].lower()}/{docname}?payment={payment.name}"
	cancel_url = f"{app_base}{redirect_to}"

	# The checkout lives on the platform: the learner pays on its hosted page,
	# the app stores the reference and confirms on return.
	try:
		checkout = client().call(
			"payments.checkout.create",
			{
				"lineItems": [
					{
						"name": f"{title} ({docname})",
						"amount": to_minor_units(total_amount, currency),
						"currency": currency.lower(),
						"quantity": 1,
					}
				],
				"successUrl": success_url,
				"cancelUrl": cancel_url,
				"customerEmail": frappe.session.user,
				"mode": "payment",
			},
			idempotency_key=payment.name,
		)
	except PramaanError as error:
		frappe.throw(_(str(error)))

	frappe.db.set_value(
		"LMS Payment", payment.name, {"checkout_ref": checkout.get("ref") or ""}
	)
	return checkout.get("checkoutUrl") or ""


def mark_payment_free(payment: str, doctype: str, docname: str):
	frappe.db.set_value("LMS Payment", payment, "payment_received", 1)
	complete_enrollment(payment, doctype, docname)


@frappe.whitelist()
def confirm_checkout(payment: str):
	"""Confirm a checkout the learner returned from.

	Reads the platform's own state: only a confirmed capture completes the
	enrollment. Anything else leaves the payment open, with the state to retry
	later. Never retries a request on its own.
	"""
	from lms.pramaan import PramaanError

	payment_doc = frappe.db.get_value(
		"LMS Payment",
		payment,
		["name", "checkout_ref", "payment_received", "payment_for_document_type",
		 "payment_for_document", "member"],
		as_dict=True,
	)
	if not payment_doc:
		frappe.throw(_("We could not find your payment record. Please contact the administrator."))
	if payment_doc.member != frappe.session.user:
		frappe.throw(_("We could not find your payment record. Please contact the administrator."), frappe.PermissionError)
	if payment_doc.payment_received:
		return {"paid": True, "redirect_to": get_redirect_url(
			payment_doc.payment_for_document_type, payment_doc.payment_for_document, 0)}

	if not payment_doc.checkout_ref:
		frappe.throw(_("This payment was never started. Begin the payment again."))

	try:
		result = client().call("payments.checkout.get", {"ref": payment_doc.checkout_ref})
	except PramaanError as error:
		frappe.throw(_(str(error)))

	status = result.get("status")
	if status == "paid":
		from lms.lms.utils import mark_checkout_paid

		payments = result.get("payments") or []
		if mark_checkout_paid(payment_doc.name, (payments[0] or {}).get("ref", "") if payments else ""):
			complete_enrollment(payment_doc.name, payment_doc.payment_for_document_type,
				payment_doc.payment_for_document)
		else:
			return {"paid": False, "status": "unknown"}
		return {"paid": True, "redirect_to": get_redirect_url(
			payment_doc.payment_for_document_type, payment_doc.payment_for_document, 0)}
	if status in {"unknown", "unpaid", "active", "pending"}:
		return {"paid": False, "status": status}
	frappe.throw(
		_("The payment did not go through ({0}). Start again or try later.").format(status)
	)


def already_has_access(doctype: str, docname: str, payment_for_certificate: int) -> bool:
	member = frappe.session.user

	if int(payment_for_certificate):
		return bool(
			frappe.db.get_value(
				"LMS Enrollment", {"member": member, "course": docname}, "purchased_certificate"
			)
		)

	if doctype == "LMS Course":
		return bool(frappe.db.exists("LMS Enrollment", {"member": member, "course": docname}))

	return bool(frappe.db.exists("LMS Batch Enrollment", {"member": member, "batch": docname}))


def get_amount_with_gst(amount: float, gst_amount: float) -> float:
	amount_with_gst = 0
	if gst_amount:
		amount_with_gst = amount + gst_amount

	return amount_with_gst


def record_payment(
	address: dict,
	doctype: str,
	docname: str,
	amount: float,
	original_amount: float,
	currency: str,
	amount_with_gst: float = 0,
	discount_amount: float = 0,
	payment_for_certificate: int = 0,
	coupon_code: str | None = None,
	coupon: str | None = None,
):
	address = frappe._dict(address)
	address_name = save_address(address)

	payment_doc = frappe.new_doc("LMS Payment")
	payment_doc.update(
		{
			"member": frappe.session.user,
			"billing_name": address.billing_name,
			"address": address_name,
			"amount": amount,
			"currency": currency,
			"discount_amount": discount_amount,
			"amount_with_gst": amount_with_gst,
			"gstin": address.gstin,
			"pan": address.pan,
			"source": address.source,
			"payment_for_document_type": doctype,
			"payment_for_document": docname,
			"payment_for_certificate": payment_for_certificate,
			"member_consent": address.member_consent,
		}
	)
	if coupon_code:
		payment_doc.update(
			{
				"coupon": coupon,
				"coupon_code": coupon_code,
				"discount_amount": discount_amount,
				"original_amount": original_amount,
			}
		)

	payment_doc.save(ignore_permissions=True)
	return payment_doc


def get_redirect_url(doctype: str, docname: str, payment_for_certificate: int) -> str:
	if int(payment_for_certificate):
		return get_lms_route(f"courses/{docname}/certification")
	elif doctype == "LMS Course":
		return get_lms_route(f"courses/{docname}")
	else:
		return get_lms_route(f"batches/{docname}")


def save_address(address: dict) -> str:
	filters = {"email_id": frappe.session.user}
	exists = frappe.db.exists("Address", filters)
	if exists:
		address_doc = frappe.get_last_doc("Address", filters=filters)
	else:
		address_doc = frappe.new_doc("Address")

	address_doc.update(address)
	address_doc.update(
		{
			"address_title": frappe.db.get_value("User", frappe.session.user, "full_name"),
			"address_type": "Billing",
			"is_primary_address": 1,
			"email_id": frappe.session.user,
		}
	)
	address_doc.save(ignore_permissions=True)
	return address_doc.name

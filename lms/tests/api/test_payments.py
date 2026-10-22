# Copyright (c) 2023, Frappe and Contributors
# See license.txt

from unittest.mock import patch

import frappe

from lms.lms import payments as payments_module
from lms.lms.test_helpers import BaseTestUtils

BILLING_ADDRESS = {
	"billing_name": "Test Buyer",
	"address_line1": "1 Test Street",
	"city": "Test City",
	"country": "India",
	"pincode": "560001",
	"source": "Website",
	"member_consent": 1,
}


class FakeCheckout:
	"""In-memory fake of the platform's checkout calls."""

	def __init__(self):
		self.calls = []
		self.status = "unpaid"

	def call(self, capability, inputs, idempotency_key=None, max_polls=60):
		self.calls.append((capability, inputs, idempotency_key))
		if capability == "payments.checkout.create":
			return {
				"ref": idempotency_key,
				"checkoutUrl": f"https://pay.example/c/{idempotency_key}",
				"expiresAt": "",
			}
		if capability == "payments.checkout.get":
			if self.status == "paid":
				return {"status": "paid", "payments": [{"ref": "pay_ref_1"}]}
			return {"status": self.status, "payments": []}
		raise AssertionError(f"unexpected capability {capability}")


class TestCheckout(BaseTestUtils):
	"""Paid enrollments go through the platform's hosted checkout: the app
	stores the checkout reference and confirms on return."""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		hash = frappe.generate_hash(length=6)
		cls.instructor = cls._create_user(
			f"payinstr-{hash}@example.com", "Ina", "Instructor", ["Course Creator"]
		)
		cls.course = cls._create_course(title=f"Paid Payments Course {hash}", instructor=cls.instructor.email)
		cls.course.db_set({"paid_course": 1, "course_price": 500, "currency": "INR"}, update_modified=False)

	def setUp(self):
		super().setUp()
		self.pramaan = FakeCheckout()
		patcher = patch("lms.lms.payments.client", return_value=self.pramaan)
		patcher.start()
		self.addCleanup(patcher.stop)

	def _buy_course(self):
		return payments_module.get_payment_link(
			doctype="LMS Course",
			docname=self.course.name,
			address=BILLING_ADDRESS,
			payment_for_certificate=0,
		)

	def _confirm(self, payment_name):
		from lms.lms.payments import confirm_checkout

		return confirm_checkout(payment_name)

	def _payment(self):
		return frappe.get_last_doc("LMS Payment", filters={
			"member": frappe.session.user,
			"payment_for_document_type": "LMS Course",
			"payment_for_document": self.course.name,
		})

	def _is_enrolled(self):
		return bool(
			frappe.db.exists(
				"LMS Enrollment", {"member": frappe.session.user, "course": self.course.name}
			)
		)

	def test_the_checkout_is_created_on_the_platform(self):
		checkout_url = self._buy_course()

		self.assertTrue(checkout_url.startswith("https://pay.example/c/"))
		create = next(c for c in self.pramaan.calls if c[0] == "payments.checkout.create")
		item = create[1]["lineItems"][0]
		# 500 rupees arrive as whole paise, in the currency's lowercase code.
		self.assertEqual(item["amount"], 50000)
		self.assertEqual(item["currency"], "inr")
		self.assertTrue(create[2])

	def test_the_checkout_reference_is_stored_on_the_payment(self):
		self._buy_course()

		payment = self._payment()
		self.assertTrue(payment.checkout_ref)
		self.assertEqual(payment.payment_received, 0)
		self.assertFalse(self._is_enrolled())

	def test_a_confirmed_checkout_enrolls_the_learner(self):
		self._buy_course()
		payment = self._payment()
		self.pramaan.status = "paid"

		result = self._confirm(payment.name)

		self.assertTrue(result["paid"])
		self.assertTrue(self._is_enrolled())
		self.assertEqual(frappe.db.get_value("LMS Payment", payment.name, "payment_id"), "pay_ref_1")

	def test_an_unpaid_checkout_leaves_the_payment_open(self):
		self._buy_course()
		payment = self._payment()
		self.pramaan.status = "unpaid"

		result = self._confirm(payment.name)

		self.assertFalse(result["paid"])
		self.assertFalse(self._is_enrolled())
		self.assertEqual(payment.payment_received, 0)

	def test_an_unknown_checkout_state_is_never_treated_as_payment(self):
		self._buy_course()
		payment = self._payment()
		self.pramaan.status = "unknown"

		result = self._confirm(payment.name)

		self.assertFalse(result["paid"])
		self.assertFalse(self._is_enrolled())

	def test_confirming_twice_credits_once(self):
		self._buy_course()
		payment = self._payment()
		self.pramaan.status = "paid"

		self._confirm(payment.name)
		# The second confirm re-reads the row: already received, nothing to do.
		result = self._confirm(payment.name)

		self.assertTrue(result["paid"])
		self.assertEqual(
			frappe.db.count("LMS Enrollment", {"member": frappe.session.user, "course": self.course.name}),
			1,
		)

	def test_one_capture_cannot_confirm_two_local_payments(self):
		self._buy_course()
		first = self._payment()
		self._buy_course()
		second = self._payment()
		self.pramaan.status = "paid"
		self.assertTrue(self._confirm(first.name)["paid"])
		self.assertFalse(self._confirm(second.name)["paid"])
		self.assertEqual(frappe.db.get_value("LMS Payment", second.name, "payment_received"), 0)

	def test_a_learner_cannot_confirm_someone_elses_payment(self):
		self._buy_course()
		payment = self._payment()
		other = self._create_user(
			f"payother-{frappe.generate_hash(length=6)}@example.com", "Other", "Buyer", ["LMS Student"]
		)

		frappe.set_user(other.name)
		self.addCleanup(frappe.set_user, "Administrator")
		with self.assertRaises(frappe.PermissionError):
			self._confirm(payment.name)

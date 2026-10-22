import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_days, nowdate

from lms.lms.api import delete_batch
from lms.lms.utils import get_instructors


class TestBatchDeletion(IntegrationTestCase):
	def test_reusing_a_deleted_batch_name_has_no_old_instructors(self):
		previous_user = frappe.session.user
		self.addCleanup(frappe.set_user, previous_user)
		frappe.set_user("Administrator")
		title = f"Batch reuse {frappe.generate_hash(length=8)}"

		def create_batch():
			return frappe.get_doc({
				"doctype": "LMS Batch", "title": title,
				"description": "Local deletion check", "batch_details": "<p>Local deletion check</p>",
				"start_date": nowdate(), "end_date": add_days(nowdate(), 1),
				"start_time": "09:00:00", "end_time": "10:00:00", "timezone": "UTC",
				"instructors": [{"instructor": "Administrator"}],
			}).insert()

		first = create_batch()
		delete_batch(first.name)
		self.assertEqual(frappe.db.count("Course Instructor", {
			"parent": first.name, "parenttype": "LMS Batch",
		}), 0)
		second = create_batch()
		self.assertEqual(second.name, first.name)
		self.assertEqual(len(get_instructors("LMS Batch", second.name)), 1)

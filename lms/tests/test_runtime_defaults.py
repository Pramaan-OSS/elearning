import frappe
from frappe.tests import IntegrationTestCase

from lms.install import ensure_local_settings


class TestRuntimeDefaults(IntegrationTestCase):
	def tearDown(self):
		frappe.clear_document_cache("System Settings", "System Settings")
		super().tearDown()

	def test_empty_preferences_are_ready_to_save(self):
		frappe.db.set_single_value("System Settings", {"language": "", "time_zone": ""})
		ensure_local_settings()
		settings = frappe.get_single("System Settings")
		self.assertEqual(settings.language, "en")
		self.assertEqual(settings.time_zone, "UTC")
		settings.password_reset_limit = 5
		settings.save(ignore_permissions=True)

	def test_existing_preferences_survive_repeated_setup(self):
		settings = frappe.get_single("System Settings")
		settings.language = "en"
		settings.time_zone = "Europe/London"
		settings.save(ignore_permissions=True)
		ensure_local_settings()
		ensure_local_settings()
		self.assertEqual(frappe.db.get_single_value("System Settings", "time_zone"), "Europe/London")

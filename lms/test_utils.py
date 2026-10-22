"""Test-harness setup: the local boundaries must be in place before any
document save in the runner, where no request hook has run yet."""
import frappe


def before_tests():
	from lms.integrations.configuration import install_local_boundaries

	install_local_boundaries()
	from lms.integrations.pramaan_mail import install_transport

	install_transport()
	frappe.db.commit()

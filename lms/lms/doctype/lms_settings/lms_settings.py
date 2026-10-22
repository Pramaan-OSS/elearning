# Copyright (c) 2021, FOSS United and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, get_url_to_list, validate_email_address, validate_url

from lms.lms.sidebar import validate_sidebar_items


class LMSSettings(Document):
	def validate(self):
		self.validate_calendar_settings()
		self.validate_signup()
		self.validate_contact_us_details()
		self.validate_lesson_dwell_time()
		validate_sidebar_items(self)

	def validate_lesson_dwell_time(self):
		if cint(self.lesson_dwell_time) < 1:
			frappe.throw(_("Lesson Dwell Time must be at least 1 second."))

	def validate_calendar_settings(self):
		if self.send_calendar_invite_for_evaluations and not self.calendar_inbox:
			frappe.throw(_("Choose the calendar inbox in Connected Services to send evaluation invites."))

	def validate_signup(self):
		if self.has_value_changed("disable_signup"):
			frappe.db.set_single_value("Website Settings", "disable_signup", self.disable_signup)

	def validate_contact_us_details(self):
		if self.contact_us_email and not validate_email_address(self.contact_us_email):
			frappe.throw(_("Please enter a valid Contact Us Email."))
		if self.contact_us_url and not validate_url(self.contact_us_url, True, ["http", "https"]):
			frappe.throw(_("Please enter a valid Contact Us URL."))


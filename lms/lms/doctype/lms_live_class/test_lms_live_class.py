# Copyright (c) 2023, Frappe and Contributors
# See license.txt

from unittest.mock import MagicMock, patch

import frappe
from frappe.utils import add_days, nowdate

from lms.lms.test_helpers import BaseTestUtils


class FakePramaan:
	"""In-memory fake of the single client for live-class flows."""

	def __init__(self):
		self.calls = []
		self.rooms = {}
		self.events = {}
		self.fail_rooms = False
		self.fail_events = False
		self._room_seq = 0
		self._event_seq = 0

	def call(self, capability, inputs, idempotency_key=None, max_polls=60):
		self.calls.append((capability, inputs, idempotency_key))
		if capability == "meetings.room.create":
			if self.fail_rooms:
				from lms.pramaan import PramaanError

				raise PramaanError("unavailable")
			self._room_seq += 1
			ref = f"room/{self._room_seq}"
			self.rooms[ref] = inputs
			return {
				"ref": ref,
				"joinUrl": f"https://meet.example/j/{self._room_seq}",
				"hostUrl": f"https://meet.example/h/{self._room_seq}",
			}
		if capability == "meetings.room.delete":
			self.rooms.pop(inputs.get("ref"), None)
			return {"deleted": True}
		if capability == "calendar.event.create":
			if self.fail_events:
				from lms.pramaan import PramaanError

				raise PramaanError("unavailable")
			self._event_seq += 1
			ref = f"event/{self._event_seq}"
			self.events[ref] = inputs
			return {"ref": ref}
		if capability == "calendar.event.update":
			if self.fail_events:
				from lms.pramaan import PramaanError

				raise PramaanError("unavailable")
			self.events[inputs["ref"]] = {**self.events.get(inputs["ref"], {}), **inputs}
			return {"ref": inputs["ref"]}
		if capability == "calendar.event.delete":
			self.events.pop(inputs.get("ref"), None)
			return {"deleted": True}
		raise AssertionError(f"unexpected capability {capability}")


class TestLMSLiveClass(BaseTestUtils):
	"""Tests for LMS Live Class over the platform's room and calendar calls."""

	fake = None

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.admin = cls._create_user(
			"frappe@example.com", "Eval", "Admin", ["Moderator", "Course Creator", "Batch Evaluator"]
		)
		cls.course = cls._create_course()
		cls._create_evaluator()
		cls.batch = cls._create_batch(cls.course.name)
		frappe.db.set_single_value("LMS Settings", "meeting_app", "meetapp")

	@classmethod
	def tearDownClass(cls):
		frappe.db.set_single_value("LMS Settings", "meeting_app", "")
		frappe.db.set_single_value("LMS Settings", "calendar_inbox", "")
		super().tearDownClass()

	def setUp(self):
		super().setUp()
		type(self).fake = FakePramaan()
		patch("lms.integrations.conferencing.client", return_value=self.fake).start()
		patch("lms.lms.doctype.lms_live_class.lms_live_class.client", return_value=self.fake).start()
		self.addCleanup(patch.stopall)
		self.batch.reload()

	def test_meeting_start_keeps_the_selected_zone_offset(self):
		from lms.integrations.conferencing import meeting_start

		self.assertEqual(meeting_start("2026-07-01", "15:00", "Europe/London"), "2026-07-01T15:00:00+01:00")
		self.assertEqual(meeting_start("2026-12-01", "15:00", "Europe/London"), "2026-12-01T15:00:00+00:00")
		self.assertEqual(meeting_start("2026-07-01", "15:00", "Asia/Kolkata"), "2026-07-01T15:00:00+05:30")

	def _create_live_class(self, **kwargs):
		data = {
			"doctype": "LMS Live Class",
			"title": f"Test Class {frappe.generate_hash(length=6)}",
			"host": "Administrator",
			"date": add_days(nowdate(), 1),
			"time": "10:00:00",
			"duration": 60,
			"timezone": "Asia/Kolkata",
			"batch_name": self.batch.name,
			"conferencing_provider": "meetapp",
		}
		data.update(kwargs)
		live_class = frappe.get_doc(data)
		live_class.insert(ignore_permissions=True)
		return live_class

	def _student(self):
		email = f"live-class-student-{frappe.generate_hash(length=6)}@example.com"
		self._create_user(email, "Live", "Student", ["LMS Student"])
		return email

	def _event_guests(self, live_class):
		return frappe.get_all(
			"Event Participants", {"parent": live_class.event, "parenttype": "Event"}, pluck="email"
		)

	def _invite_state(self, live_class):
		return frappe.db.get_value(
			"LMS Live Class", live_class.name, ["invite_status", "invite_attempts"], as_dict=True
		)

	def test_the_room_is_created_on_the_platform_and_stored(self):
		from lms.lms.doctype.lms_batch.lms_batch import create_live_class

		live_class = create_live_class(
			batch_name=self.batch.name,
			title="Platform class",
			duration=60,
			date=add_days(nowdate(), 1),
			time="10:00:00",
			timezone="Asia/Kolkata",
		)
		self.assertEqual(live_class.meeting_id, "room/1")
		self.assertEqual(live_class.join_url, "https://meet.example/j/1")
		create_call = self.fake.calls[0]
		self.assertEqual(create_call[0], "meetings.room.create")
		self.assertEqual(create_call[1]["app"], "meetapp")
		self.assertTrue(create_call[1]["endUserRef"])
		self.assertTrue(create_call[2])
		from datetime import datetime
		self.assertIsNotNone(datetime.fromisoformat(create_call[1]["start"]).utcoffset())

	def test_a_class_without_a_meeting_app_is_refused_before_any_call(self):
		from lms.lms.doctype.lms_batch.lms_batch import create_live_class

		frappe.db.set_single_value("LMS Settings", "meeting_app", "")
		self.addCleanup(frappe.db.set_single_value, "LMS Settings", "meeting_app", "meetapp")

		with self.assertRaises(frappe.ValidationError):
			create_live_class(
				batch_name=self.batch.name,
				title="No app",
				duration=60,
				date=add_days(nowdate(), 1),
				time="10:00:00",
				timezone="Asia/Kolkata",
			)
		self.assertEqual(self.fake.calls, [])

	def test_a_room_is_deleted_when_its_class_fails_to_save(self):
		from lms.lms.doctype.lms_batch.lms_batch import create_live_class
		from lms.lms.doctype.lms_live_class.lms_live_class import LMSLiveClass

		with patch.object(
			LMSLiveClass, "create_calendar_event", side_effect=frappe.ValidationError("broken")
		):
			with self.assertRaises(frappe.ValidationError):
				create_live_class(
					batch_name=self.batch.name,
					title="Unsaved class",
					duration=60,
					date=add_days(nowdate(), 1),
					time="10:00:00",
					timezone="Asia/Kolkata",
				)
		self.assertNotIn("room/1", self.fake.rooms)

	def test_a_class_with_an_inbox_puts_the_hosts_on_the_calendar(self):
		frappe.db.set_single_value("LMS Settings", "calendar_inbox", "inbox/main")
		self.addCleanup(frappe.db.set_single_value, "LMS Settings", "calendar_inbox", "")

		live_class = self._create_live_class()
		live_class.reload()

		self.assertTrue(live_class.event)
		self.assertEqual(live_class.platform_event_ref, "event/1")
		event_call = next(c for c in self.fake.calls if c[0] == "calendar.event.create")
		attendees = [row["email"] for row in event_call[1]["attendees"]]
		self.assertIn("Administrator", attendees)
		self.assertTrue(event_call[1]["sendInvites"])

	def test_a_class_without_an_inbox_is_left_for_the_scheduler(self):
		live_class = self._create_live_class()
		live_class.reload()

		self.assertFalse(any(c[0] == "calendar.event.create" for c in self.fake.calls))
		self.assertEqual(self._invite_state(live_class).invite_status, "Retrying")

	def test_a_late_learner_is_invited_through_the_platform_event(self):
		frappe.db.set_single_value("LMS Settings", "calendar_inbox", "inbox/main")
		self.addCleanup(frappe.db.set_single_value, "LMS Settings", "calendar_inbox", "")

		student = self._student()
		live_class = self._create_live_class()
		live_class.reload()

		self._create_batch_enrollment(student, self.batch.name)

		self.assertIn(student, self._event_guests(live_class))
		updates = [c for c in self.fake.calls if c[0] == "calendar.event.update"]
		self.assertTrue(updates)
		emails = [row["email"] for row in updates[-1][1]["attendees"]]
		self.assertIn(student, emails)

	def test_a_failed_invite_is_retried_and_then_recoverable(self):
		from lms.lms.doctype.lms_live_class.lms_live_class import retry_pending_invites

		frappe.db.set_single_value("LMS Settings", "calendar_inbox", "inbox/main")
		self.addCleanup(frappe.db.set_single_value, "LMS Settings", "calendar_inbox", "")

		student = self._student()
		live_class = self._create_live_class()
		live_class.reload()
		self.fake.fail_events = True

		self._create_batch_enrollment(student, self.batch.name)
		self.assertEqual(self._invite_state(live_class).invite_status, "Retrying")

		self.fake.fail_events = False
		retry_pending_invites()

		self.assertIn(student, self._event_guests(live_class))
		self.assertEqual(self._invite_state(live_class).invite_status, "")

	def test_enrollments_during_an_outage_do_not_use_up_the_tries(self):
		frappe.db.set_single_value("LMS Settings", "calendar_inbox", "inbox/main")
		self.addCleanup(frappe.db.set_single_value, "LMS Settings", "calendar_inbox", "")

		self._create_batch_enrollment(self._student(), self.batch.name)
		live_class = self._create_live_class()
		live_class.reload()
		self.fake.fail_events = True

		for _ in range(6):
			self._create_batch_enrollment(self._student(), self.batch.name)

		self.assertEqual(
			self._invite_state(live_class), {"invite_status": "Retrying", "invite_attempts": 0}
		)

	def test_a_learner_cannot_retry_a_class_invite(self):
		from lms.lms.doctype.lms_live_class.lms_live_class import retry_invites

		live_class = self._create_live_class()
		student = self._student()
		self._create_batch_enrollment(student, self.batch.name)

		frappe.set_user(student)
		self.addCleanup(frappe.set_user, "Administrator")
		with self.assertRaises(frappe.PermissionError):
			retry_invites(live_class.name)

	def test_updating_a_live_class_updates_its_events(self):
		frappe.db.set_single_value("LMS Settings", "calendar_inbox", "inbox/main")
		self.addCleanup(frappe.db.set_single_value, "LMS Settings", "calendar_inbox", "")

		live_class = self._create_live_class()
		live_class.reload()
		event_name = live_class.event
		self.fake.calls.clear()

		live_class.time = "15:00:00"
		# nosemgrep: lms-unjustified-ignore-permissions - test fixture setup
		live_class.save(ignore_permissions=True)

		event = frappe.get_doc("Event", event_name)
		self.assertIn("15:00", str(event.starts_on))
		updates = [c for c in self.fake.calls if c[0] == "calendar.event.update"]
		self.assertTrue(updates)
		self.assertEqual(updates[-1][1]["start"], f"{live_class.date} 15:00:00")

	def test_deleting_a_class_deletes_its_events(self):
		frappe.db.set_single_value("LMS Settings", "calendar_inbox", "inbox/main")
		self.addCleanup(frappe.db.set_single_value, "LMS Settings", "calendar_inbox", "")

		live_class = self._create_live_class()
		live_class.reload()
		event_name = live_class.event

		frappe.delete_doc("LMS Live Class", live_class.name, force=True)

		self.assertFalse(frappe.db.exists("Event", event_name))
		self.assertNotIn(live_class.platform_event_ref, self.fake.events)

	def test_another_moderator_can_delete_a_class_and_its_private_event(self):
		"""The private event belongs to whoever scheduled the class, not to the deleter."""
		live_class = self._create_live_class()
		live_class.reload()
		event = live_class.event
		moderator = self._create_user(
			f"live-class-mod-{frappe.generate_hash(length=6)}@example.com",
			"Live",
			"Moderator",
			["Moderator"],
			user_type="System User",
		)

		frappe.set_user(moderator.name)
		try:
			frappe.delete_doc("LMS Live Class", live_class.name)
		finally:
			frappe.set_user("Administrator")

		self.assertFalse(frappe.db.exists("Event", event))

	def test_the_live_class_event_is_private_without_a_reminder(self):
		"""A public event lands in every staff member's daily event digest."""
		live_class = self._create_live_class()
		live_class.reload()

		event = frappe.db.get_value("Event", live_class.event, ["event_type", "send_reminder"], as_dict=1)
		self.assertEqual(event.event_type, "Private")
		self.assertEqual(event.send_reminder, 0)

	def test_a_class_whose_event_was_deleted_stops_retrying(self):
		from lms.lms.doctype.lms_live_class.lms_live_class import send_learner_invites

		live_class = self._create_live_class()
		live_class.reload()
		frappe.db.set_value("LMS Live Class", live_class.name, "invite_status", "Retrying")
		frappe.db.delete("Event", live_class.event)

		self.assertTrue(send_learner_invites(live_class.name))
		self.assertEqual(self._invite_state(live_class).invite_status, "")

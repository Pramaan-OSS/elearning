# Copyright (c) 2023, Frappe and contributors
# For license information, please see license.txt

from datetime import timedelta

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.query_builder import Bracket
from frappe.utils import cint, format_date, format_time, generate_hash, get_datetime, nowdate
from pypika.terms import LiteralValue

from lms.integrations.conferencing import client, get_site_inbox
from lms.lms.permissions import (
	authored_batch_condition,
	can_author_batch,
	can_instruct_batch,
	is_site_administrator,
)
from lms.pramaan import PramaanError


class LMSLiveClass(Document):
	def after_insert(self):
		self.create_calendar_event()

	def on_update(self):
		if not self.event:
			return

		if (
			not self.has_value_changed("date")
			and not self.has_value_changed("time")
			and not self.has_value_changed("duration")
			and not self.has_value_changed("title")
		):
			return

		self._update_linked_event()

	def after_delete(self):
		# The event is private, so only its creator may delete it directly. Whoever may
		# delete the live class may remove its event with it, as _update_linked_event
		# already saves it on their behalf.
		if self.event:
			# nosemgrep: lms-unjustified-ignore-permissions - the private event's owner alone may delete it; deleting the class was already authorised
			frappe.delete_doc("Event", self.event, force=True, ignore_permissions=True)
		if self.platform_event_ref:
			delete_platform_event(self.platform_event_ref)

	def get_hosts(self):
		"""Whoever scheduled the class, its host, and the batch's instructors."""
		hosts = {frappe.session.user, *get_batch_instructors(self.batch_name)}
		if self.host:
			hosts.add(self.host)
		return list(hosts)

	def build_event_description(self):
		description = f"A Live Class has been scheduled on {format_date(self.date, 'medium')} at {format_time(self.time, 'hh:mm a')}."
		if self.join_url:
			description += f" Click on this link to join. {self.join_url}. \n\n"
		if self.description:
			description += f"{self.description}"
		return description

	def _update_linked_event(self):
		event = frappe.get_doc("Event", self.event)
		start = f"{self.date} {self.time}"

		event.subject = f"Live Class on {self.title}"
		event.starts_on = start
		event.ends_on = get_datetime(start) + timedelta(minutes=cint(self.duration))
		event.description = self.build_event_description()

		event.save(ignore_permissions=True)
		update_platform_event(self)

	def create_calendar_event(self):
		# Learners are invited so the class reaches their calendar. The platform
		# event carries the hosts at first; the learners are added right after, so
		# a burst of enrollments never races the class's creation.
		event = self.create_event()
		frappe.db.set_value(self.doctype, self.name, "event", event.name)
		add_event_participants(event, self.get_hosts())
		create_platform_event(self)
		send_learner_invites(self.name)

	def create_event(self):
		start = f"{self.date} {self.time}"

		event = frappe.new_doc("Event")
		event.update(
			{
				"doctype": "Event",
				"subject": f"Live Class on {self.title}",
				# Private, with no Frappe reminder: a public event lands in every staff
				# member's daily event digest, and LMS sends its own class reminders.
				"event_type": "Private",
				"send_reminder": 0,
				"starts_on": start,
				"ends_on": get_datetime(start) + timedelta(minutes=cint(self.duration)),
			}
		)

		event.save()
		return event




def event_body(cls, attendees=None, send_invites=False):
	"""The platform event for a live class: wall-clock start and end, hosts
	first, then learners as they enroll."""
	start = f"{cls.date} {cls.time}"
	body = {
		"inbox": get_site_inbox(required=True),
		"title": f"Live Class on {cls.title}",
		"start": start,
		"end": get_datetime(start) + timedelta(minutes=cint(cls.duration)),
		"timezone": cls.timezone or None,
		"description": cls.build_event_description(),
		"sendInvites": send_invites,
	}
	if attendees:
		body["attendees"] = [{"email": email} for email in attendees]
	return {k: v for k, v in body.items() if v is not None}


def create_platform_event(cls):
	"""Put the class on the site's calendar so hosts get their invites.

	Nothing is hidden here: every attendee can see the others (the platform has
	no hidden-guest option yet). A failure leaves the class live and marked for
	the scheduler, which retries with the learners.
	"""
	if not get_site_inbox():
		set_invite_status(cls.name, "Retrying", 0)
		return
	try:
		event = client().call(
			"calendar.event.create",
			event_body(cls, attendees=cls.get_hosts(), send_invites=True),
			idempotency_key=generate_hash(),
		)
	except PramaanError as error:
		frappe.db.set_value(cls.doctype, cls.name, "platform_event_ref", "")
		frappe.log_error(
			title=f"Could not put live class {cls.name} on the calendar", message=str(error)
		)
		set_invite_status(cls.name, "Retrying", 0)
		return
	frappe.db.set_value(cls.doctype, cls.name, "platform_event_ref", event.get("ref") or "")


def update_platform_event(cls, attendees=None, send_invites=False):
	"""Mirror title, time and guest changes onto the platform event."""
	if not cls.platform_event_ref:
		return False
	try:
		client().call(
			"calendar.event.update",
			{"ref": cls.platform_event_ref, **event_body(cls, attendees=attendees, send_invites=send_invites)},
			idempotency_key=generate_hash(),
		)
	except PramaanError:
		frappe.log_error(title=f"Could not update the calendar event of live class {cls.name}")
		return False
	return True


def delete_platform_event(event_ref):
	"""Best effort: the class's own delete is the one to report."""
	try:
		client().call("calendar.event.delete", {"ref": event_ref}, idempotency_key=generate_hash())
	except PramaanError:
		frappe.log_error(title=f"Could not delete the calendar event {event_ref}")


def add_event_participants(event, emails):
	for email in emails:
		# nosemgrep: lms-unjustified-ignore-permissions - a self-enrolling learner has no create permission on Event Participants; the boundary is the enrollment
		frappe.get_doc(
			{
				"doctype": "Event Participants",
				"reference_doctype": "User",
				"reference_docname": email,
				"email": email,
				"parent": event.name,
				"parenttype": "Event",
				"parentfield": "event_participants",
			}
		).insert(ignore_permissions=True)


def invite_to_event(event, emails):
	"""Add guests and save the event, so Frappe pushes them to Google, which sends
	their invites. Adding the rows alone never reaches Google."""
	emails = list(emails)
	if not emails:
		return
	add_event_participants(event, emails)
	event.reload()
	# nosemgrep: lms-unjustified-ignore-permissions - the private event belongs to its creator; a self-enrolling learner's save only pushes the guest list
	event.save(ignore_permissions=True)


# Tries before the hosts are told: the one made with the class, then one per
# scheduler tick from retry_pending_invites.
MAX_INVITE_ATTEMPTS = 5


def send_learner_invites(live_class: str, count_attempt: bool = True) -> bool:
	"""Invite the batch's learners who are not on the class's invite yet. If the
	platform refuses, the class is marked Retrying and tried again on every
	scheduler tick;
	after MAX_INVITE_ATTEMPTS it is marked Failed, the hosts are told, and the
	class's Retry button takes over. Returns whether every learner is invited.

	An enrollment passes count_attempt=False, so a burst of them during a short
	outage leaves the class to the scheduler instead of using up its tries.

	Never raises, and muted: a failure must not undo the class or the enrollment
	that led here, and Frappe's own Google messages would otherwise reach
	whoever triggered it, which may be an enrolling learner."""
	# Locks the class, so two jobs for it cannot both see the same learners missing
	# and invite them twice; the second waits and finds them invited.
	frappe.db.get_value("LMS Live Class", live_class, "name", for_update=True)

	muted = frappe.flags.mute_messages
	frappe.flags.mute_messages = True
	try:
		invited = invite_missing_learners(live_class)
	except Exception:
		frappe.log_error(title=f"Could not invite learners to live class {live_class}")
		invited = False
	finally:
		frappe.flags.mute_messages = muted

	status, attempts = frappe.db.get_value("LMS Live Class", live_class, ["invite_status", "invite_attempts"])
	if invited:
		if status:
			set_invite_status(live_class, "", 0)
		return True

	attempts = cint(attempts) + (1 if count_attempt else 0)
	if status == "Failed":
		# Already reported. A later enrollment or a retry that fails again leaves it
		# for the Retry button rather than telling the hosts twice.
		set_invite_status(live_class, "Failed", attempts)
	elif attempts >= MAX_INVITE_ATTEMPTS and notified_hosts(live_class):
		set_invite_status(live_class, "Failed", attempts)
	else:
		# Also when the hosts could not be told: still Retrying, the next tick
		# tries the invites again and, failing, the notice.
		set_invite_status(live_class, "Retrying", attempts)
	return False


def notified_hosts(live_class: str) -> bool:
	"""Failed is set only once this succeeds: the scheduler never picks a Failed
	class up again, so a notice lost after it would never be sent."""
	frappe.db.savepoint("notify_hosts")
	try:
		notify_hosts_of_missing_invites(live_class)
	except Exception:
		# No half-sent notices left to be sent again with the next try.
		frappe.db.rollback(save_point="notify_hosts")
		frappe.log_error(title=f"Could not tell the hosts of live class {live_class} about its invites")
		return False
	return True


def invite_missing_learners(live_class: str) -> bool:
	event_name, batch = frappe.db.get_value("LMS Live Class", live_class, ["event", "batch_name"])
	# No event, or one deleted since: nothing to invite anyone to.
	if not event_name or not frappe.db.exists("Event", event_name):
		return True

	event = frappe.get_doc("Event", event_name)
	# An event from before this was Public, readable by any staff member and in
	# their event digests, so adding learners there would expose them.
	if event.event_type != "Private":
		return True

	invited = {guest.email for guest in event.event_participants}
	learners = frappe.get_all("LMS Batch Enrollment", {"batch": batch}, pluck="member")
	missing = [learner for learner in learners if learner not in invited]
	cls = frappe.get_doc("LMS Live Class", live_class)
	if not cls.platform_event_ref:
		# The platform event never happened (the platform was down, say). Make it
		# now, with the hosts and the missing learners together.
		if not get_site_inbox():
			return False
		create_platform_event(cls)
		cls.reload()
		if not cls.platform_event_ref:
			return False
		add_event_participants(event, cls.get_hosts())

	if not missing:
		return True

	# The full guest list rides every update: the platform replaces the
	# attendees, and invites go to the ones newly added.
	attendees = sorted(invited | set(missing))
	invited_ok = update_platform_event(cls, attendees=attendees, send_invites=True)
	if invited_ok:
		add_event_participants(event, missing)
	return invited_ok


def set_invite_status(live_class: str, status: str, attempts: int):
	frappe.db.set_value(
		"LMS Live Class",
		live_class,
		{"invite_status": status, "invite_attempts": attempts},
		update_modified=False,
	)


def notify_hosts_of_missing_invites(live_class: str):
	from frappe.desk.doctype.notification_log.notification_log import make_notification_logs

	from lms.lms.utils import get_lms_route

	cls = frappe.db.get_value(
		"LMS Live Class", live_class, ["title", "batch_name", "host", "owner"], as_dict=True
	)
	hosts = {cls.host, cls.owner, *get_batch_instructors(cls.batch_name)} - {None}
	notification = frappe._dict(
		{
			"subject": _("Learners haven't been invited to {0}").format(frappe.bold(cls.title)),
			"email_content": _(
				"Calendar didn't take their invites. Open the class and select Retry to send them."
			),
			"document_type": "LMS Live Class",
			"document_name": live_class,
			"type": "Alert",
			"link": get_lms_route(f"batches/{cls.batch_name}#classes"),
		}
	)
	make_notification_logs(notification, list(hosts))


def retry_pending_invites():
	"""Scheduled. Tries again for upcoming classes whose invites the platform has
	not taken yet."""
	classes = frappe.get_all(
		"LMS Live Class",
		{"invite_status": "Retrying", "date": [">=", nowdate()]},
		pluck="name",
	)
	for live_class in classes:
		# One class failing outside the calendar must not stop the others being retried.
		try:
			send_learner_invites(live_class)
		except Exception:
			frappe.log_error(title=f"Could not retry the invites of live class {live_class}")


@frappe.whitelist(methods=["POST"])
def retry_invites(live_class: str) -> bool:
	"""The Retry button on a class whose learners could not be invited."""
	frappe.get_doc("LMS Live Class", live_class).check_permission("write")
	return send_learner_invites(live_class)


def add_learner_to_live_classes(batch):
	"""Invite a learner who joins the batch to its upcoming live classes. In the
	background, after the enrollment commits: each class costs several Google
	calls, too slow to make inside the enrollment request. A job finding no one
	missing returns before calling Google, so a bulk import's later jobs are cheap."""
	classes = frappe.get_all(
		"LMS Live Class",
		{"batch_name": batch, "event": ["is", "set"], "date": [">=", nowdate()]},
		pluck="name",
	)
	for live_class in classes:
		frappe.enqueue(
			send_learner_invites,
			queue="short",
			enqueue_after_commit=True,
			now=frappe.flags.in_test,
			live_class=live_class,
			count_attempt=False,
		)


def get_batch_instructors(batch: str) -> list[str]:
	return frappe.get_all(
		"Course Instructor", {"parenttype": "LMS Batch", "parent": batch}, pluck="instructor"
	)


def send_live_class_reminder():
	classes = frappe.get_all(
		"LMS Live Class",
		{
			"date": nowdate(),
		},
		["name", "batch_name", "title", "date", "time"],
	)

	for live_class in classes:
		students = frappe.get_all(
			"LMS Batch Enrollment",
			{"batch": live_class.batch_name},
			["member", "member_name"],
		)
		for student in students:
			send_mail(live_class, student)


def send_mail(live_class, student):
	subject = _("Your class on {0} is today").format(live_class.title)
	template = "live_class_reminder"

	args = {
		"student_name": student.member_name,
		"title": live_class.title,
		"date": live_class.date,
		"time": live_class.time,
		"batch_name": live_class.batch_name,
	}

	frappe.sendmail(
		recipients=student.member,
		subject=subject,
		template=template,
		args=args,
		header=[_(f"Class Reminder: {live_class.title}"), "orange"],
	)


def has_permission(doc, ptype="read", user=None):
	user = user or frappe.session.user
	roles = frappe.get_roles(user)
	if "Moderator" in roles:
		return True

	if ptype not in ("read", "select", "print"):
		# Only the batch's instructors schedule and change its classes; a tagged
		# evaluator keeps read access below.
		if not can_instruct_batch(doc.batch_name, user=user):
			return False
		# Authorise the stored batch too, or a submitted batch_name moves the class.
		stored = None if doc.is_new() else frappe.db.get_value("LMS Live Class", doc.name, "batch_name")
		return not stored or can_instruct_batch(stored, user=user)

	# "Batch Evaluator" keeps its existing blanket read; any other tagged
	# instructor/evaluator (e.g. Course Creator) is scoped to their own batch.
	if "Batch Evaluator" in roles or can_author_batch(doc.batch_name, user=user):
		return True

	return frappe.db.exists(
		"LMS Batch Enrollment",
		{"batch": doc.batch_name, "member": user},
	)


def get_permission_query_conditions(user=None):
	"""List-read counterpart of has_permission above.

	has_permission is never consulted on a list or report query, so without this
	the enrolment check is enforced on the single-doc read and dropped on the
	list read — which is how every batch's host link was readable by any
	authenticated user.
	"""
	user = user or frappe.session.user
	if is_site_administrator(user):
		return ""

	roles = frappe.get_roles(user)
	if "Moderator" in roles or "Batch Evaluator" in roles:
		return ""

	live_class = frappe.qb.DocType("LMS Live Class")
	enrollment = frappe.qb.DocType("LMS Batch Enrollment")
	member = LiteralValue(frappe.db.escape(user))
	enrolled = frappe.qb.from_(enrollment).select(enrollment.batch).where(enrollment.member == member)
	condition = Bracket(
		live_class.batch_name.isin(enrolled) | authored_batch_condition(live_class.batch_name, user)
	)
	return condition.get_sql(with_namespace=True, quote_char="`" if frappe.db.db_type == "mariadb" else '"')

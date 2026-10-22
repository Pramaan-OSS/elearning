# Copyright (c) 2022, Frappe and contributors
# For license information, please see license.txt

from datetime import timedelta

import frappe
from frappe import _
from frappe.desk.doctype.notification_log.notification_log import make_notification_logs
from frappe.model.document import Document
from frappe.query_builder import Bracket
from frappe.utils import add_days, cint, generate_hash, get_time, nowdate
from pypika.terms import LiteralValue

from lms.integrations.conferencing import end_user_ref, get_meeting_app, meeting_start

from lms.lms.permissions import (
	administrable_assessment_names,
	authored_batch_condition,
	can_author_batch,
	can_instruct_batch,
	courses_authored_by,
	is_site_administrator,
)
from lms.lms.utils import (
	format_timezone,
	generate_slug,
	get_assignment_details,
	get_instructors,
	get_lesson_index,
	get_lesson_url,
	get_lms_route,
	get_quiz_details,
	guest_access_allowed,
)


class LMSBatch(Document):
	def validate(self):
		self._validate_mandatory()
		self.validate_added_assessments_and_courses()
		self.validate_seats_left()
		self.validate_batch_end_date()
		self.validate_batch_time()
		self.validate_duplicate_courses()
		self.validate_duplicate_instructors()
		self.validate_instructor_changes()
		self.validate_amount_and_currency()
		self.validate_duplicate_assessments()
		self.validate_timetable()
		self.validate_evaluation_end_date()

	def on_update(self):
		if self.has_value_changed("published") and self.published:
			frappe.enqueue(send_notification_for_published_batch, batch=self)

	def autoname(self):
		if not self.name and self.title:
			self.name = generate_slug(self.title, "LMS Batch")

	def validate_added_assessments_and_courses(self):
		"""A tagged Course Creator may add only assessments they administer and
		courses they author. Checked against rows ADDED vs the stored batch, so
		existing rows survive an edit made by someone else."""
		user = frappe.session.user
		roles = frappe.get_roles(user)
		if is_site_administrator(user) or "Moderator" in roles or "Batch Evaluator" in roles:
			return
		if self.is_new():
			return

		stored_assessments = {
			(row.assessment_type, row.assessment_name)
			for row in frappe.get_all(
				"LMS Assessment",
				filters={"parent": self.name},
				fields=["assessment_type", "assessment_name"],
			)
		}
		added_assessments = [
			row
			for row in self.assessment
			if (row.assessment_type, row.assessment_name) not in stored_assessments
		]
		self._validate_added_assessments(added_assessments, user)

		stored_courses = set(frappe.get_all("Batch Course", filters={"parent": self.name}, pluck="course"))
		added_courses = {row.course for row in self.courses if row.course not in stored_courses}
		self._validate_added_courses(added_courses, user)

	def _validate_added_assessments(self, added_assessments, user):
		if not added_assessments:
			return

		by_type = {}
		for row in added_assessments:
			by_type.setdefault(row.assessment_type, set()).add(row.assessment_name)

		for assessment_type, names in by_type.items():
			# One query per assessment type in this batch, not one per row.
			administrable = set(frappe.db.sql_list(administrable_assessment_names(assessment_type, user)))
			unauthorised = names - administrable
			if unauthorised:
				frappe.throw(
					_("You are not authorized to add {0} to this batch.").format(next(iter(unauthorised))),
					frappe.PermissionError,
				)

	def _validate_added_courses(self, added_courses, user):
		if not added_courses:
			return

		authored = courses_authored_by(user, added_courses)
		unauthorised = added_courses - authored
		if unauthorised:
			title = frappe.db.get_value("LMS Course", next(iter(unauthorised)), "title")
			frappe.throw(
				_("You are not authorized to add {0} to this batch.").format(frappe.bold(title)),
				frappe.PermissionError,
			)

	def validate_batch_end_date(self):
		if self.end_date < self.start_date:
			frappe.throw(_("Batch end date cannot be before the batch start date"))

	def validate_batch_time(self):
		if self.start_time and self.end_time:
			if get_time(self.start_time) >= get_time(self.end_time):
				frappe.throw(_("Batch start time cannot be greater than or equal to end time."))

	def validate_duplicate_courses(self):
		courses = [row.course for row in self.courses]
		duplicates = {course for course in courses if courses.count(course) > 1}
		if len(duplicates):
			title = frappe.db.get_value("LMS Course", next(iter(duplicates)), "title")
			frappe.throw(_("Course {0} has already been added to this batch.").format(frappe.bold(title)))

	def validate_duplicate_instructors(self):
		instructors = [row.instructor for row in self.instructors]
		duplicates = {instructor for instructor in instructors if instructors.count(instructor) > 1}
		if len(duplicates):
			full_name = frappe.db.get_value("User", next(iter(duplicates)), "full_name")
			frappe.throw(
				_("Instructor {0} has already been added to this batch.").format(frappe.bold(full_name))
			)


	def validate_amount_and_currency(self):
		if self.paid_batch and (not self.amount or not self.currency):
			frappe.throw(_("Amount and currency are required for paid batches."))

	def validate_duplicate_assessments(self):
		assessments = [row.assessment_name for row in self.assessment]
		for assessment in self.assessment:
			if assessments.count(assessment.assessment_name) > 1:
				title = frappe.db.get_value(assessment.assessment_type, assessment.assessment_name, "title")
				frappe.throw(
					_("Assessment {0} has already been added to this batch.").format(frappe.bold(title))
				)

	def validate_evaluation_end_date(self):
		if self.evaluation_end_date and self.evaluation_end_date < self.end_date:
			frappe.throw(_("Evaluation end date cannot be less than the batch end date."))

	def validate_seats_left(self):
		if cint(self.seat_count) < 0:
			frappe.throw(_("Seat count cannot be negative."))

		students = frappe.db.count("LMS Batch Enrollment", {"batch": self.name})
		if cint(self.seat_count) and cint(self.seat_count) < students:
			frappe.throw(_("There are no seats available in this batch."))

	def validate_timetable(self):
		for schedule in self.timetable:
			if schedule.start_time and schedule.end_time:
				if get_time(schedule.start_time) > get_time(schedule.end_time) or get_time(
					schedule.start_time
				) == get_time(schedule.end_time):
					frappe.throw(
						_("Row #{0} Start time cannot be greater than or equal to end time.").format(
							schedule.idx
						)
					)

				if get_time(schedule.start_time) < get_time(self.start_time) or get_time(
					schedule.start_time
				) > get_time(self.end_time):
					frappe.throw(
						_("Row #{0} Start time cannot be outside the batch duration.").format(schedule.idx)
					)

				if get_time(schedule.end_time) < get_time(self.start_time) or get_time(
					schedule.end_time
				) > get_time(self.end_time):
					frappe.throw(
						_("Row #{0} End time cannot be outside the batch duration.").format(schedule.idx)
					)

			if schedule.date < self.start_date or schedule.date > self.end_date:
				frappe.throw(_("Row #{0} Date cannot be outside the batch duration.").format(schedule.idx))

	def validate_instructor_changes(self):
		"""An evaluator may edit the batch, but listing themselves as its instructor
		would let them schedule its live classes."""
		if self.is_new():
			return
		stored = frappe.get_all(
			"Course Instructor", {"parent": self.name, "parenttype": "LMS Batch"}, pluck="instructor"
		)
		if set(stored) == {row.instructor for row in self.instructors}:
			return
		if not can_instruct_batch(self.name):
			frappe.throw(_("Only the batch's instructors can change who teaches it."), frappe.PermissionError)



def send_notification_for_published_batch(batch):
	send_notification = frappe.db.get_single_value("LMS Settings", "send_notification_for_published_batches")
	if not send_notification:
		return

	if not batch.published:
		return
	if batch.notification_sent:
		return

	if send_notification == "Email":
		send_email_notification_for_published_batch(batch)
	else:
		send_system_notification_for_published_batch(batch)


def send_email_notification_for_published_batch(batch):
	brand_name = frappe.db.get_single_value("Website Settings", "app_name")
	brand_logo = frappe.db.get_single_value("Website Settings", "banner_image")
	subject = _("A new course has been published on {0}").format(brand_name)
	template = "published_batch_notification"
	students = frappe.get_all("User", {"enabled": 1}, pluck="name")
	instructors = get_instructors("LMS Batch", batch.name)

	args = {
		"brand_logo": brand_logo,
		"brand_name": brand_name,
		"title": batch.title,
		"short_introduction": batch.description,
		"start_date": batch.start_date,
		"end_date": batch.end_date,
		"start_time": batch.start_time,
		"medium": batch.medium,
		"timezone": format_timezone(batch.timezone, batch.start_date),
		"instructors": instructors,
		"batch_url": frappe.utils.get_url(get_lms_route(f"batches/{batch.name}")),
	}

	frappe.sendmail(
		recipients=instructors,
		bcc=students,
		subject=subject,
		template=template,
		args=args,
	)
	frappe.db.set_value("LMS Batch", batch.name, "notification_sent", 1)


def send_system_notification_for_published_batch(batch):
	students = frappe.get_all("User", {"enabled": 1}, pluck="name")
	instructors = frappe.get_all("Course Instructor", {"parent": batch.name}, pluck="instructor")
	instructor_name = frappe.db.get_value("User", instructors[0], "full_name")
	notification = frappe._dict(
		{
			"subject": _("{0} has published a new batch {1}").format(
				frappe.bold(instructor_name), frappe.bold(batch.title)
			),
			"email_content": _(
				"A new batch '{0}' has been published that might interest you. Check it out!"
			).format(batch.title),
			"document_type": "LMS Batch",
			"document_name": batch.name,
			"from_user": instructors[0] if instructors else None,
			"type": "Alert",
			"link": get_lms_route(f"batches/{batch.name}"),
		}
	)
	make_notification_logs(notification, students)
	frappe.db.set_value("LMS Batch", batch.name, "notification_sent", 1)


@frappe.whitelist()
def create_live_class(
	batch_name: str,
	title: str,
	duration: int,
	date: str,
	time: str,
	timezone: str,
	auto_recording: str = "No Recording",
	description: str = None,
):
	"""Schedule a live class on the person's connected meeting app.

	The room lives on the platform: the site names its meeting app in settings,
	and the class stores the returned join link and room reference. Nothing is
	sent to a conferencing vendor from this app.
	"""
	# Checked before any platform call, or an unauthorised request still burns a
	# real room that the later save() only orphans.
	check_can_schedule_live_class(batch_name)

	from lms.integrations.conferencing import client as mail_client

	from lms.pramaan import PramaanError

	meeting_app = get_meeting_app()
	if not meeting_app:
		frappe.throw(
			_("Live class conferencing is not set up yet. Connect a meeting app in settings.")
		)

	payload = {
		"endUserRef": end_user_ref(),
		"app": meeting_app,
		"title": title,
		"start": meeting_start(date, time, timezone),
		"durationMinutes": duration,
		"timezone": timezone,
		"recording": "cloud" if auto_recording == "Cloud" else "none",
	}
	try:
		room = mail_client().call("meetings.room.create", payload, idempotency_key=generate_hash())
	except PramaanError as error:
		frappe.throw(_(str(error)))

	doc = frappe.get_doc(
		{
			"doctype": "LMS Live Class",
			"start_url": room.get("hostUrl") or "",
			"join_url": room.get("joinUrl") or "",
			"meeting_id": room.get("ref") or "",
			"uuid": room.get("ref") or "",
			"title": title,
			"host": frappe.session.user,
			"date": date,
			"time": time,
			"duration": duration,
			"timezone": timezone,
			"description": description,
			"auto_recording": auto_recording,
			"batch_name": batch_name,
			"conferencing_provider": meeting_app,
		}
	)
	try:
		doc.insert()
	except Exception:
		# The room already exists on the meeting app; without its class nothing
		# points at it.
		delete_meeting_room(doc.meeting_id)
		raise
	return doc


def delete_meeting_room(room_ref: str):
	"""Best effort: the save's own error is the one to report, not this one."""
	if not room_ref:
		return
	from lms.integrations.conferencing import client as mail_client

	try:
		mail_client().call("meetings.room.delete", {"ref": room_ref}, idempotency_key=generate_hash())
	except Exception:
		frappe.log_error(
			title=f"Could not delete the room of an unsaved live class {room_ref}", defer_insert=True
		)
	# Checked before any platform call, or an unauthorised request still burns a
def check_can_schedule_live_class(batch_name):
	if not can_instruct_batch(batch_name):
		frappe.throw(_("Only the batch's instructors can schedule live classes."), frappe.PermissionError)
	if not frappe.has_permission("LMS Live Class", "create"):
		frappe.throw(
			_("You do not have permission to create a live class for this batch."), frappe.PermissionError
		)


@frappe.whitelist()
def get_batch_timetable(batch: str):
	roles = frappe.get_roles()
	is_batch_student = frappe.db.exists(
		"LMS Batch Enrollment", {"batch": batch, "member": frappe.session.user}
	)
	is_admin = "Moderator" in roles or "Batch Evaluator" in roles
	if not (is_batch_student or is_admin):
		frappe.throw(
			_("You do not have permission to access announcements for this batch."), frappe.PermissionError
		)

	timetable = frappe.get_all(
		"LMS Batch Timetable",
		filters={"parent": batch},
		fields=[
			"reference_doctype",
			"reference_docname",
			"date",
			"start_time",
			"end_time",
			"milestone",
			"name",
			"idx",
			"parent",
		],
		order_by="date",
	)

	show_live_class = frappe.db.get_value("LMS Batch", batch, "show_live_class")
	if show_live_class:
		live_classes = get_live_classes(batch)
		timetable.extend(live_classes)

	timetable = get_timetable_details(timetable)
	return timetable


def get_live_classes(batch):
	live_classes = frappe.get_all(
		"LMS Live Class",
		{"batch_name": batch},
		["name", "title", "date", "time as start_time", "duration", "join_url as url"],
		order_by="date",
	)
	for class_ in live_classes:
		class_.end_time = class_.start_time + timedelta(minutes=class_.duration)
		class_.reference_doctype = "LMS Live Class"
		class_.reference_docname = class_.name
		class_.icon = "icon-call"

	return live_classes


def get_timetable_details(timetable):
	for entry in timetable:
		entry.title = frappe.db.get_value(entry.reference_doctype, entry.reference_docname, "title")
		assessment = frappe._dict({"assessment_name": entry.reference_docname})

		if entry.reference_doctype == "Course Lesson":
			course = frappe.db.get_value(entry.reference_doctype, entry.reference_docname, "course")
			entry.url = get_lesson_url(course, get_lesson_index(entry.reference_docname))

			entry.completed = (
				True
				if frappe.db.exists(
					"LMS Course Progress",
					{
						"lesson": entry.reference_docname,
						"member": frappe.session.user,
						"status": "Complete",
					},
				)
				else False
			)

		elif entry.reference_doctype == "LMS Quiz":
			entry.url = "/quizzes"
			details = get_quiz_details(assessment, frappe.session.user)
			entry.update(details)

		elif entry.reference_doctype == "LMS Assignment":
			details = get_assignment_details(assessment, frappe.session.user)
			entry.update(details)

	timetable = sorted(timetable, key=lambda k: k["date"])
	return timetable


def send_batch_start_reminder():
	batches = frappe.get_all(
		"LMS Batch",
		{"start_date": add_days(nowdate(), 1), "published": 1},
		[
			"name",
			"title",
			"start_date",
			"start_time",
			"medium",
			"show_live_class",
			"evaluation",
			"evaluation_end_date",
		],
	)

	for batch in batches:
		students = frappe.get_all("LMS Batch Enrollment", {"batch": batch.name}, ["member", "member_name"])
		for student in students:
			send_mail(batch, student)


def send_mail(batch, student):
	if batch.show_live_class:
		subject = _("Your batch {0} is starting tomorrow").format(batch.title)
		template = "batch_start_reminder"
	else:
		subject = _("You're enrolled in {0} – start whenever you're ready").format(batch.title)
		template = "batch_start_reminder_recorded"

	args = {
		"student_name": student.member_name,
		"title": batch.title,
		"start_date": batch.start_date,
		"start_time": batch.start_time,
		"medium": batch.medium,
		"name": batch.name,
		"evaluation": batch.evaluation,
		"evaluation_end_date": batch.evaluation_end_date,
	}

	frappe.sendmail(
		recipients=student.member,
		subject=subject,
		template=template,
		args=args,
		header=[_(f"Batch Start Reminder: {batch.title}"), "orange"],
	)


def has_permission(doc, ptype="read", user=None):
	user = user or frappe.session.user
	if user == "Guest" and not guest_access_allowed():
		return False

	roles = frappe.get_roles(user)
	if "Moderator" in roles:
		return True

	if ptype not in ("read", "select", "print"):
		# A new batch has no tags yet; creation stays governed by the DocPerm grant.
		return doc.is_new() or can_author_batch(doc.name, user=user)

	# Batch Evaluator keeps its existing blanket read; any other tagged
	# instructor/evaluator (e.g. Course Creator) is scoped to their own batch.
	if "Batch Evaluator" in roles or can_author_batch(doc.name, user=user):
		return True

	is_enrolled = frappe.db.exists("LMS Batch Enrollment", {"batch": doc.name, "member": user})
	if is_enrolled:
		return True

	is_batch_published = frappe.db.get_value("LMS Batch", doc.name, "published")
	if is_batch_published:
		return True

	return False


def get_permission_query_conditions(user=None):
	"""List-read counterpart of has_permission above: published, enrolled, or authored."""
	user = user or frappe.session.user
	if is_site_administrator(user):
		return ""

	if user == "Guest" and not guest_access_allowed():
		return "1 = 0"

	roles = frappe.get_roles(user)
	if "Moderator" in roles or "Batch Evaluator" in roles:
		return ""

	batch = frappe.qb.DocType("LMS Batch")
	enrollment = frappe.qb.DocType("LMS Batch Enrollment")
	member = LiteralValue(frappe.db.escape(user))
	enrolled = frappe.qb.from_(enrollment).select(enrollment.batch).where(enrollment.member == member)
	condition = Bracket(
		(batch.published == 1) | batch.name.isin(enrolled) | authored_batch_condition(batch.name, user)
	)
	return condition.get_sql(with_namespace=True, quote_char="`" if frappe.db.db_type == "mariadb" else '"')

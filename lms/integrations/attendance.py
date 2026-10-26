"""Completed room sessions; display names never identify local learners."""
import json
from datetime import datetime, timedelta, timezone

import frappe
from frappe import _
from frappe.utils import now_datetime

from lms.integrations.conferencing import client, end_user_ref, meeting_start
from lms.lms.permissions import can_instruct_batch, is_site_administrator
from lms.pramaan import PramaanError


def collect(cls):
    if not cls.meeting_id:
        return {"availability": "no_data", "results": []}
    end = datetime.fromisoformat(meeting_start(cls.date, cls.time, cls.timezone)) + timedelta(minutes=int(cls.duration))
    if end > datetime.now(timezone.utc):
        return {"availability": "processing", "results": []}
    rows, cursor, seen = [], None, set()
    for _page in range(100):
        inputs = {"ref": cls.meeting_id, "endUserRef": cls.meeting_end_user_ref or end_user_ref(cls.owner), "limit": 50}
        if cursor:
            inputs["cursor"] = cursor
        report = client().call("meetings.room.attendance.list", inputs)
        if report.get("availability") in {"no_data", "processing"}:
            return {"availability": report["availability"], "results": []}
        if report.get("availability") != "available" or not isinstance(report.get("results"), list):
            raise PramaanError("invalid_response")
        rows.extend(report["results"])
        cursor = report.get("nextCursor")
        if not cursor:
            completed = {"availability": "available", "results": rows}
            frappe.db.set_value("LMS Live Class", cls.name, "attendance_report", json.dumps(completed))
            return completed
        if cursor in seen:
            break
        seen.add(cursor)
    raise PramaanError("invalid_response")


@frappe.whitelist(methods=["POST"])
def report(live_class: str):
    cls = frappe.get_doc("LMS Live Class", live_class)
    if not (is_site_administrator(frappe.session.user) or can_instruct_batch(cls.batch_name)):
        frappe.throw(_("Only this batch's instructors can read attendance."), frappe.PermissionError)
    try:
        return collect(cls)
    except PramaanError as error:
        frappe.throw(str(error))


def refresh_completed():
    for row in frappe.get_all("LMS Live Class", filters={"date": ["<=", now_datetime().date()], "meeting_id": ["!=", ""]}, fields=["name"]):
        cls = frappe.get_doc("LMS Live Class", row.name)
        if cls.attendance_report:
            continue
        try:
            collect(cls)
        except PramaanError:
            frappe.log_error(title="Class attendance is not available yet")

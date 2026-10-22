"""Shared helpers for platform conferencing and calendar calls.

Every outside call goes through the single client; these helpers only build
its inputs. Client errors are already plain and caller-safe.
"""
import hashlib
from zoneinfo import ZoneInfo

import frappe
from frappe import _

from lms.pramaan import PramaanClient


def client():
    return PramaanClient()


def end_user_ref(user: str | None = None) -> str:
    """A stable platform reference for a person, derived from their account.

    The platform's reference is opaque letters, digits, '_' and '-' only; it is
    never the person's address.
    """
    user = user or frappe.session.user
    return hashlib.sha256(user.encode()).hexdigest()[:32]


def get_meeting_app() -> str:
    """The meeting app key the site schedules live classes on."""
    return frappe.db.get_single_value("LMS Settings", "meeting_app") or ""


def get_site_inbox(required: bool = False) -> str:
    """The connected inbox whose calendar carries class and evaluation events."""
    inbox = frappe.db.get_single_value("LMS Settings", "calendar_inbox") or ""
    if required and not inbox:
        frappe.throw(
            _("Calendars are not set up yet. Choose the site's inbox in settings to send invites.")
        )
    return inbox


def meeting_start(date, time, timezone=None):
    """Include the chosen local zone offset in the scheduled meeting time."""
    from frappe.utils import get_datetime, get_system_timezone

    zone = ZoneInfo(timezone or get_system_timezone())
    return get_datetime(f"{date} {time}").replace(tzinfo=zone).isoformat()

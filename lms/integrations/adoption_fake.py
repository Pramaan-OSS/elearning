"""Explicit offline fixtures for capability adoption; never opens a socket."""
import json
import os
from urllib.parse import urlparse

IDS = {
    "auth.social.start", "auth.social.exchange", "auth.app-invitation.create",
    "auth.app-invitation.accept", "meetings.room.attendance.list", "media.stock-photos.search",
    "calendar.event.create", "calendar.event.update",
}


def transport(method, url, headers, body):
    capability = urlparse(url).path.rsplit("/", 1)[-1]
    if capability in IDS:
        json.dumps(body)  # The real transport must be able to encode the same request.
    mode = os.environ.get("PRAMAAN_FAKE_ADOPTION", "unavailable")
    if capability not in IDS or mode == "unavailable":
        return 404, {"error": {"code": "not_found"}}
    if mode == "refused":
        return 400, {"error": {"code": "invalid_request"}}
    fixtures = {
        "auth.social.start": {"startRef": "fake-start", "authorizationUrl": "https://api.pramaan.dev/connect/link/fake", "state": (body or {}).get("state"), "expiresAt": "2099-01-01T00:00:00Z"},
        "auth.social.exchange": {"subjectId": "fake-subject", "email": "learner@example.test", "emailVerified": True},
        "auth.app-invitation.create": {"ref": "fake-invitation", "status": "pending", "expiresAt": "2099-01-01T00:00:00Z"},
        "auth.app-invitation.accept": {"email": "learner@example.test", "role": "LMS Student", "invitationRef": "fake-invitation"},
        "meetings.room.attendance.list": {"availability": mode if mode in {"no_data", "processing"} else "available", "results": [] if mode in {"no_data", "processing"} else [{"name": "Learner", "joinedAt": "2026-10-25T10:00:00Z", "leftAt": "2026-10-25T10:30:00Z", "durationSeconds": 1800}]},
        "media.stock-photos.search": {"results": [{"url": "https://images.example.test/photo.jpg", "previewUrl": "https://images.example.test/preview.jpg", "width": 800, "height": 600, "author": "Sample Photographer", "authorUrl": "https://photos.example.test/author", "sourceUrl": "https://photos.example.test/photo", "licence": "Stock licence", "licenceUrl": "https://photos.example.test/licence", "attribution": "Photo by Sample Photographer", "sourceCredit": "Photo library", "sourceCreditUrl": "https://photos.example.test"}]},
        "calendar.event.create": {"ref": "fake-event"},
        "calendar.event.update": {"ref": "fake-event"},
    }
    return 200, fixtures[capability]

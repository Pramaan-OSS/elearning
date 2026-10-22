"""Author assistance through the single client: translation and, when an
administrator turns it on, transcription of a lesson's own media.

Both are explicit author actions. Translation returns a draft the author
copies and reviews; nothing is written back automatically. Transcription
never publishes a private file: local media is uploaded to the platform as
transcription input and the upload is deleted as soon as the text is back.
"""
import json
import re

import frappe
from frappe import _

from lms.pramaan import PramaanClient, PramaanError

AUTHOR_ROLES = ["Course Creator", "Moderator", "Batch Evaluator"]

# The platform accepts 100 MB uploads; keep a margin for the request body.
MAX_MEDIA_BYTES = 90 * 1024 * 1024
MAX_TRANSLATION_CHARS = 5000

MEDIA_TYPES = {
    "mp3": "audio/mpeg",
    "m4a": "audio/mp4",
    "wav": "audio/wav",
    "ogg": "audio/ogg",
    "oga": "audio/ogg",
    "webm": "audio/webm",
    "mp4": "video/mp4",
    "m4v": "video/mp4",
    "mov": "video/quicktime",
}

PUBLIC_URL = re.compile(r"^https://[A-Za-z0-9.\-_]+(:\d+)?/")


def client():
    return PramaanClient()


def require_author():
    frappe.only_for(AUTHOR_ROLES)


def _throw_plain(error: PramaanError):
    frappe.throw(_(str(error)))


def _clean_language(value: str) -> str:
    value = (value or "").strip().lower()
    if not re.fullmatch(r"[a-z]{2,3}(-[a-z0-9]{2,8})?", value):
        frappe.throw(_("Give a language like en, de or pt-br."))
    return value


@frappe.whitelist(methods=["POST"])
def translate_content(content: str, target_language: str, source_language: str = None) -> dict:
    """A draft translation of author text, returned for review.

    Nothing is saved: the caller shows the text and the author decides.
    """
    require_author()
    content = content or ""
    if not content.strip():
        frappe.throw(_("There is nothing to translate yet."))
    if len(content) > MAX_TRANSLATION_CHARS:
        frappe.throw(
            _("Translate up to {0} characters at a time; this text is {1}.").format(
                MAX_TRANSLATION_CHARS, len(content)
            )
        )
    body = {
        "text": content,
        "targetLanguage": _clean_language(target_language),
    }
    if source_language:
        body["sourceLanguage"] = _clean_language(source_language)
    try:
        result = client().call("text.translate", body)
    except PramaanError as error:
        _throw_plain(error)
    return {
        "text": result.get("text") or "",
        "detectedLanguage": result.get("detectedLanguage") or "",
    }


def transcription_enabled() -> bool:
    return bool(frappe.db.get_single_value("LMS Settings", "lesson_media_transcription"))


@frappe.whitelist()
def transcription_status() -> dict:
    """Whether the optional transcription action is switched on."""
    return {"enabled": transcription_enabled()}


def _media_file(file_url: str):
    if not file_url:
        frappe.throw(_("Give the media file to transcribe."))
    file_doc = frappe.get_doc("File", {"file_url": file_url})
    file_doc.check_permission("read")
    return file_doc


def _content_type(file_doc) -> str:
    extension = (file_doc.file_name or "").rsplit(".", 1)[-1].lower()
    content_type = MEDIA_TYPES.get(extension)
    if not content_type:
        frappe.throw(
            _("Transcription accepts mp3, m4a, wav, ogg, webm, mp4, m4v or mov files.")
        )
    return content_type


@frappe.whitelist(methods=["POST"])
def transcribe_media(file_url: str, language: str = None) -> dict:
    """A transcript of one lesson media file, for the author to edit in.

    Off until an administrator turns it on. A public link is transcribed in
    place; the lesson's own files are uploaded as transcription input and the
    upload is deleted when the text is back, whatever the answer was.
    """
    require_author()
    if not transcription_enabled():
        frappe.throw(
            _("Media transcription is not enabled. Ask your administrator to turn it on in settings.")
        )
    file_doc = _media_file(file_url)
    content_type = _content_type(file_doc)
    body = {}
    if language:
        body["language"] = _clean_language(language)[:2]

    if PUBLIC_URL.match(file_doc.file_url or ""):
        body["audioUrl"] = file_doc.file_url
        return _transcribe(body)

    content = file_doc.get_content()
    if not content:
        frappe.throw(_("The file is empty."))
    if len(content) > MAX_MEDIA_BYTES:
        frappe.throw(_("Transcription accepts media up to {0} MB.").format(90))

    try:
        upload = client().upload_file(content, "audio" if content_type.startswith("audio") else "video", content_type)
    except PramaanError as error:
        _throw_plain(error)
    try:
        body["fileId"] = upload["fileId"]
        return _transcribe(body)
    finally:
        try:
            client().delete_file(upload["fileId"])
        except PramaanError:
            frappe.log_error(
                title="Could not delete a transcription upload",
                message=upload["fileId"],
                defer_insert=True,
            )


def _transcribe(body: dict) -> dict:
    try:
        result = client().call("audio.transcribe", body)
    except PramaanError as error:
        _throw_plain(error)
    return {
        "text": result.get("text") or "",
        "language": result.get("language") or "",
        "durationSeconds": result.get("durationSeconds"),
    }

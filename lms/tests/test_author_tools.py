# Author assistance through the single client: translation and, when an
# administrator enables it, transcription of a lesson's own media.
# Every request rides a fake transport; no live call is made.

import json
import unittest
from unittest.mock import MagicMock, patch
from urllib.parse import urlsplit

import frappe


class FakeTransport:
	"""Strict wire fake for the files and capability endpoints."""

	def __init__(self, capability_result=None, fail_delete=False):
		self.requests = []
		self.capability_result = capability_result or {"text": "Hallo", "detectedLanguage": "en"}
		self.fail_delete = fail_delete
		self.file_seq = 0

	def __call__(self, method, url, headers, body):
		self.requests.append((method, url, headers, body))
		if method == "POST" and url.endswith("/v1/files?kind=audio"):
			self.file_seq += 1
			return 201, {"fileId": f"file_{self.file_seq}", "kind": "audio"}
		if method == "DELETE" and "/v1/files/" in url:
			if self.fail_delete:
				from lms.pramaan import PramaanError

				raise PramaanError("unavailable")
			return 200, {"deleted": True}
		if method == "POST" and "/v1/capabilities/" in url:
			capability = url.rsplit("/", 1)[-1]
			if capability == "audio.transcribe":
				return 200, {"text": "Hello there", "language": "en", "durationSeconds": 12}
			return 200, self.capability_result
		return 503, {"error": {"code": "upstream_unavailable"}}


class TestAuthorTools(unittest.TestCase):
	def setUp(self):
		self.transport = FakeTransport()
		self.frappe = MagicMock()
		# A plain throw: the real class, so assertRaises sees it.
		self.frappe.throw.side_effect = frappe.ValidationError
		patchers = [
			patch("lms.lms.author_tools.frappe", self.frappe),
			patch(
				"lms.lms.author_tools.PramaanClient",
				lambda: self._client(),
			),
		]
		for patcher in patchers:
			patcher.start()
			self.addCleanup(patcher.stop)

	def _client(self):
		from lms.pramaan import PramaanClient

		return PramaanClient(api_key="fake", transport=self.transport, sleep=lambda _: None)

	def _settings(self, enabled=True):
		self.frappe.db.get_single_value.return_value = 1 if enabled else 0

	def test_translate_returns_draft_for_review(self):
		from lms.lms.author_tools import translate_content

		self.frappe.db.get_single_value.return_value = 0
		result = translate_content("Good morning", "de")
		self.assertEqual(result["text"], "Hallo")
		call = next(c for c in self.transport.requests if "/text.translate" in c[1])
		self.assertEqual(call[3], {"text": "Good morning", "targetLanguage": "de"})

	def test_translate_refuses_oversize_and_bad_language_before_any_call(self):
		from lms.lms.author_tools import translate_content

		with self.assertRaises(frappe.ValidationError):
			translate_content("x" * 5001, "de")
		with self.assertRaises(frappe.ValidationError):
			translate_content("hello", "not a language")
		self.assertFalse(any("/text.translate" in c[1] for c in self.transport.requests))

	def test_transcription_is_off_until_enabled(self):
		import lms.lms.author_tools as tools

		self._settings(enabled=False)
		with self.assertRaises(frappe.ValidationError):
			tools.transcribe_media("/files/a.mp3")
		self.assertEqual(self.transport.requests, [])

	def test_local_media_uploads_transcribes_and_deletes(self):
		import lms.lms.author_tools as tools

		self._settings(enabled=True)
		file_doc = MagicMock()
		file_doc.file_url = "/private/files/a.mp3"
		file_doc.file_name = "a.mp3"
		file_doc.get_content.return_value = b"\x00\x01audio"
		self.frappe.get_doc.return_value = file_doc

		result = tools.transcribe_media("/private/files/a.mp3")

		self.assertEqual(result["text"], "Hello there")
		methods = [(m, urlsplit(u).path + ("?" + urlsplit(u).query if urlsplit(u).query else "")) for m, u, *_ in self.transport.requests]
		self.assertIn(("POST", "/v1/files?kind=audio"), methods)
		self.assertIn(("DELETE", "/v1/files/file_1"), methods)
		transcribe = next(c for c in self.transport.requests if "audio.transcribe" in c[1])
		self.assertEqual(transcribe[3], {"fileId": "file_1"})

	def test_the_upload_is_deleted_even_when_transcription_fails(self):
		import lms.lms.author_tools as tools

		self._settings(enabled=True)
		file_doc = MagicMock()
		file_doc.file_url = "/private/files/a.mp3"
		file_doc.file_name = "a.mp3"
		file_doc.get_content.return_value = b"audio"
		self.frappe.get_doc.return_value = file_doc
		# The capability endpoint refuses everything with upstream_unavailable.
		self.transport.capability_result = None

		requests = self.transport.requests

		def refuse(method, url, headers, body):
			requests.append((method, url, headers, body))
			if method == "POST" and url.endswith("/v1/files?kind=audio"):
				return 201, {"fileId": "file_1", "kind": "audio"}
			if method == "DELETE":
				return 200, {"deleted": True}
			from lms.pramaan import PramaanError

			raise PramaanError("unavailable")

		self.transport = refuse
		with self.assertRaises(frappe.ValidationError):
			tools.transcribe_media("/private/files/a.mp3")
		self.assertIn(("DELETE", "/v1/files/file_1"), [(m, urlsplit(u).path) for m, u, *_ in requests])

	def test_upload_refusal_is_a_plain_transcription_error(self):
		import lms.lms.author_tools as tools
		self._settings(enabled=True)
		file_doc = MagicMock(file_url='/private/files/lesson.wav', file_name='lesson.wav')
		file_doc.get_content.return_value = b'audio'
		self.frappe.get_doc.return_value = file_doc
		self.transport = lambda *args: (404, {'error': {'code': 'not_found'}})
		with self.assertRaises(frappe.ValidationError):
			tools.transcribe_media('/private/files/lesson.wav')

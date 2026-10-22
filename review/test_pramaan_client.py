"""Contract and safety tests; every request uses an in-memory fake."""
import io
import json
import os
import unittest
from unittest.mock import Mock, patch
from urllib.error import HTTPError

from test_pramaan_stubs import boundary, client, FakeTransport


class ClientTests(unittest.TestCase):
    def test_payment_creation_uses_one_tax_setting_without_changing_the_callers_input(self):
        for capability in ("payments.payment-link.create", "payments.checkout.create"):
            for configured, expected in ((None, "edtech"), ("", "edtech"), ("  ", "edtech"), (" live_tutoring ", "live_tutoring")):
                for existing in (None, "saas"):
                    with self.subTest(capability=capability, configured=configured, existing=existing):
                        transport = FakeTransport()
                        inputs = {"amount": 100, "currency": "usd"} if capability.endswith("payment-link.create") else {
                            "lineItems": [{"name": "Course", "amount": 100, "currency": "usd", "quantity": 1}],
                            "successUrl": "https://learning.example/complete",
                            "cancelUrl": "https://learning.example/cancel", "mode": "payment",
                        }
                        if existing is not None:
                            inputs["taxCategory"] = existing
                        original = dict(inputs)
                        with patch.dict(os.environ, {}, clear=True):
                            if configured is not None:
                                os.environ["PRAMAAN_TAX_CATEGORY"] = configured
                            client(transport).call(capability, inputs, idempotency_key="tax-test")
                        self.assertEqual(transport.requests[0][3]["taxCategory"], expected)
                        self.assertEqual(transport.requests[0][2]["Idempotency-Key"], "tax-test")
                        self.assertEqual(inputs, original)

    def test_payment_reads_do_not_receive_a_creation_tax_category(self):
        transport = FakeTransport()
        client(transport).call("payments.checkout.get", {"ref": "checkout-one"})
        self.assertEqual(transport.requests[0][3], {"ref": "checkout-one"})

    def test_missing_key_is_clear_and_never_calls_transport(self):
        calls = []
        c = boundary.PramaanClient(api_key="", transport=lambda *args: calls.append(args))
        with self.assertRaises(boundary.MissingPramaanKey) as raised:
            c.call("email.send", {})
        self.assertEqual(raised.exception.http_status_code, 422)
        self.assertEqual("Add PRAMAAN_API_KEY to .env", str(raised.exception))
        self.assertFalse(c.configured)
        self.assertEqual(calls, [])

    def test_async_completion_uses_same_job_and_only_one_action(self):
        replies = iter([(202, {"job_id": "job/one", "status": "running"}),
                        (200, {"status": "done", "result": {"roomId": "r1"}})])
        requests = []

        def transport(*args):
            requests.append(args)
            return next(replies)

        c = client(transport)
        result = c.call("meetings.room.create", {"title": "Class"}, idempotency_key="saved-key")
        self.assertEqual(result, {"roomId": "r1"})
        self.assertEqual([r[0] for r in requests], ["POST", "GET"])
        self.assertEqual(requests[0][2]["Idempotency-Key"], "saved-key")
        self.assertTrue(requests[1][1].endswith("/jobs/job%2Fone"))

    def test_uncertain_action_is_not_retried_and_error_is_safe(self):
        calls = []

        def transport(*args):
            calls.append(args)
            raise RuntimeError("vendor secret customer data")

        c = client(transport)
        with self.assertRaises(boundary.PramaanError) as raised:
            c.call("email.send", {}, idempotency_key="saved")
        self.assertTrue(raised.exception.uncertain)
        self.assertNotIn("secret", str(raised.exception))
        self.assertEqual(len(calls), 1)

    def test_invalid_capabilities_are_rejected_before_transport(self):
        calls = []
        c = client(lambda *args: calls.append(args))
        for cap in ["invented.capability", "voice.call.start-configured", "companies.enrich"]:
            with self.assertRaises(boundary.PramaanError):
                c.run(cap, {})
        self.assertEqual(calls, [])

    def test_actions_require_a_saved_idempotency_key_before_transport(self):
        calls = []
        c = client(lambda *args: calls.append(args))
        for cap in ["email.send", "code.run", "calendar.event.create",
                    "payments.checkout.create", "meetings.room.delete"]:
            with self.assertRaises(boundary.PramaanError):
                c.run(cap, {})
        self.assertEqual(calls, [])

    def test_redirects_never_forward_credentials(self):
        self.assertIsNone(boundary.NoRedirects().redirect_request(None, None, 302, "", {}, "https://elsewhere.example"))

    def test_configuration_rejects_credentials_and_remote_plain_http(self):
        for url in ["http://remote.example", "https://user:password@example.com", "https://example.com?secret=key"]:
            with self.assertRaises(boundary.PramaanError):
                boundary.PramaanClient(api_key="fake", base_url=url)

    def test_unavailable_surfaces_are_plain_and_per_family(self):
        cases = {
            "meetings.room.create": "Live class conferencing is not available yet.",
            "calendar.event.create": "Calendars is not available yet.",
            "payments.checkout.create": "Payments is not available yet.",
            "code.run": "The code runner is not available yet.",
            "auth.social.exchange": "Connected sign-in is not available yet.",
        }
        for cap, message in cases.items():
            c, context = unavailable_client(501, {"error": {"code": "not_available_yet"}})
            self.addCleanup(context.stop)
            with self.assertRaises(boundary.PramaanNotAvailable) as raised:
                c.call(cap, {}, idempotency_key="saved")
            self.assertEqual(str(raised.exception), message)

    def test_upstream_unavailable_reads_as_not_available_per_family(self):
        c, context = unavailable_client(502, {"error": {"code": "upstream_unavailable",
                                                        "retryable": False}})
        self.addCleanup(context.stop)
        with self.assertRaises(boundary.PramaanNotAvailable) as raised:
            c.call("payments.checkout.create", {}, idempotency_key="saved")
        self.assertEqual(str(raised.exception), "Payments is not available yet.")

    def test_connection_required_names_no_provider(self):
        transport = FakeTransport({"can_run": False, "reason": "connection_required",
                                   "slot": "meetapp"})
        c = client(transport)
        with self.assertRaises(boundary.ConnectionRequired) as raised:
            c.call("meetings.room.create", {"title": "Class"}, idempotency_key="saved")
        self.assertEqual(str(raised.exception), "Connect your account in settings first.")
        self.assertNotIn("meetapp", str(raised.exception))

    def test_upstream_error_text_never_reaches_the_caller(self):
        c, context = unavailable_client(502, {"error": {"code": "upstream_unavailable",
                                                        "message": "private upstream diagnostics"}})
        self.addCleanup(context.stop)
        with self.assertRaises(boundary.PramaanError) as raised:
            c.call("finance.exchange-rate.get", {"from": "USD", "to": "INR"})
        self.assertNotIn("private", str(raised.exception))

    def test_generation_sends_messages_and_bounded_tokens(self):
        transport = FakeTransport({"text": "ok"})
        c = client(transport)
        c.call("llm.complete", {"messages": [{"role": "user", "content": "hi"}]})
        body = transport.requests[0][3]
        self.assertEqual(body["messages"], [{"role": "user", "content": "hi"}])
        self.assertEqual(body["maxTokens"], 1024)
        with self.assertRaises(boundary.InvalidGenerationRequest):
            c.call("llm.complete", {"prompt": "hi"})
        with self.assertRaises(boundary.InvalidGenerationRequest):
            c.call("llm.complete", {"messages": [{"role": "user", "content": "hi"}], "maxTokens": 10})

    def test_unverified_identity_is_refused(self):
        c = client(FakeTransport({"subjectId": "s1", "email": "a@b.c", "emailVerified": False}))
        with self.assertRaises(boundary.PramaanError) as raised:
            c.exchange_social_sign_in(code="one", redirect_uri="https://app.test/callback")
        self.assertEqual(raised.exception.code, "identity_unverified")

    def test_verified_identity_returns_claims_without_tokens(self):
        transport = FakeTransport({"subjectId": "s1", "email": "a@b.c",
                                   "emailVerified": True, "displayName": "A"})
        c = client(transport)
        claims = c.exchange_social_sign_in(code="one", redirect_uri="https://app.test/cb",
                                           pkce_verifier="v", expected_nonce="n")
        self.assertEqual(claims["email"], "a@b.c")
        body = transport.requests[0][3]
        self.assertEqual(body, {"code": "one", "redirectUri": "https://app.test/cb",
                                "pkceVerifier": "v", "expectedNonce": "n"})

    def test_fixture_mode_has_no_network_transport(self):
        import os
        with patch.dict(os.environ, {"PRAMAAN_FAKE": "1"}):
            with patch.object(boundary, "build_opener") as http:
                c = boundary.PramaanClient(api_key="fake")
                with self.assertRaises(boundary.PramaanNotAvailable):
                    c.call("email.send", {}, idempotency_key="saved")
                http.assert_not_called()


def failing_open(status, body):
    payload = io.BytesIO(json.dumps(body).encode())
    opener = Mock()
    opener.open.side_effect = HTTPError("https://pramaan.test", status, "err", {}, payload)
    return opener


def unavailable_client(status, body):
    """A client on the real HTTP transport whose opener always fails."""
    c = boundary.PramaanClient(api_key="fake", base_url="https://pramaan.test")
    context = patch.object(boundary, "build_opener", return_value=failing_open(status, body))
    context.start()
    return c, context


if __name__ == "__main__":
    unittest.main()

class FileAvailabilityTests(unittest.TestCase):
    def test_missing_upload_route_is_a_plain_unavailable_response(self):
        wire = FakeTransport(response={'error': {'code': 'not_found'}}, status=404)
        with self.assertRaises(boundary.PramaanNotAvailable):
            client(wire).upload_file(b'audio', 'audio', 'audio/wav')
        self.assertTrue(wire.requests[0][2]['Idempotency-Key'])

    def test_upload_and_cleanup_actions_have_idempotency_keys(self):
        wire = FakeTransport(response={'fileId': 'file_fake'}, status=201)
        c = client(wire)
        c.upload_file(b'audio', 'audio', 'audio/wav')
        c.delete_file('file_fake')
        self.assertTrue(all(r[2].get('Idempotency-Key') for r in wire.requests))

class CheckoutAddressTests(unittest.TestCase):
    def test_local_return_address_refusal_is_actionable_and_not_uncertain(self):
        wire = FakeTransport(response={'error': {'code': 'invalid_request', 'message': 'Must be a public http or https URL.'}}, status=400)
        with self.assertRaises(boundary.PublicCheckoutAddressRequired) as raised:
            client(wire).call('payments.checkout.create', {}, idempotency_key='local-checkout')
        self.assertIn('public site address', str(raised.exception))
        self.assertFalse(raised.exception.uncertain)

    def test_http_transport_preserves_only_the_recognized_checkout_hint(self):
        raw = json.dumps({'error': {'code': 'invalid_request', 'message': 'Must be a public http or https URL.'}, 'private': 'not-for-the-page'}).encode()
        opener = Mock()
        opener.open.side_effect = HTTPError('https://api.invalid', 400, 'Bad Request', {}, io.BytesIO(raw))
        c = boundary.PramaanClient(api_key='fake')
        with patch.object(boundary, 'build_opener', return_value=opener):
            with self.assertRaises(boundary.PublicCheckoutAddressRequired) as raised:
                c.call('payments.checkout.create', {}, idempotency_key='local-checkout')
        opener.open.side_effect.close()
        self.assertNotIn('not-for-the-page', str(raised.exception))

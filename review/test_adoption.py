import os
import unittest
from unittest.mock import patch

from lms.integrations.adoption_fake import IDS, transport
from lms.pramaan import PramaanClient, PramaanError, PramaanNotAvailable


class AdoptionContracts(unittest.TestCase):
    def test_success_refusal_unavailable_for_every_id(self):
        for capability in IDS:
            with self.subTest(capability=capability):
                for mode in ('success', 'refused', 'unavailable'):
                    with patch.dict(os.environ, {'PRAMAAN_FAKE_ADOPTION': mode}):
                        client = PramaanClient(api_key='offline-fixture', transport=transport)
                        args = {'state': 's'}
                        if mode == 'success':
                            result = client.call(capability, args, idempotency_key='fixture')
                            self.assertIsInstance(result, dict)
                        else:
                            error = PramaanNotAvailable if mode == 'unavailable' else PramaanError
                            with self.assertRaises(error):
                                client.call(capability, args, idempotency_key='fixture')

    def test_no_data_and_processing_are_explicit_and_empty(self):
        for mode in ('no_data', 'processing'):
            with patch.dict(os.environ, {'PRAMAAN_FAKE_ADOPTION': mode}):
                result = PramaanClient(api_key='offline', transport=transport).call('meetings.room.attendance.list', {'ref': 'room'})
                self.assertEqual(result, {'availability': mode, 'results': []})

    def test_hosted_exchange_passes_proof_and_start_reference(self):
        calls = []
        def fake(method, url, headers, body):
            calls.append(body)
            return 200, {'subjectId': 'identity', 'email': 'learner@example.test', 'emailVerified': True}
        result = PramaanClient(api_key='offline', transport=fake).exchange_social_sign_in(code='code', redirect_uri='https://app.test/callback', start_ref='start', state='state', pkce_verifier='proof', expected_nonce='nonce')
        self.assertTrue(result['email_verified'])
        self.assertEqual(calls[0]['startRef'], 'start')
        self.assertEqual(calls[0]['state'], 'state')
        self.assertEqual(calls[0]['pkceVerifier'], 'proof')
        self.assertEqual(calls[0]['expectedNonce'], 'nonce')

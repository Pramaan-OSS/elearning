import hashlib
import json
from unittest.mock import MagicMock, patch

import frappe
from frappe.tests.utils import FrappeTestCase

from lms.integrations import attendance, invitations, social
from lms.lms.doctype.lms_live_class import lms_live_class as classes
from lms.pramaan import PramaanError


class TestCapabilityAdoption(FrappeTestCase):
    def test_hidden_guests_are_required(self):
        cls = frappe._dict(date='2026-10-25', time='10:00:00', duration=30, timezone='UTC', title='Class')
        cls.build_event_description = lambda: 'Class'
        with patch.object(classes, 'get_site_inbox', return_value='inbox'):
            body = classes.event_body(cls, ['learner@example.test'], True)
            self.assertIs(body['guestListHidden'], True)
            self.assertEqual(body['end'], '2026-10-25T10:30:00')
            json.dumps(body)

    def test_calendar_refusal_is_not_downgraded(self):
        cls = frappe._dict(platform_event_ref='event', date='2026-10-25', time='10:00:00', duration=30, timezone='UTC', title='Class', name='class')
        cls.build_event_description = lambda: 'Class'
        fake = MagicMock()
        fake.call.side_effect = PramaanError('request_rejected')
        with patch.object(classes, 'get_site_inbox', return_value='inbox'), patch.object(classes, 'client', return_value=fake), patch.object(frappe, 'log_error'):
            self.assertFalse(classes.update_platform_event(cls, ['learner@example.test'], True))
        self.assertEqual(fake.call.call_count, 1)
        self.assertTrue(fake.call.call_args.args[1]['guestListHidden'])

    def test_attendance_requires_batch_permission_before_call(self):
        with patch.object(frappe, 'get_doc', return_value=frappe._dict(batch_name='other')), patch.object(attendance, 'is_site_administrator', return_value=False), patch.object(attendance, 'can_instruct_batch', return_value=False), patch.object(attendance, 'client') as client:
            self.assertRaises(frappe.PermissionError, attendance.report, 'class')
            client.assert_not_called()

    def test_attendance_pages_only_save_after_complete(self):
        cls = frappe._dict(name='class', meeting_id='room', meeting_end_user_ref='creator', owner='owner', date='2026-01-01', time='10:00:00', duration=30, timezone='UTC')
        fake = MagicMock()
        fake.call.side_effect = [{'availability': 'available', 'results': [{'name': 'Learner'}], 'nextCursor': 'next'}, {'availability': 'processing', 'results': []}]
        with patch.object(attendance, 'client', return_value=fake), patch.object(frappe.db, 'set_value') as save:
            self.assertEqual(attendance.collect(cls), {'availability': 'processing', 'results': []})
            save.assert_not_called()
        self.assertEqual(fake.call.call_args.args[1]['cursor'], 'next')
        self.assertEqual(fake.call.call_args.args[1]['endUserRef'], 'creator')

    def test_invitation_rejects_invalid_token_before_call(self):
        with patch.object(invitations, 'PramaanClient') as client:
            self.assertRaises(frappe.ValidationError, invitations.accept, 'bad-token')
            client.assert_not_called()

    def test_invitation_cannot_offer_administrator(self):
        with patch.object(frappe, 'only_for'), patch.object(invitations, 'PramaanClient') as client:
            self.assertRaises(frappe.ValidationError, invitations.create, 'learner@example.test', 'System Manager')
            client.assert_not_called()

    def test_social_wrong_state_does_not_exchange(self):
        cache = MagicMock()
        cache.get_value.return_value = {'state': 'expected', 'created': 0}
        request = MagicMock()
        request.cookies = {'social_binding': 'visitor-cookie'}
        with patch.object(frappe.local, 'response', frappe._dict()), patch.object(frappe, 'cache', cache), patch.object(frappe, 'request', request), patch.object(social, 'PramaanClient') as client:
            social.callback(code='code', state='wrong')
            client.assert_not_called()
            cache.delete_value.assert_called_once_with('social:visitor-cookie')
            self.assertEqual(frappe.local.response['location'], '/login?signin=unavailable')

    def test_invitation_accept_is_durable_and_never_escalates_existing_user(self):
        fixture = {'email': 'existing@example.test', 'role': 'Course Creator', 'invitationRef': 'one-invitation'}
        fake = MagicMock()
        fake.call.return_value = fixture
        account = MagicMock()
        def exists(doctype, filters):
            return doctype == 'User'
        with patch.object(invitations, 'PramaanClient', return_value=fake), patch.object(frappe.db, 'exists', side_effect=exists), patch.object(frappe, 'get_doc', return_value=account) as get_doc, patch.object(frappe.db, 'commit'):
            invitations.accept('a' * 43)
            get_doc.assert_called_once_with({'doctype': 'LMS App Invitation', 'invitation_ref': hashlib.sha256(b'one-invitation').hexdigest(), 'member': 'existing@example.test', 'role': 'Course Creator'})
        with patch.object(invitations, 'PramaanClient', return_value=fake), patch.object(frappe.db, 'exists', return_value=True), patch.object(frappe, 'get_doc') as get_doc:
            self.assertEqual(invitations.accept('a' * 43), {'status': 'accepted'})
            get_doc.assert_not_called()

    def test_hosted_start_uses_unique_visitor_binding_and_proof(self):
        fake = MagicMock()
        fake._base_url = 'https://api.pramaan.dev'
        fake.call.side_effect = lambda capability, body, **kwargs: {'startRef': 'start', 'state': body['state'], 'authorizationUrl': 'https://api.pramaan.dev/connect/link/fake', 'expiresAt': '2099-01-01T00:00:00Z'}
        cache, cookies = MagicMock(), MagicMock()
        with patch.object(social, 'providers', return_value=['google']), patch.object(frappe.utils, 'get_url', return_value='https://app.test/callback'), patch.object(social, 'PramaanClient', return_value=fake), patch.object(frappe, 'cache', cache), patch.object(frappe.local, 'cookie_manager', cookies, create=True):
            social.start('google')
            social.start('google')
        keys = [call.args[0] for call in cache.set_value.call_args_list]
        self.assertNotEqual(keys[0], keys[1])
        self.assertEqual(len(fake.call.call_args.args[1]['codeChallenge']), 43)
        self.assertTrue(cookies.set_cookie.call_args.kwargs['httponly'])
        self.assertTrue(cookies.set_cookie.call_args.kwargs['secure'])

    def test_social_valid_callback_opens_only_an_enabled_local_account(self):
        import time
        saved = {'state': 'state', 'created': time.time(), 'redirect_uri': 'https://app.test/callback', 'verifier': 'proof', 'nonce': 'nonce', 'start_ref': 'start'}
        cache = MagicMock()
        cache.get_value.return_value = saved
        request = MagicMock()
        request.cookies = {'social_binding': 'visitor'}
        fake = MagicMock()
        fake.exchange_social_sign_in.return_value = {'email': 'learner@example.test', 'email_verified': True}
        login = MagicMock()
        with patch.object(frappe.local, 'response', frappe._dict()), patch.object(frappe, 'cache', cache), patch.object(frappe, 'request', request), patch.object(social, 'PramaanClient', return_value=fake), patch.object(frappe.db, 'get_value', return_value='learner@example.test') as get_value, patch.object(frappe.local, 'login_manager', login, create=True):
            social.callback(code='code', state='state')
            get_value.assert_called_once_with('User', {'email': 'learner@example.test', 'enabled': 1}, 'name')
            login.login_as.assert_called_once_with('learner@example.test')
            self.assertEqual(frappe.local.response['location'], '/lms')

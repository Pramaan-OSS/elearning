import json
from types import SimpleNamespace
from unittest.mock import Mock, patch

import frappe
from frappe.tests import IntegrationTestCase

from lms.integrations import pramaan_mail


class TestOutgoingSender(IntegrationTestCase):
    def test_worker_hook_does_not_require_an_already_loaded_email_module(self):
        worker, email_module = SimpleNamespace(), SimpleNamespace()
        with patch.object(pramaan_mail, 'frappe', worker), patch.object(pramaan_mail, 'import_module', return_value=email_module):
            pramaan_mail.install_transport()
        self.assertIs(worker.sendmail, pramaan_mail.sendmail)
        self.assertIs(email_module.sendmail, pramaan_mail.sendmail)

    def test_missing_sender_uses_the_complete_schema_default(self):
        with patch.object(frappe.db, 'get_single_value', return_value=''):
            self.assertEqual(pramaan_mail.default_sender(), 'eLearning <noreply@updates.pramaan.one>')

    def test_sender_is_one_setting_and_is_not_replaced_by_a_local_author(self):
        saved_mute, saved_test = frappe.flags.mute_emails, frappe.flags.in_test
        frappe.flags.mute_emails = frappe.flags.in_test = False
        fake = Mock()
        fake.call.return_value = {'status': 'queued', 'ref': 'mail_fake', 'rfcMessageId': 'fake-message'}
        try:
            with patch.object(pramaan_mail, 'default_sender', return_value='School <mail@school.test>'), patch('frappe.enqueue'), patch.object(pramaan_mail, 'client', return_value=fake):
                queued = pramaan_mail.sendmail(recipients=['learner@example.test'], sender='author@example.test', subject='Local notice', message='<p>Hello</p>')
                outbox = frappe.get_doc('Pramaan Outbox', queued.name)
                payload = json.loads(outbox.payload)
                self.assertEqual(payload['from'], 'School <mail@school.test>')
                self.assertNotIn('replyTo', payload)
                pramaan_mail.deliver(outbox.name)
                fake.call.assert_called_once_with('email.send', payload, idempotency_key=outbox.idempotency_key)
                outbox.reload()
                self.assertEqual(outbox.platform_ref, 'mail_fake')
                self.assertEqual(outbox.acceptance, 'queued')
        finally:
            frappe.flags.mute_emails, frappe.flags.in_test = saved_mute, saved_test

    def test_complete_sender_survives_settings_save(self):
        settings = frappe.get_single('LMS Settings')
        settings.outgoing_sender_email = 'eLearning <noreply@updates.pramaan.one>'
        settings.save(ignore_permissions=True)
        settings.reload()
        self.assertEqual(settings.outgoing_sender_email, 'eLearning <noreply@updates.pramaan.one>')

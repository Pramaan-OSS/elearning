from unittest.mock import patch
import frappe
from frappe.tests import IntegrationTestCase
from lms.lms import api
from lms.pramaan import PramaanClient


class TestCalendarConnectionStart(IntegrationTestCase):
    def test_hosted_start_uses_calendar_app_and_local_return_path(self):
        requests = []
        def transport(method, url, headers, body):
            requests.append((method, url, headers, body))
            return 200, {'connectUrl': 'https://connect.example.test/start'}
        fake = PramaanClient(api_key='fake', transport=transport)
        with patch.object(api, 'client', return_value=fake), patch('frappe.utils.get_url', side_effect=lambda path: 'http://localhost:18147'+path):
            result = api.calendar_connect_start()
        self.assertEqual(result['connectUrl'], 'https://connect.example.test/start')
        method, url, headers, body = requests[0]
        self.assertEqual(method, 'POST')
        self.assertTrue(url.endswith('/apps.connection.start'))
        self.assertEqual(body['app'], 'googlecalendar')
        self.assertTrue(body['redirectUrl'].endswith('/user/administrator/slots'))
        self.assertNotIn('returnUrl', body)
        self.assertTrue(headers['Idempotency-Key'])
        self.assertNotIn('@', body['endUserRef'])

    def test_authorization_is_not_claimed_as_a_ready_inbox(self):
        def transport(method, url, headers, body):
            self.assertTrue(url.endswith('/apps.connections.list'))
            self.assertEqual(body['app'], 'googlecalendar')
            return 200, {'results': [{'app': 'googlecalendar', 'status': 'active'}]}
        with patch.object(api, 'get_calendar_connect', return_value={'app': 'googlecalendar'}), patch.object(api, 'client', return_value=PramaanClient(api_key='fake', transport=transport)):
            state = api.calendar_connection_status('Administrator')
        self.assertTrue(state['authorized'])
        self.assertFalse(state['connected'])
        self.assertEqual(state['inbox'], '')

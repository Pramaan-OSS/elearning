from unittest.mock import patch
import frappe
from frappe.tests import IntegrationTestCase
from lms.lms import utils
from lms.pramaan import PramaanClient


class TestCurrencyAvailability(IntegrationTestCase):
    def setUp(self):
        super().setUp()
        frappe.cache.delete_value('exchange_rate:EUR:USD')
        self.addCleanup(lambda: frappe.cache.delete_value('exchange_rate:EUR:USD'))
        self.settings = frappe._dict(show_usd_equivalent=1, exception_country=[], apply_rounding=0)

    def price(self, status, result):
        requests = []
        def transport(*args):
            requests.append(args)
            return status, result
        fake = PramaanClient(api_key='fake', transport=transport)
        with patch('lms.pramaan.PramaanClient', return_value=fake), patch.object(frappe, 'get_single', return_value=self.settings):
            price = utils.check_multicurrency(10, 'EUR', country='France')
        return price, requests

    def test_unavailable_optional_quote_keeps_the_original_price(self):
        price, requests = self.price(503, {'error': {'code': 'upstream_unavailable'}})
        self.assertEqual(price, (10, 'EUR'))
        self.assertEqual(len(requests), 1)

    def test_valid_quote_is_used_and_cached(self):
        price, requests = self.price(200, {'rate': 1.1})
        self.assertEqual(price, (11, 'USD'))
        price, requests = self.price(503, {'error': {'code': 'upstream_unavailable'}})
        self.assertEqual(price, (11, 'USD'))
        self.assertEqual(requests, [])

    def test_invalid_quote_cannot_turn_a_price_into_zero(self):
        for rate in (0, -1, 'NaN'):
            with self.subTest(rate=rate):
                self.assertEqual(self.price(200, {'rate': rate})[0], (10, 'EUR'))

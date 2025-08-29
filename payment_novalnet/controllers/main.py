# Part of Odoo. See LICENSE file for full copyright and licensing details.

"""
 This is main.py controller file
"""
import json
import logging
import pprint

from odoo import _, http
from odoo.exceptions import ValidationError
from odoo.http import request

_logger = logging.getLogger(__name__)


class PaymentNovalnetController(http.Controller):
    """
     Controller for handling Novalnet payment processing.

     This controller manages the payment flow, including payment simulation, return
     handling, and webhook notifications for Novalnet payments.

     Routes:
     - _simulation_url: Endpoint for simulating a Novalnet payment.
     - _return_url: Endpoint for handling return requests from Novalnet.
     - _webhook_url: Endpoint for receiving webhook notifications from Novalnet.
     """
    _simulation_url = '/payment/novalnet/simulate_payment'
    _return_url = '/payment/novalnet/return'
    webhook_url = '/payment/novalnet/webhook'

    @http.route(_simulation_url, type='json', auth='public')
    def novalnet_simulate_payment(self, **data):
        """ Simulate the response of a payment request.

        :param dict data: The simulated notification data.
        :return: None
        """
        request.env['payment.transaction'].sudo()._handle_notification_data('novalnet', data)

    @http.route(webhook_url, type='json', auth='public', methods=['POST'], csrf=False, website=True)
    def novalnet_webhook(self, **data):
        """
        Handles webhook notifications from Novalnet.
        """
        data = json.loads(request.httprequest.data)
        _logger.info("notification received from Novalnet with data:\n%s", pprint.pformat(data))

        if not {'event', 'result', 'transaction'} <= set(data):
            raise ValidationError(_("webhook necessary information not found"))
        tid = data.get('event')['parent_tid'] if 'parent_tid' in data.get('event') else data.get('event')['tid']
        event_type, checksum = data.get('event')['type'], data.get('event')['checksum']
        if 'order_no' not in data.get('transaction'):
            raise ValidationError(_("Order number not found"))

        transaction_info = request.env['payment.transaction'].sudo().search(
            [('reference', '=', data.get('transaction')['order_no'])], limit=1)
        if not transaction_info:
            raise ValidationError(_("Could not found order number"))

        custom_data = data.get('custom') or {}
        book_reference = custom_data.get('book_reference')

        result = data.get('result') or {}

        notification_values = {
            'nn_tid': tid,
            'event_type': event_type,
            'check_sum': checksum,
            'nn_status': result.get('status'),
            'nn_status_text': result.get('status_text'),
            'reference': transaction_info.reference,
        }

        if book_reference:
            notification_values['book_reference'] = book_reference
        transaction_info._handle_notification_data('novalnet', notification_values)

    @http.route(_return_url, type='http', auth='public')
    def novalnet_return_payment(self, **data):
        """
        Handles the return URL after processing a payment with Novalnet
        """
        _logger.info(pprint.pformat(data))

        if not {'status', 'status_text', 'status_code'} <= set(data):
            return request.render('payment_novalnet.novalnet_redirect_failure', {
                'failure_message': _('Unknown error occured please try after some time')
            })

        _nn_status, _nn_status_text = data['status'], data['status_text']

        if not {'txn_secret', 'tid', 'checksum'} <= set(data):
            return request.render('payment_novalnet.novalnet_redirect_failure', {
                'failure_message': _nn_status_text
            })
        novalnet_transaction_info = request.env['payment.novalnet.transaction'].sudo().search(
            [('novalnet_txn_secret', '=', data['txn_secret'])], limit=1)

        if not novalnet_transaction_info:
            return request.render('payment_novalnet.novalnet_redirect_failure', {
                'failure_message': _('Could not found Novalnet transaction')
            })
        transaction_info = request.env['payment.transaction'].sudo().search(
            [('novalnet_transaction_id', '=', novalnet_transaction_info.id)], limit=1)
        if not transaction_info:
            return request.render('payment_novalnet.novalnet_redirect_failure', {
                'failure_message': _('Could not found transaction')
            })
        transaction_info._handle_notification_data('novalnet', {'nn_tid': data['tid'], 'nn_status': _nn_status,
                                                                'nn_status_text': _nn_status_text,
                                                                'reference': transaction_info.reference})
        return request.redirect('/payment/status')

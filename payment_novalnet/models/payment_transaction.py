"""
This file is used for Novalnet Payment Transaction Process
"""

import logging
import re
import socket
from datetime import datetime, timedelta
from ipaddress import ip_interface

from odoo import _, fields, models, service, http
from odoo.exceptions import UserError, ValidationError
from odoo.http import request
from odoo.tools import format_amount, format_datetime
from werkzeug import urls

from odoo.addons.payment import utils as payment_utils
from odoo.addons.payment_novalnet.const import RESULT_CODES_MAPPING
from odoo.addons.payment_novalnet.controllers.main import PaymentNovalnetController

_logger = logging.getLogger(__name__)


class PaymentTransaction(models.Model):
    """
    Inherit core Payment Transaction
    """
    _inherit = 'payment.transaction'
    capture_manually = fields.Boolean(related='provider_id.capture_manually')
    novalnet_transaction_id = fields.Many2one(string="Novalnet transaction details",
                                              comodel_name='payment.novalnet.transaction')
    novalnet_callback_ids = fields.One2many(string="Novalnet transaction callback details",
                                            comodel_name='novalnet.callback', inverse_name='transaction_id')
    novalnet_transaction_amount_status_id = fields.Many2one('novalnet.transaction.amount.status',
                                                            string=" Novalnet transaction amount status ")

    def action_novalnet_set_done(self):
        """ Set the state of the novalnet transaction to 'done'.

        Note: self.ensure_one()

        :return: None
        """
        self.ensure_one()
        if self.provider_code != 'novalnet':
            return

        notification_data = {'reference': self.reference, 'simulated_state': 'done'}
        self._handle_notification_data('novalnet', notification_data)

    def action_novalnet_set_canceled(self):
        """ Set the state of the novalnet transaction to 'cancel'.

        Note: self.ensure_one()

        :return: None
        """
        self.ensure_one()
        if self.provider_code != 'novalnet':
            return

        notification_data = {'reference': self.reference, 'simulated_state': 'cancel'}
        self._handle_notification_data('novalnet', notification_data)

    def action_novalnet_set_error(self):
        """ Set the state of the novalnet transaction to 'error'.

        Note: self.ensure_one()

        :return: None
        """
        self.ensure_one()
        if self.provider_code != 'novalnet':
            return

        notification_data = {'reference': self.reference, 'simulated_state': 'error'}
        self._handle_notification_data('novalnet', notification_data)

    def _send_payment_request(self):
        """ Override of payment to simulate a payment request.

        Note: self.ensure_one()

        :return: None
        """
        super()._send_payment_request()
        if self.provider_code != 'novalnet':
            return

        if not self.token_id:
            raise UserError("Novalnet: " + _("The transaction is not linked to a token."))
        if self.operation != 'offline':
            return
        # Novalnet token used to payment process
        processing_val = self._get_processing_values()
        self._handle_notification_data('novalnet', processing_val)

    def _send_refund_request(self, **kwargs):
        refund_tx = super()._send_refund_request(**kwargs)
        if self.provider_code != 'novalnet':
            return refund_tx
        converted_amount = payment_utils.to_minor_currency_units(refund_tx.amount, refund_tx.currency_id)
        refund_payload = {
            'transaction': {
                'tid': self.provider_reference,
                'amount': abs(converted_amount),
                'reason': f'Refund for payment transaction with reference/{refund_tx.reference}',
            },
            'custom': {
                'shop_invoked': 1
            }
        }
        current_date = datetime.now().strftime("%d-%m-%Y")
        current_time = datetime.now().strftime("%H:%M:%S")
        refund_response = self.provider_id._novalnet_make_request("transaction/refund", data=refund_payload)
        formatted_amount = format_amount(refund_tx.env, refund_tx.amount, refund_tx.currency_id)
        if 'transaction' not in refund_response or 'tid' not in refund_response.get('transaction'):
            raise ValidationError(_(refund_response['result']['status_text']))
        elif 'refund' in refund_response.get('transaction') and 'tid' in refund_response.get('transaction')['refund']:
            _portal_comments = _(
                'Refund has been initiated for the TID: %(parent_tid)s with the amount %(amount)s. New TID:%('
                'child_tid)s for the refunded amount',
                parent_tid=refund_response.get('transaction')['tid'], amount=formatted_amount,
                child_tid=refund_response.get('transaction')['refund']['tid']
            )
            refund_tx._log_message_on_linked_documents(_portal_comments)
            refund_tid = refund_response.get('transaction')['refund']['tid']
        else:
            _portal_comments = _(
                'Refund has been initiated for the TID:%(parent_tid)s with the amount %(amount)s',
                parent_tid=refund_response.get('transaction')['tid'], amount=formatted_amount
            )
            refund_tid = refund_response.get('transaction')['tid']
            if refund_response.get('transaction')['status'] == 'DEACTIVATED':
                refund_tx.state = 'cancel'
            refund_tx._log_message_on_linked_documents(_portal_comments)
        notification_data = {'nn_tid': refund_tid,
                             'portal_comments': _portal_comments,
                             'nn_status': refund_response.get('transaction')['status']}
        self._add_extension_comments(_portal_comments, current_date, current_time)
        refund_tx._handle_notification_data('novalnet', notification_data)
        return refund_tx

    def _send_capture_request(self, amount_to_capture=None):
        """
         Novalnet transaction capture process
        """
        child_capture_tx = super()._send_capture_request(amount_to_capture=amount_to_capture)
        if self.provider_code != 'novalnet':
            return child_capture_tx

        tx = child_capture_tx or self
        if not tx.provider_reference:
            raise ValidationError(_("Could not find Novalnet parent transaction "))
        capture_payload = {
            'transaction': {
                'tid': tx.provider_reference
            },
            'custom': {
                'shop_invoked': 1
            }
        }

        capture_response = tx.provider_id._novalnet_make_request("transaction/capture", data=capture_payload)
        if capture_response['transaction']['status'] in ['CONFIRMED', 'PENDING']:
            current_date = datetime.now().strftime("%d-%m-%Y")
            current_time = datetime.now().strftime("%H:%M:%S")
            _portal_comments = _(
                'The transaction has been confirmed on %(date)s,%(time)s',
                date=datetime.now().strftime("%d-%m-%Y"),
                time=datetime.now().strftime("%H:%M:%S")
            )
        else:
            raise ValidationError(_(capture_response['result']['status_text']))
        tx._log_message_on_linked_documents(_portal_comments)
        self._add_extension_comments(_portal_comments, current_date, current_time)
        tx._handle_notification_data('novalnet', {'nn_tid': tx.provider_reference, 'portal_comments': _portal_comments})
        return child_capture_tx

    def _send_void_request(self, amount_to_void=None):
        """
          Novalnet transaction cancel process
        """
        child_void_tx = super()._send_void_request(amount_to_void=amount_to_void)
        if self.provider_code != 'novalnet':
            return child_void_tx

        tx = child_void_tx or self
        void_payload = {
            'transaction': {
                'tid': self.provider_reference
            },
            'custom': {
                'shop_invoked': 1
            }
        }
        cancel_response = tx.provider_id._novalnet_make_request("transaction/cancel", data=void_payload)
        if cancel_response['transaction']['status'] == 'DEACTIVATED':
            current_date = datetime.now().strftime("%d-%m-%Y")
            current_time = datetime.now().strftime("%H:%M:%S")
            _portal_comments = _(
                'The transaction has been canceled on %(datetime)s ',
                datetime=datetime.now().strftime("%d-%m-%Y %H:%M:%S")
            )
        else:
            raise ValidationError(_(cancel_response['result']['status_text']))
        tx._log_message_on_linked_documents(_portal_comments)
        self._add_extension_comments(_portal_comments, current_date, current_time)
        tx._handle_notification_data('novalnet',
                                     {'nn_tid': self.provider_reference, 'portal_comments': _portal_comments,
                                      'nn_status': 'DEACTIVATED'})
        return child_void_tx

    def _add_extension_comments(self, _portal_comments, current_date=None, current_time=None):
        if _portal_comments:
            # If date/time are passed, use them; otherwise, fallback to now()
            if current_date and current_time:
                timestamp = f"{current_date}, {current_time}"
            else:
                # Fallback formatting if no external values passed
                timestamp = format_datetime(
                    self.env,
                    fields.Datetime.now(),
                    dt_format="MMM d, yyyy, hh:mm:ss a"
                )

            # Final comment line
            comment_with_time = f"Published on {timestamp}\n{_portal_comments}"

            # Append to existing field with newline
            existing_comments = self.novalnet_transaction_id.novalnet_extension_comment_update or ''
            new_comment = f"{existing_comments}\n{comment_with_time}" if existing_comments else comment_with_time

            self.novalnet_transaction_id.novalnet_extension_comment_update = new_comment

    def _execute_callback(self):
        """
        This function for validate Novalnet Callback
        """
        if self.provider_code != 'novalnet':
            return
        for nn_callback in self.novalnet_callback_ids.filtered(lambda t: not t.is_done):
            nn_callback._validate_callback()

    def _get_tx_from_notification_data(self, provider_code, notification_data):
        """ Override of payment to find the transaction based on dummy data.

        :param str provider_code: The code of the provider that handled the transaction
        :param dict notification_data: The dummy notification data
        :return: The transaction if found
        :rtype: recordset of `payment.transaction`
        :raise: ValidationError if the data match no transaction
        """
        tx = super()._get_tx_from_notification_data(provider_code, notification_data)
        if provider_code != 'novalnet' or len(tx) == 1:
            return tx

        reference = notification_data.get('reference')
        tx = self.search([('reference', '=', reference), ('provider_code', '=', 'novalnet')])
        if not tx:
            raise ValidationError(
                "Novalnet: " + _("No transaction found matching reference %s.", reference)
            )
        return tx

    def _process_notification_data(self, notification_data):
        """ Override of payment to process the transaction based on dummy data.

        Note: self.ensure_one()

        :param dict notification_data: The dummy notification data
        :return: None
        :raise: ValidationError if inconsistent data were received
        """
        super()._process_notification_data(notification_data)
        if self.provider_code != 'novalnet':
            return

        if 'event_type' in notification_data:
            self._initiate_transaction_callback(notification_data)
            if notification_data.get('event_type') == 'PAYMENT' and self.state != 'draft':
                _logger.info(_("Callback received for event type %s but communication failure not found",
                               notification_data.get('event_type')))

                book_reference = notification_data.get('book_reference')
                if book_reference:
                    self._execute_callback()
                else:
                    return
            elif notification_data.get('event_type') != 'PAYMENT':
                self._execute_callback()

        if not notification_data.get('nn_tid'):
            raise ValidationError(_("Invalid transaction"))

        # Save the transaction ID (tid) for Redirect Payments.
        self.provider_reference = notification_data.get('nn_tid')

        if 'nn_status' in notification_data:
            if notification_data.get('nn_status') == 'FAILURE':
                self._set_error(notification_data.get('nn_status_text'))
                return
            elif notification_data.get('nn_status') == 'DEACTIVATED':
                self._set_canceled()
                return

        retrieve_transaction = self.provider_id._novalnet_make_request("transaction/details", data={
            'transaction': {'tid': notification_data.get('nn_tid')},
            'custom': {'lang': self.env.context.get('lang')}
        })

        # Check for the 'transaction' key in the response
        transaction_data = retrieve_transaction.get('transaction')

        if not transaction_data or not transaction_data.get('tid'):
            raise ValidationError(_("Invalid transaction"))

        if 'test_mode' in transaction_data:
            self.novalnet_transaction_id.novalnet_test_mode = transaction_data['test_mode']

        if 'bank_details' in transaction_data:
            self._validate_create_bank_account(transaction_data['bank_details'])

        if 'instalment' in retrieve_transaction and 'cycles_executed' in retrieve_transaction['instalment']:
            self._validate_instament_details(retrieve_transaction['instalment'], self.currency_id)

        state = RESULT_CODES_MAPPING[transaction_data['status']]

        # Novalnet token storing process
        if 'payment_data' in transaction_data and 'token' in transaction_data[
            'payment_data'] and self.payment_method_id.support_tokenization:
            _token = transaction_data['payment_data']['token']
            _token_name = ''
            if transaction_data['payment_type'] == 'CREDITCARD':
                _token_name = ("%s - %s" % (transaction_data['payment_data']['card_number'],
                                            transaction_data['payment_data']['card_brand']))
            elif transaction_data['payment_type'] in ['DIRECT_DEBIT_SEPA', 'GUARANTEED_DIRECT_DEBIT_SEPA']:
                _token_name = ("%s" % (transaction_data['payment_data']['iban']))
            self._novalnet_tokenize_from_notification_data(_token, _token_name, transaction_data)

        converted_amount = payment_utils.to_minor_currency_units(self.amount, self.currency_id)
        _novalnet_transaction_dict = {
            'paid_amount': converted_amount,
            'tid': notification_data.get('nn_tid'),
            'status': transaction_data['status'],
            'status_code': transaction_data['status_code'],
            'payment_type': transaction_data['payment_type'],
        }

        custom_data = retrieve_transaction.get('custom')
        if custom_data and 'order_lang' in custom_data:
            _novalnet_transaction_dict['nn_lang'] = custom_data['order_lang']

        # Update the payment state.
        if state == 'pending':
            _novalnet_transaction_dict['paid_amount'] = 0
            if transaction_data['payment_type'] != 'PREPAYMENT' and transaction_data['status_code'] == 100:
                state = 'done'

        if not self.novalnet_transaction_id:
            _logger.warning("Novalnet transaction details Not found")
            self.novalnet_transaction_id = self.env['payment.novalnet.transaction'].create(_novalnet_transaction_dict)
        else:
            self.novalnet_transaction_id.write(_novalnet_transaction_dict)

        # Handle nearest stores and multibanco payment info only if 'transaction' is present
        if 'nearest_stores' in transaction_data:
            self._validate_create_store_info_for_cashpayment(transaction_data['nearest_stores'])
            self.novalnet_transaction_id.novalnet_cashpayment_token = transaction_data['checkout_token']
            self.novalnet_transaction_id.novalnet_cashpayment_js = (transaction_data['checkout_js'] + '?token=' +
                                                                    transaction_data['checkout_token'])

        if {'partner_payment_reference', 'service_supplier_id'} <= set(transaction_data):
            self._validate_create_multibanco_payment_info(
                transaction_data['partner_payment_reference'],
                transaction_data['service_supplier_id']
            )

        if ('payment_data' in transaction_data and 'card_number' in transaction_data['payment_data']):
            self.novalnet_transaction_id.novalnet_wallet_card_details = (
                    transaction_data['payment_data']['card_brand'] + ' ' +
                    transaction_data['payment_data']['card_number']
            )

        _transaction_amount_dict = {
            'paid_amount': converted_amount,
        }
        self.novalnet_transaction_amount_status_id = self.env['novalnet.transaction.amount.status'].create(
            _transaction_amount_dict)

        # Update the payment state based on the transaction status
        if state == 'pending':
            self._set_pending()
        elif state == 'authorize':
            self._set_authorized()
        elif state == 'done':
            self._set_done()
            # Immediately post-process the transaction if it is a refund, as the post-processing
            # will not be triggered by a customer browsing the transaction from the portal.
            if self.operation == 'refund':
                self.env.ref('payment.cron_post_process_payment_tx')._trigger()
        elif state == 'cancel':
            self._set_canceled()
        else:  # Simulate an error state.
            self._set_error(_("You selected the following novalnet payment status: %s", state))

    def _initiate_transaction_callback(self, notification_data):
        """
        This function for initiate Novalnet callback
        """
        nn_ip = ip_interface(socket.gethostbyname('pay-nn.de'))
        request_ip = ip_interface(payment_utils.get_customer_ip_address())
        if not (nn_ip and request_ip):
            raise ValidationError(_('Unauthorized access: Missing Host or Received IP'))
        if nn_ip != request_ip and not self.provider_id.novalnet_allow_manual_testing:
            raise ValidationError(_('Unauthorized request from IP %s') % payment_utils.get_customer_ip_address())
        if 'event_type' not in notification_data or 'check_sum' not in notification_data:
            raise ValidationError(_("Could not initiate callback"))

        self.write({
            'novalnet_callback_ids': [(0, 0, {
                'event_type': notification_data.get('event_type'),
                'parent_tid': notification_data.get('nn_tid'),
                'check_sum': notification_data.get('check_sum'),
                'transaction_id': self.id,
                'callback_json': request.httprequest.data
            })],
        })

    def _set_pending(self):
        """
        Sets the current state to pending
        """
        super()._set_pending()
        if self.provider_code != 'novalnet':
            return

    def _set_authorized(self):
        """
        Sets the current state to authorized
        """
        super()._set_authorized()
        if self.provider_code != 'novalnet':
            return

    def _set_done(self):
        """
        Sets the current state to done
        """
        super()._set_done()
        if self.provider_code != 'novalnet':
            return

    def _set_error(self, error_text):
        """ Update the transactions' state to `error`."""
        super()._set_error(error_text)
        if self.provider_code != 'novalnet':
            return

    def _create_customer_payload(self, notification_data):

        """ Prepare customer data """
        first_name, last_name = payment_utils.split_partner_name(self.partner_id.name)
        customer = {
            'first_name': first_name or last_name,
            'last_name': last_name or first_name,
            'customer_ip': self.provider_id.get_client_ip_novalnet() or "",
            'customer_no': self.partner_id.id,
            'billing': {
                'city': self.partner_city or None,
                'country_code': self.partner_country_id.code or None,
                'street': self.partner_address or None,
                'zip': self.partner_zip or None,
                'state': self.partner_state_id.name or None,
            },
            'shipping': {'same_as_billing': 1},
            'email': self.partner_email or None,
            'phone': self.partner_phone or None,
        }
        order = None
        if len(self.sale_order_ids) == 1:
            order = self.sale_order_ids[0]

        partner = request.env.user.partner_id
        if partner.company_name or partner.commercial_company_name or (
                order and order.partner_invoice_id and order.partner_invoice_id.company_name):
            customer['billing']['company'] = partner.company_name or partner.commercial_company_name or (
                order.partner_invoice_id.company_name if order and order.partner_invoice_id else '')
        if order and self.partner_id.id != order.partner_shipping_id.id:
            customer['shipping'] = {
                'street': order.partner_shipping_id.street,
                'state': order.partner_shipping_id.state_id.name or None,
                'city': order.partner_shipping_id.city,
                'zip': order.partner_shipping_id.zip,
                'country_code': order.partner_shipping_id.country_id.code,
            }
            if order.partner_shipping_id.company_name or order.partner_shipping_id.commercial_company_name:
                customer['shipping']['company'] = \
                    (order.partner_shipping_id.company_name or order.partner_shipping_id.commercial_company_name)
        if 'pay_data' in notification_data and 'birth_date' in notification_data['pay_data']:
            customer['birth_date'] = notification_data['pay_data']['birth_date']
        return customer

    def _compute_due_date_from_terms(self):
        """ Compute due date from the payment terms.
        :return: duedate
        """
        im_payment_terms = payment_term_id = self.env.ref('account.account_payment_term_immediate', False).sudo()
        if len(self.sale_order_ids) > 0:
            if len(self.sale_order_ids) > 1:
                _logger.warning(
                    "Novalnet: More than one payment transaction assigned to sale.order '%s', so mapping the "
                    "sale.order to the transaction via transaction reference",
                    self.sale_order_ids)
            sale_order = self.sale_order_ids.filtered(lambda so: so.name == self.reference)
            if sale_order:
                payment_term_id = sale_order.payment_term_id

        if len(self.invoice_ids) > 0:
            if len(self.sale_order_ids) > 1:
                _logger.warning(
                    "Novalnet: More than one payment transaction assigned to account.move '%s', so mapping the "
                    "account.move to the transaction via transaction reference ",
                    self.sale_order_ids)
            inv = self.invoice_ids.filtered(lambda inv: inv.name == self.reference)
            if inv and inv.invoice_payment_term_id:
                payment_term_id = inv.invoice_payment_term_id
            elif inv and inv.invoice_date_due:
                try:
                    return inv.invoice_date_due.strftime("%Y-%m-%d")
                except:
                    _logger.warning("Could not convert invoice due-date")

        # check payment terms
        if payment_term_id and im_payment_terms.id != payment_term_id.id:
            due_date = datetime.today()
            for term_line in payment_term_id.line_ids:
                if term_line.nb_days:
                    due_date += timedelta(days=term_line.nb_days)
                else:
                    _logger.warning("Term line does not have a 'days' value: %s", term_line)
            return due_date.strftime('%Y-%m-%d')
        return False

    def set_novalnet_payment_terms(self, server_due_date):
        sale_order = inv = payment_term = None
        sale_order = self.sale_order_ids.filtered(lambda so: so.name == self.reference)
        inv = self.invoice_ids.filtered(lambda inv: inv.name == self.reference)
        current_date = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        server_due_date_obj = datetime.strptime(server_due_date, '%Y-%m-%d').replace(hour=0, minute=0, second=0,
                                                                                     microsecond=0)
        date_difference = (server_due_date_obj - current_date).days
        payment_term = self.env['account.payment.term'].search([('line_ids.nb_days', '=', date_difference)],
                                                               limit=1)
        if not payment_term:
            payment_term_vals = {
                'name': _('Novalnet payment due - {} Days').format(date_difference),
                'line_ids': [(0, 0, {
                    'nb_days': date_difference,
                    'value_amount': 100.0,
                    'value': 'percent',
                })]
            }
            # Create the new payment term
            payment_term = self.env['account.payment.term'].create(payment_term_vals)
        if payment_term:
            if sale_order:
                sale_order.write({'payment_term_id': payment_term.id})
            elif inv:
                if inv.state == 'posted':
                    # Unpost the invoice first
                    inv.button_draft()
                # Now you can modify the field
                inv.write({'invoice_payment_term_id': payment_term.id})
                # Re-post the invoice
                inv.action_post()

    def get_paypal_sheet_details(self):
        self.ensure_one()

        def to_cents(amount):
            """Safely convert currency amount to cents with proper rounding"""
            return round(float(amount or 0) * 100)

        cart_info = {
            'line_items': [],
            'items_shipping_price': 0,
            'items_tax_price': 0,
            'items_handling_price': 0
        }

        #  Case 1: Handle Sales Orders
        if self.sale_order_ids:
            order = self.sale_order_ids[0]
            _logger.info("Processing sales order %s for PayPal", order.name)

            for line in order.order_line:
                if line.product_uom_qty <= 0:
                    continue

                line_item = {
                    'category': 'physical',
                    'description': line.name or '',
                    'name': line.product_id.name if line.product_id else line.name,
                    'price': str(to_cents(line.price_unit)),  # Use helper function
                    'quantity': int(line.product_uom_qty)
                }
                cart_info['line_items'].append(line_item)

            # Use helper function for all conversions
            cart_info['items_shipping_price'] = to_cents(order.amount_total - order.amount_untaxed - order.amount_tax)
            exclude_tax_amount = sum(
                line.price_tax
                for line in order.order_line
                if line.tax_id and not any(tax.price_include for tax in line.tax_id)
            )
            cart_info['items_tax_price'] = to_cents(exclude_tax_amount)

        #  Case 2: Handle Invoices
        elif self.invoice_ids:
            invoice = self.invoice_ids[0]
            _logger.info("Processing invoice %s for PayPal", invoice.name)

            for line in invoice.invoice_line_ids:
                if line.quantity <= 0:
                    continue

                line_item = {
                    'category': 'physical',
                    'description': line.name or '',
                    'name': line.product_id.name if line.product_id else line.name,
                    'price': str(to_cents(line.price_unit)),  # Use helper function
                    'quantity': int(line.quantity)
                }
                cart_info['line_items'].append(line_item)

            # Use helper function for all conversions
            cart_info['items_shipping_price'] = to_cents(
                invoice.amount_total - invoice.amount_untaxed - invoice.amount_tax)

            exclude_tax_amount = sum(
                line.price_subtotal * (sum(tax.amount for tax in line.tax_ids if not tax.price_include) / 100)
                for line in invoice.invoice_line_ids
                if line.tax_ids
            )
            cart_info['items_tax_price'] = to_cents(exclude_tax_amount)

        _logger.info("Cart info for PayPal: %s", cart_info)
        return cart_info

    def _create_transaction_payload(self, notification_data):
        """Prepare transaction data"""
        # Get versions
        odoo_version = service.common.exp_version()['server_version']

        module = self.env.ref('base.module_payment_novalnet').installed_version
        module_version = '.'.join(module.split('.')[2:])
        # Convert amount to minor currency units
        converted_amount = payment_utils.to_minor_currency_units(self.amount, self.currency_id)

        # Initialize transaction payload
        transaction_payload = {
            'payment_type': notification_data.get('pm_data', {}).get('type', self.token_id.novalnet_payment_method),
            'amount': converted_amount,
            'system_name': f'Odoo_{odoo_version}',
            'system_version': f'{odoo_version}-NN{module_version}-NNT{self.provider_id.get_current_theme() or ""}',
            'system_ip': self.provider_id.get_system_ip() or "",
            'currency': self.currency_id.name,
            'order_no': self.reference,
        }

        # test mode
        if 'pay_data' in notification_data and 'test_mode' in notification_data['pay_data']:
            transaction_payload['test_mode'] = notification_data['pay_data']['test_mode']
        # payment data form
        payment_data_keys = ['token', 'pan_hash', 'unique_id', 'iban', 'wallet_token', 'bic', 'account_holder']

        params = {'transaction': {'payment_data': {}}}
        paydata = notification_data.get('pay_data', {})
        params['transaction']['payment_data'] = {key: paydata[key] for key in payment_data_keys if key in paydata}

        if params['transaction']['payment_data']:
            transaction_payload['payment_data'] = params['transaction']['payment_data']

        # payment process using stored token
        if self.token_id:
            payment_data = {
                'token': self.token_id.provider_ref,
            }
            transaction_payload['test_mode'] = self.token_id.novalnet_token_process_mode
            transaction_payload['payment_data'] = payment_data
            if self.token_id.novalnet_payment_method == 'DIRECT_DEBIT_SEPA':
                get_payment_terms_date = self._compute_due_date_from_terms()
                if get_payment_terms_date:
                    transaction_payload['due_date'] = get_payment_terms_date

        if 'pay_data' in notification_data:
            # create token
            if 'create_token' in notification_data['pay_data']:
                transaction_payload['create_token'] = notification_data['pay_data']['create_token']
            # do redirect params
            if 'do_redirect' in notification_data['pay_data']:
                transaction_payload['enforce_3d'] = notification_data['pay_data']['do_redirect']
            # due date params
            if 'due_date' in notification_data['pay_data']:
                get_payment_terms_date = self._compute_due_date_from_terms()
                if get_payment_terms_date:
                    transaction_payload['due_date'] = get_payment_terms_date
                else:
                    transaction_payload['due_date'] = (
                            datetime.today() + timedelta(days=int(notification_data['pay_data']['due_date']))).strftime(
                        "%Y-%m-%d")

            # bank details params
            if 'account_number' in notification_data['pay_data']:
                payment_data = {
                    'account_holder': notification_data['pay_data']['account_holder'],
                    'account_number': notification_data['pay_data']['account_number'],
                    'routing_number': notification_data['pay_data']['routing_number'],
                }
                transaction_payload['payment_data'] = payment_data
            # zero amount booking params
            if notification_data['pay_data'].get('payment_action') == 'zero_amount':
                transaction_payload['amount'] = 0
            # token params
            if 'payment_ref' in notification_data['pay_data'] and 'token' in \
                    notification_data['pay_data']['payment_ref']:
                transaction_payload['payment_data'] = params['transaction']['payment_data']
                transaction_payload['payment_data']['token'] = notification_data['pay_data']['payment_ref']['token']


        if self.operation in ['online_redirect']:
            base_url = self.provider_id.get_base_url()
            transaction_payload['return_url'] = urls.url_join(base_url, PaymentNovalnetController._return_url)
        return transaction_payload

    def _create_instalment_payload(self, notification_data):
        """Prepare instalment data"""
        instalment_payload = {
            'cycles': notification_data['pay_data']['cycle'],
            'interval': '1m',
        }
        return instalment_payload

    def _novalnet_prepare_payment_request(self, notification_data):
        """
        Prepare request data for novalnet transaction
        """
        user_lang = self.env.context.get('lang')
        customer = self._create_customer_payload(notification_data)
        transaction_payload = self._create_transaction_payload(notification_data)
        request = {
            'customer': customer,
            'custom': {
                'lang': 'EN' if user_lang == 'en_US' else 'DE',
                'input1': 'order_lang',
                'inputval1': user_lang
            },
            'transaction': transaction_payload,
        }

        get_payment_terms_date = self._compute_due_date_from_terms()
        if get_payment_terms_date:
            request['custom']['input2'] = 'payment_terms'
            request['custom']['inputval2'] = get_payment_terms_date
        if 'pm_data' in notification_data and notification_data['pm_data'].get('type') == 'PAYPAL':
            cart_info = self.get_paypal_sheet_details()
            request['cart_info'] = cart_info

        if 'payment_data' in notification_data and 'cycle' in notification_data['payment_data']:
            instalment_payload = self._create_instalment_payload(notification_data)
            request['instalment'] = instalment_payload
        return request

    def _validate_create_bank_account(self, _bank_details):
        """
        Save server response bank details
        """
        if not {'account_holder', 'bank_name', 'bank_place', 'bic', 'iban'} <= set(_bank_details):
            return
        bank_info = self.env['novalnet.payment.transaction.bank'].search(
            [('account_holder', '=', _bank_details['account_holder']), ('bank_name', '=', _bank_details['bank_name']),
             ('bic', '=', _bank_details['bic']), ('iban', '=', _bank_details['iban']),
             ('bank_place', '=', _bank_details['bank_place'])])

        if bank_info:
            self.novalnet_transaction_id.novalnet_bank_account = bank_info.id
        else:
            bank_info = self.env['novalnet.payment.transaction.bank'].create(
                {'account_holder': _bank_details['account_holder'], 'bank_place': _bank_details['bank_place'],
                 'bank_name': _bank_details['bank_name'], 'bic': _bank_details['bic'], 'iban': _bank_details['iban']})
            self.novalnet_transaction_id.novalnet_bank_account = bank_info.id

    def _validate_instament_details(self, instalment_details, currency_id):
        """
        Save server response instalment details
        """
        amount = instalment_details['cycle_amount'] / 100.0
        instalment_info = self.env['novalnet.payment.instalment.details'].create(
            {'current_executed_cycle': instalment_details['cycles_executed'],
             'due_instalment': instalment_details['pending_cycles'],
             'cycle_amount': format_amount(self.env, amount, currency_id),
             'next_instalment_date': instalment_details['next_cycle_date'],
             'instalment_all_details': instalment_details})
        self.novalnet_transaction_id.novalnet_instalment_information = instalment_info.id

    def _validate_create_store_info_for_cashpayment(self, _nearest_stores):
        """
        Save server response cash payment details
        """
        if not _nearest_stores:
            return
        store_values = []
        for key, val in _nearest_stores.items():
            store_values.append((0, 0, {
                'city': val.get('city'),
                'country_code': val.get('country_code'),
                'store_name': val.get('store_name'),
                'street': val.get('street'),
                'zip': val.get('zip'),
            }))

        self.novalnet_transaction_id.write({
            'novalnet_nearest_store_ids': store_values,
        })

    def _validate_create_multibanco_payment_info(self, _partner_payment_reference, _service_supplier_id):
        """
        Save server response multibanco payment details
        """
        if not _partner_payment_reference or not _service_supplier_id:
            return
        self.novalnet_transaction_id.novalnet_multibanco_payment_reference = _partner_payment_reference
        self.novalnet_transaction_id.novalnet_multibanco_service_supplier_id = _service_supplier_id

    def _get_specific_processing_values(self, processing_values):
        """
        Processes payment values for Novalnet, validating input data and handling server response based on
        operation.
        """
        res = super()._get_specific_rendering_values(processing_values)
        if self.provider_code != 'novalnet':
            return res
        if not self.token_id:
            payment_data = request.params.get('pay_data', {})
            pm_data = request.params.get('pm_data', {})

            if not pm_data or not payment_data:
                raise ValidationError(_("Could not find payment please try any other payment "))
            processing_values['pm_data'] = pm_data
            processing_values['payment_data'] = payment_data
            processing_values['pay_data'] = payment_data

            if not pm_data.get('type'):
                raise ValidationError(_("Could not find payment please try any other payment "))

            self._log_message_on_linked_documents(_(
                "Transaction initiated with %(provider_name)s payment type %(payment_type)s for %(ref)s.",
                provider_name=self.provider_id.name, payment_type=pm_data['name'], ref=self.reference
            ))
        payload = self._novalnet_prepare_payment_request(processing_values)
        if self.token_id:
            payment_data = 'payment'
            pm_data = ''
        endpoint = self._novalnet_prepare_end_point(payment_data)
        payment_response = self.provider_id._novalnet_make_request(endpoint, data=payload)
        if not self.novalnet_transaction_id:
            _novalnet_transaction_dict = {
                'payment_type': pm_data.get('name') if pm_data else self.token_id.novalnet_payment_type
            }
            self.novalnet_transaction_id = self.env['payment.novalnet.transaction'].create(
                _novalnet_transaction_dict)
            if 'payment_action' in payment_data and payment_data['payment_action'] == 'zero_amount':
                self.novalnet_transaction_id.zero_amount_check_flag = 1

        if self.operation in ['online_direct', 'online_token', 'offline']:
            if 'transaction' not in payment_response or 'tid' not in payment_response.get('transaction'):
                raise ValidationError(_("Invalid transaction"))
            self.provider_reference = payment_response.get('transaction')['tid']
            self.novalnet_transaction_id.tid = str(payment_response.get('transaction')['tid'])
            self.novalnet_transaction_id.status = str(payment_response.get('transaction')['status'])
            self.novalnet_transaction_id.status_code = str(payment_response.get('transaction')['status_code'])
            self.novalnet_transaction_id.payment_name = pm_data.get(
                'name') if pm_data else self.token_id.novalnet_payment_type
            self.novalnet_transaction_id.novalnet_test_mode = str(payment_response.get('transaction')['test_mode'])
            if 'invoice_ref' in payment_response['transaction']:
                self.novalnet_transaction_id.payment_reference_two = str(
                    payment_response.get('transaction')['invoice_ref'])
            if 'due_date' in payment_response['transaction']:
                transaction = payment_response.get('transaction', {})
                self.set_novalnet_payment_terms(transaction.get('due_date'))
                self.novalnet_transaction_id.novalnet_due_date = datetime.strptime(
                    transaction.get('due_date'), '%Y-%m-%d').strftime('%d/%m/%Y')
            return {'nn_tid': str(payment_response.get('transaction')['tid'])}
        elif self.operation in ['online_redirect']:
            if 'transaction' not in payment_response or 'txn_secret' not in payment_response.get(
                    'transaction') or 'redirect_url' not in payment_response.get('result'):
                raise ValidationError(_("Could not redirect to acquirer, please try again later"))
            self.novalnet_transaction_id.novalnet_txn_secret = payment_response.get('transaction')['txn_secret']
            self.novalnet_transaction_id.payment_name = str(pm_data['name'])
            self.novalnet_transaction_id.novalnet_test_mode = str(payment_data['test_mode'])
            return {'redirect_url': payment_response.get('result')['redirect_url']}

    def _get_specific_rendering_values(self, processing_values):
        """
        This function required for redirect payments
        """
        return processing_values

    def _novalnet_prepare_end_point(self, payment_data):
        """
        Prepare Novalnet payment endpoint
        """
        if not payment_data:
            return
        if 'payment_action' in payment_data and payment_data['payment_action'] == "authorized":
            return "authorize"
        return "payment"

    def _novalnet_tokenize_from_notification_data(self, _token, _token_name, transaction_data):
        self.ensure_one()
        token = self.env['payment.token'].create({
            'provider_id': self.provider_id.id,
            'payment_details': _token_name,
            'partner_id': self.partner_id.id,
            'provider_ref': _token,
            'payment_method_id': self.payment_method_id.id,
            'novalnet_payment_type': self.novalnet_transaction_id.payment_type,
            'novalnet_payment_method': transaction_data.get('payment_type'),
            'novalnet_payment_reference_id': transaction_data.get('tid'),
            'novalnet_token_process_mode': transaction_data.get('test_mode'),
        })
        self.write({
            'token_id': token,
            'tokenize': False,
        })
        _logger.info(
            "Created token with id %s for partner with id %s.", token.id, self.partner_id.id
        )

    def render_novalnet_backend_info(self, order=None):
        self.ensure_one()
        return self.env['ir.qweb']._render(
            'payment_novalnet.novalnet_payment_information',
            {
                'tx_sudo': self.sudo(),
                'order': order,
                'is_backend': True
            }
        )

# Part of Odoo. See LICENSE file for full copyright and licensing details.
"""
Handling Novalnet Callback
"""
import datetime
import json
import logging

from odoo import _, fields, models
from odoo.exceptions import ValidationError
from odoo.http import request
from odoo.tools import format_amount

from odoo.addons.payment import utils as payment_utils
from odoo.addons.payment_novalnet.const import RESULT_CODES_MAPPING

_logger = logging.getLogger(__name__)

_event_selection = [
    ('PAYMENT', 'PAYMENT'),
    ('TRANSACTION_CAPTURE', 'TRANSACTION_CAPTURE'),
    ('TRANSACTION_CANCEL', 'TRANSACTION_CANCEL'),
    ('TRANSACTION_REFUND', 'TRANSACTION_REFUND'),
    ('TRANSACTION_UPDATE', 'TRANSACTION_UPDATE'),
    ('CREDIT', 'CREDIT'),
    ('CHARGEBACK', 'CHARGEBACK'),
    ('INSTALMENT_CANCEL', 'INSTALMENT_CANCEL'),
    ('INSTALMENT', 'INSTALMENT'),
    ('PAYMENT_REMINDER_1', 'PAYMENT_REMINDER_1'),
    ('PAYMENT_REMINDER_2', 'PAYMENT_REMINDER_2'),
    ('SUBMISSION_TO_COLLECTION_AGENCY', 'SUBMISSION_TO_COLLECTION_AGENCY'),
]


class NovalnetTransactionAmountStatus(models.Model):
    """
    Represents the status of transaction amounts for Novalnet payments.

    Attributes:
    - paid_amount (int): The total amount that has been paid for the
      transaction. Defaults to 0.
    - refund_amount (int): The total amount that has been refunded for
      the transaction. Defaults to 0.
    """
    _name = 'novalnet.transaction.amount.status'
    _description = 'Novalnet transaction amount status'

    paid_amount = fields.Integer(default=0)
    refund_amount = fields.Integer(default=0)


class NovalnetCallback(models.Model):
    """
      Represents a callback from Novalnet payment gateway.

      This model stores information about callbacks received from the
      Novalnet payment gateway, including transaction details and the
      status of the callback execution.

      Attributes:
      - event_type (Selection): The type of event for the callback,
        defaulting to 'PAYMENT'.
      - parent_tid (str): The transaction ID of the parent transaction
        associated with this callback.
      - tid (str): The unique transaction ID for this callback.
      - check_sum (str): A checksum for validating the integrity of the
        callback data.
      - transaction_id (Many 2 one): A reference to the associated payment
        transaction, linking to the 'payment.transaction' model. This field
        is read-only.
      - callback_json (Text): The raw JSON request received from Novalnet,
        containing callback details. This field is required.
      - is_done (Boolean): Indicates whether the callback has already been
        executed, defaulting to False.
      """
    _name = 'novalnet.callback'
    _description = 'Novalnet callback'

    event_type = fields.Selection(selection=_event_selection, default='PAYMENT')
    parent_tid = fields.Char(string='NN Transaction ID of parent transaction ')
    tid = fields.Char(string='NN Transaction ID ')
    check_sum = fields.Char(string='checksum')

    transaction_id = fields.Many2one(string="Payment transaction", comodel_name='payment.transaction', readonly=True,
                                     domain='[("provider_id", "=", "provider_id")]', ondelete='restrict')
    callback_json = fields.Text(string="callback request from novalnet", required=True)
    is_done = fields.Boolean(string="Callback Done", help="Whether the callback has already been executed",
                             default=False)
    callback_comment = fields.Char(string='callback comments ')
    current_datetime = fields.Char(string='callback comments date')

    def _process_credit(self, data):
        """
        Handles the Novalnet callback process for credit events.
        """
        if self.event_type != 'CREDIT':
            return
        _logger.info("Entering in to Novalnt callback credit")
        converted_amount = payment_utils.to_major_currency_units(data.get('transaction')['amount'],
                                                                 self.transaction_id.currency_id)
        formatted_amount = format_amount(self.transaction_id.env, converted_amount, self.transaction_id.currency_id)
        _credit_msg = _(
            'Credit has been successfully received for the TID: %(parent_tid)s with amount on %(amount)s. Please '
            'refer PAID order details in our Novalnet Admin Portal for the TID: %(child_tid)s',
            parent_tid=self.parent_tid, child_tid=self.tid, amount=formatted_amount
        )
        converted_amount_formated = payment_utils.to_minor_currency_units(converted_amount,
                                                                          self.transaction_id.currency_id)
        # Safely retrieve transaction data
        transaction = data.get('transaction', {})
        payment_type = transaction.get('payment_type')
        transaction_amount = transaction.get('amount', 0)
        # novalnet transaction amount status table
        paid_amount_status = self.transaction_id.novalnet_transaction_amount_status_id.paid_amount
        # novalnet transaction table paid amount
        self.transaction_id.novalnet_transaction_id.paid_amount += data.get('transaction')['amount']
        credited_amount = self.transaction_id.novalnet_transaction_id.paid_amount
        # Check state of the transaction once
        is_pending_or_authorized = self.transaction_id.state in {'pending', 'authorized'}
        # Validate conditions and set transaction to done if applicable
        if (payment_type == 'INVOICE_CREDIT' and
                paid_amount_status >= converted_amount_formated and
                is_pending_or_authorized and
                paid_amount_status == credited_amount):
            self.transaction_id._set_done()
        self._display_callback_comments(_credit_msg)
        self.is_done = True

    def _process_capture(self, data):
        """
        Handles the Novalnet callback process for capture events.
        """
        if self.event_type != 'TRANSACTION_CAPTURE':
            return
        _logger.info("Entering in to Novalnt callback Capture")

        if self._check_shop_invoked_request(data):
            self.is_done = True
            _logger.info("Process already handled in the shop")
            return
        _capture_msg = _(
            'The transaction has been confirmed on %(date)s,%(time)s',
            date=datetime.datetime.now().strftime("%d-%m-%Y"),
            time=datetime.datetime.now().strftime("%H:%M:%S")
        )
        if self.transaction_id.state in 'authorized':
            transaction = data.get('transaction', {})
            payment_type = transaction.get('payment_type')
            if payment_type == 'INSTALMENT_INVOICE' or payment_type == 'INSTALMENT_DIRECT_DEBIT_SEPA':
                instalment_information = data.get('instalment', {})
                self.transaction_id._validate_instament_details(instalment_information, self.transaction_id.currency_id)
            if transaction.get('due_date') is not None:
                due_date = datetime.datetime.strptime(data['transaction']['due_date'], '%Y-%m-%d').strftime(
                    '%d/%m/%Y')
                self.transaction_id.novalnet_transaction_id.novalnet_due_date = due_date
                self.transaction_id.set_novalnet_payment_terms(transaction.get('due_date'))
            self.transaction_id._set_done()
        self._display_callback_comments(_capture_msg)
        self.is_done = True

    def _process_cancel(self, data):
        """
        Handles the Novalnet callback process for cancel events.
        """
        if self.event_type != 'TRANSACTION_CANCEL':
            return
        _logger.info("Entering in to Novalnt callback Cancel")
        if self._check_shop_invoked_request(data):
            self.is_done = True
            _logger.info("Process already handled in the shop")
            return
        _cancel_msg = _(
            'The transaction has been canceled on %(datetime)s ',
            datetime=datetime.datetime.now().strftime("%d-%m-%Y %H:%M:%S")
        )
        if self.transaction_id.state in 'authorized':
            self.transaction_id._set_canceled()
        self._display_callback_comments(_cancel_msg)
        self.is_done = True

    def _check_shop_invoked_request(self, data):
        """
        Checks if the shop has already handled the callback event.
        """
        if 'custom' in data and 'shop_invoked' in data.get('custom'):
            return True
        return False

    def _process_refund(self, data):
        """
        Handles the Novalnet callback process for refund events.
        """
        if self.event_type != 'TRANSACTION_REFUND':
            return
        _logger.info("Entering in to Novalnt callback Refund")
        _shop_invoked = self._check_shop_invoked_request(data)
        converted_amount = payment_utils.to_major_currency_units(data.get('transaction')['refund']['amount'],
                                                                 self.transaction_id.currency_id)
        formatted_amount = format_amount(self.transaction_id.env, converted_amount, self.transaction_id.currency_id)
        if self.transaction_id.refunds_count > 0:
            refund_tx_from_source = self.env['payment.transaction'].search(
                [('source_transaction_id', '=', self.transaction_id.id)], limit=1)
            refund_tx_from_nn_tid = refund_tx_from_source.filtered(lambda tx: tx.provider_reference == self.tid)
            if _shop_invoked or (refund_tx_from_nn_tid and
                                 refund_tx_from_nn_tid[0].provider_reference != self.transaction_id.provider_reference):
                _logger.info("Callback received for already executed event")
                self.is_done = True
                return

        _refund_msg = _(
            'Refund has been initiated for the TID: %(parent_tid)s with the amount -%(amount)s. New TID:%('
            'child_tid)s for the refunded amount',
            parent_tid=self.parent_tid, amount=formatted_amount, child_tid=self.tid
        )
        refund_tx = self.transaction_id._create_child_transaction(converted_amount, is_refund=True)
        if refund_tx:
            refund_tx.provider_reference = self.tid
            refund_tx._set_done()
        self._display_callback_comments(_refund_msg)
        self.is_done = True

    def _process_chargeback(self, data):
        """
        Handles the Novalnet callback process for chargeback events.
        """
        if self.event_type != 'CHARGEBACK':
            return
        _logger.info("Entering in to Novalnt callback Chargeback")
        converted_amount = payment_utils.to_major_currency_units(data.get('transaction')['amount'],
                                                                 self.transaction_id.currency_id)
        formatted_amount = format_amount(self.transaction_id.env, converted_amount, self.transaction_id.currency_id)
        _chargeback_msg = _(
            'Chargeback executed successfully for the TID: %(parent_tid)s amount: %(amount)s on %(datetime)s . The '
            'subsequent TID: %(child_tid)s',
            parent_tid=self.parent_tid, amount=formatted_amount, child_tid=self.tid,
            datetime=datetime.datetime.now().strftime("%d-%m-%Y %H:%M:%S")
        )
        self._display_callback_comments(_chargeback_msg)
        self.is_done = True

    def _process_update(self, data):
        """
        Handles the Novalnet callback process for transaction update events.
        """
        if self.event_type != 'TRANSACTION_UPDATE':
            return
        _logger.info("Entering in to Novalnt callback TRANSACTION_UPDATE")
        converted_amount = payment_utils.to_major_currency_units(data.get('transaction')['amount'],
                                                                 self.transaction_id.currency_id)
        formatted_amount = format_amount(self.transaction_id.env, converted_amount, self.transaction_id.currency_id)

        update_type = data.get('transaction')['update_type']
        if update_type == 'AMOUNT_DUE_DATE':
            _update_msg = _(
                'The transaction has been updated with amount and due date',
            )
        elif update_type == 'DUE_DATE':
            _update_msg = _(
                'The transaction has been updated with a new due date',
            )
        elif update_type == 'AMOUNT':
            _update_msg = _(
                'Transaction amount %(amount)s has been updated successfully on %(datetime)s',
                amount=formatted_amount, datetime=datetime.datetime.now().strftime("%d-%m-%Y %H:%M:%S")
            )
        elif update_type == 'STATUS':
            _update_msg = _(
                'Transaction updated successfully for the TID: %(parent_tid)s with the amount %(amount)s on %('
                'datetime)s ',
                parent_tid=self.parent_tid, amount=formatted_amount,
                datetime=datetime.datetime.now().strftime("%d-%m-%Y %H:%M:%S")
            )
            if 'status' not in data.get('transaction'):
                self.is_done = True
                raise ValidationError('Status Not found')
            state = RESULT_CODES_MAPPING[data.get('transaction')['status']]
            if self.transaction_id.state == state:
                self.is_done = True
                _logger.info(" Order already in the same state ")
                return
            if self.transaction_id.state == 'cancel':
                return
            if state == 'pending':
                self.transaction_id._set_pending()
            elif state == 'authorize':
                transaction = data.get('transaction', {})
                _update_msg = _(
                    'The transaction status has been changed from pending to on-hold for the TID: %(parent_tid)s on '
                    '%(date)s &  %(time)s',
                    parent_tid=self.parent_tid, amount=formatted_amount,
                    date=datetime.datetime.now().strftime("%d-%m-%Y"),
                    time=datetime.datetime.now().strftime("%H:%M:%S")
                )
                if transaction.get('due_date') is not None:
                    self.transaction_id.set_novalnet_payment_terms(transaction.get('due_date'))
                self.transaction_id._set_authorized()
            elif state == 'done':
                transaction = data.get('transaction', {})
                payment_type = transaction.get('payment_type')
                if payment_type == 'INSTALMENT_INVOICE' or payment_type == 'INSTALMENT_DIRECT_DEBIT_SEPA':
                    instalment_information = data.get('instalment', {})
                    self.transaction_id._validate_instament_details(instalment_information,
                                                                    self.transaction_id.currency_id)
                if transaction.get('due_date') is not None:
                    due_date = datetime.datetime.strptime(data['transaction']['due_date'], '%Y-%m-%d').strftime(
                        '%d/%m/%Y')
                    self.transaction_id.novalnet_transaction_id.novalnet_due_date = due_date
                    self.transaction_id.set_novalnet_payment_terms(transaction.get('due_date'))
                self.transaction_id._set_done()
            elif state == 'cancel':
                self.transaction_id._set_canceled()
        self._display_callback_comments(_update_msg)
        self.is_done = True

    def _process_instalment(self, data):
        """
        Handles the Novalnet callback process for instalment events.
        """
        if self.event_type != 'INSTALMENT':
            return
        converted_amount = payment_utils.to_major_currency_units(data.get('instalment')['cycle_amount'],
                                                                 self.transaction_id.currency_id)
        formatted_cycle_amount = format_amount(self.transaction_id.env, converted_amount,
                                               self.transaction_id.currency_id)
        instalment_comments_msgs = [
            _('A new instalment has been received for the Transaction ID: %(parent_tid)s with amount %(cycle_amount)s '
              'on %(datetime)s. The new instalment transaction ID is: %(child_tid)s\n') % {
                'parent_tid': self.parent_tid,
                'cycle_amount': formatted_cycle_amount,
                'datetime': datetime.datetime.now().strftime("%d-%m-%Y %H:%M:%S"),
                'child_tid': self.tid
            }
        ]

        if data.get('instalment'):
            instalment_comments_msgs.append(_('Instalment information:\n'))
        instalment_comments_msgs.append(_('Current Instalment Cycle: %(current_executed_cycle)s.\n') % {
            'current_executed_cycle': data.get('instalment')['cycles_executed']
        })
        instalment_comments_msgs.append(_('Due instalments: %(due_instalment)s.\n') % {
            'due_instalment': data.get('instalment')['pending_cycles']
        })
        instalment_comments_msgs.append(_('Cycle amount: %(cycle_amount)s.\n') % {
            'cycle_amount': formatted_cycle_amount
        })
        instalment_data = data.get('instalment')
        if instalment_data and 'next_cycle_date' in instalment_data:
            instalment_comments_msgs.append(_('Next instalment date: %(next_instalment_date)s.\n') % {
                'next_instalment_date': data.get('instalment')['next_cycle_date']
            })

        all_instalment_comments_msg = ''.join(instalment_comments_msgs)
        self._display_callback_comments(all_instalment_comments_msg)
        self.is_done = True

    def _process_instalment_cancel(self, data):
        """
        Handles the Novalnet callback process for instalment cancel events.
        """
        if self.event_type != 'INSTALMENT_CANCEL':
            return
        if (data.get('instalment')['cancel_type'] == 'ALL_CYCLES' or
                data.get('instalment')['cancel_type'] == 'REMAINING_CYCLES'):
            parent_tid = self.parent_tid or self.tid
            _instalment_cancel_msg = _(
                'Instalment has been stopped for the TID :  %(parent_tid)s on %(datetime)s',
                parent_tid=parent_tid, datetime=datetime.datetime.now().strftime("%d-%m-%Y %H:%M:%S"))
            if data.get('instalment')['cancel_type'] == 'ALL_CYCLES':
                converted_amount = payment_utils.to_major_currency_units(data.get('transaction')['refund']['amount'],
                                                                         self.transaction_id.currency_id)
                formatted_amount = format_amount(self.transaction_id.env, converted_amount,
                                                 self.transaction_id.currency_id)
                _instalment_cancel_msg = _(
                    'Instalment has been cancelled for the TID: %(parent_tid)s on %(datetime)s & Refund has been '
                    'initiated with the amount -%(refund_amount)s',
                    parent_tid=self.parent_tid, datetime=datetime.datetime.now().strftime("%d-%m-%Y %H:%M:%S"),
                    refund_amount=formatted_amount)
                self.transaction_id._set_canceled(extra_allowed_states=('done',))
            self._display_callback_comments(_instalment_cancel_msg)
            self.is_done = True

    def _process_payment_reminder(self):
        """
        Handles the Novalnet callback process for payment reminder events.
        """

        if self.event_type not in ['PAYMENT_REMINDER_1', 'PAYMENT_REMINDER_2']:
            return
        event_type = self.event_type.split('_')
        payment_reminder_no = format(event_type[2])
        _payment_remainder_msg = _('Payment Reminder %(remainder_no)s has been sent to the customer.',
                                   remainder_no=payment_reminder_no)
        self._display_callback_comments(_payment_remainder_msg)
        self.is_done = True

    def _process_collection_submission(self, data):
        """
        Handles the Novalnet callback process for collection submission events.
        """
        if self.event_type != 'SUBMISSION_TO_COLLECTION_AGENCY':
            return
        _submission_collection_msg = _(
            'The transaction has been submitted to the collection agency. Collection Reference: %('
            'collection_reference)s',
            collection_reference=data.get('collection')['reference'])
        self._display_callback_comments(_submission_collection_msg)
        self.is_done = True

    def _handle_zero_amount_booking(self, data):
        """Handle Zero Amount Booking Process"""
        if self.event_type != 'PAYMENT':
            return
        parent_tid = self.parent_tid or self.tid
        converted_amount = payment_utils.to_major_currency_units(data.get('transaction')['amount'],
                                                                 self.transaction_id.currency_id)
        formatted_amount = format_amount(self.transaction_id.env, converted_amount,
                                         self.transaction_id.currency_id)
        _zero_amount_booking_msg = _(
            'Your order has been booked with the amount of %(amount)s. Your new TID for the booked amount: %('
            'parent_tid)s',
            amount=formatted_amount,
            parent_tid=parent_tid)
        self._display_callback_comments(_zero_amount_booking_msg)

    def _send_callback_email(self, comment):
        """
        Handles the send callback process emails.
        """
        if not self.transaction_id.provider_id.novalnet_webhook_send_mail:
            return
        mail_template = request.env.ref('payment_novalnet.novalnet_callback_notification').sudo()
        _subject = 'Novalnet odoo callback script'
        _email_to = self.transaction_id.provider_id.novalnet_webhook_send_mail
        _email_from = "no-reply@odoo.com"
        _values = {'comments': comment}
        mail_template.with_context(_values).send_mail(self.transaction_id.id,
                                                      email_values={'email_to': _email_to, 'email_from': _email_from,
                                                                    'subject': _subject, })

    def _display_callback_comments(self, callback_comments):
        self.transaction_id._log_message_on_linked_documents(callback_comments)
        self.callback_comment = callback_comments
        get_datetime = fields.Datetime.now()
        self.current_datetime = get_datetime.strftime('%b %d, %Y, %I:%M:%S %p')
        self._send_callback_email(callback_comments)

    def _validate_callback(self):
        """
        Handles the validate Novalnet callback events
        """
        data = json.loads(self.callback_json)
        self.tid = data.get('event')['tid']
        order_lang = data.get('custom')['order_lang']
        if order_lang == 'de_DE':
            self = self.with_context(lang=order_lang)
        if self.event_type == 'PAYMENT' and data.get('custom', {}).get('book_reference'):
            self._handle_zero_amount_booking(data)
            return
        if self.event_type == 'PAYMENT':
            self.is_done = True
            return


        # Dictionary to map event types to processing functions
        event_handler = {
            'CREDIT': self._process_credit,
            'TRANSACTION_CAPTURE': self._process_capture,
            'TRANSACTION_CANCEL': self._process_cancel,
            'TRANSACTION_REFUND': self._process_refund,
            'CHARGEBACK': self._process_chargeback,
            'TRANSACTION_UPDATE': self._process_update,
            'INSTALMENT': self._process_instalment,
            'INSTALMENT_CANCEL': self._process_instalment_cancel,
            'PAYMENT_REMINDER_1': self._process_payment_reminder,
            'PAYMENT_REMINDER_2': self._process_payment_reminder,
            'SUBMISSION_TO_COLLECTION_AGENCY': self._process_collection_submission
        }
        # Invoke the appropriate handler if the event type matches
        handler = event_handler.get(self.event_type)
        if handler:
            if self.event_type in ['PAYMENT_REMINDER_1', 'PAYMENT_REMINDER_2']:
                handler()
            else:
                handler(data)

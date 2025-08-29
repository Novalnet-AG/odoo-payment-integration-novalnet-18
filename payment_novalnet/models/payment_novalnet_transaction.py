"""
Create model for Novalnet payment transaction
"""
import logging

from odoo import _, fields, models, api

_logger = logging.getLogger(__name__)


class PaymentTransaction(models.Model):
    """
       Represents a Novalnet payment transaction.

       This model stores detailed information about Novalnet transactions,
       including payment status, amounts, and associated data. It is used
       to track and manage payment processing within the Odoo framework.
       """
    _name = 'payment.novalnet.transaction'
    _description = 'Novalnet transaction details'

    tid = fields.Char(string='NN Transaction ID ')
    payment_type = fields.Char(string="Payment Method Code")
    status = fields.Char(string='Transaction status ')
    payment_name = fields.Char(string='Payment Name')
    status_code = fields.Char(string='Transaction status_code')
    paid_amount = fields.Integer(default=0)
    refund_amount = fields.Integer(default=0)
    novalnet_txn_secret = fields.Char(string="Transaction secret is a temporary identifier for the payment types with "
                                             "the redirect flow and it travels across the transaction, "
                                             "useful in verifying the payment result")
    novalnet_bank_account = fields.Many2one('novalnet.payment.transaction.bank', string="Bank details to which "
                                                                                        "customer has to transfer the "
                                                                                        "transaction amount ")
    payment_reference_two = fields.Char(string='Payment Reference two ')
    novalnet_multibanco_payment_reference = fields.Char(string="The payment reference for the Multibanco payment "
                                                               "type. Using this reference, the customer pays in "
                                                               "online portal or in the Multibanco ATM to complete "
                                                               "the purchase")
    novalnet_multibanco_service_supplier_id = fields.Char(string="Service supplier ID from Multibanco")
    novalnet_nearest_store_ids = fields.One2many(string="Store details to which customer has to transfer the "
                                                        "transaction amount, Applies only for cashpayment",
                                                 comodel_name='novalnet.payment.transaction.store',
                                                 inverse_name='novalnet_nearest_store_ids')
    novalnet_due_date = fields.Char(string="Novalnet due date for Invoice, Prepayment, Direct Debit Sepa , Guaranteed "
                                           "Invoice , Guaranteed Direct Debit Sepa , Cashpayment")
    novalnet_instalment_information = fields.Many2one('novalnet.payment.instalment.details', string="Novalnet "
                                                                                                    "Instalment "
                                                                                                    "Details for "
                                                                                                    "Instalment "
                                                                                                    "Payments ")
    novalnet_wallet_card_details = fields.Char(string='Wallet Payment Card Details')
    novalnet_test_mode = fields.Char(string='Novalnet Test Mode')
    novalnet_cashpayment_token = fields.Text(string='Novalnet Cash Payment token')
    novalnet_cashpayment_js = fields.Char(string='Novalnet Cash Payment JS Script URL')
    zero_amount_check_flag = fields.Char(string='Check Zero Amount Transaction')
    nn_lang = fields.Char(string='Novalnet Payment Language')
    novalnet_extension_comment_update = fields.Char(string='Novalnet Extension Comment Update')

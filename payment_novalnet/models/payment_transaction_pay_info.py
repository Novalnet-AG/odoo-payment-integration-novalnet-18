"""
Store Novalnet Transaction Payment Informationy
"""
from odoo import fields, models


class NovalnetPaymentTransactionBank(models.Model):
    """
     Store Novalnet Bank Details
    """
    _name = 'novalnet.payment.transaction.bank'
    _description = 'Novalnet bank details for a transaction'

    account_holder = fields.Char(string="Account holder name")
    bank_name = fields.Char(string="Name of the bank that need to be transferred")
    bank_place = fields.Char(string="Place of the bank that need to be transferred")
    bic = fields.Char(string="BIC")
    iban = fields.Char(string="IBAN")


class NovalnetPaymentTransactionStore(models.Model):
    """
    Store Novalnet Cashpayment Details
    """
    _name = 'novalnet.payment.transaction.store'
    _description = 'Novalnet store details for a transaction'

    novalnet_nearest_store_ids = fields.Many2one(
            string="Store details to which customer has to transfer the transaction amount, Applies only for "
                   "cashpayment ", comodel_name='payment.novalnet.transaction', readonly=True, ondelete='restrict')
    city = fields.Char(string="City of the store")
    country_code = fields.Char(string="Country Code of the store")
    store_name = fields.Char(string="Store name")
    street = fields.Char(string="Street")
    zip = fields.Char(string="zip")


class NovalnetPaymentInstalmentDetails(models.Model):
    """
    Store Novalnet Instalment Details
    """
    _name = 'novalnet.payment.instalment.details'
    _description = 'Novalnet Instalment Details'

    current_executed_cycle = fields.Integer(string="Current Cycle")
    due_instalment = fields.Integer(string="Due Instalment")
    cycle_amount = fields.Char(string="Cycle Amount")
    next_instalment_date = fields.Char(string="Next Instalment Date")
    instalment_all_details = fields.Json(string="Instalment All Details")

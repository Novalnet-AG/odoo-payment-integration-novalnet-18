# Part of Odoo. See LICENSE file for full copyright and licensing details

from odoo import fields, models


class PaymentToken(models.Model):
    _inherit = 'payment.token'

    novalnet_payment_method = fields.Char(
        string="novalnet payment method", help="This used for mapping payment method for particular token",
        readonly=True)
    novalnet_payment_reference_id = fields.Char(
        string="novalnet reference store", help="Store novalnet token reference",
        readonly=True)
    novalnet_token_process_mode = fields.Char(
        string="novalnet process mode", help="Store novalnet process mode",
        readonly=True)
    novalnet_payment_type = fields.Char(
        string="novalnet payment type", help="Store novalnet payment type",
        readonly=True)

    def _build_display_name(self, *args, should_pad=True, **kwargs):
        """ Override of `payment` to build the display name without padding.
        Note: self.ensure_one()
        :param list args: The arguments passed by QWeb when calling this method.
        :param bool should_pad: Whether the token should be padded or not.
        :param dict kwargs: Optional data.
        :return: The novlanet token name.
        :rtype: str
        """
        if self.provider_code != 'novalnet':
            return super()._build_display_name(*args, should_pad=should_pad, **kwargs)
        return super()._build_display_name(*args, should_pad=False, **kwargs)

    def _get_available_tokens(self, providers_ids, partner_id, is_validation=False, **kwargs):
        # Fetch tokens using the super method
        tokens = super()._get_available_tokens(providers_ids, partner_id, is_validation, **kwargs)
        novalnet_tokens = tokens.filtered(lambda t: t.provider_id.name == 'Novalnet' and t.payment_details)
        other_tokens = tokens.filtered(lambda t: t.provider_id.name != 'Novalnet')
        filtered_tokens = novalnet_tokens + other_tokens
        return filtered_tokens

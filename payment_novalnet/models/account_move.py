import logging

from odoo import _, fields, models, api

_logger = logging.getLogger(__name__)


class AccountMove(models.Model):
    _inherit = 'account.move'

    novalnet_invoice_info_html = fields.Html(
        string="Payment Information:",
        compute="_compute_novalnet_invoice_info_html",
        sanitize=False,
    )

    @api.depends('payment_ids')
    def _compute_novalnet_invoice_info_html(self):
        for move in self:
            tx = move.transaction_ids.filtered(lambda t: t.provider_id.code == 'novalnet')[:1]
            if tx:
                move.novalnet_invoice_info_html = tx.render_novalnet_backend_info(order=move)
            else:
                move.novalnet_invoice_info_html = ''

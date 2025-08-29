import logging

from odoo import _, fields, models, api

_logger = logging.getLogger(__name__)


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    novalnet_backend_order_info_html = fields.Html(
        string="Payment Information:",
        compute="_compute_novalnet_info_html",
        sanitize=False
    )

    @api.depends('transaction_ids')
    def _compute_novalnet_info_html(self):
        for order in self:
            tx = order.transaction_ids.filtered(lambda t: t.provider_id.code == 'novalnet')[:1]
            if tx:
                order.novalnet_backend_order_info_html = tx.render_novalnet_backend_info(order=order)
            else:
                order.novalnet_backend_order_info_html = ''

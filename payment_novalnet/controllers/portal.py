# Part of Odoo. See LICENSE file for full copyright and licensing details.
"""
Novalnet Payment Portal Controller.

This class extends the PaymentPortal to handle Novalnet-specific payment
processes. It provides methods for managing customer interactions with
the payment system, including payment confirmation, refunds, and
transaction history.
"""

from odoo import _
from odoo.exceptions import AccessError, ValidationError
from odoo.addons.payment.controllers import portal
import logging

_logger = logging.getLogger(__name__)


class NovalnetPaymentPortal(portal.PaymentPortal):

    @staticmethod
    def _validate_transaction_kwargs(kwargs, additional_allowed_keys=()):
        """ Verify that the keys of a transaction route's kwargs are all whitelisted.

        The whitelist consists of all the keys that are expected to be passed to a transaction
        route, plus optional contextually allowed keys.

        This method must be called in all transaction routes to ensure that no undesired kwarg can
        be passed as param and then injected in the create values of the transaction.

        :param dict kwargs: The transaction route's kwargs to verify.
        :param tuple additional_allowed_keys: The keys of kwargs that are contextually allowed.
        :return: None
        :raise ValidationError: If some kwargs keys are rejected.
        """
        whitelist = {
            'provider_id',
            'payment_method_id',
            'token_id',
            'amount',
            'flow',
            'tokenization_requested',
            'landing_route',
            'is_validation',
            'csrf_token',
            'pay_data',
            'pm_data'
        }
        whitelist.update(additional_allowed_keys)
        rejected_keys = set(kwargs.keys()) - whitelist
        if rejected_keys:
            raise ValidationError(
                _("The following kwargs are not whitelisted: %s", ', '.join(rejected_keys))
            )

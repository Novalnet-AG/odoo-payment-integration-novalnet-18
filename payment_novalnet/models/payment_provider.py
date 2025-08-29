"""
    This model represents a payment provider in the Odoo system. It handles
    integration with various payment gateways, facilitating the processing of
    transactions, managing payment methods, and storing configuration settings
    specific to each provider.
"""
import base64
import logging
import pprint
import re
import requests
import socket
from odoo.http import request

from odoo import _, api, fields, models, service, http
from odoo.exceptions import ValidationError, UserError
from werkzeug import urls

from odoo.addons.payment import utils as payment_utils
from odoo.addons.payment_novalnet import const
from odoo.addons.payment_novalnet.controllers.main import PaymentNovalnetController

_logger = logging.getLogger(__name__)


class NovalnetTariff(models.Model):
    """
    Represents a Novalnet tariff.

    This model stores information about tariffs related to Novalnet payment
    processing. Tariffs define the pricing structure and conditions for
    various payment methods offered by Novalnet.

    Attributes:
    - name (str): The name of the tariff, which can be translated into
      different languages.
    - tariff_id (int): The unique identifier for the tariff as defined
      by Novalnet.
    - tariff_type (int): The type of tariff, indicating the category or
      characteristics of the tariff (e.g., fixed, variable).
    - project_id (int): An identifier linking the tariff to a specific
      project, allowing for project-specific configurations.
    """
    _name = 'novalnet.tariff'
    _description = 'Novalnet tariff'

    name = fields.Char(translate=True)
    tariff_id = fields.Integer()
    tariff_type = fields.Integer()
    project_id = fields.Integer()


class PaymentProvider(models.Model):
    """
    Payment Provider Extension for Novalnet.

    This model extends the existing payment provider functionality in Odoo
    to include support for the Novalnet payment gateway. It adds specific
    fields required for integrating with Novalnet services, including
    product activation keys 'and' etc.
    """
    _inherit = 'payment.provider'

    code = fields.Selection(selection_add=[('novalnet', 'Novalnet')], ondelete={'novalnet': 'set default'})
    novalnet_product_activation_key = fields.Char(string='Product Activation Key', help='Get your Product activation '
                                                                                        'key from the Novalnet Admin '
                                                                                        'Portal: Projects > Choose '
                                                                                        'your project > API '
                                                                                        'credentials > API Signature '
                                                                                        '(Product activation key)')
    novalnet_payment_access_key = fields.Char(string='Payment Access Key', help='Get your Payment access key from the '
                                                                                'Novalnet Admin Portal: Projects > '
                                                                                'Choose your project > API '
                                                                                'credentials > Payment access key')
    novalnet_traiff = fields.Selection(selection='_get_tariff_options', string='Select Tariff ID', help='Select a '
                                                                                                        'Tariff ID to'
                                                                                                        ' match the '
                                                                                                        'preferred '
                                                                                                        'tariff plan '
                                                                                                        'you created '
                                                                                                        'at the '
                                                                                                        'Novalnet '
                                                                                                        'Admin Portal '
                                                                                                        'for this '
                                                                                                        'project')
    hide_novalnet_tariff = fields.Boolean(default=False)
    novalnet_allow_manual_testing = fields.Boolean(string='Allow manual testing of the Notification / Webhook URL',
                                                   help='Enable this to test the Novalnet Notification / Webhook URL '
                                                        'manually. Disable this before setting your shop live to '
                                                        'block unauthorized calls from external parties', default=False)

    # Hide tariff id if 'novalnet_product_activation_key', 'novalnet_payment_access_key' is empty
    @api.onchange('novalnet_product_activation_key', 'novalnet_payment_access_key')
    def _on_change_novalnet_keys(self):
        if not self.novalnet_product_activation_key or not self.novalnet_payment_access_key:
            self.hide_novalnet_tariff = False

    # Get tariff id in novalnet.tariff table
    def _get_tariff_options(self):
        tariff_model = self.env['novalnet.tariff']
        tariffs = tariff_model.search([])
        return [(str(tariff.tariff_id), tariff.name) for tariff in tariffs]

    # Generate and Return Webhook URL
    @api.model
    def _default_webhook_url(self):
        base_url = self.get_base_url()
        return urls.url_join(base_url, PaymentNovalnetController.webhook_url)

    novalnet_webhook_url = fields.Char(string='Notification / Webhook URL', help='Notification / Webhook URL is '
                                                                                 'required to keep the merchant’s '
                                                                                 'database/system synchronized with '
                                                                                 'the Novalnet account (e.g. delivery '
                                                                                 'status). Refer the Installation '
                                                                                 'Guide for more information',
                                       default=_default_webhook_url, readonly=True)
    novalnet_webhook_send_mail = fields.Char(string='Send e-mail to', type="email", help='Notification / Webhook URL '
                                                                                         'execution messages will be '
                                                                                         'sent to this e-mail')

    # Webhook Novalnet mail Validator
    @api.constrains('novalnet_webhook_send_mail')
    def _check_email_format(self):
        email_regex = r'^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$'
        if isinstance(self, models.Model):
            records = self
        else:
            records = self.browse([self.id])
        for record in records:
            if record.novalnet_webhook_send_mail and not re.match(email_regex, record.novalnet_webhook_send_mail):
                raise ValidationError("Email address is not valid.")

    # Get Merchant Details
    def get_novalnet_merchant_details(self):
        """
        Get Novalnet Merchant Details
        """
        if not self.novalnet_product_activation_key or not self.novalnet_payment_access_key or self.code != 'novalnet':
            raise ValidationError("Novalnet: " + _("Mandatory fields are missing"))
        data = {"merchant": {'signature': self.novalnet_product_activation_key}}
        get_merchant_details = self._novalnet_make_request("merchant/details", data=data)
        if (get_merchant_details.get('result')['status'] == 'SUCCESS' and
                get_merchant_details.get('result')['status_code'] == 100):
            self.hide_novalnet_tariff = True
            merchant_project_id = get_merchant_details.get('merchant')['project']
            check_novalnet_traiff = get_merchant_details.get('merchant')['tariff']
            self.env['novalnet.tariff'].search([]).unlink()
            if check_novalnet_traiff:
                for tariff_id, val in get_merchant_details.get('merchant')['tariff'].items():
                    create_dict = {'name': val['name'], 'tariff_id': tariff_id, 'tariff_type': val['type'],
                                   'project_id': merchant_project_id}
                    self.env['novalnet.tariff'].create(create_dict)
                return {'type': 'ir.actions.client', 'tag': 'reload'}
        else:
            raise ValidationError("Novalnet: " + _(get_merchant_details.get('result')['status_text']))

    # Send Call for Webhook
    def novalnet_webhook_config_btn(self):
        """
        This function for Novalnet webhook configuration
        """
        if not self.novalnet_product_activation_key or not self.novalnet_payment_access_key or self.code != 'novalnet':
            raise ValidationError("Novalnet: " + _("Mandatory fields are missing"))
        data = {"webhook": {'url': self.novalnet_webhook_url}}
        get_webhook_connect_response = self._novalnet_make_request("webhook/configure", data=data)
        if get_webhook_connect_response.get('result', {}).get(
                'status') == 'SUCCESS' and get_webhook_connect_response.get('result', {}).get('status_code') == 100:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Success',
                    'message': 'Notification / Webhook URL is configured successfully in Novalnet Admin Portal',
                    'type': 'success',
                    'sticky': False,
                }
            }

        else:
            raise ValidationError((get_webhook_connect_response.get('result', {}).get('status_text')))

    # Override of `payment` to enable additional features.
    def _compute_feature_support_fields(self):
        super()._compute_feature_support_fields()
        self.filtered(lambda p: p.code == 'novalnet').update({
            'support_manual_capture': 'partial',
            'support_refund': 'partial',
        })

    # Form customer params
    def _create_customer_payload_order(self, order, partner_id):
        billing_address = order.partner_invoice_id
        shipping_address = order.partner_shipping_id
        first_name, last_name = payment_utils.split_partner_name(billing_address.name or partner_id.name)
        customer = {
            'first_name': first_name or last_name,
            'last_name': last_name or first_name,
            'customer_ip': self.get_client_ip_novalnet(),
            'customer_no': partner_id.id,
            'billing': {
                'city': billing_address.city or None,
                'country_code': billing_address.country_id.code or None,
                'street': billing_address.street or None,
                'zip': billing_address.zip or None,
                'state': billing_address.state_id.name or None,
            },
            'shipping': {'same_as_billing': 1},
            'email': partner_id.email or None,
            'phone': partner_id.phone or None,
        }
        if partner_id.company_name or partner_id.commercial_company_name or billing_address.company_name:
            customer['billing'][
                'company'] = partner_id.company_name or partner_id.commercial_company_name or billing_address.company_name
        if len(order) > 1:
            order = order[0]
        if not (self.check_address_equal(billing_address, shipping_address)):
            customer['shipping'] = {
                'city': shipping_address.city or None,
                'country_code': shipping_address.country_id.code or None,
                'street': shipping_address.street or None,
                'zip': shipping_address.zip or None,
                'state': shipping_address.state_id.name or None,
            }
            if order.partner_shipping_id.company_name or order.partner_shipping_id.commercial_company_name or shipping_address.company_name:
                customer['shipping'][
                    'company'] = (order.partner_shipping_id.company_name or
                                  order.partner_shipping_id.commercial_company_name or shipping_address.company_name)
        return customer

    # Function to compare two addresses
    @staticmethod
    def check_address_equal(billing, shipping):
        """
        Check Billing and Shipping address are equal
        """
        return (billing['city'] == shipping['city'] and
                billing['country_code'] == shipping['country_code'] and
                billing['street'] == shipping['street'] and
                billing['zip'] == shipping['zip'] and
                billing['state_id']['name'] == shipping['state_id']['name'])

    def get_current_theme(self):
        """
        Get Current theme
        """
        themes = self.env['ir.module.module'].with_context(active_test=True).search([
            ('category_id', 'child_of', self.env.ref('base.module_category_theme').id),
        ], order='name')

        theme_name = None  # Initialize theme_name

        for theme in themes:
            theme_name = theme.name  # Update theme_name in the loop
            break  # Exit after the first theme to get the current theme

        return theme_name if theme_name is not None else ''

    def get_system_ip(self):
        try:
            hostname = socket.gethostname()
            system_ip = socket.gethostbyname(hostname)
            return system_ip if system_ip else ""
        except Exception:
            return ""

    # Form transaction params
    def _create_transaction_order_payload(self, order, currency):
        odoo_version = service.common.exp_version()['server_version']
        module = self.env.ref('base.module_payment_novalnet').installed_version
        module_version = '.'.join(module.split('.')[2:])
        converted_amount = payment_utils.to_minor_currency_units(order.amount_total, currency)
        transaction_payload = {
            'amount': converted_amount,
            'system_name': 'Odoo',
            'system_version': f'{odoo_version}-NN{module_version}-NNT{self.get_current_theme() or ""}',
            'system_ip': self.get_system_ip() or "",
            'currency': currency.name,
            'order_no': order.reference,
        }
        return transaction_payload

    # Load payment page and seamless payment call perform
    def _novalnet_load_payment_page(self, order, amount, currency, partner_id, invoice=None):

        if invoice:
            return self.invoice_payment_flow(invoice, amount, currency)
        if order is None:
            return self.donation_process(amount, currency, partner_id)
        if order:
            customer = self._create_customer_payload_order(order, partner_id)
            transaction_payload = self._create_transaction_order_payload(order, currency)
            data = {
                'customer': customer,
                'transaction': transaction_payload,
                'hosted_page': {
                    'type': 'PAYMENTFORM'
                }
            }
            seamless_payment = self._novalnet_make_request("seamless/payment", data=data)
            if 'result' in seamless_payment and 'redirect_url' in seamless_payment.get('result'):
                return seamless_payment.get('result')['redirect_url']
        return

    def invoice_payment_flow(self, invoice_data, amount, currency):
        converted_amount = payment_utils.to_minor_currency_units(amount, currency)
        odoo_version = service.common.exp_version()['server_version']
        module_version = self.env.ref('base.module_payment_novalnet').installed_version
        first_name, last_name = payment_utils.split_partner_name(invoice_data.partner_id.name)
        data = {
            'customer': {
                'first_name': first_name or last_name,
                'last_name': last_name or first_name,
                'customer_ip': self.get_client_ip_novalnet(),
                'customer_no': invoice_data.partner_id.id,
                'email': invoice_data.partner_id.email or None,
                'phone': invoice_data.partner_id.phone or invoice_data.partner_id.mobile or None,
                'billing': {
                    'city': invoice_data.partner_id.city or None,
                    'country_code': invoice_data.partner_id.country_id.code or None,
                    'street': invoice_data.partner_id.street or None,
                    'zip': invoice_data.partner_id.zip or None,
                    'state': invoice_data.partner_id.state_id.name or None,
                },
                'shipping': {'same_as_billing': 1},
            },
            'transaction': {
                'amount': converted_amount,
                'system_name': 'Odoo',
                'system_version': f'{odoo_version}-NN{module_version}-NNT{self.get_current_theme() or ""}',
                'system_ip': self.get_system_ip() or "",
                'currency': currency.name,
            },
            'hosted_page': {
                'type': 'PAYMENTFORM'
            },
        }
        seamless_payment = self._novalnet_make_request("seamless/payment", data=data)
        if 'result' in seamless_payment and 'redirect_url' in seamless_payment.get('result'):
            return seamless_payment.get('result')['redirect_url']
        return

    def donation_process(self, amount, currency, partner_id):
        """
        This function for Donation Payment Process
        """
        if not currency:
            return
        converted_amount = payment_utils.to_minor_currency_units(amount, currency)
        odoo_version = service.common.exp_version()['server_version']
        module_version = self.env.ref('base.module_payment_novalnet').installed_version
        first_name, last_name = payment_utils.split_partner_name(partner_id.name)
        data = {
            'customer': {
                'first_name': first_name or last_name,
                'last_name': last_name or first_name,
                'customer_ip': self.get_client_ip_novalnet(),
                'customer_no': partner_id.id,
                'email': partner_id.email or None,
                'phone': partner_id.phone or None,
                'billing': {
                    'country_code': partner_id.country_id.code or None,
                },
            },
            'transaction': {
                'amount': converted_amount,
                'system_name': 'Odoo',
                'system_version': f'{odoo_version}-NN{module_version}-NNT{self.get_current_theme() or ""}',
                'system_ip': self.get_system_ip() or "",
                'currency': currency.name,
            },
            'hosted_page': {
                'type': 'PAYMENTFORM'
            },
        }
        seamless_payment = self._novalnet_make_request("seamless/payment", data=data)
        if 'result' in seamless_payment and 'redirect_url' in seamless_payment.get('result'):
            return seamless_payment.get('result')['redirect_url']
        return

    # === CONSTRAINT METHODS ===#
    # Method for not allow to publish our payment provider when enable status
    @api.constrains('state', 'code')
    def _check_provider_state(self):
        if self.filtered(lambda p: p.code == 'novalnet' and p.state not in ('enabled', 'disabled')):
            raise UserError(_("Test mode for the Novalnet payment plugin cannot be configured directly within the "
                              "plugin. To enable or disable test mode, please log in to your Novalnet Admin Portal."))

    # Override of `payment` to return the default payment method codes.
    def _get_default_payment_method_codes(self):
        default_codes = super()._get_default_payment_method_codes()
        if self.code != 'novalnet':
            return default_codes
        return const.DEFAULT_PAYMENT_METHOD_CODES

    def get_client_ip_novalnet(self):
        """Get client IP address with multiple fallback options"""
        try:
            if not hasattr(http.request, 'httprequest'):
                _logger.warning("Not in HTTP request context")
                return '0.0.0.0'

            request = http.request.httprequest

            # List of headers to check for client IP (in order of preference)
            ip_headers = [
                'X-Forwarded-For',
                'X-Real-IP',
                'Client-IP',
                'X-Client-IP',
                'X-Forwarded',
                'Forwarded-For',
                'Forwarded'
            ]

            # Check each header
            for header in ip_headers:
                ip_value = request.headers.get(header)
                if ip_value:
                    # Handle comma-separated IP lists (common with proxies)
                    ips = [ip.strip() for ip in ip_value.split(',')]
                    # Return the first non-empty, non-unknown IP
                    for ip in ips:
                        if ip and ip.lower() != 'unknown':
                            return ip

            # Fallback to remote_addr
            return request.remote_addr or '0.0.0.0'

        except AttributeError:
            _logger.warning("HTTP request not available")
            return '0.0.0.0'
        except Exception as e:
            _logger.error("Error getting client IP: %s", str(e))
            return '0.0.0.0'

    # Perform server call
    def _novalnet_make_request(self, endpoint, data=None, method='POST'):
        """ Make a request at novalnet endpoint.
        Note: self.ensure_one()
        :param str endpoint: The endpoint to be reached by the request
        :param dict data: The payload of the request
        :param str method: The HTTP method of the request
        :return The JSON-formatted content of the response
        :rtype: dict
        :raise: ValidationError if an HTTP error occurs
        """
        self.ensure_one()
        endpoint = f'/v2/{endpoint.strip("/")}'
        url = urls.url_join('https://payport.novalnet.de', endpoint)
        base64_bytes = base64.b64encode(self.novalnet_payment_access_key.encode("ascii"))
        encoded_data = base64_bytes.decode("ascii")
        headers = {
            "Content-Type": "application/json",
            "Charset": "utf-8",
            "Accept": "application/json",
            "X-NN-Access-Key": encoded_data,
        }
        if 'merchant' not in data:
            data['merchant'] = {'signature': self.novalnet_product_activation_key, 'tariff': self.novalnet_traiff}
        if 'custom' not in data:
            data['custom'] = {'lang': 'EN' if self.env.context.get('lang') == 'en_US' else 'DE'}
        try:
            _logger.info(
                "novalnet payment transfer request\nURL: %(url)s\nPayload: %(values)s",
                {'url': url, 'values': pprint.pformat(data)},
            )
            response = requests.request(method, url, json=data, headers=headers, timeout=120)
            result = response.json()
            _logger.info(
                "novalnet payment transfer response "
                "\n%(values)s",
                {'values': pprint.pformat(result)},
            )
            if response.status_code == 204:
                return True  # returned no content
            if response.status_code not in [200]:
                error_msg = f"Error[{response.status_code}]"
                _logger.exception("Error from Novalnet: %s", result)
                raise ValidationError("novalnet: " + _(error_msg))
            response.raise_for_status()
        except requests.exceptions.RequestException:
            _logger.exception("Unable to communicate with novalnet: %s", url)
            raise ValidationError("novalnet: " + _("Could not establish the connection to the API."))
        if result.get('result')['status'] == 'FAILURE':
            error_msg = (f"Error[{result.get('result')['status']}] : "
                         f"{result.get('result')['status_code']} - {result.get('result')['status_text']}")
            raise ValidationError("novalnet: " + _(error_msg))
        return result

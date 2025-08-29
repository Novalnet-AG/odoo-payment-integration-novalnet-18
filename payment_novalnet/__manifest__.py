# Part of Odoo. See LICENSE file for full copyright and licensing details.

{
    'name': 'Payment Provider: Novalnet',
        'version': '5.0.0',
    'category': 'Accounting/Payment Providers',
    'sequence': 350,
    'summary': "A global payment service provider.",
    'website': 'https://www.novalnet.com',
    'depends': ['web', 'website_sale', 'payment'],
    'data': [
        'views/payment_novalnet_templates.xml',
        'views/payment_transaction_views.xml',
        'views/payment_provider_view.xml',
        'views/callback_notification.xml',
        'views/payment_method_views.xml',
        'security/ir.model.access.csv',
        'data/payment_method_data.xml',
        'data/payment_provider_data.xml',
    ],
    'images': ['static/description/icon.png'],
    'post_init_hook': 'post_init_hook',
    'uninstall_hook': 'uninstall_hook',
    'application': False,
    'assets': {
        'web.assets_frontend': [
            'payment_novalnet/static/src/js/**/*',
        ],
    },
    'license': 'LGPL-3',
}

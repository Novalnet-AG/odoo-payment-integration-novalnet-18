"""
Module for Novalnet payment integration.

This module sets up the Novalnet payment provider and handles the
uninstallation process, ensuring proper management of payment providers
within Odoo.
"""
from . import controllers
from . import models

from odoo.addons.payment import setup_provider, reset_payment_provider


def post_init_hook(env):
    """
    Decorator to setup the Novalnet payment provider.

    This decorator will set up the Novalnet payment provider when
    applied to a function, allowing for custom initialization logic.
    """
    setup_provider(env, 'novalnet')


def uninstall_hook(env):
    """
    Decorator to reset the Novalnet payment provider.

    This decorator will reset the Novalnet payment provider when
    applied to a function, ensuring proper cleanup during
    uninstallation.
    """
    reset_payment_provider(env, 'novalnet')

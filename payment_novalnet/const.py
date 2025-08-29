"""
Constants for the Novalnet Payment Integration.

This module defines constants used throughout the Novalnet payment provider integration.
"""

DEFAULT_PAYMENT_METHOD_CODES = [
    'novalnet',
]

RESULT_CODES_MAPPING = {
    'CONFIRMED': 'done',
    'ON_HOLD': 'authorize',
    'PENDING': 'pending',
    'DEACTIVATED': 'cancel',
    'FAILURE': 'error',
}

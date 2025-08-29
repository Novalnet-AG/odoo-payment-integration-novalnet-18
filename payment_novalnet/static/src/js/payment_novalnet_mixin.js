/** @odoo-module **/

import { _t } from "@web/core/l10n/translation";
import { rpc, RPCError } from "@web/core/network/rpc";

export default {

/**
 * Simulate a feedback from a payment provider and redirect the customer to the status page.
 *
 * @private
 * @param {object} processingValues - The processing values of the transaction.
 * @return {void}
 */
async processNovalnetPayment(processingValues, payment_details, card_details) {
    rpc('/payment/novalnet/simulate_payment', {
        'reference': processingValues.reference,
        'nn_tid': processingValues.nn_tid,
    }).then(() => {
       window.location = '/payment/status';
    }).catch(error => {
        if (error instanceof RPCError) {
            this._displayErrorDialog(_t("Payment processing failed"), error.data.message);
            this._enableButton?.(); // This method doesn't exists in Express Checkout form.
        } else {
            return Promise.reject(error);
        }
    });
},

};




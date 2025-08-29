/** @odoo-module **/


import { Component } from '@odoo/owl';
import paymentForm from '@payment/js/payment_form';
import { _t } from '@web/core/l10n/translation';
import paymentNovalnetMixin from '@payment_novalnet/js/payment_novalnet_mixin';
import { rpc, RPCError } from "@web/core/network/rpc";



paymentForm.include({
    // DOM MANIPULATION

    /**
     * Prepare the inline form of Novalnet for direct payment.
     *
     * @override method from @payment/js/payment_form
     * @private
     * @param {number} providerId - The id of the selected payment option's provider.
     * @param {string} providerCode - The code of the selected payment option's provider.
     * @param {number} paymentOptionId - The id of the selected payment option
     * @param {string} paymentMethodCode - The code of the selected payment method, if any.
     * @param {string} flow - The online payment flow of the selected payment option.
     * @return {void}
     */

     start: async function () {
     /**
      * Connect the shop's iframe with the NovalnetUtility.js file
     */
       await this._super(...arguments);



// For order line items
var orderLineItemsElement = document.getElementById('novalnet_payment_data_line_items');
var lineItems = [];

if (orderLineItemsElement) {
    var lineItemsJson = orderLineItemsElement.dataset.lineItems;
    if (lineItemsJson) {
        lineItems = JSON.parse(lineItemsJson);
    }
}

// For invoice line items (fallback if order not available)
if (lineItems.length === 0) {
    var invoiceLineItemsElement = document.getElementById('novalnet_invoice_data_line_items');
    if (invoiceLineItemsElement) {
        var lineItemsJson = invoiceLineItemsElement.dataset.lineItems;
        if (lineItemsJson) {
            lineItems = JSON.parse(lineItemsJson);
        }
    }
}


       this.novalnetPaymentIframe = new NovalnetPaymentForm();
       const paymentFormRequestObj = {
           iframe: '#novalnet_iframe',
           initForm : {
               orderInformation : {
                      lineItems: lineItems
               },
               uncheckPayments: true,
               setWalletPending: true,
               showButton : false
           }
       };

       /**
        * Initiate the payment form Iframe
        */
       this.novalnetPaymentIframe.initiate(paymentFormRequestObj);
       $('[data-provider-code="novalnet"]').filter(':not([data-payment-option-type="token"])').closest('[name="o_payment_option"]').css('padding', '0px');

      // Hide the paynow button, if novalnet google or apple pay button clicked
       $(window).on('change', function() {
            const payButton = document.querySelector('button[name="o_payment_submit_button"]');
            if (!$('[data-provider-radio="o_payment_method_novalnet"]').is(':checked')) {
              payButton.style.display = 'block';
             }
        });


       this.novalnetPaymentIframe.selectedPayment((data) => {
           $('[data-provider-radio="o_payment_method_novalnet"]').trigger('click');
           const payButton = document.querySelector('button[name="o_payment_submit_button"]');
           if (payButton) {
                payButton.style.display = (data.payment_details.type === 'GOOGLEPAY' || data.payment_details.type === 'APPLEPAY') ? 'none' : 'block';
           }
       });
       const self = this;
       $('[data-provider-code]').on('click', function() {
       if ($(this).data('provider-code') !== 'novalnet' || ($('[data-provider-code="novalnet"]').filter('[data-payment-option-type="token"]:checked').length > 0))
        {
        self.novalnetPaymentIframe.uncheckPayment();
        }
       });
      this.novalnetPaymentIframe.walletResponse({
        onProcessCompletion: (response) => {
            this._disableButton(false); // Re-enable the button after processing

            if (response.result.status === 'FAILURE') {
                return { status: 'FAILURE', statusText: 'Failure' };
            }

            const checkedRadio = this.el.querySelector('input[name="o_payment_radio"]:checked');
            const providerCode = this.paymentContext.providerCode = this._getProviderCode(checkedRadio);

            if (providerCode !== 'novalnet') {
                  return { status: 'FAILURE', statusText: 'Failure' }; // Tokens are handled by the generic flow
            }

            const paymentOptionId = this.paymentContext.paymentOptionId = this._getPaymentOptionId(checkedRadio);
            const pmCode = this.paymentContext.paymentMethodCode = this._getPaymentMethodCode(checkedRadio);

            this.set_nn_payment_details(response);
            this.paymentContext.providerId = this._getProviderId(checkedRadio);
            this.paymentContext.paymentMethodId = paymentOptionId;
            const inlineForm = this._getInlineForm(checkedRadio);
            this.paymentContext.tokenizationRequested = inlineForm?.querySelector('[name="o_payment_tokenize_checkbox"]')?.checked ?? this.paymentContext['mode'] === 'validation';
            this._initiatePaymentFlow(providerCode, paymentOptionId, pmCode, this.paymentContext['flow']);
            return { status: 'SUCCESS', statusText: 'Successful' };
        }
      });

     },

     async _submitForm(ev) {
       /**
       * Override the shop payment submit button
       */
        ev.stopPropagation();
        ev.preventDefault();
        const checkedRadio = this.el.querySelector('input[name="o_payment_radio"]:checked');
        // Block the entire UI to prevent fiddling with other widgets.
        this._disableButton(true);
        // Initiate the payment flow of the selected payment option.
        const flow = this.paymentContext.flow = this._getPaymentFlow(checkedRadio);
        const paymentOptionId = this.paymentContext.paymentOptionId = this._getPaymentOptionId(
            checkedRadio
        );
        const providerCode = this.paymentContext.providerCode = this._getProviderCode(
                checkedRadio
            );
       if (providerCode !== 'novalnet') {
          return this._super(...arguments); // Tokens are handled by the generic flow
      }
        if (flow === 'token' && this.paymentContext['assignTokenRoute']) { // Assign token flow.
            await this._assignToken(paymentOptionId);
        } else { // Both tokens and payment methods must process a payment operation.
            const pmCode = this.paymentContext.paymentMethodCode = this._getPaymentMethodCode(
                checkedRadio
            );
            this.paymentContext.providerId = this._getProviderId(checkedRadio);

            const inlineForm = this._getInlineForm(checkedRadio);
            this.paymentContext.tokenizationRequested = inlineForm?.querySelector(
                '[name="o_payment_tokenize_checkbox"]'
            )?.checked ?? this.paymentContext['mode'] === 'validation';

            if (this._getPaymentOptionType(checkedRadio) === 'token') {
                this.paymentContext.tokenId = paymentOptionId;
                this._initiatePaymentFlow(providerCode, paymentOptionId, pmCode, this.paymentContext['flow']);
            } else { // 'payment_method'
                this.paymentContext.paymentMethodId = paymentOptionId;
                this.novalnetPaymentIframe.getPayment((data) => {
                    if(data.result && data.result.statusCode ==100) {
                            this.set_nn_payment_details(data);
                            this._initiatePaymentFlow(providerCode, paymentOptionId, pmCode, this.paymentContext['flow']);
                            if (window.location.pathname.includes('/donation')) {
                            this.call('ui', 'unblock');
                            }
                    }else {
                       // Create the modal for novalnet error Handling
                        const modalHtml = `
                            <div id="NovalnetErrorPopup" style="position:fixed;top:0;left:0;width:100%;height:100%;background:rgba(0,0,0,0.3);display:flex;justify-content:center;align-items:center;z-index:9999;font-family:Arial,sans-serif;">
                                <div style="background:#fff;border-radius:6px;width:auto;padding:50px 50px;box-shadow:0 2px 8px rgba(0,0,0,0.15);display:flex;flex-direction:column;align-items:center;gap:15px;">
                                    <p style="margin:0;text-align:center;">${data.result.message}</p>
                                    <button id="closeModalButton" style="background-color:#604058;color:#fff;border:none;padding:5px 15px;border-radius:4px;cursor:pointer;font-size:13px;">OK</button>
                                </div>
                            </div>
                        `;
                        document.body.insertAdjacentHTML('beforeend', modalHtml);

                        // Reload when OK is clicked
                        document.getElementById('closeModalButton').addEventListener('click', () => {
                            document.getElementById('NovalnetErrorPopup').remove();
                            window.location.reload();
                        });

                        this._enableButton();  // Enable button even though modal is shown
                    }

                });
            }


        }


    },

    _prepareTransactionRouteParams: function () {
    /**
    * Prepares the inline payment form
    */
          const transactionRouteParams = this._super();
          if (this.paymentContext.providerCode !== 'novalnet') {
              return transactionRouteParams;
          }
          const nn_payment_details = {'pay_data':this.paymentContext.payment_details,'pm_data':this.paymentContext.pm_data}
          return {...transactionRouteParams,...nn_payment_details};
      },

    async _prepareInlineForm(providerId, providerCode, paymentOptionId, paymentMethodCode, flow) {
    /**
    * Prepares the inline payment form for the specified provider and payment method
    */
        if (providerCode !== 'novalnet') {
            this._super(...arguments);
            return;
        } else if (flow === 'token') {
            return;
        }
        this._setPaymentFlow('direct');
    },

    async set_nn_payment_details(response) {
    /**
    * Set Novalnet payment Details
    */
        this.paymentContext['pm_data'] = response.payment_details;
        this.paymentContext['payment_details'] = response.booking_details;
        this.paymentContext['flow'] = response.payment_details.process_mode;
        if(response.booking_details.wallet_token) {
             this.paymentContext['wallet_token'] = response.booking_details.wallet_token;
        }
        if(response.card_details) {
             this.paymentContext['card_details'] = response.card_details;
        }

    },

    async _processTokenFlow(providerCode, paymentOptionId, paymentMethodCode, processingValues) {
    /**
     * Payment flow process
     *
     * Simulate a feedback from a payment provider and redirect the customer to the status page.
     *
     * @override method from payment.payment_form
     * @private
     * @param {string} providerCode - The code of the selected payment option's provider.
     * @param {number} paymentOptionId - The id of the selected payment option.
     * @param {string} paymentMethodCode - The code of the selected payment method, if any.
     * @param {object} processingValues - The processing values of the transaction.
     * @return {void}
     */
        if (providerCode !== 'novalnet') {
            this._super(...arguments);
            return;
        }
        paymentNovalnetMixin.processNovalnetPayment(processingValues);
    },

    async _processDirectFlow(providerCode, paymentOptionId, paymentMethodCode, processingValues) {
    /**
     * Payment flow process
     *
     * Simulate a feedback from a payment provider and redirect the customer to the status page.
     *
     * @override method from payment.payment_form
     * @private
     * @param {string} providerCode - The code of the selected payment option's provider.
     * @param {number} paymentOptionId - The id of the selected payment option.
     * @param {string} paymentMethodCode - The code of the selected payment method, if any.
     * @param {object} processingValues - The processing values of the transaction.
     * @return {void}
     */
        if (providerCode !== 'novalnet') {
            this._super(...arguments);
            return;
        }
        paymentNovalnetMixin.processNovalnetPayment(processingValues);
    },

});

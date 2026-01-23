# services/payment_retry_service.py

from datetime import datetime, timedelta
from ...models.admin.payment import Payment
from ...utils.logger import Log


class PaymentRetryService:
    """Service for retrying failed/stuck payments."""
    
    MAX_RETRIES = 3
    RETRY_DELAY_MINUTES = 5
    
    @staticmethod
    def retry_pending_payments():
        """
        Find and retry pending payments that are stuck.
        Run this as a cron job every 5-10 minutes.
        """
        log_tag = "[PaymentRetryService][retry_pending_payments]"
        
        try:
            # Get payments pending for more than 5 minutes
            pending_payments = Payment.get_pending_payments(
                older_than_minutes=PaymentRetryService.RETRY_DELAY_MINUTES
            )
            
            Log.info(f"{log_tag} Found {len(pending_payments)} stuck payments")
            
            for payment in pending_payments:
                payment_id = payment.get('_id')
                retry_count = payment.get('retry_count', 0)
                gateway = payment.get('gateway')
                
                # Check if we've exceeded max retries
                if retry_count >= PaymentRetryService.MAX_RETRIES:
                    Log.warning(f"{log_tag} Payment {payment_id} exceeded max retries")
                    
                    # Mark as failed
                    Payment.update_status(
                        payment_id,
                        Payment.STATUS_FAILED,
                        error_message=f"Payment failed after {retry_count} retry attempts"
                    )
                    continue
                
                # ✅ INCREMENT RETRY COUNT
                Payment.increment_retry(payment_id)
                
                Log.info(f"{log_tag} Retrying payment {payment_id} (attempt {retry_count + 1}/{PaymentRetryService.MAX_RETRIES})")
                
                # Retry based on gateway
                if gateway == "hubtel":
                    PaymentRetryService._retry_hubtel_payment(payment)
                elif gateway == "mpesa":
                    PaymentRetryService._retry_mpesa_payment(payment)
                else:
                    Log.warning(f"{log_tag} Unknown gateway: {gateway}")
            
            return len(pending_payments)
            
        except Exception as e:
            Log.error(f"{log_tag} Error: {str(e)}", exc_info=True)
            return 0
    
    @staticmethod
    def _retry_hubtel_payment(payment):
        """Retry a Hubtel payment."""
        log_tag = "[PaymentRetryService][_retry_hubtel_payment]"
        
        try:
            from ...services.payments.payment_service import PaymentService
            
            payment_id = payment.get('_id')
            metadata = payment.get('metadata', {})
            
            # Extract original payment details
            business_id = payment.get('business_id')
            user_id = payment.get('user_id')
            user__id = payment.get('user__id')
            package_id = metadata.get('package_id') or payment.get('package_id')
            billing_period = metadata.get('billing_period', 'monthly')
            customer_name = payment.get('customer_name')
            customer_phone = payment.get('customer_phone')
            customer_email = payment.get('customer_email')
            
            # Initiate new payment attempt
            success, data, error = PaymentService.initiate_hubtel_payment(
                business_id=business_id,
                user_id=user_id,
                user__id=user__id,
                package_id=package_id,
                billing_period=billing_period,
                customer_name=customer_name,
                customer_phone=customer_phone,
                customer_email=customer_email,
                metadata=metadata
            )
            
            if success:
                # Mark old payment as cancelled
                Payment.update_status(
                    payment_id,
                    Payment.STATUS_CANCELLED,
                    error_message="Replaced by retry payment"
                )
                
                Log.info(f"{log_tag} Payment retry successful, new payment: {data.get('payment_id')}")
            else:
                Log.error(f"{log_tag} Payment retry failed: {error}")
            
        except Exception as e:
            Log.error(f"{log_tag} Error: {str(e)}", exc_info=True)
    
    @staticmethod
    def _retry_mpesa_payment(payment):
        """Retry an M-Pesa payment."""
        # Similar to Hubtel retry
        pass
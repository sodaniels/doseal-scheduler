import os
from ..utils.logger import Log # import logging
from ..models.people_model import Agent
from ..models.user_model import User
from ..models.instntmny.promo_model import Promo
from app.utils.calculation_engine import (
    cal_receive_amount_with_rate,
    cal_total_send_amount,
    cal_total_receive_amount,
    calculate_discounted_amount,
)

class Transaction_amount_wizard:
    
    def create(sender_currency, 
               recipient_currency, 
               send_amount, 
               fee, 
               rate, 
               user_type, 
               business_id=None,
               subscriber_id=None,
               transaction_type=None
            ):
        incentive_status = os.getenv("SENDING_COUNTRY_INCENTIVE_STATUS", "false")
        incentive_threshold = float(os.getenv("SENDING_COUNTRY_INCENTIVE_THRESHOLD", 0))
        
        log_tag = "[transaction_utils.py][Transaction_amount_wizard][create]"

        send_amount = float(send_amount)
        fee = float(fee)
        rate = float(rate)
        
       

        if user_type == "Agent":
            receive_amount = cal_receive_amount_with_rate(send_amount, rate)
            total_send_amount = cal_total_send_amount(send_amount, fee)

            return {
                "send_amount": send_amount,
                "total_send_amount": total_send_amount,
                "receive_amount": receive_amount,
                "total_receive_amount": receive_amount,
                "fee": fee,
                "rate": rate,
                "sender_currency": sender_currency,
                "recipient_currency": recipient_currency
            }

        elif user_type == "Subscriber":
            incentive_amount = float(os.getenv("SENDING_COUNTRY_INCENTIVE_AMOUNT", 0))
            
            try:
                Log.info(f"{log_tag}[{business_id}] fetching active promo Subscriber promo" )
                promo = Promo.get_active_one_by_category(business_id, "Subscriber") 
            except Exception as e:
                Log.info(f"{log_tag} error fetching active promo Subscriber promo. {str(e)}" )

            receive_amount = cal_receive_amount_with_rate(send_amount, rate)
            total_send_amount = cal_total_send_amount(send_amount, fee)

            incentive_amount_in_receiver_currency = cal_receive_amount_with_rate(
                incentive_amount, rate
            )

            total_receive_amount = cal_total_receive_amount(
                receive_amount, incentive_amount_in_receiver_currency
            )
            
            amount_payload = {
                "send_amount": send_amount,
                "sender_currency": sender_currency,
                "total_send_amount": total_send_amount,
                "receive_amount": receive_amount,
                "total_receive_amount": total_receive_amount,
                "fee": fee,
                "rate": rate,
            }
            
            if promo is not None and transaction_type != 'billpay':
                promo_amt_in_rev_currency = cal_receive_amount_with_rate(promo.get("promo_amount"), rate)
                
                
                promoObj = {
                    "promo_id": str(promo.get("_id")),
                    "promo_name": promo.get("promo_name"),
                    "promo_category": promo.get("promo_category"),
                    "promo_start_date": promo.get("promo_start_date"),
                    "promo_end_date": promo.get("promo_end_date"),
                    "sender_currency": str.upper(sender_currency),
                    "promo_amount": promo.get("promo_amount"),
                    "promo_amount_in_receiving_currency": promo_amt_in_rev_currency,
                    "current_rate": rate,
                    "promo_limit": promo.get("promo_limit"),
                    "promo_total_allowable_limit": promo.get("promo_total_allowable_limit"),
                    "promo_limit_reached": True if int(promo.get("promo_limit")) <=0 else False,
                    "promo_threshold": promo.get("promo_threshold"),
                }
                
                # retrieve system user information using subscriber_id
                try:
                    user = User.get_user_by_subscriber_id(subscriber_id)
                    if user.get("promos") and len(user.get("promos")) > 0:
                        user_promos = user.get("promos")
                        for i in user_promos:
                            if i["promo_id"] == promo.get("_id"):
                                Log.info(f"{log_tag} item: {i}")
                                promoObj["user_promo_limit"] = i["promo_limit"]
                                promoObj["user_promo_left"] = i["promo_left"]
                                
                               
                except Exception as e:
                    Log.info(f"{log_tag}: error retreiving for system user: {e}")
                    
                
                amount_payload["promo"] = promoObj
                
            
            # check if inventive is activated and update the amount payload
            if incentive_status == "true" and send_amount >= incentive_threshold:
                incentive_payload = dict()
                incentive_payload["incentive_amount"] = incentive_amount
                incentive_payload["incentive_amount_in_receiver_currency"] = incentive_amount_in_receiver_currency
                
                amount_payload.update(incentive_payload)
                
            return amount_payload

        else:
            return None  # or raise ValueError("Invalid user type")


    def create_billpay(_sender_currency, _send_amount, _rate, _fee):
        send_amount = float(_send_amount)
        rate = float(_rate)
        fee = float(_fee)

        total_send_amount = cal_total_send_amount(send_amount, fee)
        receive_amount = cal_receive_amount_with_rate(send_amount, rate)

        return {
            "sendAmount": send_amount,
            "totalSendAmount": total_send_amount,
            "receiveAmount": receive_amount,
            "totalReceiveAmount": receive_amount,
            "fee": fee,
            "rate": rate,
        }

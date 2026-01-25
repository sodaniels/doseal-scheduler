# app/routes/social/facebook_webhook.py
import os
from flask import request
from flask_smorest import Blueprint
from flask.views import MethodView
from app.utils.logger import Log

blp_fb_webhook = Blueprint("Facebook Webhook", __name__, description="Facebook Webhook")

@blp_fb_webhook.route("/social/webhooks/facebook", methods=["GET", "POST"])
class FacebookWebhookResource(MethodView):

    def get(self):
        # Facebook verification handshake
        mode = request.args.get("hub.mode")
        token = request.args.get("hub.verify_token")
        challenge = request.args.get("hub.challenge")

        expected = os.getenv("FACEBOOK_WEBHOOK_VERIFY_TOKEN")
        if mode == "subscribe" and token == expected:
            return challenge, 200

        return "Verification failed", 403

    def post(self):
        # Actual webhook events come here
        payload = request.get_json(silent=True) or {}
        Log.info(f"[facebook_webhook] received: {payload}")
        return "ok", 200
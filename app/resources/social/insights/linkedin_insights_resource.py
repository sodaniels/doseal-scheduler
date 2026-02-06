# app/resources/social/linkedin_insights.py
#
# LinkedIn analytics using STORED SocialAccount token
#
# What you can reliably get with LinkedIn Marketing/Organization APIs (depending on app access + permissions):
# - Organization info: localizedName, vanityName, logo, etc.
# - Followers: organizationalEntityFollowerStatistics (aggregates + time buckets)
# - Page stats: organizationPageStatistics (page views, clicks, etc. — varies by product access)
# - Posts list: ugcPosts (org authored posts)
# - Engagement counts: socialActions (likes/comments counts) for a given post URN (best-effort)
#
# Important notes:
# - LinkedIn APIs are gated. Many endpoints require your app to be approved for Marketing/Community Management use-cases.
# - 403 is common if your app doesn’t have access to the product or missing permissions.
# - 401 means token expired/invalid. If you store refresh_token, you can auto-refresh (if your app supports it).
#
# Required env vars for refresh (if you want auto-refresh):
#   LINKEDIN_CLIENT_ID
#   LINKEDIN_CLIENT_SECRET
#
# Token permissions/scopes vary by endpoint. Common ones include:
#   r_organization_social, rw_organization_admin, w_organization_social, r_basicprofile (legacy), etc.

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote

import os
import requests
from flask import g, jsonify, request
from flask.views import MethodView
from flask_smorest import Blueprint

from ....constants.service_code import HTTP_STATUS_CODES
from ....models.social.social_account import SocialAccount
from ....utils.logger import Log
from ...doseal.admin.admin_business_resource import token_required


# -------------------------------------------------------------------
# Blueprint
# -------------------------------------------------------------------

blp_linkedin_insights = Blueprint(
    "linkedin_insights",
    __name__,
)
# resources/cash_resource.py
from flask import g, request
from flask.views import MethodView
from flask_smorest import Blueprint
from bson import ObjectId

from ....utils.rate_limits import (
    crud_read_limiter, 
    crud_write_limiter
)
from ....utils.redis import remove_redis
from ....utils.redis import set_redis
from ....utils.helpers import make_log_tag
from ....utils.crypt import decrypt_data
#helper functions
from .admin_business_resource import token_required
from ....utils.json_response import prepared_response
from ....utils.helpers import make_log_tag
from ....utils.logger import Log # import logging
from ....models.admin.customer_model import Customer
from ....constants.service_code import (
   HTTP_STATUS_CODES,SYSTEM_USERS
)

from ....schemas.admin.cash_schemas import (
    OpenSessionSchema,
    CloseSessionSchema,
    CashMovementSchema,
    SessionIdQuerySchema,
    SessionsListQuerySchema,
    MovementsListQuerySchema
)
from ....models.admin.cash_session import CashSession
from ....models.admin.cash_movement import CashMovement
from ....services.pos.cash_session_service import CashSessionService


cash_blp = Blueprint("Cash", __name__, description="Cash register and till management operations")


@cash_blp.route("/cash/session/open")
class OpenSessionResource(MethodView):
    """Open a new cash session."""
    
    @token_required
    @crud_write_limiter(entity_name="open_cash_session")
    @cash_blp.arguments(OpenSessionSchema, location="json")
    @cash_blp.response(HTTP_STATUS_CODES["CREATED"])
    @cash_blp.doc(
        summary="Open cash session",
        description="""
            Open a new cash register session for a cashier.
            
            - Ensures no existing open session for the user
            - Records opening float
            - Tracks all sales and movements during session
        """,
        security=[{"Bearer": []}],
    )
    def post(self, json_data):
        """Open new cash session."""
        client_ip = request.remote_addr
        user_info = g.get("current_user", {}) or {}
        
        auth_business_id = str(user_info.get("business_id"))
        user_id = user_info.get("user_id")
        user__id = str(user_info.get("_id"))
        account_type_enc = user_info.get("account_type")
        account_type = account_type_enc if account_type_enc else None
        agent_id = user_info.get("agent_id")
        admin_id = user_info.get("_id")
        
        # Role-aware business selection
        requested_business_id = json_data.get("business_id")
        if account_type in (SYSTEM_USERS["SYSTEM_OWNER"], SYSTEM_USERS["SUPER_ADMIN"]):
            business_id = requested_business_id or auth_business_id
        else:
            business_id = auth_business_id
        
        outlet_id = json_data.get("outlet_id")
        opening_float = json_data.get("opening_float")
        notes = json_data.get("notes")
        
        log_tag = make_log_tag(
            "admin_cash_resource.py",
            "OpenSessionResource",
            "post",
            client_ip,
            user__id,
            account_type,
            auth_business_id,
            business_id
        )
        
        try:
            
            Log.info(f"{log_tag} Opening session with float: {opening_float}")
            
            success, session_id, error = CashSessionService.open_session(
                business_id=business_id,
                outlet_id=outlet_id,
                user_id=user_id,
                user__id=user__id,
                opening_float=opening_float,
                notes=notes,
                agent_id=agent_id,
                admin_id=admin_id
            )
            
            if not success:
                Log.error(f"{log_tag} Open failed: {error}")
                return prepared_response(
                    status=False,
                    status_code="BAD_REQUEST",
                    message=f"Failed to open cash session: {error}",
                    errors=[error],
                )
                
            if success:
                #store cash_session_id in redis
                redisKey = f'cash_session_token_{auth_business_id}_{user__id}'
                set_redis(redisKey, session_id)

            
            Log.info(f"{log_tag} Session opened: {session_id}")
            
            return prepared_response(
                status=True,
                status_code="CREATED",
                message="Cash session opened successfully",
                data={"session_id": session_id}
            )
            
        except Exception as e:
            Log.error(f"{log_tag} Error: {str(e)}")
            return prepared_response(
                status=False,
                status_code="INTERNAL_SERVER_ERROR",
                message="Error opening cash session",
                errors=[str(e)]
            )


@cash_blp.route("/cash/session/close")
class CloseSessionResource(MethodView):
    """Close a cash session."""
    
    @token_required
    @crud_write_limiter(entity_name="close_cash_session")
    @cash_blp.arguments(CloseSessionSchema, location="json")
    @cash_blp.response(HTTP_STATUS_CODES["OK"])
    @cash_blp.doc(
        summary="Close cash session",
        description="""
            Close a cash register session.
            
            - Requires actual cash count
            - Calculates expected vs actual variance
            - Updates session status to Closed
        """,
        security=[{"Bearer": []}],
    )
    def post(self, json_data):
        """Close cash session."""
        client_ip = request.remote_addr
        user_info = g.get("current_user", {}) or {}
        
        auth_business_id = str(user_info.get("business_id"))
        user__id = user_info.get("_id")
        account_type_enc = user_info.get("account_type")
        account_type = account_type_enc if account_type_enc else None
        
        # Role-aware business selection
        requested_business_id = json_data.get("business_id")
        if account_type in (SYSTEM_USERS["SYSTEM_OWNER"], SYSTEM_USERS["SUPER_ADMIN"]):
            business_id = requested_business_id or auth_business_id
        else:
            business_id = auth_business_id
        
        session_id = json_data.get("session_id")
        actual_balance = json_data.get("actual_balance")
        notes = json_data.get("notes")
        
        log_tag = make_log_tag(
            "admin_cash_resource.py",
            "CloseSessionResource",
            "post",
            client_ip,
            user__id,
            account_type,
            auth_business_id,
            business_id
        )
        
        try:
            if not session_id:
                Log.error(f"{log_tag} session_id required")
                return prepared_response(
                    status=False,
                    status_code="BAD_REQUEST",
                    message="session_id is required"
                )
            
            Log.info(f"{log_tag} Closing session with balance: {actual_balance}")
            
            success, variance, error = CashSessionService.close_session(
                session_id=session_id,
                business_id=business_id,
                actual_balance=actual_balance,
                notes=notes
            )
            
            if not success:
                Log.error(f"{log_tag} Close failed: {error}")
                return prepared_response(
                    status=False,
                    status_code="BAD_REQUEST",
                    message=f"Failed to close cash session: {error}",
                    errors=[error]
                )
            
            Log.info(f"{log_tag} Session closed. Variance: {variance}")
            
            #remove cash_session_token from redis
            redisKey = f'cash_session_token_{auth_business_id}_{user__id}'
            remove_redis(redisKey)
                
            # Determine message based on variance
            if variance == 0:
                message = "Cash session closed successfully. Cash balanced perfectly!"
            elif variance > 0:
                message = f"Cash session closed. Cash over by {abs(variance):.2f}"
            else:
                message = f"Cash session closed. Cash short by {abs(variance):.2f}"
            
            return prepared_response(
                status=True,
                status_code="OK",
                message=message,
                data={
                    "session_id": session_id,
                    "variance": variance
                }
            )
            
        except Exception as e:
            Log.error(f"{log_tag} Error: {str(e)}")
            return prepared_response(
                status=False,
                code_string="INTERNAL_SERVER_ERROR",
                message="Error closing cash session",
                errors=[str(e)]
            )


@cash_blp.route("/cash/session/current")
class CurrentSessionResource(MethodView):
    """Get current open session."""
    
    @token_required
    @crud_read_limiter(entity_name="current_session")
    @cash_blp.arguments(SessionIdQuerySchema, location="query")
    @cash_blp.response(HTTP_STATUS_CODES["OK"])
    @cash_blp.doc(
        summary="Get current open session",
        description="Get the currently open session for the authenticated user.",
        security=[{"Bearer": []}],
    )
    def get(self, query_args):
        """Get current session."""
        client_ip = request.remote_addr
        user_info = g.get("current_user", {}) or {}
        
        auth_business_id = str(user_info.get("business_id"))
        user__id = user_info.get("_id")
        account_type_enc = user_info.get("account_type")
        account_type = account_type_enc if account_type_enc else None
        
        # Role-aware business selection
        query_business_id = query_args.get("business_id")
        if account_type in (SYSTEM_USERS["SYSTEM_OWNER"], SYSTEM_USERS["SUPER_ADMIN"]):
            business_id = query_business_id or auth_business_id
        else:
            business_id = auth_business_id
        
        outlet_id = query_args.get("outlet_id")
        
        log_tag = make_log_tag(
            "admin_cash_resource.py",
            "CurrentSessionResource",
            "get",
            client_ip,
            user__id,
            account_type,
            auth_business_id,
            business_id
        )
        
        try:
            if not outlet_id:
                Log.error(f"{log_tag} outlet_id required")
                return prepared_response(
                    status=False,
                    statos_code="BAD_REQUEST",
                    message="outlet_id is required"
                )
            
            session = CashSession.get_current_session(
                business_id=business_id,
                outlet_id=outlet_id,
                user__id=user__id
            )
            
            if not session:
                Log.info(f"{log_tag} No open session found")
                return prepared_response(
                    status=True,
                    status_code="OK",
                    message="No open session found",
                    data={"session": None},
                )
            
            Log.info(f"{log_tag} Current session: {session['_id']}")
            
            return prepared_response(
                status=True,
                status_code="OK",
                message="Current session retrieved",
                data={"session": session}
            )
            
        except Exception as e:
            Log.error(f"{log_tag} Error: {str(e)}")
            return prepared_response(
                status=False,
                status_code="INTERNAL_SERVER_ERROR",
                message="Error retrieving current session",
                errors=[str(e)]
            )


@cash_blp.route("/cash/sessions")
class SessionsListResource(MethodView):
    """List cash sessions."""
    
    @token_required
    @crud_read_limiter(entity_name="sessions_list")
    @cash_blp.arguments(SessionsListQuerySchema, location="query")
    @cash_blp.response(HTTP_STATUS_CODES["OK"])
    @cash_blp.doc(
        summary="List cash sessions",
        description="Get paginated list of cash sessions for an outlet.",
        security=[{"Bearer": []}],
    )
    def get(self, query_args):
        """List sessions."""
        client_ip = request.remote_addr
        user_info = g.get("current_user", {}) or {}
        
        user__id = user_info.get("_id")
        auth_business_id = str(user_info.get("business_id"))
        account_type_enc = user_info.get("account_type")
        account_type = account_type_enc if account_type_enc else None
        
        # Role-aware business selection
        query_business_id = query_args.get("business_id")
        if account_type in (SYSTEM_USERS["SYSTEM_OWNER"], SYSTEM_USERS["SUPER_ADMIN"]):
            business_id = query_business_id or auth_business_id
        else:
            business_id = auth_business_id
        
        outlet_id = query_args.get("outlet_id")
        status = query_args.get("status")
        page = query_args.get("page", 1)
        per_page = query_args.get("per_page", 50)
        
        log_tag = make_log_tag(
            "admin_cash_resource.py",
            "SessionsListResource",
            "get",
            client_ip,
            user__id,
            account_type,
            auth_business_id,
            business_id
        )
        
        try:
            if not outlet_id:
                Log.error(f"{log_tag} outlet_id required")
                return prepared_response(
                    status=False,
                    status_code="BAD_REQUEST",
                    message="outlet_id is required"
                )
            
            result = CashSession.get_by_outlet(
                business_id=business_id,
                outlet_id=outlet_id,
                page=page,
                per_page=per_page,
                status=status
            )
            
            Log.info(f"{log_tag} Retrieved {len(result.get('cash_sessions', []))} sessions")
            
            return prepared_response(
                status=True,
                status_code="OK",
                message="Sessions retrieved successfully",
                data=result
            )
            
        except Exception as e:
            Log.error(f"{log_tag} Error: {str(e)}")
            return prepared_response(
                status=False,
                code_string="INTERNAL_SERVER_ERROR",
                message="Error retrieving sessions",
                errors=[str(e)]
            )


@cash_blp.route("/cash/movement")
class CashMovementResource(MethodView):
    """Record cash movement (in/out)."""
    
    @token_required
    @crud_write_limiter(entity_name="cash_movement")
    @cash_blp.arguments(CashMovementSchema, location="json")
    @cash_blp.response(HTTP_STATUS_CODES["CREATED"])
    @cash_blp.doc(
        summary="Record cash movement",
        description="""
            Record manual cash addition or removal.
            
            - IN: Adding cash to drawer (e.g., from bank)
            - OUT: Removing cash from drawer (e.g., bank deposit, expense)
        """,
        security=[{"Bearer": []}],
    )
    def post(self, json_data):
        """Record cash movement."""
        client_ip = request.remote_addr
        user_info = g.get("current_user", {}) or {}
        
        auth_business_id = str(user_info.get("business_id"))
        user_id = user_info.get("user_id")
        user__id = user_info.get("_id")
        account_type_enc = user_info.get("account_type")
        account_type = account_type_enc if account_type_enc else None
        agent_id = user_info.get("agent_id")
        admin_id = user_info.get("admin_id")
        
        # Role-aware business selection
        requested_business_id = json_data.get("business_id")
        if account_type in (SYSTEM_USERS["SYSTEM_OWNER"], SYSTEM_USERS["SUPER_ADMIN"]):
            business_id = requested_business_id or auth_business_id
        else:
            business_id = auth_business_id
        
        session_id = json_data.get("session_id")
        outlet_id = json_data.get("outlet_id")
        movement_type = json_data.get("movement_type")
        amount = json_data.get("amount")
        reason = json_data.get("reason")
        notes = json_data.get("notes")
        
        log_tag = make_log_tag(
            "admin_cash_resource.py",
            "CashMovementResource",
            "post",
            client_ip,
            user__id,
            account_type,
            auth_business_id,
            business_id
        )
        
        try:
            if not all([session_id, outlet_id, movement_type, amount, reason]):
                Log.error(f"{log_tag} Missing required fields")
                return prepared_response(
                    status=False,
                    status_code="BAD_REQUEST",
                    message="session_id, outlet_id, movement_type, amount, and reason are required"
                )
            
            Log.info(f"{log_tag} Recording {movement_type}: {amount}")
            
            # Call appropriate service method
            if movement_type == "IN":
                success, movement_id, error = CashSessionService.record_cash_in(
                    session_id=session_id,
                    business_id=business_id,
                    outlet_id=outlet_id,
                    user_id=user_id,
                    user__id=user__id,
                    amount=amount,
                    reason=reason,
                    notes=notes,
                    agent_id=agent_id,
                    admin_id=admin_id
                )
            else:  # OUT
                success, movement_id, error = CashSessionService.record_cash_out(
                    session_id=session_id,
                    business_id=business_id,
                    outlet_id=outlet_id,
                    user_id=user_id,
                    user__id=user__id,
                    amount=amount,
                    reason=reason,
                    notes=notes,
                    agent_id=agent_id,
                    admin_id=admin_id
                )
            
            if not success:
                Log.error(f"{log_tag} Movement failed: {error}")
                return prepared_response(
                    status=False,
                    status_code="BAD_REQUEST",
                    message=f"Failed to record cash movement: {error}",
                    errors=[error]
                )
            
            Log.info(f"{log_tag} Movement recorded: {movement_id}")
            
            return prepared_response(
                status=True,
                status_code="CREATED",
                message="Cash movement recorded successfully",
                data={"movement_id": movement_id}
            )
            
        except Exception as e:
            Log.error(f"{log_tag} Error: {str(e)}")
            return prepared_response(
                status=False,
                code_string="INTERNAL_SERVER_ERROR",
                message="Error recording cash movement",
                errors=[str(e)],
                status_code=HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]
            )


@cash_blp.route("/cash/movements")
class MovementsListResource(MethodView):
    """List cash movements."""
    
    @token_required
    @crud_read_limiter(entity_name="movements_list")
    @cash_blp.arguments(MovementsListQuerySchema, location="query")
    @cash_blp.response(HTTP_STATUS_CODES["OK"])
    @cash_blp.doc(
        summary="List cash movements",
        description="Get cash movements for a session or outlet.",
        security=[{"Bearer": []}],
    )
    def get(self, query_args):
        """List movements."""
        client_ip = request.remote_addr
        user_info = g.get("current_user", {}) or {}
        
        user__id = str(user_info.get("_id"))
        auth_business_id = str(user_info.get("business_id"))
        account_type_enc = user_info.get("account_type")
        account_type = account_type_enc if account_type_enc else None
        
        # Role-aware business selection
        query_business_id = query_args.get("business_id")
        if account_type in (SYSTEM_USERS["SYSTEM_OWNER"], SYSTEM_USERS["SUPER_ADMIN"]):
            business_id = query_business_id or auth_business_id
        else:
            business_id = auth_business_id
        
        session_id = query_args.get("session_id")
        outlet_id = query_args.get("outlet_id")
        page = query_args.get("page", 1)
        per_page = query_args.get("per_page", 50)
        
        log_tag = make_log_tag(
            "admin_cash_resource.py",
            "MovementsListResource",
            "get",
            client_ip,
            user__id,
            account_type,
            auth_business_id,
            business_id
        )
        
        try:
            if session_id:
                # Get movements for specific session
                movements = CashMovement.get_by_session(
                    session_id=session_id,
                    business_id=business_id
                )
                result = {
                    "cash_movements": movements,
                    "total": len(movements)
                }
            elif outlet_id:
                # Get movements for outlet
                result = CashMovement.get_by_outlet(
                    business_id=business_id,
                    outlet_id=outlet_id,
                    page=page,
                    per_page=per_page
                )
            else:
                Log.error(f"{log_tag} session_id or outlet_id required")
                return prepared_response(
                    status=False,
                    status_code="BAD_REQUEST",
                    message="Either session_id or outlet_id is required"
                )
            
            Log.info(f"{log_tag} Retrieved {len(result.get('cash_movements', []))} movements")
            
            return prepared_response(
                status=True,
                status_code="OK",
                message="Movements retrieved successfully",
                data=result
            )
            
        except Exception as e:
            Log.error(f"{log_tag} Error: {str(e)}")
            return prepared_response(
                status=False,
                status_code="INTERNAL_SERVER_ERROR",
                message="Error retrieving movements",
                errors=[str(e)]
            )


@cash_blp.route("/cash/session/summary")
class SessionSummaryResource(MethodView):
    """Get detailed session summary."""
    
    @token_required
    @crud_read_limiter(entity_name="session_summary")
    @cash_blp.arguments(SessionIdQuerySchema, location="query")
    @cash_blp.response(HTTP_STATUS_CODES["OK"])
    @cash_blp.doc(
        summary="Get session summary",
        description="Get detailed summary including all movements and totals.",
        security=[{"Bearer": []}],
    )
    def get(self, query_args):
        """Get session summary."""
        client_ip = request.remote_addr
        user_info = g.get("current_user", {}) or {}
        
        user__id = str(user_info.get("_id"))
        auth_business_id = str(user_info.get("business_id"))
        account_type_enc = user_info.get("account_type")
        account_type = account_type_enc if account_type_enc else None
        
        # Role-aware business selection
        query_business_id = query_args.get("business_id")
        if account_type in (SYSTEM_USERS["SYSTEM_OWNER"], SYSTEM_USERS["SUPER_ADMIN"]):
            business_id = query_business_id or auth_business_id
        else:
            business_id = auth_business_id
        
        session_id = query_args.get("session_id")
        
        log_tag = make_log_tag(
            "admin_cash_resource.py",
            "SessionSummaryResource",
            "get",
            client_ip,
            user__id,
            account_type,
            auth_business_id,
            business_id
        )
        
        try:
            if not session_id:
                Log.error(f"{log_tag} session_id required")
                return prepared_response(
                    status=False,
                    status_code="BAD_REQUEST",
                    message="session_id is required"
                )
            
            summary = CashSessionService.get_session_summary(
                session_id=session_id,
                business_id=business_id
            )
            
            if not summary:
                Log.error(f"{log_tag} Session not found")
                return prepared_response(
                    status=False,
                    status_code="NOT_FOUND",
                    message="Session not found"
                )
            
            Log.info(f"{log_tag} Summary retrieved")
            
            return prepared_response(
                status=True,
                status_code="OK",
                message="Session summary retrieved successfully",
                data=summary
            )
            
        except Exception as e:
            Log.error(f"{log_tag} Error: {str(e)}")
            return prepared_response(
                status=False,
                status_code="INTERNAL_SERVER_ERROR",
                message="Error retrieving session summary",
                errors=[str(e)]
            )
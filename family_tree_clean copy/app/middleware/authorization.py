"""
Authorization dependency — matches bi-dashboards-service/middleware/authorization.py.

Usage:
    app.include_router(
        family.router,
        prefix="/api/v1",
        dependencies=[Depends(Authorization(Group.ICP_FAMILY_TREE_DASHBOARD))],
    )

ADMIN is always allowed in addition to the listed groups (mirrors bi-dashboards).
"""
from fastapi import Depends, HTTPException

from app.common.errors import ErrorCode, get_error_message
from app.core.group import Group
from app.middleware.auth_bearer import JWTBearer
from app.utill.LoggingHandler import LoggingHandler

logger = LoggingHandler.get_logger(__name__)


class Authorization:
    def __init__(self, *required_groups: Group):
        self.required_groups = list(required_groups) if required_groups else []

    def __call__(self, user_context: dict = Depends(JWTBearer())):
        groups = user_context.get("groups", [])
        has_access = Group.ADMIN.value in groups or any(
            rg.value in groups for rg in self.required_groups
        )

        if not has_access:
            logger.warning(
                "authorization.deny | username=%s | required_any=%s | user_groups=%s",
                user_context.get("username"),
                [g.value for g in self.required_groups],
                groups,
            )
            raise HTTPException(
                status_code=403,
                detail={
                    "code": ErrorCode.FORBIDDEN_001,
                    "message": get_error_message(ErrorCode.FORBIDDEN_001),
                    "params": [],
                },
            )
        return user_context

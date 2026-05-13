"""
Error envelope — same shape as bi-dashboards-service/common/errors.py so the
frontend's response interceptor gets a consistent payload from both services:

    { "details": { "code": "...", "message": "...", "params": [...] } }
"""
from enum import Enum
from typing import Any, Optional

from fastapi import HTTPException

from app.utill.LoggingHandler import LoggingHandler

logger = LoggingHandler.get_logger(__name__)


class ErrorCode(str, Enum):
    INTERNAL_SERVER_ERROR_001 = "INTERNAL_SERVER_ERROR_001"

    FORBIDDEN_001 = "FORBIDDEN_001"

    NOT_AUTHENTICATED_001 = "NOT_AUTHENTICATED_001"

    UNAUTHORIZED_001 = "UNAUTHORIZED_001"
    UNAUTHORIZED_002 = "UNAUTHORIZED_002"
    UNAUTHORIZED_003 = "UNAUTHORIZED_003"
    UNAUTHORIZED_004 = "UNAUTHORIZED_004"

    INVALID_INPUT_001 = "INVALID_INPUT_001"
    INVALID_INTEGER_001 = "INVALID_INTEGER_001"
    INVALID_FLOAT_001 = "INVALID_FLOAT_001"
    INVALID_TIME_001 = "INVALID_TIME_001"
    INVALID_DATE_001 = "INVALID_DATE_001"
    INVALID_DATETIME_001 = "INVALID_DATETIME_001"

    RATE_LIMIT_EXCEEDED_001 = "RATE_LIMIT_EXCEEDED_001"

    # Family-tree specific
    FAMILY_TREE_SEARCH_TYPE_INVALID_001 = "FAMILY_TREE_SEARCH_TYPE_INVALID_001"
    FAMILY_TREE_VALUE_REQUIRED_001 = "FAMILY_TREE_VALUE_REQUIRED_001"
    FAMILY_TREE_EID_NO_DIGITS_001 = "FAMILY_TREE_EID_NO_DIGITS_001"


ERROR_MESSAGES = {
    ErrorCode.INTERNAL_SERVER_ERROR_001: "An unexpected error occurred. Please try again later or contact the administrator.",
    ErrorCode.FORBIDDEN_001: "Permission denied.",
    ErrorCode.NOT_AUTHENTICATED_001: "Not authenticated.",
    ErrorCode.UNAUTHORIZED_001: "Invalid authentication scheme.",
    ErrorCode.UNAUTHORIZED_002: "Invalid authorization code.",
    ErrorCode.UNAUTHORIZED_003: "Invalid token.",
    ErrorCode.UNAUTHORIZED_004: "Token has expired.",
    ErrorCode.INVALID_INTEGER_001: "Input should be a valid integer, unable to parse input '{placeholder}' as an integer.",
    ErrorCode.INVALID_FLOAT_001: "Input should be a valid float, unable to parse input '{placeholder}' as a float.",
    ErrorCode.INVALID_TIME_001: "Input should be a valid time, unable to parse input '{placeholder}' as a time.",
    ErrorCode.INVALID_DATE_001: "Input should be a valid date, unable to parse input '{placeholder}' as a date.",
    ErrorCode.INVALID_DATETIME_001: "Input should be a valid datetime, unable to parse input '{placeholder}' as a datetime.",
    ErrorCode.INVALID_INPUT_001: "Invalid input.",
    ErrorCode.RATE_LIMIT_EXCEEDED_001: "You have exceeded the allowed request limit. Try again after 60sec.",
    ErrorCode.FAMILY_TREE_SEARCH_TYPE_INVALID_001: "searchType must be UNIFIED_ID, EID, or PASSPORT.",
    ErrorCode.FAMILY_TREE_VALUE_REQUIRED_001: "value is required.",
    ErrorCode.FAMILY_TREE_EID_NO_DIGITS_001: "EID must contain digits.",
}


def get_error_message(error_code: ErrorCode) -> str:
    return ERROR_MESSAGES.get(error_code, "Unknown error")


def handle_errors(
    error_code: ErrorCode,
    status_code: int,
    e: Any = None,
    error_context: Optional[str] = None,
    params: Optional[list] = None,
    loggers=logger,
):
    error_context = error_context or "InternalServerError"
    error_message = get_error_message(error_code)
    exe = e if e else error_message

    loggers.error(
        f"{error_context} occurred",
        exc_info=True,
        extra={
            "error_code": error_code,
            "error_message": f"Error: {str(exe)}",
            "status_code": status_code,
        },
    )
    raise HTTPException(
        status_code=status_code,
        detail={
            "code": error_code,
            "message": get_error_message(error_code),
            "params": params if params else [],
        },
    )

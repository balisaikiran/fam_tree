"""
Shared error envelope.

All error responses follow the bi-dashboards-service contract:
    {"details": {"code": <ErrorCode>, "message": <str>, "params": [<...>]}}

`handle_errors(error_code, error_context, status_code)` raises an HTTPException
whose `.detail` already carries this envelope, and main.py installs an
exception handler that simply hands `.detail` straight back to the client.
"""
from enum import Enum
from typing import Any, List, Optional

from fastapi import HTTPException


class ErrorCode(str, Enum):
    # Auth
    NOT_AUTHENTICATED_001 = "NOT_AUTHENTICATED_001"
    UNAUTHORIZED_001 = "UNAUTHORIZED_001"
    UNAUTHORIZED_002 = "UNAUTHORIZED_002"
    UNAUTHORIZED_003 = "UNAUTHORIZED_003"
    UNAUTHORIZED_004 = "UNAUTHORIZED_004"
    FORBIDDEN_001 = "FORBIDDEN_001"

    # Generic input validation
    INVALID_INPUT_001 = "INVALID_INPUT_001"
    INVALID_INTEGER_001 = "INVALID_INTEGER_001"
    INVALID_FLOAT_001 = "INVALID_FLOAT_001"
    INVALID_DATE_001 = "INVALID_DATE_001"
    INVALID_TIME_001 = "INVALID_TIME_001"
    INVALID_DATETIME_001 = "INVALID_DATETIME_001"
    INVALID_ENUM_001 = "INVALID_ENUM_001"

    # Family-tree specific
    FAMILY_TREE_VALUE_REQUIRED_001 = "FAMILY_TREE_VALUE_REQUIRED_001"
    FAMILY_TREE_SEARCH_TYPE_INVALID_001 = "FAMILY_TREE_SEARCH_TYPE_INVALID_001"
    FAMILY_TREE_EID_NO_DIGITS_001 = "FAMILY_TREE_EID_NO_DIGITS_001"

    # Server
    INTERNAL_SERVER_ERROR_001 = "INTERNAL_SERVER_ERROR_001"
    RATE_LIMIT_EXCEEDED_001 = "RATE_LIMIT_EXCEEDED_001"
    SERVICE_UNAVAILABLE_001 = "SERVICE_UNAVAILABLE_001"


_DEFAULT_MESSAGES = {
    ErrorCode.NOT_AUTHENTICATED_001: "Not authenticated",
    ErrorCode.UNAUTHORIZED_001: "Unauthorized: invalid auth scheme",
    ErrorCode.UNAUTHORIZED_002: "Unauthorized: invalid credentials",
    ErrorCode.UNAUTHORIZED_003: "Unauthorized: invalid token",
    ErrorCode.UNAUTHORIZED_004: "Unauthorized: token expired",
    ErrorCode.FORBIDDEN_001: "Forbidden: missing required group",
    ErrorCode.INVALID_INPUT_001: "Invalid input",
    ErrorCode.INVALID_INTEGER_001: "Invalid integer value",
    ErrorCode.INVALID_FLOAT_001: "Invalid float value",
    ErrorCode.INVALID_DATE_001: "Invalid date value",
    ErrorCode.INVALID_TIME_001: "Invalid time value",
    ErrorCode.INVALID_DATETIME_001: "Invalid datetime value",
    ErrorCode.INVALID_ENUM_001: "Invalid enum value",
    ErrorCode.FAMILY_TREE_VALUE_REQUIRED_001: "Search value is required",
    ErrorCode.FAMILY_TREE_SEARCH_TYPE_INVALID_001: "Unknown search type",
    ErrorCode.FAMILY_TREE_EID_NO_DIGITS_001: "EID must contain digits",
    ErrorCode.INTERNAL_SERVER_ERROR_001: "Internal server error",
    ErrorCode.RATE_LIMIT_EXCEEDED_001: "Rate limit exceeded",
    ErrorCode.SERVICE_UNAVAILABLE_001: "Service unavailable",
}


def envelope(
    error_code: ErrorCode,
    message: Optional[str] = None,
    params: Optional[List[Any]] = None,
) -> dict:
    return {
        "details": {
            "code": error_code.value,
            "message": message or _DEFAULT_MESSAGES.get(error_code, error_code.value),
            "params": list(params or []),
        }
    }


def handle_errors(
    error_code: ErrorCode,
    error_context: str = "",
    status_code: int = 400,
    message: Optional[str] = None,
    params: Optional[List[Any]] = None,
) -> None:
    """Raise an HTTPException whose detail is the standard envelope."""
    raise HTTPException(status_code=status_code, detail=envelope(error_code, message, params)["details"])

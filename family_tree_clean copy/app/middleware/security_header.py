"""
Security headers — copied verbatim from bi-dashboards-service so the same set
is applied uniformly across both services.
"""


async def add_security_headers(request, call_next):
    response = await call_next(request)
    response.headers["Strict-Transport-Security"] = (
        "max-age=63072000; includeSubDomains"
    )
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Referrer-Policy"] = "no-referrer"

    if "X-Powered-By" in response.headers:
        del response.headers["X-Powered-By"]

    return response

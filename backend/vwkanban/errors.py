"""Error envelope: every API error is `{"error": {"code", "message"}}`."""

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException

_CODES = {
    400: "validation",
    401: "unauthenticated",
    403: "forbidden",
    404: "not_found",
    405: "not_found",
    409: "conflict",
    410: "gone",
    422: "validation",
}


class ApiError(HTTPException):
    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(status_code=status_code, detail=message)
        self.code = code


def error_body(code: str, message: str) -> dict:
    return {"error": {"code": code, "message": message}}


async def _http_error(request: Request, exc: HTTPException) -> JSONResponse:
    code = getattr(exc, "code", None) or _CODES.get(exc.status_code, "error")
    message = exc.detail if isinstance(exc.detail, str) else code
    return JSONResponse(error_body(code, message), status_code=exc.status_code, headers=exc.headers)


async def _validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
    errors = exc.errors()
    message = "invalid request"
    if errors:
        first = errors[0]
        field = ".".join(str(p) for p in first.get("loc", ()) if p != "body")
        msg = str(first.get("msg", "invalid")).removeprefix("Value error, ")
        message = f"{field}: {msg}" if field else msg
    return JSONResponse(error_body("validation", message), status_code=422)


def install_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(HTTPException, _http_error)
    app.add_exception_handler(RequestValidationError, _validation_error)

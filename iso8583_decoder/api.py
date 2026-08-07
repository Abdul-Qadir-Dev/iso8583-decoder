"""FastAPI application.

Core principle: a message that fails to decode is a successful API
call. Stops, diagnostics, partial results -- all 200, with the result
in the body. 4xx is reserved for a genuinely malformed *request*
(missing encoding, invalid encoding value, oversized body); 5xx is
reserved for actual server bugs. Even decode_message() raising
(MtiFormatError, UnsupportedVersionError -- the message is too broken
to even start) is caught here and reported as partial=true with a
reason_code, same as any other stop, not surfaced as an HTTP error:
the JSON *request* was well-formed even though the ISO 8583 *message*
inside it wasn't, and that distinction is what decides the status code.

Security, non-negotiable:
  - The raw message body is never logged, never echoed to stderr,
    never persisted. Only request metadata (endpoint, encoding, byte
    length, diagnostic codes) is logged.
  - The unhandled-exception handler returns a fixed, generic body and
    logs only the exception's type name -- never str(exc) or a
    traceback -- since an internal exception message could in
    principle embed a raw field value and there's no way to guarantee
    otherwise for a genuinely unexpected bug.
  - Request bodies over MAX_BODY_BYTES are rejected with 413 before
    the handler ever sees them.
  - No auth. This is a local/internal tool, not exposed as-is in
    production -- see the README.

Response fields are masked/redacted by default (render.py's existing
sensitivity rules), same as render.py's own reveal flag: off unless
the request explicitly asks for it. explain=true attaches
explain_fields()'s plain-language layer on top; it never changes what
`raw` contains, and interpretation runs on the *true* decoded values
internally regardless of the reveal setting used for display.
"""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from .diagnostics import Diagnostic, DiagnosticCode
from .explain import explain_fields
from .mti import (
    VERSION_SPEC_FILES,
    MtiDecodeResult,
    MtiFormatError,
    UnsupportedVersionError,
    load_spec_for_version,
)
from .parser import decode_message
from .render import mask_value
from .samples import Sample, get_sample, load_samples
from .schemas import (
    DecodeRequest,
    DecodeResponse,
    DiagnosticDefResponse,
    DiagnosticResponse,
    FieldResponse,
    HealthResponse,
    MtiComponentResponse,
    MtiResponse,
    SampleExpectedResponse,
    SampleResponse,
    SpecResponse,
)

MAX_BODY_BYTES = 64 * 1024
LOCAL_ORIGIN_REGEX = r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$"
WEB_DIR = Path(__file__).resolve().parent.parent / "web"

logger = logging.getLogger("iso8583_decoder.api")


def _log_request(endpoint: str, encoding: str, byte_length: int, diagnostic_codes: list[str]) -> None:
    """Request metadata only -- never the raw message or decoded values."""
    logger.info(
        "endpoint=%s encoding=%s byte_length=%d diagnostic_codes=%s",
        endpoint, encoding, byte_length, diagnostic_codes,
    )


def _mti_response(mti: MtiDecodeResult) -> MtiResponse:
    def component(c):
        return MtiComponentResponse(digit=c.digit, meaning=c.meaning)

    return MtiResponse(
        raw=mti.raw,
        version=component(mti.version),
        message_class=component(mti.message_class),
        function=component(mti.function),
        origin=component(mti.origin),
        summary=mti.summary,
    )


def _diagnostic_response(d: Diagnostic) -> DiagnosticResponse:
    return DiagnosticResponse(
        code=d.code.value,
        severity=d.severity.value,
        field_number=d.field_number,
        byte_offset=d.byte_offset,
        message=d.message,
    )


def _sample_response(s: Sample) -> SampleResponse:
    return SampleResponse(
        id=s.id,
        description=" ".join(s.description.split()),  # collapse the YAML block-scalar's whitespace
        transaction_type=s.transaction_type,
        encoding=s.encoding,
        raw=s.raw,
        expected=SampleExpectedResponse(
            partial=s.expected.partial,
            diagnostic_codes=sorted(s.expected.diagnostic_codes),
            stopped_at=s.expected.stopped_at,
            reason_code=s.expected.reason_code,
        ),
    )


def _unparseable_response(code: DiagnosticCode, message: str, request: DecodeRequest) -> DecodeResponse:
    diagnostic = Diagnostic(code=code, message=message, field_number=None, byte_offset=None)
    _log_request("/decode", request.encoding, len(request.raw), [code.value])
    return DecodeResponse(
        mti=None,
        fields=[],
        diagnostics=[_diagnostic_response(diagnostic)],
        partial=True,
        stopped_at="mti",
        reason_code=code.value,
    )


def _decode(request: DecodeRequest) -> DecodeResponse:
    try:
        result = decode_message(request.raw, encoding=request.encoding)
    except MtiFormatError as exc:
        return _unparseable_response(DiagnosticCode.MTI_FORMAT_INVALID, str(exc), request)
    except UnsupportedVersionError as exc:
        return _unparseable_response(DiagnosticCode.MTI_VERSION_UNSUPPORTED, str(exc), request)

    spec = load_spec_for_version(result.mti.version.digit)  # can't fail: decode_message already used this version
    explained = explain_fields(result.decoded_so_far, spec) if request.explain else None

    fields = []
    for field_number, raw_value in result.decoded_so_far.items():
        field_spec = spec.fields.get(field_number)
        display_value = mask_value(field_spec, raw_value, reveal=request.reveal) if field_spec else raw_value
        name = field_spec.name if field_spec else f"field {field_number}"
        interpreted = explained.fields[field_number].interpreted if explained else None
        fields.append(FieldResponse(field_number=field_number, name=name, raw=display_value, interpreted=interpreted))
    fields.sort(key=lambda f: f.field_number)

    diagnostics = [_diagnostic_response(d) for d in result.diagnostics]
    if explained is not None:
        diagnostics.extend(_diagnostic_response(d) for d in explained.diagnostics)

    reason_code = None
    if result.partial and result.reason is not None:
        # the stop cause isn't in result.diagnostics internally (see parser.py),
        # but the API surfaces it in the array too so its message/byte_offset
        # aren't lost -- reason_code is a pointer to which entry is the cause
        diagnostics.append(_diagnostic_response(result.reason))
        reason_code = result.reason.code.value

    _log_request("/decode", request.encoding, len(request.raw), [d.code for d in diagnostics])

    return DecodeResponse(
        mti=_mti_response(result.mti),
        fields=fields,
        diagnostics=diagnostics,
        partial=result.partial,
        stopped_at=result.stopped_at,
        reason_code=reason_code,
    )


async def _unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    # Type name only, never str(exc) or a traceback -- an internal exception's
    # message could in principle embed a raw field value, and there's no way
    # to guarantee otherwise for a genuinely unexpected bug.
    logger.error("unhandled exception: type=%s endpoint=%s", type(exc).__name__, request.url.path)
    return JSONResponse({"detail": "internal server error"}, status_code=500)


def create_app() -> FastAPI:
    app = FastAPI(title="ISO 8583 Decoder API", version="0.1.0")

    app.add_middleware(
        CORSMiddleware,
        allow_origin_regex=LOCAL_ORIGIN_REGEX,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def limit_body_size(request: Request, call_next):
        content_length = request.headers.get("content-length")
        if content_length is not None:
            try:
                too_big = int(content_length) > MAX_BODY_BYTES
            except ValueError:
                too_big = False
            if too_big:
                return JSONResponse({"detail": "request body too large"}, status_code=413)
        return await call_next(request)

    app.add_exception_handler(Exception, _unhandled_exception_handler)

    @app.post("/decode", response_model=DecodeResponse)
    def decode_endpoint(request: DecodeRequest) -> DecodeResponse:
        return _decode(request)

    @app.get("/diagnostics", response_model=list[DiagnosticDefResponse])
    def diagnostics_endpoint() -> list[DiagnosticDefResponse]:
        return [
            DiagnosticDefResponse(code=c.value, severity=c.severity.value, description=c.description)
            for c in DiagnosticCode.all()
        ]

    @app.get("/samples", response_model=list[SampleResponse])
    def samples_endpoint() -> list[SampleResponse]:
        return [_sample_response(s) for s in load_samples()]

    @app.get("/samples/{sample_id}", response_model=SampleResponse)
    def sample_detail_endpoint(sample_id: str) -> SampleResponse:
        try:
            sample = get_sample(sample_id)
        except KeyError:
            raise HTTPException(status_code=404, detail=f"no sample with id {sample_id!r}")
        return _sample_response(sample)

    @app.get("/specs", response_model=list[SpecResponse])
    def specs_endpoint() -> list[SpecResponse]:
        specs = []
        for digit in VERSION_SPEC_FILES:
            spec = load_spec_for_version(digit)
            specs.append(SpecResponse(version_digit=digit, variant=spec.variant, name=spec.name))
        return specs

    @app.get("/health", response_model=HealthResponse)
    def health_endpoint() -> HealthResponse:
        return HealthResponse()

    # Vercel's documented pattern for serving a FastAPI app's static assets:
    # app.mount(...) with StaticFiles gets promoted to the CDN at build time
    # there, and works identically under local uvicorn -- same ASGI-level
    # StaticFiles either way, nothing uvicorn-specific about it. html=True
    # serves web/index.html for "/". Mounted last so it only ever handles
    # paths none of the explicit routes above already claimed.
    app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")

    return app


app = create_app()

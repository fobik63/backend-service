"""Typed application errors for the generation submission pipeline."""

from __future__ import annotations


class GenerationSubmissionError(Exception):
    """Base error for create/status flows that map cleanly to HTTP."""

    status_code: int = 500
    code: str = "generation_error"

    def __init__(self, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        if code is not None:
            self.code = code


class GenerationValidationError(GenerationSubmissionError):
    status_code = 422
    code = "generation_validation_error"


class GenerationBadRequestError(GenerationSubmissionError):
    status_code = 400
    code = "generation_bad_request"


class GenerationPayloadTooLargeError(GenerationSubmissionError):
    status_code = 413
    code = "generation_payload_too_large"


class GenerationUnsupportedMediaError(GenerationSubmissionError):
    status_code = 415
    code = "generation_unsupported_media"


class GenerationForbiddenError(GenerationSubmissionError):
    status_code = 403
    code = "generation_forbidden"


class GenerationPaymentRequiredError(GenerationSubmissionError):
    status_code = 402
    code = "generation_payment_required"


class GenerationNotFoundError(GenerationSubmissionError):
    status_code = 404
    code = "generation_not_found"


class GenerationStorageUnavailableError(GenerationSubmissionError):
    status_code = 503
    code = "generation_storage_unavailable"


class GenerationInternalError(GenerationSubmissionError):
    status_code = 500
    code = "generation_internal_error"

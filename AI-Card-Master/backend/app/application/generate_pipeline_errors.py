"""Typed application errors for the n8n generate-pipeline bridge."""

from __future__ import annotations


class GeneratePipelineError(Exception):
    """Base error mapped to a stable HTTP envelope by the controller."""

    status_code: int = 500
    code: str = "generate_pipeline_error"

    def __init__(self, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        if code is not None:
            self.code = code


class GeneratePipelineValidationError(GeneratePipelineError):
    status_code = 422
    code = "generate_pipeline_validation_error"


class GeneratePipelineBadRequestError(GeneratePipelineError):
    status_code = 400
    code = "generate_pipeline_bad_request"


class GeneratePipelineNotConfiguredError(GeneratePipelineError):
    status_code = 503
    code = "generate_pipeline_not_configured"


class GeneratePipelineUpstreamError(GeneratePipelineError):
    status_code = 502
    code = "generate_pipeline_upstream_error"


class GeneratePipelineTimeoutError(GeneratePipelineError):
    status_code = 504
    code = "generate_pipeline_timeout"


class GeneratePipelineInternalError(GeneratePipelineError):
    status_code = 500
    code = "generate_pipeline_internal_error"

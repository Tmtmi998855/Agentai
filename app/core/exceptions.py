class AhThereException(Exception):
    """Base exception for Ah! There application."""
    def __init__(self, message: str, error_code: str = "INTERNAL_ERROR", detail: dict | None = None):
        super().__init__(message)
        self.message = message
        self.error_code = error_code
        self.detail = detail or {}


class ProviderException(AhThereException):
    """Exception raised during LLM provider execution."""
    def __init__(self, message: str, error_code: str = "PROVIDER_ERROR", detail: dict | None = None):
        super().__init__(message, error_code=error_code, detail=detail)


class ProviderAuthException(ProviderException):
    """Exception raised when LLM provider authentication fails (e.g., HTTP 401/403)."""
    def __init__(self, message: str = "Provider authentication failed", detail: dict | None = None):
        super().__init__(message, error_code="PROVIDER_AUTH_ERROR", detail=detail)


class ProviderTimeoutException(ProviderException):
    """Exception raised when a provider call times out."""
    def __init__(self, message: str = "Provider call timed out", detail: dict | None = None):
        super().__init__(message, error_code="PROVIDER_TIMEOUT", detail=detail)


class CitationIntegrityException(AhThereException):
    """Exception raised when evidence_id references non-existent evidence."""
    def __init__(self, message: str = "Invalid evidence_id referenced", detail: dict | None = None):
        super().__init__(message, error_code="INVALID_CITATION", detail=detail)


class ValidationException(AhThereException):
    """Exception raised for domain schema validation failures."""
    def __init__(self, message: str = "Domain validation failed", detail: dict | None = None):
        super().__init__(message, error_code="VALIDATION_ERROR", detail=detail)

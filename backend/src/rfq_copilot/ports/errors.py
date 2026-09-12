"""Copilot error taxonomy (authority: docs/specs/01-port-spec.md §8)."""


class CopilotError(Exception):
    """Base class for all engine errors."""


class ConfigError(CopilotError):
    """Manifest invalid or port implementation missing."""


class PortError(CopilotError):
    """Upstream (site) side problem."""


class PortTimeoutError(PortError):
    pass


class UpstreamAuthError(PortError):
    pass


class UpstreamInvalidResponseError(PortError):
    """Upstream response violates the port schema."""


class UpstreamUnavailableError(PortError):
    pass


class PolicyError(CopilotError):
    """Recoverable policy outcome: rendered as a template answer, not a failure."""


class CapabilityDisabledError(PolicyError):
    def __init__(self, capability: str) -> None:
        self.capability = capability
        super().__init__(f"capability disabled: {capability}")


class GuestNotAllowedError(PolicyError):
    pass


class MissingRequiredFieldsError(PolicyError):
    def __init__(self, fields: list[str]) -> None:
        self.fields = fields
        super().__init__(f"missing required fields: {fields}")


class ConfirmationRequiredError(PolicyError):
    pass


class ContentPolicyRefusalError(PolicyError):
    pass


class RateLimitError(CopilotError):
    pass

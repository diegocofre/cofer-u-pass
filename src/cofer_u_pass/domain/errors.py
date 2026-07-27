from __future__ import annotations

from cofer_u_pass.domain.models import FailureClass


class CoferUPassError(Exception):
    failure_class = FailureClass.FATAL


class ProtocolError(CoferUPassError):
    failure_class = FailureClass.PROTOCOL_ERROR


class AuthenticationRequired(CoferUPassError):
    failure_class = FailureClass.AUTHENTICATION


class AdapterMismatch(CoferUPassError):
    failure_class = FailureClass.ADAPTER_MISMATCH


class EnvironmentFailure(CoferUPassError):
    failure_class = FailureClass.ENVIRONMENT


class TransientFailure(CoferUPassError):
    failure_class = FailureClass.TRANSIENT


class OutcomeUnknown(CoferUPassError):
    failure_class = FailureClass.OUTCOME_UNKNOWN


class AdapterActionError(CoferUPassError):
    def __init__(self, message: str, *, failure_class: FailureClass, external_effect_possible: bool = False):
        super().__init__(message)
        self.failure_class = failure_class
        self.external_effect_possible = external_effect_possible

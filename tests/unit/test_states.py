import pytest

from cofer_u_pass.domain.models import RunState, assert_run_transition


def test_valid_run_transition():
    assert_run_transition(RunState.QUEUED, RunState.RUNNING)
    assert_run_transition(RunState.RUNNING, RunState.OUTCOME_UNKNOWN)


def test_invalid_terminal_transition_fails_closed():
    with pytest.raises(ValueError):
        assert_run_transition(RunState.COMPLETED, RunState.RUNNING)

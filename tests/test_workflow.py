import pytest

from backend.workflow import State, Workflow


def test_approval_blocks_navigation():
    flow = Workflow()
    flow.transition(State.READY)
    flow.transition(State.LOADING_IMAGE)
    flow.transition(State.READY)
    flow.transition(State.ANALYZING)
    flow.transition(State.AWAITING_APPROVAL)
    flow.unresolved = True
    with pytest.raises(ValueError, match="Resolve"):
        flow.transition(State.LOADING_IMAGE)
    flow.resolve("skipped")
    flow.transition(State.LOADING_IMAGE)
    assert flow.busy


def test_invalid_transition_and_decision():
    flow = Workflow()
    with pytest.raises(ValueError):
        flow.transition(State.APPLYING_TAGS)
    with pytest.raises(ValueError):
        flow.resolve("next")
from enum import StrEnum


class State(StrEnum):
    DISCONNECTED = "DISCONNECTED"
    READY = "READY"
    LOADING_IMAGE = "LOADING_IMAGE"
    ANALYZING = "ANALYZING"
    AWAITING_APPROVAL = "AWAITING_APPROVAL"
    APPLYING_TAGS = "APPLYING_TAGS"
    ERROR = "ERROR"
    COMPLETED = "COMPLETED"


class Workflow:
    def __init__(self) -> None:
        self.state = State.DISCONNECTED
        self.unresolved = False

    @property
    def busy(self) -> bool:
        return self.state in {State.LOADING_IMAGE, State.ANALYZING, State.APPLYING_TAGS}

    def transition(self, target: State) -> None:
        allowed = {
            State.DISCONNECTED: {State.READY, State.ERROR},
            State.READY: {State.LOADING_IMAGE, State.ANALYZING, State.AWAITING_APPROVAL, State.ERROR, State.COMPLETED},
            State.LOADING_IMAGE: {State.READY, State.AWAITING_APPROVAL, State.ERROR, State.COMPLETED},
            State.ANALYZING: {State.AWAITING_APPROVAL, State.LOADING_IMAGE, State.ERROR},
            State.AWAITING_APPROVAL: {State.ANALYZING, State.APPLYING_TAGS, State.LOADING_IMAGE, State.COMPLETED, State.READY, State.ERROR},
            State.APPLYING_TAGS: {State.AWAITING_APPROVAL, State.READY, State.ERROR},
            State.ERROR: {State.READY, State.LOADING_IMAGE, State.ANALYZING, State.APPLYING_TAGS, State.AWAITING_APPROVAL, State.COMPLETED},
            State.COMPLETED: {State.LOADING_IMAGE, State.READY, State.ANALYZING, State.AWAITING_APPROVAL, State.ERROR},
        }
        if target != self.state and target not in allowed[self.state]:
            raise ValueError(f"Invalid transition: {self.state} -> {target}")
        if self.unresolved and target in {State.LOADING_IMAGE, State.COMPLETED}:
            raise ValueError("Resolve the current approval before navigating.")
        self.state = target

    def resolve(self, decision: str) -> None:
        if decision not in {"applied", "skipped"}:
            raise ValueError("A review must be explicitly applied or skipped.")
        self.unresolved = False
from enum import StrEnum, auto


class JobStatus(StrEnum):
    PENDING = auto()  # job and tasks saved; events not sent yet
    RUNNING = auto()  # every event sent; the worker is processing tasks
    COMPLETED = auto()  # every task succeeded (from phase 3)
    COMPLETED_WITH_FAILURES = auto()  # every task finished, some failed (phase 3)
    FAILED = auto()  # the job could not run, e.g. its events could not be sent


class TaskStatus(StrEnum):
    PENDING = auto()  # waiting for the worker
    IN_PROGRESS = auto()  # claimed by the worker
    SUCCEEDED = auto()  # enriched (from phase 3)
    FAILED = auto()  # enrichment call failed (from phase 3)


class Tier(StrEnum):
    LARGE = auto()  # score >= the Large threshold
    MEDIUM = auto()  # score >= the Medium threshold, below Large
    SMALL = auto()  # below the Medium threshold

from enum import Enum


class ProcessStatus(str, Enum):
    """Status of process"""

    NOT_STARTED = "not_started"
    CREATING_SCRIPT = "creating_script"
    BUILDING_TRANSACTION = "building_transaction"
    TRANSACTION_BUILT = "transaction_built"
    SIGNING_TRANSACTION = "signing_transaction"
    TRANSACTION_SIGNED = "transaction_signed"
    SUBMITTING_TRANSACTION = "submitting_transaction"
    COMPLETED = "completed"
    FAILED = "failed"

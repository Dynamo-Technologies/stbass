"""stbass — Formal concurrency primitives for the agentic era."""

from stbass._version import __version__
from stbass.process import Process
from stbass.result import ProcessResult, Failure, FailurePolicy, FailureReport
from stbass.channel import Chan
from stbass.seq import SEQ
from stbass.par import PAR
from stbass.alt import ALT, PRI_ALT, Guard
from stbass.timer import TIMER, DEADLINE
from stbass.replicator import PAR_FOR, SEQ_FOR
from stbass.placement import PLACED_PAR, Placement, BackendRegistry, ExecutionBackend, LocalBackend
from stbass.topology import Distributor, Collector, ChanArray

__all__ = [
    "__version__",
    "Process",
    "ProcessResult",
    "Failure",
    "Chan",
    "SEQ",
    "PAR",
    "ALT",
    "PRI_ALT",
    "Guard",
    "TIMER",
    "DEADLINE",
    "PAR_FOR",
    "SEQ_FOR",
    "PLACED_PAR",
    "Placement",
    "FailurePolicy",
    "FailureReport",
    "Distributor",
    "Collector",
    "ChanArray",
    "BackendRegistry",
    "ExecutionBackend",
    "LocalBackend",
]

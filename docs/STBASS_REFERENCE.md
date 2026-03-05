# stbass Complete Reference

> **stbass** (Spinal Tap Bassist) v0.1.0 — Formal concurrency primitives for the agentic era.

stbass is a Python process algebra library for parallel orchestration of AI agents, inspired by the CSP (Communicating Sequential Processes) model and Occam-2's concurrency primitives. It provides typed channels, composable process primitives (PAR, SEQ, ALT), failure management, placement-aware execution, and MCP tool integration.

---

## Table of Contents

1. [Installation](#installation)
2. [Architecture Overview](#architecture-overview)
3. [Core Concepts](#core-concepts)
4. [Complete API Reference](#complete-api-reference)
   - [Process](#process)
   - [ProcessResult](#processresult)
   - [Failure](#failure)
   - [Chan (Channels)](#chan-channels)
   - [SEQ (Sequential Composition)](#seq-sequential-composition)
   - [PAR (Parallel Composition)](#par-parallel-composition)
   - [ALT and PRI_ALT (Alternation)](#alt-and-pri_alt-alternation)
   - [Guard](#guard)
   - [TIMER and DEADLINE](#timer-and-deadline)
   - [PAR_FOR and SEQ_FOR (Replicators)](#par_for-and-seq_for-replicators)
   - [ChanArray, Distributor, Collector (Topology)](#chanarray-distributor-collector-topology)
   - [Placement and PLACED_PAR](#placement-and-placed_par)
   - [ExecutionBackend, LocalBackend, BackendRegistry](#executionbackend-localbackend-backendregistry)
   - [FailurePolicy and RetryPolicy](#failurepolicy-and-retrypolicy)
   - [FailureReport](#failurereport)
   - [FailureAggregator](#failureaggregator)
   - [retry_process](#retry_process)
   - [MCP Integration](#mcp-integration)
5. [Channel Protocols](#channel-protocols)
6. [Patterns and Recipes](#patterns-and-recipes)
7. [Error Reference](#error-reference)
8. [Anti-Patterns (How NOT to Use stbass)](#anti-patterns)
9. [Testing Guide](#testing-guide)
10. [Common Workflows](#common-workflows)

---

## Installation

```bash
pip install stbass
```

### From source (development)

```bash
git clone <repo-url>
cd stbass
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

### Requirements

- Python >= 3.11
- Runtime dependencies: `pydantic>=2.0`, `httpx>=0.27`
- Dev dependencies: `pytest>=8.0`, `pytest-asyncio>=0.23`, `rich>=13.0`

### Verify installation

```python
from stbass import PAR, SEQ, ALT, Chan, Process
print("stbass ready")
```

---

## Architecture Overview

stbass models concurrent computation as a graph of **Processes** that communicate through **Channels** and compose via algebraic operators.

```
                    +------------------+
                    |   Composition    |
                    |  SEQ  PAR  ALT   |
                    +--------+---------+
                             |
              +--------------+--------------+
              |              |              |
        +-----------+  +-----------+  +-----------+
        |  Process  |  |  Process  |  |  Process  |
        |  (agent)  |  |  (agent)  |  |  (agent)  |
        +-----+-----+  +-----+-----+  +-----+-----+
              |              |              |
         +----+----+    +----+----+    +----+----+
         |  Chan   |    |  Chan   |    |  Chan   |
         | (typed) |    | (typed) |    | (typed) |
         +---------+    +---------+    +---------+
```

### Design Principles

| Principle | Meaning |
|-----------|---------|
| **Rendezvous semantics** | A sender blocks until a receiver consumes the value. No buffering. |
| **1:1 channel binding** | Each channel has at most one writer and one reader. |
| **Typed channels** | Every channel enforces a type spec at send time via Pydantic or isinstance checks. |
| **Immutable results** | `ProcessResult` and `Failure` are frozen dataclasses. |
| **Composition over inheritance** | Processes compose via SEQ, PAR, ALT — not by subclassing each other. |
| **Failure as data** | Failures are structured values with diagnostics, not just exceptions. |

### Module Map

| Module | Purpose |
|--------|---------|
| `stbass.process` | `Process` base class, `ProcessContext`, decorator pattern |
| `stbass.result` | `ProcessResult`, `Failure`, `FailurePolicy`, `RetryPolicy`, `FailureReport` |
| `stbass.channel` | `Chan`, type validation, protocols, channel errors |
| `stbass.seq` | `SEQ` sequential composition |
| `stbass.par` | `PAR` parallel composition |
| `stbass.alt` | `ALT`, `PRI_ALT`, `Guard`, `SKIP` |
| `stbass.timer` | `TIMER`, `DEADLINE`, `TimerExpired` |
| `stbass.replicator` | `PAR_FOR`, `SEQ_FOR` dynamic replication |
| `stbass.topology` | `ChanArray`, `Distributor`, `Collector` |
| `stbass.placement` | `Placement`, `PLACED_PAR`, `ExecutionBackend`, `BackendRegistry`, `LocalBackend` |
| `stbass.failure` | `FailureAggregator`, `retry_process` |
| `stbass.mcp` | `MCPProcess`, `MCPServer`, `MCPBackend` |

---

## Core Concepts

### Everything is a Process

A **Process** is any unit of async work that receives a `ProcessContext` and returns a `ProcessResult`. Processes can be defined two ways:

**1. Decorator (recommended for simple processes):**

```python
from stbass import Process, ProcessResult
from stbass.process import ProcessContext

@Process
async def my_agent(ctx: ProcessContext) -> ProcessResult:
    return ProcessResult.ok("done")
```

**2. Subclass (for stateful processes):**

```python
class MyAgent(Process):
    def __init__(self, model: str):
        super().__init__()
        self.model = model

    async def run(self, ctx: ProcessContext) -> ProcessResult:
        return ProcessResult.ok(f"used {self.model}")
```

### Channels are Typed Pipes

A **Chan** is a zero-buffered, typed communication pipe between exactly two processes. Values are validated at send time.

```python
from stbass import Chan

ch = Chan(int, name="scores")   # only accepts int values
await ch.send(42)               # blocks until a receiver calls recv()
value = await ch.recv()         # blocks until a sender calls send()
```

### Composition is Algebraic

Processes compose through three operators:

| Operator | Behavior |
|----------|----------|
| `SEQ(a, b, c)` | Run a, then b, then c. Output of each feeds input of next. |
| `PAR(a, b, c)` | Run a, b, c concurrently. Complete when all finish. |
| `ALT(Guard(ch1), Guard(ch2))` | Wait for whichever channel is ready first. |

---

## Complete API Reference

---

### Process

**Import:** `from stbass import Process`
**Also:** `from stbass.process import ProcessContext`

#### Creating Processes

##### Decorator — no arguments

```python
@Process
async def agent(ctx: ProcessContext) -> ProcessResult:
    return ProcessResult.ok("result")
```

The function name becomes the process name automatically (`agent.name == "agent"`).

##### Decorator — with arguments

```python
@Process(name="custom_name")
async def agent(ctx: ProcessContext) -> ProcessResult:
    return ProcessResult.ok("result")

@Process(placement=Placement(model="opus"))
async def placed_agent(ctx: ProcessContext) -> ProcessResult:
    return ProcessResult.ok("result")
```

**Decorator parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `name` | `str \| None` | Override the auto-derived process name |
| `placement` | `Placement \| None` | Default placement for this process |

##### Subclass

```python
class Researcher(Process):
    def __init__(self, topic: str):
        super().__init__()
        self.topic = topic

    async def run(self, ctx: ProcessContext) -> ProcessResult:
        # do research
        return ProcessResult.ok({"findings": [...]})
```

Subclasses **must** implement `async def run(self, ctx) -> ProcessResult`.

#### Process Methods

| Method | Signature | Description |
|--------|-----------|-------------|
| `run` | `async (ctx: ProcessContext) -> ProcessResult` | The main logic. Override in subclasses. |
| `execute` | `async (ctx: ProcessContext) -> ProcessResult` | Wraps `run()` with timing and error capture. Never override this. |
| `optional` | `() -> Process` | Returns a copy marked optional. Optional process failures don't halt PAR. |
| `with_channels` | `(**channels: Chan) -> Process` | Returns a copy with named channels bound. |
| `with_name` | `(name: str) -> Process` | Returns a copy with a new name. |

#### Process Properties

| Property | Type | Description |
|----------|------|-------------|
| `name` | `str` | The process name (auto-derived or explicit) |
| `process_id` | `str` | A fresh UUID on every access |

#### ProcessContext

Every process receives a `ProcessContext` that provides access to channels, checkpoints, and metadata.

```python
@dataclass
class ProcessContext:
    process_name: str
    process_id: str           # auto-generated UUID
    channels: dict[str, Chan] # named channels
    parent: str | None        # parent process name
    placement: Any | None     # placement info
    deadline: datetime | None # deadline if set
```

**Methods:**

| Method | Signature | Description |
|--------|-----------|-------------|
| `recv` | `async (channel_name: str) -> Any` | Receive a value from a named channel |
| `send` | `async (channel_name: str, value: Any) -> None` | Send a value to a named channel |
| `checkpoint` | `(value: Any) -> None` | Save a checkpoint value (captured in Failure if process fails) |
| `get_channel` | `(name: str) -> Chan` | Get a channel by name. Raises `KeyError` if not found. |

**Example — using context channels:**

```python
@Process
async def transformer(ctx: ProcessContext) -> ProcessResult:
    data = await ctx.recv("input")
    result = transform(data)
    await ctx.send("output", result)
    return ProcessResult.ok(result)
```

**Example — using checkpoints:**

```python
@Process
async def multi_step(ctx: ProcessContext) -> ProcessResult:
    ctx.checkpoint("started")
    step1 = do_step_1()
    ctx.checkpoint("step1_done")
    step2 = do_step_2(step1)
    ctx.checkpoint("step2_done")
    return ProcessResult.ok(step2)
```

If the process fails after step 1, the Failure will have `checkpoint="step1_done"`.

---

### ProcessResult

**Import:** `from stbass import ProcessResult`

An immutable (frozen dataclass) result of executing a process. Every process must return one.

#### Factory Methods

```python
# Success
result = ProcessResult.ok("my_value")
result = ProcessResult.ok(None)       # success with no value
result = ProcessResult.ok({"key": 1}) # any value type

# Failure
result = ProcessResult.fail(ValueError("bad input"))
result = ProcessResult.fail(
    RuntimeError("timeout"),
    process_name="agent_3",
    placement=some_placement,
)
```

**`ProcessResult.ok(value=None)`** — Create a successful result.

**`ProcessResult.fail(error, **context)`** — Create a failed result. Context kwargs are passed to the `Failure` constructor (e.g., `process_name`, `placement`, `parent_process`).

#### Properties

| Property | Type | Description |
|----------|------|-------------|
| `is_ok` | `bool` | `True` if successful |
| `is_fail` | `bool` | `True` if failed |
| `value` | `Any` | The success value. **Raises the original error if accessed on a failure.** |
| `failure` | `Failure` | The Failure object. **Raises `AttributeError` if accessed on a success.** |

**Always check `is_ok` before accessing `value`:**

```python
result = await some_process.execute(ctx)
if result.is_ok:
    print(result.value)
else:
    print(result.failure.summary)
```

---

### Failure

**Import:** `from stbass import Failure`

A frozen dataclass containing full diagnostic context about a process failure.

#### Fields

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `error` | `Exception` | required | The exception that caused the failure |
| `process_name` | `str` | `"unknown"` | Name of the failed process |
| `process_id` | `str` | auto UUID | Unique ID of the execution |
| `started_at` | `datetime \| None` | `None` | When execution started |
| `failed_at` | `datetime` | `now()` | When the failure occurred |
| `placement` | `Any \| None` | `None` | Placement info if using PLACED_PAR |
| `parent_process` | `str \| None` | `None` | Parent process name |
| `channel_state` | `dict` | `{}` | State of channels at failure time |
| `checkpoint` | `Any \| None` | `None` | Last checkpoint value before failure |
| `traceback_str` | `str` | `""` | Full Python traceback as string |

#### Properties

| Property | Type | Description |
|----------|------|-------------|
| `elapsed` | `timedelta \| None` | Time between `started_at` and `failed_at`. `None` if `started_at` is not set. |
| `summary` | `str` | One-line summary: `[process_name] ErrorType: message` |
| `detailed` | `str` | Multi-line diagnostic output including traceback |

**Example:**

```python
result = await agent.execute(ctx)
if result.is_fail:
    f = result.failure
    print(f.summary)    # [agent] ValueError: bad input
    print(f.elapsed)    # 0:00:00.032145
    print(f.detailed)   # full multi-line diagnostic
```

---

### Chan (Channels)

**Import:** `from stbass import Chan`
**Also:** `from stbass.channel import ChannelTypeError, ChannelClosedError, ChannelTopologyError, ChannelProtocolError, SequentialProtocol, VariantProtocol`

#### Constructor

```python
Chan(type_spec, *, name=None)
```

| Parameter | Type | Description |
|-----------|------|-------------|
| `type_spec` | `type \| SequentialProtocol \| VariantProtocol` | The type this channel enforces |
| `name` | `str \| None` | Human-readable name (auto-generated if omitted) |

#### Type Specifications

**Primitive types:**

```python
ch = Chan(int)                    # only int values
ch = Chan(str)                    # only str values
ch = Chan(dict)                   # only dict values
```

**Pydantic models (with auto-coercion from dicts):**

```python
from pydantic import BaseModel

class Query(BaseModel):
    text: str
    limit: int = 10

ch = Chan(Query)
await ch.send(Query(text="hello"))              # direct model
await ch.send({"text": "hello"})                # dict auto-coerced to Query
await ch.send({"text": "hello", "limit": 5})    # full dict
```

**SequentialProtocol (values must follow an exact type order):**

```python
from stbass.channel import SequentialProtocol

ch = Chan(SequentialProtocol(str, int, float))
await ch.send("hello")  # first must be str
await ch.send(42)        # second must be int
await ch.send(3.14)      # third must be float
# fourth send raises ChannelProtocolError (sequence exhausted)
```

**VariantProtocol (any of the specified types):**

```python
from stbass.channel import VariantProtocol

ch = Chan(VariantProtocol(str, int))
await ch.send("hello")  # ok
await ch.send(42)        # ok
await ch.send(3.14)      # raises ChannelTypeError
```

#### Channel Operations

```python
# Send (blocks until receiver is ready — rendezvous)
await ch.send(value)

# Receive (blocks until sender sends — rendezvous)
value = await ch.recv()

# Close (unblocks any waiting sender or receiver)
ch.close()
```

**Rendezvous semantics:** `send()` does not return until a corresponding `recv()` consumes the value. There is no buffer. This guarantees synchronization between writer and reader.

#### Channel Binding (Topology)

Channels enforce 1:1 binding — at most one writer and one reader.

```python
ch.bind_writer("process_a")   # register writer
ch.bind_reader("process_b")   # register reader
ch.unbind_writer()             # release writer
ch.unbind_reader()             # release reader
```

| Property | Type | Description |
|----------|------|-------------|
| `name` | `str` | Channel name |
| `type_spec` | `Any` | The type specification |
| `writer_attached` | `bool` | True if a writer is bound |
| `reader_attached` | `bool` | True if a reader is bound |
| `is_bound` | `bool` | True if both writer and reader are bound |

**Binding a second writer or reader raises `ChannelTopologyError`:**

```python
ch.bind_writer("a")
ch.bind_writer("b")  # raises ChannelTopologyError
```

---

### SEQ (Sequential Composition)

**Import:** `from stbass import SEQ`

Runs processes in order. The output of each process becomes the input to the next.

#### Constructor

```python
SEQ(*processes, on_failure=FailurePolicy.HALT)
```

| Parameter | Type | Description |
|-----------|------|-------------|
| `*processes` | `Process` | Processes to run in order |
| `on_failure` | `FailurePolicy` | What to do when a process fails (default: `HALT`) |

#### Running

```python
result = await SEQ(step1, step2, step3).run(input_value="start")
```

Each process receives an `"input"` channel with the previous stage's output and may write to an `"output"` channel. Two patterns work:

**Pattern A — Channel I/O (explicit):**

```python
@Process
async def step(ctx: ProcessContext) -> ProcessResult:
    data = await ctx.recv("input")
    result = transform(data)
    await ctx.send("output", result)
    return ProcessResult.ok(result)
```

**Pattern B — Return value only (simpler):**

```python
@Process
async def step(ctx: ProcessContext) -> ProcessResult:
    data = await ctx.recv("input")
    result = transform(data)
    return ProcessResult.ok(result)
```

Both patterns work. If the process writes to `"output"`, that value is used. If not, `result.value` is used.

#### Result: SEQResult

| Property | Type | Description |
|----------|------|-------------|
| `is_ok` | `bool` | True if all stages succeeded |
| `value` | `Any` | Value from the last successful stage |
| `results` | `list[ProcessResult]` | All individual results |
| `failures` | `list[Failure]` | All failures |

#### Failure Policies in SEQ

| Policy | Behavior |
|--------|----------|
| `FailurePolicy.HALT` | Stop pipeline at first failure. Subsequent stages do not run. |
| `FailurePolicy.COLLECT` | Continue pipeline after failure. Next stage receives `None` as input. |

**Example — three-stage pipeline:**

```python
@Process
async def parse(ctx: ProcessContext) -> ProcessResult:
    raw = await ctx.recv("input")
    return ProcessResult.ok(json.loads(raw))

@Process
async def validate(ctx: ProcessContext) -> ProcessResult:
    data = await ctx.recv("input")
    if "name" not in data:
        raise ValueError("missing name")
    return ProcessResult.ok(data)

@Process
async def save(ctx: ProcessContext) -> ProcessResult:
    data = await ctx.recv("input")
    db.insert(data)
    return ProcessResult.ok("saved")

result = await SEQ(parse, validate, save).run(input_value='{"name": "test"}')
```

#### Context Manager

```python
async with SEQ(step1, step2) as pipeline:
    result = await pipeline.run(input_value=data)
```

---

### PAR (Parallel Composition)

**Import:** `from stbass import PAR`

Runs processes concurrently. All processes start at the same time.

#### Constructor

```python
PAR(*processes, on_failure=FailurePolicy.HALT, deadline=None)
```

| Parameter | Type | Description |
|-----------|------|-------------|
| `*processes` | `Process` | Processes to run concurrently |
| `on_failure` | `FailurePolicy` | How to handle failures |
| `deadline` | `float \| None` | Maximum seconds before cancelling remaining processes |

#### Running

```python
result = await PAR(agent_a, agent_b, agent_c).run()
```

#### Result: PARResult

| Property | Type | Description |
|----------|------|-------------|
| `is_ok` | `bool` | True if all processes succeeded |
| `results` | `list[ProcessResult]` | All results in declaration order |
| `successes` | `list[ProcessResult]` | Only successful results |
| `failures` | `list[Failure]` | Only failures |
| `value` | `list` | List of success values |

#### Failure Policies in PAR

| Policy | Behavior |
|--------|----------|
| `FailurePolicy.HALT` | Cancel all remaining processes when any non-optional process fails |
| `FailurePolicy.COLLECT` | Run all processes to completion, collect all results |

**Example — halt on failure:**

```python
result = await PAR(
    critical_agent,
    important_agent,
    on_failure=FailurePolicy.HALT,
).run()
# If critical_agent fails, important_agent is cancelled immediately
```

**Example — collect all results:**

```python
result = await PAR(
    agent_a, agent_b, agent_c,
    on_failure=FailurePolicy.COLLECT,
).run()

print(f"{len(result.successes)} succeeded, {len(result.failures)} failed")
```

#### Optional Processes

Mark a process as optional so its failure doesn't trigger HALT:

```python
result = await PAR(
    critical_agent,
    nice_to_have_agent.optional(),   # failure won't halt others
    on_failure=FailurePolicy.HALT,
).run()
```

#### Deadlines

Cancel all processes that haven't finished within a time limit:

```python
result = await PAR(
    slow_agent, fast_agent,
    on_failure=FailurePolicy.COLLECT,
    deadline=5.0,   # 5 seconds max
).run()
```

Processes that exceed the deadline receive `CancelledError` and appear as failures in the result.

---

### ALT and PRI_ALT (Alternation)

**Import:** `from stbass import ALT, PRI_ALT, Guard`

Wait for one of several guarded channel operations. Only the first ready channel is consumed.

#### ALT (Fair Selection)

```python
result = await ALT(
    Guard(channel_a, handler=lambda v: f"from_a: {v}"),
    Guard(channel_b, handler=lambda v: f"from_b: {v}"),
)
```

When multiple guards are ready simultaneously, ALT picks **randomly** among them (fair selection).

#### PRI_ALT (Priority Selection)

```python
result = await PRI_ALT(
    Guard(high_priority_ch, handler=lambda v: v),    # checked first
    Guard(low_priority_ch, handler=lambda v: v),      # checked second
    Guard(TIMER(seconds=5.0), handler=lambda v: "timeout"),  # fallback
)
```

PRI_ALT picks the **first ready guard in declaration order** (priority selection).

#### How ALT works internally

ALT uses a polling loop with `asyncio.sleep(0)` to check channel readiness without consuming values. It checks `channel._queue.empty()` for channels and timer events for timers. Only the winning guard's channel is consumed via `recv()`.

---

### Guard

**Import:** `from stbass import Guard`

A guard wraps a channel (or timer, or SKIP sentinel) with an optional precondition and handler.

#### Constructor

```python
Guard(channel, *, precondition=True, handler=None)
```

| Parameter | Type | Description |
|-----------|------|-------------|
| `channel` | `Chan \| TIMER \| DEADLINE \| SKIP` | The channel or timer to guard |
| `precondition` | `bool \| Callable[[], bool]` | Static or dynamic eligibility condition |
| `handler` | `Callable \| None` | Transform the received value. If `None`, raw value is returned. |

#### Preconditions

```python
# Static — always eligible
Guard(ch, precondition=True, handler=...)

# Static — never eligible (disabled)
Guard(ch, precondition=False, handler=...)

# Dynamic — re-evaluated on each polling cycle
Guard(ch, precondition=lambda: cache.is_valid(), handler=...)
```

If **all** guards have `precondition=False` (statically), `AllGuardsDisabledError` is raised.

#### SKIP Sentinel

**Import:** `from stbass.alt import SKIP`

SKIP is always ready. It's the lowest-priority fallback in ALT:

```python
from stbass.alt import SKIP

result = await ALT(
    Guard(ch, handler=lambda v: v),
    Guard(SKIP, handler=lambda: "nothing_ready"),
)
```

ALT prefers non-SKIP guards when others are ready. SKIP only fires when no channel or timer is ready.

---

### TIMER and DEADLINE

**Import:** `from stbass import TIMER, DEADLINE`
**Also:** `from stbass.timer import TimerExpired`

#### TIMER

Fires after a duration:

```python
t = TIMER(seconds=5.0)
t = TIMER(seconds=0.5, name="agent_timeout")
```

| Parameter | Type | Description |
|-----------|------|-------------|
| `seconds` | `float` | Duration in seconds |
| `name` | `str \| None` | Optional name (auto-generated if omitted) |

#### DEADLINE

Fires at a specific point in time:

```python
from datetime import datetime, timedelta

target = datetime.now() + timedelta(minutes=5)
d = DEADLINE(target, name="hard_deadline")
print(d.remaining)  # timedelta until deadline
```

| Parameter | Type | Description |
|-----------|------|-------------|
| `target` | `datetime` | When to fire |
| `name` | `str \| None` | Optional name |

| Property | Type | Description |
|----------|------|-------------|
| `remaining` | `timedelta` | Time remaining until deadline |
| `seconds` | `float` | Remaining seconds (for ALT integration) |

#### Using Timers in ALT

```python
result = await PRI_ALT(
    Guard(data_channel, handler=lambda v: v),
    Guard(TIMER(seconds=10.0), handler=lambda v: "timed_out"),
)
```

When a timer fires, the handler receives a `TimerExpired` value.

#### TimerExpired

**Import:** `from stbass.timer import TimerExpired`

Frozen dataclass produced when a timer or deadline fires.

| Field | Type | Description |
|-------|------|-------------|
| `started_at` | `datetime` | When the ALT began waiting |
| `deadline` | `datetime` | When the timer/deadline was set to fire |
| `elapsed` | `timedelta` | Actual elapsed time |
| `timer_name` | `str` | Name of the timer |
| `last_checkpoint` | `Any \| None` | Last checkpoint if applicable |

---

### PAR_FOR and SEQ_FOR (Replicators)

**Import:** `from stbass.replicator import PAR_FOR, SEQ_FOR`
**Also re-exported from:** `from stbass import PAR_FOR, SEQ_FOR`

Dynamic fan-out: create N instances of a process from a factory function.

#### PAR_FOR

Runs N instances concurrently:

```python
result = await PAR_FOR(
    count=10,
    factory=my_worker,
    on_failure=FailurePolicy.COLLECT,
    deadline=30.0,
).run()
```

| Parameter | Type | Description |
|-----------|------|-------------|
| `count` | `int \| Callable[[], int]` | Number of instances, or a callable returning the count |
| `factory` | `Callable[[int, ProcessContext], Awaitable[ProcessResult]]` | Function that creates work for each index |
| `on_failure` | `FailurePolicy` | How to handle failures (default: `HALT`) |
| `deadline` | `float \| None` | Maximum seconds |

**Factory signature:**

```python
async def my_worker(index: int, ctx: ProcessContext) -> ProcessResult:
    # index is 0, 1, 2, ... count-1
    return ProcessResult.ok(f"result_{index}")
```

**Dynamic count:**

```python
items = fetch_items()
result = await PAR_FOR(
    count=lambda: len(items),
    factory=lambda i, ctx: process_item(items[i], ctx),
).run()
```

#### SEQ_FOR

Runs N instances sequentially (one at a time, in order):

```python
result = await SEQ_FOR(
    count=5,
    factory=my_worker,
    on_failure=FailurePolicy.HALT,
).run()
```

Returns a `SEQResult` with results in order.

#### Nesting Replicators

Replicators can nest — subagents spawning subagents:

```python
async def inner_worker(idx, ctx):
    return ProcessResult.ok(idx)

async def outer_worker(idx, ctx):
    result = await PAR_FOR(count=3, factory=inner_worker).run()
    return ProcessResult.ok(f"outer_{idx}")

result = await PAR_FOR(count=4, factory=outer_worker).run()
# Creates 4 outer workers, each spawning 3 inner workers = 12 total
```

---

### ChanArray, Distributor, Collector (Topology)

**Import:** `from stbass import ChanArray, Distributor, Collector`
**Also:** `from stbass.topology import ChanArray, Distributor, Collector`

#### ChanArray

An indexed array of identically-typed channels:

```python
arr = ChanArray(int, 5, name_prefix="worker")
# Creates 5 channels: worker[0], worker[1], ..., worker[4]
```

| Parameter | Type | Description |
|-----------|------|-------------|
| `type_spec` | `Any` | Type specification for all channels |
| `count` | `int` | Number of channels |
| `name_prefix` | `str \| None` | Prefix for channel names |

| Property/Method | Description |
|-----------------|-------------|
| `count` | Number of channels |
| `type_spec` | The type specification |
| `channels` | List of Chan objects |
| `arr[i]` | Get channel by index |
| `len(arr)` | Number of channels |
| `for ch in arr` | Iterate over channels |

#### Distributor (Fan-Out)

Reads values from one source channel and distributes them to multiple target channels:

```python
source = Chan(int, name="source")
targets = ChanArray(int, 3, name_prefix="target")

dist = Distributor(source, targets, strategy="round_robin")
```

| Parameter | Type | Description |
|-----------|------|-------------|
| `source` | `Chan` | Source channel to read from |
| `targets` | `ChanArray \| list[Chan]` | Target channels to distribute to |
| `strategy` | `str` | Distribution strategy |

**Strategies:**

| Strategy | Behavior |
|----------|----------|
| `"round_robin"` | Cycles through targets: 0, 1, 2, 0, 1, 2, ... |
| `"broadcast"` | Sends every value to all targets |
| `"ready_first"` | Sends to whichever target accepts first |

When the source channel closes, the Distributor closes all target channels.

#### Collector (Fan-In)

Reads values from multiple source channels and sends them to one sink channel:

```python
sources = ChanArray(int, 3, name_prefix="src")
sink = Chan(int, name="sink")

collector = Collector(sources, sink, ordered=False)
```

| Parameter | Type | Description |
|-----------|------|-------------|
| `sources` | `ChanArray \| list[Chan]` | Source channels to read from |
| `sink` | `Chan` | Destination channel |
| `ordered` | `bool` | If `True`, drain channels sequentially. If `False`, collect as values arrive. |

When all source channels close, the Collector closes the sink channel.

---

### Placement and PLACED_PAR

**Import:** `from stbass import Placement, PLACED_PAR`
**Also:** `from stbass.placement import Placement, PLACED_PAR, BackendRegistry, ExecutionBackend, LocalBackend`

#### Placement

Describes where a process should execute:

```python
opus = Placement(model="claude-opus-4-5-20250414", endpoint="anthropic")
haiku = Placement(model="claude-haiku-4-5-20250414", endpoint="anthropic")
local = Placement(model="llama-3", endpoint="local:8080", config={"temperature": 0.7})
```

| Field | Type | Description |
|-------|------|-------------|
| `model` | `str \| None` | Model name |
| `endpoint` | `str \| None` | Endpoint identifier |
| `config` | `dict \| None` | Arbitrary backend configuration |

| Property | Type | Description |
|----------|------|-------------|
| `summary` | `str` | Human-readable summary |

#### PLACED_PAR

Like PAR, but each process is paired with a Placement:

```python
result = await PLACED_PAR(
    (reasoning_agent, Placement(model="opus", endpoint="anthropic")),
    (classifier_agent, Placement(model="haiku", endpoint="anthropic")),
    (embed_agent, Placement(model="nomic", endpoint="local:8080")),
    on_failure=FailurePolicy.COLLECT,
    deadline=30.0,
).run()
```

| Parameter | Type | Description |
|-----------|------|-------------|
| `*pairs` | `tuple[Process, Placement]` | Process-placement pairs |
| `on_failure` | `FailurePolicy` | Failure handling |
| `deadline` | `float \| None` | Timeout in seconds |
| `registry` | `BackendRegistry \| None` | Custom registry (uses global default if omitted) |

Returns a `PARResult`. Placement info is captured in `Failure.placement` on failure.

---

### ExecutionBackend, LocalBackend, BackendRegistry

**Import:** `from stbass.placement import ExecutionBackend, LocalBackend, BackendRegistry`

#### ExecutionBackend (Abstract Base Class)

Implement this to create custom execution backends:

```python
class MyCloudBackend(ExecutionBackend):
    async def execute(self, process, ctx):
        # route to cloud
        return await process.execute(ctx)

    async def health_check(self):
        return True

    @property
    def concurrency_limit(self):
        return 100

    @property
    def name(self):
        return "my-cloud"
```

| Method/Property | Description |
|-----------------|-------------|
| `execute(process, ctx)` | Execute a process (async) |
| `health_check()` | Check if backend is available (async) |
| `concurrency_limit` | Max concurrent processes (property) |
| `name` | Backend identifier (property) |

#### LocalBackend

The default backend. Runs processes directly via asyncio:

```python
backend = LocalBackend()
result = await backend.execute(my_process, ctx)
```

#### BackendRegistry

Maps placement specs to backends:

```python
registry = BackendRegistry()
registry.register("anthropic", my_anthropic_backend)
registry.register("local", my_local_backend)

backend = registry.get(Placement(endpoint="anthropic"))  # returns my_anthropic_backend
backend = registry.get(Placement(endpoint="unknown"))     # returns default (LocalBackend)
```

| Method/Property | Description |
|-----------------|-------------|
| `register(name, backend)` | Register a named backend |
| `get(placement)` | Look up backend by placement (falls back to default) |
| `default` | The default LocalBackend |

---

### FailurePolicy and RetryPolicy

**Import:** `from stbass import FailurePolicy`
**Also:** `from stbass.result import RetryPolicy`

#### FailurePolicy

```python
class FailurePolicy(Enum):
    HALT = "halt"        # stop on first failure
    COLLECT = "collect"  # run all, collect results
```

**Factory for RetryPolicy:**

```python
policy = FailurePolicy.retry(
    max_attempts=5,
    backoff="exponential",  # or "linear" or "constant"
    base_delay=1.0,
)
```

#### RetryPolicy

```python
policy = RetryPolicy(max_attempts=5, backoff="exponential", base_delay=1.0)
```

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `max_attempts` | `int` | required | Maximum number of attempts |
| `backoff` | `str` | `"exponential"` | Backoff strategy |
| `base_delay` | `float` | `1.0` | Base delay in seconds |

**Backoff strategies:**

| Strategy | Formula | Example (base=1.0) |
|----------|---------|---------------------|
| `"exponential"` | `base * 2^attempt` | 1s, 2s, 4s, 8s, 16s |
| `"linear"` | `base * (attempt + 1)` | 1s, 2s, 3s, 4s, 5s |
| `"constant"` | `base` | 1s, 1s, 1s, 1s, 1s |

```python
policy = RetryPolicy(max_attempts=3, backoff="exponential", base_delay=0.5)
policy.delay_for(0)  # 0.5
policy.delay_for(1)  # 1.0
policy.delay_for(2)  # 2.0
```

---

### FailureReport

**Import:** `from stbass import FailureReport`

Aggregated analysis of process execution results with pattern detection.

#### Building a Report

```python
report = FailureReport()
for r in par_result.results:
    report.add(r)
```

#### Fields

| Field | Type | Description |
|-------|------|-------------|
| `total_processes` | `int` | Total processes tracked |
| `succeeded` | `int` | Count of successes |
| `failed` | `int` | Count of failures |
| `failures` | `list[Failure]` | All failure objects |

#### Properties

| Property | Type | Description |
|----------|------|-------------|
| `failure_rate` | `float` | `failed / total_processes` (0.0 if empty) |
| `common_failure_types` | `dict[str, int]` | Error type name to count |
| `slowest_failure` | `Failure \| None` | Failure with longest elapsed time |

#### Methods

| Method | Return | Description |
|--------|--------|-------------|
| `add(result)` | `None` | Add a ProcessResult to the report |
| `pattern_analysis()` | `dict` | Detect failure patterns (see below) |
| `recommendations()` | `list[str]` | Human-readable engineering recommendations |
| `to_dict()` | `dict` | Serializable representation |
| `summary()` | `str` | Multi-line text summary |

#### Pattern Analysis

```python
patterns = report.pattern_analysis()
```

Returns a dict with:

| Key | Type | Description |
|-----|------|-------------|
| `"repeat_timeouts"` | `list[str]` | Process names with repeated TimerExpired failures |
| `"repeat_errors"` | `list[tuple[str, str]]` | `(process_name, error_type)` pairs recurring 2+ times |
| `"cascade_failures"` | `bool` | True if consecutive failures occurred < 100ms apart |

#### Recommendations

```python
recs = report.recommendations()
for r in recs:
    print(r)
```

Generates actionable messages like:
- `"Process 'slow_agent' timeout 3/5 runs — consider increasing deadline or optimizing"`
- `"Process 'parser' consistently fails with ValueError — check input validation"`
- `"Cascade failure detected — consider adding FailurePolicy.COLLECT to isolate"`

#### Serialization

```python
d = report.to_dict()
# {
#   "total_processes": 10,
#   "succeeded": 8,
#   "failed": 2,
#   "failure_rate": 0.2,
#   "failures": [
#     {"process_name": "agent_x", "error_type": "ValueError", "error_message": "..."},
#     ...
#   ]
# }
```

---

### FailureAggregator

**Import:** `from stbass.failure import FailureAggregator`

Collects `FailureReport` objects across multiple pipeline runs for longitudinal analysis.

```python
agg = FailureAggregator()

for run in range(10):
    result = await PAR_FOR(count=5, factory=worker, on_failure=FailurePolicy.COLLECT).run()
    report = FailureReport()
    for r in result.results:
        report.add(r)
    agg.add_report(report)

print(agg.overall_summary())
worst = agg.worst_processes(n=3)
print(f"Worst processes: {worst}")
```

| Method | Return | Description |
|--------|--------|-------------|
| `add_report(report)` | `None` | Add a FailureReport |
| `overall_summary()` | `str` | Summary across all reports |
| `worst_processes(n=5)` | `list[str]` | Process names with highest failure counts |

---

### retry_process

**Import:** `from stbass.failure import retry_process`

Retry a process according to a `RetryPolicy`:

```python
from stbass.failure import retry_process
from stbass.result import RetryPolicy

policy = RetryPolicy(max_attempts=5, backoff="exponential", base_delay=0.5)
ctx = ProcessContext(process_name="flaky_agent")
result = await retry_process(my_agent, ctx, policy)
```

| Parameter | Type | Description |
|-----------|------|-------------|
| `process` | `Process` | The process to retry |
| `ctx` | `ProcessContext` | Context to pass on each attempt |
| `policy` | `RetryPolicy` | Retry configuration |

Returns the first successful `ProcessResult`, or the last failure if all attempts are exhausted.

**Behavior:**
1. Execute the process
2. If `is_ok`, return immediately
3. If `is_fail` and attempts remain, wait `policy.delay_for(attempt)` seconds, then retry
4. If all attempts exhausted, return the final failure

---

### MCP Integration

**Import:** `from stbass.mcp import MCPProcess, MCPServer, MCPBackend`

#### MCPProcess

Wraps a single MCP tool as an stbass Process:

```python
search = MCPProcess("http://mcp-server.com/sse", "web_search", timeout=10.0)

# Use like any other process
result = await PAR(search, other_agent).run()
```

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `server_url` | `str` | required | MCP server URL |
| `tool_name` | `str` | required | Name of the tool to call |
| `timeout` | `float` | `30.0` | Timeout in seconds |

MCPProcess handles:
- Connection errors → `ProcessResult.fail()` with descriptive error
- Timeouts → `ProcessResult.fail()` with `TimeoutError`
- HTTP errors → `ProcessResult.fail()` with the HTTP exception

#### MCPServer

Represents a connected MCP server:

```python
server = MCPServer("http://mcp-server.com/sse", name="brave-search")

# Get a process for a specific tool
search_proc = server.tool("web_search", timeout=10.0)

# Health check
is_up = await server.health()

# List available tools
tool_names = await server.tools()
```

| Method | Return | Description |
|--------|--------|-------------|
| `tool(name, timeout=30.0)` | `MCPProcess` | Get a process for a tool |
| `health()` | `bool` | Check if server is reachable |
| `tools()` | `list[str]` | List available tool names |

| Property | Type | Description |
|----------|------|-------------|
| `url` | `str` | Server URL |
| `name` | `str` | Server name |

#### MCPBackend

An `ExecutionBackend` that routes to an MCP server:

```python
backend = MCPBackend("http://mcp-server.com/sse")

# Register with BackendRegistry
registry = BackendRegistry()
registry.register("mcp:brave", backend)
```

---

## Channel Protocols

### SequentialProtocol

Forces a channel to carry types in an exact sequence:

```python
from stbass.channel import SequentialProtocol

# First message must be str, second int, third float
proto = SequentialProtocol(str, int, float)
ch = Chan(proto, name="handshake")

await ch.send("hello")    # ok (str)
await ch.send(42)          # ok (int)
await ch.send(3.14)        # ok (float)
await ch.send("again")    # raises ChannelProtocolError (sequence exhausted)
```

Use this for multi-phase handshake protocols between processes.

### VariantProtocol

Allows a channel to accept any of several types:

```python
from stbass.channel import VariantProtocol

proto = VariantProtocol(str, int, dict)
ch = Chan(proto, name="flexible")

await ch.send("text")     # ok
await ch.send(42)          # ok
await ch.send({"k": "v"}) # ok
await ch.send(3.14)        # raises ChannelTypeError (float not in variants)
```

Use this for channels that carry heterogeneous message types (e.g., commands + data).

---

## Patterns and Recipes

### Research Fan-Out with Timeout

Fan out to N research agents, with a global deadline:

```python
async def research_agent(idx, ctx):
    result = await do_research(topics[idx])
    return ProcessResult.ok(result)

result = await PAR_FOR(
    count=len(topics),
    factory=research_agent,
    on_failure=FailurePolicy.COLLECT,
    deadline=30.0,
).run()

# Use whatever results came back in time
for r in result.successes:
    print(r.value)
```

### Pipeline with Retry Stage

```python
@Process
async def fetch(ctx: ProcessContext) -> ProcessResult:
    data = await ctx.recv("input")
    return ProcessResult.ok(await api.get(data))

@Process
async def transform(ctx: ProcessContext) -> ProcessResult:
    data = await ctx.recv("input")
    return ProcessResult.ok(process(data))

# Run pipeline, with retry on the flaky fetch stage
policy = RetryPolicy(max_attempts=3, backoff="exponential", base_delay=1.0)
ctx = ProcessContext(process_name="fetch", channels={"input": input_ch})
fetch_result = await retry_process(fetch, ctx, policy)

if fetch_result.is_ok:
    pipeline_result = await SEQ(transform, save).run(input_value=fetch_result.value)
```

### ALT with Cache/Search/Timeout Pattern

```python
@Process
async def smart_agent(ctx: ProcessContext) -> ProcessResult:
    cache_ch = Chan(dict)
    search_ch = Chan(dict)

    # Start cache lookup and search in background
    asyncio.create_task(check_cache(cache_ch))
    asyncio.create_task(run_search(search_ch))

    result = await PRI_ALT(
        Guard(cache_ch, handler=lambda v: ("cache", v)),      # fastest
        Guard(search_ch, handler=lambda v: ("search", v)),    # slower
        Guard(TIMER(seconds=5.0), handler=lambda v: ("timeout", None)),  # fallback
    )

    source, data = result
    return ProcessResult.ok({"source": source, "data": data})
```

### Heterogeneous Agent Placement

```python
result = await PLACED_PAR(
    (reasoning_agent, Placement(model="opus", endpoint="anthropic")),
    (classifier_agent, Placement(model="haiku", endpoint="anthropic")),
    (embed_agent, Placement(model="nomic", endpoint="local:8080")),
    on_failure=FailurePolicy.COLLECT,
).run()
```

### Distributor/Collector Pipeline

```python
source = Chan(int, name="tasks")
targets = ChanArray(int, 4, name_prefix="worker")
results_sink = Chan(int, name="results")

dist = Distributor(source, targets, strategy="round_robin")
collector = Collector(targets, results_sink, ordered=False)

# Run distributor, workers, and collector concurrently
async def feed():
    for i in range(100):
        await source.send(i)
    source.close()

async def drain():
    results = []
    try:
        while True:
            results.append(await results_sink.recv())
    except ChannelClosedError:
        pass
    return results

feed_task = asyncio.create_task(feed())
drain_task = asyncio.create_task(drain())

ctx = ProcessContext(process_name="topology")
await asyncio.gather(
    dist.run(ctx),
    collector.run(ctx),
)

await feed_task
all_results = await drain_task
```

### Failure Report Across Multiple Runs

```python
agg = FailureAggregator()

for batch in data_batches:
    result = await PAR_FOR(
        count=len(batch),
        factory=lambda i, ctx: process_item(batch[i]),
        on_failure=FailurePolicy.COLLECT,
        deadline=60.0,
    ).run()

    report = FailureReport()
    for r in result.results:
        report.add(r)
    agg.add_report(report)

    # Check recommendations after each batch
    recs = report.recommendations()
    for r in recs:
        logger.warning(r)

# Final analysis
print(agg.overall_summary())
print(f"Worst processes: {agg.worst_processes(n=3)}")
```

### MCP Tool in a PAR Composition

```python
from stbass.mcp import MCPServer

brave = MCPServer("http://localhost:3000/sse", name="brave-search")
search = brave.tool("web_search", timeout=10.0)

@Process
async def internal_analysis(ctx: ProcessContext) -> ProcessResult:
    return ProcessResult.ok({"analysis": "internal data"})

result = await PAR(
    search,
    internal_analysis,
    on_failure=FailurePolicy.COLLECT,
).run()
```

---

## Error Reference

### ChannelTypeError

**Inherits:** `TypeError`

Raised when a value sent to a channel does not match its type specification.

```python
ch = Chan(int)
await ch.send("not_an_int")  # raises ChannelTypeError
```

**Fields:** `expected`, `actual`, `channel_name`

**How to fix:** Ensure the value matches the channel's type_spec. For Pydantic models, the dict must match the model's schema.

### ChannelTopologyError

Raised when binding discipline is violated (e.g., binding a second writer).

```python
ch = Chan(int)
ch.bind_writer("process_a")
ch.bind_writer("process_b")  # raises ChannelTopologyError
```

**How to fix:** Each channel allows at most one writer and one reader. Use `unbind_writer()` / `unbind_reader()` before rebinding, or create a new channel.

### ChannelClosedError

Raised when sending to or receiving from a closed channel.

```python
ch = Chan(int)
ch.close()
await ch.send(42)  # raises ChannelClosedError
await ch.recv()     # raises ChannelClosedError
```

**How to fix:** Check channel state before operations, or catch this exception to handle graceful shutdown in loops:

```python
try:
    while True:
        value = await ch.recv()
        process(value)
except ChannelClosedError:
    pass  # channel was closed, stop processing
```

### ChannelProtocolError

Raised when a SequentialProtocol's type sequence is exhausted.

```python
ch = Chan(SequentialProtocol(str, int))
await ch.send("hello")
await ch.send(42)
await ch.send("extra")  # raises ChannelProtocolError
```

**How to fix:** Only send the exact number of values matching the protocol's type list.

### AllGuardsDisabledError

**Import:** `from stbass.alt import AllGuardsDisabledError`

Raised when all guards in an ALT have static `precondition=False`.

```python
await ALT(
    Guard(ch, precondition=False, handler=lambda v: v),
)  # raises AllGuardsDisabledError
```

**How to fix:** Ensure at least one guard has a true (or callable) precondition, or add a SKIP or TIMER fallback.

### KeyError from ProcessContext

Raised when accessing a channel name that doesn't exist in the context.

```python
ctx.get_channel("nonexistent")  # raises KeyError
await ctx.recv("nonexistent")   # raises KeyError
```

**How to fix:** Use `ctx.channels` to check available channels, or ensure your composition sets up the expected channels.

---

## Anti-Patterns

### Do NOT access `value` without checking `is_ok`

```python
# WRONG — will raise the original exception if result is a failure
print(result.value)

# CORRECT
if result.is_ok:
    print(result.value)
else:
    print(result.failure.summary)
```

### Do NOT use channels as buffers

```python
# WRONG — channels are zero-buffered (rendezvous)
# This will deadlock because send blocks until recv
await ch.send(1)
await ch.send(2)  # deadlock — no one received the first value
value = await ch.recv()

# CORRECT — sender and receiver must run concurrently
async def sender():
    await ch.send(1)
    await ch.send(2)

async def receiver():
    v1 = await ch.recv()
    v2 = await ch.recv()

await asyncio.gather(sender(), receiver())
```

### Do NOT bind multiple writers to the same channel

```python
# WRONG — violates 1:1 topology
ch = Chan(int)
ch.bind_writer("agent_a")
ch.bind_writer("agent_b")  # ChannelTopologyError

# CORRECT — use a Collector for fan-in
sources = ChanArray(int, 2)
sink = Chan(int)
collector = Collector(sources, sink)
```

### Do NOT use HALT when you need all results

```python
# WRONG — if any process fails, the rest are cancelled
result = await PAR(a, b, c, on_failure=FailurePolicy.HALT).run()
# result.results may have incomplete data

# CORRECT — use COLLECT to get all results
result = await PAR(a, b, c, on_failure=FailurePolicy.COLLECT).run()
for r in result.successes:
    use(r.value)
```

### Do NOT forget to close channels in topology patterns

```python
# WRONG — reader tasks hang forever waiting for more data
async def feed():
    for i in range(10):
        await source.send(i)
    # forgot to close!

# CORRECT
async def feed():
    for i in range(10):
        await source.send(i)
    source.close()  # signals readers that no more data is coming
```

### Do NOT use `await` in ALT guard handlers

```python
# WRONG — handlers should be synchronous transformations
Guard(ch, handler=lambda v: await some_async_op(v))

# CORRECT — transform synchronously in handler, do async work in the process
Guard(ch, handler=lambda v: {"received": v})
```

### Do NOT retry without backoff in production

```python
# WRONG — hammers the failing service
policy = RetryPolicy(max_attempts=100, backoff="constant", base_delay=0.0)

# CORRECT — use exponential backoff
policy = RetryPolicy(max_attempts=5, backoff="exponential", base_delay=1.0)
```

### Do NOT use PAR_FOR for sequential dependencies

```python
# WRONG — if step 2 depends on step 1's output, PAR runs them simultaneously
result = await PAR_FOR(count=3, factory=dependent_steps).run()

# CORRECT — use SEQ_FOR for ordered dependencies
result = await SEQ_FOR(count=3, factory=dependent_steps).run()
```

---

## Testing Guide

### Setup

```toml
# pyproject.toml
[project.optional-dependencies]
dev = ["pytest>=8.0", "pytest-asyncio>=0.23"]

[tool.pytest.ini_options]
asyncio_mode = "strict"
```

### Testing Processes

All stbass operations are async. Use `@pytest.mark.asyncio`:

```python
import pytest
from stbass import Process, ProcessResult
from stbass.process import ProcessContext

class TestMyAgent:
    @pytest.mark.asyncio
    async def test_basic_execution(self):
        @Process
        async def my_agent(ctx: ProcessContext) -> ProcessResult:
            return ProcessResult.ok("hello")

        ctx = ProcessContext(process_name="my_agent")
        result = await my_agent.execute(ctx)
        assert result.is_ok
        assert result.value == "hello"
```

### Testing SEQ Pipelines

```python
@pytest.mark.asyncio
async def test_pipeline():
    @Process
    async def step1(ctx: ProcessContext) -> ProcessResult:
        data = await ctx.recv("input")
        return ProcessResult.ok(data * 2)

    @Process
    async def step2(ctx: ProcessContext) -> ProcessResult:
        data = await ctx.recv("input")
        return ProcessResult.ok(data + 10)

    result = await SEQ(step1, step2).run(input_value=5)
    assert result.is_ok
    assert result.value == 20  # (5 * 2) + 10
```

### Testing PAR Compositions

```python
@pytest.mark.asyncio
async def test_parallel():
    @Process
    async def fast(ctx: ProcessContext) -> ProcessResult:
        return ProcessResult.ok("fast")

    @Process
    async def slow(ctx: ProcessContext) -> ProcessResult:
        await asyncio.sleep(0.01)
        return ProcessResult.ok("slow")

    result = await PAR(fast, slow).run()
    assert result.is_ok
    assert len(result.results) == 2
```

### Testing Failures

```python
@pytest.mark.asyncio
async def test_failure_handling():
    @Process
    async def failing(ctx: ProcessContext) -> ProcessResult:
        raise ValueError("expected error")

    ctx = ProcessContext(process_name="failing")
    result = await failing.execute(ctx)
    assert result.is_fail
    assert "expected error" in str(result.failure.error)
    assert result.failure.process_name == "failing"
    assert result.failure.traceback_str  # traceback captured
```

### Testing Channels

```python
@pytest.mark.asyncio
async def test_typed_channel():
    from stbass.channel import ChannelTypeError

    ch = Chan(int)
    with pytest.raises(ChannelTypeError):
        await asyncio.wait_for(ch.send("wrong_type"), timeout=0.5)

@pytest.mark.asyncio
async def test_channel_rendezvous():
    ch = Chan(str)
    async def sender():
        await ch.send("hello")
    task = asyncio.create_task(sender())
    value = await ch.recv()
    assert value == "hello"
    await task
```

### Testing with Timers

```python
@pytest.mark.asyncio
async def test_timer_fallback():
    ch = Chan(str)
    # No one sends to ch, so timer fires
    result = await ALT(
        Guard(ch, handler=lambda v: "data"),
        Guard(TIMER(seconds=0.05), handler=lambda v: "timeout"),
    )
    assert result == "timeout"
```

### Testing MCP (Mocked)

```python
from unittest.mock import AsyncMock, patch
from stbass.mcp import MCPProcess

@pytest.mark.asyncio
async def test_mcp_tool():
    proc = MCPProcess("http://fake.com/sse", "search", timeout=5.0)
    mock_result = {"results": ["a", "b"]}

    with patch.object(proc, '_call_tool', new_callable=AsyncMock, return_value=mock_result):
        ctx = ProcessContext(process_name="search")
        result = await proc.execute(ctx)
        assert result.is_ok
        assert result.value == mock_result
```

### Testing Concurrency Timing

```python
import time

@pytest.mark.asyncio
async def test_truly_parallel():
    async def worker(idx, ctx):
        await asyncio.sleep(0.1)
        return ProcessResult.ok(idx)

    start = time.monotonic()
    result = await PAR_FOR(count=10, factory=worker).run()
    elapsed = time.monotonic() - start

    assert result.is_ok
    assert elapsed < 0.5  # 10 * 0.1s parallel, not 1.0s sequential
```

---

## Common Workflows

### Workflow 1: API Call Orchestration

Fan out API calls to multiple services, collect results:

```python
import httpx
from stbass import Process, ProcessResult, PAR, FailurePolicy
from stbass.process import ProcessContext

@Process
async def call_service_a(ctx: ProcessContext) -> ProcessResult:
    async with httpx.AsyncClient() as client:
        resp = await client.get("https://api.service-a.com/data")
        return ProcessResult.ok(resp.json())

@Process
async def call_service_b(ctx: ProcessContext) -> ProcessResult:
    async with httpx.AsyncClient() as client:
        resp = await client.get("https://api.service-b.com/data")
        return ProcessResult.ok(resp.json())

async def orchestrate():
    result = await PAR(
        call_service_a,
        call_service_b,
        on_failure=FailurePolicy.COLLECT,
        deadline=10.0,
    ).run()

    for r in result.successes:
        print(r.value)
    for f in result.failures:
        print(f"Failed: {f.summary}")
```

### Workflow 2: ETL Pipeline

```python
@Process
async def extract(ctx: ProcessContext) -> ProcessResult:
    source = await ctx.recv("input")
    raw_data = await fetch_from_database(source)
    return ProcessResult.ok(raw_data)

@Process
async def transform(ctx: ProcessContext) -> ProcessResult:
    raw = await ctx.recv("input")
    cleaned = [clean_record(r) for r in raw]
    return ProcessResult.ok(cleaned)

@Process
async def load(ctx: ProcessContext) -> ProcessResult:
    records = await ctx.recv("input")
    await write_to_warehouse(records)
    return ProcessResult.ok(len(records))

async def run_etl():
    result = await SEQ(extract, transform, load).run(
        input_value="orders_2024"
    )
    if result.is_ok:
        print(f"Loaded {result.value} records")
    else:
        for f in result.failures:
            print(f.detailed)
```

### Workflow 3: Multi-Agent Research with Synthesis

```python
async def run_research(query: str):
    @Process
    async def plan(ctx: ProcessContext) -> ProcessResult:
        q = await ctx.recv("input")
        subtopics = generate_subtopics(q)
        return ProcessResult.ok(subtopics)

    @Process
    async def research_all(ctx: ProcessContext) -> ProcessResult:
        subtopics = await ctx.recv("input")

        async def research_one(idx, c):
            finding = await do_research(subtopics[idx])
            return ProcessResult.ok(finding)

        result = await PAR_FOR(
            count=len(subtopics),
            factory=research_one,
            on_failure=FailurePolicy.COLLECT,
            deadline=60.0,
        ).run()
        return ProcessResult.ok([r.value for r in result.successes])

    @Process
    async def synthesize(ctx: ProcessContext) -> ProcessResult:
        findings = await ctx.recv("input")
        report = create_report(findings)
        return ProcessResult.ok(report)

    result = await SEQ(plan, research_all, synthesize).run(
        input_value=query
    )
    return result.value
```

### Workflow 4: Batch Processing with Monitoring

```python
async def process_batch(items: list):
    agg = FailureAggregator()

    for batch in chunk(items, size=100):
        async def process_item(idx, ctx):
            item = batch[idx]
            result = await handle(item)
            return ProcessResult.ok(result)

        result = await PAR_FOR(
            count=len(batch),
            factory=process_item,
            on_failure=FailurePolicy.COLLECT,
            deadline=120.0,
        ).run()

        report = FailureReport()
        for r in result.results:
            report.add(r)
        agg.add_report(report)

        # Check health after each batch
        if report.failure_rate > 0.5:
            print("WARNING: >50% failure rate")
            print(report.recommendations())

    print(agg.overall_summary())
```

### Workflow 5: Script with Retry and Fallback

```python
from stbass.failure import retry_process
from stbass.result import RetryPolicy

async def resilient_fetch(url: str):
    @Process
    async def primary(ctx: ProcessContext) -> ProcessResult:
        async with httpx.AsyncClient() as client:
            resp = await client.get(url, timeout=5.0)
            return ProcessResult.ok(resp.json())

    @Process
    async def fallback(ctx: ProcessContext) -> ProcessResult:
        return ProcessResult.ok({"cached": True, "data": get_cached(url)})

    # Try primary with retries
    policy = RetryPolicy(max_attempts=3, backoff="exponential", base_delay=1.0)
    ctx = ProcessContext(process_name="primary")
    result = await retry_process(primary, ctx, policy)

    if result.is_ok:
        return result.value

    # Fall back to cache
    ctx = ProcessContext(process_name="fallback")
    fallback_result = await fallback.execute(ctx)
    return fallback_result.value
```

### Workflow 6: MCP Tool Server Integration

```python
from stbass.mcp import MCPServer

async def search_and_analyze(query: str):
    # Connect to MCP servers
    brave = MCPServer("http://localhost:3000/sse", name="brave")
    filesystem = MCPServer("http://localhost:3001/sse", name="fs")

    # Check health
    if not await brave.health():
        return {"error": "brave search unavailable"}

    # Create tool processes
    web_search = brave.tool("brave_web_search", timeout=15.0)
    read_file = filesystem.tool("read_file", timeout=5.0)

    # Run tools in parallel
    result = await PAR(
        web_search,
        read_file,
        on_failure=FailurePolicy.COLLECT,
    ).run()

    return {
        "web_results": result.results[0].value if result.results[0].is_ok else None,
        "file_data": result.results[1].value if result.results[1].is_ok else None,
    }
```

---

## Public API Surface

All symbols available from `import stbass`:

```python
from stbass import (
    # Version
    __version__,          # "0.1.0"

    # Core
    Process,              # Base class / decorator
    ProcessResult,        # Success/failure result
    Failure,              # Structured failure data
    Chan,                 # Typed channel

    # Composition
    SEQ,                  # Sequential composition
    PAR,                  # Parallel composition
    ALT,                  # Fair alternation
    PRI_ALT,              # Priority alternation
    Guard,                # Guard for ALT/PRI_ALT

    # Time
    TIMER,                # Duration-based timer
    DEADLINE,             # Absolute deadline

    # Replicators
    PAR_FOR,              # Dynamic parallel fan-out
    SEQ_FOR,              # Dynamic sequential iteration

    # Placement
    Placement,            # Execution placement descriptor
    PLACED_PAR,           # Placement-aware parallel composition
    BackendRegistry,      # Backend lookup registry
    ExecutionBackend,     # Abstract backend protocol
    LocalBackend,         # Default local backend

    # Topology
    ChanArray,            # Array of typed channels
    Distributor,          # Fan-out pattern
    Collector,            # Fan-in pattern

    # Failure
    FailurePolicy,        # HALT or COLLECT enum
    FailureReport,        # Aggregated failure analysis
)
```

Additional imports from submodules:

```python
from stbass.process import ProcessContext
from stbass.result import RetryPolicy
from stbass.timer import TimerExpired
from stbass.channel import (
    ChannelTypeError, ChannelTopologyError,
    ChannelClosedError, ChannelProtocolError,
    SequentialProtocol, VariantProtocol,
)
from stbass.alt import SKIP, AllGuardsDisabledError
from stbass.failure import FailureAggregator, retry_process
from stbass.mcp import MCPProcess, MCPServer, MCPBackend
```

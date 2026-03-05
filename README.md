# stbass

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

**Formal concurrency primitives for the agentic era. Too many bass players? Now they're in tune.**

Named after Spinal Tap's infamous revolving door of bass players -- each one meeting a more absurd fate than the last. Like an uncoordinated parallel system, nobody knew who was playing bass at any given time. `stbass` brings order to that chaos.

## Why

`stbass` is a process algebra library inspired by Occam-2's CSP (Communicating Sequential Processes) concurrency model. CSP, originally formalized by Tony Hoare, models concurrent systems as independent processes that communicate exclusively through typed channels -- no shared mutable state, no locks, no data races.

Occam-2 brought CSP to hardware with constructs like `PAR`, `SEQ`, `ALT`, and channel-based communication. `stbass` brings these same formally-verified concurrency primitives to Python's async ecosystem, purpose-built for orchestrating agentic workflows.

## Quick Start

```python
from stbass import PAR, SEQ, Chan, Process

# Define typed channels
input_chan = Chan[str]("input")
output_chan = Chan[str]("output")

# Compose processes with PAR and SEQ
pipeline = SEQ(
    fetch_data(input_chan),
    PAR(
        analyze(input_chan, output_chan),
        summarize(input_chan, output_chan),
    ),
    report(output_chan),
)

result = await pipeline.run()
```

## Installation

```bash
pip install stbass
```

## License

MIT License - see [LICENSE](LICENSE) for details.

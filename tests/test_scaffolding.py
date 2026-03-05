import pytest


def test_package_importable():
    import stbass
    assert hasattr(stbass, '__version__')
    assert stbass.__version__ == "0.1.0"


def test_core_exports_exist():
    from stbass import (
        Process, ProcessResult, Failure,
        Chan, SEQ, PAR, ALT, PRI_ALT,
        Guard, TIMER, DEADLINE,
        PAR_FOR, SEQ_FOR,
        PLACED_PAR, Placement,
        FailurePolicy, FailureReport,
        Distributor, Collector, ChanArray,
    )
    # All imports should succeed without error


def test_all_modules_have_docstrings():
    import stbass.process
    import stbass.result
    import stbass.channel
    import stbass.seq
    import stbass.par
    import stbass.alt
    import stbass.timer
    import stbass.replicator
    import stbass.placement
    import stbass.failure
    import stbass.topology
    import stbass.mcp
    import stbass.observe
    modules = [
        stbass.process, stbass.result, stbass.channel,
        stbass.seq, stbass.par, stbass.alt, stbass.timer,
        stbass.replicator, stbass.placement, stbass.failure,
        stbass.topology, stbass.mcp, stbass.observe
    ]
    for mod in modules:
        assert mod.__doc__ is not None, f"{mod.__name__} missing docstring"


def test_license_file_exists():
    from pathlib import Path
    license_path = Path(__file__).parent.parent / "LICENSE"
    assert license_path.exists()
    content = license_path.read_text()
    assert "MIT" in content
    assert "Beautiful Majestic Dolphin" in content

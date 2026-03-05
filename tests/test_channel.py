import pytest
import asyncio
from pydantic import BaseModel
from stbass import Chan
from stbass.channel import (
    ChannelTypeError, ChannelTopologyError, ChannelClosedError,
    SequentialProtocol, VariantProtocol
)

class SearchResult(BaseModel):
    query: str
    score: float

class ErrorReport(BaseModel):
    code: int
    message: str

class TestChanBasic:
    @pytest.mark.asyncio
    async def test_send_recv_pydantic(self):
        ch = Chan(SearchResult, name="test_ch")
        async def writer():
            await ch.send(SearchResult(query="hello", score=0.9))
        async def reader():
            val = await ch.recv()
            assert isinstance(val, SearchResult)
            assert val.query == "hello"
            assert val.score == 0.9
        async with asyncio.TaskGroup() as tg:
            tg.create_task(writer())
            tg.create_task(reader())

    @pytest.mark.asyncio
    async def test_send_recv_primitive(self):
        ch = Chan(int, name="int_ch")
        async def writer():
            await ch.send(42)
        async def reader():
            val = await ch.recv()
            assert val == 42
        async with asyncio.TaskGroup() as tg:
            tg.create_task(writer())
            tg.create_task(reader())

    @pytest.mark.asyncio
    async def test_send_dict_coerced_to_pydantic(self):
        ch = Chan(SearchResult)
        async def writer():
            await ch.send({"query": "test", "score": 0.5})
        async def reader():
            val = await ch.recv()
            assert isinstance(val, SearchResult)
        async with asyncio.TaskGroup() as tg:
            tg.create_task(writer())
            tg.create_task(reader())

    @pytest.mark.asyncio
    async def test_rendezvous_semantics(self):
        """Writer blocks until reader is ready."""
        ch = Chan(str)
        order = []
        async def writer():
            order.append("writer_start")
            await ch.send("hello")
            order.append("writer_done")
        async def reader():
            await asyncio.sleep(0.05)  # delay reader
            order.append("reader_start")
            await ch.recv()
            order.append("reader_done")
        async with asyncio.TaskGroup() as tg:
            tg.create_task(writer())
            tg.create_task(reader())
        assert order.index("writer_done") > order.index("reader_start")

    def test_auto_name(self):
        ch = Chan(str)
        assert ch.name is not None
        assert len(ch.name) > 0

class TestChanTypeValidation:
    @pytest.mark.asyncio
    async def test_type_mismatch_pydantic(self):
        ch = Chan(SearchResult)
        with pytest.raises(ChannelTypeError) as exc_info:
            await asyncio.wait_for(ch.send("not a search result"), timeout=1.0)
        assert "SearchResult" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_type_mismatch_primitive(self):
        ch = Chan(int)
        with pytest.raises(ChannelTypeError):
            await asyncio.wait_for(ch.send("not an int"), timeout=1.0)

    @pytest.mark.asyncio
    async def test_correct_type_passes(self):
        ch = Chan(float)
        async def w():
            await ch.send(3.14)
        async def r():
            v = await ch.recv()
            assert v == 3.14
        async with asyncio.TaskGroup() as tg:
            tg.create_task(w())
            tg.create_task(r())

class TestChanTopology:
    def test_bind_one_writer(self):
        ch = Chan(str)
        ch.bind_writer("proc_1")
        assert ch.writer_attached is True

    def test_double_writer_raises(self):
        ch = Chan(str)
        ch.bind_writer("proc_1")
        with pytest.raises(ChannelTopologyError):
            ch.bind_writer("proc_2")

    def test_bind_one_reader(self):
        ch = Chan(str)
        ch.bind_reader("proc_1")
        assert ch.reader_attached is True

    def test_double_reader_raises(self):
        ch = Chan(str)
        ch.bind_reader("proc_1")
        with pytest.raises(ChannelTopologyError):
            ch.bind_reader("proc_2")

    def test_unbind_allows_rebind(self):
        ch = Chan(str)
        ch.bind_writer("proc_1")
        ch.unbind_writer()
        ch.bind_writer("proc_2")  # should not raise
        assert ch.writer_attached is True

class TestChanClose:
    @pytest.mark.asyncio
    async def test_send_after_close_raises(self):
        ch = Chan(str)
        ch.close()
        with pytest.raises(ChannelClosedError):
            await asyncio.wait_for(ch.send("hello"), timeout=1.0)

    @pytest.mark.asyncio
    async def test_recv_after_close_raises(self):
        ch = Chan(str)
        ch.close()
        with pytest.raises(ChannelClosedError):
            await asyncio.wait_for(ch.recv(), timeout=1.0)

class TestSequentialProtocol:
    @pytest.mark.asyncio
    async def test_correct_sequence(self):
        proto = SequentialProtocol(str, int, float)
        ch = Chan(proto)
        async def w():
            await ch.send("hello")
            await ch.send(42)
            await ch.send(3.14)
        async def r():
            assert await ch.recv() == "hello"
            assert await ch.recv() == 42
            assert await ch.recv() == 3.14
        async with asyncio.TaskGroup() as tg:
            tg.create_task(w())
            tg.create_task(r())

    @pytest.mark.asyncio
    async def test_wrong_sequence_raises(self):
        proto = SequentialProtocol(str, int)
        ch = Chan(proto)
        with pytest.raises(ChannelTypeError):
            await asyncio.wait_for(ch.send(42), timeout=1.0)  # expected str first

class TestVariantProtocol:
    @pytest.mark.asyncio
    async def test_accepts_any_variant(self):
        proto = VariantProtocol(SearchResult, ErrorReport)
        ch = Chan(proto)
        async def w():
            await ch.send(SearchResult(query="q", score=1.0))
            await ch.send(ErrorReport(code=404, message="not found"))
        async def r():
            v1 = await ch.recv()
            v2 = await ch.recv()
            assert isinstance(v1, SearchResult)
            assert isinstance(v2, ErrorReport)
        async with asyncio.TaskGroup() as tg:
            tg.create_task(w())
            tg.create_task(r())

    @pytest.mark.asyncio
    async def test_rejects_non_variant(self):
        proto = VariantProtocol(SearchResult, ErrorReport)
        ch = Chan(proto)
        with pytest.raises(ChannelTypeError):
            await asyncio.wait_for(ch.send("not a variant"), timeout=1.0)

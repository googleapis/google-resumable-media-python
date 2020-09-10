# Copyright 2017 Google Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import io


import mock
import pytest
from six.moves import http_client


from google.resumable_media import common
from google.async_resumable_media import _helpers
from google.async_resumable_media.requests import download as download_mod
from tests.unit.requests import test_download as sync_test

EXPECTED_TIMEOUT = 61


class TestDownload(object):
    @pytest.mark.asyncio
    async def test__write_to_stream_no_hash_check(self):
        stream = io.BytesIO()
        download = download_mod.Download(sync_test.EXAMPLE_URL, stream=stream)

        chunk1 = b"right now, "
        chunk2 = b"but a little later"
        response = _mock_response(chunks=[chunk1, chunk2], headers={})

        ret_val = await download._write_to_stream(response)
        assert ret_val is None

        assert stream.getvalue() == chunk1 + chunk2

    @pytest.mark.parametrize("checksum", ["md5", "crc32c", None])
    @pytest.mark.asyncio
    async def test__write_to_stream_with_hash_check_success(self, checksum):
        stream = io.BytesIO()
        download = download_mod.Download(
            sync_test.EXAMPLE_URL, stream=stream, checksum=checksum
        )
        chunk1 = b"first chunk, count starting at 0. "
        chunk2 = b"second chunk, or chunk 1, which is better? "
        chunk3 = b"ordinals and numerals and stuff."
        header_value = u"crc32c=qmNCyg==,md5=fPAJHnnoi/+NadyNxT2c2w=="
        headers = {_helpers._HASH_HEADER: header_value}
        response = _mock_response(chunks=[chunk1, chunk2, chunk3], headers=headers)

        ret_val = await download._write_to_stream(response)
        assert ret_val is None

        assert stream.getvalue() == chunk1 + chunk2 + chunk3

    @pytest.mark.parametrize("checksum", ["md5", "crc32c"])
    @pytest.mark.asyncio
    async def test__write_to_stream_with_hash_check_fail(self, checksum):
        stream = io.BytesIO()
        download = download_mod.Download(
            sync_test.EXAMPLE_URL, stream=stream, checksum=checksum
        )

        chunk1 = b"first chunk, count starting at 0. "
        chunk2 = b"second chunk, or chunk 1, which is better? "
        chunk3 = b"ordinals and numerals and stuff."
        bad_checksum = u"d3JvbmcgbiBtYWRlIHVwIQ=="
        header_value = u"crc32c={bad},md5={bad}".format(bad=bad_checksum)
        headers = {_helpers._HASH_HEADER: header_value}
        response = _mock_response(chunks=[chunk1, chunk2, chunk3], headers=headers)

        with pytest.raises(common.DataCorruption) as exc_info:
            await download._write_to_stream(response)

        assert not download.finished

        error = exc_info.value
        assert error.response is response
        assert len(error.args) == 1
        if checksum == u"md5":
            good_checksum = u"fPAJHnnoi/+NadyNxT2c2w=="
        else:
            good_checksum = u"qmNCyg=="
        msg = download_mod._CHECKSUM_MISMATCH.format(
            sync_test.EXAMPLE_URL,
            bad_checksum,
            good_checksum,
            checksum_type=checksum.upper(),
        )
        assert error.args[0] == msg

    @pytest.mark.asyncio
    async def test__write_to_stream_with_invalid_checksum_type(self):
        BAD_CHECKSUM_TYPE = "badsum"

        stream = io.BytesIO()
        download = download_mod.Download(
            sync_test.EXAMPLE_URL, stream=stream, checksum=BAD_CHECKSUM_TYPE
        )

        chunk1 = b"first chunk, count starting at 0. "
        chunk2 = b"second chunk, or chunk 1, which is better? "
        chunk3 = b"ordinals and numerals and stuff."
        bad_checksum = u"d3JvbmcgbiBtYWRlIHVwIQ=="
        header_value = u"crc32c={bad},md5={bad}".format(bad=bad_checksum)
        headers = {_helpers._HASH_HEADER: header_value}
        response = _mock_response(chunks=[chunk1, chunk2, chunk3], headers=headers)

        with pytest.raises(ValueError) as exc_info:
            await download._write_to_stream(response)

        assert not download.finished

        error = exc_info.value
        assert error.args[0] == "checksum must be ``'md5'``, ``'crc32c'`` or ``None``"

    @pytest.mark.asyncio
    async def _consume_helper(
        self,
        stream=None,
        end=65536,
        headers=None,
        chunks=(),
        response_headers=None,
        checksum="md5",
        timeout=None,
    ):
        download = download_mod.Download(
            sync_test.EXAMPLE_URL, stream=stream, end=end, headers=headers
        )
        transport = mock.AsyncMock(spec=["request"])
        mockResponse = _mock_response(chunks=chunks, headers=response_headers)
        transport.request = mock.AsyncMock(spec=["__call__"], return_value=mockResponse)

        assert not download.finished

        if timeout is not None:
            ret_val = await download.consume(transport, timeout=timeout)
        else:
            ret_val = await download.consume(transport)

        assert ret_val is transport.request.return_value

        called_kwargs = {
            u"data": None,
            u"headers": download._headers,
            u"timeout": EXPECTED_TIMEOUT if timeout is None else timeout,
        }

        if chunks:
            assert stream is not None
            called_kwargs[u"stream"] = True
        transport.request.assert_called_once_with(
            u"GET", sync_test.EXAMPLE_URL, **called_kwargs
        )

        range_bytes = u"bytes={:d}-{:d}".format(0, end)
        assert download._headers[u"range"] == range_bytes
        assert download.finished

        return transport

    @pytest.mark.asyncio
    async def test_consume(self):
        await self._consume_helper(timeout=14.7)

    @pytest.mark.parametrize("checksum", ["md5", "crc32c", None])
    @pytest.mark.asyncio
    async def test_consume_with_stream(self, checksum):
        stream = io.BytesIO()
        chunks = (b"up down ", b"charlie ", b"brown")
        # transport = await self._consume_helper(stream=stream, chunks=chunks, checksum=checksum)
        await self._consume_helper(stream=stream, chunks=chunks, checksum=checksum)

        assert stream.getvalue() == b"".join(chunks)

        # TODO(anirudhbaddepu) Add checking that the required methods were called.
        # Discrepancy between sync and async implementation on response stream.
        # response = transport.request.return_value

    @pytest.mark.parametrize("checksum", ["md5", "crc32c"])
    @pytest.mark.asyncio
    async def test_consume_with_stream_hash_check_success(self, checksum):
        stream = io.BytesIO()
        chunks = (b"up down ", b"charlie ", b"brown")
        header_value = u"crc32c=UNIQxg==,md5=JvS1wjMvfbCXgEGeaJJLDQ=="
        headers = {_helpers._HASH_HEADER: header_value}
        await self._consume_helper(
            stream=stream, chunks=chunks, response_headers=headers, checksum=checksum
        )

        assert stream.getvalue() == b"".join(chunks)

    @pytest.mark.parametrize("checksum", ["md5", "crc32c"])
    @pytest.mark.asyncio
    async def test_consume_with_stream_hash_check_fail(self, checksum):
        stream = io.BytesIO()
        download = download_mod.Download(
            sync_test.EXAMPLE_URL, stream=stream, checksum=checksum
        )

        chunks = (b"zero zero", b"niner tango")
        bad_checksum = u"anVzdCBub3QgdGhpcyAxLA=="
        header_value = u"crc32c={bad},md5={bad}".format(bad=bad_checksum)
        headers = {_helpers._HASH_HEADER: header_value}

        transport = mock.AsyncMock(spec=["request"])
        mockResponse = _mock_response(chunks=chunks, headers=headers)
        transport.request = mock.AsyncMock(spec=["__call__"], return_value=mockResponse)

        assert not download.finished
        with pytest.raises(common.DataCorruption) as exc_info:
            await download.consume(transport)

        assert stream.getvalue() == b"".join(chunks)
        assert download.finished
        assert download._headers == {}

        error = exc_info.value
        assert error.response is transport.request.return_value
        assert len(error.args) == 1
        if checksum == u"md5":
            good_checksum = u"1A/dxEpys717C6FH7FIWDw=="
        else:
            good_checksum = u"GvNZlg=="
        msg = download_mod._CHECKSUM_MISMATCH.format(
            sync_test.EXAMPLE_URL,
            bad_checksum,
            good_checksum,
            checksum_type=checksum.upper(),
        )
        assert error.args[0] == msg

        # Check mocks.
        transport.request.assert_called_once_with(
            u"GET",
            sync_test.EXAMPLE_URL,
            data=None,
            headers={},
            stream=True,
            timeout=EXPECTED_TIMEOUT,
        )

    @pytest.mark.asyncio
    async def test_consume_with_headers(self):
        headers = {}  # Empty headers
        end = 16383
        await self._consume_helper(end=end, headers=headers)
        range_bytes = u"bytes={:d}-{:d}".format(0, end)
        # Make sure the headers have been modified.
        assert headers == {u"range": range_bytes}


class TestRawDownload(object):
    @pytest.mark.asyncio
    async def test__write_to_stream_no_hash_check(self):
        stream = io.BytesIO()
        download = download_mod.RawDownload(sync_test.EXAMPLE_URL, stream=stream)

        chunk1 = b"right now, "
        chunk2 = b"but a little later"
        response = _mock_raw_response(chunks=[chunk1, chunk2], headers={})
        ret_val = await download._write_to_stream(response)
        assert ret_val is None

        assert stream.getvalue() == chunk1 + chunk2

    @pytest.mark.parametrize("checksum", ["md5", "crc32c"])
    @pytest.mark.asyncio
    async def test__write_to_stream_with_hash_check_success(self, checksum):
        stream = io.BytesIO()
        download = download_mod.RawDownload(
            sync_test.EXAMPLE_URL, stream=stream, checksum=checksum
        )

        chunk1 = b"first chunk, count starting at 0. "
        chunk2 = b"second chunk, or chunk 1, which is better? "
        chunk3 = b"ordinals and numerals and stuff."
        header_value = u"crc32c=qmNCyg==,md5=fPAJHnnoi/+NadyNxT2c2w=="
        headers = {_helpers._HASH_HEADER: header_value}
        response = _mock_raw_response(chunks=[chunk1, chunk2, chunk3], headers=headers)

        ret_val = await download._write_to_stream(response)
        assert ret_val is None

        assert stream.getvalue() == chunk1 + chunk2 + chunk3

    @pytest.mark.parametrize("checksum", ["md5", "crc32c"])
    @pytest.mark.asyncio
    async def test__write_to_stream_with_hash_check_fail(self, checksum):
        stream = io.BytesIO()
        download = download_mod.RawDownload(
            sync_test.EXAMPLE_URL, stream=stream, checksum=checksum
        )

        chunk1 = b"first chunk, count starting at 0. "
        chunk2 = b"second chunk, or chunk 1, which is better? "
        chunk3 = b"ordinals and numerals and stuff."
        bad_checksum = u"d3JvbmcgbiBtYWRlIHVwIQ=="
        header_value = u"crc32c={bad},md5={bad}".format(bad=bad_checksum)
        headers = {_helpers._HASH_HEADER: header_value}
        response = _mock_raw_response(chunks=[chunk1, chunk2, chunk3], headers=headers)

        with pytest.raises(common.DataCorruption) as exc_info:
            await download._write_to_stream(response)

        assert not download.finished

        error = exc_info.value
        assert error.response is response
        assert len(error.args) == 1
        if checksum == u"md5":
            good_checksum = u"fPAJHnnoi/+NadyNxT2c2w=="
        else:
            good_checksum = u"qmNCyg=="
        msg = download_mod._CHECKSUM_MISMATCH.format(
            sync_test.EXAMPLE_URL,
            bad_checksum,
            good_checksum,
            checksum_type=checksum.upper(),
        )
        assert error.args[0] == msg

    @pytest.mark.asyncio
    async def test__write_to_stream_with_invalid_checksum_type(self):
        BAD_CHECKSUM_TYPE = "badsum"

        stream = io.BytesIO()
        download = download_mod.RawDownload(
            sync_test.EXAMPLE_URL, stream=stream, checksum=BAD_CHECKSUM_TYPE
        )

        chunk1 = b"first chunk, count starting at 0. "
        chunk2 = b"second chunk, or chunk 1, which is better? "
        chunk3 = b"ordinals and numerals and stuff."
        bad_checksum = u"d3JvbmcgbiBtYWRlIHVwIQ=="
        header_value = u"crc32c={bad},md5={bad}".format(bad=bad_checksum)
        headers = {_helpers._HASH_HEADER: header_value}
        response = _mock_response(chunks=[chunk1, chunk2, chunk3], headers=headers)

        with pytest.raises(ValueError) as exc_info:
            await download._write_to_stream(response)

        assert not download.finished

        error = exc_info.value
        assert error.args[0] == "checksum must be ``'md5'``, ``'crc32c'`` or ``None``"

    async def _consume_helper(
        self,
        stream=None,
        end=65536,
        headers=None,
        chunks=(),
        response_headers=None,
        checksum=None,
        timeout=None,
    ):
        download = download_mod.RawDownload(
            sync_test.EXAMPLE_URL, stream=stream, end=end, headers=headers
        )

        transport = mock.AsyncMock(spec=["request"])
        mockResponse = _mock_raw_response(chunks=chunks, headers=response_headers)
        transport.request = mock.AsyncMock(spec=["__call__"], return_value=mockResponse)

        assert not download.finished
        ret_val = await download.consume(transport)
        assert ret_val is transport.request.return_value

        if chunks:
            assert stream is not None
        transport.request.assert_called_once_with(
            u"GET",
            sync_test.EXAMPLE_URL,
            data=None,
            headers=download._headers,
            timeout=EXPECTED_TIMEOUT,
        )

        range_bytes = u"bytes={:d}-{:d}".format(0, end)
        assert download._headers[u"range"] == range_bytes
        assert download.finished

        return transport

    @pytest.mark.asyncio
    async def test_consume(self):
        await self._consume_helper()

    @pytest.mark.asyncio
    async def test_consume_with_stream(self):
        stream = io.BytesIO()
        chunks = (b"up down ", b"charlie ", b"brown")
        # TODO(asyncio): verify we check what sync version checked.
        await self._consume_helper(stream=stream, chunks=chunks)

        assert stream.getvalue() == b"".join(chunks)

    @pytest.mark.asyncio
    async def test_consume_with_stream_hash_check_success(self):
        stream = io.BytesIO()
        chunks = (b"up down ", b"charlie ", b"brown")
        header_value = u"md5=JvS1wjMvfbCXgEGeaJJLDQ=="
        headers = {_helpers._HASH_HEADER: header_value}

        await self._consume_helper(
            stream=stream, chunks=chunks, response_headers=headers
        )

        assert stream.getvalue() == b"".join(chunks)

    @pytest.mark.parametrize("checksum", ["md5", "crc32c"])
    @pytest.mark.asyncio
    async def test_consume_with_stream_hash_check_fail(self, checksum):
        stream = io.BytesIO()
        download = download_mod.RawDownload(
            sync_test.EXAMPLE_URL, stream=stream, checksum=checksum
        )

        chunks = (b"zero zero", b"niner tango")
        bad_checksum = u"anVzdCBub3QgdGhpcyAxLA=="
        header_value = u"crc32c={bad},md5={bad}".format(bad=bad_checksum)
        headers = {_helpers._HASH_HEADER: header_value}
        transport = mock.AsyncMock(spec=["request"])
        mockResponse = _mock_raw_response(chunks=chunks, headers=headers)
        transport.request = mock.AsyncMock(spec=["__call__"], return_value=mockResponse)

        assert not download.finished
        with pytest.raises(common.DataCorruption) as exc_info:
            await download.consume(transport)

        assert stream.getvalue() == b"".join(chunks)
        assert download.finished
        assert download._headers == {}

        error = exc_info.value
        assert error.response is transport.request.return_value
        assert len(error.args) == 1
        if checksum == u"md5":
            good_checksum = u"1A/dxEpys717C6FH7FIWDw=="
        else:
            good_checksum = u"GvNZlg=="
        msg = download_mod._CHECKSUM_MISMATCH.format(
            sync_test.EXAMPLE_URL,
            bad_checksum,
            good_checksum,
            checksum_type=checksum.upper(),
        )
        assert error.args[0] == msg

        # Check mocks.
        transport.request.assert_called_once_with(
            u"GET",
            sync_test.EXAMPLE_URL,
            data=None,
            headers={},
            timeout=EXPECTED_TIMEOUT,
        )

    @pytest.mark.asyncio
    async def test_consume_with_headers(self):
        headers = {}  # Empty headers
        end = 16383
        await self._consume_helper(end=end, headers=headers)
        range_bytes = u"bytes={:d}-{:d}".format(0, end)
        # Make sure the headers have been modified.
        assert headers == {u"range": range_bytes}


class TestChunkedDownload(object):
    @staticmethod
    def _response_content_range(start_byte, end_byte, total_bytes):
        return u"bytes {:d}-{:d}/{:d}".format(start_byte, end_byte, total_bytes)

    def _response_headers(self, start_byte, end_byte, total_bytes):
        content_length = end_byte - start_byte + 1
        resp_range = self._response_content_range(start_byte, end_byte, total_bytes)
        return {
            u"content-length": u"{:d}".format(content_length),
            u"content-range": resp_range,
        }

    def _mock_response(
        self, start_byte, end_byte, total_bytes, content=None, status_code=None
    ):
        response_headers = self._response_headers(start_byte, end_byte, total_bytes)
        content_stream = mock.AsyncMock(spec=["__call__", "read"])
        content_stream.read = mock.AsyncMock(spec=["__call__"], return_value=content)
        return mock.AsyncMock(
            content=content_stream,
            _headers=response_headers,
            headers=response_headers,
            status=status_code,
            spec=["content", "headers", "status"],
        )

    @pytest.mark.asyncio
    async def test_consume_next_chunk_already_finished(self):
        download = download_mod.ChunkedDownload(sync_test.EXAMPLE_URL, 512, None)
        download._finished = True
        with pytest.raises(ValueError):
            await download.consume_next_chunk(None)

    def _mock_transport(self, start, chunk_size, total_bytes, content=b""):
        transport = mock.AsyncMock(spec=["request"])
        assert len(content) == chunk_size
        mockResponse = self._mock_response(
            start,
            start + chunk_size - 1,
            total_bytes,
            content=content,
            status_code=int(http_client.OK),
        )
        transport.request = mock.AsyncMock(spec=["__call__"], return_value=mockResponse)

        return transport

    @pytest.mark.asyncio
    async def test_consume_next_chunk(self):
        start = 1536
        stream = io.BytesIO()
        data = b"Just one chunk."
        chunk_size = len(data)
        download = download_mod.ChunkedDownload(
            sync_test.EXAMPLE_URL, chunk_size, stream, start=start
        )
        total_bytes = 16384
        transport = self._mock_transport(start, chunk_size, total_bytes, content=data)

        # Verify the internal state before consuming a chunk.
        assert not download.finished
        assert download.bytes_downloaded == 0
        assert download.total_bytes is None
        # Actually consume the chunk and check the output.
        ret_val = await download.consume_next_chunk(transport)
        assert ret_val is transport.request.return_value
        range_bytes = u"bytes={:d}-{:d}".format(start, start + chunk_size - 1)
        download_headers = {u"range": range_bytes}
        transport.request.assert_called_once_with(
            u"GET",
            sync_test.EXAMPLE_URL,
            data=None,
            headers=download_headers,
            timeout=EXPECTED_TIMEOUT,
        )
        assert stream.getvalue() == data
        # Go back and check the internal state after consuming the chunk.
        assert not download.finished
        assert download.bytes_downloaded == chunk_size
        assert download.total_bytes == total_bytes

    @pytest.mark.asyncio
    async def test_consume_next_chunk_with_custom_timeout(self):
        start = 1536
        stream = io.BytesIO()
        data = b"Just one chunk."
        chunk_size = len(data)
        download = download_mod.ChunkedDownload(
            sync_test.EXAMPLE_URL, chunk_size, stream, start=start
        )
        total_bytes = 16384
        transport = self._mock_transport(start, chunk_size, total_bytes, content=data)

        # Actually consume the chunk and check the output.
        await download.consume_next_chunk(transport, timeout=14.7)

        range_bytes = u"bytes={:d}-{:d}".format(start, start + chunk_size - 1)
        download_headers = {u"range": range_bytes}
        transport.request.assert_called_once_with(
            u"GET",
            sync_test.EXAMPLE_URL,
            data=None,
            headers=download_headers,
            timeout=14.7,
        )


class TestRawChunkedDownload(object):
    @staticmethod
    def _response_content_range(start_byte, end_byte, total_bytes):
        return u"bytes {:d}-{:d}/{:d}".format(start_byte, end_byte, total_bytes)

    def _response_headers(self, start_byte, end_byte, total_bytes):
        content_length = end_byte - start_byte + 1
        resp_range = self._response_content_range(start_byte, end_byte, total_bytes)
        return {
            u"content-length": u"{:d}".format(content_length),
            u"content-range": resp_range,
        }

    def _mock_response(
        self, start_byte, end_byte, total_bytes, content=None, status_code=None
    ):
        response_headers = self._response_headers(start_byte, end_byte, total_bytes)
        content_stream = mock.AsyncMock(spec=["__call__", "read"])
        content_stream.read = mock.AsyncMock(spec=["__call__"], return_value=content)
        return mock.AsyncMock(
            content=content_stream,
            _headers=response_headers,
            headers=response_headers,
            status=status_code,
            spec=["_headers", "content", "headers", "status"],
        )

    @pytest.mark.asyncio
    async def test_consume_next_chunk_already_finished(self):
        download = download_mod.RawChunkedDownload(sync_test.EXAMPLE_URL, 512, None)
        download._finished = True
        with pytest.raises(ValueError):
            await download.consume_next_chunk(None)

    def _mock_transport(self, start, chunk_size, total_bytes, content=b""):
        transport = mock.AsyncMock(spec=["request"])
        assert len(content) == chunk_size
        mockResponse = self._mock_response(
            start,
            start + chunk_size - 1,
            total_bytes,
            content=content,
            status_code=int(http_client.OK),
        )
        transport.request = mock.AsyncMock(spec=["__call__"], return_value=mockResponse)

        return transport

    @pytest.mark.asyncio
    async def test_consume_next_chunk(self):
        start = 1536
        stream = io.BytesIO()
        data = b"Just one chunk."
        chunk_size = len(data)
        download = download_mod.RawChunkedDownload(
            sync_test.EXAMPLE_URL, chunk_size, stream, start=start
        )
        total_bytes = 16384
        transport = self._mock_transport(start, chunk_size, total_bytes, content=data)

        # Verify the internal state before consuming a chunk.
        assert not download.finished
        assert download.bytes_downloaded == 0
        assert download.total_bytes is None
        # Actually consume the chunk and check the output.
        ret_val = await download.consume_next_chunk(transport)
        assert ret_val is transport.request.return_value
        range_bytes = u"bytes={:d}-{:d}".format(start, start + chunk_size - 1)
        download_headers = {u"range": range_bytes}
        transport.request.assert_called_once_with(
            u"GET",
            sync_test.EXAMPLE_URL,
            data=None,
            headers=download_headers,
            timeout=EXPECTED_TIMEOUT,
        )

        # Go back and check the internal state after consuming the chunk.
        assert not download.finished
        assert download.bytes_downloaded == chunk_size
        assert download.total_bytes == total_bytes

    @pytest.mark.asyncio
    async def test_consume_next_chunk_with_custom_timeout(self):
        start = 1536
        stream = io.BytesIO()
        data = b"Just one chunk."
        chunk_size = len(data)
        download = download_mod.RawChunkedDownload(
            sync_test.EXAMPLE_URL, chunk_size, stream, start=start
        )
        total_bytes = 16384
        transport = self._mock_transport(start, chunk_size, total_bytes, content=data)

        # Actually consume the chunk and check the output.
        await download.consume_next_chunk(transport, timeout=14.7)

        range_bytes = u"bytes={:d}-{:d}".format(start, start + chunk_size - 1)
        download_headers = {u"range": range_bytes}
        transport.request.assert_called_once_with(
            u"GET",
            sync_test.EXAMPLE_URL,
            data=None,
            headers=download_headers,
            timeout=14.7,
        )

        # Go back and check the internal state after consuming the chunk.
        assert not download.finished
        assert download.bytes_downloaded == chunk_size
        assert download.total_bytes == total_bytes


class Test__add_decoder(object):
    def test_non_gzipped(self):
        response_raw = mock.AsyncMock(headers={}, spec=["headers"])
        md5_hash = download_mod._add_decoder(response_raw, mock.sentinel.md5_hash)

        assert md5_hash is mock.sentinel.md5_hash

    def test_gzipped(self):
        headers = {u"content-encoding": u"gzip"}
        response_raw = mock.AsyncMock(headers=headers, spec=["headers", "_decoder"])
        md5_hash = download_mod._add_decoder(response_raw, mock.sentinel.md5_hash)

        assert md5_hash is not mock.sentinel.md5_hash

        assert md5_hash == _helpers._DoNothingHash
        assert isinstance(response_raw._decoder, download_mod._GzipDecoder)
        assert response_raw._decoder._checksum is mock.sentinel.md5_hash


class Test_GzipDecoder(object):
    def test_constructor(self):
        decoder = download_mod._GzipDecoder(mock.sentinel.md5_hash)
        assert decoder._checksum is mock.sentinel.md5_hash

    def test_decompress(self):
        md5_hash = mock.Mock(spec=["update"])
        decoder = download_mod._GzipDecoder(md5_hash)

        data = b"\x1f\x8b\x08\x08"
        result = decoder.decompress(data)

        assert result == b""
        md5_hash.update.assert_called_once_with(data)


class AsyncIter:
    def __init__(self, items):
        self.items = items

    async def __aiter__(self):
        for item in self.items:
            yield item


def _mock_response(status=http_client.OK, chunks=(), headers=None):
    if headers is None:
        headers = {}

    if chunks:
        chunklist = b"".join(chunks)
        stream_content = mock.AsyncMock(spec=["__call__", "read", "iter_chunked"])
        stream_content.read = mock.AsyncMock(spec=["__call__"], return_value=chunklist)
        stream_content.iter_chunked.return_value = AsyncIter(chunks)
        mock_raw = mock.AsyncMock(headers=headers, spec=["headers"])
        response = mock.AsyncMock(
            _headers=headers,
            headers=headers,
            status=int(status),
            raw=mock_raw,
            content=stream_content,
            spec=[
                u"__aenter__",
                u"__aexit__",
                u"_headers",
                u"iter_chunked",
                u"status",
                u"headers",
                u"raw",
                u"content",
            ],
        )
        # i.e. context manager returns ``self``.
        response.__aenter__.return_value = response
        response.__aexit__.return_value = None
        return response
    else:
        return mock.AsyncMock(
            _headers=headers,
            headers=headers,
            status=int(status),
            spec=["_headers", "status", "headers"],
        )


def _mock_raw_response(status_code=http_client.OK, chunks=(), headers=None):
    if headers is None:
        headers = {}
    chunklist = b"".join(chunks)
    stream_content = mock.AsyncMock(spec=["__call__", "read", "iter_chunked"])
    stream_content.read = mock.AsyncMock(spec=["__call__"], return_value=chunklist)
    stream_content.iter_chunked.return_value = AsyncIter(chunks)
    mock_raw = mock.AsyncMock(_headers=headers, headers=headers, spec=["__call__"])
    response = mock.AsyncMock(
        _headers=headers,
        headers=headers,
        status=int(status_code),
        raw=mock_raw,
        content=stream_content,
        spec=[
            u"__aenter__",
            u"__aexit__",
            u"_headers",
            u"iter_chunked",
            u"status",
            u"headers",
            u"raw",
            u"content",
        ],
    )
    # i.e. context manager returns ``self``.
    response.__aenter__.return_value = response
    response.__aexit__.return_value = None
    return response

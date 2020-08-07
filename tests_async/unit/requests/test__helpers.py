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

import mock
from six.moves import http_client
import pytest

from google.async_resumable_media.requests import _request_helpers as _helpers

# Change expected timeout to single numeral instead of tuple for asyncio compatibility.
EXPECTED_TIMEOUT = 61


class TestRequestsMixin(object):
    def test__get_status_code(self):
        status_code = int(http_client.OK)
        response = _make_response(status_code)
        assert status_code == _helpers.RequestsMixin._get_status_code(response)

    def test__get_headers(self):
        headers = {u"fruit": u"apple"}
        response = mock.Mock(headers=headers, _headers=headers, spec=["headers", "_headers"])
        assert headers == _helpers.RequestsMixin._get_headers(response)

    @pytest.mark.asyncio
    async def test__get_body(self):
        body = b"This is the payload."
        content_stream = mock.AsyncMock(spec=["__call__", "read"])
        content_stream.read = mock.AsyncMock(spec=["__call__"], return_value=body)
        response = mock.AsyncMock(
            content=content_stream,
            spec=["__call__", "content"],
        )
        temp = await _helpers.RequestsMixin._get_body(response)
        assert body == temp


@pytest.mark.asyncio
async def test_http_request():
    transport = _make_transport(http_client.OK)
    response = await transport.request()
    method = u"POST"
    url = u"http://test.invalid"
    data = mock.sentinel.data
    headers = {u"one": u"fish", u"blue": u"fish"}
    timeout = mock.sentinel.timeout
    ret_val = await _helpers.http_request(
        transport,
        method,
        url,
        data=data,
        headers=headers,
        extra1=b"work",
        extra2=125.5,
        timeout=timeout,
    )

    # TODO() check response value
    assert ret_val is response


@pytest.mark.asyncio
async def test_http_request_defaults():
    transport = _make_transport(http_client.OK)
    response = await transport.request()
    method = u"POST"
    url = u"http://test.invalid"

    ret_val = await _helpers.http_request(transport, method, url)
    assert ret_val is response


def _make_response(status_code):
    return mock.AsyncMock(status=status_code, spec=["status"])


def _make_transport(status_code):
    transport = mock.AsyncMock(spec=["request"])
    # responses = [_make_response(status_code) for status_code in status_codes]
    transport.request = mock.AsyncMock(spec=["__call__"], return_value=_make_response(status_code))
    return transport

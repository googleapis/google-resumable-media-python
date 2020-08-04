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
import asyncio
from six.moves import http_client
import pytest

from google.async_resumable_media.requests import _request_helpers as _helpers

#Change expected timeout to single numeral instead of tuple for asyncio compatibility.
EXPECTED_TIMEOUT = 61


class TestRequestsMixin(object):
    def test__get_status_code(self):
        status_code = int(http_client.OK)
        response = _make_response(status_code)
        assert status_code == _helpers.RequestsMixin._get_status_code(response)

    def test__get_headers(self):
        headers = {u"fruit": u"apple"}
        response = mock.Mock(headers=headers, spec=["headers"])
        assert headers == _helpers.RequestsMixin._get_headers(response)

    def test__get_body(self):
        body = b"This is the payload."
        response = mock.Mock(content=body, spec=["content"])
        assert body == _helpers.RequestsMixin._get_body(response)

'''
class TestRawRequestsMixin(object):
    def test__get_body_wo_content_consumed(self):
        body = b"This is the payload."
        raw = mock.AsyncMock(spec=["content"])
        raw.content.return_value = iter([body])
        response = mock.AsyncMock(content=raw, _content=False, spec=["content", "_content"])
        assert body == _helpers.RawRequestsMixin._get_body(response)


    def test__get_body_w_content_consumed(self):
        body = b"This is the payload."
        response = mock.Mock(_content=body, spec=["_content"])
        assert body == _helpers.RawRequestsMixin._get_body(response)
'''

@pytest.mark.asyncio
async def test_http_request():
    transport = _make_transport(http_client.OK)
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

    #breakpoint()

    transport.request.assert_called_once_with(
        method,
        url,
        data=data,
        headers=headers,
        extra1=b"work",
        extra2=125.5,
        timeout=timeout,
    )

@pytest.mark.asyncio
async def test_http_request_defaults():
    transport = _make_transport(http_client.OK)
    method = u"POST"
    url = u"http://test.invalid"
    #breakpoint()
    ret_val = await _helpers.http_request(transport, method, url)

    transport.request.assert_called_once_with(
        method, url, data=None, headers=None, timeout=EXPECTED_TIMEOUT
    )


def _make_response(status_code):
    return mock.AsyncMock(status=status_code, spec=["status"])


def _make_transport(status_code):
    transport = mock.AsyncMock(spec=["request"])
    transport.request = mock.AsyncMock(spec = ["__call__"], return_value = _make_response(status_code))
    return transport

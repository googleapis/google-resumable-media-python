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
import pytest

from google.resumable_media import _download
from google.resumable_media import exceptions


EXAMPLE_URL = (
    u'https://www.googleapis.com/download/storage/v1/b/'
    u'{BUCKET}/o/{OBJECT}?alt=media')


class TestDownloadBase(object):

    def test_constructor_defaults(self):
        download = _download.DownloadBase(EXAMPLE_URL)
        assert download.media_url == EXAMPLE_URL
        assert download.start is None
        assert download.end is None
        assert download._headers == {}
        assert not download._finished

    def test_constructor_explicit(self):
        start = 11
        end = 10001
        headers = {u'foof': u'barf'}
        download = _download.DownloadBase(
            EXAMPLE_URL, start=start, end=end, headers=headers)
        assert download.media_url == EXAMPLE_URL
        assert download.start == start
        assert download.end == end
        assert download._headers is headers
        assert not download._finished

    def test_finished_property(self):
        download = _download.DownloadBase(EXAMPLE_URL)
        # Default value of @property.
        assert not download.finished

        # Make sure we cannot set it on public @property.
        with pytest.raises(AttributeError):
            download.finished = False

        # Set it privately and then check the @property.
        download._finished = True
        assert download.finished


class Test__add_bytes_range(object):

    def test_do_nothing(self):
        headers = {}
        ret_val = _download.add_bytes_range(None, None, headers)
        assert ret_val is None
        assert headers == {}

    def test_both_vals(self):
        headers = {}
        ret_val = _download.add_bytes_range(17, 1997, headers)
        assert ret_val is None
        assert headers == {u'range': u'bytes=17-1997'}

    def test_end_only(self):
        headers = {}
        ret_val = _download.add_bytes_range(None, 909, headers)
        assert ret_val is None
        assert headers == {u'range': u'bytes=0-909'}

    def test_start_only(self):
        headers = {}
        ret_val = _download.add_bytes_range(3735928559, None, headers)
        assert ret_val is None
        assert headers == {u'range': u'bytes=3735928559-'}

    def test_start_as_offset(self):
        headers = {}
        ret_val = _download.add_bytes_range(-123454321, None, headers)
        assert ret_val is None
        assert headers == {u'range': u'bytes=-123454321'}


class Test_get_range_info(object):

    @staticmethod
    def _make_response(content_range):
        headers = {u'content-range': content_range}
        return mock.Mock(headers=headers, spec=[u'headers'])

    def test_success(self):
        content_range = u'Bytes 7-11/42'
        response = self._make_response(content_range)
        start_byte, end_byte, total_bytes = _download.get_range_info(
            response)
        assert start_byte == 7
        assert end_byte == 11
        assert total_bytes == 42

    def test_failure(self):
        content_range = u'nope x-6/y'
        response = self._make_response(content_range)
        with pytest.raises(exceptions.InvalidResponse) as exc_info:
            _download.get_range_info(response)

        error = exc_info.value
        assert error.response is response
        assert len(error.args) == 3
        assert error.args[1] == content_range
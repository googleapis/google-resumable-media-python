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

"""Support for downloading media from Google APIs."""

import base64
import hashlib
import logging

from google.resumable_media import _download
from google.resumable_media.common import DataCorruption
from google.resumable_media.requests import _helpers


_SINGLE_GET_CHUNK_SIZE = 8192


class Download(_helpers.RequestsMixin, _download.Download):
    """Helper to manage downloading a resource from a Google API.

    "Slices" of the resource can be retrieved by specifying a range
    with ``start`` and / or ``end``. However, in typical usage, neither
    ``start`` nor ``end`` is expected to be provided.

    Args:
        media_url (str): The URL containing the media to be downloaded.
        stream (IO[bytes]): A write-able stream (i.e. file-like object) that
            the downloaded resource can be written to.
        start (int): The first byte in a range to be downloaded. If not
            provided, but ``end`` is provided, will download from the
            beginning to ``end`` of the media.
        end (int): The last byte in a range to be downloaded. If not
            provided, but ``start`` is provided, will download from the
            ``start`` to the end of the media.
        headers (Optional[Mapping[str, str]]): Extra headers that should
            be sent with the request, e.g. headers for encrypted data.

    Attributes:
        media_url (str): The URL containing the media to be downloaded.
        start (Optional[int]): The first byte in a range to be downloaded.
        end (Optional[int]): The last byte in a range to be downloaded.
    """

    def _write_to_stream(self, response):
        """Write response body to a write-able stream.

        .. note:

            This method assumes that the ``_stream`` attribute is set on the
            current download.

        Args:
            response (~requests.Response): The HTTP response object.

        Raises:
            DataCorruption: If the download's checksum doesn't agree with
                server-computed checksum.
        """
        md5_hash = hashlib.md5()
        # TODO: Add support for validating CRC32C for composite objects. Note
        # that this is somewhat painful in Python 2 because most OS distros of
        # Python 2 don't include a compiled crcmod (and executing without a
        # compiled crcmod is very slow; and installing a compiled crcmod will
        # make getting google-cloud-python working well more difficult).
        expected_md5_hash = None
        if ('X-Goog-Hash' in response.headers
            and len(response.headers['X-Goog-Hash']) != 0):
            for checksum in response.headers['X-Goog-Hash'].split(','):
                name, value = checksum.split('=', 1)
                if name == 'md5':
                    expected_md5_hash = value
        if not expected_md5_hash:
            logging.getLogger().info(
                'No MD5 checksum was returned from the service while '
                'downloading %s (which happens for composite objects), so '
                'client-side content integrity checking is not being '
                'performed.' % self.media_url)
        with response:
            body_iter = response.iter_content(
                chunk_size=_SINGLE_GET_CHUNK_SIZE, decode_unicode=False)
            for chunk in body_iter:
                self._stream.write(chunk)
                md5_hash.update(chunk)
        actual_md5_hash = base64.encodestring(md5_hash.digest()).rstrip('\n')
        if expected_md5_hash and actual_md5_hash != expected_md5_hash:
              raise DataCorruption('Checksum mismatch while downloading %s: '
                                    'expected=%s, actual=%s' %
                                    (self.media_url, expected_md5_hash,
                                     actual_md5_hash))

    def consume(self, transport):
        """Consume the resource to be downloaded.

        If a ``stream`` is attached to this download, then the downloaded
        resource will be written to the stream.

        Args:
            transport (~requests.Session): A ``requests`` object which can
                make authenticated requests.

        Returns:
            ~requests.Response: The HTTP response returned by ``transport``.

        Raises:
            DataCorruption: If the download's checksum doesn't agree with
                server-computed checksum.
            ValueError: If the current :class:`Download` has already
                finished.
        """
        method, url, payload, headers = self._prepare_request()
        # NOTE: We assume "payload is None" but pass it along anyway.
        request_kwargs = {
            u'data': payload,
            u'headers': headers,
            u'retry_strategy': self._retry_strategy,
        }
        if self._stream is not None:
            request_kwargs[u'stream'] = True

        result = _helpers.http_request(
            transport, method, url, **request_kwargs)

        self._process_response(result)

        if self._stream is not None:
            self._write_to_stream(result)

        return result


class ChunkedDownload(_helpers.RequestsMixin, _download.ChunkedDownload):
    """Download a resource in chunks from a Google API.

    Args:
        media_url (str): The URL containing the media to be downloaded.
        chunk_size (int): The number of bytes to be retrieved in each
            request.
        stream (IO[bytes]): A write-able stream (i.e. file-like object) that
            will be used to concatenate chunks of the resource as they are
            downloaded.
        start (int): The first byte in a range to be downloaded. If not
            provided, defaults to ``0``.
        end (int): The last byte in a range to be downloaded. If not
            provided, will download to the end of the media.
        headers (Optional[Mapping[str, str]]): Extra headers that should
            be sent with each request, e.g. headers for data encryption
            key headers.

    Attributes:
        media_url (str): The URL containing the media to be downloaded.
        start (Optional[int]): The first byte in a range to be downloaded.
        end (Optional[int]): The last byte in a range to be downloaded.
        chunk_size (int): The number of bytes to be retrieved in each request.

    Raises:
        ValueError: If ``start`` is negative.
    """

    def consume_next_chunk(self, transport):
        """Consume the next chunk of the resource to be downloaded.

        Args:
            transport (~requests.Session): A ``requests`` object which can
                make authenticated requests.

        Returns:
            ~requests.Response: The HTTP response returned by ``transport``.

        Raises:
            ValueError: If the current download has finished.
        """
        method, url, payload, headers = self._prepare_request()
        # NOTE: We assume "payload is None" but pass it along anyway.
        result = _helpers.http_request(
            transport, method, url, data=payload, headers=headers,
            retry_strategy=self._retry_strategy)
        self._process_response(result)
        return result

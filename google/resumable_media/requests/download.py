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

import functools
import time
import urllib3.response

from google.resumable_media import _download
from google.resumable_media import common
from google.resumable_media import _helpers
from google.resumable_media.requests import _request_helpers


_CHECKSUM_MISMATCH = u"""\
Checksum mismatch while downloading:

  {}

The X-Goog-Hash header indicated an {checksum_type} checksum of:

  {}

but the actual {checksum_type} checksum of the downloaded contents was:

  {}
"""


class Download(_request_helpers.RequestsMixin, _download.Download):
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
        checksum Optional([str]): The type of checksum to compute to verify
            the integrity of the object. The response headers must contain
            a checksum of the requested type. If the headers lack an
            appropriate checksum (for instance in the case of transcoded or
            ranged downloads where the remote service does not know the
            correct checksum) an INFO-level log will be emitted. Supported
            values are "md5", "crc32c" and None. The default is "md5".

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
            ~google.resumable_media.common.DataCorruption: If the download's
                checksum doesn't agree with server-computed checksum.
        """

        # `_get_expected_checksum()` may return None even if a checksum was
        # requested, in which case it will emit an info log _MISSING_CHECKSUM.
        # If an invalid checksum type is specified, this will raise ValueError.
        expected_checksum, checksum_object = _helpers._get_expected_checksum(
            response, self._get_headers, self.media_url, checksum_type=self.checksum
        )

        with response:
            # NOTE: In order to handle compressed streams gracefully, we try
            # to insert our checksum object into the decompression stream. If
            # the stream is indeed compressed, this will delegate the checksum
            # object to the decoder and return a _DoNothingHash here.
            local_checksum_object = _add_decoder(response.raw, checksum_object)
            body_iter = response.iter_content(
                chunk_size=_request_helpers._SINGLE_GET_CHUNK_SIZE, decode_unicode=False
            )
            for chunk in body_iter:
                self._stream.write(chunk)
                local_checksum_object.update(chunk)

        if expected_checksum is None:
            return
        else:
            actual_checksum = _helpers.prepare_checksum_digest(checksum_object.digest())
            if actual_checksum != expected_checksum:
                msg = _CHECKSUM_MISMATCH.format(
                    self.media_url,
                    expected_checksum,
                    actual_checksum,
                    checksum_type=self.checksum.upper(),
                )
                raise common.DataCorruption(response, msg)

    def original_consume(
        self,
        transport,
        timeout=(
            _request_helpers._DEFAULT_CONNECT_TIMEOUT,
            _request_helpers._DEFAULT_READ_TIMEOUT,
        ),
    ):
        """Consume the resource to be downloaded.

        If a ``stream`` is attached to this download, then the downloaded
        resource will be written to the stream.

        Args:
            transport (~requests.Session): A ``requests`` object which can
                make authenticated requests.
            timeout (Optional[Union[float, Tuple[float, float]]]):
                The number of seconds to wait for the server response.
                Depending on the retry strategy, a request may be repeated
                several times using the same timeout each time.

                Can also be passed as a tuple (connect_timeout, read_timeout).
                See :meth:`requests.Session.request` documentation for details.

        Returns:
            ~requests.Response: The HTTP response returned by ``transport``.

        Raises:
            ~google.resumable_media.common.DataCorruption: If the download's
                checksum doesn't agree with server-computed checksum.
            ValueError: If the current :class:`Download` has already
                finished.
        """
        method, url, payload, headers = self._prepare_request()
        # NOTE: We assume "payload is None" but pass it along anyway.
        request_kwargs = {
            u"data": payload,
            u"headers": headers,
            u"retry_strategy": self._retry_strategy,
            u"timeout": timeout,
        }
        if self._stream is not None:
            request_kwargs[u"stream"] = True

        result = _request_helpers.http_request(transport, method, url, **request_kwargs)

        self._process_response(result)

        if self._stream is not None:
            self._write_to_stream(result)

        return result

    def consume(
        self,
        transport,
        timeout=(
            _request_helpers._DEFAULT_CONNECT_TIMEOUT,
            _request_helpers._DEFAULT_READ_TIMEOUT,
        ),
    ):
        total_sleep = 0.0
        num_retries = 0
        # base_wait will be multiplied by the multiplier on the first retry.
        base_wait = (
            float(self._retry_strategy.initial_delay) / self._retry_strategy.multiplier
        )

        method, url, payload, headers = self._prepare_request()
        # NOTE: We assume "payload is None" but pass it along anyway.
        request_kwargs = {
            u"data": payload,
            u"headers": headers,
            u"timeout": timeout,
        }
        if self._stream is not None:
            request_kwargs[u"stream"] = True

        func = functools.partial(transport.request, method, url, **request_kwargs)

        # Set the retriable_exception_type if possible. We expect requests to be
        # present here and the transport to be using requests.exceptions errors,
        # but due to loose coupling with the transport layer we can't guarantee it.
        try:
            connection_error_exceptions = _helpers._get_connection_error_classes()
        except ImportError:
            # We don't know the correct classes to use to catch connection errors,
            # so an empty tuple here communicates "catch no exceptions".
            connection_error_exceptions = ()

        while True:  # return on success or when retries exhausted.
            error = None
            try:
                response = func()
                self._process_response(response)
                if self._stream is not None:
                    self._write_to_stream(response)
            except connection_error_exceptions as e:
                error = e
            else:
                if self._get_status_code(response) not in common.RETRYABLE:
                    return response

            if not self._retry_strategy.retry_allowed(total_sleep, num_retries):
                # Retries are exhausted and no acceptable response was received. Raise the
                # retriable_error or return the unacceptable response.
                if error:
                    raise error

                return response

            base_wait, wait_time = _helpers.calculate_retry_wait(
                base_wait,
                self._retry_strategy.max_sleep,
                self._retry_strategy.multiplier,
            )

            num_retries += 1
            total_sleep += wait_time
            time.sleep(wait_time)


class RawDownload(_request_helpers.RawRequestsMixin, _download.Download):
    """Helper to manage downloading a raw resource from a Google API.

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
        checksum Optional([str]): The type of checksum to compute to verify
            the integrity of the object. The response headers must contain
            a checksum of the requested type. If the headers lack an
            appropriate checksum (for instance in the case of transcoded or
            ranged downloads where the remote service does not know the
            correct checksum) an INFO-level log will be emitted. Supported
            values are "md5", "crc32c" and None. The default is "md5".
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
            ~google.resumable_media.common.DataCorruption: If the download's
                checksum doesn't agree with server-computed checksum.
        """

        # `_get_expected_checksum()` may return None even if a checksum was
        # requested, in which case it will emit an info log _MISSING_CHECKSUM.
        # If an invalid checksum type is specified, this will raise ValueError.
        expected_checksum, checksum_object = _helpers._get_expected_checksum(
            response, self._get_headers, self.media_url, checksum_type=self.checksum
        )

        with response:
            body_iter = response.raw.stream(
                _request_helpers._SINGLE_GET_CHUNK_SIZE, decode_content=False
            )
            for chunk in body_iter:
                self._stream.write(chunk)
                checksum_object.update(chunk)
            response._content_consumed = True

        if expected_checksum is None:
            return
        else:
            actual_checksum = _helpers.prepare_checksum_digest(checksum_object.digest())

            if actual_checksum != expected_checksum:
                msg = _CHECKSUM_MISMATCH.format(
                    self.media_url,
                    expected_checksum,
                    actual_checksum,
                    checksum_type=self.checksum.upper(),
                )
                raise common.DataCorruption(response, msg)

    def consume(
        self,
        transport,
        timeout=(
            _request_helpers._DEFAULT_CONNECT_TIMEOUT,
            _request_helpers._DEFAULT_READ_TIMEOUT,
        ),
    ):
        """Consume the resource to be downloaded.

        If a ``stream`` is attached to this download, then the downloaded
        resource will be written to the stream.

        Args:
            transport (~requests.Session): A ``requests`` object which can
                make authenticated requests.
            timeout (Optional[Union[float, Tuple[float, float]]]):
                The number of seconds to wait for the server response.
                Depending on the retry strategy, a request may be repeated
                several times using the same timeout each time.

                Can also be passed as a tuple (connect_timeout, read_timeout).
                See :meth:`requests.Session.request` documentation for details.

        Returns:
            ~requests.Response: The HTTP response returned by ``transport``.

        Raises:
            ~google.resumable_media.common.DataCorruption: If the download's
                checksum doesn't agree with server-computed checksum.
            ValueError: If the current :class:`Download` has already
                finished.
        """
        method, url, payload, headers = self._prepare_request()
        # NOTE: We assume "payload is None" but pass it along anyway.
        result = _request_helpers.http_request(
            transport,
            method,
            url,
            data=payload,
            headers=headers,
            retry_strategy=self._retry_strategy,
            stream=True,
            timeout=timeout,
        )

        self._process_response(result)

        if self._stream is not None:
            self._write_to_stream(result)

        return result


class ChunkedDownload(_request_helpers.RequestsMixin, _download.ChunkedDownload):
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

    def consume_next_chunk(
        self,
        transport,
        timeout=(
            _request_helpers._DEFAULT_CONNECT_TIMEOUT,
            _request_helpers._DEFAULT_READ_TIMEOUT,
        ),
    ):
        """Consume the next chunk of the resource to be downloaded.

        Args:
            transport (~requests.Session): A ``requests`` object which can
                make authenticated requests.
            timeout (Optional[Union[float, Tuple[float, float]]]):
                The number of seconds to wait for the server response.
                Depending on the retry strategy, a request may be repeated
                several times using the same timeout each time.

                Can also be passed as a tuple (connect_timeout, read_timeout).
                See :meth:`requests.Session.request` documentation for details.

        Returns:
            ~requests.Response: The HTTP response returned by ``transport``.

        Raises:
            ValueError: If the current download has finished.
        """
        method, url, payload, headers = self._prepare_request()
        # NOTE: We assume "payload is None" but pass it along anyway.
        result = _request_helpers.http_request(
            transport,
            method,
            url,
            data=payload,
            headers=headers,
            retry_strategy=self._retry_strategy,
            timeout=timeout,
        )
        self._process_response(result)
        return result


class RawChunkedDownload(_request_helpers.RawRequestsMixin, _download.ChunkedDownload):
    """Download a raw resource in chunks from a Google API.

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

    def consume_next_chunk(
        self,
        transport,
        timeout=(
            _request_helpers._DEFAULT_CONNECT_TIMEOUT,
            _request_helpers._DEFAULT_READ_TIMEOUT,
        ),
    ):
        """Consume the next chunk of the resource to be downloaded.

        Args:
            transport (~requests.Session): A ``requests`` object which can
                make authenticated requests.
            timeout (Optional[Union[float, Tuple[float, float]]]):
                The number of seconds to wait for the server response.
                Depending on the retry strategy, a request may be repeated
                several times using the same timeout each time.

                Can also be passed as a tuple (connect_timeout, read_timeout).
                See :meth:`requests.Session.request` documentation for details.

        Returns:
            ~requests.Response: The HTTP response returned by ``transport``.

        Raises:
            ValueError: If the current download has finished.
        """
        method, url, payload, headers = self._prepare_request()
        # NOTE: We assume "payload is None" but pass it along anyway.
        result = _request_helpers.http_request(
            transport,
            method,
            url,
            data=payload,
            headers=headers,
            stream=True,
            retry_strategy=self._retry_strategy,
            timeout=timeout,
        )
        self._process_response(result)
        return result


def _add_decoder(response_raw, checksum):
    """Patch the ``_decoder`` on a ``urllib3`` response.

    This is so that we can intercept the compressed bytes before they are
    decoded.

    Only patches if the content encoding is ``gzip``.

    Args:
        response_raw (urllib3.response.HTTPResponse): The raw response for
            an HTTP request.
        checksum (object):
            A checksum which will be updated with compressed bytes.

    Returns:
        object: Either the original ``checksum`` if ``_decoder`` is not
        patched, or a ``_DoNothingHash`` if the decoder is patched, since the
        caller will no longer need to hash to decoded bytes.
    """
    encoding = response_raw.headers.get(u"content-encoding", u"").lower()
    if encoding != u"gzip":
        return checksum

    response_raw._decoder = _GzipDecoder(checksum)
    return _helpers._DoNothingHash()


class _GzipDecoder(urllib3.response.GzipDecoder):
    """Custom subclass of ``urllib3`` decoder for ``gzip``-ed bytes.

    Allows a checksum function to see the compressed bytes before they are
    decoded. This way the checksum of the compressed value can be computed.

    Args:
        checksum (object):
            A checksum which will be updated with compressed bytes.
    """

    def __init__(self, checksum):
        super(_GzipDecoder, self).__init__()
        self._checksum = checksum

    def decompress(self, data):
        """Decompress the bytes.

        Args:
            data (bytes): The compressed bytes to be decompressed.

        Returns:
            bytes: The decompressed bytes from ``data``.
        """
        self._checksum.update(data)
        return super(_GzipDecoder, self).decompress(data)

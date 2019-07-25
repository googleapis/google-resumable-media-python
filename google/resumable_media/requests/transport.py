# Copyright 2019 Google Inc.
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

from google.auth import transport
from google.auth.transport.requests import AuthorizedSession


class TimeoutAuthorizedSession(AuthorizedSession):
    """A Requests Session class with credentials.

    This class is used to perform requests to API endpoints that require
    authorization::

        from google.resumable_media.requests.transport import
                                                      TimeoutAuthorizedSession

        authed_session = TimeoutAuthorizedSession(credentials)

        response = authed_session.request(
            'GET', 'https://www.googleapis.com/storage/v1/b')

    The underlying :meth:`request` implementation handles adding the
    credentials' headers to the request and refreshing credentials as needed.

    Args:
        credentials (google.auth.credentials.Credentials): The credentials to
            add to the request.
        refresh_status_codes (Sequence[int]): Which HTTP status codes indicate
            that credentials should be refreshed and the request should be
            retried.
        max_refresh_attempts (int): The maximum number of times to attempt to
            refresh the credentials and retry the request.
        refresh_timeout (Optional[int]): The timeout value in seconds for
            credential refresh HTTP requests.
        auth_request (google.auth.transport.requests.Request):
            (Optional) An instance of
            :class:`~google.auth.transport.requests.Request` used when
            refreshing credentials. If not passed,
            an instance of :class:`~google.auth.transport.requests.Request`
            is created.
        timeout(int) : The timeout value in second for request.

    """

    def __init__(self, credentials,
                 refresh_status_codes=transport.DEFAULT_REFRESH_STATUS_CODES,
                 max_refresh_attempts=transport.DEFAULT_MAX_REFRESH_ATTEMPTS,
                 refresh_timeout=None,
                 auth_request=None, **kwargs):
        self.timeout = None
        if "timeout" in kwargs:
            self.timeout = kwargs.pop("timeout")
        super(TimeoutAuthorizedSession, self).__init__(
            credentials,
            refresh_status_codes=refresh_status_codes,
            max_refresh_attempts=max_refresh_attempts,
            refresh_timeout=refresh_timeout,
            auth_request=auth_request)

    def request(self, method, url, data=None, headers=None, **kwargs):
        """
        :param method: request method 'GET', 'POST' etc.
        :param url: request url
        :param data: request data
        :param headers: request header
        :param kwargs: extra data
        :return: response of timeout set request.
        """
        if "timeout" not in kwargs:
            kwargs['timeout'] = self.timeout
        return super(TimeoutAuthorizedSession, self).request(method=method,
                                                             url=url,
                                                             data=data,
                                                             headers=headers,
                                                             **kwargs)

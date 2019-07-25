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

import mock
import requests
from google.resumable_media.requests.transport import TimeoutAuthorizedSession


def make_response(status=200, data=None, *args, **kwargs):
    response = requests.Response()
    response.status_code = status
    response._content = data
    response.timeout = kwargs['timeout']
    return response


class TestTimeoutSession(object):
    TEST_URL = 'http://example.com/'

    def test_request_timeout(self):
        auth_session = TimeoutAuthorizedSession(mock.sentinel.credentials,
                                                auth_request=None, timeout=50)
        assert auth_session.timeout == 50
        with mock.patch('google.auth.transport.requests.AuthorizedSession.'
                        'request', new=make_response):
            response = auth_session.request(method='GET',
                                            url=self.TEST_URL)
            assert response.timeout == 50

    def test_default_request_timeout(self):
        auth_session = TimeoutAuthorizedSession(mock.sentinel.credentials,
                                                auth_request=None)
        assert auth_session.timeout is None
        with mock.patch('google.auth.transport.requests.AuthorizedSession.'
                        'request', new=make_response):
            response = auth_session.request(method='GET',
                                            url=self.TEST_URL)
            assert response.timeout is None
            response2 = auth_session.request(method='GET', url=self.TEST_URL,
                                             timeout=10)
            assert response2.timeout == 10

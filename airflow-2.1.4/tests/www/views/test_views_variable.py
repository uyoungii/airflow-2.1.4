#
# Licensed to the Apache Software Foundation (ASF) under one
# or more contributor license agreements.  See the NOTICE file
# distributed with this work for additional information
# regarding copyright ownership.  The ASF licenses this file
# to you under the Apache License, Version 2.0 (the
# "License"); you may not use this file except in compliance
# with the License.  You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing,
# software distributed under the License is distributed on an
# "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
# KIND, either express or implied.  See the License for the
# specific language governing permissions and limitations
# under the License.
import io
from unittest import mock

import pytest

from airflow.models import Variable
from airflow.security import permissions
from airflow.utils.session import create_session
from tests.test_utils.api_connexion_utils import create_user
from tests.test_utils.www import check_content_in_response, check_content_not_in_response, client_with_login

VARIABLE = {
    'key': 'test_key',
    'val': 'text_val',
    'description': 'test_description',
    'is_encrypted': True,
}


@pytest.fixture(autouse=True)
def clear_variables():
    with create_session() as session:
        session.query(Variable).delete()


@pytest.fixture(scope="module")
def user_variable_reader(app):
    """Create User that can only read variables"""
    return create_user(
        app,
        username="user_variable_reader",
        role_name="role_variable_reader",
        permissions=[(permissions.ACTION_CAN_READ, permissions.RESOURCE_VARIABLE)],
    )


@pytest.fixture()
def client_variable_reader(app, user_variable_reader):
    """Client for User that can only access the first DAG from TEST_FILTER_DAG_IDS"""
    return client_with_login(
        app,
        username="user_variable_reader",
        password="user_variable_reader",
    )


def test_can_handle_error_on_decrypt(session, admin_client):
    # create valid variable
    admin_client.post('/variable/add', data=VARIABLE, follow_redirects=True)

    # update the variable with a wrong value, given that is encrypted
    session.query(Variable).filter(Variable.key == VARIABLE['key']).update(
        {'val': 'failed_value_not_encrypted'},
        synchronize_session=False,
    )
    session.commit()

    # retrieve Variables page, should not fail and contain the Invalid
    # label for the variable
    resp = admin_client.get('/variable/list', follow_redirects=True)
    check_content_in_response(
        '<span class="label label-danger">Invalid</span>',
        resp,
    )


def test_xss_prevention(admin_client):
    xss = "/variable/list/<img%20src=''%20onerror='alert(1);'>"
    resp = admin_client.get(xss, follow_redirects=True)
    check_content_not_in_response("<img src='' onerror='alert(1);'>", resp, resp_code=404)


def test_import_variables_no_file(admin_client):
    resp = admin_client.post('/variable/varimport', follow_redirects=True)
    check_content_in_response('Missing file or syntax error.', resp)


def test_import_variables_failed(session, admin_client):
    content = '{"str_key": "str_value"}'

    with mock.patch('airflow.models.Variable.set') as set_mock:
        set_mock.side_effect = UnicodeEncodeError
        assert session.query(Variable).count() == 0

        bytes_content = io.BytesIO(bytes(content, encoding='utf-8'))

        resp = admin_client.post(
            '/variable/varimport', data={'file': (bytes_content, 'test.json')}, follow_redirects=True
        )
        check_content_in_response('1 variable(s) failed to be updated.', resp)


def test_import_variables_success(session, admin_client):
    assert session.query(Variable).count() == 0

    content = '{"str_key": "str_value", "int_key": 60, "list_key": [1, 2], "dict_key": {"k_a": 2, "k_b": 3}}'
    bytes_content = io.BytesIO(bytes(content, encoding='utf-8'))

    resp = admin_client.post(
        '/variable/varimport', data={'file': (bytes_content, 'test.json')}, follow_redirects=True
    )
    check_content_in_response('4 variable(s) successfully updated.', resp)


def test_import_variables_anon(session, app):
    assert session.query(Variable).count() == 0

    content = '{"str_key": "str_value}'
    bytes_content = io.BytesIO(bytes(content, encoding='utf-8'))

    resp = app.test_client().post(
        '/variable/varimport', data={'file': (bytes_content, 'test.json')}, follow_redirects=True
    )
    check_content_not_in_response('variable(s) successfully updated.', resp)
    check_content_in_response('Sign In', resp)


def test_import_variables_form_shown(app, admin_client):
    resp = admin_client.get('/variable/list/')
    check_content_in_response('Import Variables', resp)


def test_import_variables_form_hidden(app, client_variable_reader):
    resp = client_variable_reader.get('/variable/list/')
    check_content_not_in_response('Import Variables', resp)


def test_description_retrieval(session, admin_client):
    # create valid variable
    admin_client.post('/variable/add', data=VARIABLE, follow_redirects=True)

    row = session.query(Variable.key, Variable.description).first()
    assert row.key == 'test_key' and row.description == 'test_description'

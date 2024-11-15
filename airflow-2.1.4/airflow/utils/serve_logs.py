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

"""Serve logs process"""

# pylint: skip-file

import os
import time

from flask import Flask, abort, request, send_from_directory
from itsdangerous import TimedJSONWebSignatureSerializer
from setproctitle import setproctitle

from airflow.configuration import conf


def flask_app():
    flask_app = Flask(__name__)
    max_request_age = conf.getint('webserver', 'log_request_clock_grace', fallback=30)
    log_directory = os.path.expanduser(conf.get('logging', 'BASE_LOG_FOLDER'))

    signer = TimedJSONWebSignatureSerializer(
        secret_key=conf.get('webserver', 'secret_key'),
        algorithm_name='HS512',
        expires_in=max_request_age,
        # This isn't really a "salt", more of a signing context
        salt='task-instance-logs',
    )

    # Prevent direct access to the logs port
    @flask_app.before_request
    def validate_pre_signed_url():
        try:
            auth = request.headers['Authorization']

            # We don't actually care about the payload, just that the signature
            # was valid and the `exp` claim is correct
            filename, headers = signer.loads(auth, return_header=True)

            issued_at = int(headers['iat'])
            expires_at = int(headers['exp'])
        except Exception:
            abort(403)

        if filename != request.view_args['filename']:
            abort(403)

        # Validate the `iat` and `exp` are within `max_request_age` of now.
        now = int(time.time())
        if abs(now - issued_at) > max_request_age:
            abort(403)
        if abs(now - expires_at) > max_request_age:
            abort(403)
        if issued_at > expires_at or expires_at - issued_at > max_request_age:
            abort(403)

    @flask_app.route('/log/<path:filename>')
    def serve_logs_view(filename):
        return send_from_directory(log_directory, filename, mimetype="application/json", as_attachment=False)

    return flask_app


def serve_logs():
    """Serves logs generated by Worker"""
    setproctitle("airflow serve-logs")
    app = flask_app()

    worker_log_server_port = conf.getint('celery', 'WORKER_LOG_SERVER_PORT')
    app.run(host='0.0.0.0', port=worker_log_server_port)

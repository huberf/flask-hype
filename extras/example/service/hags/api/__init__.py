__all__ = [
    'init',
    'app',
    'exc',
    'User',
    'Anonymous',
    'Password',
    'Prisoner',
    'Stats',
]

import logging
import sys

import flask
from flask.ext import hype
import pilo
import werkzeug.utils

from hags import models, mimes, config


logger = logging.getLogger(__name__)


def init(config):
    pass


class RequestAdminMixin(flask.Request):

    @werkzeug.utils.cached_property
    def admin(self):
        return self.headers.get(config.API_HEADERS['admin']) == config.API_ADMIN


class RequestUserMixin(flask.Request):

    @werkzeug.utils.cached_property
    def user(self):
        if not self.authorization:
            return Anonymous()
        if isinstance(self.authorization.username, str):
            username = self.authorization.username.decode('utf-8')
        if isinstance(self.authorization.password, str):
            password = self.authorization.password.decode('utf-8')
        user = User.authenticate(username, password)
        if not user.enabled:
            return Anonymous()
        return user

    @property
    def authorize(self):
        return self.user.authorize


class RequestMIMEMixin(object):

    def accept_match(self, *mime_types):
        mime_type = self.accept_mimetypes.best_match(
            mime_types, default=mime_types[0]
        )
        if not mime_type:
            raise exc.BadRequest(
                'No matching accept mime-type'
            )

    def accept_encoder(self):
        self.accept_match(mimes.json.accept_type)
        return mimes.json.accept_type, mimes.json.encode

    def content_source(self):
        if self.mimetype == mimes.json.content_type:
            charset = self.mimetype_params.get('charset') or None
            return mimes.json.source(
                text=self.get_data(), encoding=charset
            )
        raise exc.BadRequest(
            'Unsupported content mime-type "{}"'.format(self.mimetype)
        )


class Request(
          RequestUserMixin,
          RequestMIMEMixin,
          RequestAdminMixin,
          flask.Request,
      ):

    pass


RequestForm = hype.RequestForm

request = flask.request

Response = flask.Response


class Application(flask.Flask):

    request_class = Request

    debug = True

    def __init__(self, *args, **kwargs):
        super(Application, self).__init__('hags.api', *args, **kwargs)
        self.url_map.redirect_defaults = False
        self.register_error_handler(Exception, self.on_error)
        self.teardown_request(self.teardown_db_session)

    def on_error(self, ex):
        exc_info = sys.exc_info()
        try:
            encode_type, encode = request.accept_encoder()
        except exc.BadRequest:
            flask.app.reraise(*exc_info)
        try:
            error = exc.Error.cast(ex)
        except (ValueError, LookupError):
            flask.app.reraise(*exc_info)
        if error.status_code >= 500:
            logger.exception(exc_info[0], exc_info=exc_info)
        return Response(
            status=error.status_code,
            response=encode(error),
            content_type=encode_type,
        )

    def teardown_db_session(self, _):
        models.db_session_teardown()


app = Application()


class Resource(hype.Resource):

    registry = hype.Registry(app)


from . import exc
from .resources import User, Anonymous, Password, Prisoner, Stats

import contextlib
import threading
import urlparse

import pilo
import requests

from . import exc, mimes


class Config(pilo.Form):

    url = pilo.fields.String(default=None)

    headers = pilo.fields.Dict(
        pilo.fields.String(), pilo.fields.String(), default=dict
    )

    email_address = pilo.fields.String(default=None)

    password = pilo.fields.String(default=None)

    @property
    def auth(self):
        if self.email_address is None or self.password is None:
            return
        return (self.email_address, self.password)


class Client(threading.local):

    accept_type = mimes.json.content_type

    def __init__(self, config):
        self.session = requests.Session()
        self.config = config

    def configure(self, **kwargs):
        src = self.config.copy()
        src.update(kwargs)
        config = self.config
        self.config = Config(src)

        @contextlib.contextmanager
        def restore():
            try:
                yield
            finally:
                self.config = config

        return restore()

    def use_headers(self, *args):
        headers = self.config.headers.copy() if self.config.headers else {}
        headers.update((name, value) for (name, value) in args)
        return self.configure(headers=headers)

    def error(self, ex):
        if not ex.response.content:
            return
        try:
            source = mimes.source_for(ex.response.headers['content-type'])
        except LookupError:
            return
        return exc.Error.from_source(source(
            ex.response.content, encoding=ex.response.encoding
        ))

    def method(self, method, uri, data, params, headers, source=True):
        url = urlparse.urljoin(self.config.url, uri)
        headers.update({
            'accept-type': self.accept_type,
        })
        headers.update(self.config.headers)
        if data is not None:
            text = mimes.json.encode(data)
            headers['content-type'] = mimes.json.content_type
        else:
            text = None
        if self.config.headers:
            headers.update(self.config.headers)
        if params:
            params = mimes.url.encode(params)
        response = method(
            url,
            params=params,
            data=text,
            headers=headers,
            auth=self.config.auth
        )
        try:
            response.raise_for_status()
        except requests.HTTPError as ex:
            error = self.error(ex)
            if error is not None:
                raise error
            raise
        if not response.content:
            return
        if source:
            source = mimes.source_for(response.headers['content-type'])
            return source(response.content, encoding=response.encoding)
        decode = mimes.decoder_for(response.headers['content-type'])
        return decode(response.content)

    def get(self, uri, params=None, **kwargs):
        return self.method(self.session.get, uri, None, params, {}, **kwargs)

    def delete(self, uri, params=None, **kwargs):
        return self.method(self.session.delete, uri, None, params, {}, **kwargs)

    def post(self, uri, params=None, data=None, **kwargs):
        return self.method(self.session.post, uri, data, params, {}, **kwargs)

    def put(self, uri, params=None, data=None, **kwargs):
        return self.method(self.session.put, uri, data, params, {}, **kwargs)


default = Config()

configure = default.update

cli = Client(default)

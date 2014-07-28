__all__ = [
    'json',
    'url',
]

import collections
import datetime
import logging
import json
import urllib
import uuid

import pilo


logger = logging.getLogger(__name__)


MIME = collections.namedtuple('MIME', [
    'accept_type', 'source', 'content_type', 'encode',
])


# json

JSONSource = pilo.source.JsonSource


class JSONEncoder(json.JSONEncoder):

    def __init__(self, indent=4, sort_keys=True, errors='strict'):
        super(JSONEncoder, self).__init__(indent=indent, sort_keys=sort_keys)
        self.errors = errors

    def default(self, o):
        if isinstance(o, datetime.datetime):
            return self._datetime(o)
        if isinstance(o, datetime.date):
            return self._date(o)
        if isinstance(o, datetime.time):
            return self._time(o)
        if isinstance(o, uuid.UUID):
            return self._uuid(o)
        if self.errors == 'strict':
            raise TypeError(repr(o) + ' is not JSON serializable')
        if self.errors == 'warn':
            logger.warning(repr(o) + ' is not JSON serializable')

    def _datetime(self, o):
        return o.isoformat()

    def _date(self, o):
        return '{:04d}-{:02d}-{:02d}'.format(o.year, o.month, o.day)

    def _time(self, o):
        return o.strftime('%H:%M:%S')

    def _uuid(self, o):
        return str(o.hex)


json = MIME(
    accept_type='application/json',
    source=JSONSource,
    content_type='application/json',
    encode=JSONEncoder().encode,
)


# url

class URLEncoder(object):

    def __init__(self, exclude_none=True, doseq=1, errors='strict'):
        super(URLEncoder, self).__init__()
        self.exclude_none = exclude_none
        self.doseq = doseq
        self.errors = errors

    def encode(self, o):

        query = []

        def _encode_value(key, value):
            if value is None and self.exclude_none:
                return
            if isinstance(value, (list, tuple)):
                for v in value:
                    _encode_value(key, v)
                return
            if not isinstance(value, basestring):
                v = self.default(value)
            if value is None and self.exclude_none:
                return
            query.append((key, value))

        for k, v in o.iteritems():
            _encode_value(k, v)

        return urllib.urlencode(query, self.doseq)

    def default(self, o):
        if isinstance(o, (int, long)):
            return str(o)
        if isinstance(o, bool):
            return 'true' if o else 'false'
        if isinstance(o, datetime.datetime):
            return self._datetime(o)
        if self.errors == 'strict':
            raise TypeError(repr(o) + ' is not URL serializable')
        if self.errors == 'warn':
            logger.warning(repr(o) + ' is not URL serializable')

    def _datetime(self, value):
        return value.isoformat()

    def _date(self, o):
        return o.strftime('%Y-%m-%d')

    def _time(self, o):
        return o.strftime('%H:%M:%S')


url = MIME(
    accept_type='application/x-www-form-urlencoded',
    source=None,
    content_type='application/x-www-form-urlencoded',
    encode=URLEncoder().encode,
)

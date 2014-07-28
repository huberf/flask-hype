from __future__ import unicode_literals


SQLA = 'postgresql://hag:hag@localhost/hag'

REDIS = {
    'host': 'localhost',
    'port': 6379,
    'db': 10,
}

PASSWORD_SALT = 'dbf0f3be-4fe7-4987-a905-bed94a32eda9'

API_HEADERS = {
    'admin': 'X-Hags-Admin',
}

API_ADMIN = 'idkfa'

WORDS = {
    'url': '/usr/share/dict/words',
}

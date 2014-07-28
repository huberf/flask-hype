from __future__ import absolute_import

__all__ = [
    'Id',
]

import codecs
import uuid


class Id(object, codecs.Codec):

    def __init__(self, encoding='hex', prefix=None):
        if encoding == 'hex':
            self._encode, self._decode = base32_encode, base32_decode
        elif encoding == 'base58':
            self._encode, self._decode = base58_encode, base58_decode
        elif encoding == 'base62':
            self._encode, self._decode = base62_encode, base62_decode
        else:
            raise ValueError('Invalid encoding {0}'.format(encoding))
        self.encoding = encoding
        self.prefix = prefix

    def encode(self, input, errors='strict'):
        if not isinstance(input, uuid.UUID):
            raise TypeError(
                'Expected instance of {0} not {1}'.format(uuid.UUID, type(input))
            )
        encoded = self._encode(input.int)
        if self.prefix:
            value = '{0}{1}'.format(self.prefix, encoded)
        else:
            value = encoded
        return value

    def decode(self, input, errors='strict'):
        if not isinstance(input, basestring):
            raise TypeError(
                'Expected instance of {0} not {1}'
                .format(basestring, type(input))
            )
        encoded = input
        if self.prefix:
            if not input.startswith(self.prefix):
                raise ValueError('Does not start with "{}"'.format(self.prefix))
            encoded = encoded[len(self.prefix):]
        decoded = self._decode(encoded)
        return uuid.UUID(int=decoded)


def base_encode(num, alphabet, base):
    """
    Adapted from https://gist.github.com/ianoxley/865912
    """
    encode = ''

    if (num < 0):
        return ''

    while (num >= base):
        mod = num % base
        encode = alphabet[mod] + encode
        num = num / base

    if (num):
        encode = alphabet[num] + encode

    return encode


def base_decode(s, alphabet, base):
    """
    Adapted from https://gist.github.com/ianoxley/865912
    """
    decoded = 0
    multi = 1
    s = s[::-1]
    for char in s:
        decoded += multi * alphabet.index(char)
        multi = multi * base

    return decoded


def base32_encode(num):
    raise NotImplementedError


def base32_decode(s):
    raise NotImplementedError


base58_alphabet = '123456789abcdefghijkmnopqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ'


def base58_encode(num):
    return base_encode(num, base58_alphabet, 58)


def base58_decode(s):
    return base_decode(s, base58_alphabet, 58)


base62_alphabet = '0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ'


def base62_encode(num):
    return base_encode(num, base62_alphabet, 62)


def base62_decode(s):
    return base_decode(s, base62_alphabet, 62)

from __future__ import unicode_literals

import pilo
from werkzeug.exceptions import (
    HTTPException,
    NotFound,
    Forbidden,
    BadRequest,
    Unauthorized,
    ServiceUnavailable,
)

from hags import models

from . import Resource


def cannot_guess(ex):
    prisoner = Resource.registry.adapt(ex.prisoner)
    description = (
        'Cannot guess "{0}" for prisoner {1} in state "{2}"'
        .format(ex.guess, prisoner.link, prisoner.state)
    )
    return Error(
        type='cannot_guess',
        status_code=409,
        description=description,
    )


def cannot_giveup(ex):
    prisoner = Resource.registry.adapt(ex.prisoner)
    description = (
        'Cannot suicide prisoner {0} in state "{1}"'
        .format(prisoner.link, prisoner.state)
    )
    return Error(
        type='cannot_suicide',
        status_code=409,
        description=description,
    )


class Error(pilo.Form):

    registry = {
        models.CannotGuess: cannot_guess,
        models.CannotGiveUp: cannot_giveup,
    }

    @classmethod
    def cast(cls, ex):
        if type(ex) not in cls.registry:
            raise LookupError('None registered for {0}'.format(type(ex)))
        return cls.registry[type(ex)](ex)

    _type_ = pilo.fields.Type.instance('error_t')

    type = pilo.fields.String()

    status_code = pilo.fields.Integer()

    description = pilo.fields.String()


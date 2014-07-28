__all__ = [
    'init',
    'models',
    'api',
]

__version__ = '0.1.0'

import logging

from . import config
from . import models
from . import api


logger = logging.getLogger(__name__)


def init(conf_file=None):
    if conf_file is not None:
        logger.info('loading config from "%s"', conf_file)
        execfile(conf_file, {'config': config})
    models.init(config)
    api.init(config)

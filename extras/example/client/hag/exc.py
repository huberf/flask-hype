import pilo
import requests


HTTPError = requests.HTTPError


class MultipleFound(Exception):
    pass


class NoneFound(Exception):
    pass


class Error(Exception):

    registry = {
    }

    @classmethod
    def from_source(cls, source):
        view = cls.View()
        errors = view.map(source)
        if errors:
            return None
        matched_cls = cls.registry.get(view.type, cls)
        return matched_cls(**view)

    class View(pilo.Form):

        _type_ = pilo.fields.Type.instance('error_t')

        type = pilo.fields.String()

        status_code = pilo.fields.Integer()

        description = pilo.fields.String()

    def __init__(self, type, status_code, description, **kwargs):
        self.type = type
        self.status_code = status_code
        self.description = description
        super(Error, self).__init__(description)


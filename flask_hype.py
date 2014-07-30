"""
Used to build a resource layer for your models, like e.g.:

.. code:: python

    import flask
    from flask.ext import hype

    import models

    app = flask.Flask()


    class Resource(hype.Resource)

        registry = hype.Registry(app)


    class DB(hype.Binding)

        def __init__(self, cls, *args, **kwargs):
            self.cls = cls
            super(DB, self).__init__(name='db', *args, **kwargs)

        def get(self, id)
            return models.db_session.query(cls).get(id)

        def adapts(self, obj)
            return isinstance(obj, cls)


    class Cache(hype.Binding)

        def __init__(self, cls, *args, **kwargs):
            self.cls = cls
            super(Cache, self).__init__(name='cache', *args, **kwargs)

        def get(self, id)
            return models.cache_cli.get(id)

        def adapts(self, obj)
            return isinstance(obj, cls)


    class Something(Resource):

        link = hype.Link('show_something', something='id')

        id = hype.Id()

        def mutate(self, **kwargs)
            self.bindings.db.cast(self)
            assert isinstance(self.obj, models.Other)
            self.obj.mutate(**kwargs)
            return self.refresh()

    Something.bind(Cache(models.CachedOther), DB(models.Other))

    @app.route('/somethings/', methods=['POST'])
    def create_something():
        ...

    @app.route('/somethings/<Something:something>', methods=['GET'])
    def show_something(something):
        ...

    @app.route('/somethings/<Something:something>', methods=['PUT'])
    def update_something(something):
        something.murate(yes='pleez')

"""

__version__ = '0.1.1'

__all__ = [
    'Id',
    'id_field',
    'Link',
    'ResolvedLink',
    'Binding',
    'Resource',
    'Registry',
]

import codecs
import collections
import functools
import inspect
import itertools
import logging

import flask
import pilo
import werkzeug.routing


logger = logging.getLogger(__name__)


class Id(pilo.fields.String):
    """
    String fields used with identified `Resource`s:

    .. code:: python

        class MyResource(Resource):

            id = hype.Id('guid')

    Pass a `codecs.Codec` if the model space id needs to be encoded:

    .. code:: python

        class MyResource(Resource):

            id = hype.Id('guid', IdCodec(prefix='munch=', encoding='hex'))

    `Link`s (i.e. URIs) are the canonical way to reference a `Resource`.
    """

    def __init__(self, *args, **kwargs):
        # pluck resource
        is_resource = lambda x: inspect.isclass(x) and issubclass(x, Resource)
        args, resource = pilo.fields.pluck(args, is_resource)
        if resource is not pilo.NOT_SET:
            kwargs['resource'] = resource

        # pluck codec
        is_codec = lambda x: isinstance(x, codecs.Codec)
        args, codec = pilo.fields.pluck(args, is_codec)
        if codec is not pilo.NOT_SET:
            kwargs['codec'] = codec

        # codec
        if 'resource' in kwargs:
            self._codec = kwargs.pop('resource')
        elif 'codec' in kwargs:
            self._codec = kwargs.pop('codec')
        else:
            self._codec = self.Identity()

        super(Id, self).__init__(*args, **kwargs)

    class Identity(codecs.Codec):

        def encode(self, input, errors='strict'):
            return input

        def decode(self, input, errors='strict'):
            return input

    @property
    def codec(self):
        if isinstance(self._codec, codecs.Codec):
            return self._codec

        # registry
        if isinstance(self._codec, basestring):
            try:
                self._codec = codecs.lookup(self._codec)
                return self._codec
            except LookupError:
                pass

        # resource
        if isinstance(self._codec, basestring):
            resource_cls = Resource.registry.match_name(self._codec)
            if resource_cls is None:
                raise Exception(
                    'No resource with name "{0}"'.format(self._codec)
                )
        elif inspect.isclass(self._codec) and issubclass(self._codec, Resource):
            resource_cls = self._codec

        # resource id field
        field = id_field(resource_cls, default=None)
        if not field:
            raise Exception('{0} has no Id field'.format(resource_cls.__name__))
        self._codec = field.codec

        return self._codec

    def encode(self, obj):
        return self.codec.encode(obj)

    def decode(self, obj):
        return self.codec.decode(obj)

    def is_encoded(self, obj):
        try:
            self.codec.decode(obj)
            return True
        except (TypeError, ValueError):
            return False

    def is_decoded(self, obj):
        try:
            self.codec.encode(obj)
            return True
        except (TypeError, ValueError):
            return False

    # pilo.fields.String

    def _parse(self, path):
        return self.encode(path.primitive())


class DecodedId(pilo.Field):

    def __init__(self, resource=None, *args, **kwargs):
        self.resource = resource
        super(DecodedId, self).__init__(*args, **kwargs)

    def _parse(self, path):
        if isinstance(self.resource, basestring):
            resource = Resource.registry.match_name(self.resource)
            if resource is None:
                raise Exception('No resource with name "{0}"'.format(self.resource))
            self.resource = resource
        resource_cls = Resource.registry.match_id(path.value, self.resource)
        if not resource_cls:
            self.ctx.errors.invalid('does not match resource')
            return pilo.ERROR
        return id_field(resource_cls).decode(path.value)


# https://wiki.python.org/moin/PythonDecoratorLibrary#Alternate_memoize_as_nested_functions
def memoize(func):

    cache = {}

    @functools.wraps(func)
    def memoizer(*args, **kwargs):
        key = (args, tuple(kwargs.iteritems()))
        if not isinstance(key, collections.Hashable):
            return func(*args, **kwargs)
        if key in cache:
            return cache[key]
        result = func(*args, **kwargs)
        cache[key] = result
        return result

    return memoizer


@memoize
def id_field(obj, default=pilo.NOT_SET):
    """
    Locates and returns the `Id` field associated with either a:

        - `Resource` subclass
        - `Resource` instance

    :param obj: Either a `Resource` subclass or instance.
    :param default: What to return if no such `Id` field can be located.

    :returns: The `Id` field.
    """
    if not inspect.isclass(obj):
        if not isinstance(type(obj), Resource):
            raise TypeError(
                '{0} not a {1} subclass or instance'.format(obj, Resource)
            )
        obj = type(obj)
    if not issubclass(obj, Resource):
        raise TypeError('{0} not a {1} subclass'.format(obj, Resource))
    for field in obj.fields:
        if isinstance(field, Id):
            return field
    if default is pilo.NOT_SET:
        raise ValueError('{0} has not Id field'.format(obj))
    return default


class Link(pilo.fields.String):
    """
    String fields used to externally reference `Resource`:

    .. code:: python

        class MyResource(Resource):

            id =  hype.Id('guid')

            link = hype.Link('my_resource.show', my_resource='id')

        @flask_app.route('/mrs/<MyResource:my_resource>', endpoint='my_resource.show')
        def show_my_resource(my_resource):
            ...

    This is just a `flask.url_for` wrapper for rendering a URLs. If you want
    to by-pass `flask.url_for`s context requirements you could do e.g.:

    .. code:: python

        class Link(hype.Link):

            # hype.Link

            def _url_map(self):
                return return flask_app.url_map

    """

    def __init__(self, endpoint, **kwargs):
        self.endpoint = endpoint
        self.method = kwargs.pop('method', None)
        self.append_unknown = kwargs.pop('append_unknown', True)
        reserved = {
            'nullable': kwargs.pop('nullable', pilo.NONE),
            'default': kwargs.pop('default', pilo.NOT_SET),
        }
        for k, v in kwargs.iteritems():
            if not isinstance(v, (basestring, pilo.Field)):
                raise ValueError('{0}= type {1} invalid'.format(k, type(v)))
        self.params = kwargs
        super(Link, self).__init__(**reserved)

    def _url_map(self):
        if flask.has_app_context():
            return flask.current_app.url_map

    def _url_for(self, **values):
        url_map = self._url_map()
        if url_map is None:
            raise Exception('{0}._url_map() = None'.format(type(self)))
        for rule in url_map.iter_rules(self.endpoint):
            if rule.suitable_for(values, self.method):
                rv = rule.build(values, self.append_unknown)
                if rv is not None:
                    _, path = rv
                    return path
        raise werkzeug.routing.BuildError(self.endpoint, values, self.method)

    # pilo.fields.String

    def _compute(self):
        values = {}
        try:
            for name, field in self.params.iteritems():
                if isinstance(field, pilo.Field):
                    value = field.__get__(self.ctx.form)
                else:
                    value = reduce(getattr, field.split('.'), self.ctx.form)
                if value in (None, pilo.IGNORE):
                    return pilo.NONE
                values[name] = value
        except (AttributeError, pilo.Missing):
            return pilo.NONE
        return self._url_for(**values)


class RequestForm(pilo.Form):
    """
    Helper specialization of form which represents form mapping errors:

        - pilo.Missing
        - pilo.Invalid

    as `werkzeug.exceptions.BadRequest`.
    """

    @classmethod
    def _missing(cls, field):
        return werkzeug.exceptions.BadRequest(
            '{0} - required but missing'.format(field.src)
        )

    @classmethod
    def _invalid(cls, field, violation):
        return werkzeug.exceptions.BadRequest(
            '{0} - {1}'.format(field.src, violation)
        )

    # pilo.Form

    def _root_map(self, src, tags, unmapped, error):
        with self.ctx(Missing=self._missing, Invalid=self._invalid):
            return super(RequestForm, self)._root_map(src, tags, unmapped, error)


class ResolvedLink(pilo.fields.Field):
    """
    Object field typically with `RequestForm`s to translate a `Link` value
    (i.e. URL) to the `Resource` instance it references:

    .. code:: python

        class Blah(Resource)

            ...

        @flask_app.route('/blahs/<Blah:blah>', endpoint='blah.show')
        def show_blah(blah):
            ...

        class CreateSomething(hype.RequestForm):

            blah = hype.ResolveField('blah.show')


        form = CreateSomething(request.json)
        assert isinstance(form.blah, Blah)

    """

    def __init__(self, *args, **kwargs):
        self.method = kwargs.pop('method', 'GET')
        self.param = kwargs.pop('param', None)
        self.endpoint = kwargs.pop('endpoint', None)
        super(ResolvedLink, self).__init__(*args, **kwargs)

    def _url_adapter(self):
        if flask.has_request_context():
            request_ctx = flask._request_ctx_stack.top
            return request_ctx.url_adapter

    # pilo.fields.String

    def _parse(self, path):
        uri = super(ResolvedLink, self)._parse(path)
        if uri in pilo.IGNORE:
            return uri
        url_adapter = self._url_adapter()
        if url_adapter is None:
            return pilo.NONE
        try:
            endpoint, params = url_adapter.match(uri, method=self.method)
        except werkzeug.exceptions.NotFound:
            self.ctx.errors.invalid('not found')
            return pilo.NONE
        if self.endpoint is not None and endpoint != self.endpoint:
            self.ctx.errors.invalid('unexpected type')
            return pilo.NONE
        if self.param is None:
            if len(params) != 1:
                self.ctx.errors.invalid('ambiguous')
                return pilo.NONE
            return params.values()[0]
        if self.param not in params:
            self.ctx.errors.invalid('not present')
            return pilo.NONE
        return params[self.param]


class ResourceConverter(werkzeug.routing.BaseConverter):
    """
    Routing parameter converted for `Resource`s. These are generated and
    registered for you with the same name as that of you resource, e.g.:

    .. code:: python

        class Resource(hype.Resource):

            registry = hype.Registry(flask_app)

        class Something(Resource)

            id = field.Id('ID')

        assert 'Something' in flask_app.url_map.converters

        @flask_app.route('/tight/<Something:something>/en')
        def tighten(something):
            assert isinstance(something, Something)
            ...

    """

    resource_cls = None

    def to_python(self, value):
        if self.resource_cls is None:
            raise Exception('{0}.resource_cls is None'.format(type(self)))

        if isinstance(value, self.resource_cls):
            return value
        matched_cls = self.resource_cls.registry.match_id(value, self.resource_cls)
        if matched_cls is None:
            raise werkzeug.routing.ValidationError(
                'No {0} with id "{1}"'.format(self.resource_cls, value)
            )
        field = id_field(matched_cls, default=None)
        if field is None:
            raise werkzeug.routing.ValidationError(
                '{0} has no Id field'.format(matched_cls, value)
            )
        obj = matched_cls.get(value)
        if obj is None:
            raise werkzeug.routing.ValidationError(
                '{0}.get({1}) is None'.format(matched_cls, value)
            )
        return obj

    def to_url(self, value):
        if self.resource_cls is None:
            raise Exception('{0}.resource_cls is None'.format(type(self)))

        # resource
        if isinstance(value, self.resource_cls):
            field = id_field(self.resource_cls, default=None)
            if field is None:
                poly_cls = self.resource_cls.registry.polymorphic(
                    value, self.resource_cls,
                )
                if poly_cls is not None:
                    raise werkzeug.routing.ValidationError(
                        '{0} has no Id field'.format(self.resource_cls)
                    )
                field = id_field(poly_cls, default=None)
                if poly_cls is not None:
                    raise werkzeug.routing.ValidationError(
                        '{0} has no Id field'.format(poly_cls)
                    )
            value = field.__get__(value)
        elif (isinstance(value, basestring) and
              self.resource_cls.registry.match_id(value, self.resource_cls)):
            pass
        elif self.resource_cls.registry.match_obj(value, self.resource_cls):
            value = self.resource_cls.registry.encode_id(value, self.resource_cls)
        else:
            raise werkzeug.routing.ValidationError(
                '{0}.to_url() unable to encode "{1}"'.format(type(self), value)
            )
        return super(ResourceConverter, self).to_url(value)


class Registry(collections.MutableSet):
    """
    Set containing all your `Resource`s. When building out your resource layer
    you'll need to create and attach one of these to your base `Resource` like
    this:

    .. code:: python

        flask_app = flask.Flask()

        class Resource(hype.Resource)

            registry = hype.Registry(flask_app)

    and that's it.

    """
    def __init__(self, app):
        self.app = app
        self.resource_clses = set()
        self.resource_cls = None

    def adapt(self, obj, *resource_clses):
        matched_cls = self.match_obj(obj, *resource_clses)
        if matched_cls is None:
            raise TypeError('{0} matches no {1}'.format(obj, self.resource_cls))
        return matched_cls(obj)

    def encode_id(self, obj, *resource_clses):
        matched_cls = self.match_obj(obj, *resource_clses)
        if matched_cls is None:
            raise TypeError('{0} matches no {1}'.format(obj, self.resource_cls))
        return id_field(matched_cls).__get__(matched_cls(obj))

    def decode_id(self, id, *resource_clses):
        matched_cls = self.match_id(id, *resource_clses)
        if matched_cls is None:
            raise TypeError('{0} matches no {1}'.format(id, self.resource_cls))
        return id_field(matched_cls).decode(id)

    def id_codecs(self):
        codecs = []
        for resource_cls in self:
            field = id_field(resource_cls, None)
            if field is None:
                continue
            codecs.append(field.codec)
        return codecs

    def match_obj(self, obj, *resource_clses):
        resource_clses = resource_clses or self
        for cls in resource_clses:
            for binding in cls.bindings:
                if not binding.adapts(obj):
                    continue
                if not binding.polymorphic:
                    return cls
                return self.match_obj(obj, *cls.__subclasses__()) or cls
            if cls.__subclasses__():
                cls = self.match_obj(obj, *cls.__subclasses__())
                if cls is not None:
                    return cls

    def match_id(self, id, *resource_clses):

        def _match(clses):
            for cls in clses:
                field = id_field(cls, default=None)
                if field is not None and field.is_encoded(id):
                    return cls
                cls = _match(cls.__subclasses__())
                if cls is not None:
                    return cls

        return _match(resource_clses or self)

    def match_name(self, name):
        for cls in self:
            if name == cls.__name__:
                return cls

    # collections.MutableSet

    def add(self, value):
        if not inspect.isclass(value):
            raise TypeError('{0} not a class'.format(value))
        if self.resource_cls:
            if not issubclass(value, self.resource_cls):
                raise TypeError(
                    '{0} not {1} subclass'.format(value, self.resource_cls)
                )
        else:
            self.resource_cls = value

        converter_name = value.__name__
        if converter_name in self.app.url_map.converters:
            converter_cls = self.app.url_map.converters[converter_name]
            if not issubclass(converter_cls, ResourceConverter):
                raise Exception(
                    'Incompatible converter "{0}" registered'
                    .format(converter_name)
                )
            if converter_cls.resource_cls != value:
                raise Exception(
                    'Incompatible converter "{0}" registered'
                    .format(converter_name)
                )
        else:
            self.app.url_map.converters[converter_name] = type(
                '{0}Converter'.format(converter_name),
                (ResourceConverter,),
                {'resource_cls': value}
            )

        return self.resource_clses.add(value)

    def discard(self, value):
        if value.__name__ in self.app.url_map.converters:
            self.app.url_map.converters.pop(value.__name__)
        return self.resource_clses.discard(value)

    def __contains__(self, value):
        return self.resource_clses.__contains__(value)

    def __iter__(self):
        return self.resource_clses.__iter__()

    def __len__(self):
        return self.resource_clses.__len__()


class Binding(object):
    """
    A `Binding` is what you use to link a model type to a `Resource`.

    `name`
        An optional name the binding. If named a binding can be referenced by
        name like:

        .. code:: python

            class Something(Resouce)

                ...

                def do_it(self):
                    self.bindings.{name}.cast(self)  # force to {name} binding
                    ...

    `polymorphic`
        Flag indicating whether this binding is polymorphic. Defaults to `False`.

    """

    _order = itertools.count(0)

    def __init__(self, name=None, polymorphic=False):
        if not isinstance(name, basestring):
            raise TypeError('name={0!r} is not a string'.format(name))
        self._order = self._order.next()
        self.name = name
        self.polymorphic = polymorphic

    def get(self, id):
        """
        Retrieves the model instance by id (see `Id`).

        :param id: A *decoded* id (see `Id`).

        :returns: The underlying model object or None if not present.
        """
        raise NotImplementedError

    @property
    def enabled(self):
        """
        This can be used to disable a binding so that it won't be used when
        adapting model objects to `Resource`s (e.g. maybe the data-store for a
        binding is offline).

        :returns: `True` if it enabled, otherwise `False`.
        """
        return True

    def cast(self, obj):
        """
        Convert a model instance to its an equivalent adapts by this binding.
        """
        raise NotImplementedError

    def adapts(self, obj):
        """
        Can this binding adapt a model instance?

        :param obj: Model instance.

        :returns: `True` if it can, otherwise `False`.
        """
        raise NotImplementedError


class Bindings(collections.defaultdict):
    """
    Mapping of `Resource` types to a list of its registered `Binding`s. This is
    created and attached to your base `Resource` for you:

    .. code:: python

        class Resource(hype.Resource):

            registry = hype.Registry(flask_app)

        assert hasattr(Resource, 'bindings')
        assert isinstance(Resource.bindings, hype.Bindings)
        assert hasattr(Resource, 'b')
        assert Resource.b is Resource.bindings

        class A(Resource):

            ...

        A.bind(Binding(models.A))

        assert A.b is Resource.b
        assert A in Resource.b
        assert Resource.b[A] == [Binding(models.A)]

    """

    class ForResource(collections.MutableSequence):

        def __init__(self):
            self.bindings = []

        def __getitem__(self, key):
            return self.bindings.__getitem__(key)

        def __setitem__(self, key, value):
            ret = self.bindings.__setitem__(key, value)
            if value.name is not None:
                setattr(self, value.name, value)
            return ret

        def __delitem__(self, key):
            value = self.bindings[key]
            ret = self.bindings.__delitem__(key)
            if value.name is not None:
                delattr(self, value.name)
            return ret

        def __len__(self):
            return self.bindings.__len__()

        def insert(self, key, value):
            ret = self.bindings.insert(key, value)
            if value.name is not None:
                setattr(self, value.name, value)
            return ret

    def __init__(self, resource_cls):
        super(Bindings, self).__init__(self.ForResource)
        self.resource_cls = resource_cls

    def __get__(self, resource, resource_cls=None):
        if resource is not None:
            resource_cls = type(resource)
        if not issubclass(resource_cls, self.resource_cls):
            raise TypeError(
                '{0} it not {1} subclass'.format(resource_cls, self.resource_cls)
            )
        return self[resource_cls]


class Resource(pilo.Form):
    """
    The Resource used to represent you model type(s) via flask. They are:

    - hooked up to a `Registry`
    - bound to models types

    and

    - define whatever transformations needed to place models instances in
      resource space.

    The first step is always to attach `Registry`:

    .. code:: python

        class Resource(hype.Resource)

            registry = hype.Registry(flask_app)

    Then you and define and bind you resources:

        .. code:: python

        class Something(Resource)


            link = hype.Link('show_somethings', something='id')

            id = hype.Id('guid')

        Something.bind(DBBinding(model.Something))

    """

    class __metaclass__(pilo.Form.__metaclass__):

        def __new__(mcs, name, bases, dikt):
            cls = pilo.Form.__metaclass__.__new__(mcs, name, bases, dikt)
            if cls.registry is not None:
                cls.registry.add(cls)
                if cls.registry.resource_cls is cls:
                    cls.bindings = cls.b = Bindings(cls)
            return cls

    #: Registry for all resources derived from `Resource`. You set this.
    registry = None

    #: Bindings used to adapt objects to `Resource`s. Set for you.
    bindings = b = None

    @classmethod
    def bind(cls, *bindings):
        """
        Registers one of more `Binding` for this `Resource` type.

        :param bindings: Zero or more `Binding`s.

        """
        if cls.b is None:
            raise Exception(
                'Missing bindings, did you set {0}.registry'.format(cls)
            )
        cls.b.extend(bindings)

    #: The object this `Resource` instance is adapting.
    obj = None

    @classmethod
    def get(cls, id):
        matched_cls = cls.registry.match_id(id, cls)
        if not matched_cls:
            logger.info('no resource with id %s', id)
            return
        decoded_id = id_field(matched_cls).decode(id)
        candidates = 0
        for binding in matched_cls.bindings:
            if not binding.enabled:
                continue
            candidates += 1
            obj = binding.get(decoded_id)
            if obj is not None:
                if binding.polymorphic:
                    matched_cls = cls.registry.match_obj(obj, matched_cls)
                return matched_cls(obj)
        if candidates == 0:
            raise werkzeug.exceptions.ServiceUnavailable()

    def __eq__(self, other):
        if not isinstance(other, Resource):
            return super(Resource, self).__eq__(other)
        self_id, other_id = id_field(type(self), None), id_field(type(other), None)
        if id is None or other_id is None:
            return super(Resource, self).__eq__(other)
        return self_id.__get__(self) == other_id.__get__(other)

    def __ne__(self, other):
        return not self.__eq__(other)

    def __hash__(self):
        field = id_field(type(self), None)
        if field is None:
            return super(Resource, self).__hash__()
        return field.__get__(self)

    def refresh(self, obj=None):
        src = pilo.DefaultSource(self.obj if obj is None else obj)
        return self.map(src, reset=True, error='raise')

    # pilo.Form

    def _map(self, tags, unmapped):
        self.obj = self.ctx.src_path.value
        return super(Resource, self)._map(tags, unmapped)

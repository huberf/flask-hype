import copy

import pilo

from . import cli, exc


class Enum(list):

    def __init__(self, *args, **kwargs):
        for arg in args:
            kwargs[arg.upper()] = arg.lower()
        super(Enum, self).__init__(kwargs.values())
        for k, v in kwargs.iteritems():
            setattr(self, k, v)



class Page(pilo.Form):

    link = pilo.fields.String()

    number = pilo.fields.Integer()

    size = pilo.fields.Integer()

    first_link = pilo.fields.String()

    @property
    def first(self):
        return type(self)(cli.get(self.first_link))

    next_link = pilo.fields.String(default=None)

    @property
    def next(self):
        return (
            type(self)(cli.get(self.next_link))
            if self.next_link else None
        )

    previous_link = pilo.fields.String(default=None)

    @property
    def previous(self):
        return (
             type(self)(cli.get(self.previous_link))
             if self.previous_link else None
        )

    last = pilo.fields.String()

    @property
    def last(self):
        return type(self)(cli.get(self.last_link))

    items = pilo.fields.List(pilo.Field())

    @items.field.parse
    def items(self, path):
        identity = Resource._type_.probe(None)
        if identity not in Resource._type_.types:
            raise ValueError('Invalid value for type field {} = {}'.format(
                Resource._type_, identity
            ))
        item = Resource._type_.types[identity]()
        errors = item.map()
        if errors:
            return pilo.ERROR
        return item

    total = pilo.fields.Integer()


class Pagination(object):

    def __init__(self, uri, params):
        self.uri = uri
        self.params = params
        self.page = None

    def __iter__(self):
        return self

    def next(self):
        if not self.page:
            source = Resource.cli.get(self.uri, params=self.params)
            self.page = Page(source)
            return self.page
        if self.page.next:
            self.page = self.page.next
            return self.page
        raise StopIteration()


class QueryIndex(pilo.Form):

    offset = pilo.fields.Integer(optional=True)

    limit = pilo.fields.Integer(optional=True)


class Query(object):

    def __init__(self, uri, index=None):
        self.uri = uri
        self.index = index if index is not None else QueryIndex()

    def all(self):
        return [item for item in self]

    def count(self):
        return copy.copy(self).limit(1).pages.next().total

    def first(self):
        items = list(copy.copy(self).limit(1))
        if len(items) == 0:
            raise exc.NoneFound()
        return items[0]

    def one(self):
        items = list(copy.copy(self).limit(2))
        if len(items) == 0:
            raise exc.NoneFound()
        elif len(items) > 1:
            raise exc.MultipleFound()
        return items[0]

    def filter_by(self, **kwargs):
        self.index.map(kwargs, error='raise')
        return self

    def limit(self, value):
        self.index.map({'limit': value}, error='raise')
        return self

    def offset(self, value):
        self.index.map({'offset': value}, error='raise')
        return self

    @property
    def pages(self):
        return Pagination(self.uri, self.index.copy())

    def __iter__(self):
        pages = self.pages
        for page in pages:
            i = 0
            while i < len(page.items):
                item = page.items[i]
                i += 1
                yield item

    def update(self, data):
        return Resource.cli.put(self.uri, params=self.index, data=data)


class Resource(pilo.Form):

    cli = cli

    _type_ = pilo.fields.Type.abstract()

    link = pilo.fields.String()

    @classmethod
    def get(cls, link):
        return cls(cls.cli.get(link))

    def refresh(self, source=None):
        source = self.get(self.link) if source is None else source
        self.map(source, reset=True, error='raise')
        return self


def me():
    return User(User.cli.get('/users/me'))


class User(Resource):

    _type_ = pilo.fields.Type.instance('user_t')

    id = pilo.fields.String()

    created_at = pilo.fields.Datetime(format='iso8601')

    updated_at = pilo.fields.Datetime(format='iso8601')

    enabled = pilo.fields.Boolean()

    passwords_link = pilo.fields.String()

    @property
    def passwords(self):
        return Page(self.link)

    def add_password(self, text):
        self.cli.post(self.passwords_link, {'text': text})

    stats_link = pilo.fields.String()

    @property
    def stats(self):
        return Stats.get(self.stats_link)

    prisoners_link = pilo.fields.String()

    @property
    def prisoners(self):
        return Page(self.prisoners_link)


class Password(Resource):

    _type_ = pilo.fields.Type.instance('password_t')

    id = pilo.fields.String()

    enabled = pilo.fields.Boolean()


class Stats(Resource):

    _type_ = pilo.fields.Type.instance('stats_t')

    prisoners = pilo.fields.Integer()

    rescued = pilo.fields.Integer()

    failed = pilo.fields.Integer()

    chickens = pilo.fields.Integer()

    hits = pilo.fields.Integer()

    misses = pilo.fields.Integer()

    total = pilo.fields.Integer()

    hit_rate = pilo.fields.Decimal(nullable=True)


class Prisoner(Resource):

    _type_ = pilo.fields.Type.instance('prisoner_t')

    id = pilo.fields.String()

    started_at = pilo.fields.Datetime(format='iso8601')

    updated_at = pilo.fields.Datetime(format='iso8601')

    terminated_at = pilo.fields.Datetime(format='iso8601', nullable=True)

    expires_at = pilo.fields.Datetime(format='iso8601')

    states = Enum(ALIVE='alive', RESCUED='rescued', DEAD='dead')

    state = pilo.fields.String(choices=states)

    secret = pilo.fields.String()

    guesses = pilo.fields.List(pilo.fields.String())

    hits = pilo.fields.List(pilo.fields.String())

    misses = pilo.fields.List(pilo.fields.String())

    guess_link = pilo.fields.String()

    class Create(pilo.Form):

        secret = pilo.fields.String(optional=True).ignore(None)

    @classmethod
    def create(cls, secret=None, **kwargs):
        return cls(cli.post('/prisoners/', data=cls.Create(secret=secret, **kwargs)))

    def guess(self, value):
        return self.cli.post(self.guess_link, source=False, data=value)

    suicide_link = pilo.fields.String()

    def suicide(self):
        self.refresh(self.cli.post(self.suicide_link))

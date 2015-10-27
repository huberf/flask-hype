from flask.ext import hype
import pilo
import sqlalchemy.orm as saorm

from hags import models, codecs

from . import app, request, RequestForm, Response, exc, Resource


class Enum(list):

    def __init__(self, *args, **kwargs):
        for arg in args:
            kwargs[arg.upper()] = arg
        super(Enum, self).__init__(kwargs.values())
        for k, v in kwargs.iteritems():
            setattr(self, k, v)


class Id(hype.Id):

    def __init__(self, *args, **kwargs):
        if 'prefix' in kwargs:
            prefix = kwargs.pop('prefix')
            encoding = kwargs.pop('encoding', 'base58')
            kwargs['codec'] = codecs.Id(prefix=prefix, encoding=encoding)
        super(Id, self).__init__(*args, **kwargs)


class Link(hype.Link):

    def _url_map(self):
        return app.url_map


class Binding(hype.Binding):

    def __init__(self, cls, *args, **kwargs):
        self.cls = cls
        super(Binding, self).__init__(*args, **kwargs)

    def cast(self, obj, default=pilo.NOT_SET):
        if isinstance(obj, self.cls):
            return obj
        if isinstance(obj, Resource):
            obj.obj = self.cast(obj.obj)
            return obj
        if not self.adapts(obj):
            raise TypeError('{0}.adapts({1}) is False'.format(type(self), obj))
        cast_obj = self.get(obj.id)
        if cast_obj is not None:
            return cast_obj
        if default is not pilo.NOT_SET:
            return default
        raise exc.ServiceUnavailable()

    def adapts(self, obj):
        return isinstance(obj, self.cls)


class DBBinding(Binding):

    def __init__(self, *args, **kwargs):
        self.auto_cache = kwargs.pop('auto_cache', False)
        super(DBBinding, self).__init__(name='db', *args, **kwargs)

    def get(self, decodec_id):
        obj = self.cls.query.get(decodec_id)
        if obj is not None and self.auto_cache:
            obj.cache()
        return obj


class CacheBinding(Binding):

    def __init__(self, *args, **kwargs):
        super(CacheBinding, self).__init__(name='cache', *args, **kwargs)

    def get(self, decodec_id):
        return self.cls.get(decodec_id)


class Anonymous(Resource):

    def authorize(self, resource, action, *nesting):
        if resource is User and action == 'create':
            return
        raise exc.Unauthorized()


class User(Resource):

    _type_ = pilo.fields.String().constant('user_t')

    link = Link('user.show', user='id')

    id = Id(prefix='us-')

    email_address = pilo.fields.String()

    created_at = pilo.fields.Datetime()

    updated_at = pilo.fields.Datetime()

    enabled = pilo.fields.Boolean()

    prisoners_link = Link('prisoner.index', user='id')

    stats_link = Link('stats.show', user='id')

    @property
    def stats(self):
        obj = models.Stats.get(self.obj.id)
        if obj is None:
            return
        return Stats(obj)

    passwords_link = Link('password.create', user='id')

    @classmethod
    def authenticate(cls, email_address, password):
        try:
            obj = (
                models.User.query
                .filter_by(email_address=email_address)
            ).one()
        except saorm.exc.NoResultFound:
            return
        if not obj.authenticate(password):
            return
        return cls(obj)

    class Create(RequestForm):

        email_address = pilo.fields.String()

        password = pilo.fields.String(min_length=5)

    @classmethod
    def create(cls, source):
        form = cls.Create(source)
        obj = models.User.create(
            email_address=form.email_address, password=form.password
        )
        models.db_session.commit()
        return User(obj)

    def authorize(self, resource, action, *nesting):
        if isinstance(resource, Resource):
            resources = list(nesting) + [resource]
        if True:
            return
        raise exc.Forbidden()

    def add_password(self, source):
        return Password.create(source, user=self)


User.bind(
    CacheBinding(models.User.Cached),
    DBBinding(models.User),
)


@app.route('/users/<User:user>', methods=['GET'], endpoint='user.show')
@app.route('/users/me', methods=['GET'], endpoint='user.show', defaults={'user': None})
def show_user(user):
    user = request.user if user is None else user
    request.authorize(user, 'show')
    encode_type, encode = request.accept_encoder()
    return Response(status=200, response=encode(user), content_type=encode_type)


@app.route('/users/', methods=['POST'], endpoint='user.create')
def create_user():
    request.authorize(User, 'create')
    encode_type, encode = request.accept_encoder()
    user = User.create(request.content_source())
    return Response(status=201, response=encode(user), content_type=encode_type)


class Password(Resource):

    _type_ = pilo.fields.String().constant('user_t')

    id = Id(prefix='us-')

    created_at = pilo.fields.Datetime()

    enabled = pilo.fields.Boolean()

    class Create(RequestForm):

        text = pilo.fields.String(min_length=5)

    @classmethod
    def create(cls, source, user):
        form = cls.Create(source)
        obj = user.b.db.cast(user.obj).add_password(form.text)
        models.db_session.commit()
        return Password(obj)

    def delete(self):
        self.b.db.cast(self)
        models.db_session.delete(self.obj)
        models.db_session.commit()


@app.route('/users/<User:user>/passwords', methods=['POST'], endpoint='password.create')
@app.route('/passwords', methods=['POST'], endpoint='password.create', defaults={'user': None})
def create_password(user):
    if user is None:
        user = request.user
    request.authorize(Password, 'create', user)
    encode_type, encode = request.accept_encoder()
    user.add_password(request.content_source())
    return Response(status=201, response=encode({}), content_type=encode_type)


@app.route('/users/<User:user>/passwords', methods=['DELETE'], endpoint='password.delete')
@app.route('/passwords', methods=['DELETE'], endpoint='password.delete', defaults={'user': None})
def delete_password(user, password):
    if user is None:
        user = request.user
    request.authorize(password, 'delete', user)
    password.delete()
    return Response(status=204)


class Prisoner(Resource):

    _type_ = pilo.fields.String().constant('prisoner_t')

    link = Link('prisoner.show', prisoner='id')

    id = Id(prefix='pr-')

    user_link = Link('user.show', user='user.id')

    @property
    def user(self):
        return User(self.obj.user)

    started_at = pilo.fields.Datetime('created_at')

    updated_at = pilo.fields.Datetime('updated_at')

    expires_at = pilo.fields.Datetime()

    terminated_at = pilo.fields.Datetime()

    secret = pilo.fields.String(min_length=1)

    @secret.compute
    def secret(self):
        return ''.join(c if c in self.hits else 'x' for c in self.obj.secret)

    guess_link = Link('prisoner.guess', prisoner='id')

    guesses = pilo.fields.List(pilo.fields.String(length=1))

    hits = pilo.fields.List(pilo.fields.String(length=1))

    @hits.compute
    def hits(self):
        return [c for c in self.guesses if c in self.obj.secret]

    misses = pilo.fields.List(pilo.fields.String(length=1))

    @misses.compute
    def misses(self):
        return [c for c in self.guesses if c not in self.obj.secret]

    suicide_link = Link('prisoner.suicide', prisoner='id')

    states = Enum(
       ALIVE='alive',
       RESCUED='rescued',
       DEAD='dead',
    )

    state = pilo.fields.String(choices=states).translate({
        models.Prisoner.states.ALIVE: states.ALIVE,
        models.Prisoner.states.RESCUED: states.RESCUED,
        models.Prisoner.states.EXECUTED: states.DEAD,
        models.Prisoner.states.GAVE_UP: states.DEAD,
        models.Prisoner.states.EXPIRED: states.DEAD,
    })

    class Create(RequestForm):

        secret = pilo.fields.String(default=None)

        @secret.validate
        def secret(self, value):
            if not request.admin:
                self.ctx.errors.invalid('only allowed for admins')
                return False
            return True

    @classmethod
    def create(cls, source, user):
        form = cls.Create(source)
        obj = models.Prisoner.create(
            user=user.b.db.cast(user.obj),
            secret=form.secret,
        )
        models.db_session.commit()
        return cls(obj)

    class Guess(RequestForm):

        guess = pilo.fields.String(None, length=1)

    def guess(self, source):
        form = self.Guess(source)
        self.b.db.cast(self)
        hit = self.obj.guess(form.guess)
        models.db_session.commit()
        return hit

    def suicide(self):
        self.b.db.cast(self)
        self.obj.give_up()
        models.db_session.commit()


Prisoner.bind(
    CacheBinding(models.Prisoner.Cached),
    DBBinding(models.Prisoner),
)

@app.route('/users/<User:user>/prisoners/', methods=['GET'], endpoint='prisoner.index')
@app.route('/prisoners/', methods=['GET'], endpoint='prisoner.index', defaults={'user': None})
def index_prisoners(user):
    user = request.user if user is None else user
    request.authorize(Prisoner, 'index', user)
    encode_type, encode = request.accept_encoder()
    page = Prisoner.Index(request.content_source())(request.user.prisoner)
    return Response(status=200, response=encode(page), content_type=encode_type)


@app.route('/users/<User:user>/prisoners/', methods=['POST'], endpoint='prisoner.create')
@app.route('/prisoners/', methods=['POST'], endpoint='prisoner.create', defaults={'user': None})
def create_prisoner(user):
    user = request.user if user is None else user
    request.authorize(Prisoner, 'create', user)
    encode_type, encode = request.accept_encoder()
    prisoner = Prisoner.create(request.content_source(), user)
    return Response(status=200, response=encode(prisoner), content_type=encode_type)


@app.route('/prisoners/<Prisoner:prisoner>', methods=['GET'], endpoint='prisoner.show')
def show_prisoner(prisoner):
    request.authorize(prisoner, 'show')
    encode_type, encode = request.accept_encoder()
    return Response(status=200, response=encode(prisoner), content_type=encode_type)


@app.route('/prisoners/<Prisoner:prisoner>/guess', methods=['POST'], endpoint='prisoner.guess')
def guess_prisoner(prisoner):
    request.authorize(prisoner, 'guess')
    encode_type, encode = request.accept_encoder()
    hit = prisoner.guess(request.content_source())
    return Response(status=200, response=encode(hit), content_type=encode_type)


@app.route('/prisoners/<Prisoner:prisoner>/suicide', methods=['POST'], endpoint='prisoner.suicide')
def suicide_prisoner(prisoner):
    request.authorize(prisoner, 'suicide')
    prisoner.suicide()
    return Response(status=204)


class Stats(Resource):

    _type_ = pilo.fields.String().constant('stats_t')

    link = Link('stats.show', user='user.id')

    user_link = Link('user.show', id='user.id')

    @property
    def user(self):
        return User.get(User.id.encode(self.obj.user_id))

    prisoners = pilo.fields.Integer('total', min_value=0)

    rescued = pilo.fields.Integer(min_value=0)

    failed = pilo.fields.Integer(min_value=0)

    @failed.compute
    def failed(self):
        return self.obj.executed + self.obj.gave_up + self.obj.expired

    executed = pilo.fields.Integer(min_value=0)

    chickens = pilo.fields.Integer(min_value=0)

    @chickens.compute
    def chickens(self):
        return self.obj.gave_up + self.obj.expired

    hits = pilo.fields.Integer(min_value=0)

    misses = pilo.fields.Integer(min_value=0)

    total = pilo.fields.Integer(min_value=0)

    @total.compute
    def total(self):
        return self.hits + self.misses

    hit_rate = pilo.fields.Decimal(min_value=0, max_value=100, nullable=True)

    @hit_rate.compute
    def hit_rate(self):
        if not self.total:
            return
        return (self.obj.hits / float(self.total)) * 100.0


Stats.bind(CacheBinding(models.Stats))


@app.route('/users/<User:user>/stats', methods=['GET'], endpoint='stats.show')
@app.route('/stats', methods=['GET'], endpoint='stats.show', defaults={'user': None})
def show_stats(user):
    if user is None:
        user = request.user
    request.authorize(Stats, 'show', user)
    encode_type, encode = request.accept_encoder()
    stats = user.stats
    if stats is None:
        raise exc.ServiceUnavailable()
    return Response(status=200, response=encode(user.stats), content_type=encode_type)

from __future__ import unicode_literals, absolute_import

__all__ = [
    'init',
    'db_session',
    'cache_cli',
    'User',
    'Game',
    'Stats',
    'consumer',
]

import collections
import datetime
import functools
import hashlib
import logging
import random
import uuid

import pilo
import redis
import sqlalchemy as sa
import sqlalchemy.dialects.postgresql as pg
import sqlalchemy.event as saevent
import sqlalchemy.ext.declarative as sadecl
import sqlalchemy.ext.hybrid as sahybrid
import sqlalchemy.orm as saorm
import threading

from hags import config, codecs, mimes


logger = logging.getLogger(__name__)


def init(config):
    global db_engine, cache_cli, words

    db_engine = sa.create_engine(config.SQLA)
    db_metadata.bind = db_engine
    db_session.configure(bind=db_engine)
    cache_cli = redis.Redis(**config.REDIS)
    words = Words.load(**config.WORDS)


class Enum(list):

    def __init__(self, *args, **kwargs):
        for arg in args:
            kwargs[arg.upper()] = arg.lower()
        super(Enum, self).__init__(kwargs.values())
        for k, v in kwargs.iteritems():
            setattr(self, k, v)

# db

db_engine = None
db_metadata = sa.MetaData()
db_session = saorm.scoped_session(saorm.sessionmaker())


def db_session_teardown():
    try:
        db_session.rollback()
        db_session.expunge_all()
        db_session.remove()
    except sa.exc.InterfaceError, ex:
        if not ex.connection_invalidated:
            raise
        db_session.close()


class _DBModel(object):

    generate_id = staticmethod(uuid.uuid4)

DBModel = sadecl.declarative_base(cls=_DBModel)
DBModel.query = db_session.query_property()


class DBUUID(sa.TypeDecorator):

    impl = pg.UUID

    def process_bind_param(self, value, dialect=None):
        if isinstance(value, uuid.UUID):
            return str(value)
        return value

    def process_result_value(self, value, dialect=None):
        if value is not None:
            return uuid.UUID(value)
        return None


class DBEnum(list):

    def __init__(self, db_type):
        super(DBEnum, self).__init__(db_type.enums)
        for value in self:
            setattr(self, value.upper(), value)


# cache

cache_cli = None


class CacheStringModel(pilo.Form):

    mime = mimes.json

    @classmethod
    def get(cls, key):
        value = cache_cli.get(key)
        if value is None:
            return
        source = cls.mime.source(value)
        obj = cls(source)
        return obj

    @classmethod
    def delete(cls, key):
        cache_cli.delete(key)

    @property
    def key(self):
        raise NotImplementedError

    @property
    def ttl(self):
        return None

    def save(self):
        value = type(self).mime.encode(self)
        if self.ttl:
            cache_cli.setex(value, ttl=self.ttl)
        else:
            cache_cli.set(value)
        return self


class CacheHashModel(pilo.Form):

    mime = mimes.json

    @classmethod
    def get(cls, key):
        mapping = cache_cli.hgetall(key)
        if not mapping:
            return
        obj = cls(mapping)
        return obj

    @property
    def key(self):
        raise NotImplementedError

    def save(self):
        encode = type(self).mime.encode
        mapping = dict((k, v) for k, v in self.iteritems())
        cache_cli.hmset(self.key, mapping)
        return self

    def incr_by(self, field, value):
        if isinstance(field, pilo.fields.Integer):
            return cache_cli.hincrby(self.key, field.name, value)
        if isinstance(field, pilo.fields.Decimal):
            return cache_cli.hincrbyfloat(self.key, field.name, value)
        raise TypeError(
            '{0} is not pilo.fields.Integer or pilo.fields.Decimal'.
            format(field)
        )

    def decr_by(self, field, value):
        if isinstance(field, pilo.fields.Integer):
            cache_cli.hdecrby(self.key, field.name, value)
        if isinstance(field, pilo.fields.Integer):
            cache_cli.hdecrbyfloat(self.key, field.name, value)
        raise TypeError(
            '{0} is not pilo.fields.Integer or pilo.fields.Decimal'.
            format(field)
        )


# message


class MessageModel(pilo.Form):

    mime = mimes.json

    _type_ = pilo.fields.Type.abstract()

    channel = None

    def publish(self, q=None):
        if q:
            q.append(self)
            return
        encoded = self.mime.encode(self)
        cache_cli.publish(self.channel, encoded)

    subscribers = set()

    class Subscriber(collections.namedtuple(
              'Subscriber', ['channel', 'pattern', 'cls', 'func'],
          )):

        def handle(self, message):
            logger.debug('handling\n%s', message)
            try:
                src = self.cls.mime.source(message['data'])
            except (ValueError, TypeError) as ex:
                logger.warning(
                    '%s.mime cannot cannot source\n%s%s',
                    self.cls.__name__, message['data'], ex, exc_info=ex,
                )
                return
            try:
                msg_cls = self.cls._type_.cast(src)
            except (ValueError, TypeError) as ex:
                logger.warning(
                    '%s._type_ cannot cast\n%s%s',
                    self.cls.__name__, message['data'], ex, exc_info=ex
                )
                return
            try:
                msg = msg_cls(src)
            except (pilo.Invalid, pilo.Missing):
                logger.warning(
                    '%s._type_ cannot map\n%s%s',
                    msg_cls.__name__, message['data'], ex, exc_info=ex
                )
                return
            result = self.func(msg)
            return result

    @classmethod
    def subscribe(cls, channel=None, pattern=None):

        def _subscribe(func):
            cls.subscribers.add(cls.Subscriber(
                channel=channel, pattern=pattern, cls=cls, func=func,
            ))
            return func

        return _subscribe

    @classmethod
    def consumer(cls, *subscribers, **kwargs):
        if not subscribers:
            subscribers = cls.subscribers
        subscribers = list(subscribers)
        consumer = cache_cli.pubsub(**kwargs)
        channels = dict(
            (subscriber.channel, subscriber.handle)
            for subscriber in subscribers if subscriber.channel is not None
        )
        consumer.subscribe(**channels)
        patterns = dict(
            (subscriber.pattern, subscriber.handle)
            for subscriber in subscribers if subscriber.pattern is not None
        )
        consumer.psubscribe(**patterns)
        return consumer


class MessageQ(threading.local, collections.MutableSequence):

    def __init__(self):
        self.msgs = []

    def publish(self):
        count = 0
        while self:
            msg = self[0]
            msg.publish()
            self.pop(0)
            count += 1
        return count

    # collections.MutableSequence

    def __getitem__(self, index):
        return self.msgs.__getitem__(index)

    def __setitem__(self, index, value):
        return self.msgs.__setitem__(index, value)

    def __delitem__(self, index):
        return self.msgs.__delitem__(index)

    def __len__(self):
        return self.msgs.__len__()

    def insert(self, index, value):
        return self.msgs.insert(index, value)


class TransactionalMessageQ(MessageQ):

    def monitor(self):

        def _commit(session):
            self.publish()

        def _rollback(session, previous_transaction):
            del self[:]

        saevent.listen(db_session, 'after_commit', _commit, propagate=True)
        saevent.listen(db_session, 'after_soft_rollback', _rollback, propagate=True)
        return self

txnq = TransactionalMessageQ().monitor()


# domain

class Words(list):

    @classmethod
    def load(cls, url, encoding='utf-8'):
        import codecs

        return cls(
            line.strip()
            for line in codecs.open(url, encoding=encoding).readlines()
        )

words = None


class Change(MessageModel):

    @classmethod
    def monitor(cls, entity_cls):

        def _publish(op, mapper, cxn, entity):
            entity_cls.Change.create(entity=entity, op=op).publish()

        for event, op in [
                ('after_insert', cls.ops.CREATED),
                ('after_update', cls.ops.UPDATED),
                ('after_delete', cls.ops.DELETED),
            ]:
            saevent.listen(
                entity_cls,
                event,
                functools.partial(_publish, op),
                propagate=True
            )

    @classmethod
    def created(cls, entity):
        return cls.create(entity, cls.ops.CREATED).publish(txnq)

    @classmethod
    def updated(cls, entity):
        return cls.create(entity, cls.ops.UPDATED).publish(txnq)

    @classmethod
    def deleted(cls, entity):
        return cls.create(entity, cls.ops.DELETED).publish(txnq)

    @classmethod
    def create(cls, entity, op):
        return cls(entity=type(entity).__name__, op=op, id=entity.id)


    entity = pilo.fields.String()

    ops = Enum('CREATED', 'UPDATED', 'DELETED')

    op = pilo.fields.String(choices=ops)

    id = pilo.fields.UUID()

    def bust(self):
        raise NotImplementedError


@Change.subscribe(pattern='change.*')
def on_change(msg):
    msg.bust()


class User(DBModel):

    __table__ = sa.Table(
        'users',
        db_metadata,
        sa.Column('id', DBUUID, server_default=sa.text('uuid_generate_v4()'), primary_key=True),
        sa.Column('created_at', sa.DateTime, nullable=False, server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime, nullable=False, onupdate=sa.func.clock_timestamp(), server_default=sa.text('now()')),
        sa.Column('email_address', sa.Unicode, index=True, nullable=False, unique=True),
        sa.Column('enabled', sa.Boolean, default=True, server_default='t', nullable=False),
    )

    prisoners = saorm.relationship(
        'Prisoner', lazy='dynamic', backref=saorm.backref('user'), cascade='all, delete-orphan',
    )

    passwords = saorm.relationship(
        'Password', lazy='dynamic', backref=saorm.backref('user'), cascade='all, delete-orphan',
    )

    @property
    def stats(self):
        return Stats.get(self.id, create=True)

    @classmethod
    def create(cls, email_address, password, id=None):
        obj = cls(
            email_address=email_address,
	    password=password,
            id=id or cls.generate_id(),
        )
        db_session.add(obj)
        Stats.create(user=obj)
        return obj

    def authenticate(self, text):
        exists = (
            self.passwords
            .filter(Password.hashed == Password.hash(text))
        ).exists()
        return db_session.query(exists).scalar()

    def add_password(self, text):
        self.passwords.append(Password.create(text))

    def generate_password(self):
        text = Password.generate()
        self.passwords.append(Password.create(text))
        return text

    class Change(Change):

        channel = 'change.user'

        _type_ = pilo.fields.Type.instance('message_t.user_change.v1')

        def bust(self):
            User.Cached.delete(self.id)

    class Cached(CacheStringModel):

        _type_ = pilo.fields.Type.instance('prisoner_t.v1')

        id = pilo.fields.UUID()

        created_at = pilo.fields.Datetime(format='iso8601')

        updated_at = pilo.fields.Datetime(format='iso8601')

        email_address = pilo.fields.String()

        enabled = pilo.fields.Boolean()

        @classmethod
        def get(cls, id):
            return super(User.Cached, cls).get(cls.calculate_key(id))

        @classmethod
        def delete(cls, id):
            return super(User.Cached, cls).delete(cls.calculate_key(id))

        calculate_key = codecs.Id(prefix='us-', encoding='base58').encode

        @property
        def key(self):
            return self.calculate_key(self.id)

    def cache(self):
        return self.Cached(self).save()


Change.monitor(User)


class Password(DBModel):

    __table__ = sa.Table(
        'passwords',
        db_metadata,
        sa.Column('id', DBUUID, server_default=sa.text('uuid_generate_v4()'), primary_key=True),
        sa.Column('created_at', sa.DateTime, nullable=False, server_default=sa.text('now()')),
        sa.Column('user_id', DBUUID, sa.ForeignKey('users.id', ondelete='CASCADE'), index=True, nullable=False),
        sa.Column('hashed', sa.Unicode, index=True, nullable=False),
        sa.Column('enabled', sa.Boolean, default=True, server_default='t', nullable=False),
    )

    @classmethod
    def generate(cls):
        return uuid.uuid4().hex

    @classmethod
    def hash(cls,
             text,
             glue='$',
             version='1',
             method=hashlib.sha1,
             encoding='hex',
        ):
        hashed = method(text + config.PASSWORD_SALT)
        parts = [
            version,
            hashed.name,
            encoding,
            hashed.digest().encode(encoding)
        ]
        result = glue + glue.join(parts)
        if not isinstance(result, unicode):
            result = result.decode('utf-8')
        return result

    @classmethod
    def create(cls, text, user=None):
        obj = Password(
            hashed=cls.hash(text),
            user_id=user.id if user else None,
        )
        db_session.add(obj)
        return obj


PrisonerState = pg.ENUM(
    'ALIVE',
    'RESCUED',
    'EXECUTED',
    'EXPIRED',
    'GAVE_UP',
    name='perisoner_state',
    create_type=True,
)


class CannotGuess(Exception):

    def __init__(self, prisoner, guess):
        super(CannotGuess, self).__init__(
            'Cannot guess {0} prisoner {1} with state {2}'
            .format(guess, prisoner.id, prisoner.state)
        )
        self.prisoner = prisoner
        self.guess = guess


class CannotExpire(Exception):

    def __init__(self, prisoner):
        super(CannotGuess, self).__init__(
            'Cannot expire prisoner {0} with state {1}'
            .format(prisoner.id, prisoner.state)
        )
        self.prisoner = prisoner



class CannotRescue(Exception):

    def __init__(self, prisoner):
        super(CannotRescue, self).__init__(
            'Cannot rescue prisoner {0} with state {1}'
            .format(prisoner.id, prisoner.state)
        )
        self.prisoner = prisoner


class CannotExecute(Exception):

    def __init__(self, prisoner):
        super(CannotExecute, self).__init__(
            'Cannot expire prisoner {0} with state {1}'
            .format(prisoner.id, prisoner.state)
        )
        self.prisoner = prisoner


class CannotGiveUp(Exception):

    def __init__(self, prisoner):
        super(CannotGiveUp, self).__init__(
            'Cannot give up prisoner {0} with state {1}'
            .format(prisoner.id, prisoner.state)
        )
        self.prisoner = prisoner


class Prisoner(DBModel):

    __table__ = sa.Table(
        'prisoners',
        db_metadata,
        sa.Column('id', DBUUID, server_default=sa.text('uuid_generate_v4()'), primary_key=True),
        sa.Column('created_at', sa.DateTime, nullable=False, server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime, nullable=False, onupdate=sa.func.clock_timestamp(), server_default=sa.text('now()')),
        sa.Column('expires_at', sa.DateTime, nullable=False),
        sa.Column('terminated_at', sa.DateTime),
        sa.Column('user_id', DBUUID, sa.ForeignKey('users.id', ondelete='CASCADE'), index=True, nullable=False),
        sa.Column('state', PrisonerState, nullable=False, default='ALIVE', server_default='ALIVE', index=True),
        sa.Column('secret', sa.Unicode, nullable=False),
        sa.Column('misses', sa.Integer, server_default=sa.text('0'), default=0, nullable=False),
        sa.Column('guesses', pg.ARRAY(sa.Unicode), server_default=sa.text('array[]::varchar[]'), nullable=False),
    )

    states = DBEnum(PrisonerState)

    @sahybrid.hybrid_property
    def is_alive(self):
        return self.state == Prisoner.states.ALIVE

    @sahybrid.hybrid_property
    def is_rescued(self):
        return self.state == Prisoner.states.RESCUED

    @property
    def max_misses(self):
        return 5

    @classmethod
    def generate_secret(cls):
        return random.choice(words)

    @classmethod
    def create(cls, user, secret=None, id=None):
        expires_at = datetime.datetime.utcnow() + datetime.timedelta(hours=1)
        obj = cls(
            id=id or cls.generate_id(),
            secret=secret or cls.generate_secret(),
            user=user,
            expires_at=expires_at,
        )
        db_session.add(obj)
        cls.Create(user_id=obj.user.id, prisoner_id=obj.id).publish(txnq)
        return obj

    class Change(Change):

        channel = 'change.prisoner'

        _type_ = pilo.fields.Type.instance('message_t.prisoner_change.v1')

        def bust(self):
            Prisoner.Cached.delete(self.id)

    class Cached(CacheStringModel):

        _type_ = pilo.fields.Type.instance('prisoner_t.v1')

        id = pilo.fields.UUID()

        created_at = pilo.fields.Datetime(format='iso8601')

        updated_at = pilo.fields.Datetime(format='iso8601')

        expires_at = pilo.fields.Datetime(format='iso8601')

        termianted_at = pilo.fields.Datetime(format='iso8601', default=None)

        secret = pilo.fields.String()

        misses = pilo.fields.Integer(min_value=0, default=0)

        guesses = pilo.fields.List(pilo.fields.String())

        calculate_key = codecs.Id(prefix='pr-', encoding='base58').encode

        @classmethod
        def get(cls, id):
            return super(Prisoner.Cached, cls).get(cls.calculate_key(id))

        @classmethod
        def delete(cls, id):
            return super(Prisoner.Cached, cls).delete(cls.calculate_key(id))

        @property
        def key(self):
            return self.calculate_key(self.id)

    def cache(self):
        return self.Cached(self).save()

    class Create(MessageModel):

        channel = 'prisoner.create'

        _type_ = pilo.fields.Type.instance('message_t.prisoner_create.v1')

        user_id = pilo.fields.UUID()

        prisoner_id = pilo.fields.UUID()


    class Guess(MessageModel):

        channel = 'prisoner.guess'

        _type_ = pilo.fields.Type.instance('message_t.prisoner_guess.v1')

        user_id = pilo.fields.UUID()

        prisoner_id = pilo.fields.UUID()

        value = pilo.fields.String(length=1)

        hit = pilo.fields.Boolean()

    class Transition(MessageModel):

        channel = 'prisoner.transition'

        _type_ = pilo.fields.Type.instance('message_t.prisoner_transition.v1')

        user_id = pilo.fields.UUID()

        prisoner_id = pilo.fields.UUID()

        state = pilo.fields.String(choices=DBEnum(PrisonerState))

    def guess(self, value):
        hit = value in self.secret
        value_array = sa.cast([value], pg.ARRAY(sa.Unicode))
        values = {
            'guesses': Prisoner.guesses.op('||')(value_array),
        }
        if not hit:
            values['misses'] = Prisoner.misses + 1
        count = self._atom(
            Prisoner.is_alive,
            sa.not_(Prisoner.guesses.op('@>')(value_array)),
            Prisoner.misses < self.max_misses,
            **values
        )
        if count == 1:
            self.Guess(
                user_id=self.user.id,
                prisoner_id=self.id,
                value=value,
                hit=hit,
            ).publish(txnq)
            if len(set(self.secret) - set(self.guesses)) == 0:
                self.rescue()
            if not hit and self.misses >= self.max_misses:
                self.execute()
            return hit
        if value in self.guesses:
            return hit
        raise CannotGuess(self, value)

    def rescue(self):
        count = self._atom(
            Prisoner.is_alive,
            state=Prisoner.states.RESCUED,
        )
        if count == 1:
            return self
        if not self.is_rescued:
            raise CannotRescue(self)

    def execute(self):
        count = self._atom(
            Prisoner.is_alive,
            state=Prisoner.states.EXECUTED,
        )
        if count == 1:
            return self
        if not self.is_alive:
            raise CannotExecute(self)

    def expire(self):
        count = self._atom(
            Prisoner.is_alive,
            state=Prisoner.states.EXPIRED,
        )
        if count == 1:
            return self
        if not self.is_alive:
            raise CannotExpire(self)

    def give_up(self):
        count = self._atom(
            self.is_alive,
            state=Prisoner.states.GAVE_UP
        )
        if count == 1:
            return self
        if not self.is_alive:
            raise CannotGiveUp(self)

    def _atom(self, *filters, **values):
        if 'state' in values:
            values['terminated_at'] = sa.func.clock_timestamp()
        values['updated_at'] = sa.func.clock_timestamp()
        count = (
            Prisoner.query
            .filter(Prisoner.id == self.id, *filters)
            .update(values=values, synchronize_session='fetch')
        )
        if count == 1 and 'state' in values:
            self.Transition(
                user_id=self.user.id,
                prisoner_id=self.id,
                state=self.state,
            ).publish(txnq)
        return count


Change.monitor(Prisoner)

class Stats(CacheHashModel):

    _type_ = pilo.fields.Type.instance('stats_t.v1')

    user_id = pilo.fields.UUID()

    total = pilo.fields.Integer(default=0)

    hits = pilo.fields.Integer(default=0)

    misses = pilo.fields.Integer(default=0)

    rescued = pilo.fields.Integer(default=0)

    executed = pilo.fields.Integer(default=0)

    expired = pilo.fields.Integer(default=0)

    gave_up = pilo.fields.Integer(default=0)

    calculate_key = staticmethod(
        codecs.Id(prefix='ust-', encoding='base58').encode
    )

    @classmethod
    def create(cls, user):
        return cls(user_id=user.id).save()

    @classmethod
    def get(cls, user_id):
        return super(Stats, cls).get(cls.calculate_key(user_id))

    @property
    def key(self):
        return self.calculate_key(self.user_id)


@Prisoner.Create.subscribe('prisoner.create')
def on_prisoner_create(msg):
    Stats(user_id=msg.user_id).incr_by(Stats.total, 1)


@Prisoner.Transition.subscribe('prisoner.transition')
def on_prisoner_transition(msg):
    field = {
        Prisoner.states.RESCUED: Stats.rescued,
        Prisoner.states.EXECUTED: Stats.executed,
        Prisoner.states.EXPIRED: Stats.expired,
        Prisoner.states.GAVE_UP: Stats.gave_up,
    }.get(msg.state)
    if field is None:
        return
    Stats(user_id=msg.user_id).incr_by(field, 1)


@Prisoner.Guess.subscribe('prisoner.guess')
def on_prisoner_guess(msg):
    Stats(user_id=msg.user_id).incr_by(Stats.total, 1)
    if msg.hit:
        Stats(user_id=msg.user_id).incr_by(Stats.hits, 1)
    else:
        Stats(user_id=msg.user_id).incr_by(Stats.misses, 1)


Consumer = MessageModel.consumer

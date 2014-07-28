from __future__ import unicode_literals

import decimal
import random
import string
import threading
import uuid

import pytest
import werkzeug.serving

import hag
import hags


@pytest.fixture(scope='session', autouse=True)
def init():
    hags.init()
    hags.models.db_metadata.create_all()


@pytest.fixture(scope='session', autouse=True)
def example_server(init, request):
    server = werkzeug.serving.make_server(
        app=hags.api.app, host='127.0.0.1', port=0,
    )
    thd = threading.Thread(target=server.serve_forever)
    thd.start()
    request.addfinalizer(lambda: server.shutdown())
    return 'http://{0}:{1}'.format(*server.server_address)


@pytest.fixture(scope='session', autouse=True)
def example_consume(init, request):
    consumer = hags.models.Consumer()
    thd = consumer.run_in_thread()
    request.addfinalizer(lambda: thd.stop())
    return consumer


@pytest.fixture()
def user():
    user = hags.models.User.create(
        email_address='{0}@de.isthmus'.format(uuid.uuid4().hex)
    )
    hags.models.db_session.commit()
    return user


@pytest.fixture()
def password(user):
    text = user.generate_password()
    hags.models.db_session.commit()
    return text


@pytest.fixture()
def me(example_server, user, password):
    hag.configure(
        url=example_server,
        email_address=user.email_address,
        password=password
    )
    return hag.me()


class TestExample(object):

    def test_rescue(self, me):
        with hag.cli.use_headers((hags.config.API_HEADERS['admin'], hags.config.API_ADMIN)):
            prisoner = hag.Prisoner.create('peep')

        assert prisoner.state == prisoner.states.ALIVE
        assert prisoner.secret == 'xxxx'
        assert prisoner.hits == []
        assert prisoner.misses == []

        assert prisoner.guess('p')
        prisoner.refresh()
        assert prisoner.state == prisoner.states.ALIVE
        assert prisoner.secret == 'pxxp'
        assert prisoner.hits == ['p']
        assert prisoner.misses == []

        assert not prisoner.guess('m')
        prisoner.refresh()
        assert prisoner.state == prisoner.states.ALIVE
        assert prisoner.secret == 'pxxp'
        assert prisoner.hits == ['p']
        assert prisoner.misses == ['m']

        assert prisoner.guess('e')
        prisoner.refresh()
        assert prisoner.secret == 'peep'
        assert prisoner.hits == ['p', 'e']
        assert prisoner.misses == ['m']
        assert prisoner.state == prisoner.states.RESCUED

        with pytest.raises(hag.exc.Error):
            assert prisoner.guess('o')

        with pytest.raises(hag.exc.Error):
            assert prisoner.suicide()

    def test_suicide(self, me):
        prisoner = hag.Prisoner.create()
        assert prisoner.state == prisoner.states.ALIVE

        prisoner.suicide()
        prisoner.refresh()
        assert prisoner.state == prisoner.states.DEAD
        assert prisoner.hits == []
        assert prisoner.misses == []

        with pytest.raises(hag.exc.Error):
            assert prisoner.guess('o')

    def test_stats(self, me):
        with hag.cli.use_headers((hags.config.API_HEADERS['admin'], hags.config.API_ADMIN)):
            prisoner = hag.Prisoner.create('peep')
        prisoner.guess('p')
        prisoner.guess('e')

        with hag.cli.use_headers((hags.config.API_HEADERS['admin'], hags.config.API_ADMIN)):
            prisoner = hag.Prisoner.create('peep')
        alphabet = list(set(string.letters) - set('peep'))
        while prisoner.state == prisoner.states.ALIVE:
            prisoner.guess(random.choice(alphabet))
            prisoner.refresh()

        prisoner = hag.Prisoner.create()
        prisoner.suicide()

        stats = me.stats
        assert stats == {
            '_type_': 'stats_t',
            'chickens': 1,
            'failed': 2,
            'hit_rate': decimal.Decimal((stats['hits'] / float(stats['total'])) * 100),
            'hits': 2,
            'link': '/users/{0}/stats'.format(me.id),
            'misses': 5,
            'prisoners': 10,
            'rescued': 1,
            'total': 7
        }

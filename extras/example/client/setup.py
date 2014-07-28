import re
import setuptools


setuptools.setup(
    name='hag',
    version=(
        re
        .compile(r".*__version__ = '(.*?)'", re.S)
        .match(open('hag/__init__.py').read())
        .group(1)
    ),
    url='https://github.com/flask-hype/extras/example/',
    author='Franz Sanchez',
    author_email='banco@de.isthmus',
    description='Flask-hype example client',
    platforms='any',
    install_requires=[
        'iso8601 >=0.1.10,<0.2',
        'pilo >=0.3.2,<0.4',
        'requests >=2.3.0,<2.4',
    ],
    packages=setuptools.find_packages('.', exclude=('tests', 'tests.*')),
    classifiers=[
        'Development Status :: 4 - Beta',
        'Intended Audience :: Developers',
        'Natural Language :: English',
        'License :: OSI Approved :: ISC License (ISCL)',
        'Programming Language :: Python',
        'Programming Language :: Python :: 2.7',
    ],
    test_suite='nose.collector',
)

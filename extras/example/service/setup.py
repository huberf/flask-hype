import re
import setuptools


setuptools.setup(
    name='hags',
    version=(
        re
        .compile(r".*__version__ = '(.*?)'", re.S)
        .match(open('hags/__init__.py').read())
        .group(1)
    ),
    url='https://github.com/bninja/flask-type/extras/example/',
    author='Franz Sanchez',
    author_email='banco@de.isthmus',
    description='Flask-hype example service',
    platforms='any',
    install_requires=[
        'iso8601 >=0.1.10,<0.2',
        'psycopg2 >=2.5.2,<3.0',
        'SQLAlchemy >=0.9,<0.9.5',
        'redis >=2.9.1,<3.0',
        'pilo >=0.3.2,<0.4',
        'Flask >=0.10.1,<0.11',
        'flask-hype >=0.1,<0.2',
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
)

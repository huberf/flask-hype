import re
import setuptools


setuptools.setup(
    name='flask-hype',
    version=(
        re
        .compile(r".*__version__ = '(.*?)'", re.S)
        .match(open('flask_hype.py').read())
        .group(1)
    ),
    url='https://github.com/bninja/flask-hype',
    license='BSD',
    author='egon',
    author_email='egon@gb.com',
    description='Flask extension for hype',
    long_description=open('README.rst').read(),
    py_modules=['flask_hype'],
    zip_safe=False,
    include_package_data=True,
    platforms='any',
    install_requires=[
        'Flask >=0.10,<0.11',
        'pilo >=0.3,<0.4',
    ],
    extras_require={
        'test': [
            'pytest >=2.5.2,<3',
            'pytest-cov >=1.7,<2',
        ],
    },
    classifiers=[
        'Environment :: Web Environment',
        'Intended Audience :: Developers',
        'License :: OSI Approved :: BSD License',
        'Operating System :: OS Independent',
        'Programming Language :: Python',
        'Topic :: Internet :: WWW/HTTP :: Dynamic Content',
        'Topic :: Software Development :: Libraries :: Python Modules'
    ]
)
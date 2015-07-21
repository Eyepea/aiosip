#!/usr/bin/env python


try:
    from setuptools import setup
except ImportError:
    from distutils.core import setup


readme = open('README.rst').read()
history = open('HISTORY.rst').read().replace('.. :changelog:', '')

requirements = [
   'aiohttp'
]

test_requirements = [
    # TODO: put package test requirements here
]

setup(
    name='aiosip',
    version='0.1.0',
    description='SIP support for AsyncIO',
    long_description=readme + '\n\n' + history,
    author='Ludovic Gasc (GMLudo)',
    author_email='gmludo@gmail.com',
    url='https://github.com/Eyepea/aiosip',
    packages=[
        'aiosip',
    ],
    package_dir={'aiosip':
                 'aiosip'},
    include_package_data=True,
    install_requires=requirements,
    license="Apache 2",
    zip_safe=False,
    keywords=['asyncio', 'sip', 'telephony'],
    classifiers=[
        'Development Status :: 2 - Pre-Alpha',
        'Intended Audience :: Developers',
        'License :: OSI Approved :: BSD License',
        'Natural Language :: English',
        'Programming Language :: Python :: 3',
        'Programming Language :: Python :: 3.3',
        'Programming Language :: Python :: 3.4',
    ],
    test_suite='tests',
    tests_require=test_requirements
)

"""LombokSerde setup."""

from setuptools import setup, find_packages

setup(
    name='lombokserde',
    version='0.1.0',
    description='JSON, TOML, MessagePack serialization/deserialization — zero dependencies',
    author='codinglombok',
    author_email='codinglombok@gmail.com',
    url='https://github.com/codinglombok/LombokSerde',
    license='Apache-2.0',
    packages=find_packages(),
    python_requires='>=3.8',
    classifiers=[
        'Development Status :: 3 - Alpha',
        'Intended Audience :: Developers',
        'License :: OSI Approved :: Apache Software License',
        'Programming Language :: Python :: 3',
    ],
)

"""TOML serialization/deserialization."""

from .parser import parse
from .serializer import stringify

__all__ = ['parse', 'stringify']

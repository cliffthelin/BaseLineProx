"""Strict, bounded JSON-object request parsing for local web handlers."""
from __future__ import annotations

import json

MAX_JSON_BODY_BYTES=8*1024*1024


class JsonBodyError(ValueError):
    """The request body is not a bounded UTF-8 JSON object."""


def _reject_constant(value):
    raise ValueError(f'non-standard JSON constant {value}')


def _unique_object(pairs):
    result={}
    for key,value in pairs:
        if key in result:raise ValueError('duplicate JSON object key')
        result[key]=value
    return result


def read_json_object(headers, stream, *, max_bytes=MAX_JSON_BODY_BYTES):
    """Read exactly one bounded JSON object or raise without a default payload."""
    raw_length=headers.get('Content-Length')
    try:
        length=int(raw_length) if raw_length is not None else -1
    except (TypeError,ValueError) as exc:
        raise JsonBodyError('invalid Content-Length') from exc
    if length<1:
        raise JsonBodyError('JSON request body must not be empty and requires a valid Content-Length')
    if length>max_bytes:
        raise JsonBodyError(f'JSON request body exceeds {max_bytes} bytes')
    raw=stream.read(length)
    if len(raw)!=length:
        raise JsonBodyError('JSON request body ended before Content-Length bytes arrived')
    try:
        value=json.loads(raw.decode('utf-8'),parse_constant=_reject_constant,object_pairs_hook=_unique_object)
    except (UnicodeDecodeError,ValueError) as exc:
        raise JsonBodyError('malformed JSON request body') from exc
    if not isinstance(value,dict):
        raise JsonBodyError('JSON request body must be an object')
    return value

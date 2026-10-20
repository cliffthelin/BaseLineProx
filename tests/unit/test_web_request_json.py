import io
from email.message import Message

import pytest

from web_request_json import JsonBodyError, read_json_object


def _request(body):
    headers=Message();headers['Content-Length']=str(len(body))
    return read_json_object(headers,io.BytesIO(body))


def test_reads_a_utf8_json_object():
    assert _request('{"message":"héllo"}'.encode())=={'message':'héllo'}


@pytest.mark.parametrize('body',[b'',b'{broken',b'[]',b'null',b'\xff'])
def test_rejects_empty_malformed_non_object_and_non_utf8_documents(body):
    headers=Message();headers['Content-Length']=str(len(body))
    with pytest.raises(JsonBodyError):read_json_object(headers,io.BytesIO(body))


def test_rejects_oversized_body_before_reading_it():
    class Unreadable:
        def read(self,_length):raise AssertionError('oversized body should not be read')
    headers=Message();headers['Content-Length']='8388609'
    with pytest.raises(JsonBodyError,match='exceeds'):
        read_json_object(headers,Unreadable())


def test_rejects_invalid_content_length():
    headers=Message();headers['Content-Length']='-1'
    with pytest.raises(JsonBodyError,match='Content-Length'):
        read_json_object(headers,io.BytesIO(b''))


@pytest.mark.parametrize('body',[b'{"action":"view","action":"delete"}',b'{"value":NaN}'])
def test_rejects_duplicate_keys_and_nonstandard_numbers(body):
    headers=Message();headers['Content-Length']=str(len(body))
    with pytest.raises(JsonBodyError):read_json_object(headers,io.BytesIO(body))

"""Import a local session without executing pickle globals or exposing cookies."""
import io
import base64
import json
import os
from pathlib import Path
import pickle
import re
import uuid


class CookieUnpickler(pickle.Unpickler):
    def find_class(self, module, name):
        raise ValueError('Session file contains unsupported objects')


def decode_cookies(content):
    if len(content)>1024*1024:
        raise ValueError('Session file exceeds size limit')
    try:
        data=json.loads(content)
    except (ValueError,UnicodeError):
        data=CookieUnpickler(io.BytesIO(content)).load()
    if not isinstance(data,dict) or not data.get('sessionid') or not data.get('csrftoken') or any(
        not isinstance(k,str) or not isinstance(v,str) for k,v in data.items()):
        raise ValueError('Expected an Instaloader cookie session')
    return data


def read_cookies(path):
    with Path(path).expanduser().open('rb') as handle:
        return decode_cookies(handle.read(1024*1024+1))


def import_session(directory, username, path):
    if not isinstance(username,str) or not re.fullmatch(r'[A-Za-z0-9_.]{1,30}',username):
        raise ValueError('Enter a valid Instagram username')
    try:
        cookies=read_cookies(path)
    except Exception:
        raise ValueError('Could not read a valid local Instaloader session file') from None
    directory=Path(directory)
    directory.mkdir(parents=True,exist_ok=True,mode=0o700)
    destination=directory/(uuid.uuid4().hex+'.json')
    fd=os.open(destination,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
    with os.fdopen(fd,'w',encoding='utf-8') as handle:
        json.dump(cookies,handle)
    return {'username':username,'session_file':str(destination.resolve())}


def import_session_data(directory, username, encoded):
    if not isinstance(encoded,str) or len(encoded)>1400000:
        raise ValueError('Choose an Instaloader session file up to 1 MB')
    try:
        content=base64.b64decode(encoded,validate=True)
        cookies=decode_cookies(content)
    except Exception:
        raise ValueError('Could not read a valid local Instaloader session file') from None
    if not isinstance(username,str) or not re.fullmatch(r'[A-Za-z0-9_.]{1,30}',username):
        raise ValueError('Enter a valid Instagram username')
    directory=Path(directory)
    directory.mkdir(parents=True,exist_ok=True,mode=0o700)
    destination=directory/(uuid.uuid4().hex+'.json')
    fd=os.open(destination,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
    with os.fdopen(fd,'w',encoding='utf-8') as handle:
        json.dump(cookies,handle)
    return {'username':username,'session_file':str(destination.resolve())}

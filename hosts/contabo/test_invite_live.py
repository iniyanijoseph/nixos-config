"""Run only against the disposable Synapse VM, never the production host."""
import hashlib
import hmac
import importlib.util
import json
from pathlib import Path
import sys
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlsplit

spec = importlib.util.spec_from_file_location('admin', sys.argv[1])
c = importlib.util.module_from_spec(spec); spec.loader.exec_module(c)
nonce = c.api('/_synapse/admin/v1/register')['nonce']
password = 'disposable-vm-password'
mac = hmac.new(b'vm-fixture-only', '\0'.join([nonce, 'owner', password, 'admin']).encode(), hashlib.sha1).hexdigest()
owner = c.api('/_synapse/admin/v1/register', body={'nonce': nonce, 'username': 'owner', 'password': password, 'admin': True, 'mac': mac})
token = owner['access_token']
url, _ = c.invite(token=token)
invitation = parse_qs(urlsplit(url).fragment)['token'][0]


def request_registration(username, auth=None):
    try:
        return 200, c.api('/_matrix/client/v3/register', body={
            'username': username, 'password': 'a-private-friend-password', 'inhibit_login': True,
            **({'auth': auth} if auth else {})})
    except HTTPError as error:
        return error.code, json.load(error)


status, challenge = request_registration('friend')
assert status == 401 and all('m.login.registration_token' in flow['stages'] for flow in challenge['flows'])
session = challenge['session']
status, result = request_registration('friend', {'type': 'm.login.registration_token', 'token': invitation, 'session': session})
if status == 401:
    assert 'm.login.registration_token' in result['completed']
    status, result = request_registration('friend', {'type': 'm.login.dummy', 'session': session})
assert status == 200 and result['user_id'] == '@friend:iniyanjoseph.com', (status, result)
assert c.api('/_synapse/admin/v1/users/%40friend%3Ainiyanjoseph.com/admin', token)['admin'] is False
status, challenge = request_registration('anotherfriend')
assert status == 401
status, denied = request_registration('anotherfriend', {'type': 'm.login.registration_token', 'token': invitation, 'session': challenge['session']})
assert status != 200, 'single-use token was reused'
state = c.api('/_synapse/admin/v1/registration_tokens/' + invitation, token)
assert state['completed'] == 1 and state['uses_allowed'] == 1
assert not Path('/var/lib/contabo-admin/admin-session.json').exists(), 'fixture leaked an admin session to persistent storage'
print('Live Synapse invitation passed: token required, one account created, no administrator grant, reuse rejected.')

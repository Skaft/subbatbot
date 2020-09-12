"""
oAuth process:
    - auth_link() to make a link where logged in user can authorize the app
    - user goes and accepts, copy code from redirected url
    - pass code to get_new_bearer(code)

"""

import os
import requests
from globals import *
import logging
from functools import lru_cache


TWITCH_AUTH_URL = "https://id.twitch.tv/oauth2/authorize"
TWITCH_TOKEN_URL = "https://id.twitch.tv/oauth2/token"
TWITCH_REFRESH_URL = "https://id.twitch.tv/oauth2/token"
REDIRECT_URI = "https://localhost"
TOKEN = None
log = logging.getLogger(__name__)


def auth_link(scope="user:edit:follows"):
    params = {
        'client_id': os.environ['CLIENT_ID'],
        'scope': scope,
        'response_type': 'code',
        'redirect_uri': REDIRECT_URI
    }
    req = requests.Request('GET', TWITCH_AUTH_URL, params=params)
    prep = req.prepare()
    return prep.url


def get_new_bearer(code, db=None):
    global TOKEN
    # After user accepted on auth_link, pass the generated code here
    params = {
        'client_id': os.environ['CLIENT_ID'],
        'client_secret': os.environ['CLIENT_SECRET'],
        'code': code,
        'grant_type': 'authorization_code',
        'redirect_uri': REDIRECT_URI
    }
    TOKEN = requests.post(TWITCH_TOKEN_URL, params=params).json()
    if db:
        db.update_token(TOKEN)
    return TOKEN


def refresh_token(db=None):
    params = {
        'client_id': os.environ['CLIENT_ID'],
        'client_secret': os.environ['CLIENT_SECRET'],
        'grant_type': 'refresh_token',
        'refresh_token': TOKEN['refresh_token'],
    }
    new_token = requests.post(TWITCH_REFRESH_URL, params=params).json()
    log.debug(f"Refreshed token from {TOKEN['access_token'][:5]} to {new_token['refresh_token'][:5]}")
    TOKEN.update(new_token)
    if db:
        db.update_token(TOKEN)
    return TOKEN


def get_bearer_token(db):
    global TOKEN
    if TOKEN is None:
        TOKEN = db.get_token()
    log.debug(f"Fetched token: {TOKEN['access_token'][:5]}")
    return TOKEN


def add_follow(user_id=None, username=None, db=None):
    if username:
        user_id = get_user_id(username, db=db)
    elif user_id is None:
        raise ValueError("No user to follow")
    if os.environ['BOT_NICK'].lower() == 'sbbdev':
        from_id = str(SBBD_ID)
    else:
        from_id = str(SBB_ID)
    log.debug(f"Requesting follow to name={username}, id={user_id}")
    url = 'https://api.twitch.tv/helix/users/follows'
    make_private_req(url, method='post', db=db, login=username, from_id=from_id, to_id=str(user_id))


def get_user_id(username, db=None):
    log.debug(f"Looking up ID for user {username}")
    url = f"https://api.twitch.tv/helix/users"
    d = make_private_req(url, db=db, json=True, login=username)
    return int(d['data'][0]['id'])


def make_private_req(url, method='get', attempts=0, db=None, json=False, **params):
    token = get_bearer_token(db)
    headers = {
        'client-id': os.environ['CLIENT_ID'],
        'Authorization': f"Bearer {token['access_token']}",
    }
    function = getattr(requests, method)
    resp = function(url, headers=headers, params=params)
    if resp.status_code == 401:
        if attempts == 1:
            log.error(f"Unauthorized even after refresh! {url}, {params}, token {token['access_token'][:5]}")
            return
        log.info(f"Token {token['access_token'][:5]} looks invalid")
        refresh_token(db)
        return make_private_req(url, method=method, attempts=1, db=db, **params)
    resp.raise_for_status()
    if json:
        return resp.json()


@lru_cache()
def get_moderated_channels(user):
    print('looking up', user)
    url = f"https://modlookup.3v.fi/api/user-v3/{user}"
    r = requests.get(url, timeout=4)
    if r.status_code == 200:
        dct = r.json()
        return {ch['name'] for ch in dct['channels']}
    log.error(f"Mod lookup failed with status {r.status_code} for user {user}")



if __name__ == '__main__':
    pass
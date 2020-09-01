"""
oAuth process:
    - auth_link() to make a link where logged in user can authorize the app
    - user goes and accepts, copy code from redirected url
    - pass code to get_new_bearer(code)

"""

import os
import requests
from globals import *


TWITCH_AUTH_URL = "https://id.twitch.tv/oauth2/authorize"
TWITCH_TOKEN_URL = "https://id.twitch.tv/oauth2/token"
TWITCH_REFRESH_URL = "https://id.twitch.tv/oauth2/token"
REDIRECT_URI = "https://localhost"
TOKEN = None


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
    TOKEN.update(new_token)
    if db:
        db.update_token(TOKEN)
    return TOKEN


def get_bearer_token(db):
    global TOKEN
    if TOKEN is None:
        TOKEN = db.get_token()
    return TOKEN


def add_follow(user_id=None, username=None):
    if username:
        user_id = get_user_id(username)
    elif user_id is None:
        raise ValueError("No user to follow")
    if os.environ['BOT_NICK'].lower() == 'sbbdev':
        from_id = str(SBBD_ID)
    else:
        from_id = str(SBB_ID)
    url = 'https://api.twitch.tv/helix/users/follows'
    make_private_req(url, method='post', login=username, from_id=from_id, to_id=str(user_id))


def get_user_id(username):
    url = f"https://api.twitch.tv/helix/users"
    d = make_private_req(url, login=username)
    return int(d['data'][0]['id'])


def make_private_req(url, method='get', attempts=0, **params):
    token = get_bearer_token()
    headers = {
        'client-id': os.environ['CLIENT_ID'],
        'Authorization': f"Bearer {token['access_token']}",
    }
    function = getattr(requests, method)
    resp = function(url, headers=headers, params=params)
    if resp.status_code == 401:
        if attempts == 1:
            print(f"Unauthorized even after refresh! {url}, {params}")
            return
        print('Unauthorized, refreshing token')
        refresh_token()
        return make_private_req(url, method=method, attempts=1, **params)
    resp.raise_for_status()
    return resp.json()

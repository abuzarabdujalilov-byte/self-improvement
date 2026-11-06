"""Google sign-in. Lucid does not accept a shared Gemini key here."""

from __future__ import annotations

import json
import urllib.parse
import urllib.request

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
USERINFO_URL = "https://www.googleapis.com/oauth2/v2/userinfo"


def authorization_url(*, client_id: str, redirect_uri: str, state: str) -> str:
    query = urllib.parse.urlencode(
        {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": "openid email profile",
            "state": state,
            "prompt": "select_account",
        }
    )
    return f"{AUTH_URL}?{query}"


def fetch_profile(*, client_id: str, client_secret: str, redirect_uri: str, code: str, opener=None) -> dict:
    open_request = opener or urllib.request.urlopen
    form = urllib.parse.urlencode(
        {
            "code": code,
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
        }
    ).encode()
    token_request = urllib.request.Request(TOKEN_URL, data=form, method="POST")
    with open_request(token_request, timeout=20) as response:
        token = json.loads(response.read().decode())
    access = token.get("access_token")
    if not access:
        raise RuntimeError("Google did not return an access token.")
    profile_request = urllib.request.Request(
        USERINFO_URL,
        headers={"Authorization": f"Bearer {access}"},
    )
    with open_request(profile_request, timeout=20) as response:
        profile = json.loads(response.read().decode())
    if not profile.get("id"):
        raise RuntimeError("Google did not return an account id.")
    return profile

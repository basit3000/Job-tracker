"""Fictional Google transport with real RSA-signed test tokens."""

import base64
import hashlib
import json
import time
from urllib.parse import parse_qs

import pytest
from joserfc import jwt
from joserfc.jwk import RSAKey
from requests import Response, Session, Timeout

BASE_URL = "http://localhost:5000"
GOOGLE_CONFIG = {
    "GOOGLE_CLIENT_ID": "fictional-client-id",
    "GOOGLE_CLIENT_SECRET": "fictional-client-secret",
    "GOOGLE_REDIRECT_URI": BASE_URL + "/auth/google/callback",
}
METADATA_URL = "https://accounts.google.com/.well-known/openid-configuration"
TOKEN_URL = "https://oauth2.googleapis.com/token"
KEYS_URL = "https://www.googleapis.com/oauth2/v3/certs"


class FictionalGoogle:
    def __init__(self):
        self.key = RSAKey.generate_key(parameters={"kid": "fictional-key"})
        self.codes = {}
        self.challenges = {}
        self.issued_codes = 0
        self.token_calls = 0
        self.unavailable = False
        self.redirect_uri = GOOGLE_CONFIG["GOOGLE_REDIRECT_URI"]

    def request(self, method, url, **kwargs):
        assert kwargs.get("timeout") == 10
        if self.unavailable:
            raise Timeout("Do not expose fictional provider details.")
        if url == METADATA_URL:
            assert method == "GET"
            payload = {
                "issuer": "https://accounts.google.com",
                "authorization_endpoint": "https://accounts.google.com/o/oauth2/v2/auth",
                "token_endpoint": TOKEN_URL,
                "jwks_uri": KEYS_URL,
                "id_token_signing_alg_values_supported": ["RS256"],
            }
        elif url == KEYS_URL:
            assert method == "GET"
            payload = {"keys": [self.key.as_dict()]}
        elif url == TOKEN_URL:
            assert method == "POST"
            self.token_calls += 1
            data = kwargs["data"]
            if isinstance(data, str):
                data = {key: value[0] for key, value in parse_qs(data).items()}
            code = data["code"]
            assert len(data["code_verifier"]) >= 43
            challenge = (
                base64.urlsafe_b64encode(
                    hashlib.sha256(data["code_verifier"].encode()).digest()
                )
                .decode()
                .rstrip("=")
            )
            assert challenge == self.challenges.pop(code)
            assert data["redirect_uri"] == self.redirect_uri
            payload = self.codes.pop(code)
        else:
            pytest.fail(
                "Unexpected network request during fictional OAuth test."
            )
        response = Response()
        response.status_code = 200
        response.url = url
        response.headers["Content-Type"] = "application/json"
        response._content = json.dumps(payload).encode()
        return response

    def issue(self, requested_nonce, *, code_challenge, **changes):
        now = int(time.time())
        claims = {
            "iss": "https://accounts.google.com",
            "aud": "fictional-client-id",
            "sub": "fictional-google-subject",
            "iat": now,
            "exp": now + 300,
            "nonce": requested_nonce,
            "email": "google-user@example.com",
            "email_verified": True,
        }
        bad_signature = changes.pop("bad_signature", False)
        omit_id_token = changes.pop("omit_id_token", False)
        claims.update(changes)
        key = (
            RSAKey.generate_key(parameters={"kid": "fictional-key"})
            if bad_signature
            else self.key
        )
        token = {
            "access_token": "fictional-access-token",
            "token_type": "Bearer",
            "id_token": jwt.encode(
                {"alg": "RS256", "kid": "fictional-key"}, claims, key
            ),
        }
        if omit_id_token:
            token.pop("id_token")
        self.issued_codes += 1
        code = "fictional-code-" + str(self.issued_codes)
        self.codes[code] = token
        self.challenges[code] = code_challenge
        return code


def mock_google_transport(monkeypatch):
    provider = FictionalGoogle()
    monkeypatch.setattr(
        Session,
        "request",
        lambda session, method, url, **kwargs: provider.request(
            method, url, **kwargs
        ),
    )
    return provider

"""
WebSocket $connect REQUEST authorizer.
Reads the JWT from the Sec-WebSocket-Protocol header (sent as
'bearer.<token>' by the frontend) or the Authorization header,
validates it, and returns an IAM Allow/Deny policy.
"""

import os
import json
import time
import base64
import urllib.request

REGION = os.environ.get("REGION", "us-east-1")
USER_POOL_ID = os.environ.get("USER_POOL_ID", "")

try:
    import jwt as pyjwt  # type: ignore
    _HAS_PYJWT = True
except ImportError:
    pyjwt = None
    _HAS_PYJWT = False

_JWKS_CACHE = {}
_JWKS_TTL_SECONDS = 300


def _b64url_decode(segment):
    padding = "=" * (-len(segment) % 4)
    return base64.urlsafe_b64decode(segment + padding)


def _jwks_url():
    return (
        "https://cognito-idp.{region}.amazonaws.com/"
        "{pool}/.well-known/jwks.json"
    ).format(region=REGION, pool=USER_POOL_ID)


def _fetch_jwks():
    req = urllib.request.Request(_jwks_url(), headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=5) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    now = int(time.time())
    for key in data.get("keys", []):
        kid = key.get("kid")
        if kid:
            _JWKS_CACHE[kid] = {"key": key, "fetched_at": now}


def get_signing_key(kid):
    now = int(time.time())
    cached = _JWKS_CACHE.get(kid)
    if cached and (now - cached["fetched_at"]) < _JWKS_TTL_SECONDS:
        return cached["key"]
    _fetch_jwks()
    cached = _JWKS_CACHE.get(kid)
    return cached["key"] if cached else None


def _generate_policy(principal_id, effect, resource, context=None):
    policy = {
        "principalId": principal_id or "unknown",
        "policyDocument": {
            "Version": "2012-10-17",
            "Statement": [{"Action": "execute-api:Invoke", "Effect": effect, "Resource": resource}],
        },
    }
    if context:
        policy["context"] = {k: v for k, v in context.items() if v is not None}
    return policy


def _deny(resource):
    return _generate_policy("unauthorized", "Deny", resource)


def _extract_token(event):
    """
    Extract JWT from WebSocket connect request.
    Browser sends: Sec-WebSocket-Protocol: bearer.<token>
    API Gateway surfaces this as headers['Sec-WebSocket-Protocol'].
    Fall back to Authorization header if present.
    """
    headers = event.get("headers") or {}
    # Case-insensitive header lookup
    headers_lower = {k.lower(): v for k, v in headers.items()}

    proto = headers_lower.get("sec-websocket-protocol", "")
    if proto.lower().startswith("bearer."):
        return proto[7:].strip()

    auth = headers_lower.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()

    # Also check queryStringParameters for ?token=<jwt>
    qs = event.get("queryStringParameters") or {}
    token = qs.get("token", "")
    if token:
        return token.strip()

    return ""


def handler(event, context):
    method_arn = event.get("methodArn", "*")

    try:
        token = _extract_token(event)
        if not token:
            print("WsAuthorizer: token missing")
            return _deny(method_arn)

        # Decode header to get kid
        try:
            parts = token.split(".")
            if len(parts) != 3:
                raise ValueError("Malformed JWT")
            header = json.loads(_b64url_decode(parts[0]).decode("utf-8"))
            claims = json.loads(_b64url_decode(parts[1]).decode("utf-8"))
        except Exception as exc:
            print("WsAuthorizer: JWT decode failed: %s" % exc)
            return _deny(method_arn)

        kid = header.get("kid")

        if _HAS_PYJWT and kid:
            try:
                jwk = get_signing_key(kid)
                if jwk is None:
                    print("WsAuthorizer: no matching JWKS key for kid=%s" % kid)
                    return _deny(method_arn)
                public_key = pyjwt.algorithms.RSAAlgorithm.from_jwk(json.dumps(jwk))
                claims = pyjwt.decode(
                    token, public_key, algorithms=["RS256"], options={"verify_aud": False}
                )
            except Exception as exc:
                print("WsAuthorizer: signature verification failed: %s" % exc)
                return _deny(method_arn)
        else:
            exp = claims.get("exp")
            if exp is not None and int(time.time()) >= int(exp):
                print("WsAuthorizer: token expired")
                return _deny(method_arn)

        sub = claims.get("sub")
        if not sub:
            print("WsAuthorizer: no sub claim")
            return _deny(method_arn)

        ctx = {"userId": sub}
        if claims.get("email"):
            ctx["email"] = claims["email"]

        base_arn = method_arn.rsplit("/", 3)[0]
        return _generate_policy(sub, "Allow", base_arn + "/*", ctx)

    except Exception as exc:
        print("WsAuthorizer: unexpected error: %s" % exc)
        return _deny(method_arn)

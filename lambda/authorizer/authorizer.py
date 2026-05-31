"""
JWT Token Authorizer for API Gateway.

Verifies a Cognito-issued JWT and returns an IAM policy that either Allows or
Denies the request. On any failure the function returns a Deny policy and never
raises, so API Gateway always receives a well-formed response.

Only stdlib + boto3 are guaranteed to be present in the Lambda runtime. PyJWT is
attempted as an optional import; when it is unavailable we fall back to an
unverified decode of the JWT payload (acceptable for lab purposes only).
"""

import os
import json
import time
import base64
import urllib.request
import urllib.error

REGION = os.environ.get("REGION", "us-east-1")
USER_POOL_ID = os.environ.get("USER_POOL_ID", "")

# Optional PyJWT - not present in the default Lambda runtime.
try:
    import jwt as pyjwt  # type: ignore
    _HAS_PYJWT = True
except ImportError:  # pragma: no cover - depends on layer availability
    pyjwt = None
    _HAS_PYJWT = False

# Module-level JWKS cache: {kid: {"key": <jwk dict>, "fetched_at": <epoch>}}
_JWKS_CACHE = {}
_JWKS_TTL_SECONDS = 300


def _jwks_url():
    return (
        "https://cognito-idp.{region}.amazonaws.com/"
        "{pool}/.well-known/jwks.json"
    ).format(region=REGION, pool=USER_POOL_ID)


def _b64url_decode(segment):
    """Decode a base64url string, adding any missing padding."""
    padding = "=" * (-len(segment) % 4)
    return base64.urlsafe_b64decode(segment + padding)


def decode_jwt_header(token):
    """Return the decoded JWT header dict (no verification)."""
    parts = token.split(".")
    if len(parts) != 3:
        raise ValueError("Malformed JWT: expected 3 segments")
    return json.loads(_b64url_decode(parts[0]).decode("utf-8"))


def decode_jwt_payload(token):
    """Return the decoded JWT payload/claims dict (no verification)."""
    parts = token.split(".")
    if len(parts) != 3:
        raise ValueError("Malformed JWT: expected 3 segments")
    return json.loads(_b64url_decode(parts[1]).decode("utf-8"))


def _fetch_jwks():
    """Fetch the full JWKS document from Cognito and refresh the cache."""
    req = urllib.request.Request(
        _jwks_url(), headers={"Accept": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=5) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    now = int(time.time())
    for key in data.get("keys", []):
        kid = key.get("kid")
        if kid:
            _JWKS_CACHE[kid] = {"key": key, "fetched_at": now}
    return data


def get_signing_key(kid):
    """
    Return the JWK dict matching kid, using the cache when fresh and
    re-fetching from Cognito otherwise. Returns None if not found.
    """
    now = int(time.time())
    cached = _JWKS_CACHE.get(kid)
    if cached and (now - cached["fetched_at"]) < _JWKS_TTL_SECONDS:
        return cached["key"]

    # Cache miss or stale - refresh from Cognito.
    _fetch_jwks()
    cached = _JWKS_CACHE.get(kid)
    if cached:
        return cached["key"]
    return None


def _verify_with_pyjwt(token, jwk):
    """
    Verify the JWT signature with PyJWT using the JWK public key.
    Returns the verified claims dict. Raises on any verification failure.
    """
    public_key = pyjwt.algorithms.RSAAlgorithm.from_jwk(json.dumps(jwk))
    return pyjwt.decode(
        token,
        public_key,
        algorithms=["RS256"],
        options={"verify_aud": False},
    )


def _generate_policy(principal_id, effect, resource, context=None):
    """Build an API Gateway IAM policy document."""
    policy = {
        "principalId": principal_id or "unknown",
        "policyDocument": {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Action": "execute-api:Invoke",
                    "Effect": effect,
                    "Resource": resource,
                }
            ],
        },
    }
    if context:
        # API Gateway context values must be strings/numbers/bools.
        policy["context"] = {k: v for k, v in context.items() if v is not None}
    return policy


def _deny(resource):
    return _generate_policy("unauthorized", "Deny", resource)


def handler(event, context):
    method_arn = event.get("methodArn", "*")

    try:
        token = event.get("authorizationToken", "") or ""
        if token.lower().startswith("bearer "):
            token = token[7:].strip()

        if not token:
            print("Authorizer: token missing")
            return _deny(method_arn)

        # Read kid from the header to select the correct signing key.
        try:
            header = decode_jwt_header(token)
        except Exception as exc:  # malformed token
            print("Authorizer: failed to decode header: %s" % exc)
            return _deny(method_arn)

        kid = header.get("kid")

        claims = None
        if _HAS_PYJWT and kid:
            try:
                jwk = get_signing_key(kid)
                if jwk is None:
                    print("Authorizer: no matching JWKS key for kid=%s" % kid)
                    return _deny(method_arn)
                claims = _verify_with_pyjwt(token, jwk)
            except Exception as exc:
                # Covers expired token, invalid signature, JWKS issues.
                print("Authorizer: signature verification failed: %s" % exc)
                return _deny(method_arn)
        else:
            # Fallback: decode payload without signature verification.
            # Lab-only path - validate exp manually so expired tokens are denied.
            try:
                claims = decode_jwt_payload(token)
            except Exception as exc:
                print("Authorizer: failed to decode payload: %s" % exc)
                return _deny(method_arn)

            exp = claims.get("exp")
            if exp is not None and int(time.time()) >= int(exp):
                print("Authorizer: token expired (fallback path)")
                return _deny(method_arn)

        sub = claims.get("sub")
        if not sub:
            print("Authorizer: no sub claim present")
            return _deny(method_arn)

        ctx = {"userId": sub}
        if claims.get("email"):
            ctx["email"] = claims["email"]

        base_arn = method_arn.rsplit("/", 3)[0]
        return _generate_policy(sub, "Allow", base_arn + "/*", ctx)

    except Exception as exc:  # absolute safety net - never raise
        print("Authorizer: unexpected error: %s" % exc)
        return _deny(method_arn)

"""A JupyterHub Authenticator that logs users in via a short-lived, single-use signed
JWT passed in a url param, instead of a username/password form.

Configuration Example:
    c.JupyterHub.authenticator_class = "jwt_authenticator.JWTAuthenticator"

    c.JWTAuthenticator.username_claim_field = "platformname"
    c.JWTAuthenticator.admin_claim_field = "assistant_or_owner"
    c.JWTAuthenticator.course_claim_field = "course_id"
    c.JWTAuthenticator.expected_course_id = "6aad51577690f9d7c0766519"
    c.JWTAuthenticator.jwt_key_algorithm = "RS256"

    # Public key to verify tokens
    with open("/etc/jupyterhub/jwt_public_key.pem") as f:
        c.JWTAuthenticator.jwt_public_key = f.read()

    c.Authenticator.allow_all = True
"""

import time

import jwt
from jupyterhub.auth import Authenticator
from jupyterhub.handlers import BaseHandler
from jwt import PyJWTError
from traitlets import Unicode

NOT_SIGNED_IN_MESSAGE = (
    "Instead of directly visiting JupyterHub, please use the sign-in "
    "link which was emailed to you or log in through the main application portal."
)
EXPIRED_OR_INVALID_MESSAGE = (
    "Your sign-in token has expired or is invalid, or you're not "
    "permitted to access this course. Please re-authenticate through the portal."
)


class JWTLoginHandler(BaseHandler):
    """Replaces default login page. Reads the JWT from the URL query parameter 'token'."""

    async def get(self):
        token = self.get_argument("token", None)

        if not token:
            user = self.current_user
            if user:
                # Already signed in, so there's nothing to log in to
                self.redirect(self.get_next_url(user))
                return
            self.log.warning("JWTAuthenticator: no token query param present")
            await self._show_error(NOT_SIGNED_IN_MESSAGE)
            return

        user = await self.login_user({"token": token})
        if user is None:
            await self._show_error(EXPIRED_OR_INVALID_MESSAGE)
            return

        self.redirect(self.get_next_url(user))

    async def _show_error(self, message):
        html = await self.render_template(
            "error.html",
            status_code=403,
            status_message="Sign-in required",
            message=message,
        )
        self.set_status(403)
        self.finish(html)


class JWTAuthenticator(Authenticator):
    """Authenticate JupyterHub users via a signed JWT."""

    username_claim_field = Unicode(
        "platformname",
        config=True,
        help="Claim in the decoded JWT to use as the JupyterHub username.",
    )

    course_claim_field = Unicode(
        "course_id",
        config=True,
        help="Claim in the decoded JWT which holds the course ID.",
    )

    expected_course_id = Unicode(
        "",
        config=True,
        help=(
            "Required. The JWT's course claim (see course_claim_field) must "
            "equal this value or login is rejected."
        ),
    )

    admin_claim_field = Unicode(
        "assistant_or_owner",
        config=True,
        help=(
            "If set, the JWT's field name matching this value should be a bool"
            "indicating if the user should be set as an admin."
        ),
    )

    jwt_public_key = Unicode(
        "",
        config=True,
        help="PEM-encoded public key used to verify JWT signature.",
    )

    jwt_key_algorithm = Unicode(
        "RS256",
        config=True,
        help="Algorithm the JWT is signed with, e.g. 'RS256' or 'HS256'.",
    )

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        if not self.expected_course_id:
            raise ValueError("JWTAuthenticator.expected_course_id must be set")
        # Token ID -> expiry time, for the tokens which have been used to log in
        self._used_token_ids: dict[str, float] = {}

    def verify_token(self, token):
        """Decode and verify the JWT, returning its claims dict.

        Raises jwt.PyJWTError (or a subclass) on any failure: bad
        signature, expired token, malformed token, no expiry or token ID, etc.
        """
        return jwt.decode(
            token,
            self.jwt_public_key,
            algorithms=[self.jwt_key_algorithm],
            options={"require": ["exp", "jti"]},
        )

    def mark_token_used(self, claims) -> bool:
        """Record the token as used, returning False if it already had been."""
        now = time.time()
        self._used_token_ids = {
            token_id: expiry
            for token_id, expiry in self._used_token_ids.items()
            if expiry > now
        }
        if claims["jti"] in self._used_token_ids:
            return False
        self._used_token_ids[claims["jti"]] = claims["exp"]
        return True

    def extract_username(self, claims):
        return claims.get(self.username_claim_field) or None

    def get_handlers(self, app):
        return [("/login", JWTLoginHandler)]

    async def authenticate(self, handler, data=None):
        """Verify the JWT passed as data['token'] and return an auth model.

        Called by JupyterHub's login_user()/get_authenticated_user(),
        which also applies allow_all/allowed_users/blocked_users on top
        of whatever we return here. Returning None means "not
        authenticated" and is handled generically by the caller.
        """
        token = (data or {}).get("token")
        if not token:
            handler.log.warning("JWTAuthenticator: authenticate() called with no token")
            return None

        try:
            claims = self.verify_token(token)
        except PyJWTError as e:
            handler.log.warning("JWTAuthenticator: token verification failed: %s", e)
            return None

        if claims.get(self.course_claim_field) != self.expected_course_id:
            handler.log.warning(
                "JWTAuthenticator: %s %r != expected %r",
                self.course_claim_field,
                claims.get(self.course_claim_field),
                self.expected_course_id,
            )
            return None

        if not self.mark_token_used(claims):
            handler.log.warning("JWTAuthenticator: token has already been used")
            return None

        username = self.extract_username(claims)
        if not username:
            handler.log.warning(
                "JWTAuthenticator: claim %r missing/empty in token",
                self.username_claim_field,
            )
            return None

        user_dict = {
            "name": username,
            # "auth_state": claims, # Not needed right now
        }

        if self.admin_claim_field and self.admin_claim_field in claims:
            admin_val = claims[self.admin_claim_field]
            if isinstance(admin_val, bool):
                user_dict["admin"] = admin_val

        return user_dict

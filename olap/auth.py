from hashlib import scrypt, sha256
from hmac import compare_digest
from secrets import token_hex, token_urlsafe

COOKIE = "olap_session"
SESSION_SECONDS = 8 * 60 * 60
ROLE_LOCK = 141405


def password_hash(password, salt=None):
    salt = salt or token_hex(16)
    value = scrypt(password.encode(), salt=bytes.fromhex(salt), n=2**14, r=8, p=1)
    return f"{salt}:{value.hex()}"


def verify_password(password, stored):
    salt, _ = stored.split(":", 1)
    return compare_digest(password_hash(password, salt), stored)


def token_digest(token):
    return sha256(token.encode()).hexdigest()


def create_session(cursor, username):
    token = token_urlsafe(32)
    cursor.execute("DELETE FROM app_session WHERE expires_at <= now()")
    cursor.execute("""
        INSERT INTO app_session (token_hash, username, expires_at)
        VALUES (%s, %s, now() + %s * interval '1 second')
    """, (token_digest(token), username, SESSION_SECONDS))
    return token


def find_user(cursor, token):
    if not token or len(token) != 43:
        return None
    cursor.execute("""
        SELECT u.username, u.role
        FROM app_user u JOIN app_session s USING (username)
        WHERE s.token_hash = %s AND s.expires_at > now() AND u.enabled
    """, (token_digest(token),))
    return cursor.fetchone()

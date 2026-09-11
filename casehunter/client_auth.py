from datetime import datetime, timedelta, timezone
import base64
import hashlib
import hmac
import secrets

from .database import row_to_dict, transaction, utc_now


PASSWORD_SCHEME = "pbkdf2_sha256"
PASSWORD_ITERATIONS = 390_000
SESSION_TTL_DAYS = 7
MAX_FAILED_ATTEMPTS = 5
LOCK_MINUTES = 15
VALID_ROLES = {"VIEWER", "OWNER"}


def _b64(data):
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _b64decode(value):
    text = str(value or "")
    text += "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode(text.encode("ascii"))


def _normalize_email(value):
    return str(value or "").strip().lower()


def hash_password(password, salt=None, iterations=PASSWORD_ITERATIONS):
    value = str(password or "")
    if len(value) < 12:
        raise ValueError("La contraseña debe tener al menos 12 caracteres")
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", value.encode("utf-8"), salt, int(iterations))
    return f"{PASSWORD_SCHEME}${int(iterations)}${_b64(salt)}${_b64(digest)}"


def verify_password(password, stored_hash):
    try:
        scheme, iterations, salt_text, digest_text = str(stored_hash or "").split("$", 3)
        if scheme != PASSWORD_SCHEME:
            return False
        salt = _b64decode(salt_text)
        expected = _b64decode(digest_text)
        actual = hashlib.pbkdf2_hmac("sha256", str(password or "").encode("utf-8"), salt, int(iterations))
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError):
        return False


_DUMMY_HASH = f"{PASSWORD_SCHEME}${PASSWORD_ITERATIONS}${_b64(b'casehunter-dummy')}${_b64(hashlib.pbkdf2_hmac('sha256', b'not-a-password', b'casehunter-dummy', PASSWORD_ITERATIONS))}"


def _public_user(row):
    if row is None:
        return None
    data = row_to_dict(row)
    return {
        "id": int(data["id"]),
        "company_id": int(data["company_id"]),
        "email": data["email"],
        "role": data["role"],
        "status": data["status"],
        "last_login_at": data.get("last_login_at"),
        "created_at": data.get("created_at"),
        "permissions": ["portfolio:read"],
    }


def create_client_user(company_id, email, password, role="VIEWER", db_path=None):
    company_id = int(company_id)
    email = _normalize_email(email)
    role = str(role or "VIEWER").strip().upper()
    if not email or "@" not in email:
        raise ValueError("Correo de cliente no válido")
    if role not in VALID_ROLES:
        raise ValueError("Rol de cliente no válido")
    password_hash = hash_password(password)
    now = utc_now()
    with transaction(db_path) as conn:
        if conn.execute("SELECT id FROM companies WHERE id=?", (company_id,)).fetchone() is None:
            raise KeyError("Empresa no encontrada")
        existing = conn.execute("SELECT id FROM client_users WHERE email=?", (email,)).fetchone()
        if existing:
            raise ValueError("Ya existe una cuenta con ese correo")
        cur = conn.execute(
            """INSERT INTO client_users(
                   company_id,email,password_hash,role,status,failed_attempts,locked_until,last_login_at,created_at,updated_at
               ) VALUES(?,?,?,?,'ACTIVE',0,NULL,NULL,?,?)""",
            (company_id, email, password_hash, role, now, now),
        )
        user_id = cur.lastrowid
        row = conn.execute("SELECT * FROM client_users WHERE id=?", (user_id,)).fetchone()
    return _public_user(row)


def list_client_users(db_path=None):
    with transaction(db_path) as conn:
        rows = conn.execute(
            """SELECT u.*,c.name company_name
               FROM client_users u JOIN companies c ON c.id=u.company_id
               ORDER BY c.name,u.email"""
        ).fetchall()
    result = []
    for row in rows:
        item = _public_user(row)
        item["company_name"] = row["company_name"]
        result.append(item)
    return result


def set_client_user_status(user_id, status, db_path=None):
    status = str(status or "").strip().upper()
    if status not in {"ACTIVE", "DISABLED"}:
        raise ValueError("Estado de cuenta no válido")
    now = utc_now()
    with transaction(db_path) as conn:
        row = conn.execute("SELECT * FROM client_users WHERE id=?", (int(user_id),)).fetchone()
        if row is None:
            raise KeyError("Cuenta de cliente no encontrada")
        conn.execute("UPDATE client_users SET status=?,updated_at=? WHERE id=?", (status, now, int(user_id)))
        if status == "DISABLED":
            conn.execute(
                "UPDATE client_sessions SET revoked_at=? WHERE user_id=? AND revoked_at IS NULL",
                (now, int(user_id)),
            )
        row = conn.execute("SELECT * FROM client_users WHERE id=?", (int(user_id),)).fetchone()
    return _public_user(row)


def reset_client_password(user_id, password, db_path=None):
    password_hash = hash_password(password)
    now = utc_now()
    with transaction(db_path) as conn:
        row = conn.execute("SELECT id FROM client_users WHERE id=?", (int(user_id),)).fetchone()
        if row is None:
            raise KeyError("Cuenta de cliente no encontrada")
        conn.execute(
            """UPDATE client_users
               SET password_hash=?,failed_attempts=0,locked_until=NULL,updated_at=? WHERE id=?""",
            (password_hash, now, int(user_id)),
        )
        conn.execute(
            "UPDATE client_sessions SET revoked_at=? WHERE user_id=? AND revoked_at IS NULL",
            (now, int(user_id)),
        )
        row = conn.execute("SELECT * FROM client_users WHERE id=?", (int(user_id),)).fetchone()
    return _public_user(row)


def _parse_time(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def authenticate_client(email, password, db_path=None):
    email = _normalize_email(email)
    now = datetime.now(timezone.utc)
    with transaction(db_path) as conn:
        row = conn.execute("SELECT * FROM client_users WHERE email=?", (email,)).fetchone()
        if row is None:
            verify_password(password, _DUMMY_HASH)
            return None
        data = row_to_dict(row)
        if data.get("status") != "ACTIVE":
            verify_password(password, data.get("password_hash"))
            return None
        locked_until = _parse_time(data.get("locked_until"))
        if locked_until and locked_until > now:
            verify_password(password, data.get("password_hash"))
            return None
        if not verify_password(password, data.get("password_hash")):
            failures = int(data.get("failed_attempts") or 0) + 1
            lock_until = None
            if failures >= MAX_FAILED_ATTEMPTS:
                lock_until = (now + timedelta(minutes=LOCK_MINUTES)).isoformat()
                failures = 0
            conn.execute(
                "UPDATE client_users SET failed_attempts=?,locked_until=?,updated_at=? WHERE id=?",
                (failures, lock_until, now.isoformat(), int(data["id"])),
            )
            return None
        conn.execute(
            """UPDATE client_users
               SET failed_attempts=0,locked_until=NULL,last_login_at=?,updated_at=? WHERE id=?""",
            (now.isoformat(), now.isoformat(), int(data["id"])),
        )
        row = conn.execute("SELECT * FROM client_users WHERE id=?", (int(data["id"]),)).fetchone()
    return _public_user(row)


def _token_hash(token):
    return hashlib.sha256(str(token or "").encode("utf-8")).hexdigest()


def create_client_session(user_id, db_path=None, ttl_days=SESSION_TTL_DAYS):
    token = secrets.token_urlsafe(32)
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(days=max(1, int(ttl_days)))
    with transaction(db_path) as conn:
        user = conn.execute("SELECT status FROM client_users WHERE id=?", (int(user_id),)).fetchone()
        if user is None or user["status"] != "ACTIVE":
            raise ValueError("La cuenta no está activa")
        conn.execute(
            """INSERT INTO client_sessions(
                   user_id,token_hash,expires_at,created_at,last_seen_at,revoked_at
               ) VALUES(?,?,?,?,?,NULL)""",
            (int(user_id), _token_hash(token), expires_at.isoformat(), now.isoformat(), now.isoformat()),
        )
    return token, expires_at


def get_client_session(token, db_path=None):
    if not token:
        return None
    now = datetime.now(timezone.utc)
    with transaction(db_path) as conn:
        row = conn.execute(
            """SELECT s.id session_id,s.expires_at,s.revoked_at,
                      u.id,u.company_id,u.email,u.role,u.status,u.last_login_at,u.created_at
               FROM client_sessions s
               JOIN client_users u ON u.id=s.user_id
               WHERE s.token_hash=?
               LIMIT 1""",
            (_token_hash(token),),
        ).fetchone()
        if row is None:
            return None
        data = row_to_dict(row)
        expires_at = _parse_time(data.get("expires_at"))
        if data.get("revoked_at") or data.get("status") != "ACTIVE" or expires_at is None or expires_at <= now:
            if not data.get("revoked_at"):
                conn.execute(
                    "UPDATE client_sessions SET revoked_at=? WHERE id=?",
                    (now.isoformat(), int(data["session_id"])),
                )
            return None
        conn.execute(
            "UPDATE client_sessions SET last_seen_at=? WHERE id=?",
            (now.isoformat(), int(data["session_id"])),
        )
    return _public_user(data)


def revoke_client_session(token, db_path=None):
    if not token:
        return False
    now = utc_now()
    with transaction(db_path) as conn:
        cur = conn.execute(
            "UPDATE client_sessions SET revoked_at=? WHERE token_hash=? AND revoked_at IS NULL",
            (now, _token_hash(token)),
        )
        return bool(cur.rowcount)

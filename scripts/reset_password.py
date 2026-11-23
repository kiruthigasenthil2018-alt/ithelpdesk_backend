"""Set a new password for an existing user.

Run from the backend folder:
    python -m scripts.reset_password you@company.com "NewStrongPass123"
"""

import sys

from sqlalchemy import select

from app.database.base import SessionLocal
from app.database.models import User
from app.services.security import hash_password

if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit('Usage: python -m scripts.reset_password <email> "<new password>"')
    email, password = sys.argv[1].strip().lower(), sys.argv[2]
    if len(password) < 8 or password.isalpha() or password.isdigit():
        sys.exit("Password must be at least 8 characters and mix letters and numbers.")
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.email == email))
        if user is None:
            sys.exit(f"No user with email {email}")
        user.password_hash = hash_password(password)
        db.commit()
    print(f"Password updated for {email}")

# backend/app/routers/auth.py

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(prefix="/auth", tags=["auth"])

# 🔒 Lockdown config
ALLOWED_USERS = {
    "Neurocrest_dev",
    "Neurocrest_test",
    "Neurocrest_masum",
    "Neurocrest_vishal",
    "Neurocrest_jinal",
    "Neurocrest_others",
}
FIXED_PASSWORD = "neurocrest123"
CONTACT_MSG = "Please contact on the WhatsApp number: 6358801256"

# (Kept for compatibility with your project structure; not used after lockdown)
DB_PATH = "/data/paper_trading.db"


# 📦 Pydantic models
class UserIn(BaseModel):
    username: str
    password: str


class UpdatePassword(BaseModel):
    username: str
    new_password: str


class UpdateEmail(BaseModel):
    username: str
    new_email: str


class GoogleToken(BaseModel):
    token: str


# ✅ Login route (locked to allowlist + fixed password)
@router.post("/login")
def login(user: UserIn):
    username = (user.username or "").strip()
    password = user.password or ""

    print("🔑 Login attempt:", username)

    # Not allowlisted → show WhatsApp number
    if username not in ALLOWED_USERS:
        print("⛔ Not allowlisted:", username)
        return {"success": False, "message": CONTACT_MSG}

    # On allowlist but wrong password
    if password != FIXED_PASSWORD:
        print("❌ Wrong password for:", username)
        return {"success": False, "message": "Invalid credentials"}

    # Success
    print("✅ Login success for:", username)
    return {"success": True, "username": username}


# 🚫 Register route disabled
@router.post("/register")
def register(user: UserIn):
    print("🚫 Register blocked for:", user.username)
    return {"success": False, "message": CONTACT_MSG}


# 🚫 Update password disabled (password is fixed)
@router.post("/update-password")
def update_password(data: UpdatePassword):
    print("🚫 Update password blocked for:", data.username)
    return {
        "success": False,
        "message": f"Password is fixed and cannot be changed. {CONTACT_MSG}",
    }


# 🚫 Update email/username disabled (user IDs are fixed)
@router.post("/update-email")
def update_email(data: UpdateEmail):
    print("🚫 Update email blocked for:", data.username)
    return {
        "success": False,
        "message": f"Username/Email changes are disabled. {CONTACT_MSG}",
    }


# 🚫 Google Login disabled (lockdown)
@router.post("/google-login")
def google_login(data: GoogleToken):
    print("🚫 Google login blocked")
    return {"success": False, "message": CONTACT_MSG}

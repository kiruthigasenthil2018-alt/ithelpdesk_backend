"""Service catalog (like ServiceNow / Freshservice): standard requests users can raise."""

CATALOG = [
    {"id": "new-laptop", "name": "New laptop or hardware", "description": "Request a new or replacement laptop, monitor or accessory.", "category": "hardware", "priority": "P3", "icon": "💻"},
    {"id": "software-install", "name": "Software installation", "description": "Request approved software from the company software center.", "category": "software", "priority": "P4", "icon": "📦"},
    {"id": "vpn-access", "name": "VPN access", "description": "Request VPN access or a new VPN profile.", "category": "network", "priority": "P3", "icon": "🔐"},
    {"id": "account-access", "name": "Account or access request", "description": "New account, group membership or permission change.", "category": "account", "priority": "P3", "icon": "👤"},
    {"id": "password-help", "name": "Locked out / password help", "description": "You cannot sign in and need urgent help.", "category": "account", "priority": "P2", "icon": "🔑"},
    {"id": "report-security", "name": "Report a security concern", "description": "Phishing email, lost device or suspicious activity.", "category": "security", "priority": "P1", "icon": "🛡️"},
]


def get_item(item_id: str) -> dict | None:
    return next((i for i in CATALOG if i["id"] == item_id), None)

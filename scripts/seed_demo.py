"""Fill the database with demo incidents so the dashboard looks alive.

Run from the backend folder:  python -m scripts.seed_demo
"""

from app.database.base import SessionLocal, init_db
from app.schemas.incident import IncidentCreate
from app.services import incident_service as svc

DEMO = [
    ("OOM exception for GetOrders service", "Out of memory exception in the GetOrders service", "software", "P1", "customer"),
    ("VPN cannot connect for remote team", "Authentication failed when connecting to VPN", "network", "P1", "customer"),
    ("Cannot connect CSS 912", "Application cannot connect to internal CSS service", "network", "P1", "system"),
    ("Account locked after password change", "User locked out after 5 attempts", "account", "P2", "customer"),
    ("Printer offline on floor 3", "Printer shows offline for everyone", "hardware", "P3", "customer"),
    ("Outlook keeps freezing", "Outlook freezes when opening attachments", "software", "P3", "system"),
    ("How do I install the design software?", "Need a software install request", "software", "P4", "customer"),
]

if __name__ == "__main__":
    init_db()
    db = SessionLocal()
    for title, desc, cat, prio, src in DEMO:
        svc.create_incident(db, IncidentCreate(title=title, description=desc, category=cat, priority=prio, source=src))
    print(f"Seeded {len(DEMO)} demo incidents")

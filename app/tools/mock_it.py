"""Mock IT operations. Nothing here touches a real system."""

ALLOWED_ACTIONS: dict[str, dict] = {
    "flush_dns": {"description": "Flush the DNS cache on the user's device", "requires_approval": False},
    "restart_network_adapter": {"description": "Restart the network adapter", "requires_approval": False},
    "clear_app_cache": {"description": "Clear the application cache", "requires_approval": False},
    "reset_vpn_profile": {"description": "Re-issue the VPN profile", "requires_approval": False},
    "reset_password": {"description": "Reset the user's password", "requires_approval": True},
    "unlock_account": {"description": "Unlock the user's account", "requires_approval": True},
    "quarantine_device": {"description": "Isolate the device from the network", "requires_approval": True},
}

ESCALATION_TEAMS = {
    "network": "Network Operations",
    "hardware": "Desktop Support",
    "software": "Application Support",
    "account": "Identity & Access",
    "security": "Security Operations Center",
}


def is_allowed(action: str) -> bool:
    return action in ALLOWED_ACTIONS


def requires_approval(action: str) -> bool:
    return ALLOWED_ACTIONS[action]["requires_approval"]


def execute_action(action: str, incident_id: str) -> str:
    """Pretend to run an allowlisted action."""
    if not is_allowed(action):
        raise ValueError(f"Action '{action}' is not allowlisted")
    return f"[MOCK] '{action}' executed for {incident_id}"


def team_for(category: str | None) -> str:
    return ESCALATION_TEAMS.get(category or "", "IT Service Desk (Tier 2)")

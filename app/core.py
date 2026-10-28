import yaml

ALLOWED_ROUTERS = {
    "10.0.29.101",
    "10.0.29.102",
    "10.0.29.103",
    "10.0.29.104",
    "10.0.29.105",
}

METHOD_ACTIONS = {
    "restconf": {"status", "plan", "apply"},
    "netconf": {"status", "plan", "apply"},
    "ansible": {"apply"},
    "netmiko-textfsm": {"status", "delete"},
}

def validate_request(data):
    """
    Validate one IPA2026 desired-state request.

    Return a response dictionary according to
    specs/response-spec-v1.md.
    """
    # TODO: implement
    if not isinstance(data, dict):
        return {"status": "error", "result": "invalid_yaml"}

    # Validate version first.
    version = data.get("version")
    if type(version) is not int or version != 1:
        return {"status": "error", "result": "invalid_version"}

    # Validate router.
    if "router" not in data:
        return {"status": "error", "result": "missing_router"}

    router = data["router"]
    if not isinstance(router, str) or router not in ALLOWED_ROUTERS:
        return {"status": "error", "result": "invalid_router"}

    # Validate method.
    if "method" not in data:
        return {"status": "error", "result": "missing_method"}

    method = data["method"]
    if not isinstance(method, str) or method not in METHOD_ACTIONS:
        return {"status": "error", "result": "invalid_method"}

    # Validate action.
    if "action" not in data:
        return {"status": "error", "result": "missing_action"}

    action = data["action"]
    if not isinstance(action, str):
        return {"status": "error", "result": "invalid_action"}

    if action not in METHOD_ACTIONS[method]:
        return {"status": "error", "result": "invalid_action"}

    # Validate desired.interface.
    if "desired" not in data or not isinstance(data["desired"], dict):
        return {"status": "error", "result": "missing_desired"}

    desired = data["desired"]
    if (
        "interface" not in desired
        or not isinstance(desired["interface"], dict)
    ):
        return {"status": "error", "result": "missing_interface"}

    interface = desired["interface"]
    name = interface.get("name")

    if not isinstance(name, str) or not name.strip():
        return {
            "status": "error",
            "result": "missing_interface_name",
        }

    # plan and apply require all desired interface fields.
    if action in {"plan", "apply"}:
        for field, error_code in (
            ("ipv4", "missing_ipv4"),
            ("description", "missing_description"),
            ("admin_state", "missing_admin_state"),
        ):
            value = interface.get(field)

            if value is None or (
                isinstance(value, str) and not value.strip()
            ):
                return {"status": "error", "result": error_code}

        if interface["admin_state"] not in ("up", "down"):
            return {
                "status": "error",
                "result": "invalid_admin_state",
            }

    return {"status": "ok", "result": "accepted"}


def process_request_file(path):
    """
    Read a YAML request file, validate it,
    and return a response dictionary.
    """
    # TODO: implement
    try:
        with open(path, "r", encoding="utf-8") as file:
            data = yaml.safe_load(file)
    except (OSError, UnicodeError, yaml.YAMLError, TypeError, ValueError):
        return {"status": "error", "result": "invalid_yaml"}

    return validate_request(data)

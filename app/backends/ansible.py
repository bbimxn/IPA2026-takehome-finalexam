import ipaddress
import json
import os
import subprocess
from pathlib import Path

def _error(result):
    return {
        "status": "error",
        "result": result,
    }


def _run_playbook(variables):
    """Run the real Ansible playbook."""
    if not os.environ.get("ROUTER_USER") or not os.environ.get("ROUTER_PASS"):
        raise PermissionError("Router credentials are not configured")

    project_root = Path(__file__).resolve().parents[2]
    inventory_path = project_root / "ansible" / "inventory.ini"
    playbook_path = project_root / "ansible" / "apply_interface.yml"

    command = [
        "ansible-playbook",
        "-i",
        str(inventory_path),
        str(playbook_path),
        "--limit",
        "target",
        "--extra-vars",
        json.dumps(variables),
    ]

    try:
        completed = subprocess.run(
            command,
            cwd=project_root,
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
            env=os.environ.copy(),
        )
    except subprocess.TimeoutExpired as exc:
        raise ConnectionError("Ansible operation timed out") from exc

    if completed.returncode == 0:
        return

    output = f"{completed.stdout}\n{completed.stderr}".lower()

    authentication_markers = (
        "authentication failed",
        "failed to authenticate",
        "permission denied",
        "invalid username",
        "incorrect password",
        "bad password",
    )

    connection_markers = (
        "unreachable",
        "connection refused",
        "timed out",
        "timeout",
        "no route to host",
        "failed to connect to the host",
        "ssh connection failed",
    )

    if any(marker in output for marker in authentication_markers):
        raise PermissionError("Ansible authentication failed")

    if any(marker in output for marker in connection_markers):
        raise ConnectionError("Ansible router connection failed")

    raise RuntimeError("Ansible playbook failed")

def apply_interface(
    router,
    desired_interface,
    run_playbook=None,
):
    """Apply complete desired interface state using Ansible."""
    try:
        name = desired_interface["name"]
        description = desired_interface["description"]
        desired_ipv4 = ipaddress.IPv4Interface(
            desired_interface["ipv4"]
        )
        admin_state = desired_interface["admin_state"]

        if not isinstance(name, str) or not name.strip():
            return _error("backend_failed")

        if not isinstance(description, str):
            return _error("backend_failed")

        if admin_state not in ("up", "down"):
            return _error("backend_failed")

        variables = {
            "router": router,
            "interface_name": name,
            "description": description,
            "ipv4_address": str(desired_ipv4.ip),
            "netmask": str(desired_ipv4.network.netmask),
            "shutdown": admin_state == "down",
        }

        runner = (
            run_playbook
            if run_playbook is not None
            else _run_playbook
        )

        runner(variables)

    except PermissionError:
        return _error("authentication_failed")

    except (ConnectionError, TimeoutError):
        return _error("connection_failed")

    except (KeyError, TypeError, ValueError):
        return _error("backend_failed")

    except Exception:
        return _error("backend_failed")

    return {
        "status": "ok",
        "result": "applied",
    }

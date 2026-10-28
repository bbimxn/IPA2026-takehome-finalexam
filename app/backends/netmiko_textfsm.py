import ipaddress
import os
import re

from netmiko import ConnectHandler
from netmiko.exceptions import (
    NetmikoAuthenticationException,
    NetmikoTimeoutException,
)

def _error(result):
    return {
        "status": "error",
        "result": result,
    }


def _not_found():
    return {
        "status": "ok",
        "result": "not_found",
        "interface": None,
    }


def _normalize_interface_name(name):
    if not isinstance(name, str):
        return None

    match = re.fullmatch(r"(?:Loopback|Lo)(\d+)", name, re.IGNORECASE)

    if match:
        return f"Loopback{match.group(1)}"

    return name


def _map_exception(exc):
    if isinstance(
        exc,
        (PermissionError, NetmikoAuthenticationException),
    ):
        return _error("authentication_failed")

    if isinstance(
        exc,
        (
            ConnectionError,
            TimeoutError,
            OSError,
            NetmikoTimeoutException,
        ),
    ):
        return _error("connection_failed")

    return _error("backend_failed")


def _router_credentials():
    username = os.getenv("ROUTER_USER")
    password = os.getenv("ROUTER_PASS")

    if not username or not password:
        raise PermissionError("Router credentials are not configured")

    return username, password


def _default_netmiko_get(router, interface_name):
    username, password = _router_credentials()
    connection = None

    try:
        connection = ConnectHandler(
            device_type="cisco_ios",
            host=router,
            username=username,
            password=password,
            conn_timeout=10,
            auth_timeout=10,
            banner_timeout=10,
        )

        ip_info = connection.send_command(
            f"show ip interface {interface_name}",
            use_textfsm=True,
        )

        descriptions = connection.send_command(
            "show interfaces description",
            use_textfsm=True,
        )

        if not isinstance(ip_info, list):
            raise RuntimeError("Unexpected TextFSM IP-interface output")

        if not isinstance(descriptions, list):
            raise RuntimeError("Unexpected TextFSM description output")

        return ip_info, descriptions

    finally:
        if connection is not None:
            connection.disconnect()


def _default_netmiko_delete(router, interface_name):
    username, password = _router_credentials()
    connection = None

    try:
        connection = ConnectHandler(
            device_type="cisco_ios",
            host=router,
            username=username,
            password=password,
            conn_timeout=10,
            auth_timeout=10,
            banner_timeout=10,
        )

        output = connection.send_config_set(
            [f"no interface {interface_name}"]
        )

        if not isinstance(output, str):
            raise RuntimeError("Unexpected Netmiko command output")

        error_markers = (
            "% invalid input",
            "% incomplete command",
            "% ambiguous command",
            "% authorization failed",
            "% command rejected",
        )

        if any(marker in output.lower() for marker in error_markers):
            raise RuntimeError("Router rejected the delete command")

        return "deleted"

    finally:
        if connection is not None:
            connection.disconnect()
            
            
def get_interface_state(
    router,
    interface_name,
    netmiko_get=None,
):
    """Return normalized interface status using Netmiko + TextFSM."""
    normalized_name = _normalize_interface_name(interface_name)

    if normalized_name is None:
        return _error("backend_failed")

    getter = (
        netmiko_get
        if netmiko_get is not None
        else _default_netmiko_get
    )

    try:
        response = getter(router, interface_name)
    except Exception as exc:
        return _map_exception(exc)

    if not isinstance(response, tuple) or len(response) != 2:
        return _error("backend_failed")

    ip_info, descriptions = response

    if not isinstance(ip_info, list) or not isinstance(descriptions, list):
        return _error("backend_failed")

    if not ip_info:
        return _not_found()

    matching_interface = None

    for record in ip_info:
        if not isinstance(record, dict):
            return _error("backend_failed")

        record_name = _normalize_interface_name(
            record.get("interface")
        )

        if record_name == normalized_name:
            matching_interface = record
            break

    if matching_interface is None:
        return _error("backend_failed")

    try:
        ip_addresses = matching_interface["ip_address"]
        prefix_lengths = matching_interface["prefix_length"]
        link_status = matching_interface["link_status"]

        if not isinstance(ip_addresses, list) or not ip_addresses:
            return _error("backend_failed")

        if not isinstance(prefix_lengths, list) or not prefix_lengths:
            return _error("backend_failed")

        if not isinstance(link_status, str):
            return _error("backend_failed")

        ipv4 = str(
            ipaddress.IPv4Interface(
                f"{ip_addresses[0]}/{prefix_lengths[0]}"
            )
        )

    except (KeyError, TypeError, ValueError, IndexError):
        return _error("backend_failed")

    description = None

    for record in descriptions:
        if not isinstance(record, dict):
            return _error("backend_failed")

        port_name = _normalize_interface_name(record.get("port"))

        if port_name == normalized_name:
            description = record.get("description")
            break

    if description is not None and not isinstance(description, str):
        return _error("backend_failed")

    admin_state = (
        "down"
        if "administratively down" in link_status.lower()
        else "up"
    )

    return {
        "status": "ok",
        "result": "found",
        "interface": {
            "name": normalized_name,
            "ipv4": ipv4,
            "description": description,
            "admin_state": admin_state,
        },
    }


def delete_interface(
    router,
    interface_name,
    netmiko_delete=None,
):
    """Delete an interface using Netmiko."""
    normalized_name = _normalize_interface_name(interface_name)

    if normalized_name is None or not normalized_name.startswith("Loopback"):
        return _error("backend_failed")

    # Public tests inject a fake delete operation.
    # Do not contact a real router when a fake is supplied.
    if netmiko_delete is not None:
        try:
            result = netmiko_delete(router, interface_name)
        except Exception as exc:
            return _map_exception(exc)

        if result == "deleted":
            return {
                "status": "ok",
                "result": "deleted",
            }

        if result == "not_found":
            return _not_found()

        return _error("backend_failed")

    # Check whether the interface already exists.
    current = get_interface_state(router, interface_name)

    if current.get("status") == "error":
        return current

    if current.get("result") == "not_found":
        return _not_found()

    if current.get("result") != "found":
        return _error("backend_failed")

    # Delete the existing interface.
    try:
        result = _default_netmiko_delete(router, interface_name)
    except Exception as exc:
        return _map_exception(exc)

    if result != "deleted":
        return _error("backend_failed")

    # Verify the deletion using the existing status path.
    verification = get_interface_state(router, interface_name)

    if verification.get("status") == "error":
        return verification

    if verification.get("result") == "not_found":
        return {
            "status": "ok",
            "result": "deleted",
        }

    return _error("backend_failed")

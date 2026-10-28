import ipaddress
import os

import requests

from .planning import plan_interface as _build_backend_plan


def _error(result):
    return {
        "status": "error",
        "result": result,
    }


def _transport_error(exc):
    if isinstance(exc, PermissionError):
        return _error("authentication_failed")

    if isinstance(
        exc,
        (
            ConnectionError,
            TimeoutError,
            requests.exceptions.Timeout,
            requests.exceptions.ConnectionError,
        ),
    ):
        return _error("connection_failed")

    return _error("backend_failed")


def _router_auth():
    username = os.getenv("ROUTER_USER")
    password = os.getenv("ROUTER_PASS")

    if not username or not password:
        raise PermissionError(
            "Router credentials are not configured"
        )

    return username, password


def _default_http_get(url):
    return requests.get(
        url,
        auth=_router_auth(),
        headers={
            "Accept": "application/yang-data+json",
        },
        timeout=10,
    )


def _default_http_put(url, json):
    return requests.put(
        url,
        json=json,
        auth=_router_auth(),
        headers={
            "Accept": "application/yang-data+json",
            "Content-Type": "application/yang-data+json",
        },
        timeout=10,
    )
    
def get_interface_state(
    router,
    interface_name,
    http_get=None,
):
    """Return normalized interface status using RESTCONF."""
    url = (
        f"https://{router}/restconf/data/"
        f"ietf-interfaces:interfaces/interface={interface_name}"
    )

    getter = (
        http_get
        if http_get is not None
        else _default_http_get
    )

    try:
        response = getter(url)
    except Exception as exc:
        return _transport_error(exc)

    status_code = getattr(response, "status_code", None)

    if status_code == 404:
        return {
            "status": "ok",
            "result": "not_found",
            "interface": None,
        }

    if status_code in (401, 403):
        return _error("authentication_failed")

    if status_code != 200:
        return _error("backend_failed")

    try:
        payload = response.json()
        interface = payload["ietf-interfaces:interface"]

        name = interface["name"]
        enabled = interface["enabled"]
        addresses = interface["ietf-ip:ipv4"]["address"]

        if not isinstance(name, str):
            return _error("backend_failed")

        if not isinstance(enabled, bool):
            return _error("backend_failed")

        if not isinstance(addresses, list) or not addresses:
            return _error("backend_failed")

        address = addresses[0]

        ipv4 = str(
            ipaddress.IPv4Interface(
                f"{address['ip']}/{address['netmask']}"
            )
        )

        description = interface.get("description")

        if (
            description is not None
            and not isinstance(description, str)
        ):
            return _error("backend_failed")

    except (
        AttributeError,
        KeyError,
        TypeError,
        ValueError,
        IndexError,
    ):
        return _error("backend_failed")

    return {
        "status": "ok",
        "result": "found",
        "interface": {
            "name": name,
            "ipv4": ipv4,
            "description": description,
            "admin_state": "up" if enabled else "down",
        },
    }


def plan_interface(
    router,
    desired_interface,
    http_get=None,
):
    """Return create/update/no_change plan using RESTCONF status."""
    return _build_backend_plan(
        router,
        desired_interface,
        lambda target_router, interface_name: get_interface_state(
            target_router,
            interface_name,
            http_get,
        ),
    )


def apply_interface(
    router,
    desired_interface,
    http_put=None,
):
    """Apply complete desired interface state using RESTCONF."""
    try:
        name = desired_interface["name"]

        if not isinstance(name, str) or not name.startswith(
            "Loopback"
        ):
            return _error("backend_failed")

        number = int(name[len("Loopback"):])

        ipv4 = ipaddress.IPv4Interface(
            desired_interface["ipv4"]
        )

        admin_state = desired_interface["admin_state"]

        if admin_state not in ("up", "down"):
            return _error("backend_failed")

        url = (
            f"https://{router}/restconf/data/"
            f"Cisco-IOS-XE-native:native/interface/Loopback={number}"
        )

        loopback = {
            "name": number,
            "description": desired_interface["description"],
            "ip": {
                "address": {
                    "primary": {
                        "address": str(ipv4.ip),
                        "mask": str(ipv4.network.netmask),
                    }
                }
            },
        }

        if admin_state == "down":
            loopback["shutdown"] = [None]

        payload = {
            "Cisco-IOS-XE-native:Loopback": loopback
        }

    except (KeyError, TypeError, ValueError):
        return _error("backend_failed")

    putter = (
        http_put
        if http_put is not None
        else _default_http_put
    )

    try:
        response = putter(url, json=payload)
    except Exception as exc:
        return _transport_error(exc)

    status_code = getattr(response, "status_code", None)

    if status_code in (200, 201, 204):
        return {
            "status": "ok",
            "result": "applied",
        }

    if status_code in (401, 403):
        return _error("authentication_failed")

    return _error("backend_failed")

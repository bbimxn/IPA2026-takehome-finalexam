import ipaddress
import logging
import os

import requests

from .planning import plan_interface as _build_backend_plan

logger = logging.getLogger(__name__)


def _error(result):
    return {
        "status": "error",
        "result": result,
    }


def _transport_error(exc):
    logger.warning(
        "RESTCONF transport error: %s: %s", type(exc).__name__, exc
    )

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


# (connect timeout, read timeout): the shared lab router can be slow to answer
# while many students are being graded, so allow it more time to respond.
_HTTP_TIMEOUT = (10, 30)


def _with_retry(call, attempts=2):
    """Retry once on a timeout / connection error, then re-raise."""
    for attempt in range(1, attempts + 1):
        try:
            return call()
        except (
            requests.exceptions.Timeout,
            requests.exceptions.ConnectionError,
        ) as exc:
            if attempt == attempts:
                raise
            logger.warning(
                "RESTCONF attempt %s/%s failed (%s: %s); retrying",
                attempt,
                attempts,
                type(exc).__name__,
                exc,
            )


def _default_http_get(url):
    auth = _router_auth()

    return _with_retry(
        lambda: requests.get(
            url,
            auth=auth,
            headers={
                "Accept": "application/yang-data+json",
            },
            timeout=_HTTP_TIMEOUT,
            verify=False,
        )
    )


def _default_http_put(url, json):
    auth = _router_auth()

    return _with_retry(
        lambda: requests.put(
            url,
            json=json,
            auth=auth,
            headers={
                "Accept": "application/yang-data+json",
                "Content-Type": "application/yang-data+json",
            },
            timeout=_HTTP_TIMEOUT,
            verify=False,
        )
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
        enabled = interface.get("enabled", True)

        if not isinstance(name, str):
            return _error("backend_failed")

        if not isinstance(enabled, bool):
            return _error("backend_failed")

        # interface ที่ยังไม่มี IPv4 ถือว่า ipv4 = None (ไม่ใช่ backend_failed)
        ipv4_block = interface.get("ietf-ip:ipv4") or {}
        addresses = ipv4_block.get("address") or []

        if not isinstance(addresses, list):
            return _error("backend_failed")

        ipv4 = None
        if addresses:
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

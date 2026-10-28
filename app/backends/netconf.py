import ipaddress
import os
import re
from xml.etree import ElementTree as ET
from xml.sax.saxutils import escape

from ncclient import manager

from .planning import plan_interface as _build_backend_plan


NETCONF_NS = "urn:ietf:params:xml:ns:netconf:base:1.0"
IETF_INTERFACES_NS = (
    "urn:ietf:params:xml:ns:yang:ietf-interfaces"
)
IETF_IP_NS = "urn:ietf:params:xml:ns:yang:ietf-ip"
NATIVE_NS = "http://cisco.com/ns/yang/Cisco-IOS-XE-native"


def _error(result):
    return {
        "status": "error",
        "result": result,
    }


def _transport_error(exc):
    error_type = type(exc).__name__.lower()

    if (
        isinstance(exc, PermissionError)
        or "authentication" in error_type
    ):
        return _error("authentication_failed")

    if (
        isinstance(exc, (ConnectionError, TimeoutError, OSError))
        or any(
            word in error_type
            for word in ("transport", "ssh", "session", "timeout")
        )
    ):
        return _error("connection_failed")

    return _error("backend_failed")


def _router_credentials():
    username = os.getenv("ROUTER_USER")
    password = os.getenv("ROUTER_PASS")

    if not username or not password:
        raise PermissionError("Router credentials are not configured")

    return username, password


def _default_netconf_get_config(router, filter_xml):
    username, password = _router_credentials()

    with manager.connect(
        host=router,
        port=830,
        username=username,
        password=password,
        timeout=10,
    ) as session:
        reply = session.get_config(
            source="running",
            filter=filter_xml,
        )

        return reply.data_xml


def _default_netconf_edit_config(router, config_xml):
    username, password = _router_credentials()

    with manager.connect(
        host=router,
        port=830,
        username=username,
        password=password,
        timeout=10,
    ) as session:
        session.edit_config(
            target="running",
            config=config_xml,
        )

def get_interface_state(
    router,
    interface_name,
    netconf_get_config=None,
):
    """Return normalized interface status using NETCONF."""
    if not isinstance(interface_name, str) or not interface_name:
        return _error("backend_failed")

    filter_xml = (
        f'<interfaces xmlns="{IETF_INTERFACES_NS}">'
        f"<interface>"
        f"<name>{escape(interface_name)}</name>"
        f"</interface>"
        f"</interfaces>"
    )

    getter = (
        netconf_get_config
        if netconf_get_config is not None
        else _default_netconf_get_config
    )

    try:
        xml_data = getter(router, filter_xml)
    except Exception as exc:
        return _transport_error(exc)

    if not isinstance(xml_data, (str, bytes)):
        return _error("backend_failed")

    try:
        root = ET.fromstring(xml_data)

        interfaces = root.findall(
            f".//{{{IETF_INTERFACES_NS}}}interface"
        )

        selected = None

        for interface in interfaces:
            name_element = interface.find(
                f"{{{IETF_INTERFACES_NS}}}name"
            )

            if (
                name_element is not None
                and name_element.text == interface_name
            ):
                selected = interface
                break

        if selected is None:
            return {
                "status": "ok",
                "result": "not_found",
                "interface": None,
            }

        name_element = selected.find(
            f"{{{IETF_INTERFACES_NS}}}name"
        )
        enabled_element = selected.find(
            f"{{{IETF_INTERFACES_NS}}}enabled"
        )
        description_element = selected.find(
            f"{{{IETF_INTERFACES_NS}}}description"
        )
        ipv4_element = selected.find(
            f"{{{IETF_IP_NS}}}ipv4"
        )

        if (
            name_element is None
            or enabled_element is None
            or ipv4_element is None
            or enabled_element.text not in ("true", "false")
        ):
            return _error("backend_failed")

        address_element = ipv4_element.find(
            f"{{{IETF_IP_NS}}}address"
        )

        if address_element is None:
            return _error("backend_failed")

        ip_element = address_element.find(
            f"{{{IETF_IP_NS}}}ip"
        )
        mask_element = address_element.find(
            f"{{{IETF_IP_NS}}}netmask"
        )

        if (
            ip_element is None
            or mask_element is None
            or not ip_element.text
            or not mask_element.text
        ):
            return _error("backend_failed")

        ipv4 = str(
            ipaddress.IPv4Interface(
                f"{ip_element.text}/{mask_element.text}"
            )
        )

        description = (
            description_element.text
            if description_element is not None
            else None
        )

    except (
        ET.ParseError,
        AttributeError,
        KeyError,
        TypeError,
        ValueError,
    ):
        return _error("backend_failed")

    return {
        "status": "ok",
        "result": "found",
        "interface": {
            "name": name_element.text,
            "ipv4": ipv4,
            "description": description,
            "admin_state": (
                "up" if enabled_element.text == "true" else "down"
            ),
        },
    }


def plan_interface(
    router,
    desired_interface,
    netconf_get_config=None,
):
    """Return create/update/no_change plan using NETCONF status."""
    return _build_backend_plan(
        router,
        desired_interface,
        lambda target_router, interface_name: get_interface_state(
            target_router,
            interface_name,
            netconf_get_config,
        ),
    )

def apply_interface(
    router,
    desired_interface,
    netconf_edit_config=None,
):
    """Apply complete desired interface state using NETCONF."""
    try:
        name = desired_interface["name"]

        match = re.fullmatch(r"Loopback(\d+)", name)

        if match is None:
            return _error("backend_failed")

        number = match.group(1)

        ipv4 = ipaddress.IPv4Interface(
            desired_interface["ipv4"]
        )
        description = desired_interface["description"]
        admin_state = desired_interface["admin_state"]

        if (
            not isinstance(description, str)
            or admin_state not in ("up", "down")
        ):
            return _error("backend_failed")

        shutdown_xml = (
            "<shutdown/>"
            if admin_state == "down"
            else ""
        )

        config_xml = (
            f'<config xmlns="{NETCONF_NS}" '
            f'xmlns:nc="{NETCONF_NS}">'
            f'<native xmlns="{NATIVE_NS}">'
            f"<interface>"
            f'<Loopback nc:operation="replace">'
            f"<name>{number}</name>"
            f"<description>{escape(description)}</description>"
            f"<ip>"
            f"<address>"
            f"<primary>"
            f"<address>{ipv4.ip}</address>"
            f"<mask>{ipv4.network.netmask}</mask>"
            f"</primary>"
            f"</address>"
            f"</ip>"
            f"{shutdown_xml}"
            f"</Loopback>"
            f"</interface>"
            f"</native>"
            f"</config>"
        )

    except (KeyError, TypeError, ValueError):
        return _error("backend_failed")

    editor = (
        netconf_edit_config
        if netconf_edit_config is not None
        else _default_netconf_edit_config
    )

    try:
        editor(router, config_xml)
    except Exception as exc:
        return _transport_error(exc)

    return {
        "status": "ok",
        "result": "applied",
    }

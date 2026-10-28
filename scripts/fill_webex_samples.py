import ipaddress
import re
from pathlib import Path

# Set these values once.
STUDENT_ID = "67070102"
ROUTER_IP = "10.0.29.102"

# Leave empty to enter the confirmed unused IP when running.
UNUSED_IPV4 = ""

ALLOWED_ROUTERS = {
    "10.0.29.102",
    "10.0.29.103",
    "10.0.29.104",
    "10.0.29.105",
}

RESERVED_NETWORK = ipaddress.ip_network("192.0.2.128/27")


def main():
    if not re.fullmatch(r"\d{8}", STUDENT_ID):
        raise ValueError("Student ID must contain exactly 8 digits.")

    if ROUTER_IP not in ALLOWED_ROUTERS:
        raise ValueError("Choose a router from .102 to .105.")

    unused_ip = UNUSED_IPV4.strip()

    if not unused_ip:
        unused_ip = input(
            "Enter an IPv4 address confirmed unused on this router: "
        ).strip()

    address = ipaddress.IPv4Address(unused_ip)

    if address in RESERVED_NETWORK:
        raise ValueError(
            "This IP belongs to the reserved Live-test network."
        )

    project_root = Path(__file__).resolve().parents[1]
    source_dir = project_root / "sample-tests" / "webex-manual"
    output_dir = source_dir / "filled"

    if not source_dir.is_dir():
        raise FileNotFoundError(f"Missing template directory: {source_dir}")

    output_dir.mkdir(parents=True, exist_ok=True)

    replacements = {
        "<student-id>": STUDENT_ID,
        "<assigned-router-ip>": ROUTER_IP,
        "<unused-ipv4>": str(address),
    }

    count = 0

    # Read only original YAML files; never overwrite the templates.
    for source in sorted(source_dir.glob("*.yaml")):
        content = source.read_text(encoding="utf-8")

        for placeholder, value in replacements.items():
            content = content.replace(placeholder, value)

        if any(key in content for key in replacements):
            raise ValueError(
                f"Unfilled placeholder remains in {source.name}"
            )

        destination = output_dir / source.name
        destination.write_text(content, encoding="utf-8")
        count += 1

    print(f"Generated {count} YAML files.")
    print(f"Student ID: {STUDENT_ID}")
    print(f"Router: {ROUTER_IP}")
    print(f"Loopback: Loopback{STUDENT_ID}")
    print(f"Description: IPA2026-{STUDENT_ID}")
    print(f"IPv4: {address}/32")
    print(f"Output directory: {output_dir}")


if __name__ == "__main__":
    main()
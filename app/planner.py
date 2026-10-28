def build_plan(desired_interface, current_interface):
    """
    Compare desired interface state with normalized current state
    and return a plan according to specs/plan-spec-v1.md.
    """
    # TODO: implement
    managed_fields = (
        "ipv4",
        "description",
        "admin_state",
    )

    # The interface does not exist: plan its creation.
    if current_interface is None:
        changes = {
            field: {"to": desired_interface[field]}
            for field in managed_fields
        }
        operation = "create"

    else:
        changes = {}

        # Compare only the managed fields.
        for field in managed_fields:
            current_value = current_interface[field]
            desired_value = desired_interface[field]

            if current_value != desired_value:
                changes[field] = {
                    "from": current_value,
                    "to": desired_value,
                }

        if changes:
            operation = "update"
        else:
            operation = "no_change"

    return {
        "status": "ok",
        "result": "planned",
        "operation": operation,
        "changes": changes,
    }

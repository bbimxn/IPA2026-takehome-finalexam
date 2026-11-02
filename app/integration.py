"""Part 4 student implementation."""
import yaml

from app.core import validate_request

from app.dispatcher import dispatch_request

from app.request_handler import validate_webex_envelope

def process_request(mentioned_people, attachment_path, bot_person_id):
    envelope_error = validate_webex_envelope(
        mentioned_people,
        attachment_path,
        bot_person_id,
    )

    if envelope_error is not None:
        return envelope_error

    try:
        with open(attachment_path, "r", encoding="utf-8") as file:
            data = yaml.safe_load(file)
    except (OSError, UnicodeError, yaml.YAMLError, TypeError, ValueError):
        return {
            "status": "error",
            "result": "invalid_yaml",
        }

    validation_result = validate_request(data)

    if validation_result.get("status") != "ok":
        return validation_result

    return dispatch_request(data)

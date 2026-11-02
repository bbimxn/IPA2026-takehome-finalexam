"""Part 4 student implementation."""

import json

import logging

import os

from concurrent.futures import ThreadPoolExecutor

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from pathlib import Path

from tempfile import TemporaryDirectory

from app.integration import process_request

from app.webex_client import WEBEX_API_BASE, WebexClient

class WebexEventHandler:
    def __init__(self, client, bot_person_id, processor=None):
        self.client = client
        self.bot_person_id = bot_person_id
        self.processor = processor if processor is not None else process_request

    def handle_event(self, event):
        if not isinstance(event, dict):
            return None

        if event.get("resource") != "messages":
            return None

        if event.get("event") != "created":
            return None

        event_data = event.get("data")

        if not isinstance(event_data, dict):
            return None

        message_id = event_data.get("id")

        if not isinstance(message_id, str) or not message_id:
            return None

        # Ignore the bot's own event before fetching the message.
        if event_data.get("personId") == self.bot_person_id:
            return None

        message = self.client.get_message(message_id)

        if not isinstance(message, dict):
            return None

        # Check the actual message author to prevent reply loops.
        if message.get("personId") == self.bot_person_id:
            return None

        room_id = message.get("roomId")

        if not isinstance(room_id, str) or not room_id:
            return None

        mentioned_people = message.get("mentionedPeople", [])

        if not isinstance(mentioned_people, list):
            mentioned_people = []

        attachments = message.get("files") or []

        if not isinstance(attachments, list):
            return None

        if len(attachments) > 1:
            result = {
                "status": "error",
                "result": "multiple_attachments",
            }

        else:
            try:
                if len(attachments) == 0:
                    result = self.processor(
                        mentioned_people,
                        None,
                        self.bot_person_id,
                    )

                else:
                    with TemporaryDirectory() as temp_dir:
                        attachment_path = Path(temp_dir) / "request.yaml"

                        content = self.client.download_file(
                            attachments[0]
                        )

                        attachment_path.write_bytes(content)

                        result = self.processor(
                            mentioned_people,
                            attachment_path,
                            self.bot_person_id,
                        )

            except Exception:
                logging.exception(
                    "Failed to process Webex message"
                )

                result = {
                    "status": "error",
                    "result": "backend_failed",
                }

        if not isinstance(result, dict):
            result = {
                "status": "error",
                "result": "backend_failed",
            }

        self.client.send_message(
            room_id,
            json.dumps(result),
        )

        return result


def make_http_handler(submit_event):
    class WebhookRequestHandler(BaseHTTPRequestHandler):
        def _send_json(self, status_code, payload):
            body = json.dumps(payload).encode("utf-8")

            self.send_response(status_code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if self.path == "/health":
                self._send_json(
                    200,
                    {
                        "status": "ok",
                        "result": "healthy",
                    },
                )
            else:
                self._send_json(
                    404,
                    {
                        "status": "error",
                        "result": "not_found",
                    },
                )

        def do_POST(self):
            if self.path != "/webhook":
                self._send_json(
                    404,
                    {
                        "status": "error",
                        "result": "not_found",
                    },
                )
                return

            content_length = self.headers.get("Content-Length")

            try:
                body_length = int(content_length)
            except (TypeError, ValueError):
                body_length = 0

            if body_length < 1 or body_length > 1_000_000:
                self._send_json(
                    400,
                    {
                        "status": "error",
                        "result": "invalid_event",
                    },
                )
                return

            try:
                body = self.rfile.read(body_length)
                event = json.loads(body)

            except (json.JSONDecodeError, UnicodeDecodeError):
                self._send_json(
                    400,
                    {
                        "status": "error",
                        "result": "invalid_event",
                    },
                )
                return

            if not isinstance(event, dict):
                self._send_json(
                    400,
                    {
                        "status": "error",
                        "result": "invalid_event",
                    },
                )
                return

            try:
                submit_event(event)
            except Exception:
                logging.exception("Failed to submit webhook event")

                self._send_json(
                    500,
                    {
                        "status": "error",
                        "result": "internal_error",
                    },
                )
                return

            self._send_json(
                200,
                {
                    "status": "ok",
                    "result": "accepted",
                },
            )

        def log_message(self, format_string, *args):
            logging.info(
                "%s - %s",
                self.address_string(),
                format_string % args,
            )

    return WebhookRequestHandler


def main():
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO")
    )

    client = WebexClient()

    # Resolve the bot's person ID using its Bot Access Token.
    response = client.session.get(
        f"{WEBEX_API_BASE}/people/me",
        headers=client.headers,
        timeout=10,
    )

    response.raise_for_status()

    bot_person_id = response.json().get("id")

    if not isinstance(bot_person_id, str) or not bot_person_id:
        raise RuntimeError("Unable to retrieve Webex bot person ID")

    event_handler = WebexEventHandler(
        client,
        bot_person_id,
    )

    # A single worker processes router operations sequentially.
    executor = ThreadPoolExecutor(max_workers=1)

    def submit_event(event):
        return executor.submit(
            event_handler.handle_event,
            event,
        )

    host = os.getenv("WEBHOOK_HOST", "0.0.0.0")
    port = int(os.getenv("WEBHOOK_PORT", "8000"))

    server = ThreadingHTTPServer(
        (host, port),
        make_http_handler(submit_event),
    )

    logging.info(
        "Starting Webex webhook server on %s:%s",
        host,
        port,
    )

    try:
        server.serve_forever()

    except KeyboardInterrupt:
        logging.info("Stopping webhook server")

    finally:
        server.server_close()
        executor.shutdown(wait=True)


if __name__ == "__main__":
    main()

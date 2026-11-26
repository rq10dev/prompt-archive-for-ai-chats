r"""Native messaging host for the "Prompt Archive for AI Chats" browser extension.

Part of "Prompt Archive for AI Chats" by Rahil Qureshi (MIT License).

The browser starts this program for each message the extension sends (a prompt you just sent
on ChatGPT / Claude.ai / Gemini / AI Studio, an exported chat, or a chat title). It queues the
message in ~/prompt_archive/.ai_chat_inbox.jsonl, updates the month files with
export_prompt_history.py --no-scan, and replies to the browser. Nothing is sent over the network.

Registered as com.prompt_archive.host by install.ps1 (per user, under
HKCU\Software\Microsoft\Edge\NativeMessagingHosts and the Chrome equivalent).
Protocol: 4-byte little-endian length + UTF-8 JSON, on stdin/stdout.
"""
import contextlib
import io
import json
import struct
import sys
import traceback
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import export_prompt_history as archive  # noqa: E402

ERR = archive.ARCHIVE / "errors.log"
ALLOWED = {"ARCHIVE_PROMPT", "ARCHIVE_EXPORT", "ARCHIVE_TITLE"}
MAX_BYTES = 8 * 1024 * 1024


def read_message():
    raw_len = sys.stdin.buffer.read(4)
    if len(raw_len) < 4:
        return None
    (length,) = struct.unpack("<I", raw_len)
    if length > MAX_BYTES:
        raise ValueError(f"message too large: {length} bytes")
    return json.loads(sys.stdin.buffer.read(length).decode("utf-8"))


def send_message(obj):
    data = json.dumps(obj).encode("utf-8")
    sys.stdout.buffer.write(struct.pack("<I", len(data)) + data)
    sys.stdout.buffer.flush()


def log_error():
    try:
        archive.ARCHIVE.mkdir(parents=True, exist_ok=True)
        with ERR.open("a", encoding="utf-8") as fh:
            fh.write(f"{datetime.now().isoformat()} ai_chat_host\n{traceback.format_exc()}\n")
    except Exception:
        pass


def main():
    msg = read_message()
    if not isinstance(msg, dict) or msg.get("type") not in ALLOWED:
        send_message({"ok": False, "error": "unsupported message"})
        return
    try:
        archive.append_inbox(msg)  # queued first: never lost even if the update below fails
    except Exception:
        log_error()
        send_message({"ok": False, "error": "could not queue prompt"})
        return
    try:
        # stdout belongs to the browser protocol: swallow the exporter's progress output
        with contextlib.redirect_stdout(io.StringIO()):
            archive.main(["--no-scan"])
        send_message({"ok": True})
    except Exception:
        log_error()
        send_message({"ok": True, "queued": True, "note": "archive update deferred to next run"})


if __name__ == "__main__":
    try:
        main()
    except Exception:
        log_error()

"""Offline transport worker checks; never reaches Telegram or FirstVDS."""

import importlib.util
from pathlib import Path


path = Path(__file__).resolve().with_name("nyan_telegram_relay_worker.py")
spec = importlib.util.spec_from_file_location("relay_worker_test_target", path)
worker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(worker)

calls = []


def fake_request(url, *, data=None, secret=""):
    assert secret == "fake-secret"
    calls.append((url, data))
    if "/pull" in url:
        return {"ok": True, "items": [
            {"id": 7, "lease_token": "a" * 40, "chat_id": 202, "text": "hello"},
            {"id": 8, "lease_token": "b" * 40, "chat_id": 303, "text": "error"},
        ]}
    if "/ack" in url:
        return {"ok": True}
    raise AssertionError("unexpected endpoint")


def fake_send(_token, chat_id, body):
    if chat_id == 303:
        raise worker.RelayError("bot blocked", permanent=True)
    assert chat_id == 202 and body == "hello"
    return 10001


worker.request_json = fake_request
worker.send_one = fake_send
worker.time.sleep = lambda _: None
assert worker.cycle("https://wallet.example", "fake-secret", "fake-bot-token") == 2
acks = [data for url, data in calls if url.endswith("/ack")]
assert len(acks) == 2
assert acks[0]["delivered"] and acks[0]["telegram_message_id"] == 10001
assert not acks[1]["delivered"] and acks[1]["permanent_failure"]
assert acks[1]["error"] == "bot blocked"
print("PASS: worker delivery ACK, permanent Telegram failures, correct recipients")

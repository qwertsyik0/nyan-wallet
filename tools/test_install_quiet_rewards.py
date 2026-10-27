"""Offline-only checks for the surgical notification update."""

from pathlib import Path

from install_quiet_rewards import (
    AUDIT_NEW, AUDIT_OLD, RELAY_NEW, RELAY_OLD, patch_audit, patch_relay,
)


ROOT = Path(__file__).resolve().parents[1]
relay = (ROOT / "server" / "telegram_relay.py").read_text()
audit = (ROOT / "server" / "instant_notifications.py").read_text()

assert patch_relay(relay) == relay, "GitHub relay policy must be treated as already installed"
assert patch_audit(audit) == audit, "GitHub audit policy must be treated as already installed"

# Exercise a server with the older exact-style lines, not GitHub's constants.
old_relay = relay.replace(
    '    if (\n        core.OWNER_TELEGRAM_ID\n        and int(target.telegram_id) != int(core.OWNER_TELEGRAM_ID)\n        and operation not in OWNER_SILENT_REWARD_OPERATIONS\n    ):',
    RELAY_OLD,
)
assert old_relay != relay
patched_relay = patch_relay(old_relay.replace(
    'OWNER_SILENT_REWARD_OPERATIONS = frozenset({\n    "daily_task", "achievement", "fortune_spin",\n})',
    'LEGACY_OWNER_POLICY = frozenset({})',
))
assert RELAY_NEW in patched_relay
assert patch_relay(patched_relay) == patched_relay

old_audit = audit.replace(
    '    if not core.OWNER_TELEGRAM_ID or target.action in OWNER_SILENT_AUDIT_ACTIONS:', AUDIT_OLD,
).replace('OWNER_SILENT_AUDIT_ACTIONS = frozenset({"task_approved"})',
          'LEGACY_AUDIT_POLICY = frozenset({})')
assert old_audit != audit
patched_audit = patch_audit(old_audit)
assert AUDIT_NEW in patched_audit
assert patch_audit(patched_audit) == patched_audit

for patcher in (patch_relay, patch_audit):
    try:
        patcher("# incompatible local customization\n")
    except RuntimeError:
        pass
    else:
        raise AssertionError("An incompatible local version must not be overwritten")

print("PASS: surgical notification patch preserves local files and is idempotent")

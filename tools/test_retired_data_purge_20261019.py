"""Static safety checks for the 2026-10-19 archived-feature database purge."""
from pathlib import Path
import re

root = Path(__file__).resolve().parents[1]
backend = (root / "server" / "__init__.py").read_text(encoding="utf-8")
shell = (root / "tools" / "purge_retired_nyan_data_20261019.sh").read_text(encoding="utf-8")

for call in (
    "register_elections(backend_app.app)",
    "register_elections_voting(backend_app.app)",
    "register_wallet_survey(backend_app.app)",
    "register_finance_recruitment(backend_app.app)",
    "register_finance_stage2(backend_app.app)",
    "send_survey_channel_followups_20261011()",
):
    assert call not in backend, call

assert "register_finance_workspace(backend_app.app)" in backend
assert "register_maintenance(backend_app.app)" in backend
assert "register_transfers(backend_app.app)" in backend
assert "register_giveaways(backend_app.app)" in backend

allowlist = shell.split('TABLE_NAMES="', 1)[1].split('"', 1)[0]
tables = set(allowlist.split())
assert len(tables) == 19
for name in ("election_votes", "election_ballot_parties", "election_seasons",
             "wallet_survey_responses", "survey_channel_followups",
             "financial_admin_applications", "finance_stage2_responses",
             "finance_stage2_invitations"):
    assert name in tables
for protected in ("users", "transactions", "finance_trainees",
                  "finance_decision_requests", "finance_telegram_deliveries",
                  "wallet_notifications"):
    assert protected not in tables

for guard in ("pg_dump --format=custom", "pg_restore --list",
              "sha256sum", "TRUNCATE TABLE %s RESTRICT",
              'BACKUP_DIR="/root/nyan_wallet_backups"',
              "ON_ERROR_STOP=1", "BEGIN;", "COMMIT;", "/api/health"):
    assert guard in shell, guard
assert not re.search(r'\bDROP\s+TABLE\b|\bTRUNCATE\s+TABLE\s+\$.*CASCADE', shell)
print("PASS: retired APIs disabled and full-backup, FK-safe DB purge guards present")

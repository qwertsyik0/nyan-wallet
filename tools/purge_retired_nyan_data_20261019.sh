#!/usr/bin/env bash
# One-time Nyan Wallet cleanup, 2026-10-19.
# Run ONCE as root on the PostgreSQL host, AFTER deploying the backend that
# disables Elections, wallet-survey and finance-recruitment routes.
# A full custom-format database backup is saved BEFORE any data change.
set -Eeuo pipefail
umask 077

if [ "$(id -u)" -ne 0 ]; then
  echo "ERROR: run as root on the Nyan Wallet PostgreSQL server." >&2
  exit 1
fi
for bin in runuser psql pg_dump pg_restore curl sha256sum; do
  if ! command -v "$bin" >/dev/null 2>&1; then
    echo "ERROR: missing required command: $bin" >&2
    exit 1
  fi
done

DB="nyan_wallet_db"
API="https://nyan-wallet-153-76-175-145.sslip.io"
BACKUP_DIR="/root/nyan_wallet_backups"

echo "Host: $(hostname) | database: $DB"
actual_db="$(runuser -u postgres -- psql -XAt -v ON_ERROR_STOP=1 -d "$DB" -c 'SELECT current_database()')"
if [ "$actual_db" != "$DB" ]; then
  echo "ERROR: wrong database ($actual_db); nothing was deleted." >&2
  exit 1
fi

# Refuse to purge while public endpoints can still accept votes/answers/forms.
health="$(curl --connect-timeout 5 --max-time 12 -sS -o /dev/null -w '%{http_code}' "$API/api/health")"
if [ "$health" != "200" ]; then
  echo "ERROR: API health is HTTP $health. Deploy/verify the production backend first." >&2
  exit 1
fi
for endpoint in \
  "/api/elections" \
  "/api/elections/voting/status" \
  "/api/wallet-survey/status" \
  "/api/owner/wallet-survey/results" \
  "/api/recruitment/finance/me" \
  "/api/recruitment/finance/stage2/me"; do
  status="$(curl --connect-timeout 5 --max-time 12 -sS -o /dev/null -w '%{http_code}' "$API$endpoint")"
  if [ "$status" != "404" ]; then
    echo "ERROR: $endpoint returned HTTP $status, expected 404." >&2
    echo "Deploy the retired-API backend first. Nothing was deleted." >&2
    exit 1
  fi
done
echo "OK: retired public API routes are no longer available."

# Explicit allowlist. Do NOT include users, balances, transactions, audit,
# finance_trainees, finance_decision_requests, or their notifications.
TABLE_NAMES="
election_seasons
election_parties
election_party_emblems
election_memberships
election_games_signups
election_ballot_controls
election_ballot_parties
election_votes
election_initial_rollback_20261016
election_phase_undo_20261017
election_campaign_open_20261017
election_nsn_member_letters_20261017
election_party_group_letters_20261017
election_debate_letters_20261017
wallet_survey_responses
survey_channel_followups
financial_admin_applications
finance_stage2_responses
finance_stage2_invitations
"

quoted=""
for table in $TABLE_NAMES; do
  case "$table" in
    *[!a-z0-9_]*|"") echo "ERROR: unsafe table identifier" >&2; exit 1 ;;
  esac
  if [ -n "$quoted" ]; then quoted="$quoted,"; fi
  quoted="$quoted'$table'"
done

existing="$(runuser -u postgres -- psql -XAt -v ON_ERROR_STOP=1 -d "$DB" -c "SELECT tablename FROM pg_tables WHERE schemaname='public' AND tablename IN ($quoted) ORDER BY tablename;")"
for required in election_seasons election_votes wallet_survey_responses financial_admin_applications; do
  if ! printf '%s\n' "$existing" | grep -Fxq "$required"; then
    echo "ERROR: expected table $required is missing; no data changed." >&2
    exit 1
  fi
done

unknown="$(runuser -u postgres -- psql -XAt -v ON_ERROR_STOP=1 -d "$DB" -c "
  SELECT tablename FROM pg_tables
  WHERE schemaname='public'
    AND (tablename LIKE 'election_%'
         OR tablename LIKE 'wallet_survey_%'
         OR tablename LIKE 'finance_stage2_%'
         OR tablename='financial_admin_applications'
         OR tablename='survey_channel_followups')
    AND tablename NOT IN ($quoted)
  ORDER BY tablename;")"
if [ -n "$unknown" ]; then
  echo "ERROR: new/unreviewed feature tables found. Refusing partial cleanup:" >&2
  echo "$unknown" >&2
  exit 1
fi

tables_sql=""
echo "Rows BEFORE:"
for table in $existing; do
  count="$(runuser -u postgres -- psql -XAt -v ON_ERROR_STOP=1 -d "$DB" -c "SELECT COUNT(*) FROM public.$table;")"
  printf '  %s: %s\n' "$table" "$count"
  if [ -n "$tables_sql" ]; then tables_sql="$tables_sql, "; fi
  tables_sql="$tables_sql public.$table"
done

mkdir -p "$BACKUP_DIR"
chmod 700 "$BACKUP_DIR"
BACKUP="$BACKUP_DIR/nyan_wallet_before_retired_data_purge_$(date -u +%Y%m%dT%H%M%SZ)_$$.dump"
echo "Creating FULL database backup: $BACKUP"
runuser -u postgres -- pg_dump --format=custom --no-owner --no-privileges --dbname "$DB" > "$BACKUP"
if [ ! -s "$BACKUP" ]; then
  echo "ERROR: backup is empty. Nothing deleted." >&2
  exit 1
fi
pg_restore --list "$BACKUP" >/dev/null
sha256sum "$BACKUP" > "$BACKUP.sha256"
chmod 600 "$BACKUP" "$BACKUP.sha256"
echo "Full backup created and archive format verified."

# TRUNCATE ... RESTRICT is atomic and refuses foreign keys from unrelated
# tables. No CASCADE, no schema drops, no balance/transaction modifications.
echo "Purging listed feature rows in ONE transaction..."
printf "BEGIN;\nSET LOCAL lock_timeout = '10s';\nSET LOCAL statement_timeout = '120s';\nTRUNCATE TABLE %s RESTRICT;\nCOMMIT;\n" "$tables_sql" \
  | runuser -u postgres -- psql -X -v ON_ERROR_STOP=1 --dbname "$DB"

echo "Rows AFTER:"
for table in $existing; do
  count="$(runuser -u postgres -- psql -XAt -v ON_ERROR_STOP=1 -d "$DB" -c "SELECT COUNT(*) FROM public.$table;")"
  printf '  %s: %s\n' "$table" "$count"
  if [ "$count" != "0" ]; then
    echo "WARNING: a retired table was repopulated after cleanup: $table" >&2
    exit 1
  fi
done
echo "SUCCESS. All retired-feature tables are empty."
echo "BACKUP: $BACKUP"
echo "SHA256: $BACKUP.sha256"
echo "Existing wallets, ledger transactions and active finance trainees were NOT touched."

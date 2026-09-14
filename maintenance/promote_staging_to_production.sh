#!/usr/bin/env bash
set -euo pipefail

MODE="dry-run"
if [[ "${1:-}" == "--promote" ]]; then
  MODE="promote"
elif [[ -n "${1:-}" ]]; then
  echo "Usage: $0 [--promote]" >&2
  exit 2
fi

REPO_ROOT="${REPO_ROOT:-/home/pi/coaster-collection}"
APP_DIR="${APP_DIR:-$REPO_ROOT/flow-finance}"
STAGING_DB="${STAGING_DB:-/home/pi/flow-finance-staging/flow.db}"
PROD_DB="${PROD_DB:-$APP_DIR/data/flow.db}"
BACKUP_DIR="${BACKUP_DIR:-/var/lib/flow-finance-maintenance/backups}"
TMP_DB="${PROD_DB}.candidate"
CONTAINER_NAME="${CONTAINER_NAME:-flow-finance}"
HEALTH_URL="${HEALTH_URL:-http://localhost:8010/api/health}"
INTELLIGENCE_URL="${INTELLIGENCE_URL:-http://localhost:8010/api/finance/intelligence?history_months=12}"
EXPECTED_TX_COUNT_MIN="${EXPECTED_TX_COUNT_MIN:-1949}"

python_sqlite_check() {
  local db="$1"
  python3 - "$db" <<'PY'
import sqlite3, sys
p=sys.argv[1]
con=sqlite3.connect(p)
try:
    integrity=con.execute('PRAGMA integrity_check').fetchone()[0]
    tx=con.execute('SELECT COUNT(*) FROM transactions').fetchone()[0]
    settings={r[0]:r[1] for r in con.execute("SELECT key,value FROM settings WHERE key IN ('notion_source_revision','safety_reserve_cents')")}
    tables={r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    required={'transactions','accounts','settings','recurring_transactions'}
    missing=sorted(required-tables)
    print(f'integrity={integrity}')
    print(f'transactions={tx}')
    print(f"notion_source_revision={settings.get('notion_source_revision','')}")
    print(f"safety_reserve_cents={settings.get('safety_reserve_cents','')}")
    if integrity != 'ok':
        raise SystemExit('SQLite integrity_check failed')
    if missing:
        raise SystemExit(f'Missing required tables: {missing}')
finally:
    con.close()
PY
}

count_transactions() {
  python3 - "$1" <<'PY'
import sqlite3, sys
con=sqlite3.connect(sys.argv[1])
try:
    print(con.execute('SELECT COUNT(*) FROM transactions').fetchone()[0])
finally:
    con.close()
PY
}

copy_candidate_with_prod_permissions() {
  local source_db="$1"
  sudo rm -f "$TMP_DB"
  sudo cp -a "$source_db" "$TMP_DB"
  sudo chown --reference="$PROD_DB" "$TMP_DB"
  sudo chmod --reference="$PROD_DB" "$TMP_DB"
}

replace_production_atomically() {
  sudo mv -f "$TMP_DB" "$PROD_DB"
  sync
}

if [[ ! -f "$STAGING_DB" ]]; then
  echo "ERROR staging DB not found: $STAGING_DB" >&2
  exit 1
fi
if [[ ! -f "$PROD_DB" ]]; then
  echo "ERROR production DB not found: $PROD_DB" >&2
  exit 1
fi

mkdir -p "$BACKUP_DIR"

echo "mode=$MODE"
echo "staging=$STAGING_DB"
echo "production=$PROD_DB"
echo "backup_dir=$BACKUP_DIR"

echo "--- staging preflight ---"
python_sqlite_check "$STAGING_DB"
STAGING_TX="$(count_transactions "$STAGING_DB")"
if (( STAGING_TX < EXPECTED_TX_COUNT_MIN )); then
  echo "ERROR staging transactions=$STAGING_TX < expected minimum=$EXPECTED_TX_COUNT_MIN" >&2
  exit 1
fi

echo "--- production preflight ---"
python_sqlite_check "$PROD_DB"
PROD_TX="$(count_transactions "$PROD_DB")"

echo "staging_transactions=$STAGING_TX"
echo "production_transactions=$PROD_TX"

if [[ "$MODE" == "dry-run" ]]; then
  echo "summary status=ready dry_run=true staging_transactions=$STAGING_TX production_transactions=$PROD_TX"
  echo "No files changed. Run again with --promote to perform the atomic promotion."
  exit 0
fi

STAMP="$(date +%Y%m%d_%H%M%S)"
BACKUP_DB="$BACKUP_DIR/flow.db.$STAMP.bak"
ROLLBACK_NEEDED=0

rollback() {
  if [[ "$ROLLBACK_NEEDED" == "1" ]]; then
    echo "ERROR promotion failed; restoring backup $BACKUP_DB" >&2
    docker stop "$CONTAINER_NAME" >/dev/null 2>&1 || true
    copy_candidate_with_prod_permissions "$BACKUP_DB"
    replace_production_atomically
    cd "$APP_DIR"
    docker compose up -d --build >/dev/null
    echo "rollback=completed" >&2
  fi
}
trap rollback ERR

echo "--- backup production ---"
cp -a "$PROD_DB" "$BACKUP_DB"
python_sqlite_check "$BACKUP_DB"
echo "backup=$BACKUP_DB"
ROLLBACK_NEEDED=1

echo "--- stop application ---"
docker stop "$CONTAINER_NAME" >/dev/null

echo "--- promote atomically ---"
copy_candidate_with_prod_permissions "$STAGING_DB"
python_sqlite_check "$TMP_DB"
replace_production_atomically

echo "--- restart application ---"
cd "$APP_DIR"
docker compose up -d --build >/dev/null

for _ in $(seq 1 30); do
  if curl -fsS "$HEALTH_URL" >/dev/null; then
    break
  fi
  sleep 1
done
curl -fsS "$HEALTH_URL" >/dev/null

RESPONSE="$(curl -fsS "$INTELLIGENCE_URL")"
python3 - "$RESPONSE" <<'PY'
import json, sys
p=json.loads(sys.argv[1])
headline=p.get('headline',{})
quality=p.get('data_quality',{})
print(f"safe_to_spend_cents={headline.get('safe_to_spend_cents')}")
print(f"expected_remaining_at_horizon_cents={headline.get('expected_remaining_at_horizon_cents')}")
print(f"next_salary_date={headline.get('next_salary_date')}")
print(f"bank_coverage_end={quality.get('bank_coverage_end')}")
if headline.get('safe_to_spend_cents') is None:
    raise SystemExit('Intelligence endpoint returned unavailable safe_to_spend')
PY

python_sqlite_check "$PROD_DB"
ROLLBACK_NEEDED=0
trap - ERR

echo "summary status=promoted backup=$BACKUP_DB staging_transactions=$STAGING_TX production_transactions_before=$PROD_TX"

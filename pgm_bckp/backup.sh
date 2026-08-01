#!/bin/bash
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/config.sh"

LOG_DIR="$SCRIPT_DIR/$log_dir"
mkdir -p "$LOG_DIR"
RUN_TIMESTAMP=$(date +%Y%m%d_%H%M%S)
LOG_FILE="$LOG_DIR/backup_${RUN_TIMESTAMP}.log"
ln -sf "$LOG_FILE" "$LOG_DIR/latest.log"   # comodo per controllare l'ultimo run senza cercare la data

log() { echo "$(date '+%Y-%m-%d %H:%M:%S') $*" | tee -a "$LOG_FILE"; }

notify() {
    # notify "title" "message" "priority(1-10)"
    [ -z "$gotify_url" ] && return 0
    curl -s -X POST "$gotify_url/message?token=$gotify_token" \
         -F "title=$1" -F "message=$2" -F "priority=$3" >/dev/null
}

# --- Lock: evita run sovrapposti (es. se un dump precedente è ancora in corso) ---
exec 9>"$lock_file"
if ! flock -n 9; then
    log "❌ Uno script di backup è già in esecuzione. Uscita."
    exit 1
fi

# --- Check dipendenze ---
missing=0
command -v mysqldump >/dev/null 2>&1 || { log "❌ mysqldump not found. Install: sudo apt install mariadb-client"; missing=1; }
command -v pg_dump   >/dev/null 2>&1 || { log "❌ pg_dump not found. Install: sudo apt install postgresql-client"; missing=1; }
command -v gzip      >/dev/null 2>&1 || { log "❌ gzip not found."; missing=1; }
if [ "$missing" -eq 1 ]; then
    log "❌ Aborting: Required tools are missing."
    notify "Backup - ERROR" "Tool mancanti sul sistema di backup, controlla i log." 8
    exit 1
fi

mkdir -p "$backup_dir"

success_count=0
fail_count=0
fail_names=()

for db_id in "${database_ids[@]}"; do
    IFS='|' read -r db_type db_name db_host db_port db_user db_pass <<< "${!db_id}"
    timestamp=$(date +%Y%m%d%H%M%S)
    raw_file="$backup_dir/${db_name}-${timestamp}.sql"
    gz_file="${raw_file}.gz"

    case "$db_type" in
        mysql)
            # Password via env var invece che come argomento -> non finisce in `ps aux`
            MYSQL_PWD="$db_pass" mysqldump \
                --single-transaction \
                --user="$db_user" --host="$db_host" --port="$db_port" \
                --databases "$db_name" > "$raw_file" 2>>"$LOG_FILE"
            dump_rc=$?
            ;;
        postgres)
            export PGPASSWORD="$db_pass"
            pg_dump --username="$db_user" --host="$db_host" --port="$db_port" \
                --format=plain --file="$raw_file" "$db_name" 2>>"$LOG_FILE"
            dump_rc=$?
            unset PGPASSWORD
            ;;
        *)
            log "❌ Unsupported database type: $db_type for $db_name"
            fail_count=$((fail_count+1))
            fail_names+=("$db_name (tipo non supportato)")
            continue
            ;;
    esac

    # Controllo: comando ok E file non vuoto (un dump troncato è comunque un fallimento)
    if [ "$dump_rc" -eq 0 ] && [ -s "$raw_file" ]; then
        gzip -f "$raw_file"
        log "✅ Backup di '$db_name' ($db_type) completato: $gz_file"
        success_count=$((success_count+1))
    else
        log "❌ Errore durante il backup di '$db_name' ($db_type) - file vuoto o comando fallito"
        rm -f "$raw_file"
        fail_count=$((fail_count+1))
        fail_names+=("$db_name")
    fi

    # Cleanup retention (ora su file .gz)
    find "$backup_dir" -type f -name "${db_name}-*.sql.gz" -mtime +"$backup_retention_days" -exec rm -f {} \;
done

# --- Notifica riassuntiva ---
if [ "$fail_count" -eq 0 ]; then
    notify "Backup - SUCCESS" "$success_count database salvati correttamente." 5
else
    joined_fails=$(IFS=', '; echo "${fail_names[*]}")
    notify "Backup - PARTIAL/ERROR" "$success_count ok, $fail_count falliti: $joined_fails" 8
fi

log "Riepilogo: $success_count ok, $fail_count falliti."

# Pulizia log vecchi (il symlink latest.log non viene toccato: punta sempre all'ultimo run)
find "$LOG_DIR" -type f -name "backup_*.log" -mtime +"$log_retention_days" -exec rm -f {} \;

exit $([ "$fail_count" -eq 0 ] && echo 0 || echo 1)

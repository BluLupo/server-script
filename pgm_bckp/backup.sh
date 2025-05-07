#!/bin/bash

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/config.sh"

# Check if required commands are available
missing=0

command -v mysqldump >/dev/null 2>&1 || { echo "❌ mysqldump not found. Install it with: sudo apt install mariadb-client or sudo apt install mysql-client"; missing=1; }
command -v pg_dump >/dev/null 2>&1 || { echo "❌ pg_dump not found. Install it with: sudo apt install postgresql-client"; missing=1; }

if [ "$missing" -eq 1 ]; then
    echo "❌ Aborting: Required tools are missing."
    exit 1
fi


mkdir -p "$backup_dir"

for db_id in "${database_ids[@]}"; do
    IFS='|' read -r db_type db_name db_host db_port db_user db_pass <<< "${!db_id}"
    timestamp=$(date +%Y%m%d%H%M%S)
    backup_file="$backup_dir/$db_name-$timestamp.sql"

    case "$db_type" in
        mysql)
            mysqldump --user="$db_user" --password="$db_pass" --host="$db_host" --port="$db_port" --databases "$db_name" > "$backup_file"
            ;;
        postgres)
            export PGPASSWORD="$db_pass"
            pg_dump --username="$db_user" --host="$db_host" --port="$db_port" --format=plain --file="$backup_file" "$db_name"
            ;;
        *)
            echo "❌ Unsupported database type: $db_type for $db_name"
            continue
            ;;
    esac

    if [ $? -eq 0 ]; then
        echo "✅ Backup of $db_type database '$db_name' completed: $backup_file"
    else
        echo "❌ Error during backup of $db_type database '$db_name'"
        rm -f "$backup_file"
    fi

    # Cleanup
    find "$backup_dir" -type f -name "$db_name-*.sql" -mtime +$backup_retention_days -exec rm -f {} \;
done

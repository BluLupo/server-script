#!/bin/bash

# Import the configuration file
source config.sh

# Cycle through all the databases and back up each one
for db_name in "${databases[@]}"; do
    # Compose the backup file name
    backup_file="$backup_dir/$db_name-$(date +%Y%m%d%H%M%S).sql"

    # Execute the mysqldump command to export the database
    mysqldump --user="$db_user" --password="$db_pass" --host="$db_host" --port="$db_port" --databases "$db_name" > "$backup_file"

    # Check if the backup was successful
    if [ $? -eq 0 ]; then
        echo "Backup of $db_name completed successfully in $backup_file"
    else
        echo "An error occurred during the backup of $db_name"
    fi

    # Delete backups older than specified retention period
    find "$backup_dir" -type f -name "$db_name-*.sql" -mtime +$backup_retention_days -exec rm {} \;
done

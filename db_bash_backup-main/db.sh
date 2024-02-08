#!/bin/bash

# Import the configuration file
source config.sh

# Cycle through all the databases and back up each one
for db_name in "${databases[@]}"; do
    # Compongo il nome del file di backup
    backup_file="$backup_dir/$db_name-$(date +%Y%m%d%H%M%S).sql"

    # I run the mysqldump command to export the database
    mysqldump --user="$db_user" --password="$db_pass" --host="$db_host" --port="$db_port" --databases "$db_name" > "$backup_file"

    # If the backup was successful, I see a confirmation message
    if [ $? -eq 0 ]; then
        echo "Backup di $db_name completato con successo in $backup_file"
    else
        echo "Si è verificato un errore durante il backup di $db_name"
    fi
done

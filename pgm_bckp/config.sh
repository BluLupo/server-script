# Backup destination and retention
backup_dir="db_backup"
backup_retention_days=7

# List of database identifiers
database_ids=("db1" "db2" "pg1")

# For each database, define its parameters
# Format: type|name|host|port|user|password

db1="mysql|db1|127.0.0.1|3306|root|rootpass"
db2="mysql|db2|10.0.0.2|3307|backup_user|backup123"
pg1="postgres|my_pgdb|192.168.1.100|5432|pguser|pgpass"

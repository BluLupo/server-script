# 📦 Requirements

```bash
sudo apt update
sudo apt install mariadb-client postgresql-client
```

# ⚠️ Common Issues and Fixes

### ❌ mysqldump: command not found
### Cause: MySQL client is not installed.

Fix:
```bash
sudo apt install mariadb-client
```

### ❌ pg_dump: command not found

### Cause: PostgreSQL client is missing.
Fix:
```bash
sudo apt install postgresql-client
```

### ❌ pg_dump: error: aborting because of server version mismatch

### Cause: The local pg_dump is version 15, while the remote PostgreSQL server is version 17.
Fix: Install pg_dump version 17 from the official PostgreSQL (PGDG) repository:
```bash
# Add the official PostgreSQL repository
echo "deb http://apt.postgresql.org/pub/repos/apt/ bookworm-pgdg main" | sudo tee /etc/apt/sources.list.d/pgdg.list
wget --quiet -O - https://www.postgresql.org/media/keys/ACCC4CF8.asc | sudo gpg --dearmor -o /etc/apt/trusted.gpg.d/pgdg.gpg
sudo apt update

# Install the PostgreSQL 17 client
sudo apt install postgresql-client-17

```


# ⏰ Automating via Cron

Open your crontab:

```bash
crontab -e
```

Add a line like this to run the script daily at 1 AM:
```bash
0 1 * * * /path/to/backup.sh >> /path/to/logs/backup.log 2>&1
```

# 🔐 Security Tips
Restrict access to the config file containing credentials:

```bash
chmod 600 config.sh
```

# 📦 pgm_bckp

Script bash per backup automatici di database MySQL/MariaDB e PostgreSQL, con compressione, retention, lock anti-sovrapposizione, log per-esecuzione e notifiche opzionali via Gotify.

## 📁 Struttura

```
pgm_bckp/
├── backup.sh       # script principale
├── config.sh       # configurazione (database, retention, gotify) - NON versionare con password reali
├── db_backup/       # dump compressi (.sql.gz), creata automaticamente
└── logs/            # un file di log per ogni esecuzione, creata automaticamente
    ├── backup_20260801_010000.log
    └── latest.log   # symlink sempre puntato all'ultimo run
```

## ⚙️ Requirements

```bash
sudo apt update
sudo apt install mariadb-client postgresql-client
```

## 🔧 Configurazione

Modifica `config.sh`:

```bash
# Cartella dei dump e giorni di retention
backup_dir="db_backup"
backup_retention_days=7

# Log locali e relativa retention
log_dir="logs"
log_retention_days=14

# Notifiche Gotify (facoltative): lascia vuoti i due campi per disabilitarle
gotify_url=""
gotify_token=""

# Elenco identificatori database da backuppare
database_ids=("db1" "db2" "pg1")

# Un identificatore per riga, formato: type|name|host|port|user|password
db1="mysql|db1|127.0.0.1|3306|root|rootpass"
db2="mysql|db2|10.0.0.2|3307|backup_user|backup123"
pg1="postgres|my_pgdb|192.168.1.100|5432|pguser|pgpass"
```

Tipi supportati: `mysql`, `postgres`.

## ▶️ Uso

```bash
chmod +x backup.sh
./backup.sh
```

Per ogni database configurato:
1. esegue il dump (`mysqldump --single-transaction` / `pg_dump`);
2. verifica che il file non sia vuoto o troncato prima di considerarlo valido;
3. comprime il dump in `.sql.gz`;
4. rimuove i dump più vecchi di `backup_retention_days` giorni;
5. scrive tutto nel log dell'esecuzione corrente (`logs/backup_<timestamp>.log`).

A fine esecuzione, se configurato, invia una notifica Gotify riassuntiva (successo / parziale / errore).

## 📜 Log

Ogni run genera un file di log separato in `logs/`, così una singola esecuzione non si mischia con le precedenti. Per controllare rapidamente l'ultimo esito:

```bash
tail -f logs/latest.log
```

I log più vecchi di `log_retention_days` giorni vengono ripuliti automaticamente a ogni esecuzione (stesso meccanismo usato per i dump).

## 🔒 Lock anti-sovrapposizione

Lo script usa `flock` su `/tmp/pgm_bckp.lock`: se un'esecuzione precedente è ancora in corso (es. dump lento su un host remoto), la nuova esecuzione si ferma subito invece di partire in parallelo.

## ⏰ Automazione via Cron

```bash
crontab -e
```

Aggiungi una riga per eseguire il backup ogni giorno all'1:00:

```bash
0 1 * * * /path/to/backup.sh
```

Il logging è già gestito internamente dallo script (vedi sezione Log sopra), quindi non serve più reindirizzare stdout/stderr nel cron — a meno che tu non voglia comunque un log di sistema aggiuntivo:

```bash
0 1 * * * /path/to/backup.sh >> /path/to/cron.log 2>&1
```

## 🔐 Security Tips

- Restringi l'accesso al file di configurazione, che contiene credenziali in chiaro:
  ```bash
  chmod 600 config.sh
  ```
- Le password non vengono mai passate come argomento a `mysqldump`/`pg_dump` (visibili altrimenti in `ps aux`), ma tramite variabili d'ambiente (`MYSQL_PWD`, `PGPASSWORD`) valide solo per la durata del comando.
- Valuta di non versionare `config.sh` con credenziali reali (es. `.gitignore` + un `config.sh.example` come template).

## ⚠️ Common Issues and Fixes

### ❌ mysqldump: command not found
**Causa:** client MySQL/MariaDB non installato.
```bash
sudo apt install mariadb-client
```

### ❌ pg_dump: command not found
**Causa:** client PostgreSQL mancante.
```bash
sudo apt install postgresql-client
```

### ❌ pg_dump: error: aborting because of server version mismatch
**Causa:** il `pg_dump` locale è in versione diversa (es. 15) rispetto al server PostgreSQL remoto (es. 17).

**Fix:** installa la versione corrispondente dal repository ufficiale PostgreSQL (PGDG):
```bash
echo "deb http://apt.postgresql.org/pub/repos/apt/ bookworm-pgdg main" | sudo tee /etc/apt/sources.list.d/pgdg.list
wget --quiet -O - https://www.postgresql.org/media/keys/ACCC4CF8.asc | sudo gpg --dearmor -o /etc/apt/trusted.gpg.d/pgdg.gpg
sudo apt update
sudo apt install postgresql-client-17
```

### ❌ "Uno script di backup è già in esecuzione"
**Causa:** un'esecuzione precedente non è ancora terminata (lock attivo su `/tmp/pgm_bckp.lock`).

**Fix:** aspetta il completamento del run precedente, oppure controlla `logs/latest.log` per capire perché sta impiegando così tanto. Se il lock è rimasto "orfano" dopo un crash, puoi rimuoverlo manualmente:
```bash
rm -f /tmp/pgm_bckp.lock
```

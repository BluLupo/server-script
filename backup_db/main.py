#!/usr/bin/env python
# -*- coding: utf-8 -*-

# Copyright Hersel Giannella

import time
import schedule
from jobs.delete_files import delete_sql_files
from jobs.backup_db import backup

def get_time() -> str:
    return time.strftime('%X (%d/%m/%y)')

# Schedulazione del backup di tutti i database ogni giorno alle 4:00 AM
schedule.every().day.at("04:00").do(backup, dbname='dbname')
schedule.every().day.at("05:00").do(delete_sql_files)

# Loop infinito per eseguire lo scheduler
while True:
    schedule.run_pending()
    print("eseguo job",get_time())
    time.sleep(1)
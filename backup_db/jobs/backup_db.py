#!/usr/bin/env python
# -*- coding: utf-8 -*-

# Copyright Hersel Giannella

import os
import time
import subprocess
import pymysql
from config import Config

# set backup directory and filename
backup_file = os.path.join(Config.backup_dir, '{}backup.sql'.format(time.strftime('%d%m%Y-%H%M%S')))

def backup(dbname):
    try:
        conn = pymysql.connect(host=Config.db_host, user=Config.db_user, password=Config.db_password,
                               database=dbname)
    except pymysql.Error as err:
        print(f"Error connecting to database: {err}")
        exit()

    # create backup command
    backup_cmd = f"mysqldump -u {Config.db_user} -p'{Config.db_password}' {dbname} > {backup_file}"
    print(backup_cmd)

    # execute backup command
    subprocess.call(backup_cmd, shell=True)

    # close database connection
    conn.close()
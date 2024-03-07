#!/usr/bin/env python
# -*- coding: utf-8 -*-

# Copyright Hersel Giannella

import os
from config import Config
from datetime import datetime, timedelta

def delete_sql_files():
    try:
        # Verifica se la cartella esiste
        if not os.path.exists(Config.backup_dir):
            print(f"La cartella {Config.backup_dir} non esiste.")
            return

        # Ottiene la data di 7 giorni fa
        seven_days_ago = datetime.now() - timedelta(days=Config.retention_days)

        # Itera su tutti i file nella cartella
        for filename in os.listdir(Config.backup_dir):
            file_path = os.path.join(Config.backup_dir, filename)
            # Verifica se il file ha estensione .sql e se è stato creato 7 giorni fa, quindi lo elimina
            if filename.endswith(".sql") and datetime.fromtimestamp(os.path.getctime(file_path)).date() == seven_days_ago.date():
                os.remove(file_path)
                print(f"File eliminato: {file_path}")
    except Exception as e:
        print(f"Si è verificato un errore durante l'eliminazione dei file: {e}")

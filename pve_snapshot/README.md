# Sul nodo Proxmox (raccoglie + genera HTML)
```bash
python3 pve_inventory.py                        # dashboard HTML
python3 pve_inventory.py --json                 # HTML + JSON
python3 pve_inventory.py --json-only --stdout   # solo JSON a stdout
python3 pve_inventory.py --open                 # genera e apre nel browser
```

# Da un JSON già esistente (su qualsiasi PC)
```bash
python3 pve_inventory.py --from snapshot.json
python3 pve_inventory.py --from snapshot.json -o report.html --open
```

# Pipeline automatica via cron
```bash
0 6 * * * python3 /root/pve_inventory.py --json -o /var/www/html/pve.html
```
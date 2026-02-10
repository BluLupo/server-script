#!/usr/bin/env python3
"""
PVE Inventory — Snapshot + Dashboard in un unico script
=========================================================
Raccoglie dati dall'ambiente Proxmox e genera una dashboard HTML interattiva.
Può anche leggere un JSON esistente e generare solo la dashboard.

Modalità:
  1) Su nodo PVE (raccolta + dashboard):
     python3 pve_inventory.py                     # → HTML dashboard
     python3 pve_inventory.py --json              # → salva anche il JSON
     python3 pve_inventory.py --open              # → genera e apre nel browser

  2) Da JSON esistente (solo dashboard):
     python3 pve_inventory.py --from snapshot.json
     python3 pve_inventory.py --from snapshot.json -o report.html

  3) Solo JSON (senza dashboard):
     python3 pve_inventory.py --json-only
     python3 pve_inventory.py --json-only --stdout

Requisiti:
  - Python 3.6+ (nessuna dipendenza esterna)
  - Se eseguito su PVE: accesso root e pvesh disponibile
"""

import json
import subprocess
import sys
import os
import re
import socket
import argparse
import webbrowser
import html as html_mod
from datetime import datetime
from pathlib import Path


# ═══════════════════════════════════════════════════════════════════════════
#  PARTE 1: RACCOLTA DATI (pvesh)
# ═══════════════════════════════════════════════════════════════════════════

def check_pvesh():
    """Verifica che pvesh sia disponibile e funzionante."""
    try:
        r = subprocess.run(
            ["pvesh", "get", "/version", "--output-format", "json"],
            capture_output=True, text=True, timeout=10
        )
        return r.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def api_get(path):
    """Chiama le API Proxmox via pvesh."""
    try:
        r = subprocess.run(
            ["pvesh", "get", path, "--output-format", "json"],
            capture_output=True, text=True, timeout=30
        )
        if r.returncode == 0 and r.stdout.strip():
            return json.loads(r.stdout)
    except (subprocess.TimeoutExpired, json.JSONDecodeError, FileNotFoundError) as e:
        print(f"  [WARN] API {path}: {e}", file=sys.stderr)
    return None


def bytes_human(n):
    if n is None or n == 0:
        return "0 B"
    for u in ("B", "KB", "MB", "GB", "TB", "PB"):
        if abs(n) < 1024:
            return f"{n:.1f} {u}"
        n /= 1024
    return f"{n:.1f} EB"


def pct(used, total):
    return round(used / total * 100, 1) if total else 0


# ── Collectors ────────────────────────────────────────────────────────────

def collect_version():
    log("versione PVE")
    d = api_get("/version")
    if d:
        return {"version": d.get("version", "N/A"), "release": d.get("release", ""), "repoid": d.get("repoid", "")}
    v = _run("pveversion")
    return {"version": v or "N/A", "release": "", "repoid": ""}


def collect_nodes():
    log("nodi")
    nodes = api_get("/nodes") or []
    result = []
    for node in nodes:
        name = node.get("node", "unknown")
        log(f"  nodo {name}")
        info = {
            "name": name,
            "status": node.get("status", "unknown"),
            "uptime_seconds": node.get("uptime", 0),
            "cpu_count": node.get("maxcpu", 0),
            "cpu_usage_pct": round(node.get("cpu", 0) * 100, 1),
            "memory_total": node.get("maxmem", 0),
            "memory_used": node.get("mem", 0),
            "memory_total_human": bytes_human(node.get("maxmem", 0)),
            "memory_used_human": bytes_human(node.get("mem", 0)),
            "memory_usage_pct": pct(node.get("mem", 0), node.get("maxmem", 0)),
            "kernel": "", "cpu_model": "",
        }
        up = node.get("uptime", 0)
        info["uptime_human"] = f"{up // 86400}d {(up % 86400) // 3600}h {(up % 3600) // 60}m"

        st = api_get(f"/nodes/{name}/status")
        if st:
            info["kernel"] = st.get("kversion", "") or st.get("kernel", "")
            ci = st.get("cpuinfo", {})
            if ci:
                info["cpu_model"] = ci.get("model", "")
                info["cpu_sockets"] = ci.get("sockets", 1)
                info["cpu_cores_per_socket"] = ci.get("cores", 0)
                info["cpu_threads"] = ci.get("cpus", 0)

        dns = api_get(f"/nodes/{name}/dns")
        if dns:
            info["dns_search"] = dns.get("search", "")
            servers = [dns.get(f"dns{i}", "") for i in range(1, 4)]
            info["dns_servers"] = ", ".join(s for s in servers if s)

        ti = api_get(f"/nodes/{name}/time")
        if ti:
            info["timezone"] = ti.get("timezone", "")

        result.append(info)
    return result


def collect_vms(node_name):
    log(f"  VM QEMU ({node_name})")
    vms = api_get(f"/nodes/{node_name}/qemu") or []
    result = []
    for vm in sorted(vms, key=lambda x: x.get("vmid", 0)):
        vmid = vm.get("vmid")
        info = {
            "vmid": vmid, "name": vm.get("name", ""), "status": vm.get("status", "unknown"),
            "cpu_cores": vm.get("cpus", 0),
            "cpu_usage_pct": round(vm.get("cpu", 0) * 100, 1),
            "memory_max": vm.get("maxmem", 0), "memory_used": vm.get("mem", 0),
            "memory_max_human": bytes_human(vm.get("maxmem", 0)),
            "memory_used_human": bytes_human(vm.get("mem", 0)),
            "disk_max": vm.get("maxdisk", 0),
            "disk_max_human": bytes_human(vm.get("maxdisk", 0)),
            "uptime_seconds": vm.get("uptime", 0),
            "tags": vm.get("tags", ""), "template": bool(vm.get("template", 0)),
            "qemu_agent": False, "disks": [], "networks": [],
            "boot_order": "", "machine_type": "", "bios": "", "os_type": "",
            "snapshots": [], "description": "", "scsihw": "",
        }
        cfg = api_get(f"/nodes/{node_name}/qemu/{vmid}/config")
        if cfg:
            info["bios"] = cfg.get("bios", "seabios")
            info["machine_type"] = cfg.get("machine", "")
            info["os_type"] = cfg.get("ostype", "")
            info["boot_order"] = cfg.get("boot", "")
            info["qemu_agent"] = bool(cfg.get("agent", 0))
            info["description"] = cfg.get("description", "")
            info["scsihw"] = cfg.get("scsihw", "")
            for k, v in cfg.items():
                if any(k.startswith(p) for p in ("scsi", "virtio", "ide", "sata", "efidisk", "tpmstate")):
                    if isinstance(v, str) and ":" in v:
                        info["disks"].append({"device": k, "config": v})
                if k.startswith("net") and isinstance(v, str):
                    info["networks"].append({"device": k, "config": v})

        snaps = api_get(f"/nodes/{node_name}/qemu/{vmid}/snapshot") or []
        info["snapshots"] = [
            {"name": s.get("name", ""), "description": s.get("description", ""), "snaptime": s.get("snaptime", 0)}
            for s in snaps if s.get("name") != "current"
        ]
        result.append(info)
    return result


def collect_lxc(node_name):
    log(f"  LXC ({node_name})")
    cts = api_get(f"/nodes/{node_name}/lxc") or []
    result = []
    for ct in sorted(cts, key=lambda x: x.get("vmid", 0)):
        vmid = ct.get("vmid")
        info = {
            "vmid": vmid, "name": ct.get("name", ""), "status": ct.get("status", "unknown"),
            "cpu_cores": ct.get("cpus", 0),
            "cpu_usage_pct": round(ct.get("cpu", 0) * 100, 1),
            "memory_max": ct.get("maxmem", 0), "memory_used": ct.get("mem", 0),
            "memory_max_human": bytes_human(ct.get("maxmem", 0)),
            "memory_used_human": bytes_human(ct.get("mem", 0)),
            "disk_max": ct.get("maxdisk", 0), "disk_used": ct.get("disk", 0),
            "disk_max_human": bytes_human(ct.get("maxdisk", 0)),
            "disk_used_human": bytes_human(ct.get("disk", 0)),
            "swap_max": ct.get("maxswap", 0), "swap_used": ct.get("swap", 0),
            "uptime_seconds": ct.get("uptime", 0),
            "tags": ct.get("tags", ""), "template": bool(ct.get("template", 0)),
            "type": "lxc", "mountpoints": [], "networks": [], "snapshots": [],
        }
        cfg = api_get(f"/nodes/{node_name}/lxc/{vmid}/config")
        if cfg:
            info["hostname"] = cfg.get("hostname", "")
            info["ostype"] = cfg.get("ostype", "")
            info["unprivileged"] = bool(cfg.get("unprivileged", 0))
            info["description"] = cfg.get("description", "")
            info["rootfs"] = cfg.get("rootfs", "")
            info["arch"] = cfg.get("arch", "amd64")
            info["onboot"] = bool(cfg.get("onboot", 0))
            info["startup"] = cfg.get("startup", "")
            info["features"] = cfg.get("features", "")
            for k, v in cfg.items():
                if k.startswith("mp") and isinstance(v, str):
                    info["mountpoints"].append({"device": k, "config": v})
                if k.startswith("net") and isinstance(v, str):
                    info["networks"].append({"device": k, "config": v})

        snaps = api_get(f"/nodes/{node_name}/lxc/{vmid}/snapshot") or []
        info["snapshots"] = [
            {"name": s.get("name", ""), "description": s.get("description", ""), "snaptime": s.get("snaptime", 0)}
            for s in snaps if s.get("name") != "current"
        ]
        result.append(info)
    return result


def collect_storage(node_name):
    log(f"  storage ({node_name})")
    sts = api_get(f"/nodes/{node_name}/storage") or []
    return [{
        "storage": s.get("storage", ""), "type": s.get("type", ""),
        "status": "active" if s.get("active", 0) else "inactive",
        "enabled": bool(s.get("enabled", 1)), "shared": bool(s.get("shared", 0)),
        "content": s.get("content", ""),
        "total": s.get("total", 0), "used": s.get("used", 0), "avail": s.get("avail", 0),
        "total_human": bytes_human(s.get("total", 0)),
        "used_human": bytes_human(s.get("used", 0)),
        "avail_human": bytes_human(s.get("avail", 0)),
        "usage_pct": pct(s.get("used", 0), s.get("total", 0)),
    } for s in sts]


def collect_network(node_name):
    log(f"  rete ({node_name})")
    nets = api_get(f"/nodes/{node_name}/network") or []
    result = []
    for n in nets:
        info = {k: n.get(k, "") for k in (
            "iface", "type", "method", "method6", "address", "netmask",
            "gateway", "cidr", "address6", "bridge_ports", "bridge_stp",
            "bridge_fd", "comments"
        )}
        info["active"] = bool(n.get("active", 0))
        info["autostart"] = bool(n.get("autostart", 0))
        info["bridge_vlan_aware"] = bool(n.get("bridge-vlan-aware", 0))
        info["bond_slaves"] = n.get("slaves", "")
        info["bond_mode"] = n.get("bond_mode", "")
        info = {k: v for k, v in info.items() if v not in ("", None, False, 0)}
        info.setdefault("iface", "")
        info.setdefault("type", "")
        result.append(info)
    return result


def collect_cluster():
    log("cluster")
    status = api_get("/cluster/status")
    resources = api_get("/cluster/resources")
    s = {"total_vms": 0, "running_vms": 0, "total_lxc": 0, "running_lxc": 0,
         "total_cpu": 0, "total_memory": 0, "total_memory_human": ""}
    if resources:
        for r in resources:
            t = r.get("type", "")
            if t == "qemu":
                s["total_vms"] += 1
                if r.get("status") == "running": s["running_vms"] += 1
            elif t == "lxc":
                s["total_lxc"] += 1
                if r.get("status") == "running": s["running_lxc"] += 1
            elif t == "node":
                s["total_cpu"] += r.get("maxcpu", 0)
                s["total_memory"] += r.get("maxmem", 0)
        s["total_memory_human"] = bytes_human(s["total_memory"])
    return {"status": status or [], "resource_summary": s}


def collect_simple(path, label):
    log(label)
    return api_get(path) or []


def collect_firewall():
    log("firewall")
    return {"options": api_get("/cluster/firewall/options") or {},
            "rules": api_get("/cluster/firewall/rules") or []}


def collect_ha():
    log("HA")
    return {"resources": api_get("/cluster/ha/resources") or [],
            "groups": api_get("/cluster/ha/groups") or [],
            "status": api_get("/cluster/ha/status/current") or []}


def collect_sdn():
    log("SDN")
    return {"vnets": api_get("/cluster/sdn/vnets") or [],
            "zones": api_get("/cluster/sdn/zones") or []}


def gather_all():
    """Raccoglie tutti i dati dal nodo PVE locale."""
    ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    hn = socket.gethostname()

    data = {
        "metadata": {"timestamp": ts, "hostname": hn, "generator": "pve_inventory.py", "format_version": "1.0"},
        "version": collect_version(),
        "cluster": collect_cluster(),
        "nodes": [], "guests": {"qemu": [], "lxc": []},
        "storage": [], "network": [],
        "pools": collect_simple("/pools", "pool"),
        "backup_jobs": collect_simple("/cluster/backup", "backup jobs"),
        "firewall": collect_firewall(),
        "ha": collect_ha(),
        "replication": collect_simple("/cluster/replication", "replication"),
        "sdn": collect_sdn(),
    }

    nodes = collect_nodes()
    data["nodes"] = nodes

    for node in nodes:
        nn = node["name"]
        data["guests"]["qemu"].extend(collect_vms(nn))
        data["guests"]["lxc"].extend(collect_lxc(nn))
        if nn == hn or not data["storage"]:
            data["storage"] = collect_storage(nn)
            data["network"] = collect_network(nn)

    return data


def _run(cmd, timeout=15):
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
        return r.stdout.strip() if r.returncode == 0 else None
    except subprocess.TimeoutExpired:
        return None


def log(msg):
    print(f"  📡 {msg}...", file=sys.stderr)


# ═══════════════════════════════════════════════════════════════════════════
#  PARTE 2: GENERAZIONE DASHBOARD HTML
# ═══════════════════════════════════════════════════════════════════════════

def esc(text):
    return html_mod.escape(str(text)) if text else ""

def _ip_from_desc(desc):
    if not desc: return None
    m = re.search(r'(?:ipv4|IPv4|IP)[:\s]*(\d+\.\d+\.\d+\.\d+)', desc, re.IGNORECASE)
    if m: return m.group(1)
    m = re.search(r'(\d+\.\d+\.\d+\.\d+)', desc)
    if m and not m.group(1).startswith(("192.168.", "10.", "172.")):
        return m.group(1)
    return None

def _lxc_ip(networks):
    for n in networks:
        m = re.search(r'ip=(\d+\.\d+\.\d+\.\d+)', n.get("config", ""))
        if m: return m.group(1)
    return None

def _lxc_port(desc):
    if not desc: return None
    m = re.search(r'[Pp]orta[:\s]*(\d+)', desc)
    return m.group(1) if m else None

def _bridges(networks):
    brs = []
    for n in networks:
        m = re.search(r'bridge=(\w+)', n.get("config", ""))
        if m: brs.append(m.group(1))
    return brs

def _clean_desc(desc):
    if not desc: return ""
    t = re.sub(r'<[^>]+>', ' ', desc)
    return re.sub(r'\s+', ' ', t).strip()[:120]

def _snaptime(ts):
    if not ts: return ""
    try: return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")
    except (ValueError, OSError): return str(ts)


# ── CSS ───────────────────────────────────────────────────────────────────

CSS = """:root{--bg-deep:#06080c;--bg-surface:#0c1018;--bg-card:#111822;--bg-card-hover:#161f2e;--border:#1c2738;--border-bright:#2a3a52;--text-primary:#e2e8f0;--text-secondary:#8892a4;--text-dim:#4a5568;--accent-blue:#3b82f6;--accent-blue-dim:#1e3a5f;--accent-green:#22c55e;--accent-green-dim:#0d3320;--accent-amber:#f59e0b;--accent-amber-dim:#422006;--accent-red:#ef4444;--accent-red-dim:#3b1111;--accent-purple:#a855f7;--accent-purple-dim:#2e1065;--accent-cyan:#06b6d4;--accent-cyan-dim:#083344;--glow-blue:0 0 20px rgba(59,130,246,0.15);--radius:12px;--radius-sm:8px}
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:'Outfit',sans-serif;background:var(--bg-deep);color:var(--text-primary);min-height:100vh;overflow-x:hidden}
body::before{content:'';position:fixed;inset:0;background-image:linear-gradient(rgba(59,130,246,0.03) 1px,transparent 1px),linear-gradient(90deg,rgba(59,130,246,0.03) 1px,transparent 1px);background-size:60px 60px;pointer-events:none;z-index:0}
body::after{content:'';position:fixed;top:-200px;left:50%;transform:translateX(-50%);width:800px;height:600px;background:radial-gradient(ellipse,rgba(59,130,246,0.06) 0%,transparent 70%);pointer-events:none;z-index:0}
.container{position:relative;z-index:1;max-width:1440px;margin:0 auto;padding:40px 30px}
.header{display:flex;align-items:flex-start;justify-content:space-between;margin-bottom:50px;padding-bottom:30px;border-bottom:1px solid var(--border)}
.header-left h1{font-size:2.2em;font-weight:800;letter-spacing:-0.03em;background:linear-gradient(135deg,#e2e8f0 0%,#3b82f6 100%);-webkit-background-clip:text;-webkit-text-fill-color:transparent;margin-bottom:6px}
.header-left .subtitle{font-family:'JetBrains Mono',monospace;font-size:0.85em;color:var(--text-dim)}
.header-right{text-align:right;display:flex;flex-direction:column;gap:6px}
.header-badge{display:inline-flex;align-items:center;gap:6px;font-family:'JetBrains Mono',monospace;font-size:0.75em;color:var(--text-secondary);background:var(--bg-card);border:1px solid var(--border);padding:5px 12px;border-radius:20px}
.header-badge .dot{width:6px;height:6px;border-radius:50%;background:var(--accent-green);box-shadow:0 0 8px var(--accent-green);animation:pulse 2s infinite}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:0.4}}
.summary-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:16px;margin-bottom:50px}
.summary-card{background:var(--bg-card);border:1px solid var(--border);border-radius:var(--radius);padding:22px;position:relative;overflow:hidden;transition:all 0.3s ease}
.summary-card:hover{border-color:var(--border-bright);transform:translateY(-2px);box-shadow:var(--glow-blue)}
.summary-card .icon{font-size:1.6em;margin-bottom:12px;display:block}
.summary-card .label{font-size:0.72em;text-transform:uppercase;letter-spacing:0.12em;color:var(--text-dim);font-weight:600;margin-bottom:6px}
.summary-card .value{font-size:2em;font-weight:800;letter-spacing:-0.02em;line-height:1}
.summary-card .detail{font-size:0.8em;color:var(--text-secondary);margin-top:4px;font-family:'JetBrains Mono',monospace}
.summary-card .accent-line{position:absolute;top:0;left:0;right:0;height:2px}
.section{margin-bottom:50px}
.section-header{display:flex;align-items:center;gap:12px;margin-bottom:20px}
.section-header h2{font-size:1.3em;font-weight:700}
.section-header .count{font-family:'JetBrains Mono',monospace;font-size:0.75em;color:var(--accent-blue);background:var(--accent-blue-dim);padding:3px 10px;border-radius:12px}
.tab-nav{display:flex;gap:4px;margin-bottom:20px;border-bottom:1px solid var(--border);overflow-x:auto}
.tab-btn{font-family:'Outfit',sans-serif;font-size:0.88em;font-weight:500;color:var(--text-dim);background:none;border:none;padding:10px 18px;cursor:pointer;border-bottom:2px solid transparent;transition:all 0.2s;white-space:nowrap}
.tab-btn:hover{color:var(--text-secondary)}
.tab-btn.active{color:var(--accent-blue);border-bottom-color:var(--accent-blue)}
.tab-content{display:none}.tab-content.active{display:block}
.guest-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(340px,1fr));gap:14px}
.guest-card{background:var(--bg-card);border:1px solid var(--border);border-radius:var(--radius);padding:20px;transition:all 0.25s ease}
.guest-card:hover{border-color:var(--border-bright);background:var(--bg-card-hover)}
.guest-card-header{display:flex;align-items:center;justify-content:space-between;margin-bottom:14px}
.guest-card-header .name-group{display:flex;align-items:center;gap:10px}
.guest-card-header .vmid{font-family:'JetBrains Mono',monospace;font-size:0.75em;color:var(--text-dim);background:var(--bg-deep);padding:3px 8px;border-radius:6px;border:1px solid var(--border)}
.guest-card-header .name{font-weight:600;font-size:1.05em}
.status-pill{display:inline-flex;align-items:center;gap:5px;font-family:'JetBrains Mono',monospace;font-size:0.7em;padding:3px 10px;border-radius:12px;font-weight:500}
.status-pill.running{color:var(--accent-green);background:var(--accent-green-dim)}
.status-pill.stopped{color:var(--accent-red);background:var(--accent-red-dim)}
.status-pill .sdot{width:5px;height:5px;border-radius:50%;background:currentColor}
.guest-stats{display:grid;grid-template-columns:repeat(3,1fr);gap:10px;margin-bottom:14px}
.stat-box{background:var(--bg-deep);border-radius:var(--radius-sm);padding:10px;text-align:center}
.stat-box .stat-label{font-size:0.65em;text-transform:uppercase;letter-spacing:0.1em;color:var(--text-dim);margin-bottom:4px;font-weight:600}
.stat-box .stat-value{font-family:'JetBrains Mono',monospace;font-size:0.9em;font-weight:600}
.guest-meta{display:flex;flex-wrap:wrap;gap:6px;margin-top:10px}
.meta-tag{font-family:'JetBrains Mono',monospace;font-size:0.65em;padding:2px 8px;border-radius:6px;border:1px solid var(--border);color:var(--text-secondary);background:var(--bg-deep)}
.meta-tag.bios{color:var(--accent-purple);border-color:var(--accent-purple-dim)}
.meta-tag.net{color:var(--accent-cyan);border-color:var(--accent-cyan-dim)}
.meta-tag.tag{color:var(--accent-amber);border-color:var(--accent-amber-dim)}
.meta-tag.unpriv{color:var(--accent-green);border-color:var(--accent-green-dim)}
.meta-tag.priv{color:var(--accent-amber);border-color:var(--accent-amber-dim)}
.meta-tag.warn{color:var(--accent-red)}
.guest-description{font-size:0.78em;color:var(--text-dim);margin-top:10px;padding-top:10px;border-top:1px solid var(--border);font-family:'JetBrains Mono',monospace;line-height:1.5;word-break:break-word}
.guest-disks{margin-top:10px;padding-top:10px;border-top:1px solid var(--border)}
.disk-item{display:flex;align-items:center;gap:8px;font-family:'JetBrains Mono',monospace;font-size:0.72em;color:var(--text-secondary);padding:3px 0}
.disk-item .disk-dev{color:var(--accent-blue);min-width:65px;font-weight:500}
.disk-item .disk-conf{color:var(--text-dim);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.snap-list{margin-top:10px;padding-top:10px;border-top:1px solid var(--border)}
.snap-item{font-family:'JetBrains Mono',monospace;font-size:0.72em;color:var(--text-dim);padding:2px 0;display:flex;gap:8px;align-items:center}
.snap-item .snap-icon{color:var(--accent-amber)}.snap-item .snap-name{color:var(--text-secondary)}
.topology{background:var(--bg-card);border:1px solid var(--border);border-radius:var(--radius);padding:30px;overflow-x:auto}
.topo-container{display:flex;flex-direction:column;gap:30px}
.topo-bridge-label{display:inline-flex;align-items:center;gap:8px;font-family:'JetBrains Mono',monospace;font-size:0.85em;font-weight:600;padding:8px 16px;border-radius:var(--radius-sm);margin-bottom:14px}
.topo-bridge-label.br-public{background:linear-gradient(135deg,var(--accent-blue-dim),transparent);color:var(--accent-blue);border:1px solid var(--accent-blue-dim)}
.topo-bridge-label.br-internal{background:linear-gradient(135deg,var(--accent-green-dim),transparent);color:var(--accent-green);border:1px solid var(--accent-green-dim)}
.topo-bridge-label.br-other{background:linear-gradient(135deg,var(--accent-purple-dim),transparent);color:var(--accent-purple);border:1px solid var(--accent-purple-dim)}
.topo-bridge-info{font-family:'JetBrains Mono',monospace;font-size:0.7em;color:var(--text-dim);margin-left:10px}
.topo-guests{display:flex;flex-wrap:wrap;gap:10px;padding-left:20px;border-left:2px solid var(--border);margin-left:12px}
.topo-node{font-family:'JetBrains Mono',monospace;font-size:0.75em;padding:6px 12px;border-radius:var(--radius-sm);background:var(--bg-deep);border:1px solid var(--border);color:var(--text-secondary);display:flex;align-items:center;gap:6px;transition:all 0.2s}
.topo-node:hover{border-color:var(--border-bright);background:var(--bg-card)}
.topo-node .ticon{font-size:1.1em}
.topo-node.vm .ticon{color:var(--accent-blue)}.topo-node.lxc .ticon{color:var(--accent-green)}
.topo-node .tip{color:var(--text-dim)}
.storage-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(380px,1fr));gap:14px}
.storage-card{background:var(--bg-card);border:1px solid var(--border);border-radius:var(--radius);padding:22px;transition:all 0.25s ease}
.storage-card:hover{border-color:var(--border-bright)}
.storage-header{display:flex;justify-content:space-between;align-items:center;margin-bottom:14px}
.storage-header .sname{font-weight:600;font-size:1.05em}
.storage-header .stype{font-family:'JetBrains Mono',monospace;font-size:0.72em;color:var(--accent-purple);background:var(--accent-purple-dim);padding:3px 10px;border-radius:10px}
.storage-bar{width:100%;height:10px;background:var(--bg-deep);border-radius:5px;overflow:hidden;margin:12px 0}
.storage-bar-fill{height:100%;border-radius:5px;background:linear-gradient(90deg,var(--accent-blue),var(--accent-cyan))}
.storage-bar-fill.warn{background:linear-gradient(90deg,var(--accent-amber),#f97316)}
.storage-bar-fill.crit{background:linear-gradient(90deg,var(--accent-red),#f97316)}
.storage-stats{display:flex;justify-content:space-between;font-family:'JetBrains Mono',monospace;font-size:0.78em;color:var(--text-secondary);margin-top:8px}
.storage-content{display:flex;flex-wrap:wrap;gap:5px;margin-top:10px}
.content-tag{font-family:'JetBrains Mono',monospace;font-size:0.65em;padding:2px 8px;border-radius:6px;background:var(--bg-deep);border:1px solid var(--border);color:var(--text-dim)}
.net-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:14px}
.net-card{background:var(--bg-card);border:1px solid var(--border);border-radius:var(--radius);padding:20px;transition:all 0.25s ease}
.net-card:hover{border-color:var(--border-bright)}
.net-card-header{display:flex;justify-content:space-between;align-items:center;margin-bottom:12px}
.net-card-header .iface-name{font-family:'JetBrains Mono',monospace;font-weight:700;font-size:1.1em;color:var(--accent-cyan)}
.net-card-header .iface-type{font-size:0.72em;padding:3px 10px;border-radius:10px;background:var(--accent-cyan-dim);color:var(--accent-cyan);font-family:'JetBrains Mono',monospace}
.net-detail{font-family:'JetBrains Mono',monospace;font-size:0.78em;color:var(--text-secondary);padding:3px 0;display:flex;gap:8px}
.net-detail .ndl{color:var(--text-dim);min-width:80px}
.backup-table{width:100%;border-collapse:collapse;font-size:0.88em}
.backup-table th{text-align:left;font-size:0.72em;text-transform:uppercase;letter-spacing:0.1em;color:var(--text-dim);font-weight:600;padding:10px 14px;border-bottom:1px solid var(--border);background:var(--bg-card)}
.backup-table td{padding:12px 14px;border-bottom:1px solid var(--border);font-family:'JetBrains Mono',monospace;font-size:0.88em;color:var(--text-secondary)}
.backup-table tr:hover td{background:var(--bg-card-hover)}
.enabled-yes{color:var(--accent-green)}.enabled-no{color:var(--accent-red)}
.firewall-box{background:var(--bg-card);border:1px solid var(--border);border-radius:var(--radius);padding:22px}
.fw-status{display:flex;align-items:center;gap:10px;margin-bottom:14px;font-weight:600}
.fw-rule{font-family:'JetBrains Mono',monospace;font-size:0.82em;color:var(--text-secondary);padding:10px;background:var(--bg-deep);border-radius:var(--radius-sm);margin-top:8px;border-left:3px solid var(--accent-amber)}
.fw-rule.disabled{opacity:0.5}
.warning-box{margin-top:18px;padding:14px;background:var(--accent-amber-dim);border:1px solid var(--accent-amber);border-radius:var(--radius-sm);font-size:0.85em;line-height:1.6}
@keyframes fadeUp{from{opacity:0;transform:translateY(15px)}to{opacity:1;transform:translateY(0)}}
.animate-in{animation:fadeUp 0.5s ease forwards;opacity:0}
.delay-1{animation-delay:0.05s}.delay-2{animation-delay:0.1s}.delay-3{animation-delay:0.15s}
.delay-4{animation-delay:0.2s}.delay-5{animation-delay:0.25s}.delay-6{animation-delay:0.3s}
@media(max-width:768px){.container{padding:20px 16px}.header{flex-direction:column;gap:16px}.header-right{text-align:left}.header-left h1{font-size:1.6em}.guest-grid,.storage-grid,.net-grid{grid-template-columns:1fr}.summary-grid{grid-template-columns:repeat(2,1fr)}}
"""


# ── HTML section generators ──────────────────────────────────────────────

def _header(d):
    m = d.get("metadata", {})
    v = d.get("version", {})
    n = d["nodes"][0] if d.get("nodes") else {}
    hn = esc(m.get("hostname", "unknown"))
    ts = esc(m.get("timestamp", "")).replace("_", " ")
    kr = esc(n.get("kernel", "N/A")).split(" ")[1] if " " in n.get("kernel", "") else esc(n.get("kernel", ""))
    return f"""<div class="header animate-in">
<div class="header-left"><h1>⬡ {hn}</h1><div class="subtitle">Infrastructure Snapshot — {ts}</div></div>
<div class="header-right">
<span class="header-badge"><span class="dot"></span> PVE {esc(v.get('version',''))}</span>
<span class="header-badge">⏱ Uptime {esc(n.get('uptime_human',''))}</span>
<span class="header-badge">🔧 Kernel {kr}</span>
</div></div>"""


def _summary(d):
    cs = d.get("cluster", {}).get("resource_summary", {})
    n = d["nodes"][0] if d.get("nodes") else {}
    cards = [
        ("🖥️", "VM QEMU", str(cs.get("total_vms", 0)), f'/ {cs.get("running_vms",0)} running', "var(--accent-blue)"),
        ("📦", "Container LXC", str(cs.get("total_lxc", 0)), f'/ {cs.get("running_lxc",0)} running', "var(--accent-green)"),
        ("⚡", "CPU", str(cs.get("total_cpu", 0)), n.get("cpu_model", "")[:40], "var(--accent-cyan)"),
        ("🧠", "RAM", n.get("memory_total_human", bytes_human(n.get("memory_total", 0))),
         f'{n.get("memory_used_human","")} used ({n.get("memory_usage_pct",0)}%)', "var(--accent-purple)"),
    ]
    icons = ["💾", "☁️", "📀", "🗄️"]
    for i, st in enumerate(d.get("storage", [])):
        cards.append((icons[i] if i < len(icons) else "💾", st.get("storage", ""),
                       st.get("total_human", ""), f'{st.get("used_human","")} used ({st.get("usage_pct",0)}%)',
                       "var(--accent-amber)" if i == 0 else "var(--accent-red)"))

    h = ['<div class="summary-grid">']
    for i, (icon, label, val, det, col) in enumerate(cards):
        dl = min(i + 1, 6)
        h.append(f'<div class="summary-card animate-in delay-{dl}"><div class="accent-line" style="background:linear-gradient(90deg,{col},transparent)"></div>'
                 f'<div class="icon">{icon}</div><div class="label">{esc(label)}</div>'
                 f'<div class="value" style="color:{col}">{esc(val)}</div><div class="detail">{esc(det)}</div></div>')
    h.append('</div>')
    return "\n".join(h)


def _topology(d):
    bridges = {}
    for net in d.get("network", []):
        if net.get("type") == "bridge":
            bridges[net["iface"]] = {"cidr": net.get("cidr", net.get("address", "")),
                                      "gw": net.get("gateway", ""), "ports": net.get("bridge_ports", ""),
                                      "comment": net.get("comments", "").strip(), "guests": []}
    for vm in d.get("guests", {}).get("qemu", []):
        ip = _ip_from_desc(vm.get("description", ""))
        for br in _bridges(vm.get("networks", [])):
            if br in bridges:
                bridges[br]["guests"].append(("vm", vm["vmid"], vm.get("name", ""), ip or ""))
    for ct in d.get("guests", {}).get("lxc", []):
        ip = _lxc_ip(ct.get("networks", []))
        short = "." + ip.split(".")[-1] if ip and ip.startswith("192.168.") else (ip or "")
        for br in _bridges(ct.get("networks", [])):
            if br in bridges:
                bridges[br]["guests"].append(("lxc", ct["vmid"], ct.get("name", ""), short))

    h = ['<div class="topology"><div class="topo-container">']
    for br in sorted(bridges):
        info = bridges[br]
        cls = "br-public" if info["gw"] or info["ports"] else ("br-internal" if "192.168.1." in info["cidr"] else "br-other")
        lbl = info["comment"] or br
        extra = " | ".join(filter(None, [info["cidr"], f'→ gw {info["gw"]}' if info["gw"] else "", f'port: {info["ports"]}' if info["ports"] else ""]))
        h.append(f'<div><div class="topo-bridge-label {cls}">⬡ {esc(br)} — {esc(lbl)} <span class="topo-bridge-info">{esc(extra)}</span></div><div class="topo-guests">')
        for gtype, vid, gname, gip in sorted(info["guests"], key=lambda x: x[1]):
            ico = "🖥" if gtype == "vm" else "📦"
            tip = f' <span class="tip">{esc(gip)}</span>' if gip else ""
            h.append(f'<div class="topo-node {gtype}"><span class="ticon">{ico}</span> {vid} {esc(gname)}{tip}</div>')
        if not info["guests"]:
            h.append('<div class="topo-node" style="color:var(--text-dim)">nessun guest</div>')
        h.append('</div></div>')
    h.append('</div></div>')
    return "\n".join(h)


def _vm_cards(d):
    vms = d.get("guests", {}).get("qemu", [])
    if not vms: return ""
    h = [f'<div class="section"><div class="section-header"><h2>🖥️ Virtual Machines</h2><span class="count">{len(vms)} VM</span></div><div class="guest-grid">']
    for vm in sorted(vms, key=lambda x: x.get("vmid", 0)):
        sc = "running" if vm.get("status") == "running" else "stopped"
        bios = (vm.get("bios", "seabios").upper() + ("/" + vm["machine_type"] if vm.get("machine_type") else ""))
        h.append(f'<div class="guest-card"><div class="guest-card-header"><div class="name-group">'
                 f'<span class="vmid">{vm["vmid"]}</span><span class="name">{esc(vm.get("name",""))}</span></div>'
                 f'<span class="status-pill {sc}"><span class="sdot"></span> {vm.get("status","")}</span></div>'
                 f'<div class="guest-stats">'
                 f'<div class="stat-box"><div class="stat-label">CPU</div><div class="stat-value">{vm.get("cpu_cores",0)} cores</div></div>'
                 f'<div class="stat-box"><div class="stat-label">RAM</div><div class="stat-value">{esc(vm.get("memory_max_human",bytes_human(vm.get("memory_max",0))))}</div></div>'
                 f'<div class="stat-box"><div class="stat-label">Disco</div><div class="stat-value">{esc(vm.get("disk_max_human",bytes_human(vm.get("disk_max",0))))}</div></div></div>'
                 f'<div class="guest-meta"><span class="meta-tag bios">{esc(bios)}</span>')
        for br in _bridges(vm.get("networks", [])):
            fw = " 🔥" if any("firewall=1" in n.get("config", "") for n in vm.get("networks", [])) else ""
            h.append(f'<span class="meta-tag net">{esc(br)}{fw}</span>')
        for t in (t.strip() for t in vm.get("tags", "").split(";") if t.strip()):
            h.append(f'<span class="meta-tag tag">{esc(t)}</span>')
        if vm.get("qemu_agent"): h.append('<span class="meta-tag">qemu-agent ✓</span>')
        h.append('</div>')
        if vm.get("disks"):
            h.append('<div class="guest-disks">')
            for dk in vm["disks"]:
                h.append(f'<div class="disk-item"><span class="disk-dev">{esc(dk["device"])}</span><span class="disk-conf">{esc(dk["config"][:80])}</span></div>')
            h.append('</div>')
        if vm.get("snapshots"):
            h.append('<div class="snap-list">')
            for s in vm["snapshots"]:
                h.append(f'<div class="snap-item"><span class="snap-icon">📸</span><span class="snap-name">{esc(s["name"])}</span> <span style="color:var(--text-dim)">{_snaptime(s.get("snaptime"))}</span></div>')
            h.append('</div>')
        desc = _clean_desc(vm.get("description", ""))
        if desc: h.append(f'<div class="guest-description">{esc(desc)}</div>')
        h.append('</div>')
    h.append('</div></div>')
    return "\n".join(h)


def _lxc_cards(d):
    lxcs = d.get("guests", {}).get("lxc", [])
    if not lxcs: return ""
    h = [f'<div class="section"><div class="section-header"><h2>📦 Container LXC</h2><span class="count">{len(lxcs)} LXC</span></div><div class="guest-grid">']
    for ct in sorted(lxcs, key=lambda x: x.get("vmid", 0)):
        sc = "running" if ct.get("status") == "running" else "stopped"
        rootfs = ct.get("rootfs", "")
        dm = re.search(r'size=(\d+[GMTK]?)', rootfs)
        disk = dm.group(1) if dm else ct.get("disk_max_human", "N/A")
        ip = _lxc_ip(ct.get("networks", []))
        port = _lxc_port(ct.get("description", ""))
        h.append(f'<div class="guest-card"><div class="guest-card-header"><div class="name-group">'
                 f'<span class="vmid">{ct["vmid"]}</span><span class="name">{esc(ct.get("name",""))}</span></div>'
                 f'<span class="status-pill {sc}"><span class="sdot"></span> {ct.get("status","")}</span></div>'
                 f'<div class="guest-stats">'
                 f'<div class="stat-box"><div class="stat-label">CPU</div><div class="stat-value">{ct.get("cpu_cores",0)}</div></div>'
                 f'<div class="stat-box"><div class="stat-label">RAM</div><div class="stat-value">{esc(ct.get("memory_max_human",bytes_human(ct.get("memory_max",0))))}</div></div>'
                 f'<div class="stat-box"><div class="stat-label">Disco</div><div class="stat-value">{esc(disk)}</div></div></div>'
                 f'<div class="guest-meta">')
        if ct.get("unprivileged"): h.append('<span class="meta-tag unpriv">unprivileged</span>')
        else: h.append('<span class="meta-tag priv">privileged</span>')
        if ip: h.append(f'<span class="meta-tag net">{esc(ip)}</span>')
        for t in (t.strip() for t in ct.get("tags", "").split(";") if t.strip()):
            h.append(f'<span class="meta-tag tag">{esc(t)}</span>')
        if port: h.append(f'<span class="meta-tag">:{esc(port)}</span>')
        if ct.get("onboot"): h.append('<span class="meta-tag">onboot ✓</span>')
        else: h.append('<span class="meta-tag warn">onboot ✗</span>')
        h.append('</div>')
        if ct.get("snapshots"):
            h.append('<div class="snap-list">')
            for s in ct["snapshots"]:
                h.append(f'<div class="snap-item"><span class="snap-icon">📸</span><span class="snap-name">{esc(s["name"])}</span></div>')
            h.append('</div>')
        desc = _clean_desc(ct.get("description", ""))
        if desc and len(desc) > 10: h.append(f'<div class="guest-description">{esc(desc)}</div>')
        h.append('</div>')
    h.append('</div></div>')
    return "\n".join(h)


def _storage(d):
    sts = d.get("storage", [])
    if not sts: return ""
    h = [f'<div class="section"><div class="section-header"><h2>💾 Storage</h2><span class="count">{len(sts)} pool</span></div><div class="storage-grid">']
    for s in sts:
        u = s.get("usage_pct", pct(s.get("used", 0), s.get("total", 0)))
        bc = "crit" if u > 90 else "warn" if u > 70 else ""
        shared = " (shared)" if s.get("shared") else ""
        h.append(f'<div class="storage-card"><div class="storage-header"><span class="sname">{esc(s["storage"])}</span>'
                 f'<span class="stype">{esc(s["type"])}{esc(shared)}</span></div>'
                 f'<div class="storage-bar"><div class="storage-bar-fill {bc}" style="width:{u}%"></div></div>'
                 f'<div class="storage-stats"><span>{esc(s.get("used_human",""))} / {esc(s.get("total_human",""))}</span>'
                 f'<span style="font-weight:600">{u}%</span></div><div class="storage-content">')
        for c in (c.strip() for c in s.get("content", "").split(",") if c.strip()):
            h.append(f'<span class="content-tag">{esc(c)}</span>')
        h.append('</div></div>')
    h.append('</div></div>')
    return "\n".join(h)


def _network(d):
    nets = d.get("network", [])
    if not nets: return ""
    # count guests per bridge
    bc = {}
    for vm in d.get("guests", {}).get("qemu", []):
        for br in _bridges(vm.get("networks", [])): bc.setdefault(br, {"vm": 0, "lxc": 0}); bc[br]["vm"] += 1
    for ct in d.get("guests", {}).get("lxc", []):
        for br in _bridges(ct.get("networks", [])): bc.setdefault(br, {"vm": 0, "lxc": 0}); bc[br]["lxc"] += 1

    h = ['<div class="section"><div class="section-header"><h2>🌐 Network Interfaces</h2></div><div class="net-grid">']
    for n in nets:
        iface = esc(n.get("iface", ""))
        h.append(f'<div class="net-card"><div class="net-card-header"><span class="iface-name">{iface}</span>'
                 f'<span class="iface-type">{esc(n.get("type",""))}</span></div>')
        addr = n.get("cidr", n.get("address", ""))
        if addr: h.append(f'<div class="net-detail"><span class="ndl">IPv4</span> {esc(addr)}</div>')
        if n.get("address6"): h.append(f'<div class="net-detail"><span class="ndl">IPv6</span> {esc(n["address6"])}</div>')
        if n.get("gateway"): h.append(f'<div class="net-detail"><span class="ndl">Gateway</span> {esc(n["gateway"])}</div>')
        if n.get("bridge_ports"): h.append(f'<div class="net-detail"><span class="ndl">Ports</span> {esc(n["bridge_ports"])}</div>')
        if n.get("method") and not addr: h.append(f'<div class="net-detail"><span class="ndl">Mode</span> {esc(n["method"])}</div>')
        if n.get("comments", "").strip(): h.append(f'<div class="net-detail"><span class="ndl">Note</span> {esc(n["comments"].strip())}</div>')
        if n.get("iface", "") in bc:
            c = bc[n["iface"]]
            h.append(f'<div class="net-detail"><span class="ndl">Guest</span> {c["vm"]} VM + {c["lxc"]} LXC</div>')
        h.append('</div>')
    h.append('</div></div>')
    return "\n".join(h)


def _backup(d):
    jobs = d.get("backup_jobs", [])
    if not jobs: return ""
    # Resolve names & find not backed
    id_names = {}
    all_ids = set()
    for vm in d.get("guests", {}).get("qemu", []): vid = str(vm["vmid"]); all_ids.add(vid); id_names[vid] = vm.get("name", vid)
    for ct in d.get("guests", {}).get("lxc", []): vid = str(ct["vmid"]); all_ids.add(vid); id_names[vid] = ct.get("name", vid)
    backed = set()
    for j in jobs:
        vids = j.get("vmid", "")
        if vids and vids != "all":
            for v in vids.split(","): backed.add(v.strip())
    not_backed = all_ids - backed

    h = [f'<div class="section"><div class="section-header"><h2>📋 Backup Jobs</h2><span class="count">{len(jobs)} jobs</span></div>'
         '<div style="overflow-x:auto"><table class="backup-table"><thead><tr>'
         '<th>Schedule</th><th>VM/LXC</th><th>Nomi</th><th>Compressione</th><th>Modo</th><th>Storage</th><th>Stato</th>'
         '</tr></thead><tbody>']
    for j in jobs:
        vids = j.get("vmid", "all")
        names = ", ".join(id_names.get(v.strip(), v.strip()) for v in vids.split(",")) if vids != "all" else "all"
        en = j.get("enabled", True)
        h.append(f'<tr><td>{esc(j.get("schedule",""))}</td><td>{esc(vids)}</td>'
                 f'<td style="color:var(--text-primary)">{esc(names)}</td>'
                 f'<td>{esc(j.get("compress",""))}</td><td>{esc(j.get("mode",""))}</td>'
                 f'<td>{esc(j.get("storage",""))}</td>'
                 f'<td class="{"enabled-yes" if en else "enabled-no"}">{"✅ attivo" if en else "❌ disattivo"}</td></tr>')
    h.append('</tbody></table></div>')

    warns = []
    if any(all(v is None for v in j.get("retention", {}).values()) for j in jobs):
        warns.append("⚠️ <strong>Nessuna retention policy</strong> configurata. Considera keep-daily/weekly/monthly.")
    if not_backed:
        nb = ", ".join(f'{v} ({id_names.get(v,"?")})' for v in sorted(not_backed, key=int))
        warns.append(f"⚠️ <strong>Non backuppati:</strong> {nb}")
    if warns:
        h.append(f'<div class="warning-box">{"<br>".join(warns)}</div>')
    h.append('</div>')
    return "\n".join(h)


def _firewall(d):
    fw = d.get("firewall", {})
    rules = fw.get("rules", [])
    enabled = fw.get("options", {}).get("enable", 0)
    h = ['<div class="section"><div class="section-header"><h2>🔥 Firewall</h2></div><div class="firewall-box">']
    color = "var(--accent-green)" if enabled else "var(--text-dim)"
    stato = "Abilitato" if enabled else "Disabilitato"
    h.append(f'<div class="fw-status"><span style="color:{color}">●</span> Firewall Cluster: {stato}</div>')
    if not rules:
        h.append('<p style="color:var(--text-dim);font-size:0.85em">Nessuna regola configurata.</p>')
    for r in rules:
        dis = not r.get("enable", 1)
        parts = [r.get("action", ""), r.get("type", "")]
        if r.get("proto"): parts.append(r["proto"])
        if r.get("dport"): parts.append(f'dport:{r["dport"]}')
        if r.get("source"): parts.append(f'src:{r["source"]}')
        label = "<strong>[DISABILITATA]</strong> " if dis else ""
        h.append(f'<div class="fw-rule{"  disabled" if dis else ""}">{label}{" ".join(parts)}</div>')
    h.append('</div></div>')
    return "\n".join(h)


# ── Assembler ─────────────────────────────────────────────────────────────

def build_html(data):
    hn = esc(data.get("metadata", {}).get("hostname", "PVE"))
    ts = esc(data.get("metadata", {}).get("timestamp", ""))
    return f"""<!DOCTYPE html>
<html lang="it">
<head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>PVE Dashboard — {hn}</title>
<link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@300;400;500;600;700&family=Outfit:wght@300;400;500;600;700;800;900&display=swap" rel="stylesheet">
<style>{CSS}</style>
</head>
<body>
<div class="container">
{_header(data)}
{_summary(data)}
<div class="tab-nav">
<button class="tab-btn active" onclick="switchTab('topology')">🗺️ Topology</button>
<button class="tab-btn" onclick="switchTab('vms')">🖥️ VM</button>
<button class="tab-btn" onclick="switchTab('lxc')">📦 LXC</button>
<button class="tab-btn" onclick="switchTab('storage')">💾 Storage</button>
<button class="tab-btn" onclick="switchTab('network')">🌐 Network</button>
<button class="tab-btn" onclick="switchTab('backup')">📋 Backup</button>
<button class="tab-btn" onclick="switchTab('firewall')">🔥 Firewall</button>
</div>
<div class="tab-content active" id="tab-topology"><div class="section"><div class="section-header"><h2>🗺️ Network Topology</h2></div>{_topology(data)}</div></div>
<div class="tab-content" id="tab-vms">{_vm_cards(data)}</div>
<div class="tab-content" id="tab-lxc">{_lxc_cards(data)}</div>
<div class="tab-content" id="tab-storage">{_storage(data)}</div>
<div class="tab-content" id="tab-network">{_network(data)}</div>
<div class="tab-content" id="tab-backup">{_backup(data)}</div>
<div class="tab-content" id="tab-firewall">{_firewall(data)}</div>
</div>
<script>
function switchTab(t){{document.querySelectorAll('.tab-content').forEach(e=>e.classList.remove('active'));document.querySelectorAll('.tab-btn').forEach(e=>e.classList.remove('active'));document.getElementById('tab-'+t).classList.add('active');event.target.classList.add('active')}}
</script>
</body></html>"""


# ═══════════════════════════════════════════════════════════════════════════
#  PARTE 3: CLI
# ═══════════════════════════════════════════════════════════════════════════

def main():
    p = argparse.ArgumentParser(description="PVE Inventory — Snapshot + Dashboard")
    p.add_argument("--from", dest="from_json", metavar="FILE",
                   help="Genera dashboard da un JSON esistente (senza raccolta dati)")
    p.add_argument("-o", "--output", default=None,
                   help="Nome file HTML di output (default: pve_dashboard_TIMESTAMP.html)")
    p.add_argument("--json", action="store_true",
                   help="Salva anche il JSON oltre all'HTML")
    p.add_argument("--json-only", action="store_true",
                   help="Genera solo il JSON, senza dashboard HTML")
    p.add_argument("--stdout", action="store_true",
                   help="Stampa il JSON a stdout (con --json-only)")
    p.add_argument("--open", action="store_true",
                   help="Apri la dashboard nel browser dopo la generazione")
    p.add_argument("-f", "--filename", default="pve_inventory",
                   help="Nome base per i file (default: pve_inventory)")

    args = p.parse_args()

    # ── Modalità 1: Da JSON esistente ──
    if args.from_json:
        path = Path(args.from_json)
        if not path.exists():
            print(f"❌ File non trovato: {path}", file=sys.stderr)
            sys.exit(1)
        print(f"📂 Caricamento {path}...", file=sys.stderr)
        data = json.loads(path.read_text())

    # ── Modalità 2: Raccolta dati da PVE ──
    else:
        print("🔍 PVE Inventory — Raccolta dati in corso...\n", file=sys.stderr)
        if not check_pvesh():
            print("❌ pvesh non disponibile. Esegui su un nodo Proxmox come root.", file=sys.stderr)
            print("   Oppure usa: python3 pve_inventory.py --from snapshot.json", file=sys.stderr)
            sys.exit(1)
        data = gather_all()
        print(f"\n✅ Raccolta completata!", file=sys.stderr)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")

    # ── Solo JSON ──
    if args.json_only:
        if args.stdout:
            print(json.dumps(data, indent=2, ensure_ascii=False, default=str))
        else:
            jf = f"{args.filename}_{ts}.json"
            Path(jf).write_text(json.dumps(data, indent=2, ensure_ascii=False, default=str))
            print(f"📄 JSON: {jf}", file=sys.stderr)
        return

    # ── Salva JSON se richiesto ──
    if args.json and not args.from_json:
        jf = f"{args.filename}_{ts}.json"
        Path(jf).write_text(json.dumps(data, indent=2, ensure_ascii=False, default=str))
        print(f"📄 JSON: {jf}", file=sys.stderr)

    # ── Genera HTML ──
    print("🔨 Generazione dashboard...", file=sys.stderr)
    html = build_html(data)
    out = Path(args.output) if args.output else Path(f"{args.filename}_{ts}.html")
    out.write_text(html, encoding="utf-8")
    print(f"✅ Dashboard: {out} ({out.stat().st_size / 1024:.1f} KB)", file=sys.stderr)

    if args.open:
        webbrowser.open(f"file://{out.resolve()}")


if __name__ == "__main__":
    main()
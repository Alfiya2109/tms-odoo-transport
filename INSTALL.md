# 🛠️ Installation Guide — TMS Odoo Transport Management System

## 📦 Technologies Used

| Technology | Version | Purpose |
|------------|---------|---------|
| **Odoo** | 18.0 | ERP Platform (Core) |
| **Python** | 3.11+ | Backend Business Logic |
| **PostgreSQL** | 16 | Database |
| **OWL** | (Odoo built-in) | Frontend Framework (UI Components) |
| **QWeb XML** | (Odoo built-in) | PDF Reports & Templates |
| **Leaflet.js** | (bundled) | Interactive Maps |
| **Java** | JDK 11+ | Mobile API Layer (IsoTrax) |
| **Apache Tomcat** | 10 | Mobile App Server |
| **Apache Ant** | 1.10+ | Java Build Tool |
| **Git** | Latest | Version Control |

---

## ✅ Option 1 — Windows Auto Install (Recommended)

Run this script in PowerShell as Administrator:

```powershell
.\setup\install_windows.ps1
```

This will automatically install everything needed.

---

## 🔧 Option 2 — Manual Installation (Step by Step)

### Step 1 — Install Git
Download from: https://git-scm.com/download/win

### Step 2 — Clone this Repository
```bash
git clone --recurse-submodules https://github.com/Alfiya2109/tms-odoo-transport.git
cd tms-odoo-transport
```

### Step 3 — Install Odoo 18
1. Download Odoo 18 Community installer:
   👉 https://www.odoo.com/page/download
2. Run the installer — it will install **Python 3.11** and **PostgreSQL 16** automatically
3. Install Odoo as a Windows service

### Step 4 — Configure Odoo to use this TMS Module

Find your `odoo.conf` file at:
```
C:\Program Files\Odoo 18.0.xxxxx\server\odoo.conf
```

Add the custom addons path:
```ini
addons_path = C:\Program Files\Odoo 18.0.xxxxx\server\addons,C:\path\to\tms-odoo-transport\custom_addons
```

### Step 5 — Restart Odoo Service
```powershell
# Run as Administrator
Restart-Service odoo-server-18.0
```

### Step 6 — Install the TMS Module
1. Open browser → http://localhost:8069
2. Login with admin / admin
3. Go to **Apps** menu
4. Click **"Update App List"**
5. Search for **"Transport Management"**
6. Click **Install**

---

## 📱 Mobile Stack Setup (Optional — IsoTrax)

> Only needed if you want the mobile driver app API running.

### Requirements:
- Java JDK 11+: https://adoptium.net/
- Apache Tomcat 10: https://tomcat.apache.org/download-10.cgi
- Apache Ant 1.10+: https://ant.apache.org/bindownload.cgi

### Setup:
```bash
cd mobile_stack/api-gateway
ant build
# Deploy WAR to Tomcat webapps folder
```

---

## 🔍 Verify Installation

After setup, check these:

```powershell
# Check Odoo service is running
Get-Service odoo-server-18.0

# Check PostgreSQL is running
Get-Service PostgreSQL_For_Odoo

# Open Odoo in browser
Start-Process "http://localhost:8069"
```

---

## ❓ Troubleshooting

| Problem | Solution |
|---------|----------|
| Odoo not starting | Check `C:\Program Files\Odoo 18.0.xxx\server\odoo.log` |
| Module not showing | Click "Update App List" in Apps menu |
| Database error | Make sure PostgreSQL service is running |
| Port 8069 busy | Change port in `odoo.conf`: `xmlrpc_port = 8070` |

---

## 📞 Support

- 📧 Email: alfiyakhan0921@gmail.com
- 💬 WhatsApp: +91 7208048534
- 🐙 GitHub: https://github.com/Alfiya2109/tms-odoo-transport

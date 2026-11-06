# 🚛 Transport Management System (TMS) — Odoo Enterprise Custom Module

> **Built for:** edit solution AB, Sweden 🇸🇪  
> **Author:** Alfiya Khan — Full-Stack Engineer & Odoo Developer  
> **Version:** 1.30 | **License:** Proprietary  

---

## 📬 Contact
📧 [alfiyakhan0921@gmail.com](mailto:alfiyakhan0921@gmail.com) | 💬 [WhatsApp](https://wa.me/917208048534)

---

## 📋 Overview

A **production-grade, enterprise Transport Management System** built as a custom Odoo 17 addon for international freight and logistics operations in Sweden and Europe. This system handles end-to-end transport lifecycle from order creation through driver dispatch, real-time tracking, digital freight documentation (e-CMR), and automated commercial settlements.

---

## ✨ Key Features

### 🚛 Transport Order Management
- Complete transport order lifecycle (Draft → Confirmed → In Transit → Delivered)
- 400,000+ line Python model with complex business logic
- Multi-stop routing with dynamic leg assignment
- Custom OWL (Odoo Web Library) booking interface

### 📄 e-CMR Digital Freight (EU eFTI 2027 Compliant)
- Electronic Consignment Note (CMR) generation and management
- e-Signature capture and validation
- Cross-border digital freight documentation
- Proof of Delivery (ePOD) with timestamp/location

### 🗺️ Route Optimization & Planning Board
- Real-time transport planning dashboard
- Interactive map with live route visualization
- Automated dispatch assignment engine
- Driver log and vehicle odometer tracking

### 💰 Dynamic Pricing Engine
- Sales & Purchase price list management
- Fuel surcharge (CNR index) automation
- Zone-based pricing with custom discount rules
- German MAUT toll rate integration

### 📱 Mobile Reporting Stack
- Java-based mobile app (Apache Tomcat + Ant)
- Real-time driver reporting (IsoTrax mobile)
- Push notification service for drivers
- API gateway for mobile-to-Odoo communication

### 🏦 Commercial Settlement & Invoicing
- Automated settlement review workflows
- Purchase transport contract management
- Account move integration with Odoo Finance
- SSCC number generation and barcode printing

### 🌍 Multi-Tenant Architecture
- Tenant configuration management
- Role-based access control (RBAC)
- GDPR anonymization mixin
- API key management for external integrations

### 🔒 Safety & Compliance
- ADR substance handling (dangerous goods)
- Transport safety protocol enforcement
- Digital toll compliance (Digitoll service)
- NMFC freight class management

---

## 🛠️ Tech Stack

| Layer | Technology |
|-------|-----------|
| **ERP Platform** | Odoo 17 (Python 3.11+) |
| **Frontend** | OWL (Odoo Web Library), XML QWeb Templates |
| **Backend** | Python, PostgreSQL |
| **Mobile API** | Java, Apache Tomcat 10, Apache Ant |
| **Reporting** | QWeb PDF Reports, SSCC Barcode |
| **Integration** | e-CMR REST APIs, Digitoll, Push Notifications |
| **DevOps** | Custom Odoo addon packaging |

---

## 📁 Project Structure

```
TMS/
├── custom_addons/
│   ├── transport_management/     # Core TMS module (130+ models, 99 views)
│   │   ├── models/               # Python business logic
│   │   ├── views/                # XML UI definitions (OWL + QWeb)
│   │   ├── controllers/          # HTTP controllers
│   │   ├── report/               # PDF report templates
│   │   ├── security/             # Access rights & rules
│   │   └── data/                 # Demo & initial data
│   ├── isotrax/                  # Real-time GPS tracking module
│   ├── odoo_compat/              # Odoo version compatibility layer
│   ├── tenant_manager/           # Multi-tenancy management
│   ├── manuals_hub/              # Digital documentation hub
│   └── custom_b2b_wholesale/     # B2B wholesale integration
├── mobile_stack/
│   ├── api-gateway/              # Java REST API Gateway
│   └── isotrax-mobile-reporting/ # Driver mobile reporting app
├── ecmr_implementation_plan.md   # e-CMR strategic analysis
└── Field_Visibility_Proposal.pdf # UI field visibility spec
```

---

## 🚀 Setup (Development)

> ⚠️ Requires a running Odoo 17 instance with PostgreSQL.

```bash
# 1. Clone this repo into your Odoo custom addons path
git clone https://github.com/Alfiya2109/tms-odoo-transport.git

# 2. Add to Odoo addons path in odoo.conf
addons_path = /path/to/odoo/addons,/path/to/tms-odoo-transport/custom_addons

# 3. Restart Odoo and install the module
# Apps → Update App List → Search "Transport Management" → Install
```

---

## 👩‍💻 About the Developer

**Alfiya Khan** — Full-Stack Engineer & Odoo Developer  
Currently working with **edit solution AB, Sweden** as Odoo Developer & Frontend UI Lead.

- 🌍 Available for Global Remote & Full-Time Roles
- 💼 [LinkedIn](https://www.linkedin.com/in/alfiya-khan-dev/)
- 🐙 [GitHub](https://github.com/Alfiya2109)
- 📧 [alfiyakhan0921@gmail.com](mailto:alfiyakhan0921@gmail.com)
- 💬 [WhatsApp +91 7208048534](https://wa.me/917208048534)

import './index.css';

const GITHUB_URL = 'https://github.com/Alfiya2109/tms-odoo-transport';
const PORTFOLIO_URL = 'https://my-portfolio-one-teal-18.vercel.app';

const features = [
  {
    icon: '🚛',
    badge: 'Core Module',
    title: 'Transport Order Management',
    desc: 'Complete transport order lifecycle — from Draft to Delivered. Features multi-stop routing, automated dispatch assignment, and custom OWL booking interface built on Odoo Web Library.',
    tags: ['Python', 'OWL', 'PostgreSQL', 'QWeb'],
  },
  {
    icon: '📄',
    badge: 'EU Compliance',
    title: 'e-CMR Digital Freight',
    desc: 'Electronic Consignment Note generation with e-signature capture, cross-border digital documentation, and ePOD. Fully compliant with EU eFTI Regulation 2020/1056 (2027 mandate).',
    tags: ['e-CMR', 'eIDAS', 'eFTI', 'REST API'],
  },
  {
    icon: '🗺️',
    badge: 'Planning',
    title: 'Route Optimization & Planning Board',
    desc: 'Real-time transport planning dashboard with interactive map visualization, automated dispatch engine, driver log tracking, and vehicle odometer management.',
    tags: ['Route Engine', 'Maps API', 'Real-time', 'Odoo Board'],
  },
  {
    icon: '💰',
    badge: 'Pricing Engine',
    title: 'Dynamic Pricing & Fuel Surcharge',
    desc: 'Sophisticated sales & purchase price list management with CNR fuel index automation, zone-based pricing, custom discount rules, and German MAUT toll rate integration.',
    tags: ['CNR Index', 'Price Lists', 'German MAUT', 'Discounts'],
  },
  {
    icon: '📱',
    badge: 'Mobile Stack',
    title: 'Mobile Reporting (IsoTrax)',
    desc: 'Java-based driver mobile app running on Apache Tomcat 10 with real-time reporting, push notification service, and an API gateway bridging mobile to Odoo backend.',
    tags: ['Java', 'Apache Tomcat', 'REST API', 'Push Notifications'],
  },
  {
    icon: '🏦',
    badge: 'Finance',
    title: 'Commercial Settlement & Invoicing',
    desc: 'Automated settlement review workflows with purchase transport contract management, Odoo Accounting integration, and SSCC barcode number generation for shipment tracking.',
    tags: ['Odoo Accounting', 'SSCC', 'Settlements', 'Contracts'],
  },
  {
    icon: '🌍',
    badge: 'Architecture',
    title: 'Multi-Tenant Architecture',
    desc: 'Enterprise multi-tenancy with tenant configuration management, role-based access control (RBAC), GDPR anonymization mixin, and secure API key management for external integrations.',
    tags: ['Multi-Tenant', 'RBAC', 'GDPR', 'API Keys'],
  },
  {
    icon: '🔒',
    badge: 'Safety',
    title: 'Safety & ADR Compliance',
    desc: 'Full ADR dangerous goods handling, transport safety protocol enforcement, Digitoll electronic toll compliance for Romania/Bulgaria, and NMFC freight class management.',
    tags: ['ADR', 'Digitoll', 'Safety Protocols', 'NMFC'],
  },
];

const techStack = [
  { emoji: '🐍', name: 'Python 3.11+', desc: 'Business Logic' },
  { emoji: '🔵', name: 'Odoo 17', desc: 'ERP Platform' },
  { emoji: '🗄️', name: 'PostgreSQL', desc: 'Database' },
  { emoji: '⚙️', name: 'OWL', desc: 'Frontend Framework' },
  { emoji: '📋', name: 'QWeb XML', desc: 'Templates & Reports' },
  { emoji: '☕', name: 'Java', desc: 'Mobile API Layer' },
  { emoji: '🐱', name: 'Apache Tomcat', desc: 'Mobile Server' },
  { emoji: '🐜', name: 'Apache Ant', desc: 'Java Build Tool' },
];

const responsibilities = [
  'Owned end-to-end development of enterprise TMS for international logistics operations in Sweden, replacing legacy templates with high-performance OWL (Odoo Web Library) UI.',
  'Architected the e-CMR electronic freight protocol integration enabling paperless cross-border transit tracking, e-signatures, and automated ePOD documentation.',
  'Engineered custom PostgreSQL data models, automated dispatch workflows, and dynamic QWeb reporting templates for freight billing and driver manifests.',
  'Built the mobile reporting stack using Java/Apache Tomcat with real-time driver push notifications and a secure REST API gateway.',
  'Collaborated directly with international stakeholders in Sweden, adhering to Agile/Scrum delivery milestones and EU regulatory compliance deadlines.',
];

const timelineSteps = [
  { step: 'Step 01', title: 'Transport Order Created', text: 'Shipper logs a transport request via OWL portal. System auto-assigns order type, pricing, and customer SLAs.' },
  { step: 'Step 02', title: 'Route Planning & Driver Assignment', text: 'Planner uses the interactive planning board to optimize routes, assign drivers and vehicles, and dispatch the assignment.' },
  { step: 'Step 03', title: 'e-CMR Generated & Signed', text: 'Digital CMR consignment note auto-generated. Driver, shipper, and consignee sign electronically via mobile app.' },
  { step: 'Step 04', title: 'Real-Time Tracking', text: 'IsoTrax mobile app sends live location updates. Goods events and stop completions logged in real-time.' },
  { step: 'Step 05', title: 'Delivery & ePOD', text: 'Consignee signs digital proof of delivery. Order status auto-transitions to Delivered.' },
  { step: 'Step 06', title: 'Settlement & Invoice', text: 'Commercial settlement automatically calculated. Invoice generated and posted to Odoo Accounting.' },
];

export default function App() {
  return (
    <>
      {/* NAVBAR */}
      <nav className="navbar">
        <a href="#hero" className="nav-logo">
          <span className="nav-logo-icon">🚛</span>
          <span className="nav-logo-text">TMS · edit solution</span>
        </a>
        <ul className="nav-links">
          <li><a href="#features">Features</a></li>
          <li><a href="#ecmr">e-CMR</a></li>
          <li><a href="#tech">Tech Stack</a></li>
          <li><a href="#developer">Developer</a></li>
          <li><a href={GITHUB_URL} target="_blank" rel="noopener noreferrer" className="nav-cta">View on GitHub →</a></li>
        </ul>
      </nav>

      {/* HERO */}
      <section className="hero" id="hero">
        <div className="hero-bg" />
        <div className="hero-grid" />

        <div className="hero-badge animate-in">
          <span className="badge-dot" />
          Enterprise Odoo Module · Sweden 🇸🇪
        </div>

        <h1 className="hero-title animate-in delay-1">
          Enterprise<br />
          <span className="gradient-text">Transport Management</span><br />
          System
        </h1>

        <p className="hero-subtitle animate-in delay-2">
          A production-grade Odoo 17 TMS with e-CMR digital freight, 
          intelligent route optimization, mobile driver app, and 
          multi-tenant architecture — built for <strong style={{color:'#fbbf24'}}>edit solution AB, Sweden</strong>.
        </p>

        <div className="hero-buttons animate-in delay-3">
          <a href={GITHUB_URL} target="_blank" rel="noopener noreferrer" className="btn-primary">
            🐙 View Source on GitHub
          </a>
          <a href={PORTFOLIO_URL} target="_blank" rel="noopener noreferrer" className="btn-secondary">
            👩‍💻 Alfiya's Portfolio →
          </a>
        </div>

        <div className="hero-stats animate-in delay-4">
          <div className="stat-item">
            <div className="stat-number">130+</div>
            <div className="stat-label">Python Models</div>
          </div>
          <div className="stat-item">
            <div className="stat-number">99</div>
            <div className="stat-label">XML Views</div>
          </div>
          <div className="stat-item">
            <div className="stat-number">v1.30</div>
            <div className="stat-label">Module Version</div>
          </div>
          <div className="stat-item">
            <div className="stat-number">EU</div>
            <div className="stat-label">eFTI Compliant</div>
          </div>
        </div>
      </section>

      {/* OVERVIEW */}
      <div className="overview" id="overview">
        <div className="overview-inner">
          <div>
            <span className="overview-tag">🌍 Built for Sweden</span>
            <h2 className="overview-title">What is this TMS?</h2>
            <p className="overview-text">
              A fully custom Odoo 17 addon engineered for international road freight operations across Sweden and Europe. 
              It replaces manual paperwork with digital-first workflows — from order booking to driver dispatch, 
              real-time tracking, digital CMR documents, and automated financial settlement.
            </p>
            <div className="overview-facts">
              <div className="overview-fact">
                <div className="fact-icon">🏢</div>
                <span>Client: <strong>edit solution AB</strong>, Sweden — Enterprise Logistics ERP</span>
              </div>
              <div className="overview-fact">
                <div className="fact-icon">📅</div>
                <span>Built: <strong>2025–2026</strong> · Odoo 17 · v1.30</span>
              </div>
              <div className="overview-fact">
                <div className="fact-icon">📄</div>
                <span>EU <strong>eFTI Regulation 2020/1056</strong> compliant (2027 mandate)</span>
              </div>
              <div className="overview-fact">
                <div className="fact-icon">👩‍💻</div>
                <span>Developer: <strong>Alfiya Khan</strong> — Odoo Dev & Frontend UI Lead</span>
              </div>
            </div>
          </div>

          {/* Architecture Visual */}
          <div className="arch-visual">
            <div className="arch-header">
              <div className="arch-dot red" />
              <div className="arch-dot yellow" />
              <div className="arch-dot green" />
              <span style={{marginLeft:'0.5rem', color:'rgba(255,255,255,0.3)', fontSize:'0.75rem'}}>transport_management/__manifest__.py</span>
            </div>
            <div className="arch-line"><span className="arch-comment"># Transport Management System v1.30</span></div>
            <div className="arch-line"><span style={{color:'#c678dd'}}>{`{`}</span></div>
            <div className="arch-line arch-indent"><span className="arch-key">'name'</span><span className="arch-val">: "Transport Management",</span></div>
            <div className="arch-line arch-indent"><span className="arch-key">'version'</span><span className="arch-val">: '1.30',</span></div>
            <div className="arch-line arch-indent"><span className="arch-key">'author'</span><span className="arch-val">: "EdIT Solutions",</span></div>
            <div className="arch-line arch-indent"><span className="arch-key">'depends'</span><span className="arch-val">: [</span></div>
            <div className="arch-line arch-indent2"><span className="arch-val">'sale_management',</span></div>
            <div className="arch-line arch-indent2"><span className="arch-val">'account',</span></div>
            <div className="arch-line arch-indent2"><span className="arch-val">'account_peppol',</span></div>
            <div className="arch-line arch-indent2"><span className="arch-val">'portal',</span></div>
            <div className="arch-line arch-indent2"><span className="arch-val">'odoo_compat',</span></div>
            <div className="arch-line arch-indent"><span className="arch-val">],</span></div>
            <div className="arch-line arch-indent"><span className="arch-key">'models'</span><span className="arch-val">: 130+,  <span className="arch-comment"># Python files</span></span></div>
            <div className="arch-line arch-indent"><span className="arch-key">'views'</span><span className="arch-val">: 99,    <span className="arch-comment"># XML definitions</span></span></div>
            <div className="arch-line"><span style={{color:'#c678dd'}}>{`}`}</span></div>
          </div>
        </div>
      </div>

      {/* FEATURES */}
      <section className="features" id="features">
        <div className="container">
          <div className="section-label">Core Modules</div>
          <h2 className="section-title">Everything in One Platform</h2>
          <p className="section-desc">
            8 integrated modules covering the full transport lifecycle — from booking 
            to billing, with EU regulatory compliance built in.
          </p>
          <div className="features-grid">
            {features.map((f, i) => (
              <div className="feature-card" key={i}>
                <div className="feature-icon-wrap">{f.icon}</div>
                <div className="feature-badge">{f.badge}</div>
                <h3 className="feature-title">{f.title}</h3>
                <p className="feature-desc">{f.desc}</p>
                <div className="feature-tags">
                  {f.tags.map(t => <span className="feature-tag" key={t}>{t}</span>)}
                </div>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* e-CMR */}
      <section className="ecmr" id="ecmr">
        <div className="ecmr-inner container">
          <div>
            <div className="section-label">Digital Freight</div>
            <h2 className="section-title">e-CMR — Paperless<br />Cross-Border Freight</h2>
            <p className="section-desc">
              The EU's eFTI regulation (2020/1056) mandates that all transport authorities 
              must accept digital freight data by July 2027. This TMS is fully ready.
            </p>
            <div className="eu-badge">
              <div className="eu-badge-title">🇪🇺 EU eFTI Regulation 2020/1056</div>
              <div className="eu-badge-text">
                By July 9, 2027, all EU competent authorities (police, customs, transport inspectorates) 
                across EU member states must accept digital transport documents. This TMS implements 
                e-CMR with eIDAS-compliant e-signatures and ePOD (electronic Proof of Delivery).
              </div>
            </div>
          </div>
          <div className="ecmr-timeline">
            {timelineSteps.map((s, i) => (
              <div className="timeline-item" key={i}>
                <div className="timeline-dot">{i + 1}</div>
                <div className="timeline-content">
                  <div className="timeline-step">{s.step}</div>
                  <div className="timeline-title">{s.title}</div>
                  <div className="timeline-text">{s.text}</div>
                </div>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* TECH STACK */}
      <section className="techstack" id="tech">
        <div className="container">
          <div className="section-label">Technology</div>
          <h2 className="section-title">Built With</h2>
          <p className="section-desc">Enterprise-grade stack for reliability, scalability, and EU compliance.</p>
          <div className="tech-grid">
            {techStack.map((t, i) => (
              <div className="tech-card" key={i}>
                <div className="tech-emoji">{t.emoji}</div>
                <div className="tech-name">{t.name}</div>
                <div className="tech-desc">{t.desc}</div>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* DEVELOPER */}
      <section className="about-dev" id="developer">
        <div className="about-inner container">
          <div className="dev-card">
            <div className="dev-avatar">👩‍💻</div>
            <div className="dev-name">Alfiya Khan</div>
            <div className="dev-role">Odoo Developer & Frontend UI Lead</div>
            <div className="dev-available">
              <span style={{width:'7px',height:'7px',borderRadius:'50%',background:'#4ade80',display:'inline-block'}} />
              Available for Remote Roles
            </div>
            <div className="dev-links">
              <a href="https://my-portfolio-one-teal-18.vercel.app" target="_blank" rel="noopener noreferrer" className="dev-link">
                🌐 Portfolio
              </a>
              <a href="https://github.com/Alfiya2109" target="_blank" rel="noopener noreferrer" className="dev-link">
                🐙 GitHub
              </a>
              <a href="https://www.linkedin.com/in/alfiya-khan-dev/" target="_blank" rel="noopener noreferrer" className="dev-link">
                💼 LinkedIn
              </a>
              <a href="https://wa.me/917208048534" target="_blank" rel="noopener noreferrer" className="dev-link">
                💬 WhatsApp
              </a>
              <a href="mailto:alfiyakhan0921@gmail.com" className="dev-link">
                📧 Email
              </a>
            </div>
          </div>

          <div className="about-content">
            <div className="section-label">About the Developer</div>
            <h2 className="section-title">Built by Alfiya Khan</h2>
            <p style={{color:'var(--white-60)', lineHeight:1.8, marginBottom:'0.5rem'}}>
              Full-Stack Engineer and Odoo Developer currently working with <strong style={{color:'#fbbf24'}}>edit solution AB, Sweden</strong>.
              I architected and owned the end-to-end delivery of this enterprise TMS, transforming legacy Odoo 
              templates into a modern OWL-powered interface with European freight compliance.
            </p>
            <p style={{color:'var(--white-60)', lineHeight:1.8, marginBottom:'1.5rem'}}>
              With 4+ years of experience across Sweden and India, I specialize in React, Odoo, Python, 
              Java, NestJS, and AI-powered enterprise applications.
            </p>
            <div className="section-label" style={{marginTop:'1rem'}}>Key Responsibilities</div>
            <div className="responsibilities">
              {responsibilities.map((r, i) => (
                <div className="resp-item" key={i}>
                  <div className="resp-num">{String(i + 1).padStart(2, '0')}</div>
                  <div className="resp-text">{r}</div>
                </div>
              ))}
            </div>
          </div>
        </div>
      </section>

      {/* CTA */}
      <section className="cta-section">
        <h2 className="cta-title">
          Interested in this project?<br />
          <span style={{background:'linear-gradient(135deg,#fbbf24,#f97316)', WebkitBackgroundClip:'text', WebkitTextFillColor:'transparent', backgroundClip:'text'}}>
            Let's Connect
          </span>
        </h2>
        <p className="cta-desc">
          View the full source code on GitHub or reach out directly to discuss collaboration.
        </p>
        <div className="cta-buttons">
          <a href={GITHUB_URL} target="_blank" rel="noopener noreferrer" className="btn-primary">
            🐙 View Source on GitHub
          </a>
          <a href="https://wa.me/917208048534" target="_blank" rel="noopener noreferrer" className="btn-secondary">
            💬 WhatsApp Me
          </a>
          <a href={PORTFOLIO_URL} target="_blank" rel="noopener noreferrer" className="btn-secondary">
            🌐 Full Portfolio →
          </a>
        </div>
      </section>

      {/* FOOTER */}
      <footer>
        <p>
          Built by <a href={PORTFOLIO_URL}>Alfiya Khan</a> · 
          Odoo Developer & Frontend UI Lead at edit solution, Sweden 🇸🇪 · 
          <a href="mailto:alfiyakhan0921@gmail.com"> alfiyakhan0921@gmail.com</a>
        </p>
      </footer>
    </>
  );
}

import Image from "next/image";
import styles from "./marketing-landing.module.css";

type MarketingLandingProps = {
  appUrl: string | null;
  docsUrl: string | null;
  version: string;
};

const featureCards = [
  {
    title: "Klar statt laut",
    description:
      "Die Seite wirkt jetzt wie hocX selbst: strukturiert, ruhig, verlässlich und auf Arbeitsalltag statt Showeffekte ausgerichtet.",
  },
  {
    title: "Produktnah präsentiert",
    description:
      "Vorlagen, Protokolle, Aufgaben, Finanzen und Administration erscheinen im selben visuellen System wie in der Anwendung.",
  },
  {
    title: "Professionell verkaufsstark",
    description:
      "Die Landingpage verkauft hocX nicht mit Lärm, sondern mit Klarheit, Vertrauen und einem hochwertigen Produktauftritt.",
  },
];

const featureGrid = [
  {
    eyebrow: "Workspace",
    title: "Dashboard, Protokolle, Todos und Finanzen an einem Ort",
    text: "hocX bündelt die tägliche Arbeit in einer Oberfläche, damit nichts in Chats, Mails oder Dateien verschwindet.",
  },
  {
    eyebrow: "Vorlagen",
    title: "Wiederkehrende Abläufe werden zu belastbaren Standards",
    text: "Strukturen, Elemente, Zyklen und Dokument-Vorlagen sorgen dafür, dass jede Sitzung gleich professionell startet.",
  },
  {
    eyebrow: "Abgaben",
    title: "Öffentliche Upload-Strecken ohne Chaos im Posteingang",
    text: "Mit der Abgabebox sammeln Teams Unterlagen sauber ein, statt Dokumente aus zehn Quellen mühsam zusammenzusuchen.",
  },
  {
    eyebrow: "Administration",
    title: "Rollen, Benutzer, Mandanten und Domains sauber getrennt",
    text: "hocX skaliert vom einzelnen Team bis zur Organisation mit mehreren Bereichen und klaren Verantwortlichkeiten.",
  },
  {
    eyebrow: "Exports",
    title: "PDFs und Dokumente mit konsistentem Auftritt",
    text: "Die Inhalte stammen aus Snapshots – dadurch bleiben Protokolle nachvollziehbar, exportierbar und verlässlich.",
  },
  {
    eyebrow: "Verbindlichkeit",
    title: "Aus Beschlüssen werden Aufgaben mit sichtbarem Status",
    text: "Todos, Fristen und Zuständigkeiten sind nicht mehr Nebenprodukt, sondern Teil des eigentlichen Sitzungsablaufs.",
  },
];

const workflowSteps = [
  {
    index: "01",
    title: "Vorbereiten",
    text: "Vorlagen, Elemente und Zyklen definieren die Struktur im Voraus – wiederkehrende Sitzungen starten dadurch in Minuten.",
  },
  {
    index: "02",
    title: "Durchführen",
    text: "Während der Sitzung entstehen Inhalte, Aufgaben und Entscheide direkt dort, wo später auch nachverfolgt wird.",
  },
  {
    index: "03",
    title: "Abschliessen",
    text: "Export, Aufgabenübersicht, Finanzen und Folgepunkte gehen ohne Medienbruch in den nächsten Schritt über.",
  },
];

const trustItems = [
  "Mandantenfähig",
  "Rollenbasiert",
  "Eigene Domains",
  "PDF-Export",
  "Öffentliche Abgabebox",
  "Next.js + FastAPI Stack",
];

function resolveHref(preferred: string | null, fallback: string) {
  return preferred ?? fallback;
}

export function MarketingLanding({ appUrl, docsUrl, version }: MarketingLandingProps) {
  const primaryHref = resolveHref(appUrl, "#screenshots");
  const docsHref = resolveHref(docsUrl, "#features");

  return (
    <main className={styles.page}>
      <div className={styles.background}>
        <span className={styles.glowA} aria-hidden="true" />
        <span className={styles.glowB} aria-hidden="true" />
        <span className={styles.grid} aria-hidden="true" />
      </div>

      <header className={styles.header}>
        <a href="#top" className={styles.brand}>
          <span className={styles.brandMark}>hX</span>
          <span className={styles.brandText}>
            <strong>hocX</strong>
            <span>Protokoll- und Workspace-Plattform</span>
          </span>
        </a>

        <nav className={styles.nav}>
          <a href="#screenshots">Produkt</a>
          <a href="#features">Features</a>
          <a href="#workflow">Ablauf</a>
          <a href="#cta">Demo</a>
        </nav>

        <div className={styles.headerActions}>
          <a href={docsHref} className={styles.secondaryButton}>
            Architektur
          </a>
          <a href={primaryHref} className={styles.primaryButton}>
            hocX ansehen
          </a>
        </div>
      </header>

      <section id="top" className={styles.hero}>
        <div className={styles.heroCopy}>
          <div className={styles.kickerRow}>
            <span className={styles.kicker}>Professionelles Sitzungs- und Protokollsystem</span>
            <span className={styles.versionBadge}>Version {version}</span>
          </div>

          <h1>
            hocX wirkt jetzt wie das Produkt selbst:
            <span>klar, professionell und vertrauenswürdig.</span>
          </h1>

          <p className={styles.lead}>
            hocX bündelt Protokolle, Aufgaben, Vorlagen, Finanzen, Abgaben und Administration in
            einer Oberfläche, die nach echter Produktsoftware aussieht – nicht nach einer
            generischen Promo-Seite. Genau das schafft Vertrauen beim ersten Eindruck.
          </p>

          <div className={styles.heroActions}>
            <a href={primaryHref} className={styles.primaryButton}>
              Live-Plattform öffnen
            </a>
            <a href="#screenshots" className={styles.ghostButton}>
              Screenshots ansehen
            </a>
          </div>

          <div className={styles.trustStrip}>
            {trustItems.map((item) => (
              <span key={item}>{item}</span>
            ))}
          </div>
        </div>

        <div className={styles.heroVisual}>
          <div className={styles.heroCardLarge}>
            <div className={styles.browserChrome}>
              <span />
              <span />
              <span />
            </div>
            <Image
              src="/marketing/dashboard-shot.svg"
              alt="hocX Dashboard Screenshot"
              width={1600}
              height={1000}
              priority
            />
          </div>

          <div className={`${styles.floatingCard} ${styles.floatingCardOne}`}>
            <div className={styles.floatingLabel}>Protokoll-Editor</div>
            <Image
              src="/marketing/editor-shot.svg"
              alt="hocX Protokoll Editor Screenshot"
              width={1600}
              height={1000}
            />
          </div>

          <div className={`${styles.floatingCard} ${styles.floatingCardTwo}`}>
            <div className={styles.floatingLabel}>Mandanten & Vorlagen</div>
            <Image
              src="/marketing/admin-shot.svg"
              alt="hocX Admin und Vorlagen Screenshot"
              width={1600}
              height={1000}
            />
          </div>
        </div>
      </section>

      <section className={styles.storyGrid}>
        {featureCards.map((card) => (
          <article key={card.title} className={styles.storyCard}>
            <h2>{card.title}</h2>
            <p>{card.description}</p>
          </article>
        ))}
      </section>

      <section id="screenshots" className={styles.showcase}>
        <div className={styles.sectionHeading}>
          <span className={styles.sectionKicker}>Screenshots</span>
          <h2>So sieht hocX aus, wenn Sitzungsarbeit endlich modern wird.</h2>
          <p>
            Keine überinszenierte Werbeseite, sondern ein Auftritt, der die Qualität des Produkts
            selbst spürbar macht.
          </p>
        </div>

        <div className={styles.screenshotGrid}>
          <article className={styles.screenshotCard}>
            <div className={styles.browserChrome}>
              <span />
              <span />
              <span />
            </div>
            <Image
              src="/marketing/dashboard-shot.svg"
              alt="Screenshot des hocX Dashboards"
              width={1600}
              height={1000}
            />
            <div className={styles.screenshotCopy}>
              <h3>Dashboard mit Fokus</h3>
              <p>Todos, nächste Sitzung, offene Punkte und Zahlen liegen genau dort, wo sie gebraucht werden.</p>
            </div>
          </article>

          <article className={styles.screenshotCard}>
            <div className={styles.browserChrome}>
              <span />
              <span />
              <span />
            </div>
            <Image
              src="/marketing/editor-shot.svg"
              alt="Screenshot des hocX Editors"
              width={1600}
              height={1000}
            />
            <div className={styles.screenshotCopy}>
              <h3>Editor mit Struktur</h3>
              <p>Beschlüsse, Text, Listen, Aufgaben und Zusatzinfos bleiben während der Sitzung im selben Fluss.</p>
            </div>
          </article>

          <article className={styles.screenshotCard}>
            <div className={styles.browserChrome}>
              <span />
              <span />
              <span />
            </div>
            <Image
              src="/marketing/admin-shot.svg"
              alt="Screenshot von hocX Admin und Vorlagen"
              width={1600}
              height={1000}
            />
            <div className={styles.screenshotCopy}>
              <h3>Administration, die skaliert</h3>
              <p>Mandanten, Domains, Benutzer, Vorlagen und Upload-Strecken werden zentral und professionell geführt.</p>
            </div>
          </article>
        </div>
      </section>

      <section id="features" className={styles.featureSection}>
        <div className={styles.sectionHeading}>
          <span className={styles.sectionKicker}>Features</span>
          <h2>Gebaut für Teams, die mehr wollen als ein hübsches Protokoll.</h2>
          <p>
            hocX verbindet operative Sitzungsführung, organisatorische Struktur und einen
            professionellen Systemcharakter in einer Plattform.
          </p>
        </div>

        <div className={styles.featureGrid}>
          {featureGrid.map((feature) => (
            <article key={feature.title} className={styles.featureCard}>
              <span className={styles.featureEyebrow}>{feature.eyebrow}</span>
              <h3>{feature.title}</h3>
              <p>{feature.text}</p>
            </article>
          ))}
        </div>
      </section>

      <section id="workflow" className={styles.workflowSection}>
        <div className={styles.sectionHeading}>
          <span className={styles.sectionKicker}>Ablauf</span>
          <h2>Ein Workflow, der vor der Sitzung beginnt und nach dem PDF nicht endet.</h2>
          <p>
            hocX macht aus einzelnen Sitzungen einen durchgehenden Prozess – vorbereitet,
            durchgeführt, dokumentiert und verbindlich nachverfolgt.
          </p>
        </div>

        <div className={styles.workflowGrid}>
          {workflowSteps.map((step) => (
            <article key={step.index} className={styles.workflowCard}>
              <span className={styles.workflowIndex}>{step.index}</span>
              <h3>{step.title}</h3>
              <p>{step.text}</p>
            </article>
          ))}
        </div>
      </section>

      <section id="cta" className={styles.ctaSection}>
        <div className={styles.ctaPanel}>
          <div className={styles.ctaCopy}>
            <span className={styles.sectionKicker}>Bereit für den nächsten Schritt?</span>
            <h2>Wenn eure Sitzungen professionell laufen sollen, muss das Werkzeug dazu passen.</h2>
            <p>
              hocX ist kein nettes Zusatztool, sondern die zentrale Arbeitsoberfläche für Teams mit
              Verantwortung, Struktur und Anspruch.
            </p>
          </div>

          <div className={styles.ctaActions}>
            <a href={primaryHref} className={styles.primaryButton}>
              hocX live öffnen
            </a>
            <a href={docsHref} className={styles.secondaryButton}>
              Technische Doku
            </a>
          </div>
        </div>
      </section>

      <footer className={styles.footer}>
        <div>
          <strong>hocX</strong>
          <p>Professionelle Sitzungsarbeit, sauber orchestriert.</p>
        </div>
        <div className={styles.footerLinks}>
          <a href="#screenshots">Screenshots</a>
          <a href="#features">Features</a>
          <a href="#workflow">Ablauf</a>
        </div>
      </footer>
    </main>
  );
}

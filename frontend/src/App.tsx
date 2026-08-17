import { ServiceStatus } from "./components/ServiceStatus";
import { ExperimentWorkspace } from "./components/ExperimentWorkspace";
import "./styles.css";

export default function App() {
  const isBrowserVerification =
    import.meta.env.VITE_DACHIK_ENVIRONMENT === "browser-verification";
  return (
    <main className="app-shell">
      {isBrowserVerification && (
        <p className="verification-banner" role="status">
          Browser verification environment · synthetic temporary data
        </p>
      )}
      <section className="hero" aria-labelledby="product-name">
        <div className="brand-mark" aria-hidden="true">
          D
        </div>
        <p className="eyebrow">Privacy-first data accounting</p>
        <h1 id="product-name">Dachik</h1>
        <p className="positioning">Know where your data goes.</p>
        <p className="foundation-note">Create a private, local record of your plan and ISP balance evidence.</p>
        <ServiceStatus />
      </section>
      <ExperimentWorkspace />
    </main>
  );
}

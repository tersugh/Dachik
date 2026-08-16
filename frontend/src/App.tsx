import { ServiceStatus } from "./components/ServiceStatus";
import "./styles.css";

export default function App() {
  return (
    <main className="app-shell">
      <section className="hero" aria-labelledby="product-name">
        <div className="brand-mark" aria-hidden="true">
          D
        </div>
        <p className="eyebrow">Privacy-first data accounting</p>
        <h1 id="product-name">Dachik</h1>
        <p className="positioning">Know where your data goes.</p>
        <p className="foundation-note">
          The local service foundation is ready. Traffic measurement will arrive in a later phase.
        </p>
        <ServiceStatus />
      </section>
    </main>
  );
}

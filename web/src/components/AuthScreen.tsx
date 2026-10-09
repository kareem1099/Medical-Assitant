import { FormEvent, useState } from "react";
import { ArrowRight, BookOpenCheck, FileText, FlaskConical, Languages, LockKeyhole } from "lucide-react";
import { api } from "../api";
import type { User } from "../types";
import { cx, EMAIL_RE } from "../lib";
import { Logo, Pulse } from "./Pulse";

type Mode = "signin" | "register";

export function AuthScreen({ onAuthed }: { onAuthed: (u: User) => void }) {
  const [mode, setMode] = useState<Mode>("signin");
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setError("");
    if (!EMAIL_RE.test(email.trim())) return setError("Please enter a valid email address.");
    if (mode === "register" && !name.trim()) return setError("Tell us what to call you.");
    if (mode === "register" && password.length < 8) return setError("Use at least 8 characters for the password.");
    setBusy(true);
    try {
      const user = mode === "signin" ? await api.login(email.trim(), password) : await api.register(name.trim(), email.trim(), password);
      onAuthed(user);
    } catch (err: any) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="auth">
      <section className="auth-hero">
        <div className="auth-brand">
          <Logo size={38} />
          <span>Pulse</span>
          <em>Smart Medical Assistant</em>
        </div>

        <div className="auth-copy">
          <p className="eyebrow">Evidence-first medical answers</p>
          <h1>
            Ask like a clinician.
            <br />
            <span>Get answers with a pulse.</span>
          </h1>
          <p className="lede">
            Every answer is grounded in your own protocols and the latest PubMed research, and every claim comes with
            the source it came from.
          </p>
        </div>

        <div className="auth-monitor" aria-hidden="true">
          <Pulse beats={6} />
          <div className="monitor-readout">
            <span>EVIDENCE</span>
            <strong>live</strong>
          </div>
        </div>

        <div className="specimens" aria-hidden="true">
          <div className="specimen specimen-doc">
            <FileText size={15} />
            <div>
              <b>diabetes_protocol.pdf</b>
              <small>Page 2 · relevance 0.82</small>
            </div>
          </div>
          <div className="specimen specimen-paper">
            <FlaskConical size={15} />
            <div>
              <b>GLP-1 receptor agonists</b>
              <small>N Engl J Med · 2026</small>
            </div>
          </div>
          <div className="specimen specimen-ar" dir="rtl">
            <Languages size={15} />
            <div>
              <b>اسأل بالعربي</b>
              <small>إجابات بمصادر واضحة</small>
            </div>
          </div>
        </div>

        <ul className="auth-points">
          <li><BookOpenCheck size={16} /> Cites the exact page or paper</li>
          <li><LockKeyhole size={16} /> Private workspaces per account</li>
        </ul>
      </section>

      <section className="auth-panel">
        <form className="auth-card" onSubmit={submit} noValidate>
          <div className="seg" role="tablist">
            {(["signin", "register"] as Mode[]).map((m) => (
              <button
                key={m}
                type="button"
                role="tab"
                aria-selected={mode === m}
                className={cx("seg-item", mode === m && "is-on")}
                onClick={() => (setMode(m), setError(""))}
              >
                {m === "signin" ? "Sign in" : "Create account"}
              </button>
            ))}
          </div>

          <h2>{mode === "signin" ? "Welcome back." : "Start your first workspace."}</h2>
          <p className="muted">
            {mode === "signin" ? "Pick up your conversations where you left them." : "It takes ten seconds. Your documents stay yours."}
          </p>

          {mode === "register" && (
            <label className="field">
              <span>Display name</span>
              <input value={name} onChange={(e) => setName(e.target.value)} autoComplete="name" placeholder="Dr. Laila Mansour" dir="auto" />
            </label>
          )}
          <label className="field">
            <span>Email</span>
            <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} autoComplete="email" placeholder="you@hospital.org" />
          </label>
          <label className="field">
            <span>Password</span>
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoComplete={mode === "signin" ? "current-password" : "new-password"}
              placeholder={mode === "register" ? "At least 8 characters" : "••••••••"}
            />
          </label>

          {error && <p className="form-error" role="alert">{error}</p>}

          <button className="btn btn-primary btn-lg" disabled={busy}>
            {busy ? <Pulse beats={1} className="pulse-inline" /> : null}
            {busy ? "One moment…" : mode === "signin" ? "Sign in" : "Create account"}
            {!busy && <ArrowRight size={18} />}
          </button>

          <p className="fineprint">Educational information only, not medical advice. Always consult a qualified healthcare professional.</p>
        </form>
      </section>
    </div>
  );
}

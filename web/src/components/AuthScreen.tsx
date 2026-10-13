import { FormEvent, useState } from "react";
import { ArrowRight, BookOpenCheck, FileText, FlaskConical, Languages, LockKeyhole } from "lucide-react";
import { api } from "../api";
import type { User } from "../types";
import { EMAIL_RE } from "../lib";
import { GoogleButton } from "./GoogleButton";
import { Logo, Pulse } from "./Pulse";

type Mode = "signin" | "forgot" | "reset";

const COPY: Record<Mode, { title: string; lede: string; action: string }> = {
  signin: { title: "Welcome to Pulse.", lede: "New here? Continue with Google and your account is ready in seconds.", action: "Sign in" },
  forgot: { title: "Forgot your password?", lede: "Enter your email and we'll send you a code to choose a new one.", action: "Send code" },
  reset: { title: "Choose a new password.", lede: "Enter the 6-digit code from your email and a new password.", action: "Save and sign in" },
};

export function AuthScreen({ onAuthed }: { onAuthed: (u: User) => void }) {
  const [mode, setMode] = useState<Mode>("signin");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [code, setCode] = useState("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);

  function go(next: Mode, message = "") {
    setMode(next);
    setError("");
    setNotice(message);
    setCode("");
    if (next === "reset") setPassword("");
  }

  async function submit(e: FormEvent) {
    e.preventDefault();
    setError("");
    const address = email.trim();
    if (!EMAIL_RE.test(address)) return setError("Please enter a valid email address.");
    if (mode === "reset" && password.length < 8) return setError("Use at least 8 characters for the password.");
    if (mode === "reset" && !/^\d{6}$/.test(code.trim())) return setError("Enter the 6-digit code from the email.");
    setBusy(true);
    try {
      if (mode === "signin") onAuthed(await api.login(address, password));
      else if (mode === "forgot") {
        await api.forgotPassword(address);
        go("reset", `If ${address} has an account, a code is on its way.`);
      } else onAuthed(await api.resetPassword(address, code.trim(), password));
    } catch (err: any) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  async function withGoogle(credential: string) {
    setError("");
    setBusy(true);
    try {
      onAuthed(await api.google(credential));
    } catch (err: any) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  async function resend() {
    setError("");
    setBusy(true);
    try {
      await api.forgotPassword(email.trim());
      setNotice("If a minute has passed since the last one, a new code is on its way.");
    } catch (err: any) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  const needsCode = mode === "reset";

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
          <h2>{COPY[mode].title}</h2>
          <p className="muted">{COPY[mode].lede}</p>

          {mode === "signin" && (
            <>
              <GoogleButton onCredential={withGoogle} onError={setError} />
              <div className="auth-divider" role="separator">
                <span>or sign in with a password</span>
              </div>
            </>
          )}

          {notice && <p className="form-note" role="status">{notice}</p>}

          <label className="field">
            <span>Email</span>
            <input
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              autoComplete="email"
              placeholder="you@hospital.org"
              readOnly={needsCode}
            />
          </label>
          {needsCode && (
            <label className="field">
              <span>Code</span>
              <input
                value={code}
                onChange={(e) => setCode(e.target.value.replace(/\D/g, "").slice(0, 6))}
                inputMode="numeric"
                autoComplete="one-time-code"
                placeholder="123456"
                className="code-input"
                autoFocus
              />
            </label>
          )}
          {mode !== "forgot" && (
            <label className="field">
              <span className="field-row">
                {mode === "reset" ? "New password" : "Password"}
                {mode === "signin" && (
                  <button type="button" className="link" onClick={() => go("forgot")}>
                    Forgot password?
                  </button>
                )}
              </span>
              <input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                autoComplete={mode === "signin" ? "current-password" : "new-password"}
                placeholder={mode === "signin" ? "••••••••" : "At least 8 characters"}
              />
            </label>
          )}

          {error && <p className="form-error" role="alert">{error}</p>}

          <button className={mode === "signin" ? "btn btn-ink btn-lg" : "btn btn-primary btn-lg"} disabled={busy}>
            {busy ? <Pulse beats={1} className="pulse-inline" /> : null}
            {busy ? "One moment…" : COPY[mode].action}
            {!busy && <ArrowRight size={18} />}
          </button>

          {mode !== "signin" && (
            <p className="auth-alt">
              {needsCode && (
                <button type="button" className="link" onClick={resend} disabled={busy}>
                  Send a new code
                </button>
              )}
              <button type="button" className="link" onClick={() => go("signin")}>
                Back to sign in
              </button>
            </p>
          )}

          <p className="fineprint">Educational information only, not medical advice. Always consult a qualified healthcare professional.</p>
        </form>
      </section>
    </div>
  );
}

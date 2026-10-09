import { useState } from "react";
import { LogOut, Monitor, Moon, Sun } from "lucide-react";
import { cx, EMAIL_RE, Theme } from "../lib";
import { Modal } from "./Overlay";

interface Props {
  theme: Theme;
  setTheme: (t: Theme) => void;
  ncbiEmail: string;
  setNcbiEmail: (v: string) => void;
  onSignOut: () => void;
  onClose: () => void;
}

export function SettingsDialog(p: Props) {
  const [email, setEmail] = useState(p.ncbiEmail);
  const invalid = email.trim() !== "" && !EMAIL_RE.test(email.trim());
  const themes: [Theme, typeof Sun, string][] = [["light", Sun, "Light"], ["dark", Moon, "Dark"], ["system", Monitor, "System"]];

  return (
    <Modal title="Settings" onClose={p.onClose}>
      <div className="modal-body settings">
        <section>
          <h3>Appearance</h3>
          <div className="seg">
            {themes.map(([value, Icon, label]) => (
              <button key={value} className={cx("seg-item", p.theme === value && "is-on")} onClick={() => p.setTheme(value)}>
                <Icon size={15} /> {label}
              </button>
            ))}
          </div>
        </section>
        <section>
          <h3>PubMed</h3>
          <label className="field">
            <span>NCBI email</span>
            <input
              type="email"
              value={email}
              placeholder="you@example.com"
              onChange={(e) => setEmail(e.target.value)}
              onBlur={() => !invalid && p.setNcbiEmail(email.trim())}
              aria-invalid={invalid}
            />
          </label>
          <p className={cx("hint", invalid && "hint-error")}>
            {invalid
              ? "That doesn't look like an email address."
              : "NCBI asks every PubMed request to identify itself with an email. It is kept in this browser only and sent with your questions."}
          </p>
        </section>
      </div>
      <footer className="modal-foot spread">
        <button className="btn btn-ghost danger" onClick={p.onSignOut}>
          <LogOut size={16} /> Sign out
        </button>
        <button className="btn btn-primary" disabled={invalid} onClick={() => (p.setNcbiEmail(email.trim()), p.onClose())}>
          Done
        </button>
      </footer>
    </Modal>
  );
}

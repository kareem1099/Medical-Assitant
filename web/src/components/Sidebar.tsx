import { FormEvent, useEffect, useRef, useState } from "react";
import { Check, ChevronsUpDown, FolderPlus, MessageSquarePlus, Settings2, Trash2, X } from "lucide-react";
import type { Conversation, User, Workspace } from "../types";
import { cx, relativeTime } from "../lib";
import { Logo } from "./Pulse";

interface Props {
  user: User;
  workspaces: Workspace[];
  activeWs: Workspace | null;
  conversations: Conversation[];
  activeConvId: string | null;
  busy: boolean;
  open: boolean;
  onClose: () => void;
  onSelectWs: (id: string) => void;
  onCreateWs: (name: string) => Promise<void>;
  onDeleteWs: (ws: Workspace) => void;
  onNewChat: () => void;
  onSelectConv: (id: string) => void;
  onDeleteConv: (c: Conversation) => void;
  onSettings: () => void;
}

function groupByDay(items: Conversation[]) {
  const today = new Date().toDateString();
  const yesterday = new Date(Date.now() - 86400000).toDateString();
  const groups: [string, Conversation[]][] = [];
  for (const c of items) {
    const day = c.updated_at ? new Date(c.updated_at).toDateString() : today;
    const label = day === today ? "Today" : day === yesterday ? "Yesterday" : "Earlier";
    const group = groups.find((g) => g[0] === label);
    group ? group[1].push(c) : groups.push([label, [c]]);
  }
  return groups;
}

export function Sidebar(p: Props) {
  const [menu, setMenu] = useState(false);
  const [creating, setCreating] = useState(false);
  const [name, setName] = useState("");
  const menuRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!menu) return;
    const close = (e: MouseEvent) => !menuRef.current?.contains(e.target as Node) && (setMenu(false), setCreating(false));
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, [menu]);

  async function create(e: FormEvent) {
    e.preventDefault();
    if (!name.trim()) return;
    await p.onCreateWs(name.trim());
    setName("");
    setCreating(false);
    setMenu(false);
  }

  const initials = p.user.display_name.split(/\s+/).map((w) => w[0]).slice(0, 2).join("").toUpperCase() || "?";

  return (
    <aside className={cx("sidebar", p.open && "is-open")}>
      <div className="sidebar-top">
        <div className="brand">
          <Logo />
          <div>
            <strong>Pulse</strong>
            <small>Medical assistant</small>
          </div>
          <button className="icon-btn only-mobile" aria-label="Close menu" onClick={p.onClose}>
            <X size={18} />
          </button>
        </div>

        <div className="ws-switch" ref={menuRef}>
          <button className="ws-current" onClick={() => setMenu((m) => !m)} aria-expanded={menu}>
            <span className="ws-glyph">{p.activeWs?.name.slice(0, 1).toUpperCase() ?? "·"}</span>
            <span className="ws-meta">
              <small>Workspace</small>
              <b dir="auto">{p.activeWs?.name ?? "No workspace"}</b>
            </span>
            <ChevronsUpDown size={16} />
          </button>
          {menu && (
            <div className="ws-menu">
              {p.workspaces.map((w) => (
                <div key={w.id} className={cx("ws-row", w.id === p.activeWs?.id && "is-on")}>
                  <button className="ws-pick" onClick={() => (p.onSelectWs(w.id), setMenu(false))}>
                    <span className="ws-glyph sm">{w.name.slice(0, 1).toUpperCase()}</span>
                    <span dir="auto">{w.name}</span>
                    <small>{w.file_count} doc{w.file_count === 1 ? "" : "s"}</small>
                    {w.id === p.activeWs?.id && <Check size={15} />}
                  </button>
                  <button className="icon-btn danger" aria-label={`Delete ${w.name}`} onClick={() => (setMenu(false), p.onDeleteWs(w))}>
                    <Trash2 size={14} />
                  </button>
                </div>
              ))}
              {creating ? (
                <form className="ws-create" onSubmit={create}>
                  <input autoFocus value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Cardiology protocols" maxLength={80} dir="auto" />
                  <button className="btn btn-primary btn-sm" disabled={!name.trim()}>Create</button>
                </form>
              ) : (
                <button className="ws-new" onClick={() => setCreating(true)}>
                  <FolderPlus size={16} /> New workspace
                </button>
              )}
            </div>
          )}
        </div>

        <button className="btn btn-ink new-chat" onClick={p.onNewChat} disabled={!p.activeWs || p.busy}>
          <MessageSquarePlus size={17} /> New conversation
        </button>
      </div>

      <nav className="conv-list" aria-label="Conversations">
        {p.conversations.length === 0 && <p className="empty-note">No conversations yet.</p>}
        {groupByDay(p.conversations).map(([label, items]) => (
          <div key={label} className="conv-group">
            <h3>{label}</h3>
            {items.map((c) => (
              <div key={c.id} className={cx("conv", c.id === p.activeConvId && "is-on")}>
                <button className="conv-pick" onClick={() => p.onSelectConv(c.id)} disabled={p.busy && c.id !== p.activeConvId}>
                  <span className="conv-title" dir="auto">{c.title}</span>
                  <span className="conv-sub">
                    {c.preview ? <span dir="auto">{c.preview.replace(/[#*_`>]/g, "").slice(0, 60)}</span> : <i>Empty</i>}
                    <time>{relativeTime(c.updated_at)}</time>
                  </span>
                </button>
                <button className="icon-btn danger conv-del" aria-label="Delete conversation" onClick={() => p.onDeleteConv(c)} disabled={p.busy}>
                  <Trash2 size={14} />
                </button>
              </div>
            ))}
          </div>
        ))}
      </nav>

      <footer className="sidebar-foot">
        <span className="avatar">{initials}</span>
        <span className="who">
          <b dir="auto">{p.user.display_name}</b>
          <small>{p.user.email}</small>
        </span>
        <button className="icon-btn" aria-label="Settings" onClick={p.onSettings}>
          <Settings2 size={18} />
        </button>
      </footer>
    </aside>
  );
}

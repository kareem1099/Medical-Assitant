import { KeyboardEvent, useEffect, useLayoutEffect, useRef, useState } from "react";
import {
  ArrowUp, Check, Copy, Eraser, FileText, FlaskConical, Languages, Library, Menu, PanelRight, Pencil, RotateCcw, Scale, Stethoscope,
} from "lucide-react";
import type { Conversation, Message, StageEvent, User, Workspace } from "../types";
import { cx, greeting, hasArabic } from "../lib";
import { Markdown } from "./Markdown";
import { Pulse } from "./Pulse";

export interface ErrorItem {
  id: string;
  role: "error";
  content: string;
  retry: string;
  userId: string; // the unsent question shown above the error
}
export type ThreadItem = Message | ErrorItem;

const SUGGESTIONS = [
  { icon: Stethoscope, tag: "Explain", text: "What is hypertension and how is it usually treated?" },
  { icon: FlaskConical, tag: "Latest research", text: "What does recent research say about GLP-1 agonists for type 2 diabetes?" },
  { icon: FileText, tag: "Your documents", text: "Summarize the document I uploaded." },
  { icon: Scale, tag: "Compare", text: "How does our protocol compare with recent studies?" },
  { icon: Languages, tag: "بالعربي", text: "ما هي أعراض نقص فيتامين د وإزاي بيتعالج؟" },
];

const TOOL_LABEL: Record<string, string> = { medical_rag_search: "your documents", search_pubmed: "PubMed" };

/** Live progress from the graph. `stage.tools` is kept by the app once a search started. */
function Thinking({ stage }: { stage: StageEvent }) {
  const where = stage.tools?.map((t) => TOOL_LABEL[t] ?? t).join(" & ");
  const at = { thinking: 0, searching: 1, writing: 2 }[stage.stage];
  const steps = [
    { label: "Reading your question", index: 0 },
    // A direct answer skips the search step entirely.
    ...(where || at < 2 ? [{ label: where ? `Searching ${where}` : "Deciding where to look", index: 1 }] : []),
    { label: where ? "Writing a cited answer" : "Writing the answer", index: 2 },
  ];
  return (
    <div className="msg msg-assistant">
      <div className="thinking" role="status" aria-live="polite">
        <Pulse beats={4} />
        <ol>
          {steps.map((s) => {
            const state = s.index < at ? "done" : s.index === at ? "now" : "todo";
            return (
              <li key={s.index} className={`step-${state}`}>
                <span className="step-dot">{state === "done" ? <Check size={11} /> : null}</span>
                {s.label}
              </li>
            );
          })}
        </ol>
      </div>
    </div>
  );
}

function AssistantMessage({ m, selected, onSources }: { m: Message; selected: boolean; onSources: () => void }) {
  const [copied, setCopied] = useState(false);
  const docs = m.sources.filter((s) => s.type === "local").length;
  const papers = m.sources.length - docs;
  return (
    <div className={cx("msg msg-assistant", selected && "is-selected")}>
      <div className="note">
        <Markdown text={m.content} />
        <div className="note-foot">
          {m.sources.length > 0 ? (
            <button className="evidence-chip" onClick={onSources}>
              {docs > 0 && <span className="dot dot-doc" />}
              {papers > 0 && <span className="dot dot-paper" />}
              {docs > 0 && `${docs} document${docs > 1 ? "s" : ""}`}
              {docs > 0 && papers > 0 && " · "}
              {papers > 0 && `${papers} paper${papers > 1 ? "s" : ""}`}
            </button>
          ) : (
            <span className="no-evidence">General knowledge, no sources searched</span>
          )}
          <button
            className="icon-btn"
            aria-label="Copy answer"
            onClick={async () => {
              try {
                await navigator.clipboard.writeText(m.content);
                setCopied(true);
                setTimeout(() => setCopied(false), 1500);
              } catch {
                /* clipboard blocked */
              }
            }}
          >
            {copied ? <Check size={15} /> : <Copy size={15} />}
          </button>
        </div>
      </div>
    </div>
  );
}

interface Props {
  user: User;
  workspace: Workspace | null;
  conversation: Conversation | null;
  items: ThreadItem[];
  loading: boolean;
  pending: StageEvent | null;
  selectedId: string | null;
  draft: string;
  setDraft: (v: string) => void;
  onSend: (text: string) => void;
  onRetry: (item: ErrorItem) => void;
  onShowSources: (m: Message) => void;
  onRename: (title: string) => void;
  onClear: () => void;
  onOpenSidebar: () => void;
  onOpenPanel: () => void;
  onOpenLibrary: () => void;
}

export function Chat(p: Props) {
  const scroller = useRef<HTMLDivElement>(null);
  const input = useRef<HTMLTextAreaElement>(null);
  const [editing, setEditing] = useState(false);
  const [title, setTitle] = useState("");
  const busy = p.pending !== null;
  const empty = !p.loading && p.items.length === 0 && !busy;

  useEffect(() => {
    const el = scroller.current;
    if (el) el.scrollTo({ top: el.scrollHeight, behavior: p.items.length > 2 ? "smooth" : "auto" });
  }, [p.items.length, p.pending?.stage]);

  useLayoutEffect(() => {
    const el = input.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = Math.min(el.scrollHeight, 220) + "px";
  }, [p.draft]);

  useEffect(() => {
    if (!busy) input.current?.focus();
  }, [busy, p.conversation?.id]);

  function send() {
    const text = p.draft.trim();
    if (!text || busy || !p.workspace) return;
    p.onSend(text);
  }

  function onKey(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault();
      send();
    }
  }

  function saveTitle() {
    setEditing(false);
    if (title.trim() && title.trim() !== p.conversation?.title) p.onRename(title.trim());
  }

  return (
    <main className="chat">
      <header className="chat-head">
        <button className="icon-btn only-mobile" aria-label="Open menu" onClick={p.onOpenSidebar}>
          <Menu size={20} />
        </button>
        <div className="chat-title">
          {editing ? (
            <input
              autoFocus
              value={title}
              maxLength={120}
              dir="auto"
              onChange={(e) => setTitle(e.target.value)}
              onBlur={saveTitle}
              onKeyDown={(e) => (e.key === "Enter" ? saveTitle() : e.key === "Escape" && setEditing(false))}
            />
          ) : (
            <h1 dir="auto" onDoubleClick={() => p.conversation && (setTitle(p.conversation.title), setEditing(true))}>
              {p.conversation?.title ?? "New conversation"}
            </h1>
          )}
          <span className="crumb" dir="auto">
            {p.workspace?.name} · {p.workspace?.file_count ?? 0} document{p.workspace?.file_count === 1 ? "" : "s"}
          </span>
        </div>
        <div className="chat-actions">
          {p.conversation && !editing && (
            <button className="icon-btn" aria-label="Rename conversation" title="Rename" onClick={() => (setTitle(p.conversation!.title), setEditing(true))}>
              <Pencil size={16} />
            </button>
          )}
          <button className="icon-btn" aria-label="Clear conversation" title="Clear messages" onClick={p.onClear} disabled={busy || p.items.length === 0}>
            <Eraser size={16} />
          </button>
          <button className="icon-btn panel-toggle" aria-label="Evidence and documents" title="Evidence & documents" onClick={p.onOpenPanel}>
            <PanelRight size={18} />
          </button>
        </div>
      </header>

      <div className="thread" ref={scroller}>
        {empty ? (
          <div className="welcome">
            <Pulse beats={5} className="welcome-pulse" />
            <h2>{greeting(p.user.display_name)}</h2>
            <p>
              What should we look into? I'll search{" "}
              <button className="link" onClick={p.onOpenLibrary}>
                {p.workspace?.file_count ? `your ${p.workspace.file_count} document${p.workspace.file_count > 1 ? "s" : ""}` : "your documents"}
              </button>{" "}
              and <b>PubMed</b> when it helps, and show you exactly where every answer came from.
            </p>
            <div className="suggestions">
              {SUGGESTIONS.map(({ icon: Icon, tag, text }) => (
                <button key={text} className={cx("suggestion", hasArabic(text) && "is-ar")} onClick={() => p.onSend(text)} disabled={!p.workspace}>
                  <span className="suggestion-tag">
                    <Icon size={14} /> {tag}
                  </span>
                  <span dir="auto">{text}</span>
                </button>
              ))}
            </div>
            {!p.workspace?.file_count && (
              <button className="upload-nudge" onClick={p.onOpenLibrary}>
                <Library size={16} /> Add a PDF to ground answers in your own protocols
              </button>
            )}
          </div>
        ) : (
          <div className="thread-inner">
            {p.loading && <Pulse beats={3} className="thread-loading" />}
            {p.items.map((m) =>
              m.role === "user" ? (
                <div key={m.id} className="msg msg-user">
                  <div className="bubble" dir="auto">{m.content}</div>
                </div>
              ) : m.role === "error" ? (
                <div key={m.id} className="msg msg-assistant">
                  <div className="note note-error">
                    <p dir="auto">{m.content}</p>
                    <button className="btn btn-ghost btn-sm" onClick={() => p.onRetry(m)} disabled={busy}>
                      <RotateCcw size={14} /> Try again
                    </button>
                  </div>
                </div>
              ) : (
                <AssistantMessage key={m.id} m={m} selected={m.id === p.selectedId} onSources={() => p.onShowSources(m)} />
              ),
            )}
            {p.pending && <Thinking stage={p.pending} />}
          </div>
        )}
      </div>

      <div className="composer-wrap">
        <div className={cx("composer", busy && "is-busy")}>
          <textarea
            ref={input}
            rows={1}
            value={p.draft}
            dir="auto"
            maxLength={4000}
            placeholder={p.workspace ? "Ask a medical question…" : "Create a workspace to start"}
            onChange={(e) => p.setDraft(e.target.value)}
            onKeyDown={onKey}
            disabled={!p.workspace}
            aria-label="Your question"
          />
          <button className="send" aria-label="Send" onClick={send} disabled={busy || !p.draft.trim() || !p.workspace}>
            {busy ? <Pulse beats={1} className="pulse-inline" /> : <ArrowUp size={19} />}
          </button>
        </div>
        <p className="composer-hint">
          <span className="hint-keys">
            <kbd>Enter</kbd> to send · <kbd>Shift</kbd>+<kbd>Enter</kbd> new line ·{" "}
          </span>
          Educational information only, not medical advice.
        </p>
      </div>
    </main>
  );
}

import { DragEvent, useRef, useState } from "react";
import { AlertCircle, ExternalLink, FileText, FlaskConical, Trash2, UploadCloud, X } from "lucide-react";
import { api } from "../api";
import type { DocFile, LocalSource, PubmedSource, Source, Workspace } from "../types";
import { cx, relativeTime } from "../lib";
import { useToast } from "./Overlay";
import { Pulse } from "./Pulse";

export type PanelTab = "evidence" | "library";

interface Upload {
  key: string;
  name: string;
  progress: number; // 0..1 sent; 1 = server is indexing
}

interface Props {
  tab: PanelTab;
  setTab: (t: PanelTab) => void;
  open: boolean;
  onClose: () => void;
  sources: Source[] | null;
  workspace: Workspace | null;
  files: DocFile[];
  onFilesChanged: () => void;
  onDeleteFile: (f: DocFile) => void;
}

function DocCard({ s, i }: { s: LocalSource; i: number }) {
  const score = typeof s.score === "number" ? Math.max(0, Math.min(1, s.score)) : null;
  return (
    <li className="card card-doc" style={{ ["--i" as any]: i }}>
      <div className="card-kind">
        <FileText size={14} /> Your document
      </div>
      <b dir="auto">{s.filename ?? s.label}</b>
      <div className="card-meta">
        {s.page != null && <span className="mono">PAGE {s.page}</span>}
        {score !== null && (
          <span className="relevance" title={`Relevance ${score.toFixed(2)}`}>
            <span className="relevance-bar">
              <span style={{ width: `${Math.round(score * 100)}%` }} />
            </span>
            <span className="mono">{score.toFixed(2)}</span>
          </span>
        )}
      </div>
    </li>
  );
}

function PaperCard({ s, i }: { s: PubmedSource; i: number }) {
  const title = s.title || s.label.split(" — ")[0];
  return (
    <li className="card card-paper" style={{ ["--i" as any]: i }}>
      <div className="card-kind">
        <FlaskConical size={14} /> PubMed
      </div>
      {s.url ? (
        <a href={s.url} target="_blank" rel="noreferrer noopener" className="card-title-link">
          <b>{title}</b>
          <ExternalLink size={13} />
        </a>
      ) : (
        <b>{title}</b>
      )}
      <div className="card-meta">
        {s.journal && <span className="journal">{s.journal}</span>}
        {s.date && <span className="mono">{s.date}</span>}
        {s.pmid && <span className="mono">PMID {s.pmid}</span>}
      </div>
    </li>
  );
}

function Evidence({ sources }: { sources: Source[] | null }) {
  if (!sources || sources.length === 0) {
    return (
      <div className="panel-empty">
        <Pulse beats={2} active={false} />
        <h3>{sources ? "No sources for this answer" : "Evidence appears here"}</h3>
        <p>
          {sources
            ? "That answer came from general medical knowledge. Ask about your documents or recent research to see sources."
            : "When an answer uses your documents or PubMed, every page and paper it relied on is listed here."}
        </p>
      </div>
    );
  }
  const docs = sources.filter((s): s is LocalSource => s.type === "local");
  const papers = sources.filter((s): s is PubmedSource => s.type === "pubmed");
  return (
    <div className="evidence">
      {docs.length > 0 && (
        <section>
          <h4><span className="dot dot-doc" /> From your documents <small>{docs.length}</small></h4>
          <ul className="cards">{docs.map((s, i) => <DocCard key={s.label + i} s={s} i={i} />)}</ul>
        </section>
      )}
      {papers.length > 0 && (
        <section>
          <h4><span className="dot dot-paper" /> From PubMed <small>{papers.length}</small></h4>
          <ul className="cards">{papers.map((s, i) => <PaperCard key={s.label + i} s={s} i={i + docs.length} />)}</ul>
        </section>
      )}
    </div>
  );
}

function LibraryTab({ workspace, files, onFilesChanged, onDeleteFile }: Pick<Props, "workspace" | "files" | "onFilesChanged" | "onDeleteFile">) {
  const [uploads, setUploads] = useState<Upload[]>([]);
  const [dragging, setDragging] = useState(false);
  const picker = useRef<HTMLInputElement>(null);
  const toast = useToast();

  async function upload(list: FileList | File[]) {
    if (!workspace) return;
    for (const file of Array.from(list)) {
      if (!file.name.toLowerCase().endsWith(".pdf")) {
        toast(`${file.name} is not a PDF.`, "error");
        continue;
      }
      const key = `${file.name}-${Date.now()}`;
      setUploads((u) => [...u, { key, name: file.name, progress: 0 }]);
      try {
        const res = await api.uploadFile(workspace.id, file, (progress) =>
          setUploads((u) => u.map((x) => (x.key === key ? { ...x, progress } : x))),
        );
        toast(`${res.filename} ${res.replaced ? "replaced" : "added"}: ${res.num_chunks} searchable passages.`, "success");
      } catch (err: any) {
        toast(err.message, "error");
      } finally {
        setUploads((u) => u.filter((x) => x.key !== key));
        onFilesChanged();
      }
    }
  }

  function onDrop(e: DragEvent) {
    e.preventDefault();
    setDragging(false);
    if (e.dataTransfer.files.length) upload(e.dataTransfer.files);
  }

  return (
    <div className="library">
      <button
        className={cx("dropzone", dragging && "is-drag")}
        onClick={() => picker.current?.click()}
        onDragOver={(e) => (e.preventDefault(), setDragging(true))}
        onDragLeave={() => setDragging(false)}
        onDrop={onDrop}
        disabled={!workspace}
      >
        <UploadCloud size={26} />
        <b>Drop PDFs here</b>
        <span>or click to browse · indexed for this workspace only</span>
      </button>
      <input
        ref={picker}
        type="file"
        accept="application/pdf,.pdf"
        multiple
        hidden
        onChange={(e) => (e.target.files && upload(e.target.files), (e.target.value = ""))}
      />

      <ul className="files">
        {uploads.map((u) => (
          <li key={u.key} className="file is-uploading">
            <FileText size={18} />
            <div className="file-main">
              <b dir="auto">{u.name}</b>
              <span className="progress">
                <span style={{ width: `${Math.round(u.progress * 100)}%` }} />
              </span>
              <small>{u.progress < 1 ? `Uploading ${Math.round(u.progress * 100)}%` : "Reading & indexing pages…"}</small>
            </div>
          </li>
        ))}
        {files.map((f) => (
          <li key={f.id} className={cx("file", `is-${f.status}`)}>
            {f.status === "failed" ? <AlertCircle size={18} /> : <FileText size={18} />}
            <div className="file-main">
              <b dir="auto">{f.filename}</b>
              <small>
                {f.status === "failed"
                  ? f.error_message || "Could not be processed"
                  : `${f.num_pages} pages · ${f.num_chunks} passages · ${relativeTime(f.uploaded_at)}`}
              </small>
            </div>
            <button className="icon-btn danger" aria-label={`Remove ${f.filename}`} onClick={() => onDeleteFile(f)}>
              <Trash2 size={15} />
            </button>
          </li>
        ))}
      </ul>
      {files.length === 0 && uploads.length === 0 && (
        <p className="empty-note center">No documents yet. Add protocols, guidelines or papers and I'll cite them by page.</p>
      )}
    </div>
  );
}

export function EvidencePanel(p: Props) {
  return (
    <aside className={cx("panel", p.open && "is-open")}>
      <header className="panel-head">
        <div className="tabs" role="tablist">
          {(["evidence", "library"] as PanelTab[]).map((t) => (
            <button key={t} role="tab" aria-selected={p.tab === t} className={cx("tab", p.tab === t && "is-on")} onClick={() => p.setTab(t)}>
              {t === "evidence" ? "Evidence" : "Library"}
              {t === "library" && <span className="count">{p.files.length}</span>}
              {t === "evidence" && p.sources && p.sources.length > 0 && <span className="count">{p.sources.length}</span>}
            </button>
          ))}
        </div>
        <button className="icon-btn panel-close" aria-label="Close panel" onClick={p.onClose}>
          <X size={18} />
        </button>
      </header>
      <div className="panel-body">
        {p.tab === "evidence" ? (
          <Evidence sources={p.sources} />
        ) : (
          <LibraryTab workspace={p.workspace} files={p.files} onFilesChanged={p.onFilesChanged} onDeleteFile={p.onDeleteFile} />
        )}
      </div>
    </aside>
  );
}

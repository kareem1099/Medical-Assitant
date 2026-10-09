import { ReactNode, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, AUTH_EXPIRED } from "./api";
import type { Conversation, DocFile, Message, Source, StageEvent, User, Workspace } from "./types";
import { cx, storage, usePersistent, useTheme } from "./lib";
import { AuthScreen } from "./components/AuthScreen";
import { Chat, ErrorItem, ThreadItem } from "./components/Chat";
import { EvidencePanel, PanelTab } from "./components/EvidencePanel";
import { ConfirmModal, ToastProvider, useToast } from "./components/Overlay";
import { Pulse } from "./components/Pulse";
import { SettingsDialog } from "./components/SettingsDialog";
import { Sidebar } from "./components/Sidebar";

export default function App() {
  const [user, setUser] = useState<User | null | undefined>(undefined);
  useTheme(); // applies the saved theme before anything renders

  useEffect(() => {
    api.me().then(setUser).catch(() => setUser(null));
    const expired = () => setUser(null);
    window.addEventListener(AUTH_EXPIRED, expired);
    return () => window.removeEventListener(AUTH_EXPIRED, expired);
  }, []);

  return (
    <ToastProvider>
      {user === undefined ? (
        <div className="splash">
          <Pulse beats={4} />
        </div>
      ) : user === null ? (
        <AuthScreen onAuthed={setUser} />
      ) : (
        <Shell key={user.id} user={user} onSignedOut={() => setUser(null)} />
      )}
    </ToastProvider>
  );
}

type Confirm = { title: string; body: ReactNode; confirm: string; danger?: boolean; run: () => Promise<void> };

function Shell({ user, onSignedOut }: { user: User; onSignedOut: () => void }) {
  const toast = useToast();
  const [theme, setTheme] = useTheme();
  const [ncbiEmail, setNcbiEmail] = usePersistent("sma.ncbi");

  const [workspaces, setWorkspaces] = useState<Workspace[]>([]);
  const [wsId, setWsId] = useState<string | null>(null);
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [convId, setConvId] = useState<string | null>(null);
  const [items, setItems] = useState<ThreadItem[]>([]);
  const [loadingThread, setLoadingThread] = useState(false);
  const [files, setFiles] = useState<DocFile[]>([]);
  const [pending, setPending] = useState<StageEvent | null>(null);
  const [selected, setSelected] = useState<{ id: string; sources: Source[] } | null>(null);
  const [draft, setDraft] = useState("");

  const [tab, setTab] = useState<PanelTab>("evidence");
  const [panelOpen, setPanelOpen] = useState(false);
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [confirm, setConfirm] = useState<Confirm | null>(null);

  const activeWs = useMemo(() => workspaces.find((w) => w.id === wsId) ?? null, [workspaces, wsId]);
  const activeConv = useMemo(() => conversations.find((c) => c.id === convId) ?? null, [conversations, convId]);
  const busy = pending !== null;
  const latest = useRef({ ws: "", conv: "" }); // ignore responses for a workspace/conversation we already left

  const fail = useCallback((err: any) => toast(err?.message ?? "Something went wrong.", "error"), [toast]);

  // ------------------------------------------------------------ loading
  const loadWorkspaces = useCallback(async () => {
    let list = await api.workspaces();
    if (list.length === 0) list = [await api.createWorkspace("My first workspace")];
    setWorkspaces(list);
    return list;
  }, []);

  const booted = useRef(false); // StrictMode runs effects twice in dev: don't create two default workspaces
  useEffect(() => {
    if (booted.current) return;
    booted.current = true;
    loadWorkspaces()
      .then((list) => {
        const saved = storage.get("sma.ws");
        setWsId(list.some((w) => w.id === saved) ? saved : list[0].id);
      })
      .catch(fail);
  }, [loadWorkspaces, fail]);

  const loadFiles = useCallback(async (id: string) => {
    const list = await api.files(id);
    if (latest.current.ws === id) setFiles(list);
  }, []);

  useEffect(() => {
    if (!wsId) return;
    latest.current.ws = wsId;
    storage.set("sma.ws", wsId);
    setFiles([]);
    setSelected(null);
    (async () => {
      const [convs] = await Promise.all([api.conversations(wsId), loadFiles(wsId)]);
      if (latest.current.ws !== wsId) return;
      const list = convs.length ? convs : [await api.newConversation(wsId)];
      setConversations(list);
      setConvId(list[0].id);
    })().catch(fail);
  }, [wsId, loadFiles, fail]);

  useEffect(() => {
    if (!convId) return;
    latest.current.conv = convId;
    setItems([]);
    setSelected(null);
    setLoadingThread(true);
    api
      .messages(convId)
      .then((msgs) => {
        if (latest.current.conv !== convId) return;
        setItems(msgs);
        const last = [...msgs].reverse().find((m) => m.role === "assistant");
        if (last) setSelected({ id: last.id, sources: last.sources });
      })
      .catch(fail)
      .finally(() => latest.current.conv === convId && setLoadingThread(false));
  }, [convId, fail]);

  // -------------------------------------------------------------- chat
  async function send(text: string) {
    if (busy || !wsId) return;
    let conversation = convId;
    if (!conversation) {
      const created = await api.newConversation(wsId).catch(fail);
      if (!created) return;
      setConversations((cs) => [created, ...cs]);
      setConvId(created.id);
      conversation = created.id;
    }
    const userId = `local-${Date.now()}`;
    setItems((list) => [...list.filter((x) => x.role !== "error"), { id: userId, role: "user", content: text, sources: [] }]);
    setDraft("");
    setPending({ type: "stage", stage: "thinking" });
    try {
      const res = await api.ask(conversation, text, ncbiEmail, (e) => setPending((prev) => ({ ...e, tools: e.tools ?? prev?.tools })));
      const answer: Message = { id: `answer-${Date.now()}`, role: "assistant", content: res.answer, sources: res.sources };
      setItems((list) => [...list, answer]);
      setSelected({ id: answer.id, sources: answer.sources });
      if (res.sources.length) setTab("evidence");
      setConversations((cs) => [res.conversation, ...cs.filter((c) => c.id !== res.conversation.id)]);
    } catch (err: any) {
      const error: ErrorItem = { id: `error-${Date.now()}`, role: "error", content: err.message, retry: text, userId };
      setItems((list) => [...list, error]);
    } finally {
      setPending(null);
    }
  }

  function retry(item: ErrorItem) {
    setItems((list) => list.filter((x) => x.id !== item.id && x.id !== item.userId));
    send(item.retry);
  }

  async function newChat() {
    if (!wsId || busy) return;
    try {
      const c = await api.newConversation(wsId);
      setConversations((cs) => [c, ...cs.filter((x) => x.id !== c.id)]);
      setConvId(c.id);
      setSidebarOpen(false);
    } catch (err) {
      fail(err);
    }
  }

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        newChat();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  // ----------------------------------------------------------- actions
  const ask = (c: Confirm) => setConfirm(c);

  function deleteConversation(c: Conversation) {
    ask({
      title: "Delete conversation?",
      body: <p>“<span dir="auto">{c.title}</span>” and all of its messages will be removed.</p>,
      confirm: "Delete",
      danger: true,
      run: async () => {
        await api.deleteConversation(c.id);
        const rest = conversations.filter((x) => x.id !== c.id);
        if (rest.length) {
          setConversations(rest);
          if (c.id === convId) setConvId(rest[0].id);
        } else if (wsId) {
          const fresh = await api.newConversation(wsId);
          setConversations([fresh]);
          setConvId(fresh.id);
        }
      },
    });
  }

  function clearConversation() {
    if (!convId) return;
    ask({
      title: "Clear this conversation?",
      body: <p>Every message in this conversation is deleted. The conversation itself stays.</p>,
      confirm: "Clear",
      danger: true,
      run: async () => {
        await api.clear(convId);
        setItems([]);
        setSelected(null);
        setConversations((cs) => cs.map((c) => (c.id === convId ? { ...c, preview: "" } : c)));
      },
    });
  }

  function deleteWorkspace(ws: Workspace) {
    ask({
      title: `Delete “${ws.name}”?`,
      body: (
        <p>
          This permanently deletes the workspace, its <b>{ws.file_count} document{ws.file_count === 1 ? "" : "s"}</b> and every
          conversation in it. This cannot be undone.
        </p>
      ),
      confirm: "Delete workspace",
      danger: true,
      run: async () => {
        await api.deleteWorkspace(ws.id);
        toast(`Deleted ${ws.name}.`, "success");
        const list = await loadWorkspaces();
        if (ws.id === wsId || !list.some((w) => w.id === wsId)) setWsId(list[0].id);
      },
    });
  }

  function deleteFile(f: DocFile) {
    if (!wsId) return;
    ask({
      title: "Remove document?",
      body: <p>“<span dir="auto">{f.filename}</span>” will no longer be searched or cited in this workspace.</p>,
      confirm: "Remove",
      danger: true,
      run: async () => {
        await api.deleteFile(wsId, f.id);
        toast(`Removed ${f.filename}.`, "success");
        await Promise.all([loadFiles(wsId), loadWorkspaces()]);
      },
    });
  }

  async function createWorkspace(name: string) {
    try {
      const ws = await api.createWorkspace(name);
      setWorkspaces((list) => [ws, ...list]);
      setWsId(ws.id);
      toast(`Created ${ws.name}.`, "success");
    } catch (err) {
      fail(err);
    }
  }

  async function rename(title: string) {
    if (!convId) return;
    try {
      const updated = await api.rename(convId, title);
      setConversations((cs) => cs.map((c) => (c.id === updated.id ? updated : c)));
    } catch (err) {
      fail(err);
    }
  }

  async function signOut() {
    await api.logout().catch(() => {});
    onSignedOut();
  }

  const openPanel = (t: PanelTab) => (setTab(t), setPanelOpen(true));

  return (
    <div className={cx("shell", (panelOpen || sidebarOpen) && "has-drawer")}>
      <Sidebar
        user={user}
        workspaces={workspaces}
        activeWs={activeWs}
        conversations={conversations}
        activeConvId={convId}
        busy={busy}
        open={sidebarOpen}
        onClose={() => setSidebarOpen(false)}
        onSelectWs={(id) => !busy && (setWsId(id), setSidebarOpen(false))}
        onCreateWs={createWorkspace}
        onDeleteWs={deleteWorkspace}
        onNewChat={newChat}
        onSelectConv={(id) => !busy && (setConvId(id), setSidebarOpen(false))}
        onDeleteConv={deleteConversation}
        onSettings={() => setSettingsOpen(true)}
      />

      <Chat
        user={user}
        workspace={activeWs}
        conversation={activeConv}
        items={items}
        loading={loadingThread}
        pending={pending}
        selectedId={selected?.id ?? null}
        draft={draft}
        setDraft={setDraft}
        onSend={send}
        onRetry={retry}
        onShowSources={(m) => (setSelected({ id: m.id, sources: m.sources }), openPanel("evidence"))}
        onRename={rename}
        onClear={clearConversation}
        onOpenSidebar={() => setSidebarOpen(true)}
        onOpenPanel={() => setPanelOpen((o) => !o)}
        onOpenLibrary={() => openPanel("library")}
      />

      <EvidencePanel
        tab={tab}
        setTab={setTab}
        open={panelOpen}
        onClose={() => setPanelOpen(false)}
        sources={selected?.sources ?? null}
        workspace={activeWs}
        files={files}
        onFilesChanged={() => wsId && Promise.all([loadFiles(wsId), loadWorkspaces()]).catch(fail)}
        onDeleteFile={deleteFile}
      />

      {(panelOpen || sidebarOpen) && <div className="drawer-scrim" onClick={() => (setPanelOpen(false), setSidebarOpen(false))} />}

      {settingsOpen && (
        <SettingsDialog
          theme={theme}
          setTheme={setTheme}
          ncbiEmail={ncbiEmail}
          setNcbiEmail={setNcbiEmail}
          onSignOut={signOut}
          onClose={() => setSettingsOpen(false)}
        />
      )}
      {confirm && (
        <ConfirmModal
          title={confirm.title}
          body={confirm.body}
          confirm={confirm.confirm}
          danger={confirm.danger}
          onClose={() => setConfirm(null)}
          onConfirm={() => confirm.run().catch((err) => (fail(err), Promise.reject(err)))}
        />
      )}
    </div>
  );
}

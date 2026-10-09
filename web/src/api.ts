import type { ChatEvent, Conversation, DocFile, Message, ResultEvent, StageEvent, User, Workspace } from "./types";

export class ApiError extends Error {
  constructor(message: string, public status: number) {
    super(message);
  }
}

/** Fired when the session cookie is missing/expired so the app can show the sign-in screen. */
export const AUTH_EXPIRED = "sma:auth-expired";

async function errorMessage(res: Response): Promise<string> {
  try {
    const body = await res.json();
    if (typeof body.detail === "string") return body.detail;
    if (Array.isArray(body.detail) && body.detail[0]?.msg) {
      const field = body.detail[0].loc?.at(-1);
      return field === "message" ? "That question is too long." : `Invalid ${field ?? "input"}.`;
    }
  } catch {
    /* not JSON */
  }
  return res.status >= 500 ? "The server had a problem. Please try again." : `Request failed (${res.status}).`;
}

async function check(res: Response, path: string): Promise<Response> {
  if (res.ok) return res;
  if (res.status === 401 && path !== "/auth/login" && path !== "/auth/me") {
    window.dispatchEvent(new Event(AUTH_EXPIRED));
  }
  throw new ApiError(await errorMessage(res), res.status);
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`/api${path}`, {
      credentials: "same-origin",
      ...init,
      headers: init.body && !(init.body instanceof FormData) ? { "Content-Type": "application/json" } : undefined,
    });
  } catch {
    throw new ApiError("Can't reach the server. Is it running?", 0);
  }
  await check(res, path);
  return res.json() as Promise<T>;
}

const json = (method: string, body?: unknown): RequestInit => ({
  method,
  body: body === undefined ? undefined : JSON.stringify(body),
});

export const api = {
  me: () => request<{ user: User }>("/auth/me").then((r) => r.user),
  login: (email: string, password: string) =>
    request<{ user: User }>("/auth/login", json("POST", { email, password })).then((r) => r.user),
  register: (display_name: string, email: string, password: string) =>
    request<{ user: User }>("/auth/register", json("POST", { display_name, email, password })).then((r) => r.user),
  logout: () => request<{ ok: boolean }>("/auth/logout", json("POST")),

  workspaces: () => request<Workspace[]>("/workspaces"),
  createWorkspace: (name: string, description = "") =>
    request<Workspace>("/workspaces", json("POST", { name, description })),
  deleteWorkspace: (id: string) => request<{ name: string }>(`/workspaces/${id}`, json("DELETE")),

  files: (wsId: string) => request<DocFile[]>(`/workspaces/${wsId}/files`),
  deleteFile: (wsId: string, fileId: string) =>
    request<{ filename: string }>(`/workspaces/${wsId}/files/${fileId}`, json("DELETE")),

  conversations: (wsId: string) => request<Conversation[]>(`/workspaces/${wsId}/conversations`),
  newConversation: (wsId: string) => request<Conversation>(`/workspaces/${wsId}/conversations`, json("POST")),
  messages: (convId: string) => request<Message[]>(`/conversations/${convId}/messages`),
  rename: (convId: string, title: string) => request<Conversation>(`/conversations/${convId}`, json("PATCH", { title })),
  clear: (convId: string) => request<{ ok: boolean }>(`/conversations/${convId}/clear`, json("POST")),
  deleteConversation: (convId: string) => request<{ ok: boolean }>(`/conversations/${convId}`, json("DELETE")),

  /** Upload with real progress (fetch can't report upload progress, XHR can). */
  uploadFile(wsId: string, file: File, onProgress: (fraction: number) => void) {
    return new Promise<{ filename: string; num_chunks: number; replaced: boolean }>((resolve, reject) => {
      const xhr = new XMLHttpRequest();
      xhr.open("POST", `/api/workspaces/${wsId}/files`);
      xhr.withCredentials = true;
      xhr.upload.onprogress = (e) => e.lengthComputable && onProgress(e.loaded / e.total);
      xhr.onload = () => {
        let body: any = {};
        try {
          body = JSON.parse(xhr.responseText);
        } catch {
          /* ignore */
        }
        if (xhr.status >= 200 && xhr.status < 300) return resolve(body);
        if (xhr.status === 401) window.dispatchEvent(new Event(AUTH_EXPIRED));
        reject(new ApiError(typeof body.detail === "string" ? body.detail : "Upload failed.", xhr.status));
      };
      xhr.onerror = () => reject(new ApiError("Can't reach the server.", 0));
      const form = new FormData();
      form.append("file", file);
      xhr.send(form);
    });
  },

  /** Streams NDJSON events (real graph stages) and resolves with the final answer. */
  async ask(convId: string, message: string, ncbiEmail: string, onStage: (e: StageEvent) => void): Promise<ResultEvent> {
    let res: Response;
    try {
      res = await fetch(`/api/conversations/${convId}/messages`, {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message, ncbi_email: ncbiEmail }),
      });
    } catch {
      throw new ApiError("Can't reach the server. Is it running?", 0);
    }
    await check(res, "/ask");
    const reader = res.body!.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    for (;;) {
      const { value, done } = await reader.read();
      buffer += decoder.decode(value, { stream: !done });
      const lines = buffer.split("\n");
      buffer = lines.pop() ?? "";
      for (const line of lines) {
        if (!line.trim()) continue;
        const event = JSON.parse(line) as ChatEvent;
        if (event.type === "stage") onStage(event);
        else if (event.type === "error") throw new ApiError(event.message, 500);
        else return event;
      }
      if (done) break;
    }
    throw new ApiError("The answer was interrupted. Please try again.", 0);
  },
};

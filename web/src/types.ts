export interface User {
  id: string;
  email: string;
  display_name: string;
}

export interface Workspace {
  id: string;
  name: string;
  description: string;
  file_count: number;
  created_at?: string | null;
}

export interface DocFile {
  id: string;
  filename: string;
  num_pages: number;
  num_chunks: number;
  status: "completed" | "processing" | "failed" | string;
  error_message?: string | null;
  uploaded_at?: string | null;
}

export interface Conversation {
  id: string;
  title: string;
  workspace_id: string | null;
  preview: string;
  updated_at: string | null;
}

export interface LocalSource {
  type: "local";
  label: string;
  filename?: string;
  page?: number | null;
  score?: number | null;
}

export interface PubmedSource {
  type: "pubmed";
  label: string;
  title?: string;
  journal?: string;
  date?: string;
  pmid?: string;
  url?: string;
}

export type Source = LocalSource | PubmedSource;

export interface Message {
  id: string;
  role: "user" | "assistant";
  content: string;
  sources: Source[];
  created_at?: string | null;
}

export type Stage = "thinking" | "searching" | "writing";

export interface StageEvent {
  type: "stage";
  stage: Stage;
  tools?: string[];
}

export interface ResultEvent {
  type: "result";
  answer: string;
  sources: Source[];
  conversation: Conversation;
}

export interface ErrorEvent {
  type: "error";
  message: string;
}

export type ChatEvent = StageEvent | ResultEvent | ErrorEvent;

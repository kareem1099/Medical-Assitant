# Changes in this revision

## Bugs fixed (each one has a regression test)
- **requirements.txt** pinned `langchain<0.2` / `langgraph<0.1`, but the tools use `RunnableConfig` injection which needs langchain-core >= 0.2 -> a fresh install broke RAG/PubMed. Pins updated to the tested versions (`gradio` also needs `huggingface_hub<1.0`).
- **Wrong page numbers in citations**: chunks were located with `full_text.find(chunk)` (first match) and could straddle pages. Pages are now chunked separately.
- **RAG tool cut every chunk to 500 chars** although chunks are up to `CHUNK_SIZE` -> half the evidence never reached the LLM. PubMed abstracts were cut the same way (now 2000).
- **Failed PDF ingestion left orphan chunks/vectors**; now rolled back (Mongo + Qdrant) and marked failed.
- **Re-uploading a file duplicated its chunks**; now it replaces the old copy (only after the new one succeeded).
- **Malformed ids crashed** `get_project` / `get_chunks_by_ids`; now handled.
- **`get_collection_stats` crashed** on current qdrant-client (`vectors_count` removed).
- **MongoDB credentials could reach the log** (`Connecting to MongoDB at <uri>`, masked config) - URIs are masked now.
- **Routing**: words like "say", "content", "according", "it", "that" forced a document search for ordinary research questions; Arabic document references were not recognised. Rules tightened + Arabic terms added.
- **Follow-up questions lost context in the final answer call** (only the current question was sent). Recent turns are now included (last 10), bounded.
- **A failed request left a dangling question** (and an error text) in the stored history; a turn is now saved only after it succeeded.
- **Sources panel** was built by regex-matching any `[...]` in the answer text; it now lists what the tools actually returned (file + page, linked PubMed papers).
- **PubMed cache** grew without limit; now bounded.
- `setup_logging` crashed when the log directory could not be created; falls back to console.
- Importing `tools` loaded torch/sentence-transformers eagerly; now lazy.
- Same-ms ordering ties in Mongo sorts made list order non-deterministic; `_id` used as tie-break.

## UI / UX
- Layout: Workspace -> Conversations -> Documents (upload next to the file list) -> Settings; chat + sources on the right; clear disclaimer.
- Dropdowns react to **user input only** (`.input`), removing reload cascades between workspace and conversation selectors.
- Waiting state ("Searching and writing the answer...") and the input box clears immediately.
- New: delete a document, delete a workspace (with confirmation), "Clear chat" really clears stored history, example questions, conversation titles from the first question, first workspace auto-created at sign-up, empty conversations are reused, Enter submits login/register, per-paragraph RTL for Arabic text.
- Friendly errors (no raw exception text, no stack/credentials in the UI).

## Architecture
- UI logic moved from closures to `ui/handlers.py` (testable); `ui/gradio_app.py` is declarative wiring.
- New `src/services/citations.py` and `src/services/documents.py`.

## Not changed / recommendations
- `.env` (shipped in the zip) contained a real-looking Cohere key: **rotate it** and keep `.env` out of archives.
- Two workspace models coexist (`projects` via `db/mongo_client.py`, and `workspaces` via `MongoMetadataProvider`/`WorkspaceController`); the UI uses `projects`. Worth merging in the next MVC step.
- `PyPDF2` is deprecated (-> `pypdf`); scanned/image-only PDFs need OCR; Arabic PDFs may extract in visual order.
- Sessions live in Gradio state (a page refresh signs the user out); app binds to 0.0.0.0 - bind to 127.0.0.1 unless you intend network access.

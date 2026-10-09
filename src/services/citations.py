"""
Structured source extraction for answers.

The retrieval tools return formatted text. Instead of guessing citations by
regex-matching ``[...]`` in the LLM's free text (which also matched ordinary
bracketed text), the sources are parsed from what the tools actually
returned, so the Sources panel only ever lists documents / papers that were
really retrieved.
"""

import re
from typing import Any, Dict, Iterable, List, Optional

PUBMED_URL = "https://pubmed.ncbi.nlm.nih.gov/{pmid}/"
DEFAULT_EMPTY = "No sources were used for this answer."

_FIELD = r"^{name}:[ \t]*(.*)$"


def _field(block: str, name: str) -> str:
    match = re.search(_FIELD.format(name=name), block, re.MULTILINE)
    return match.group(1).strip() if match else ""


def _blocks(text: str, header: str) -> List[str]:
    parts = re.split(rf"^{header} \d+:[ \t]*$", text, flags=re.MULTILINE)
    return parts[1:]


def _pubmed_sources(text: str) -> List[Dict[str, Any]]:
    sources = []
    for block in _blocks(text, "Paper"):
        pmid = _field(block, "PMID")
        title = _field(block, "Title")
        if not pmid and not title:
            continue
        journal, date = _field(block, "Journal"), _field(block, "Date")
        label = f"{title} — {journal}, {date}" + (f" (PMID {pmid})" if pmid else "")
        sources.append({
            "type": "pubmed", "label": label, "title": title, "journal": journal,
            "date": date, "pmid": pmid, "url": PUBMED_URL.format(pmid=pmid) if pmid else "",
        })
    return sources


def _local_sources(text: str) -> List[Dict[str, Any]]:
    best: Dict[tuple, Dict[str, Any]] = {}
    for block in _blocks(text, "Chunk"):
        filename = _field(block, "Source")
        if not filename:
            continue
        page_text = _field(block, "Page")
        page = int(page_text) if page_text.isdigit() else None
        try:
            score = float(_field(block, "Relevance"))
        except ValueError:
            score = None
        key = (filename, page)
        label = f"{filename}, p. {page}" if page is not None else filename
        entry = {"type": "local", "label": label, "filename": filename, "page": page, "score": score}
        if key not in best or (score or 0) > (best[key]["score"] or 0):
            best[key] = entry
    return list(best.values())


def extract_sources(tool_outputs: Optional[Iterable[Dict[str, Any]]]) -> List[Dict[str, Any]]:
    """Parse the sources out of the raw tool outputs of one workflow run."""
    sources: List[Dict[str, Any]] = []
    for output in tool_outputs or []:
        content = str(output.get("content", ""))
        if output.get("tool") == "search_pubmed":
            sources.extend(_pubmed_sources(content))
        elif output.get("tool") == "medical_rag_search":
            sources.extend(_local_sources(content))
    return sources


def render_sources(citations: Optional[List[str]], types: Optional[List[str]], empty: str = DEFAULT_EMPTY) -> str:
    """Markdown for the Sources panel, grouped by where the evidence came from."""
    citations = list(citations or [])
    types = list(types or [])
    if not citations:
        return f"### 📚 Sources\n_{empty}_"

    groups = {"pubmed": [], "local": []}
    for index, label in enumerate(citations):
        kind = types[index] if index < len(types) else "local"
        groups.setdefault(kind, []).append(label)

    lines = ["### 📚 Sources"]
    if groups["local"]:
        lines.append("\n**📄 Your documents**")
        lines.extend(f"- {label}" for label in groups["local"])
    if groups["pubmed"]:
        lines.append("\n**🔬 PubMed**")
        for label in groups["pubmed"]:
            pmid = re.search(r"PMID (\d+)", label)
            if pmid:
                title = label.split(" (PMID")[0]
                lines.append(f"- [{title}]({PUBMED_URL.format(pmid=pmid.group(1))})")
            else:
                lines.append(f"- {label}")
    return "\n".join(lines)

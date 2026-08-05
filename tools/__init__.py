"""
Tools module for the Smart Medical Assistant.

Contains implementations of:
- PubMed search tool (search_pubmed)
- Local RAG search tool (medical_rag_search), scoped per project
- PDF loader for document processing (extract -> Mongo -> embed -> Qdrant)
- Standalone embedding model wrapper
"""

from tools.pdf_loader import process_pdf_for_project

__all__ = ["process_pdf_for_project"]

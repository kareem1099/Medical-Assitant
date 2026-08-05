"""
PDF processing pipeline for the Smart Medical Assistant.

For each uploaded PDF (scoped to a project):
1. Extract text per page (PyPDF2)
2. Split into overlapping chunks (RecursiveCharacterTextSplitter)
3. Store chunk text + metadata in MongoDB (source of truth)
4. Embed chunks and upsert the vectors into Qdrant (payload references the
   MongoDB chunk id + project id so search results can be resolved back to
   their full text and filtered per project)
"""

import logging
import uuid
from typing import Any, Dict, List
from pathlib import Path

from langchain.text_splitter import RecursiveCharacterTextSplitter
import PyPDF2

from config.settings import settings
from db import mongo_client
from db import qdrant_client
from tools.embeddings import embed_texts


logger = logging.getLogger(__name__)


def extract_text_from_pdf(pdf_path: str) -> List[Dict[str, Any]]:
    """
    Extract text from PDF file with page-level metadata.

    Args:
        pdf_path: Path to the PDF file

    Returns:
        List of dictionaries with 'text' and 'page' keys

    Raises:
        PyPDF2.errors.PdfReadError: If PDF is corrupted or encrypted
        UnicodeDecodeError: If text encoding issues occur
        FileNotFoundError: If PDF file doesn't exist
    """
    pages_data = []

    try:
        with open(pdf_path, 'rb') as file:
            pdf_reader = PyPDF2.PdfReader(file)

            if pdf_reader.is_encrypted:
                raise PyPDF2.errors.PdfReadError("PDF is encrypted and cannot be read")

            num_pages = len(pdf_reader.pages)
            logger.info(f"Extracting text from {num_pages} pages in {pdf_path}")

            for page_num, page in enumerate(pdf_reader.pages, start=1):
                try:
                    text = page.extract_text()
                    if text.strip():
                        pages_data.append({'text': text, 'page': page_num})
                except Exception as e:
                    logger.warning(f"Failed to extract text from page {page_num}: {e}")
                    continue

            logger.info(f"Successfully extracted text from {len(pages_data)} pages")

    except PyPDF2.errors.PdfReadError as e:
        logger.error(f"PDF read error for {pdf_path}: {e}")
        raise
    except UnicodeDecodeError as e:
        logger.error(f"Unicode decode error for {pdf_path}: {e}")
        raise
    except FileNotFoundError:
        logger.error(f"File not found: {pdf_path}")
        raise
    except Exception as e:
        logger.error(f"Unexpected error extracting PDF text: {e}")
        raise

    return pages_data


def chunk_pages(pages_data: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Split extracted page text into overlapping chunks.

    Args:
        pages_data: List of dicts with 'text' and 'page' keys

    Returns:
        List of dicts with 'text' and 'page' keys (one per chunk)
    """
    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=settings.chunk_size,
        chunk_overlap=settings.chunk_overlap,
        separators=["\n\n", "\n", ".", "!", "?", ",", " ", ""],
        length_function=len
    )

    chunks = []
    for page_data in pages_data:
        for chunk_text in text_splitter.split_text(page_data['text']):
            chunks.append({'text': chunk_text, 'page': page_data['page']})

    logger.info(f"Created {len(chunks)} chunks from {len(pages_data)} pages")
    return chunks


def process_pdf_for_project(pdf_file: str, project_id: str) -> Dict[str, Any]:
    """
    Process an uploaded PDF for a given project: extract, chunk, store in
    MongoDB, embed, and upsert into Qdrant.

    Args:
        pdf_file: Path to the uploaded PDF file
        project_id: The project this document belongs to

    Returns:
        {
            "success": bool,
            "message": str,
            "num_chunks": int,
            "filename": str,
            "file_id": Optional[str]
        }

    Raises:
        No exceptions raised; errors captured in the return dict.
    """
    filename = Path(pdf_file).name
    file_id = None

    try:
        logger.info(f"Processing PDF '{filename}' for project {project_id}")

        # Step 1: Extract text
        pages_data = extract_text_from_pdf(pdf_file)
        if not pages_data:
            return {
                "success": False,
                "message": "No text could be extracted from PDF. It may be empty or image-only.",
                "num_chunks": 0,
                "filename": filename,
                "file_id": None,
            }

        # Step 2: Register the file (status=processing)
        file_id = mongo_client.create_file_record(
            project_id=project_id, filename=filename, num_pages=len(pages_data)
        )

        # Step 3: Chunk text
        raw_chunks = chunk_pages(pages_data)
        if not raw_chunks:
            mongo_client.mark_file_failed(file_id, "No chunks created from PDF text.")
            return {
                "success": False,
                "message": "No chunks created from PDF text.",
                "num_chunks": 0,
                "filename": filename,
                "file_id": file_id,
            }

        # Step 4: Store chunk text/metadata in MongoDB first (source of truth)
        point_ids = [str(uuid.uuid4()) for _ in raw_chunks]
        chunk_docs = [
            {
                "project_id": project_id,
                "file_id": file_id,
                "source": filename,
                "page": raw_chunk["page"],
                "chunk_index": idx,
                "text": raw_chunk["text"],
                "qdrant_point_id": point_ids[idx],
            }
            for idx, raw_chunk in enumerate(raw_chunks)
        ]
        chunk_mongo_ids = mongo_client.insert_chunks(chunk_docs)

        # Step 5: Embed chunk text
        embeddings = embed_texts([c["text"] for c in raw_chunks])

        # Step 6: Upsert vectors into Qdrant (payload only references Mongo)
        qdrant_points = [
            {
                "point_id": point_ids[idx],
                "vector": embeddings[idx],
                "project_id": project_id,
                "file_id": file_id,
                "chunk_id": chunk_mongo_ids[idx],
                "source": filename,
                "page": raw_chunks[idx]["page"],
            }
            for idx in range(len(raw_chunks))
        ]
        qdrant_client.upsert_chunk_vectors(qdrant_points)

        # Step 7: Mark file completed
        mongo_client.mark_file_completed(file_id, len(raw_chunks))

        logger.info(
            f"Successfully processed '{filename}': {len(raw_chunks)} chunks "
            f"(project={project_id}, file_id={file_id})"
        )

        return {
            "success": True,
            "message": f"Successfully processed {len(raw_chunks)} chunks from {len(pages_data)} pages",
            "num_chunks": len(raw_chunks),
            "filename": filename,
            "file_id": file_id,
        }

    except PyPDF2.errors.PdfReadError as e:
        error_msg = f"Unable to read PDF. File may be corrupted or encrypted: {str(e)}"
        logger.error(f"PDF read error for {filename}: {e}")
        if file_id:
            mongo_client.mark_file_failed(file_id, error_msg)
        return {"success": False, "message": error_msg, "num_chunks": 0, "filename": filename, "file_id": file_id}

    except UnicodeDecodeError as e:
        error_msg = f"Text encoding error in PDF: {str(e)}"
        logger.error(f"Unicode error for {filename}: {e}")
        if file_id:
            mongo_client.mark_file_failed(file_id, error_msg)
        return {"success": False, "message": error_msg, "num_chunks": 0, "filename": filename, "file_id": file_id}

    except FileNotFoundError:
        error_msg = f"PDF file not found: {pdf_file}"
        logger.error(error_msg)
        return {"success": False, "message": error_msg, "num_chunks": 0, "filename": filename, "file_id": file_id}

    except Exception as e:
        error_msg = f"Failed to process PDF: {str(e)}"
        logger.error(f"Unexpected error processing {filename}: {e}", exc_info=True)
        if file_id:
            mongo_client.mark_file_failed(file_id, error_msg)
        return {"success": False, "message": error_msg, "num_chunks": 0, "filename": filename, "file_id": file_id}

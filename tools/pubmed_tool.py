"""
PubMed search tool for retrieving medical research papers.

Uses the NCBI Entrez API through Biopython to search and retrieve
medical research papers from PubMed database.
"""

import logging
import time
from typing import Dict, Optional
from datetime import datetime, timedelta
from urllib.error import HTTPError, URLError

from Bio import Entrez
from langchain.tools import tool
from langchain_core.runnables import RunnableConfig

from config.settings import settings


logger = logging.getLogger(__name__)


# Simple in-memory cache for PubMed queries
# Structure: {query: {"result": str, "timestamp": datetime}}
_pubmed_cache: Dict[str, Dict] = {}
CACHE_TTL_SECONDS = 3600  # 1 hour
MAX_CACHE_ENTRIES = 200
MAX_ABSTRACT_CHARS = 2000


def _check_cache(query: str) -> Optional[str]:
    """Check if query result is in cache and not expired."""
    if query in _pubmed_cache:
        cached = _pubmed_cache[query]
        age = datetime.now() - cached["timestamp"]
        
        if age < timedelta(seconds=CACHE_TTL_SECONDS):
            logger.debug(f"Cache hit for query: {query[:50]}...")
            return cached["result"]
        else:
            # Cache expired
            logger.debug(f"Cache expired for query: {query[:50]}...")
            del _pubmed_cache[query]
    
    return None


def _update_cache(query: str, result: str) -> None:
    """Store query result in cache with timestamp."""
    if len(_pubmed_cache) >= MAX_CACHE_ENTRIES and query not in _pubmed_cache:
        # Evict the oldest entry so a long-running server cannot grow without bound.
        oldest = min(_pubmed_cache, key=lambda k: _pubmed_cache[k]["timestamp"])
        del _pubmed_cache[oldest]
    _pubmed_cache[query] = {
        "result": result,
        "timestamp": datetime.now()
    }
    logger.debug(f"Cached result for query: {query[:50]}...")


@tool
def search_pubmed(query: str, config: RunnableConfig) -> str:
    """
    Search PubMed for recent medical research papers.
    
    This tool searches the NCBI PubMed database for medical research
    papers relevant to the given query. It returns the top 5 most
    relevant papers with full metadata including title, journal,
    publication date, and abstract.
    
    Args:
        query: Medical research question or keywords. Should be specific
               and focused (e.g., "diabetes treatment guidelines 2023",
               "COVID-19 vaccine efficacy meta-analysis").
    
    Returns:
        Formatted string containing:
        - Paper title
        - Journal name
        - Publication date
        - Abstract
        - PubMed ID (PMID)
        
        Returns error message if search fails.
        
    Example:
        >>> result = search_pubmed("hypertension treatment guidelines")
        >>> print(result)
        === PubMed Search Results ===
        
        Paper 1:
        Title: 2023 Hypertension Guidelines...
        ...
    
    Notes:
        - Results are cached for 1 hour to avoid redundant API calls
        - Returns at most 5 papers sorted by relevance
        - Handles API errors gracefully with descriptive messages
        - Rate limits: 3 req/sec (standard) or 10 req/sec (with API key)
    """
    email = config.get("configurable", {}).get("ncbi_email") or settings.ncbi_email
    if not email or "@" not in email:
        return "Error: A valid NCBI email is required. Enter your email in the application before using PubMed."

    # Input validation
    if not query or not query.strip():
        error_msg = "Empty query provided. Please provide a medical research question."
        logger.warning("Empty PubMed query received")
        return f"Error: {error_msg}"
    
    query = query.strip()
    
    # Limit query length for API
    if len(query) > 500:
        logger.warning(f"Query too long ({len(query)} chars), truncating to 500")
        query = query[:500]
    
    # Check cache first
    cached_result = _check_cache(query)
    if cached_result:
        return cached_result
    
    logger.info(f"Searching PubMed for: {query[:100]}...")
    
    try:
        # Step 1: Search for relevant paper IDs
        search_handle = Entrez.esearch(
            db="pubmed",
            term=query,
            retmax=settings.top_k,
            sort="relevance",
            email=email,
            api_key=settings.ncbi_api_key or None,
        )
        search_results = Entrez.read(search_handle)
        search_handle.close()
        
        pmids = search_results.get("IdList", [])
        
        if not pmids:
            result = f"No PubMed papers found for query: {query}"
            logger.info(result)
            _update_cache(query, result)
            return result
        
        logger.info(f"Found {len(pmids)} relevant papers")
        
        # Step 2: Fetch full paper details
        fetch_handle = Entrez.efetch(
            db="pubmed",
            id=pmids,
            rettype="medline",
            retmode="xml",
            email=email,
            api_key=settings.ncbi_api_key or None,
        )
        papers = Entrez.read(fetch_handle)
        fetch_handle.close()
        
        # Step 3: Parse and format results
        formatted_results = ["=== PubMed Search Results ===\n"]
        
        for idx, paper in enumerate(papers.get("PubmedArticle", []), start=1):
            try:
                article = paper["MedlineCitation"]["Article"]
                
                # Extract metadata
                title = article.get("ArticleTitle", "No title")
                
                # Journal
                journal_info = article.get("Journal", {})
                journal = journal_info.get("Title", "Unknown Journal")
                
                # Publication date
                pub_date = journal_info.get("JournalIssue", {}).get("PubDate", {})
                year = pub_date.get("Year", pub_date.get("MedlineDate", ""))
                month = pub_date.get("Month", "")
                day = pub_date.get("Day", "")
                date_str = f"{year}-{month}-{day}".strip("-")
                if not date_str:
                    date_str = "Date unknown"
                
                # Abstract
                abstract_list = article.get("Abstract", {}).get("AbstractText", [])
                if abstract_list:
                    # Handle structured abstracts
                    if isinstance(abstract_list[0], dict):
                        abstract = " ".join([str(a) for a in abstract_list])
                    else:
                        abstract = " ".join(abstract_list)
                else:
                    abstract = "No abstract available"
                
                # PMID
                pmid = paper["MedlineCitation"]["PMID"]
                
                # Format paper entry
                paper_entry = f"\nPaper {idx}:\n"
                paper_entry += f"Title: {title}\n"
                paper_entry += f"Journal: {journal}\n"
                paper_entry += f"Date: {date_str}\n"
                paper_entry += f"PMID: {pmid}\n"
                paper_entry += f"Abstract: {abstract[:MAX_ABSTRACT_CHARS]}{'...' if len(abstract) > MAX_ABSTRACT_CHARS else ''}\n"
                paper_entry += "-" * 80 + "\n"
                
                formatted_results.append(paper_entry)
                
            except (KeyError, IndexError) as e:
                logger.warning(f"Error parsing paper {idx}: {e}")
                continue
        
        result = "\n".join(formatted_results)
        
        # Cache successful result
        _update_cache(query, result)
        
        logger.info(f"Successfully retrieved {len(papers.get('PubmedArticle', []))} papers")
        
        return result
        
    except HTTPError as e:
        error_msg = f"PubMed API HTTP error (code {e.code}): {e.reason}. The service may be temporarily unavailable. Please try again later."
        logger.error(f"PubMed HTTP error for query '{query[:50]}...': {e}")
        return f"Error: {error_msg}"
        
    except URLError as e:
        error_msg = f"Unable to reach PubMed service: {e.reason}. Please check your internet connection."
        logger.error(f"PubMed URL error for query '{query[:50]}...': {e}")
        return f"Error: {error_msg}"
        
    except RuntimeError as e:
        error_msg = f"PubMed API error: {str(e)}. The query may be malformed or the service is experiencing issues."
        logger.error(f"PubMed runtime error for query '{query[:50]}...': {e}")
        return f"Error: {error_msg}"
        
    except Exception as e:
        error_msg = f"Unexpected error searching PubMed: {str(e)}"
        logger.error(f"Unexpected PubMed error for query '{query[:50]}...': {e}", exc_info=True)
        return f"Error: {error_msg}"


def clear_pubmed_cache() -> None:
    """Clear the PubMed query cache. Useful for testing or manual cache invalidation."""
    global _pubmed_cache
    _pubmed_cache.clear()
    logger.info("PubMed cache cleared")


def get_cache_stats() -> Dict[str, int]:
    """Get statistics about the PubMed cache."""
    return {
        "cached_queries": len(_pubmed_cache),
        "cache_ttl_seconds": CACHE_TTL_SECONDS
    }

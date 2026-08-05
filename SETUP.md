# Smart Medical Assistant - Setup Guide

## Quick Start

### 1. Environment Setup

Create a `.env` file from the template:

```bash
cp .env.example .env
```

Edit `.env` and add your API keys:

```env
GEMINI_API_KEY=your_actual_gemini_api_key
NCBI_EMAIL=your_email@example.com
NCBI_API_KEY=your_ncbi_api_key  # Optional
```

### 2. Install Dependencies

Install all required Python packages:

```bash
pip install -r requirements.txt
```

**Python Version Requirement**: Python 3.9 or higher

### 3. Verify Configuration

Run the configuration test script:

```bash
python test_config.py
```

This will verify:
- ✓ Environment variables are loaded correctly
- ✓ Configuration validation passes
- ✓ Logging is configured (console + file)
- ✓ All required directories exist

## Project Structure

```
smart-medical-assistant/
├── config/                    # Configuration management
│   ├── __init__.py           # Module exports
│   ├── settings.py           # Pydantic settings with validation
│   └── logging_config.py     # Logging configuration
│
├── graph/                     # LangGraph workflow (to be implemented)
│   └── __init__.py
│
├── tools/                     # PubMed and RAG tools (to be implemented)
│   └── __init__.py
│
├── prompts/                   # System prompts (to be implemented)
│   └── __init__.py
│
├── ui/                        # Gradio interface (to be implemented)
│   └── __init__.py
│
├── vectorstore/               # ChromaDB persistent storage
│   └── .gitkeep              # (chroma_db/ created on first upload)
│
├── logs/                      # Application logs
│   └── .gitkeep              # (app.log created on startup)
│
├── requirements.txt           # Python dependencies
├── .env.example              # Environment variable template
├── .gitignore                # Git ignore rules
└── test_config.py            # Configuration test script
```

## Configuration Details

### Required Environment Variables

| Variable | Description | Required |
|----------|-------------|----------|
| `GEMINI_API_KEY` | Google Gemini API key for LLM | Yes |
| `NCBI_EMAIL` | Email for NCBI PubMed API access | Yes |
| `NCBI_API_KEY` | NCBI API key for higher rate limits | No |

### Optional Configuration Overrides

All parameters have sensible defaults but can be overridden:

| Variable | Default | Description |
|----------|---------|-------------|
| `EMBEDDING_MODEL` | sentence-transformers/all-MiniLM-L6-v2 | Embedding model |
| `LLM_MODEL` | gemini-1.5-flash | Gemini model name |
| `LLM_TEMPERATURE` | 0.1 | Temperature for generation (0.0-2.0) |
| `CHUNK_SIZE` | 1000 | Text chunk size for documents |
| `CHUNK_OVERLAP` | 200 | Overlap between chunks |
| `TOP_K` | 5 | Number of results to retrieve (1-20) |
| `SCORE_THRESHOLD` | 0.5 | Minimum relevance score (0.0-1.0) |
| `VECTORSTORE_PATH` | ./vectorstore/chroma_db | ChromaDB storage path |
| `LOG_FILE` | ./logs/app.log | Application log file path |

### Configuration Validation

The configuration system uses **Pydantic BaseSettings** for:

- ✓ Type validation (int, float, str with constraints)
- ✓ Required field checking with descriptive errors
- ✓ Email format validation for NCBI_EMAIL
- ✓ Logical validation (e.g., chunk_overlap < chunk_size)
- ✓ Automatic .env file loading
- ✓ API key masking for secure logging

### Logging Configuration

Logs are written to both:
- **Console**: Real-time output with structured format
- **File**: `./logs/app.log` with persistent storage

**Log Format**:
```
2024-01-15 10:23:45,123 - module_name - INFO - Log message
```

**Log Levels**:
- INFO: Normal operations (startup, tool execution, etc.)
- WARNING: Recoverable issues (missing optional config, etc.)
- ERROR: Failures that prevent operation completion

## Getting API Keys

### Gemini API Key

1. Visit [Google AI Studio](https://makersuite.google.com/app/apikey)
2. Sign in with your Google account
3. Click "Create API Key"
4. Copy the key to your `.env` file

### NCBI Email and API Key

1. **Email** (Required): Use your actual email address
   - NCBI requires an email for API access
   - Used to contact you if there are issues with your queries

2. **API Key** (Optional): For higher rate limits
   - Visit [NCBI Account Settings](https://www.ncbi.nlm.nih.gov/account/settings/)
   - Create an account if you don't have one
   - Generate an API key
   - Copy to your `.env` file

**Rate Limits**:
- Without API key: 3 requests/second
- With API key: 10 requests/second

## Dependencies

All dependencies are pinned with version constraints in `requirements.txt`:

### Core Framework
- `langchain`, `langgraph`: Workflow orchestration
- `langchain-google-genai`: Gemini LLM integration
- `langchain-community`: Additional components

### Vector Store & Embeddings
- `chromadb`: Persistent vector storage
- `sentence-transformers`: Embedding models

### Medical Research
- `biopython`: NCBI PubMed API access

### User Interface
- `gradio`: Web-based chat interface

### Document Processing
- `PyPDF2`: PDF text extraction

### Configuration
- `python-dotenv`: .env file loading
- `pydantic`, `pydantic-settings`: Type-safe config

## Troubleshooting

### Configuration Errors

**Error**: "Configuration error: field required"
- **Solution**: Ensure `GEMINI_API_KEY` and `NCBI_EMAIL` are set in `.env`

**Error**: "NCBI_EMAIL must be a valid email address"
- **Solution**: Use a real email address with @ symbol

**Error**: "CHUNK_OVERLAP must be less than CHUNK_SIZE"
- **Solution**: Ensure overlap is smaller than chunk size in `.env`

### Import Errors

**Error**: "ModuleNotFoundError: No module named 'pydantic_settings'"
- **Solution**: Install dependencies: `pip install -r requirements.txt`

**Error**: "ImportError: cannot import name 'Settings'"
- **Solution**: Ensure Python 3.9+ and all dependencies installed

### Logging Errors

**Error**: "Could not create log file"
- **Solution**: Check directory permissions for `logs/` folder
- Logging will continue to console only

## Next Steps

After completing setup:

1. ✓ Configuration validated
2. ✓ Dependencies installed
3. ✓ API keys configured
4. → Implement graph workflow components (Task 2)
5. → Implement tools (Task 3-5)
6. → Create user interface (Task 6)

---

**Note**: This setup establishes the foundation. The actual workflow, tools, and UI will be implemented in subsequent tasks.

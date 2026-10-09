"""
Smart Medical Assistant - Main Application Entry Point.

This is the main entry point for the Smart Medical Assistant application.
Run this file to start the web app (FastAPI API + the TypeScript front-end in web/).

Usage:
    python app.py

The application will:
1. Load configuration from .env file
2. Initialize logging
3. Initialize vector store for document storage
4. Create LangGraph workflow
5. Serve the API and the built front-end (web/dist)

Requirements:
    - .env file with COHERE_API_KEY and NCBI_EMAIL configured
    - All dependencies installed (pip install -r requirements.txt)
"""

import sys
import logging
from pathlib import Path

from config.settings import settings, validate_runtime_config
from config.logging_config import setup_logging
from db.mongo_client import init_mongo
from db.qdrant_client import init_qdrant
from tools.embeddings import get_embedding_dimension
from graph.workflow import create_workflow

WEB_DIST = Path(__file__).resolve().parent / "web" / "dist"


def main():
    """
    Main application entry point.
    
    Initializes all components and serves the web app.
    """
    print("=" * 60)
    print("Smart Medical Assistant")
    print("=" * 60)

    try:
        validate_runtime_config()
    except RuntimeError as e:
        print(f"✗ Configuration error: {e}")
        print("Please configure the required values in .env")
        sys.exit(1)
    
    # Step 1: Setup logging
    print("\n[1/5] Setting up logging...")
    try:
        setup_logging(log_file=settings.log_file, level=logging.INFO)
        logger = logging.getLogger(__name__)
        logger.info("=" * 60)
        logger.info("Smart Medical Assistant - Starting")
        logger.info("=" * 60)
        print("✓ Logging configured")
    except Exception as e:
        print(f"✗ Failed to setup logging: {e}")
        sys.exit(1)
    
    # Step 2: Log configuration (with masked API keys)
    print("\n[2/5] Loading configuration...")
    try:
        config = settings.get_masked_config()
        logger.info("Configuration loaded:")
        for key, value in config.items():
            logger.info(f"  {key}: {value}")
        print("✓ Configuration loaded")
    except Exception as e:
        logger.error(f"Configuration error: {e}", exc_info=True)
        print(f"✗ Configuration error: {e}")
        print("\nPlease ensure:")
        print("  1. .env file exists (copy from .env.example)")
        print("  2. COHERE_API_KEY is set")
        print("  3. NCBI_EMAIL is set")
        sys.exit(1)
    
    # Step 3: Initialize MongoDB (projects/files/chunks) and Qdrant (vectors)
    print("\n[3/5] Initializing MongoDB and Qdrant...")
    try:
        init_mongo()
        logger.info("MongoDB initialized")
        print("✓ MongoDB ready")

        vector_size = get_embedding_dimension()
        init_qdrant(vector_size=vector_size)
        logger.info("Qdrant initialized")
        print("✓ Qdrant ready")
    except Exception as e:
        logger.error(f"Storage initialization failed: {e}", exc_info=True)
        print(f"✗ Storage initialization failed: {e}")
        print("\nMake sure MongoDB and Qdrant are running and reachable, e.g.:")
        print("  docker run -d -p 27017:27017 --name mongo mongo:7")
        print("  docker run -d -p 6333:6333 --name qdrant qdrant/qdrant")
        sys.exit(1)
    
    # Step 4: Create workflow
    print("\n[4/5] Creating LangGraph workflow...")
    try:
        workflow = create_workflow()
        logger.info("Workflow created successfully")
        print("✓ Workflow ready")
    except Exception as e:
        logger.error(f"Workflow creation failed: {e}", exc_info=True)
        print(f"✗ Workflow creation failed: {e}")
        sys.exit(1)
    
    # Step 5: Create and launch the web server (API + built front-end)
    print("\n[5/5] Starting the web server...")
    try:
        import uvicorn
        from api.server import create_app
        from db.mongo_client import get_db
        from src.stores.metadata.MongoMetadataProvider import MongoMetadataProvider

        if not WEB_DIST.joinpath("index.html").exists():
            print(f"! Front-end build not found in {WEB_DIST} - only the API is served.")
            print("  Build it with:  cd web && npm install && npm run build")
        if not settings.app_secret:
            print("! APP_SECRET is not set - everyone is signed out whenever the server restarts.")
        app = create_app(workflow, MongoMetadataProvider(get_db()), static_dir=WEB_DIST)

        url = f"http://{'localhost' if settings.app_host in ('127.0.0.1', '0.0.0.0') else settings.app_host}:{settings.app_port}"
        print("\n" + "=" * 60)
        print("✓ Smart Medical Assistant is ready!")
        print("=" * 60)
        print(f"\nOpen {url}")
        print("  - Set APP_HOST=0.0.0.0 to expose on the network")
        print("\nPress Ctrl+C to stop the server")
        print("=" * 60 + "\n")
        logger.info("Starting web server on %s:%s", settings.app_host, settings.app_port)
        uvicorn.run(app, host=settings.app_host, port=settings.app_port, log_level="warning")
    except KeyboardInterrupt:
        logger.info("Application stopped by user")
        print("\n\nApplication stopped by user")
    except Exception as e:
        logger.error(f"Web server failed: {e}", exc_info=True)
        print(f"✗ Web server failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()



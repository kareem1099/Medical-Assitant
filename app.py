"""
Smart Medical Assistant - Main Application Entry Point.

This is the main entry point for the Smart Medical Assistant application.
Run this file to start the Gradio web interface.

Usage:
    python app.py

The application will:
1. Load configuration from .env file
2. Initialize logging
3. Initialize vector store for document storage
4. Create LangGraph workflow
5. Launch Gradio interface

Requirements:
    - .env file with GEMINI_API_KEY and NCBI_EMAIL configured
    - All dependencies installed (pip install -r requirements.txt)
"""

import sys
import logging

from config.settings import settings
from config.logging_config import setup_logging
from db.mongo_client import init_mongo
from db.qdrant_client import init_qdrant
from tools.embeddings import get_embedding_dimension
from graph.workflow import create_workflow
from ui.gradio_app import create_gradio_interface


def main():
    """
    Main application entry point.
    
    Initializes all components and launches the Gradio interface.
    """
    print("=" * 60)
    print("Smart Medical Assistant")
    print("=" * 60)
    
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
        print("  2. GEMINI_API_KEY is set")
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
    
    # Step 5: Create and launch Gradio interface
    print("\n[5/5] Launching Gradio interface...")
    try:
        interface = create_gradio_interface(workflow)
        logger.info("Gradio interface created")
        
        print("\n" + "=" * 60)
        print("✓ Smart Medical Assistant is ready!")
        print("=" * 60)
        print("\nAccess the interface at:")
        print("  - Local: http://localhost:7860")
        print("  - Network: http://0.0.0.0:7860")
        print("\nPress Ctrl+C to stop the server")
        print("=" * 60 + "\n")
        
        logger.info("Launching Gradio interface on port 7860")
        
        # Launch interface
        interface.launch(
            server_name="0.0.0.0",
            server_port=7860,
            share=False,  # Set to True to create public link
            show_error=True
        )
        
    except KeyboardInterrupt:
        logger.info("Application stopped by user")
        print("\n\nApplication stopped by user")
    except Exception as e:
        logger.error(f"Gradio launch failed: {e}", exc_info=True)
        print(f"✗ Gradio launch failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()

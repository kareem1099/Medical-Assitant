# MVC foundation

This package is the MVC architecture boundary for the Smart Medical Assistant.

The current stage includes local account authentication, user-scoped MongoDB persistence, workspace/conversation controllers, ChatTurn models, provider factories, and the authenticated Gradio view.

Migration order:

1. Add stronger production session-cookie handling if the application is deployed publicly.
2. Move document/workspace handlers into dedicated controllers and services.
3. Move RAG, PubMed, and citation logic into services.
4. Replace remaining direct provider imports with factories.
5. Run unit, integration, and UI smoke tests.

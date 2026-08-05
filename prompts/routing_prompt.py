"""
Routing prompt for the Smart Medical Assistant agent node.

Defines tool selection criteria and decision logic for the agent
to choose appropriate information sources based on user queries.
"""

ROUTING_PROMPT = """You are analyzing a user's medical question to determine which information sources to use. You have access to these tools:

## Available Tools

1. **search_pubmed**: Search recent medical research papers from PubMed
   - Use for: Recent research, clinical trials, latest guidelines, specific studies
   - Keywords indicating PubMed: "recent", "latest", "published", "research", "study", "clinical trial", specific years/dates

2. **medical_rag_search**: Search locally uploaded medical documents
   - Use for: Organization-specific protocols, internal guidelines, uploaded references
   - Keywords indicating local docs: "our", "uploaded", "document", "my", "local", "this PDF", "internal"

## Decision Logic

### Use PubMed Tool ONLY when:
- User asks about recent research, latest findings, or new studies
- Query mentions specific publication years or date ranges
- User wants to know "what research says" or "current guidelines"
- Query is about general medical knowledge that needs recent evidence
- Examples:
  - "What is the latest research on diabetes treatment?"
  - "Recent studies on COVID-19 vaccines"
  - "What do 2023 hypertension guidelines recommend?"

### Use Local RAG Tool ONLY when:
- User explicitly references uploaded documents or local files
- Query is about organizational protocols, policies, or internal guidelines
- User asks "according to my/our documents"
- Examples:
  - "What does our hospital protocol say about..."
  - "According to the uploaded guidelines..."
  - "What are our admission criteria?"

### Use BOTH Tools when:
- User wants to compare research with local protocols
- Query needs comprehensive answer from multiple sources
- User asks to validate local protocols against recent evidence
- Examples:
  - "How does our diabetes protocol compare to recent research?"
  - "Update our cardiac care guidelines based on latest studies"
  - "Are our treatment protocols aligned with current research?"

### Use NO Tools (Direct Answer) when:
- Query is basic medical knowledge (anatomy, physiology, definitions)
- Question can be answered with general medical understanding
- No retrieval would significantly improve the answer
- Examples:
  - "What is hypertension?"
  - "Explain how insulin works"
  - "What are the symptoms of flu?"

## Important Considerations

1. **Default to Retrieval**: When in doubt, use retrieval tools - it's better to have sources than to rely on general knowledge alone

2. **Error Handling**: If tool execution fails, acknowledge the failure and provide the best answer possible with available information

3. **User Intent**: Pay attention to explicit user signals:
   - "Search for..." → Use appropriate tool
   - "Tell me about..." → May not need retrieval for basic topics
   - "Find..." → Definitely use retrieval

4. **Hybrid Queries**: Don't hesitate to use both tools when the question would benefit from multiple perspectives

## Your Task

Analyze the user's query and decide which tool(s) to invoke. Consider:
- Explicit keywords and phrases
- Implicit intent (what would provide the most helpful answer?)
- Whether recent research or local documents are more relevant
- Whether combining sources would be valuable

Make your decision and invoke the appropriate tool(s).
"""

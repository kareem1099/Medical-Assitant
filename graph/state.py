"""
State management schema for the Smart Medical Assistant workflow.

Defines the TypedDict state schema that flows through the LangGraph StateGraph,
maintaining conversation history, retrieved documents, and workflow outputs.
"""

from typing import TypedDict, List, Dict, Any, Annotated
from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages


class MedicalAssistantState(TypedDict):
    """
    State schema for the Smart Medical Assistant workflow.
    
    This TypedDict defines the structure of data that flows through the LangGraph
    StateGraph workflow. The state is updated by each node (agent, tools, final_response)
    and maintains all information needed to generate the final medical answer.
    
    Attributes:
        messages: Conversation history with automatic message accumulation using add_messages reducer.
                 Includes HumanMessage, AIMessage, and ToolMessage instances.
                 The reducer automatically appends new messages while preserving history.
        
        user_query: The latest user question submitted to the assistant.
                   Updated each time a new query is received.
        
        project_id: The id of the currently active project (workspace).
                   Used to scope local RAG search to that project's uploaded
                   documents. Set by the UI before invoking the workflow.
        
        retrieved_docs: Documents retrieved from the local RAG vector store.
                       Each document includes content, source filename, page number, and relevance score.
                       Updated by the RAG tool during execution.
        
        pubmed_results: Research papers retrieved from PubMed search.
                       Each paper includes title, journal, publication date, abstract, and PMID.
                       Updated by the PubMed tool during execution.
        
        tool_outputs: Raw outputs from all executed tools for debugging and logging purposes.
                     Includes tool name, success status, output text, and execution metadata.
                     Updated by the tool executor node after each tool execution.
        
        final_answer: The generated medical answer with citations and disclaimer.
                     Produced by the final_response node after synthesizing all retrieved information.
                     Includes properly formatted citations distinguishing PubMed vs local sources.
    
    Example:
        >>> state: MedicalAssistantState = {
        ...     "messages": [HumanMessage(content="What is diabetes?")],
        ...     "user_query": "What is diabetes?",
        ...     "retrieved_docs": [],
        ...     "pubmed_results": [],
        ...     "tool_outputs": [],
        ...     "final_answer": ""
        ... }
    
    Notes:
        - The add_messages reducer ensures conversation history accumulates correctly
        - All fields except messages can be empty during intermediate workflow states
        - State is type-checked at runtime when using strict TypedDict mode
        - Metadata in retrieved_docs and pubmed_results enables proper citation formatting
    """
    
    messages: Annotated[List[BaseMessage], add_messages]
    user_query: str
    project_id: str
    retrieved_docs: List[Dict[str, Any]]
    pubmed_results: List[Dict[str, Any]]
    tool_outputs: List[Dict[str, Any]]
    final_answer: str

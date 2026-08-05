"""
LangGraph workflow construction for the Smart Medical Assistant.

Builds the StateGraph with agent node, tool executor node, and final response node,
with conditional routing based on tool selection decisions.
"""

import logging

from langgraph.graph import StateGraph, END
from langgraph.prebuilt import ToolNode, tools_condition

from graph.state import MedicalAssistantState
from graph.nodes import agent_node, final_response_node
from tools.pubmed_tool import search_pubmed
from tools.rag_tool import medical_rag_search


logger = logging.getLogger(__name__)


def create_workflow() -> StateGraph:
    """
    Create and compile the LangGraph workflow.
    
    Builds a StateGraph that orchestrates the agentic medical assistant workflow:
    1. Agent node analyzes query and selects tools
    2. Tool executor node runs selected tools (PubMed, RAG, or both)
    3. Final response node generates answer with citations
    
    The workflow uses conditional routing to decide whether to execute tools
    or proceed directly to answer generation based on the agent's decision.
    
    Returns:
        Compiled StateGraph ready for invocation
        
    Example:
        >>> workflow = create_workflow()
        >>> result = workflow.invoke({
        ...     "messages": [HumanMessage(content="What is diabetes?")],
        ...     "user_query": "What is diabetes?",
        ...     "retrieved_docs": [],
        ...     "pubmed_results": [],
        ...     "tool_outputs": [],
        ...     "final_answer": ""
        ... })
        >>> print(result["final_answer"])
    
    Workflow Structure:
        START → agent → [tools_condition] → tools → agent (loop if more tools needed)
                                          ↓
                                    final_response → END
    
    Notes:
        - Agent node uses Gemini 1.5 Flash to select appropriate tools
        - Tool executor uses LangGraph's ToolNode for automatic tool execution
        - Conditional routing via tools_condition checks for tool calls in agent response
        - Workflow maintains state throughout all transitions
        - Multi-turn capability allows agent to request additional tools after seeing results
    """
    logger.info("Creating LangGraph workflow")
    
    # Initialize tools
    tools = [search_pubmed, medical_rag_search]
    logger.info(f"Registered tools: {[t.name for t in tools]}")
    
    # Create tool executor node using LangGraph's ToolNode
    tool_executor = ToolNode(tools)
    
    # Create StateGraph with typed state
    workflow = StateGraph(MedicalAssistantState)
    
    # Add nodes
    workflow.add_node("agent", agent_node)
    workflow.add_node("tools", tool_executor)
    workflow.add_node("final_response", final_response_node)
    
    logger.info("Added nodes: agent, tools, final_response")
    
    # Set entry point
    workflow.set_entry_point("agent")
    logger.info("Set entry point: agent")
    
    # Add conditional edge from agent
    # tools_condition checks if agent returned tool calls
    # Returns "tools" if tool calls present, "end" otherwise
    workflow.add_conditional_edges(
        "agent",
        tools_condition,
        {
            "tools": "tools",           # If tools selected → execute tools
            "end": "final_response"     # If no tools → generate answer directly
        }
    )
    logger.info("Added conditional edge: agent → [tools_condition] → tools/final_response")
    
    # Add edge from tools back to agent (allows multi-turn tool execution)
    workflow.add_edge("tools", "agent")
    logger.info("Added edge: tools → agent (multi-turn capability)")
    
    # Add edge from final_response to END
    workflow.add_edge("final_response", END)
    logger.info("Added edge: final_response → END")
    
    # Compile workflow
    compiled_workflow = workflow.compile()
    logger.info("Workflow compiled successfully")
    
    return compiled_workflow

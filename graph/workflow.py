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


def route_after_agent(state: MedicalAssistantState) -> str:
    """Map version-specific tools_condition outputs to stable graph nodes."""
    decision = tools_condition(state)
    if decision == "tools":
        return "tools"
    if decision in {"end", "END", "__end__"}:
        return "final_response"
    raise ValueError(f"Unexpected tools_condition decision: {decision!r}")


def create_workflow() -> StateGraph:
   
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
    
    # Add conditional edge from agent. The wrapper normalizes LangGraph's
    # version-dependent direct-answer sentinel (end/END/__end__).
    workflow.add_conditional_edges(
        "agent",
        route_after_agent,
        {
            "tools": "tools",
            "final_response": "final_response",
        }
    )
    logger.info("Added conditional edge: agent → [tools_condition] → tools/final_response")
    
    # After tools finish, go directly to final_response (avoids a redundant
    # agent LLM call that would otherwise precede the synthesis call).
    workflow.add_edge("tools", "final_response")
    logger.info("Added edge: tools → final_response")
    
    # Add edge from final_response to END
    workflow.add_edge("final_response", END)
    logger.info("Added edge: final_response → END")
    
    # Compile workflow
    compiled_workflow = workflow.compile()
    logger.info("Workflow compiled successfully")
    
    return compiled_workflow

"""
LangGraph nodes for the Smart Medical Assistant workflow.

Implements the agent node (query analysis & tool selection) and
final response node (answer generation with citations).
"""

import logging
from typing import Dict, Any

from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage

from graph.state import MedicalAssistantState
from prompts.system_prompt import SYSTEM_PROMPT
from prompts.routing_prompt import ROUTING_PROMPT
from config.settings import settings
from tools.pubmed_tool import search_pubmed
from tools.rag_tool import medical_rag_search


logger = logging.getLogger(__name__)


# Initialize Gemini LLM (reused across node invocations)
llm = ChatGoogleGenerativeAI(
    model=settings.llm_model,
    google_api_key=settings.gemini_api_key,
    temperature=settings.llm_temperature,
    convert_system_message_to_human=True  # Gemini requirement
)

# Bind tools for agent node
llm_with_tools = llm.bind_tools([search_pubmed, medical_rag_search])


def agent_node(state: MedicalAssistantState) -> MedicalAssistantState:
    """
    Agent node: Analyze user query and select appropriate tools.
    
    Uses Gemini 1.5 Flash to analyze the user's medical question and decide
    which tools to invoke (PubMed search, RAG search, both, or neither).
    
    Args:
        state: Current workflow state containing user query and conversation history
        
    Returns:
        Updated state with tool selection decisions in messages
        
    Raises:
        Exception: If LLM call fails (propagated for workflow error handling)
    """
    logger.info("Agent node: Analyzing query and selecting tools")
    
    try:
        # Get the latest user query from messages
        messages = state["messages"]
        
        # Extract user query text for logging
        user_query = state.get("user_query", "")
        logger.info(f"Processing query: {user_query[:100]}...")
        
        # Construct prompt with routing instructions
        prompt_messages = [
            SystemMessage(content=ROUTING_PROMPT),
            *messages
        ]
        
        # Call LLM with tools bound
        response = llm_with_tools.invoke(prompt_messages)
        
        # Log tool selection decisions
        if hasattr(response, "tool_calls") and response.tool_calls:
            tool_names = [tc["name"] for tc in response.tool_calls]
            logger.info(f"Agent selected tools: {tool_names}")
        else:
            logger.info("Agent chose not to use any tools (direct response)")
        
        # Return updated state with agent's response (including tool calls if any)
        return {
            **state,
            "messages": [response]
        }
        
    except Exception as e:
        logger.error(f"Agent node error: {e}", exc_info=True)
        # Return error message to user
        error_response = AIMessage(
            content="I encountered an error while analyzing your question. Please try rephrasing or try again."
        )
        return {
            **state,
            "messages": [error_response]
        }


def final_response_node(state: MedicalAssistantState) -> MedicalAssistantState:
    """
    Final response node: Generate answer with citations from tool outputs.
    
    Synthesizes information from PubMed papers and/or local documents to create
    a coherent medical answer with proper citations, source attribution, and
    medical safety disclaimer.
    
    Args:
        state: Current workflow state with tool outputs (PubMed results, RAG docs)
        
    Returns:
        Updated state with final_answer field populated
        
    Raises:
        Exception: If LLM call fails (propagated for workflow error handling)
    """
    logger.info("Final response node: Generating answer with citations")
    
    try:
        # Extract tool outputs from messages
        messages = state["messages"]
        user_query = state.get("user_query", "")
        
        # Build context from tool outputs
        tool_outputs = []
        pubmed_used = False
        rag_used = False
        
        for msg in messages:
            if hasattr(msg, "name") and hasattr(msg, "content"):
                if msg.name == "search_pubmed":
                    tool_outputs.append(f"=== PubMed Search Results ===\n{msg.content}")
                    pubmed_used = True
                elif msg.name == "medical_rag_search":
                    tool_outputs.append(f"=== Local Document Results ===\n{msg.content}")
                    rag_used = True
        
        # Construct synthesis prompt
        if tool_outputs:
            context = "\n\n".join(tool_outputs)
            synthesis_instructions = f"""Using the retrieved information below, answer the user's question: "{user_query}"

Retrieved Information:
{context}

Instructions:
1. Synthesize a clear, coherent answer from the retrieved information
2. Cite sources appropriately:
   - PubMed papers: [Title, Journal, Date]
   - Local documents: [Filename, Page X]
3. Clearly distinguish between PubMed and local document sources
4. Mention any limitations, uncertainties, or contradictions in the evidence
5. Include relevance scores for local document citations
6. Avoid definitive diagnostic or treatment recommendations
7. End with the medical safety disclaimer

Remember: This is for informational purposes only. Encourage consulting healthcare professionals for medical decisions.
"""
        else:
            # No tool outputs - direct answer mode
            synthesis_instructions = f"""Answer the user's medical question: "{user_query}"

Since no specific research papers or local documents were retrieved, provide a general medical information response based on established medical knowledge.

Important:
1. Keep the answer factual and well-established
2. Note that this is general information, not personalized medical advice
3. Mention uncertainty when appropriate
4. Suggest consulting healthcare professionals for personal medical decisions
5. End with the medical safety disclaimer
"""
        
        # Generate final answer
        prompt_messages = [
            SystemMessage(content=SYSTEM_PROMPT),
            HumanMessage(content=synthesis_instructions)
        ]
        
        response = llm.invoke(prompt_messages)
        final_answer = response.content
        
        # Log completion
        logger.info(
            f"Generated final answer ({len(final_answer)} chars) "
            f"[PubMed: {pubmed_used}, RAG: {rag_used}]"
        )
        
        # Check for medical disclaimer (quality check)
        if "Disclaimer" not in final_answer and "disclaimer" not in final_answer.lower():
            logger.warning("Generated answer missing medical disclaimer - appending")
            final_answer += "\n\n**Disclaimer**: This information is for educational and informational purposes only and does not constitute medical advice. Always consult with qualified healthcare professionals for medical decisions, diagnoses, or treatment plans."
        
        # Return updated state
        return {
            **state,
            "final_answer": final_answer,
            "messages": [AIMessage(content=final_answer)]
        }
        
    except Exception as e:
        logger.error(f"Final response node error: {e}", exc_info=True)
        # Return error message
        error_answer = (
            "I apologize, but I encountered an error while generating your answer. "
            "Please try your question again or rephrase it.\n\n"
            "**Disclaimer**: This information is for educational and informational purposes only."
        )
        return {
            **state,
            "final_answer": error_answer,
            "messages": [AIMessage(content=error_answer)]
        }

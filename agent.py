"""
VIP Data Concierge Agent.
Uses Vertex AI (Gemini) with Function Calling to query isolated databases.
The user's department determines which tools and databases are available.
"""

from langchain_google_vertexai import ChatVertexAI
from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from config import PROJECT_ID, LOCATION, MODEL_NAME
from tools import TOOLS_BY_DEPARTMENT


def create_agent(department: str):
    """
    Create a Gemini agent bound to the tools for the given department.
    HR users get HR tools, Finance users get Finance tools.
    """
    tools = TOOLS_BY_DEPARTMENT.get(department, [])

    if not tools:
        return None, f"No tools available for department: {department}"

    llm = ChatVertexAI(
        model_name=MODEL_NAME,
        project=PROJECT_ID,
        location=LOCATION,
        temperature=0,
        max_output_tokens=1024,
    )

    agent = llm.bind_tools(tools)
    return agent, None


def run_agent(department: str, user_query: str) -> str:
    """
    Run the agent for a given department and query.
    Handles the full Function Calling loop:
    1. Send query to Gemini
    2. Gemini returns tool calls
    3. Execute tools against the correct database
    4. Return results to Gemini for final answer
    """
    agent, error = create_agent(department)
    if error:
        return error

    tools = TOOLS_BY_DEPARTMENT[department]
    tools_map = {t.name: t for t in tools}

    system_prompt = (
        f"You are a VIP Data Concierge for the {department.upper()} department. "
        f"You have access to the {department} database ONLY. "
        f"Always use the available tools to answer questions — never make up data. "
        f"The 'department' parameter in every tool call must be '{department}'. "
        f"Be concise and professional in your responses."
    )

    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=user_query),
    ]

    # First call — Gemini decides which tools to use
    response = agent.invoke(messages)
    messages.append(response)

    # If no tool calls, return the direct response
    if not response.tool_calls:
        return response.content

    # Execute each tool call
    for tool_call in response.tool_calls:
        tool_name = tool_call["name"]
        tool_args = tool_call["args"]

        # Security: force department to match authenticated user
        tool_args["department"] = department

        if tool_name not in tools_map:
            tool_result = f"Error: Unknown tool '{tool_name}'"
        else:
            try:
                tool_result = tools_map[tool_name].invoke(tool_args)
            except Exception as e:
                tool_result = f"Error executing {tool_name}: {e}"

        messages.append(
            ToolMessage(content=str(tool_result), tool_call_id=tool_call["id"])
        )

    # Second call — Gemini formats the final answer
    final_response = agent.invoke(messages)
    return final_response.content

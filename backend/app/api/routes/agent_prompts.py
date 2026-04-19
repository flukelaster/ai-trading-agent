"""
Agent Prompts API — view and customize system prompts for AI trading agents.
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.auth import require_auth

router = APIRouter(prefix="/api/agent-prompts", tags=["agent-prompts"])


class UpdatePromptRequest(BaseModel):
    prompt: str = Field(..., min_length=10, max_length=50000)


@router.get("", dependencies=[Depends(require_auth)])
async def list_agent_prompts():
    """List all agents with their active and default prompts."""
    from mcp_server.agents.prompt_registry import get_all_prompts

    return {"agents": await get_all_prompts()}


@router.put("/{agent_id}", dependencies=[Depends(require_auth)])
async def update_agent_prompt(agent_id: str, req: UpdatePromptRequest):
    """Set a custom prompt for an agent (overrides hardcoded default)."""
    from mcp_server.agents.prompt_registry import AGENT_META, set_custom_prompt

    if agent_id not in AGENT_META:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found")
    await set_custom_prompt(agent_id, req.prompt)
    return {"success": True, "agent_id": agent_id, "is_customized": True}


@router.delete("/{agent_id}", dependencies=[Depends(require_auth)])
async def reset_agent_prompt(agent_id: str):
    """Reset an agent's prompt to hardcoded default."""
    from mcp_server.agents.prompt_registry import AGENT_META, delete_custom_prompt, get_default_prompt

    if agent_id not in AGENT_META:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found")
    await delete_custom_prompt(agent_id)
    return {
        "success": True,
        "agent_id": agent_id,
        "is_customized": False,
        "active_prompt": get_default_prompt(agent_id),
    }

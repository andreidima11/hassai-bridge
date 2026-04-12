"""HASSAI Bridge — Skills REST API."""

import logging
from fastapi import APIRouter, HTTPException, Request, Depends
from pydantic import BaseModel
from typing import Optional

from config import load_config, save_config
from services import skills

log = logging.getLogger("hassai.skills")


def _require_admin_key(request: Request):
    from main import _require_admin_key as _auth
    return _auth(request)


router = APIRouter(
    prefix="/api/skills",
    tags=["skills"],
    dependencies=[Depends(_require_admin_key)],
)


class SkillCreateBody(BaseModel):
    name: str
    source: str


class SkillUpdateBody(BaseModel):
    source: str


@router.get("/")
async def list_skills():
    """List all skills with enabled/disabled status and usage counts."""
    registry = skills.get_skill_registry()
    cfg = load_config()
    disabled = set(cfg.get("skills_disabled", []))
    usage = skills.get_skill_usage()
    return [
        {
            "name": s["name"],
            "description": s["description"],
            "generated": s["generated"],
            "disabled": s["name"] in disabled,
            "usage_count": usage.get(s["name"], 0),
        }
        for s in registry
    ]


@router.get("/template")
async def get_template():
    """Return the skill template source code."""
    return {"source": skills.get_template_source()}


@router.post("/")
async def create_skill(body: SkillCreateBody):
    """Create a new generated skill."""
    ok, msg = skills.create_skill(body.name, body.source)
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    return {"status": "created", "message": msg}


@router.get("/{skill_name}")
async def get_skill(skill_name: str):
    """Get skill source code."""
    src = skills.get_skill_source(skill_name)
    if src is None:
        raise HTTPException(status_code=404, detail=f"Skill '{skill_name}' not found")
    # Find metadata
    registry = skills.get_skill_registry()
    meta = next((s for s in registry if s["name"] == skill_name), {})
    return {
        "name": skill_name,
        "description": meta.get("description", ""),
        "generated": meta.get("generated", False),
        "source": src,
    }


@router.patch("/{skill_name}")
async def update_skill(skill_name: str, body: SkillUpdateBody):
    """Update skill source code."""
    ok, msg = skills.update_skill_source(skill_name, body.source)
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    return {"status": "updated", "message": msg}


@router.delete("/{skill_name}")
async def delete_skill(skill_name: str):
    """Delete a generated skill."""
    ok, msg = skills.delete_skill(skill_name)
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    return {"status": "deleted", "message": msg}


@router.post("/{skill_name}/toggle")
async def toggle_skill(skill_name: str):
    """Toggle skill enabled/disabled."""
    cfg = load_config()
    disabled = list(cfg.get("skills_disabled", []))
    if skill_name in disabled:
        disabled.remove(skill_name)
        is_disabled = False
    else:
        disabled.append(skill_name)
        is_disabled = True
    cfg["skills_disabled"] = disabled
    save_config(cfg)
    return {"name": skill_name, "disabled": is_disabled}


@router.post("/{skill_name}/test")
async def test_skill(skill_name: str, body: dict = {}):
    """Test-run a skill with given input_data."""
    input_data = body.get("input_data", {})
    result = skills.run_skill(skill_name, input_data)
    return result


@router.post("/reload")
async def reload_skills():
    """Force rescan of skills directory."""
    skills.reload_registry()
    registry = skills.get_skill_registry()
    return {"status": "ok", "count": len(registry), "skills": [s["name"] for s in registry]}

"""
HASSAI Bridge — Skill Template

Copy this file and rename it to create a new skill.
Place in data/skills/ (built-in) or data/skills/generated/ (user).

Requirements:
  - Define a class with a `name`, `description`, and `execute()` method.
  - execute() receives a dict of string inputs and returns a dict with:
      success (bool), message (str), and optionally data (dict).
"""

from typing import Any, Dict


class MySkill:
    name = "my_skill"
    description = "Short description of what this skill does"

    @staticmethod
    def execute(input_data: Dict[str, Any]) -> Dict[str, Any]:
        # input_data keys are strings, e.g. {"query": "something"}
        return {
            "success": True,
            "message": "Result goes here",
            # "data": {}  # optional extra structured data
        }

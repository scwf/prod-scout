"""Shared prompt template loading helpers."""

import os


def load_prompt_template(
    config,
    anchor_file: str,
    logger,
    option_name: str = "prompt_template",
    default_path: str = "prompts/organizer_prompt.md",
) -> str:
    """Load a prompt template file relative to project root when needed."""
    try:
        config_path = config.get("llm", option_name, fallback=default_path)
        target_path = config_path

        if not os.path.isabs(config_path):
            project_root = os.path.dirname(os.path.dirname(os.path.abspath(anchor_file)))
            target_path = os.path.join(project_root, config_path)

        if os.path.exists(target_path):
            with open(target_path, "r", encoding="utf-8") as f:
                logger.info(f"Loaded prompt template from {target_path}")
                return f.read()

        logger.error(f"Prompt file not found at {target_path}")
        return ""
    except Exception as e:
        logger.error(f"Failed to load prompt template: {e}")
        return ""

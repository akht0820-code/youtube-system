# scripts/prompts/ — チャンネル別プロンプトパッケージ
#
# 既存の scripts/prompts.py (health) から全公開関数を re-export し、
# from prompts import build_script_prompt 等の既存 import を維持する。
#
# creatures チャンネル固有プロンプトは prompts.creatures に格納。

import importlib as _importlib
import sys as _sys
from pathlib import Path as _Path

# prompts.py (health) は同名パッケージに隠れるため、直接ロードする
_health_path = _Path(__file__).parent.parent / "prompts.py"
_spec = _importlib.util.spec_from_file_location("prompts._health", str(_health_path))
_health = _importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_health)

# health モジュールの全公開関数を re-export
pick_narrative_style = _health.pick_narrative_style
build_comedy_design_prompt = _health.build_comedy_design_prompt
build_title_prompt = _health.build_title_prompt
build_description_prompt = _health.build_description_prompt
build_tags_prompt = _health.build_tags_prompt
build_thumbnail_caption_prompt = _health.build_thumbnail_caption_prompt
build_structure_prompt = _health.build_structure_prompt
build_script_prompt_with_suggestions = _health.build_script_prompt_with_suggestions
build_script_prompt = _health.build_script_prompt

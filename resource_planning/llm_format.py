"""Conservative JSON format compatibility; never invent missing actions."""
import copy
import json


def parse_plan(response):
    value = response.get("content", response) if isinstance(response, dict) else response
    if isinstance(value, str):
        text = value.strip().lstrip("\ufeff")
        if text.startswith("```"):
            text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()
        try:
            value = json.loads(text)
        except json.JSONDecodeError:
            # Permit prose around one complete JSON object, but not truncation.
            start = text.find("{")
            if start < 0:
                raise ValueError("No complete JSON object")
            value, _ = json.JSONDecoder().raw_decode(text[start:])
    if not isinstance(value, dict):
        raise ValueError("Expected a JSON object")
    for key in ("plan", "teaching_plan", "data"):
        if not any(k in value for k in ("lesson", "subquestions", "paragraphs", "sub_questions")) and isinstance(value.get(key), dict):
            value = value[key]
    return value


def normalize_plan(data, story):
    data = copy.deepcopy(data)
    fixes = []
    if 'lesson' in data:
        # Conclusions are generated separately from the completed narration.
        if 'answer_summary' in data:
            data.pop('answer_summary')
            fixes.append('removed obsolete teaching answer_summary')
        from .animation_units import animation_units
        scene_units = {s.story_scene_id: animation_units(s) for s in story.scenes}
        for question in data.get('lesson', []):
            if not isinstance(question, dict):
                continue
            for clause in question.get('clauses', []):
                if not isinstance(clause, dict):
                    continue
                for field in ('scene_ids', 'animation_unit_ids'):
                    if isinstance(clause.get(field), str):
                        clause[field] = [clause[field]]
                        fixes.append(f'{field}: scalar -> list')
                    values = clause.get(field)
                    if isinstance(values, list) and all(isinstance(v, str) for v in values):
                        clean = list(dict.fromkeys(v.strip() for v in values))
                        if clean != values:
                            clause[field] = clean
                            fixes.append(f'{field}: trimmed and deduplicated')
                scenes = clause.get('scene_ids')
                chosen = clause.get('animation_unit_ids')
                if not (isinstance(scenes, list) and all(isinstance(s, str) for s in scenes)
                        and isinstance(chosen, list) and all(isinstance(u, str) for u in chosen)):
                    continue
                allowed = [u['unit_id'] for sid in scenes for u in scene_units.get(sid, [])]
                resolved = []
                for uid in chosen:
                    # Accept U001 only when its owner is unique in this clause.
                    matches = [u for u in allowed if u.rsplit('.', 1)[-1] == uid]
                    resolved.append(matches[0] if uid not in allowed and len(matches) == 1 else uid)
                if resolved != chosen:
                    clause['animation_unit_ids'] = list(dict.fromkeys(resolved))
                    fixes.append('resolved unambiguous scene-local unit IDs')
    if "subquestions" not in data and "sub_questions" in data:
        data["subquestions"] = data.pop("sub_questions")
        fixes.append("sub_questions -> subquestions")
    beats = {b.beat_id: b for s in story.scenes for b in s.beats}
    for question in data.get("subquestions", []):
        if not isinstance(question, dict):
            continue
        if "question" not in question and "title" in question:
            question["question"] = question["title"]
            fixes.append("title -> question")
        for step in question.get("steps", []):
            if not isinstance(step, dict):
                continue
            for target, alias in (("beat_ids", "beat_id"), ("narration", "text"),
                                  ("evidence_relation_ids", "relation_ids")):
                if target not in step and alias in step:
                    step[target] = step[alias]
                    fixes.append(f"{alias} -> {target}")
            for key in ("beat_ids", "evidence_relation_ids"):
                if isinstance(step.get(key), str):
                    step[key] = [step[key].strip()]
                    fixes.append(f"{key}: scalar -> list")
            ids = step.get("beat_ids")
            if "evidence_relation_ids" not in step and isinstance(ids, list) and ids and all(isinstance(x, str) and x in beats for x in ids):
                step["evidence_relation_ids"] = list(dict.fromkeys(r for bid in ids for r in beats[bid].relation_ids))
                fixes.append("derived missing evidence from existing beat IDs")
    return data, fixes

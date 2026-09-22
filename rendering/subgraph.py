"""Stable whole-answer layout and cumulative graph states for rendering."""
from __future__ import annotations

import copy
import math
from collections import defaultdict


def compact_revisits(payload):
    """Replay each complete evidence sequence once; later uses become brief views.

    Run after scene grouping so native layouts and existing narration/audio survive.
    Provenance stays in metadata; evidence validation still uses the original plan.
    """
    result = copy.deepcopy(payload)
    seen = set()
    for scene in result.get('scenes', []):
        if scene.get('metadata', {}).get('narration_aligned'):
            continue
        beats = scene.get('beats', [])
        sources = tuple(scene.get('metadata', {}).get('source_beat_ids', []))
        if not sources:
            sources = tuple(b.get('parameters', {}).get('source_beat_id') for b in beats)
        if not sources or not all(sources):
            continue
        repeated = sources in seen
        seen.add(sources)
        if not repeated or not beats or all(b.get('template_id') == 'evidence_revisit' for b in beats):
            continue
        groups = []
        for beat in beats:
            # Never discard a separate audio clip or change narration ordering.
            if not groups or beat.get('audio') or beat.get('narration') != groups[-1][0].get('narration'):
                groups.append([])
            groups[-1].append(beat)
        compact = []
        for group in groups:
            beat = copy.deepcopy(group[0])
            beat.update(template_id='evidence_revisit', phase_id='highlight', duration=1.2)
            for field in ('node_ids', 'relation_ids'):
                beat[field] = list(dict.fromkeys(x for b in group for x in b.get(field, [])))
            beat['parameters'] = {**beat.get('parameters', {}), 'evidence_reuse': True,
                                  'revisited_source_beat_ids': list(sources)}
            if any(b.get('audio_end') for b in group):
                beat['audio_end'] = True
            compact.append(beat)
        scene['beats'] = compact
        scene.setdefault('metadata', {})['source_beat_ids'] = list(sources)
        scene['metadata']['revisit'] = True
        scene['metadata']['original_beat_count'] = len(beats)
    return result


def add_subquestion_intros(payload):
    """Keep section markers, without synthesizing or replaying spoken titles."""
    result = compact_revisits(payload)
    from student_model.scope import outside_chapter
    excluded = set()
    retained = []
    for scene in result.get('scenes', []):
        meta = scene.get('metadata', {})
        content = [scene.get('title'), scene.get('nodes', []),
                   meta.get('student_narration'), scene.get('narration_summary'),
                   [b.get('narration') for b in scene.get('beats', [])]]
        if meta.get('prerequisite') and outside_chapter(content):
            if meta.get('subquestion_id'):
                excluded.add(meta['subquestion_id'])
            continue
        retained.append(scene)
    has_prerequisites = any(s.get('metadata', {}).get('prerequisite') for s in retained)
    result['scenes'] = [s for s in retained
        if not (s.get('scene_role') == 'subquestion_intro' and
                (s.get('metadata', {}).get('intro_for') in excluded or
                 (s.get('metadata', {}).get('prerequisite_introduction') and not has_prerequisites)))]
    # Concept explanations must stand alone now that section titles are silent.
    for scene in result.get('scenes', []):
        meta = scene.get('metadata', {})
        if not meta.get('prerequisite') or meta.get('student_action') == 'reference':
            continue
        name = meta.get('subquestion') or scene.get('title', '')
        for beat in scene.get('beats', []):
            text = beat.get('narration', '').strip()
            if name and text and not text.startswith(name):
                connector = ' is ' if result.get('metadata', {}).get('language') == 'en' else '是'
                beat['narration'] = name + connector + text
                beat.pop('audio', None)
                beat.pop('audio_end', None)
                scene['narration_summary'] = beat['narration']
    # Migrate already-voiced plans too, before the idempotency fast path.
    for scene in result.get('scenes', []):
        if (scene.get('scene_role') == 'subquestion_intro'
                and not scene.get('metadata', {}).get('prerequisite_introduction')):
            for beat in scene.get('beats', []):
                beat['narration'] = ''
                beat.pop('audio', None)
                beat.pop('audio_end', None)
    if result.get('metadata', {}).get('subquestion_intros') == 3:
        return result
    # Also accept older voiced plans: retain their existing introduction/audio.
    has_prerequisite_intro = any(s.get('metadata', {}).get('prerequisite_introduction')
                                for s in result.get('scenes', []))
    prerequisite_ids = {s.get('metadata', {}).get('subquestion_id')
                        for s in result.get('scenes', []) if s.get('metadata', {}).get('prerequisite')}
    scenes, seen = [], {s.get('metadata', {}).get('intro_for') for s in result.get('scenes', [])
                       if s.get('scene_role') == 'subquestion_intro'}
    for scene in result.get('scenes', []):
        meta = scene.get('metadata', {})
        if (meta.get('prerequisite') or (meta.get('intro_for') is not None and
                meta.get('intro_for') in prerequisite_ids)) and not has_prerequisite_intro:
            scenes.append(dict(scene_id='intro.prerequisites', scene_role='subquestion_intro',
                title='前置概念', nodes=[], relations=[], layout='question_right',
                metadata={'prerequisite_introduction': True, 'presentation_only': True},
                beats=[dict(beat_id='PRE.introduction.narration', beat_type='subquestion_intro',
                    narration='下面介绍几个前置概念。', duration=3.0, node_ids=[], relation_ids=[])]))
            has_prerequisite_intro = True
        key, question = meta.get('subquestion_id'), meta.get('subquestion')
        if key and question and key not in seen and not meta.get('prerequisite_introduction'):
            seen.add(key)
            duration = max(2.0, len(question) / 4.0)
            scenes.append(dict(scene_id=f'intro.{key}', scene_role='subquestion_intro',
                title=question, nodes=[], relations=[], layout='question_right',
                metadata={'subquestion': question, 'intro_for': key},
                beats=[dict(beat_id=f'intro.{key}.narration', beat_type='subquestion_intro',
                            narration='', duration=duration, node_ids=[], relation_ids=[])]))
        scenes.append(scene)
    result['scenes'] = scenes
    result.setdefault('metadata', {})['subquestion_intros'] = 3
    return result


def _native_semantic_scenes(payload):
    """Recover each stage's own coordinates, including older grouped payloads.

    A subquestion may contain several pair layouts with different objects at
    the same coordinate. Unioning their node dictionaries is only safe for the
    persistent overview renderer, never for native semantic scene rendering.
    """
    scenes = []
    for original in payload.get('scenes', []):
        stages = original.get('metadata', {}).get('local_stages', {})
        if not stages or original.get('metadata', {}).get('atomic_semantic_scene'):
            scene = copy.deepcopy(original)
            scene.get('metadata', {}).pop('local_stages', None)
            scenes.append(scene)
            continue
        current, current_key = None, None
        for beat in original.get('beats', []):
            stage = stages.get(beat.get('beat_id'), original)
            key = stage.get('scene_id', original.get('scene_id'))
            if current is None or key != current_key:
                current = copy.deepcopy(stage)
                current['beats'] = []
                current.setdefault('metadata', {}).pop('local_stages', None)
                current['metadata'].pop('local_scene', None)
                scenes.append(current)
                current_key = key
            # Keep current audio paths/timing; snapshots predate TTS enrichment.
            current['beats'].append(copy.deepcopy(beat))
    previous = set()
    for scene in scenes:
        ids = {n['knowledge_node_id'] for n in scene.get('nodes', [])}
        scene['carry_over_node_ids'] = sorted(previous & ids)
        previous = ids
    payload['scenes'] = scenes
    payload.setdefault('metadata', {})['shot_unit'] = 'semantic_scene'
    payload['metadata']['presentation'] = 'semantic_scenes'
    return payload


def group_subquestions(payload):
    result = copy.deepcopy(payload)
    if result.get('metadata', {}).get('presentation') == 'persistent_subgraph':
        return result
    if result.get('metadata', {}).get('shot_unit') == 'semantic_scene':
        return result
    if (result.get('metadata', {}).get('presentation') == 'semantic_scenes'
            or any(s.get('metadata', {}).get('atomic_semantic_scene') for s in result.get('scenes', []))):
        return _native_semantic_scenes(result)
    if result.get("metadata", {}).get("shot_unit") == "subquestion":
        return result
    grouped = []
    for original in result.get("scenes", []):
        scene = copy.deepcopy(original.get("metadata", {}).get("local_scene") or original)
        scene["beats"] = list(copy.deepcopy(original.get("beats", [])))
        # dataclasses.asdict preserves tuples; JSON input uses lists instead.
        for field in ("nodes", "relations"):
            scene[field] = list(scene.get(field, ()))
        key = scene.get("metadata", {}).get("subquestion_id")
        stages = {b["beat_id"]: copy.deepcopy(scene) for b in scene.get("beats", []) if "beat_id" in b}
        if (key and grouped and grouped[-1].get("metadata", {}).get("subquestion_id") == key
                and not scene.get('metadata', {}).get('atomic_semantic_scene')
                and not grouped[-1].get('metadata', {}).get('atomic_semantic_scene')):
            target = grouped[-1]
            target["beats"].extend(scene["beats"])
            for field, identity in (("nodes", "knowledge_node_id"), ("relations", "relation_id")):
                target[field] = list({x[identity]: x for x in target[field] + scene[field]}.values())
            target["metadata"]["local_stages"].update(stages)
        else:
            scene.setdefault("metadata", {})["local_stages"] = stages
            grouped.append(scene)
    result["scenes"] = grouped
    result.setdefault("metadata", {}).pop("presentation", None)
    result["metadata"]["shot_unit"] = "subquestion"
    return result


def prepare_subgraph(payload: dict, *, graph_panel: str | None = None) -> dict:
    result = copy.deepcopy(payload)
    mode = graph_panel if graph_panel is not None else result.get('metadata', {}).get('graph_panel', 'auto')
    if mode not in ('auto', 'on', 'off'):
        raise ValueError('graph_panel must be auto, on, or off')
    if graph_panel is not None:
        result.setdefault('metadata', {})['graph_panel'] = mode
    # Restore original drawing coordinates when disabling an existing overview.
    if mode == 'off':
        for i, scene in enumerate(result.get('scenes', [])):
            local = scene.get('metadata', {}).get('local_scene')
            if local:
                restored = copy.deepcopy(local)
                restored['beats'] = copy.deepcopy(scene.get('beats', []))
                result['scenes'][i] = restored
        return _native_semantic_scenes(result)
    if result.get("metadata", {}).get("presentation") == "persistent_subgraph":
        return result
    if mode == 'auto' and any(s.get('metadata', {}).get('atomic_semantic_scene') for s in result.get('scenes', [])):
        # A semantic scene owns its layout. Keep native fallback scenes alongside
        # it rather than replacing every archetype with a circular graph node.
        result.setdefault('metadata', {})['presentation'] = 'semantic_scenes'
        return result
    local_scenes = copy.deepcopy(result.get("scenes", []))
    nodes, edges = {}, {}
    for scene in result.get("scenes", []):
        for node in scene.get("nodes", []):
            nodes.setdefault(node["knowledge_node_id"], node)
        for edge in scene.get("relations", []):
            edges.setdefault(edge["relation_id"], edge)
    count = len(nodes)
    # Reserve the center for connections and the top/bottom bands for narration.
    for i, node in enumerate(nodes.values()):
        angle = math.pi / 2 - 2 * math.pi * i / max(1, count)
        node.update(x=4.5 * math.cos(angle) if count > 1 else 0,
                    y=2.05 * math.sin(angle) if count > 1 else 0,
                    width=1.8, height=0.62, scale=min(1.0, 8 / max(1, count)),
                    archetype="graph_node")
        node["metadata"] = {"graph_node": True}
    pairs = defaultdict(list)
    for edge in edges.values():
        pair = tuple(sorted((edge["stored_source_node_id"], edge["stored_target_node_id"])))
        pairs[pair].append(edge)
    for pair, relations in pairs.items():
        for i, edge in enumerate(relations):
            edge["metadata"] = {**edge.get("metadata", {}),
                                "lane": i - (len(relations) - 1) / 2,
                                "canonical_forward": edge["stored_source_node_id"] == pair[0]}
    visible_nodes, visible_edges = {}, {}
    for scene, local in zip(result.get("scenes", []), local_scenes):
        if scene.get('scene_role') in ('summary', 'subquestion_intro'):
            continue
        active_nodes = [n["knowledge_node_id"] for n in scene.get("nodes", [])]
        active_edges = [r["relation_id"] for r in scene.get("relations", [])]
        for nid in active_nodes:
            visible_nodes[nid] = nodes[nid]
        for rid in active_edges:
            visible_edges[rid] = edges[rid]
        scene["nodes"] = list(visible_nodes.values())
        scene["relations"] = list(visible_edges.values())
        scene["layout"] = "persistent_subgraph"
        scene["metadata"] = {**scene.get("metadata", {}), "active_node_ids": active_nodes,
                             "active_relation_ids": active_edges}
        if local.get("beats") and local.get("scene_role") != "summary":
            scene["metadata"]["local_scene"] = local
    result.setdefault("metadata", {})["presentation"] = "persistent_subgraph"
    return result

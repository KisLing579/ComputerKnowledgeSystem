from __future__ import annotations

import argparse
import json
from dataclasses import asdict, replace
from pathlib import Path
from datetime import datetime, timezone

from explanation.planner import ExplanationPlanner
from explanation.path_fusion import PathFusionPlanner
from kg.config import load_settings
from kg.neo4j_client import Neo4jClient
from kg.query import KGQueryService
from representation.animation_grammar import AnimationGrammar
from representation.registry import RepresentationRegistry
from rendering.layout.engine import LayoutEngine
from rendering.manim.script_generator import ManimScriptGenerator

from .binder import RepresentationBinder
from .story_planner import VisualStoryPlanner


def _write_json(obj, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(obj), ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Question -> candidate paths -> fused answer graph -> RepresentationPlan -> "
            "semantic StoryPlan -> adaptive RenderPlan -> Manim"
        )
    )
    parser.add_argument("question")
    parser.add_argument("--config", default="config.toml")
    parser.add_argument("--limit", type=int, default=10, help="Maximum candidate paths to retain and fuse")
    parser.add_argument("--max-hops", type=int)
    parser.add_argument("--out-dir", default="out_v2")
    parser.add_argument("--no-manim-script", action="store_true")
    parser.add_argument("--tts", action="store_true", help="Synthesize Azure subtitle narration")
    parser.add_argument('--language', choices=['zh', 'en'], default='en')
    parser.add_argument('--graph-panel', choices=['auto', 'on', 'off'], default='auto',
                        help='Knowledge graph panel: automatic, always shown, or hidden')
    parser.add_argument("--voice", default=None)
    parser.add_argument("--teaching", choices=["rules", "llm"], default="llm")
    from .teaching_planner import DEFAULT_MAX_TEACHING_SCENES
    parser.add_argument('--max-teaching-scenes', type=int, default=DEFAULT_MAX_TEACHING_SCENES,
                        help='Maximum distinct core evidence scenes in an LLM lesson (default: 32)')
    parser.add_argument('--coverage-policy', choices=['strict', 'partial'], default='strict',
                        help='Require complete coverage or allow an explicitly partial answer')
    parser.add_argument('--coverage-min-ratio', type=float, default=0.5,
                        help='Minimum supported requirement fraction for partial mode, in (0, 1]')
    parser.add_argument("--reasoning", choices=["rules", "llm"], default="llm",
                        help="Optional LLM subquestion decomposition before bounded KG queries")
    parser.add_argument('--student-id', default='anonymous')
    parser.add_argument('--student-states', help='JSON student-node state snapshots')
    parser.add_argument('--no-prerequisites', action='store_true')
    parser.add_argument('--prerequisite-depth', type=int, default=3)
    parser.add_argument('--prerequisite-max-nodes', type=int, default=20)
    parser.add_argument('--include-recommended-prerequisites', action='store_true')
    parser.add_argument('--state-as-of', help='Timezone-aware planning time; defaults to now')
    parser.add_argument('--planning-rounds', type=int, default=3,
                        help='Evidence repair attempts including first check (1-5)')
    args = parser.parse_args()
    if args.max_teaching_scenes < 1:
        parser.error('--max-teaching-scenes must be a positive integer')
    args.voice = args.voice or ('en-US-JennyNeural' if args.language == 'en' else 'zh-CN-YunxiNeural')
    if not 1 <= args.planning_rounds <= 5:
        parser.error('--planning-rounds must be between 1 and 5')
    if not 0 < args.coverage_min_ratio <= 1:
        parser.error('--coverage-min-ratio must be in (0, 1]')

    settings = load_settings(args.config)
    from student_model.pipeline import load_states, load_dependencies, adapt_plan
    from student_model.prerequisites import ExpansionPolicy
    from student_model.state import timestamp
    try:
        states = load_states(args.student_states, args.student_id)
        expansion_policy = ExpansionPolicy(max_depth=args.prerequisite_depth,
            max_nodes=args.prerequisite_max_nodes,
            include_recommended=args.include_recommended_prerequisites)
        as_of = timestamp(args.state_as_of) if args.state_as_of else datetime.now(timezone.utc)
    except (ValueError, TypeError, OSError) as exc:
        parser.error(str(exc))
    out_dir = Path(args.out_dir).expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    # Answer sufficiency is checked independently of decomposition/teaching mode.
    from .text_engine import DeepseekModel
    model = DeepseekModel()
    subquestions, reasoning_report = [], {"mode": "rules"}
    if args.reasoning == "llm":
        from explanation.llm_questions import decompose
        subquestions, reasoning_report = decompose(args.question, model)
    source_questions = [{'subquestion_id': f'RQ{i:03}', 'question': q}
                        for i, q in enumerate(subquestions, 1)]
    reasoning_report['source_subquestions'] = source_questions

    registry = RepresentationRegistry(settings.data.workbook)
    grammar = AnimationGrammar()
    binder = RepresentationBinder(registry, grammar)
    story_planner = VisualStoryPlanner(max_nodes_per_scene=settings.resource_planning.max_nodes_per_scene)
    layout = LayoutEngine(
        safe_width=settings.rendering.safe_width,
        safe_height=settings.rendering.safe_height,
    )

    with Neo4jClient(settings.neo4j) as client:
        query = KGQueryService(client, settings)
        matches, candidates = query.generate_candidate_paths(
            args.question, limit=args.limit, max_hops=args.max_hops,
        )
        retrievals = [{'question': args.question, 'matches': matches, 'paths': candidates}]
        if subquestions:
            from kg.query import path_key
            unique = {path_key(p): p for p in candidates}
            matched = {m.id: m for m in matches}
            evidence = []
            for subquestion in subquestions:
                linked, paths = query.generate_candidate_paths(subquestion,
                    limit=args.limit, max_hops=args.max_hops)
                retrievals.append({'question': subquestion, 'matches': linked, 'paths': paths})
                for match in linked:
                    matched.setdefault(match.id, match)
                for path in paths:
                    unique.setdefault(path_key(path), path)
                evidence.append({"question": subquestion,
                                 "candidate_paths": [asdict(p) for p in paths]})
            matches, candidates = list(matched.values()), list(unique.values())
            reasoning_report["evidence"] = evidence
        (out_dir / "reasoning_plan.json").write_text(
            json.dumps(reasoning_report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"Reasoning mode     : {reasoning_report['mode']}")
        from explanation.planning_retry import repair_evidence
        matches, candidates, repairs, planning_report = repair_evidence(
            args.question, source_questions, matches, candidates, query, model,
            rounds=args.planning_rounds, limit=args.limit, max_hops=args.max_hops,
            policy=args.coverage_policy, min_ratio=args.coverage_min_ratio)
        retrievals.extend(repairs)
        source_questions = planning_report['final_subquestions']
        reasoning_report['final_subquestions'] = source_questions
        reasoning_report['revisions'] = planning_report['revisions']
        (out_dir / 'reasoning_plan.json').write_text(
            json.dumps(reasoning_report, ensure_ascii=False, indent=2), encoding='utf-8')
        # Prerequisite planning follows the final explanation questions only.
        final_texts = {q['question'] for q in source_questions}
        retrievals = [r for r in retrievals if r['question'] == args.question or r['question'] in final_texts]
        decision = planning_report['decision']
        (out_dir / 'planning_attempts.json').write_text(
            json.dumps(planning_report, ensure_ascii=False, indent=2), encoding='utf-8')
        (out_dir / 'answer_coverage.json').write_text(json.dumps({
            'question': args.question, 'status': planning_report['coverage']['status'],
            'decision': decision,
            'attempts': [a['checks'][0]['report'] for a in planning_report['attempts']]},
            ensure_ascii=False, indent=2), encoding='utf-8')
        if not decision['accepted']:
            raise SystemExit('Answer evidence insufficient or review unavailable; generation stopped. '
                             f'See {out_dir / "answer_coverage.json"}. Existing output files may be from an earlier run.')
        fused = PathFusionPlanner(max_nodes_per_scene=settings.resource_planning.max_nodes_per_scene).fuse(args.question, matches, candidates)
        selected_plan = fused.plan
        if not candidates:
            selected_plan = ExplanationPlanner(query, settings).explain(args.question).selected_plan
        prerequisite_report = {'status': 'disabled'}
        if not args.no_prerequisites and selected_plan is not None:
            dependencies, catalog, dependency_status = load_dependencies(settings.data)
            selected_plan, prerequisite_report = adapt_plan(
                selected_plan, retrievals, dependencies, catalog, states, args.student_id,
                as_of=as_of, policy=expansion_policy)
            prerequisite_report['dependency_status'] = dependency_status
            prerequisite_report['source'] = f'{settings.data.workbook}:{settings.data.dependencies_sheet}'
            if dependency_status == 'missing_sheet':
                prerequisite_report['status'] = 'unavailable'
        (out_dir / 'prerequisite_plan.json').write_text(
            json.dumps(prerequisite_report, ensure_ascii=False, indent=2), encoding='utf-8')

    if selected_plan is None:
        raise SystemExit("Explanation planner returned no selected plan")

    (out_dir / "candidate_paths.json").write_text(
        json.dumps([asdict(p) for p in fused.candidate_paths], ensure_ascii=False, indent=2), encoding="utf-8",
    )
    (out_dir / "answer_graph.json").write_text(
        json.dumps(fused.answer_graph, ensure_ascii=False, indent=2), encoding="utf-8",
    )
    _write_json(selected_plan, out_dir / "explanation_plan.json")
    representation_plan = binder.bind(selected_plan)
    story_plan = story_planner.plan(representation_plan)
    from .scene_debug import scene_planning_report
    (out_dir / 'scene_planning_debug.json').write_text(json.dumps(
        scene_planning_report(selected_plan, story_plan, fused.answer_graph),
        ensure_ascii=False, indent=2), encoding='utf-8')
    story_plan = replace(story_plan, metadata={**story_plan.metadata,
                                              'source_subquestions': source_questions})
    if decision['partial_answer']:
        story_plan = replace(story_plan, metadata={**story_plan.metadata,
            'answer_coverage': decision})
        print('Partial answer; missing evidence: ' + '、'.join(decision['missing_requirements']))
    from .teaching_planner import plan_teaching
    revision_source = story_plan
    story_plan, teaching_report = plan_teaching(story_plan, model if args.teaching == "llm" else None,
                                               max_scenes=args.max_teaching_scenes)
    teaching_attempts = [teaching_report]
    for repair_round in range(1, args.planning_rounds):
        if teaching_report['mode'] != 'blocked' or not teaching_report.get('semantic_reviews'):
            break
        feedback = [issue for review in teaching_report['semantic_reviews']
                    for check in review.get('checks', []) for issue in check.get('issues', [])]
        # Formatting/provider failures belong to the teaching planner's own
        # retry budget. Only explicit semantic findings trigger KG repair.
        if not feedback:
            break
        with Neo4jClient(settings.neo4j) as client:
            query = KGQueryService(client, settings)
            from kg.query import path_key
            unique = {path_key(p): p for p in candidates}
            matched = {m.id: m for m in matches}
            for task in source_questions or [{'question': args.question}]:
                repair_question = task['question'] + '；需核实：' + '；'.join(feedback)
                linked, paths = query.generate_candidate_paths(repair_question,
                    limit=args.limit * (repair_round + 1), max_hops=args.max_hops)
                retrievals.append({'question': repair_question, 'matches': linked, 'paths': paths})
                for m in linked:
                    matched.setdefault(m.id, m)
                for p in paths:
                    unique.setdefault(path_key(p), p)
            previous = {key: {**report, 'status': 'insufficient'}
                        for key, report in planning_report['reports'].items()}
            matches, candidates, repairs, repaired = repair_evidence(
                args.question, source_questions, list(matched.values()), list(unique.values()), query, model,
                rounds=args.planning_rounds - repair_round, limit=args.limit, max_hops=args.max_hops,
                policy=args.coverage_policy, min_ratio=args.coverage_min_ratio, previous=previous)
            retrievals.extend(repairs)
            source_questions = repaired['final_subquestions']
            reasoning_report['final_subquestions'] = source_questions
            reasoning_report.setdefault('teaching_revisions', []).extend(repaired['revisions'])
            (out_dir / 'reasoning_plan.json').write_text(
                json.dumps(reasoning_report, ensure_ascii=False, indent=2), encoding='utf-8')
            planning_report.setdefault('teaching_repairs', []).append({
                'round': repair_round, 'feedback': feedback, 'result': repaired})
            planning_report['reports'] = repaired['reports']
            planning_report['coverage'] = repaired['coverage']
            planning_report['decision'] = repaired['decision']
            decision = repaired['decision']
            (out_dir / 'planning_attempts.json').write_text(
                json.dumps(planning_report, ensure_ascii=False, indent=2), encoding='utf-8')
            (out_dir / 'answer_coverage.json').write_text(json.dumps({
                'question': args.question, 'status': repaired['coverage']['status'],
                'decision': decision, 'attempts': [repaired['reports']['ROOT']]},
                ensure_ascii=False, indent=2), encoding='utf-8')
            if not decision['accepted']:
                teaching_report = {'mode': 'blocked', 'reason': 'evidence_repair_exhausted'}
                teaching_attempts.append(teaching_report)
                break
            fused = PathFusionPlanner(max_nodes_per_scene=settings.resource_planning.max_nodes_per_scene).fuse(args.question, matches, candidates)
            selected_plan = fused.plan
            if not args.no_prerequisites:
                selected_plan, prerequisite_report = adapt_plan(selected_plan, retrievals,
                    dependencies, catalog, states, args.student_id, as_of=as_of, policy=expansion_policy)
                (out_dir / 'prerequisite_plan.json').write_text(
                    json.dumps(prerequisite_report, ensure_ascii=False, indent=2), encoding='utf-8')
        _write_json(selected_plan, out_dir / 'explanation_plan.json')
        (out_dir / 'candidate_paths.json').write_text(json.dumps(
            [asdict(p) for p in fused.candidate_paths], ensure_ascii=False, indent=2), encoding='utf-8')
        (out_dir / 'answer_graph.json').write_text(json.dumps(
            fused.answer_graph, ensure_ascii=False, indent=2), encoding='utf-8')
        representation_plan = binder.bind(selected_plan)
        story_plan = story_planner.plan(representation_plan)
        (out_dir / 'scene_planning_debug.json').write_text(json.dumps(
            scene_planning_report(selected_plan, story_plan, fused.answer_graph),
            ensure_ascii=False, indent=2), encoding='utf-8')
        story_plan = replace(story_plan, metadata={**story_plan.metadata,
            'source_subquestions': source_questions, 'answer_coverage': decision,
            'repair_feedback': feedback})
        revision_source = story_plan
        story_plan, teaching_report = plan_teaching(story_plan, model, max_scenes=args.max_teaching_scenes)
        teaching_attempts.append(teaching_report)
    teaching_report = {**teaching_report, 'planning_attempts': teaching_attempts}
    (out_dir / "teaching_plan.json").write_text(
        json.dumps(teaching_report, ensure_ascii=False, indent=2), encoding="utf-8")
    if teaching_report['mode'] == 'blocked':
        for error in teaching_report.get('validation_errors', []):
            print(f'Teaching validation: {error}')
        raise SystemExit(f'Teaching validation failed; generation stopped. See {out_dir / "teaching_plan.json"}. '
                         'Existing render files may be from an earlier run.')
    print(f"Teaching mode      : {teaching_report['mode']}")
    if teaching_report["mode"] == "rules_fallback":
        print(f"LLM unavailable or invalid output ({teaching_report['reason']}); using original rule-based story.")
    if args.teaching == 'llm' and teaching_report.get('plan', {}).get('lesson'):
        from .narration_revision import revise_narration
        def retrieve_revision_evidence(requests):
            from kg.query import path_key
            unique = {path_key(p): p for p in candidates}
            matched = {m.id: m for m in matches}
            retrieval_log = []
            with Neo4jClient(settings.neo4j) as client:
                query = KGQueryService(client, settings)
                questions = {q['subquestion_id']: q['question'] for q in source_questions}
                for request in requests:
                    text = questions[request['subquestion_id']] + '；需要证据：' + request['missing_claim']
                    linked, paths = query.generate_candidate_paths(text, limit=args.limit, max_hops=args.max_hops)
                    before = len(unique)
                    for node in linked:
                        matched.setdefault(node.id, node)
                    for path in paths:
                        unique.setdefault(path_key(path), path)
                    retrieval_log.append({**request, 'new_paths': len(unique) - before})
            supplemented = PathFusionPlanner(max_nodes_per_scene=settings.resource_planning.max_nodes_per_scene).fuse(
                args.question, list(matched.values()), list(unique.values()))
            fresh = story_planner.plan(binder.bind(supplemented.plan))
            def prerequisite_segments(segment):
                if segment.metadata.get('prerequisite'):
                    return [segment]
                return [s for child in segment.children for s in prerequisite_segments(child)]
            old_prefix = prerequisite_segments(revision_source.representation_plan.root_segment)
            if old_prefix:
                root = fresh.representation_plan.root_segment
                fresh = replace(fresh, representation_plan=replace(fresh.representation_plan,
                    root_segment=replace(root, children=(*root.children, *old_prefix))))
            prefix = tuple(s for s in revision_source.scenes if s.metadata.get('prerequisite'))
            fresh = replace(fresh, scenes=prefix + fresh.scenes, metadata={**fresh.metadata,
                'source_subquestions': source_questions, 'answer_coverage': decision})
            _write_json(fresh, out_dir / 'revision_evidence_story.json')
            return fresh, retrieval_log
        print('Whole-narration review: at most one revision and one targeted retrieval round.')
        story_plan, teaching_report = revise_narration(revision_source, story_plan, teaching_report,
            model, out_dir, retrieve_revision_evidence, max_scenes=args.max_teaching_scenes)
        representation_plan = story_plan.representation_plan
        (out_dir / 'teaching_plan.json').write_text(json.dumps(teaching_report, ensure_ascii=False, indent=2), encoding='utf-8')
    for error in teaching_report.get("validation_errors", []):
        print(f"Teaching validation: {error}")
    if not args.no_prerequisites:
        from student_model.finalize import finalize_prerequisites
        story_plan, prerequisite_report = finalize_prerequisites(story_plan, prerequisite_report)
        representation_plan = story_plan.representation_plan
        (out_dir / 'prerequisite_plan.json').write_text(
            json.dumps(prerequisite_report, ensure_ascii=False, indent=2), encoding='utf-8')
    (out_dir / 'scene_planning_debug.json').write_text(json.dumps(
        scene_planning_report(selected_plan, story_plan, fused.answer_graph),
        ensure_ascii=False, indent=2), encoding='utf-8')
    from .summary import append_summary
    story_plan = append_summary(story_plan, model)
    (out_dir / 'conclusion_report.json').write_text(json.dumps(
        story_plan.metadata.get('conclusion_report', {}), ensure_ascii=False, indent=2), encoding='utf-8')
    from representation.coverage import coverage_report
    coverage = coverage_report(story_plan, settings.data.workbook)
    (out_dir / "animation_coverage.json").write_text(
        json.dumps(coverage, ensure_ascii=False, indent=2), encoding="utf-8")
    print("Animation coverage :", ", ".join(
        f"{item['pattern_id']}={item['status']}" for item in coverage["selected"]))
    render_plan = layout.layout(story_plan)

    rep_json = _write_json(representation_plan, out_dir / "representation_plan.json")
    story_json = _write_json(story_plan, out_dir / "story_plan.json")
    from rendering.subgraph import prepare_subgraph, group_subquestions, add_subquestion_intros
    render_payload = asdict(render_plan)
    render_payload['metadata'] = {**render_payload.get('metadata', {}), 'graph_panel': args.graph_panel}
    render_payload = add_subquestion_intros(prepare_subgraph(group_subquestions(render_payload)))
    if args.language == 'en':
        from .localization import localize_payload
        render_payload = localize_payload(render_payload, 'en', model)
    selected_nodes = {n["knowledge_node_id"]: n for s in render_payload["scenes"] for n in s["nodes"]}
    selected_relations = {r["relation_id"]: r for s in render_payload["scenes"] for r in s["relations"]}
    (out_dir / "teaching_graph.json").write_text(json.dumps({
        "nodes": list(selected_nodes.values()), "relations": list(selected_relations.values()),
        "excluded_scenes": story_plan.metadata.get("excluded_scenes", [])},
        ensure_ascii=False, indent=2), encoding="utf-8")
    render_json = out_dir / "render_plan.json"
    render_json.write_text(json.dumps(render_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    voiced_payload = None
    if args.tts:
        from .tts import AzureTTS, add_narration
        voiced_payload = add_narration(render_payload, AzureTTS(), str(out_dir / "audio"), args.voice)
        (out_dir / "render_plan_voiced.json").write_text(
            json.dumps(voiced_payload, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"RepresentationPlan : {rep_json}")
    print(f"StoryPlan          : {story_json}")
    print(f"RenderPlan         : {render_json}")
    print(f"Scenes             : {len(render_plan.scenes)}")
    print(f"Estimated duration : {render_plan.estimated_duration:.1f}s")

    if representation_plan.warnings:
        print("Representation warnings:")
        for warning in representation_plan.warnings:
            print(" -", warning)

    for scene in render_plan.scenes:
        patterns = []
        for beat in scene.beats:
            if beat.pattern_id and beat.pattern_id not in patterns:
                patterns.append(beat.pattern_id)
        print(
            f"{scene.scene_id:>5}  {scene.scene_role:<22} {scene.layout:<18} "
            f"patterns={','.join(patterns) or '-'}"
        )

    if not args.no_manim_script:
        script = ManimScriptGenerator().generate_payload(
            voiced_payload if voiced_payload is not None else render_payload,
            out_dir / settings.manim.generated_script)
        print(f"Manim script       : {script}")
        print(
            "Render with: "
            f'python -m rendering.manim.render "{script}" '
            f'--quality {settings.manim.quality} --media-dir "{settings.manim.media_dir}"'
        )


if __name__ == "__main__":
    main()

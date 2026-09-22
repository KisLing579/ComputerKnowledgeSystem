"""Translate presentation text without regenerating knowledge/teaching plans."""
import ast
import copy
import json
import re
from pathlib import Path
from .llm_format import parse_plan

TEXT_KEYS = {'question', 'subquestion', 'title', 'name', 'definition', 'narration',
             'narration_summary', 'label', 'relation_label', 'summary_points', 'answer_summary',
             'student_narration', 'text'}


def chinese(text):
    return isinstance(text, str) and re.search(r'[\u3400-\u9fff]', text)


def translate_texts(texts, model):
    unique = list(dict.fromkeys(t for t in texts if chinese(t)))
    output = {}
    for start in range(0, len(unique), 20):
        batch = unique[start:start+20]
        result = parse_plan(model.invoke(
            'Translate these computer science presentation strings into concise natural English. '
            'Preserve meaning, numbers, equations, identifiers and whitespace needed between fragments. '
            'Do not add explanations or facts. Return JSON {"translations":[strings in identical order]}. Input: '
            + json.dumps(batch, ensure_ascii=False))).get('translations')
        if not isinstance(result, list) or len(result) != len(batch) or any(
                not isinstance(t, str) or not t.strip() or chinese(t) for t in result):
            raise ValueError('Invalid English translation batch')
        output.update(zip(batch, result))
    return output


def localize_payload(payload, language='zh', model=None):
    result = copy.deepcopy(payload)
    if language not in {'zh', 'en'}:
        raise ValueError('language must be zh or en')
    if language == 'zh':
        return result
    texts = []
    def visit(value, key='', translations=None):
        if isinstance(value, dict):
            return {k: visit(v, k, translations) for k, v in value.items()}
        if isinstance(value, (list, tuple)):
            return [visit(v, key, translations) for v in value]
        if key in TEXT_KEYS and chinese(value):
            texts.append(value)
            return translations.get(value, value) if translations is not None else value
        return value
    visit(result)
    result = visit(result, translations=translate_texts(texts, model))
    result.pop('opening_audio', None)
    for scene in result.get('scenes', []):
        for beat in scene.get('beats', []):
            beat.pop('audio', None)
            beat.pop('audio_end', None)
    result.setdefault('metadata', {})['language'] = 'en'
    return result


def localize_script(code, model):
    """Translate fixed captions, including f-string text, after source assembly."""
    tree = ast.parse(code)
    # PLAN's embedded JSON already contains translated display text and stable IDs.
    plan_strings = {n.args[0] for n in ast.walk(tree) if isinstance(n, ast.Call)
                    and isinstance(n.func, ast.Attribute) and n.func.attr == 'loads'
                    and n.args and isinstance(n.args[0], ast.Constant)}
    constants = [n for n in ast.walk(tree) if isinstance(n, ast.Constant)
                 and n not in plan_strings and chinese(n.value)]
    translations = translate_texts([n.value for n in constants], model)
    for node in constants:
        node.value = translations[node.value]
    return ast.unparse(tree) + '\n'


def main():
    import argparse
    from .text_engine import DeepseekModel
    from .tts import AzureTTS, add_narration
    from rendering.subgraph import group_subquestions, prepare_subgraph, add_subquestion_intros
    from rendering.manim.script_generator import ManimScriptGenerator
    parser = argparse.ArgumentParser(description='Create an English presentation from an existing render plan')
    parser.add_argument('plan', type=Path)
    parser.add_argument('--out-dir', type=Path, required=True)
    parser.add_argument('--tts', action='store_true')
    parser.add_argument('--voice', default='en-US-JennyNeural')
    args = parser.parse_args()
    model = DeepseekModel()
    payload = json.loads(args.plan.read_text(encoding='utf-8'))
    payload = localize_payload(add_subquestion_intros(prepare_subgraph(group_subquestions(payload))), 'en', model)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    (args.out_dir / 'render_plan.json').write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    if args.tts:
        payload = add_narration(payload, AzureTTS(), str(args.out_dir / 'audio'), args.voice)
        (args.out_dir / 'render_plan_voiced.json').write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    ManimScriptGenerator().generate_payload(payload, args.out_dir / 'generated_explanation.py')


if __name__ == '__main__':
    main()

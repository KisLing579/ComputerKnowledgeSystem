# Computer Knowledge Graph → Explanation Animation

This project turns a question into a graph-backed teaching plan and a generated Manim animation script. Rendering that script produces a video; Azure Speech can optionally add narration.

The current entry point is **`resource_planning.pipeline`**. `visual.pipeline` is a compatibility alias for the same CLI. This guide replaces the earlier chapter-1 MVP instructions.

```text
Excel workbook → Neo4j
Question → candidate paths + optional LLM subquestions
         → answer coverage checks and bounded evidence repair
         → fused ExplanationPlan + student prerequisites
         → RepresentationPlan → StoryPlan + teaching validation
         → layout → RenderPlan → optional translation / narration
         → generated Manim script → separate render command → video
```
### Install Neo4j

Neo4j Community (or higher) must be running and reachable before import. The project expects `bolt://localhost:7687`, user `neo4j`, database `neo4j`, with the password supplied through `NEO4J_PASSWORD`.

The quickest local setup is Docker:

```powershell
docker run --name neo4j -p 7474:7474 -p 7687:7687 -e NEO4J_AUTH=neo4j/your-password neo4j:5-community
```

Use that same password for `NEO4J_PASSWORD` below. On Windows or macOS without Docker, install **Neo4j Desktop** from neo4j.com, create a local DBMS, and set its password there. A standalone **Neo4j Community Server** download also works: run its `neo4j console` startup script and set the password on first login.

A running instance exposes the Neo4j Browser at `http://localhost:7474`.

Start Neo4j, then set its credentials in the same shell. Configured defaults are `bolt://localhost:7687`, user `neo4j`, database `neo4j`.

```powershell
$env:NEO4J_PASSWORD = "your-password"
.\.venv\Scripts\python.exe -m kg.importer
```

`NEO4J_URI`, `NEO4J_USER` and `NEO4J_DATABASE` override the configured connection. Keep secrets in environment variables; the code does not automatically load `.env` files.

For an intentional clean rebuild of a dedicated project database, the importer accepts `--reset`. **That option deletes all nodes and relationships in the selected database.** A normal import does not perform that reset.


## 1. Python environment

Run commands from the project root. Python 3.11+ is required (`tomllib` is used). These PowerShell examples use the project's virtual environment directly, without activation.

If `.venv` does not exist, create it with an installed Python:

```powershell
py -3 -m venv .venv
```

Install core dependencies, then Manim if you want to render videos:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pip install -r requirements-manim.txt
```

On Linux/macOS, use `.venv/bin/python` instead. With an activated environment, `python` can replace the explicit executable path throughout this guide.

## 2. Validate and import the graph

`config.toml` currently selects `data/computer_core_kg_ch1_ch9_master_v0_6_dependencies.xlsx`. The workbook contains knowledge nodes, relations, representation metadata and teaching dependencies. Its path is resolved relative to the configuration file.

Validate without connecting to Neo4j:

```powershell
.\.venv\Scripts\python.exe -m kg.importer --dry-run
```

The supplied workbook currently reports **969 nodes and 2,830 relationships**. Counts can change when the workbook is updated.



## 3. Generate an explanation

The full pipeline requires a model API key and network access, including when `--reasoning rules --teaching rules` is selected: answer coverage is always checked with the model.

```powershell
$env:DEEPSEEK_API_KEY = "your-api-key"
$env:TEXT_MODEL = "deepseek-chat"
.\.venv\Scripts\python.exe -m resource_planning.pipeline "CPU由哪些部分组成？" --language zh --out-dir out_cpu
```

`TEXT_MODEL` defaults to `deepseek-chat`. `TEXT_BASE_URL` defaults to `https://api.deepseek.com/v1`; an alternative service must support the client's Chat Completions JSON-object requests. No additional LLM SDK is needed.

**The default output language is English.** Pass `--language zh` for Chinese. English localization happens after planning and uses the model; it does not rerun retrieval in English.

A successful run writes plans and `out_cpu/generated_explanation.py`. It **does not render a video automatically**.

## 4. Render the video

```powershell
.\.venv\Scripts\python.exe -m rendering.manim.render out_cpu/generated_explanation.py --quality l --media-dir out_cpu/media
```

The wrapper defaults to the `GeneratedExplanation` scene and a synchronous frame writer to reduce memory use. Quality choices are `l`, `m`, `h`, `p`, `k`; use `l` for a preview. Manim prints the resulting video location under the chosen media directory.

Without TTS, the script has visual text but no synthesized narration; the renderer reports this. `--async-writer` selects Manim's queued frame writer.

## 5. Optional speech narration

Install Azure Speech and configure credentials:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-tts.txt
$env:AZURE_SPEECH_KEY = "your-speech-key"
$env:AZURE_SPEECH_REGION = "your-resource-region"
```

Either generate a new plan with speech:

```powershell
.\.venv\Scripts\python.exe -m resource_planning.pipeline "CPU由哪些部分组成？" --language zh --tts --out-dir out_cpu_voiced
.\.venv\Scripts\python.exe -m rendering.manim.render out_cpu_voiced/generated_explanation.py --quality l --media-dir out_cpu_voiced/media
```

Or add speech to an existing successful plan without querying Neo4j again:

```powershell
.\.venv\Scripts\python.exe -m resource_planning.tts out_cpu/render_plan.json --voice zh-CN-YunxiNeural
.\.venv\Scripts\python.exe -m rendering.manim.render out_cpu/generated_explanation.py --quality l --media-dir out_cpu/media
```

The standalone TTS command writes `render_plan_voiced.json`, caches WAV files in `audio/`, and regenerates `generated_explanation.py` with audio references. Default voices are `zh-CN-YunxiNeural` for Chinese and `en-US-JennyNeural` for English. Audio paths are absolute; regenerate the voiced script if those files move.

## Pipeline options

For the complete argument list:

```powershell
.\.venv\Scripts\python.exe -m resource_planning.pipeline --help
```

| Option | Default | Purpose |
| --- | --- | --- |
| `--config` | `config.toml` | Workbook and pipeline configuration |
| `--out-dir` | `out_v2` | Plans and generated script directory |
| `--language` | `en` | Final display language: `zh` or `en` |
| `--graph-panel` | `auto` | `on`: graph on the left, animation on the right; `off`: full-width animation; `auto`: existing automatic layout |
| `--reasoning` | `llm` | Subquestion decomposition; `rules` skips model decomposition |
| `--teaching` | `llm` | Teaching organization; also accepts `rules` |
| `--max-teaching-scenes` | `32` | Maximum distinct core evidence scenes across the LLM lesson; positive integer |
| `--limit` | `10` | Candidate path limit per retrieval, not the final combined graph size |
| `--max-hops` | From config (`4`) | Bounded graph path search |
| `--planning-rounds` | `3` | Evidence planning/repair budget, from 1 to 5 |
| `--coverage-policy` | `strict` | Require complete support, or explicitly allow `partial` |
| `--coverage-min-ratio` | `0.5` | Supported requirement fraction for partial mode; range `(0, 1]` |
| `--no-manim-script` | Off | Write plans without generating a Manim script |
| `--tts` | Off | Synthesize Azure narration |
| `--voice` | Based on language | Override the speech voice |en-US-JennyNeural 
| `--student-id` | `anonymous` | Student whose knowledge state is used |
| `--student-states` | None | JSON student-node state snapshots |
| `--no-prerequisites` | Off | Disable prerequisite expansion |
| `--prerequisite-depth` | `3` | Maximum prerequisite expansion depth |
| `--prerequisite-max-nodes` | `20` | Prerequisite node budget |

Prerequisites are enabled by default and read from `Knowledge_Dependencies` in the workbook. Missing student states remain unknown. `--include-recommended-prerequisites` includes recommended dependencies; `--state-as-of` accepts a timezone-aware planning timestamp. See [student model design](student_model/DESIGN.md) for the state format and policy.

## Outputs and failed runs

| File | What to inspect |
| --- | --- |
| `reasoning_plan.json` | Subquestions, retrieval evidence and revisions |
| `planning_attempts.json` | Coverage checks and evidence repair attempts |
| `answer_coverage.json` | Whether evidence supports the requested answer |
| `candidate_paths.json`, `answer_graph.json` | Retrieved paths and fused evidence graph |
| `explanation_plan.json` | Structured explanation before visual planning |
| `prerequisite_plan.json` | Student prerequisite decisions |
| `representation_plan.json` | Bound node representations and relation animations |
| `story_plan.json`, `teaching_plan.json` | Teaching sequence and validation report |
| `conclusion_report.json` | Final conclusion synthesized from the full narration, with narration references; uses verbatim excerpts if the model fails |
| `scene_planning_debug.json` | Evidence groups, semantic scene patterns and roles |
| `animation_coverage.json` | Selected animation pattern coverage |
| `teaching_graph.json` | Displayed nodes/relations and excluded scenes |
| `render_plan.json` | Final layout and rendering payload |
| `generated_explanation.py` | Generated Manim scene |
| `render_plan_voiced.json`, `audio/` | Additional TTS outputs |

Files are written as stages complete; a failed run may produce only diagnostics. Insufficient answer evidence, unavailable coverage review or failed teaching validation can stop generation. Inspect `answer_coverage.json`, `planning_attempts.json` and `teaching_plan.json` as available.

Partial mode (`--coverage-policy partial --coverage-min-ratio 0.5`) allows an explicitly incomplete answer when enough requirements are supported. It does not bypass unavailable reviews or invalid evidence references. Coverage checks are model judgments, not proof of factual correctness.

Failed runs do not delete older outputs. Use separate output directories for experiments, and only render after the current planning command succeeds.

## Offline previews and lower-level tools

To try the rendering architecture without Neo4j, model credentials or Azure, generate the workbook-backed ISA demo:

```powershell
$env:PYTHONIOENCODING = "utf-8"
.\.venv\Scripts\python.exe -m rendering.manim.semantic_scene_demo
.\.venv\Scripts\python.exe -m rendering.manim.render out_semantic_isa/isa_interface.py --quality l --media-dir out_semantic_isa/media
```

To preview the node archetypes from the gallery module:

```powershell
.\.venv\Scripts\python.exe -m rendering.manim.archetype_gallery --batch 4 --language zh --out-dir out_archetypes/batch04
.\.venv\Scripts\python.exe -m rendering.manim.render out_archetypes/batch04/gallery_zh.py --scene ArchetypeGallery --quality l --media-dir out_archetypes/batch04/media
```

These demos need the workbook and core dependencies; rendering also needs Manim. Gallery batches are 1–6. Batches 5 and 6 add processor and memory behavior diagrams. A gallery is a structural preview, not a complete question-answering run. See [archetype progress](rendering/manim/ARCHETYPE_PROGRESS.md).

For graph retrieval or the deterministic recursive explanation planner, with Neo4j configured:

```powershell
.\.venv\Scripts\python.exe -m kg.query "CPU由哪些部分组成？" --json
.\.venv\Scripts\python.exe -m explanation.planner "CPU由哪些部分组成？" --json
```

These lower-level commands do not run the full teaching, coverage, localization or rendering pipeline. See [language conversion](resource_planning/LANGUAGES.md) for converting an existing render plan to English.

## Code map and tests

Teaching clauses select `animation_unit_ids` from each source scene's
`animation_units`. A unit keeps dependent phases (such as establish, transform,
and emphasize) together. A semantic scene supplies a shared layout, but its
unrelated relation animations need not all play under every narration. Selected
units retain their own actions on later references instead of becoming a generic
whole-scene highlight. The planner's semantic review checks narration against the
selected units, not just against the entire source scene.

Subquestion titles remain silent. Prerequisite explanations include the concept
name in the spoken definition (for example, “抽象是……”); changing that text
invalidates its old audio. Regenerate TTS and then render to update an existing
video. Existing MP4 files are not changed by editing a render plan.

| Directory | Responsibility |
| --- | --- |
| `kg/` | Configuration, Excel import, entity linking and Neo4j retrieval |
| `explanation/` | Evidence strategies, path fusion, recursive plans and coverage repair |
| `student_model/` | Student states and prerequisite adaptation |
| `representation/` | Workbook representation registry and animation grammar |
| `resource_planning/` | Main CLI, binding, story/teaching planning, localization and TTS |
| `rendering/layout/` | Scene layout |
| `rendering/manim/` | Script generation, node drawings, animations, demos and rendering |
| `visual/`, `manim_backend/` | Earlier modules and compatibility entry points |
| `tests/` | Unit and regression tests |

Run the test suite with:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Tests do not replace checking a generated video or validating live Neo4j, model and speech connections.
#   C o m p u t e r K n o w l e d g e S y s t e m  
 
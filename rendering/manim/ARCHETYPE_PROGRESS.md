# Visual archetype implementation batches

Source of truth: `config.toml` → `Visual_Archetypes` and `Visual_Profiles` in the workbook.

## Batches 05–06: processor and memory behavior

Batch 05 adds nine processor drawings (`processor_nodes.py`): clocked state,
control FSM/table, microcode, pipeline timeline, hazards, prediction, issue bundles,
and dynamic scheduling. It covers 107 profile definitions with schematic designs;
it does not implement every profile-specific mechanism. Fourteen processor
patterns now use explicit four-stage examples (`processor_effects.py`), including
forwarding, stalls, flushes and ordered retirement after out-of-order execution.

Batch 06 adds eight memory/system drawings (`memory_behavior.py`): cache mapping,
banking, locality/access traces, miss classification, protection, context switching,
and queues. Fourteen memory patterns now have example traces. The cache model
computes tags/sets/offsets, hit/miss, LRU replacement and write-back/write-through
state. Address translation preserves page offsets and identifies missing pages.
Examples state their geometry and are not measured performance results.

These new relation traces are reported as `simplified`, not full semantic coverage.
The remaining inventory is recorded in `outputs/animation_backlog/current.json`;
the initial inventory is preserved in `baseline.json`.

```powershell
python -m rendering.manim.archetype_gallery --batch 5 --language en --out-dir out_archetypes/batch05
python -m rendering.manim.archetype_gallery --batch 6 --language en --out-dir out_archetypes/batch06
python -m rendering.manim.render out_archetypes/batch06/gallery_en.py --scene ArchetypeGallery --quality l
python -m unittest discover -s tests -p test_processor_animation.py -v
python -m unittest discover -s tests -p test_memory_behavior.py -v
```

Batch 05 includes a rendered relation preview at
`out_archetypes/batch05/media/videos/relation_traces/480p15/ProcessorRelationGallery.mp4`.
The bilingual processor runtime tests construct the nine types and exercise all
four frames of all fourteen patterns. These checks do not prove every workbook
profile's teaching semantics are complete.

Validation: the focused regression suite runs 26 tests: 25 pass and one optional
Manim test is skipped in the project venv. That processor runtime test also passes in
the installed Manim environment. The memory runtime check constructs 16 bilingual
drawings and exercises 112 trace frames. Both gallery images have been inspected
for label clipping. A memory relation preview is available at
`out_archetypes/batch06/media/videos/relation_traces/480p15/MemoryRelationGallery.mp4`.
The current inventory contains 53 specialized node archetypes, 70 fallback
archetypes and one default; 72 registered pattern IDs still lack templates.

## Batch 01: structured node graphics

Implemented five dedicated node renderers in `structured_nodes.py`, covering the 16 existing profiles:

| Archetype | Profile-aware structure |
| --- | --- |
| `instruction_format` | Proportional R/I/J bit fields; generic and variable-length layouts |
| `stack_frame` | LIFO stack, saved-state/local-variable frame, logical floating-point stack |
| `memory_map` | Code/data/heap/free/stack regions, increasing-address axis, heap emphasis |
| `character_table` | Actual 7-bit ASCII values and Unicode code points |
| `table_mapping` | Symbol addresses, relocation sites, register allocation/spill, configuration entries |

The main layout engine now propagates `render_requirements` to the renderer. English labels use fitted text; CJK characters in English Unicode examples select a CJK-capable font.

These are schematic node graphics, not complete process simulations. The preview animates reveal and emphasis only. ABI-dependent stack layouts, memory regions and mapping values are labeled as examples. Existing plans without `metadata.render_requirements` use the generic variant; regenerate plans from the representation/story layer to recover profile details.

Coverage after batch 01: **124 defined / 21 explicit specialized branches / 1 default functional block / 102 fallback types**. The 21 include older simplified/shared branches; this is not a count of fully implemented semantic animations.

## Reproduce and review

Use a Python environment with project dependencies; rendering additionally requires Manim.

```powershell
python -m rendering.manim.archetype_gallery --language en
python -m rendering.manim.archetype_gallery --language zh
python -m manim -qm -s --media_dir out_archetypes/batch01/media out_archetypes/batch01/gallery_en.py ArchetypeGallery
python -m manim -qm -s --media_dir out_archetypes/batch01/media out_archetypes/batch01/gallery_zh.py ArchetypeGallery
python -m manim -ql --media_dir out_archetypes/batch01/media out_archetypes/batch01/gallery_en.py ArchetypeGallery
python -m unittest discover -s tests -p test_structured_nodes.py
```

`out_archetypes/batch01/coverage.json` lists every workbook archetype with its definition, profile count, implementation status and batch. Regenerate this report after each batch. The optional Manim test constructs every batch-01 profile in both languages and checks node bounds; other tests validate bit widths, code points, variant selection and metadata propagation.

## Batch 02: execution structures (validation incomplete)

`execution_nodes.py` adds `addressing`, `control_flow`, and `datapath_graph`, serving 59 workbook profiles. These include merge/concatenation diagrams, branch diamonds, call/return paths, MUX and ALU polygons, and simplified stage/resource topologies. Broad processor profiles remain abstract schematics; they are not full processor simulations.

`ADDRESS_CALC` now has input/formula/result phases for base-offset, indexed, generic PC-relative, and an explicitly labeled 32-bit PC+4 branch example. Other addressing profiles retain their schematic. The coverage status for this partially supported process pattern remains `simplified`. Phase operands are retained between beats; signed branch immediates and 32-bit wrapping are explicit.

An initial bilingual runtime check found horizontal overflow in chain layouts. Spacing has been corrected, but the rerun was skipped at user request. The Chinese gallery rendered before the correction; the English render encountered memory pressure. Do not interpret these files as a fully verified batch.

## Batch 03: cache and virtual-memory structures (not tested)

`memory_nodes.py` adds 6 types serving 37 profiles:

| Archetype | Structure |
| --- | --- |
| `cache_address_decode` | Tag/index/offset values; optional word/byte split |
| `cache_lookup` | Valid/tag/data array, hit/miss examples, PIPT/VIPT captions |
| `cache_set_lookup` | Set/way table; single-set and multi-set examples |
| `tlb_translation` | Valid/VPN/PPN/ASID entries and refill/miss distinctions |
| `page_table_map` | PTE fields, multilevel lookup, inverted table variants |
| `address_translation` | VPN-to-PPN mapping with unchanged page offset |

Address examples explicitly assume a 32-bit address, 16-byte cache blocks and four sets; translation examples use 4 KiB pages. Cache bit-field rectangles have equal visual widths for readability; the numeric bit counts are authoritative. Table entries are schematic examples. Specialized cache access ordering, replacement, TLB refill and page-fault state animations remain future work.

Totals after batch 03: **124 definitions / 30 explicit specialized branches / 1 default block / 93 fallback types**. **258 distinct knowledge nodes** have at least one active binding to a specialized profile. This counts available representations, not guaranteed selection in every scene or complete behavioral coverage.

Per user request, batch 03 tests were skipped. Preview scripts have not yet been rendered. Generated artifacts:

```text
out_archetypes/batch03/gallery_en.py
out_archetypes/batch03/gallery_zh.py
out_archetypes/batch03/coverage.json
```

To regenerate scripts without rendering:

```powershell
python -m rendering.manim.archetype_gallery --batch 3 --out-dir out_archetypes/batch03 --language en
python -m rendering.manim.archetype_gallery --batch 3 --out-dir out_archetypes/batch03 --language zh
```

The gallery uses `ArchetypeGallery` as its Manim scene name. Batch 02 additionally includes `AddressCalculationDemo`.

## Batch 04: memory policies, residency and requests (not tested)

`memory_system_nodes.py` adds six types serving 41 workbook profiles:

| Archetype | Representation |
| --- | --- |
| `cache_write_policy` | Write-through/write-back, dirty eviction, write allocation/bypass and buffering sequences |
| `replacement_choice` | Candidate slots, LRU/random illustrative victims, physical-frame and TLB-entry distinctions |
| `memory_hierarchy_stack` | Tiered cache/memory blocks, split I/D L1, hit/miss emphasis; placement alternatives without false serial links |
| `virtual_memory_map` | Resident/backed pages, virtual aliases, process isolation and resident direct-map examples |
| `page_fault_flow` | Recoverable-fault sequence, conditional dirty writeback, precise retry and thrashing variants |
| `memory_request_timeline` | Blocking refill, early restart, critical-word-first, overlapping requests and speculative prefetch |

Current totals: **124 definitions / 36 explicit specialized branches / 1 default block / 87 fallback types**. **299 distinct knowledge nodes** have at least one active binding to a specialized profile. Batch 04 adds node schematics, not a cycle-accurate memory simulator. Requests and maintenance operations are represented as static paths/timelines; only gallery reveal/emphasis is animated. Unsupported timing, cache coherence, exception paths and policy details are not inferred.

Tests remain skipped per user instruction; no rendered preview is claimed. Generate the standalone scripts and report with:

```powershell
python -m rendering.manim.archetype_gallery --batch 4 --out-dir out_archetypes/batch04 --language en
python -m rendering.manim.archetype_gallery --batch 4 --out-dir out_archetypes/batch04 --language zh
```

Artifacts: `out_archetypes/batch04/gallery_en.py`, `gallery_zh.py`, and `coverage.json`. The Manim scene is `ArchetypeGallery`.

## Remaining sequence

1. Finish validation of batches 02–03 when testing resumes; expand control-flow and datapath state transitions.
2. Remaining memory structures (cache mapping, banked memory, locality traces, miss taxonomy) and actual policy/access state transitions; batch 04 covers policy/residency schematics only.
3. Arithmetic and processor timing: encodings, arithmetic, pipelines, hazards and scheduling.
4. I/O and networks: buses, DMA, disks, RAID, request paths and topology.
5. Parallel systems: coherence, synchronization, memory ordering and distributed structures.
6. General explanatory graphics: metrics, formulas, comparisons, constraints and state changes; audit all remaining fallback entries.

For each batch, distinguish node-shape coverage from animation-pattern coverage; validate actual transitions before marking a process animation complete.

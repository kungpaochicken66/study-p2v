# Templates and mathematics

A storyboard is JSON data describing fixed templates, not an animation script.
[storyboard.json](../examples/storyboard.json) demonstrates V1's seven templates;
[v2-templates.json](../examples/v2-templates.json) demonstrates all 12. The authenticated
`GET /v1/templates` endpoint returns the complete JSON Schema and target conventions.

## Template catalog

Every segment requires `template` and `title`; `duration` defaults to 4 seconds.

| Template | Content fields | Animation targets | Presentation |
| --- | --- | --- | --- |
| `title` | `subtitle` | `title`, `subtitle` | Title followed by subtitle |
| `bullets` | `items`, 1-6 | `item-1`, `item-2`, ... | Numbered points revealed in order |
| `compare` | `left`, `right`: `heading` and 1-4 `items` each | `left-heading`, `right-heading`, `left-1`, `right-1`, ... | Two columns |
| `bars` | `points`, 1-6: `label` and nonnegative `value` | `bar-1`, `bar-2`, ... | Horizontal bars grow from the left; labels stay legible |
| `flow` | `steps`, 2-5 | `step-1`, `step-2`, ... | Directed nodes and incoming edges |
| `timeline` | `steps`, 2-5 | `step-1`, `step-2`, ... | Sequential timeline nodes |
| `equation` | Exactly one of `steps` or `math_steps`, 1-6 | `step-1`, `step-2`, ... | Each step replaces the preceding step |
| `definition` (V2) | `term`, `body` | `term`, `body` | Term followed by its explanation |
| `example` (V2) | `prompt`, `steps`, 1-6 | `prompt`, `step-1`, `step-2`, ... | Prompt remains while solution steps replace one another |
| `cycle` (V2) | `steps`, 2-5 | `step-1`, `step-2`, ... | Circular nodes and directional arrows |
| `checklist` (V2) | `items`, 1-6 | `item-1`, `item-2`, ... | Empty boxes remain; checks and text appear in order |
| `priority` (V2) | `items`, 1-6 | `item-1`, `item-2`, ... | Input order defines priority, highest first |

Indices are one-based and must refer to an element that exists. Only the `title` template
exposes a `title` target. Other segment headings cannot be targeted by narration cues.

## Storyboard and field limits

| Field | Default | Contract |
| --- | --- | --- |
| `schema_version` | 1 | 1 or 2; V2 is required for the five additional templates, `math_steps`, `narration`, and subtitles |
| `theme` | `midnight` | `midnight` or `paper`, shared by the whole video |
| `output` | 1280x720, 24 fps | Even dimensions: width 320-1920, height 180-1080; aspect ratio within 0.025 of 16:9; fps 15, 24, or 30 |
| `subtitle_mode` | `none` | `none`, `sidecar`, or `burn`; non-`none` requires V2 |
| `segments` | Required | 1-24 segments; sum of requested durations at most 600 seconds |
| Segment `title` | Required | 1-48 characters after trimming |
| Segment `duration` | 4 | 1-60 seconds; resolved to an integer number of video frames |
| Segment `audio_asset_id` | `null` | An uploaded audio asset in the same namespace |
| Segment `narration` | `null` | V2 `timed` or `clips`; mutually exclusive with segment `audio_asset_id` |

Unknown fields and NaN/Infinity are rejected. Character limits count Unicode characters,
including spaces and punctuation, rather than words or rendered width.

Body text fields use 1-140 characters after trimming. Short fields, including flow/timeline/
cycle steps, column headings, and definition terms, use 1-48. A bar label uses 1-24, and its
value is between 0 and 1e9. The `title` template's default subtitle is
`Structured ideas, rendered clearly`; set it explicitly for your content.

Schema limits do not promise that every combination of maximum length and element count
fits. Text is measured with Pango, wrapped, and reduced only to a bounded minimum size.
Content that still cannot fit fails with `text_overflow` instead of being clipped or
ellipsized. Review actual output at the intended viewing size.

## Write clear content

- Give each segment one explanation goal. Split dense material across segments.
- Use `compare` for two groups and `bars` for one nonnegative series. Bars do not provide
  negative values, logarithmic scales, or multiple series.
- Use `flow` for directed steps, `timeline` for sequence, and `cycle` for a loop. These
  templates illustrate relationships; they do not execute or infer a workflow.
- Treat an equation step as a complete display state. Use `example` when a question should
  remain visible above changing solution steps.
- Supply priority order yourself. Checklist checks are visual elements, not external status.
- Prepare audio and timing before writing narration. Cue `text` supplies subtitles; it is not
  copied from template content or transcribed from audio.

A one-second segment is permitted by the contract, but may not give a viewer enough time to
read it. Low-resolution output can be useful for iteration; review final output at the
resolution you intend to distribute.

## Structured mathematics

V1 equations use plain Unicode text in `steps`. V2 equations may use `math_steps` instead.
Exactly one representation must be supplied. Structured mathematics accepts a bounded tree,
not TeX, Python, or an expression to evaluate:

```json
{
  "schema_version": 2,
  "segments": [{
    "template": "equation",
    "title": "A fraction with a square root",
    "duration": 4,
    "math_steps": [{
      "kind": "fraction",
      "parts": [
        {"kind": "root", "parts": [{"kind": "symbol", "value": "a + b"}]},
        {"kind": "symbol", "value": "2"}
      ]
    }]
  }]
}
```

| `kind` | Required structure |
| --- | --- |
| `symbol` | `value`, 1-40 characters; no child expressions |
| `row` | `parts`, 1-16 expressions arranged horizontally |
| `fraction` | `parts`: numerator, denominator |
| `root` | `parts`: one radicand |
| `sub` / `sup` | `parts`: base, subscript or superscript |
| `matrix` | `rows`: 1-4 rows and 1-4 columns, rectangular |

Each expression tree is limited to 128 nodes and depth 8. `value` is only allowed on symbols;
`rows` is only allowed on matrices. Symbols accept ASCII letters, numbers, spaces, a bounded
set of punctuation, Greek letters, and selected mathematical symbols. Backslashes, braces,
and arbitrary commands are rejected. The exact character allowlist is in `models.py`.

MathText supplies symbol SVG paths; Manim arranges fractions, roots, scripts, and matrices.
No external TeX engine is invoked. A mathematical subexpression whose effective font size
would fall below 18 fails with `math_overflow`. The service does not check mathematical
correctness or provide symbolic computation.

## Timing and narration

The effective segment duration is `round(duration * fps) / fps`, using Python's rounding
rule. That same clock determines subsequent segment offsets, audio placement, and subtitles.
The result receipt reports each segment's frame count and effective duration.

Without narration cues, templates reveal content during roughly the first 65% of the
segment, then hold. With narration, use `reveal`, `highlight`, and `exit` on the targets in
the catalog. Each cue must span at least one frame after quantization. Equation and example
segments with narration must include a `reveal` cue for every `step-N`, because those steps
share the same visual area.

See [API narration](api.md) for complete timed and clip examples, audio duration rules,
subtitle behavior, and frame alignment. Upstream applications or language models must submit
the same bounded schema and uploaded asset IDs as any other caller.

## Add a template

Declare the bounded model, schema-version rules, and stable targets in `models.py`. Add the
scene implementation, discovery metadata, and an English example. Reuse the existing font,
theme, layout checks, and frame clock. Add new rendering modules to the runtime fingerprint
and lock any new dependencies during development.

Validate rejected inputs, ordinary and dense content, Unicode glyph coverage, element-count
and duration boundaries, actual frames, complete decoding, narration, and subtitle layout.
For multilingual test fixtures, use escaped Unicode in source. Check cache reuse and
render/encode counts when content changes. See [development](development.md) and
[validation](validation.md) for extension and acceptance procedures.

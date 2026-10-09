"""Public synthetic fixtures shared by visual acceptance and examples."""

from copy import deepcopy


def symbol(value):
    return {"kind": "symbol", "value": str(value)}


def math_steps():
    return [
        {
            "kind": "row",
            "parts": [
                symbol("x ="),
                {
                    "kind": "fraction",
                    "parts": [
                        {
                            "kind": "row",
                            "parts": [
                                symbol("-b ±"),
                                {
                                    "kind": "root",
                                    "parts": [
                                        {
                                            "kind": "row",
                                            "parts": [
                                                {"kind": "sup", "parts": [symbol("b"), symbol(2)]},
                                                symbol("- 4ac"),
                                            ],
                                        }
                                    ],
                                },
                            ],
                        },
                        symbol("2a"),
                    ],
                },
            ],
        },
        {
            "kind": "row",
            "parts": [
                {"kind": "sub", "parts": [symbol("A"), symbol("ij")]},
                symbol("="),
                {"kind": "matrix", "rows": [[symbol(1), symbol(2)], [symbol(3), symbol(4)]]},
            ],
        },
    ]


def samples():
    return [
        {
            "template": "title",
            "title": "Keep narration and visuals in sync",
            "subtitle": "Structured content, verified output",
        },
        {
            "template": "bullets",
            "title": "Three key actions",
            "items": ["Define the problem", "Show the evidence", "Verify the result"],
        },
        {
            "template": "compare",
            "title": "Choose a method for the task",
            "left": {
                "heading": "Structured rendering",
                "items": ["Control text and equations", "Reuse identical inputs"],
            },
            "right": {
                "heading": "Generated media",
                "items": ["Create images and short clips", "Generate options as needed"],
            },
        },
        {
            "template": "bars",
            "title": "Compare work across stages",
            "points": [
                {"label": "First render", "value": 100},
                {"label": "Partial edit", "value": 45},
                {"label": "Repeat request", "value": 8},
            ],
        },
        {
            "template": "flow",
            "title": "From input to usable output",
            "steps": ["Parse input", "Render frames", "Mix audio", "Verify output"],
        },
        {
            "template": "timeline",
            "title": "Reveal the process step by step",
            "steps": [
                "Ask a question",
                "Explain the method",
                "Show an example",
                "Review key points",
            ],
        },
        {"template": "equation", "title": "Equations and matrices", "math_steps": math_steps()},
        {
            "template": "definition",
            "title": "Start with a shared concept",
            "term": "Segment cache",
            "body": "Reuse verified frames when the content and rendering settings are unchanged.",
        },
        {
            "template": "example",
            "title": "Find the answer step by step",
            "prompt": "One box holds three balls. How many balls are in two boxes?",
            "steps": ["Three balls per box, two boxes", "3 × 2 = 6", "Answer: six balls"],
        },
        {
            "template": "cycle",
            "title": "Verify every iteration",
            "steps": ["Observe", "Hypothesize", "Experiment", "Review"],
        },
        {
            "template": "checklist",
            "title": "Check each deliverable",
            "items": [
                "Complete input",
                "Correct visuals",
                "Aligned audio and visuals",
                "Readable output",
            ],
        },
        {
            "template": "priority",
            "title": "Start with the highest priority",
            "items": [
                "Make the content correct",
                "Make the explanation clear",
                "Reduce repeated computation",
                "Scale using measured evidence",
            ],
        },
    ]


def variant(segment, kind):
    s = deepcopy(segment)
    s["duration"] = 60 if kind == "maximum-duration" else 1 if kind == "minimum-duration" else 2
    template = s["template"]
    if kind == "long-text":
        s["title"] = "Show each teaching step and verify its result"
        long = "Explain complex ideas in logical steps, preserve each condition, and help the viewer follow the process and verify its result."
        if template == "title":
            s["subtitle"] = long
        elif template in {"bullets", "checklist", "priority"}:
            s["items"] = [long]
        elif template == "compare":
            for side in ("left", "right"):
                s[side]["items"] = ["Set input limits, show each step, and check results."]
        elif template == "cycle":
            s["steps"] = [
                "Confirm input limits",
                "Follow the step order",
                "Check the saved result",
            ]
        elif template in {"flow", "timeline"}:
            s["steps"] = [
                "Define input and output limits",
                "Follow the agreed step order",
                "Read back and verify the result",
            ]
        elif template == "bars":
            s["points"] = [
                {"label": "Render every frame first", "value": 100},
                {"label": "Reuse verified output", "value": 20},
            ]
        elif template == "definition":
            s["body"] = (
                "Explain every condition and step in a complex process. Confirm completion only by independently reading and checking the saved output file."
            )
        elif template == "example":
            s["prompt"] = (
                "Use concrete numbers to explain an abstract step, preserving the conditions that make each calculation valid."
            )
            s["steps"] = [
                long,
                "Work back from the final result to the inputs and confirm that every required condition has been included.",
            ]
        elif template == "equation":
            s["math_steps"] = [
                {
                    "kind": "fraction",
                    "parts": [
                        {
                            "kind": "root",
                            "parts": [
                                {
                                    "kind": "row",
                                    "parts": [
                                        {"kind": "sup", "parts": [symbol("a"), symbol(2)]},
                                        symbol("+"),
                                        {"kind": "sup", "parts": [symbol("b"), symbol(2)]},
                                    ],
                                }
                            ],
                        },
                        {"kind": "fraction", "parts": [symbol("1 + x"), symbol("2 + y")]},
                    ],
                }
            ]
    if kind == "maximum-elements":
        if template in {"bullets", "checklist", "priority"}:
            s["items"] = [f"Item {i + 1}: check content and results" for i in range(6)]
        elif template in {"flow", "timeline", "cycle"}:
            s["steps"] = [f"Step {i + 1}" for i in range(5)]
        elif template == "bars":
            s["points"] = [{"label": f"Item {i + 1}", "value": i * 20} for i in range(6)]
        elif template == "compare":
            for side in ("left", "right"):
                s[side]["items"] = [f"Comparison item {i + 1}" for i in range(4)]
        elif template == "equation":
            s["math_steps"] = [
                {
                    "kind": "matrix",
                    "rows": [[symbol(i * 4 + j + 1) for j in range(4)] for i in range(4)],
                }
            ] * 6
        elif template == "example":
            s["steps"] = [f"Step {i + 1}: verify and record the result" for i in range(6)]
    return s


if __name__ == "__main__":
    import json
    from pathlib import Path

    spec = {
        "schema_version": 2,
        "output": {"width": 1280, "height": 720, "fps": 24},
        "segments": [dict(s, duration=3) for s in samples()],
    }
    Path("examples/v2-templates.json").write_text(
        json.dumps(spec, ensure_ascii=False, indent=2) + "\n"
    )

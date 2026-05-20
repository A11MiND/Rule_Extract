from backend.app.schemas import RuleBase


def test_rule_schema_accepts_options_and_dependencies():
    rule = RuleBase.model_validate(
        {
            "source": {
                "heading_path": ["Main", "Clause 1"],
                "section_id": "section-001-main",
                "evidence_text": "If X applies, the Project Manager shall do Y.",
            },
            "subject": "Project Manager review",
            "condition": "If X applies",
            "action": "Review Y",
            "type": "obligation",
            "options": [
                {
                    "label": "Option C",
                    "condition": "If option C is selected",
                    "action": "Review clause 1.4",
                    "next_rule_ids": ["rule-1-002"],
                    "referenced_sections": ["1.4"],
                }
            ],
            "dependencies": [{"type": "leads_to", "rule_id": "rule-1-002", "reason": "Option path"}],
            "confidence": 0.84,
        }
    )

    assert rule.type == "obligation"
    assert rule.options[0].label == "Option C"
    assert rule.dependencies[0].type == "leads_to"

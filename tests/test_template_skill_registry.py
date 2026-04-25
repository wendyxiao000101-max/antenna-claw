"""Tests for template skill discovery, recommendation, and candidate promotion."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))


def _write_minimal_outputs(paths):
    paths.output_dir.mkdir(parents=True, exist_ok=True)
    paths.json.write_text('{"antenna_type":"PIFA","solids":[]}', encoding="utf-8")
    paths.parameters.write_text(
        "\n".join(
            [
                "Dim names(1 To 2) As String",
                "Dim values(1 To 2) As String",
                'names(1) = "Lp"',
                'values(1) = "18.0"',
                'names(2) = "Wp"',
                'values(2) = "12.0"',
                "StoreParameters names, values",
            ]
        ),
        encoding="utf-8",
    )
    paths.dimensions.write_text('{"unit":"mm","solids":[]}', encoding="utf-8")
    paths.materials.write_text(
        'With Material\n .Reset\n .Name "Copper (annealed)"\n .Create\nEnd With\n',
        encoding="utf-8",
    )
    paths.model.write_text("' model content", encoding="utf-8")
    paths.boolean.write_text("' boolean content", encoding="utf-8")


def test_template_skill_registry_recommend_and_promote(tmp_path):
    from leam.models.session import SessionPaths
    from leam.templates.skill_registry import TemplateSkillRegistry

    project_root = Path(__file__).resolve().parent.parent
    registry = TemplateSkillRegistry(project_root=project_root)

    briefs = registry.list_briefs()
    assert any(item["template_id"] == "air_pifa" for item in briefs)

    recs = registry.recommend("设计一个 2.4GHz air PIFA 天线", top_k=2)
    assert recs
    assert recs[0]["template_id"] == "air_pifa"

    output_dir = tmp_path / "demo_session"
    paths = SessionPaths.build(output_dir, "demo")
    _write_minimal_outputs(paths)

    result = registry.promote_candidate(
        session_paths=paths,
        description="测试描述",
        feedback="结构满意，建议沉淀模板",
        candidate_name="demo_candidate",
    )
    assert Path(result["candidate_path"]).exists()
    assert Path(result["report_path"]).exists()
    assert result["is_valid"]

    report = json.loads(Path(result["report_path"]).read_text(encoding="utf-8"))
    assert report["is_valid"]
    assert report["parameter_count"] >= 1

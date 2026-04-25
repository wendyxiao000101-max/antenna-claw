"""Consistency + topology validation service."""

from ..models import DesignSession
from ..postprocess import format_report, normalize_and_validate_outputs, run_topology_checks


class ValidationService:
    def run_topology(self, session: DesignSession):
        return run_topology_checks(
            param_vba=session.paths.parameters.read_text(encoding="utf-8"),
            model_vba=session.paths.model.read_text(encoding="utf-8"),
            bool_vba=session.paths.boolean.read_text(encoding="utf-8"),
        )

    @staticmethod
    def print_topology_report(issues) -> None:
        print(format_report(issues))

    def run_consistency(self, session: DesignSession):
        errors = normalize_and_validate_outputs(
            json_path=session.paths.json,
            param_path=session.paths.parameters,
            dim_path=session.paths.dimensions,
            mat_path=session.paths.materials,
            model_path=session.paths.model,
            bool_path=session.paths.boolean,
        )
        session.consistency_errors = errors
        return errors


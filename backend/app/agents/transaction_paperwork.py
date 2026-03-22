from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from . import paperwork_templates, schemas as agent_schemas


PDFINFO_CANDIDATE_PATHS = (
    "/opt/homebrew/bin/pdfinfo",
    "pdfinfo",
)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2].parent


def _absolute_template_path(relative_path: str) -> Path:
    return _repo_root() / relative_path


def _resolve_pdfinfo_command() -> str | None:
    for candidate in PDFINFO_CANDIDATE_PATHS:
        resolved = shutil.which(candidate)
        if resolved:
            return resolved
        candidate_path = Path(candidate)
        if candidate_path.is_file():
            return str(candidate_path)
    return None


def _parse_pdfinfo_output(output: str) -> dict[str, str]:
    parsed: dict[str, str] = {}
    for raw_line in output.splitlines():
        line = raw_line.strip()
        if not line or ":" not in line:
            continue
        key, value = line.split(":", 1)
        parsed[key.strip()] = value.strip()
    return parsed


def inspect_registered_template(
    template: agent_schemas.TransactionPaperworkTemplateMetadata,
) -> agent_schemas.TransactionPaperworkTemplateInspection:
    absolute_path = _absolute_template_path(template.source_template_path)
    if not absolute_path.is_file():
        return agent_schemas.TransactionPaperworkTemplateInspection(
            template_id=template.template_id,
            display_name=template.display_name,
            template_version=template.template_version,
            source_template_path=template.source_template_path,
            source_template_checksum_sha256=template.source_template_checksum_sha256,
            template_present=False,
            inspection_method="file_check",
            overlay_fill_supported=False,
            notes=["Registered template asset is missing from the repo workspace."],
        )

    pdfinfo_command = _resolve_pdfinfo_command()
    if not pdfinfo_command:
        return agent_schemas.TransactionPaperworkTemplateInspection(
            template_id=template.template_id,
            display_name=template.display_name,
            template_version=template.template_version,
            source_template_path=template.source_template_path,
            source_template_checksum_sha256=template.source_template_checksum_sha256,
            template_present=True,
            inspection_method="file_check",
            overlay_fill_supported=True,
            ready_fill_modes=["overlay_coordinates"],
            notes=[
                "pdfinfo is unavailable, so form fillability could not be"
                " inspected.",
                "Overlay fill remains the safe fallback path.",
            ],
        )

    command = [pdfinfo_command, str(absolute_path)]
    completed = subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        return agent_schemas.TransactionPaperworkTemplateInspection(
            template_id=template.template_id,
            display_name=template.display_name,
            template_version=template.template_version,
            source_template_path=template.source_template_path,
            source_template_checksum_sha256=template.source_template_checksum_sha256,
            template_present=True,
            inspection_method="pdfinfo",
            overlay_fill_supported=True,
            ready_fill_modes=["overlay_coordinates"],
            notes=[
                "pdfinfo inspection failed; overlay fill remains the safe"
                " fallback path.",
                completed.stderr.strip() or "pdfinfo returned a non-zero exit code.",
            ],
        )

    info = _parse_pdfinfo_output(completed.stdout)
    form_type = info.get("Form", "unknown")
    form_type_normalized = form_type.lower()
    native_field_fill_supported = form_type_normalized not in {"", "none", "unknown"}
    ready_fill_modes: list[agent_schemas.TransactionPaperworkTemplateFillMode] = []
    if native_field_fill_supported:
        ready_fill_modes.append("fill_pdf_fields")
    ready_fill_modes.append("overlay_coordinates")

    notes = []
    if native_field_fill_supported:
        notes.append(
            "Native PDF form fields are present; PDF field fill should be the"
            " preferred runtime path."
        )
    else:
        notes.append(
            "Native PDF form fields were not detected; coordinate-overlay is the"
            " safe runtime path for this template."
        )

    return agent_schemas.TransactionPaperworkTemplateInspection(
        template_id=template.template_id,
        display_name=template.display_name,
        template_version=template.template_version,
        source_template_path=template.source_template_path,
        source_template_checksum_sha256=template.source_template_checksum_sha256,
        template_present=True,
        inspection_method="pdfinfo",
        page_count=_parse_positive_int(info.get("Pages")),
        pdf_version=info.get("PDF version"),
        pdf_form_type=form_type,
        native_field_fill_supported=native_field_fill_supported,
        overlay_fill_supported=True,
        ready_fill_modes=ready_fill_modes,
        notes=notes,
    )


def inspect_paperwork_template(
    template_id: str,
) -> agent_schemas.TransactionPaperworkTemplateInspection:
    template = paperwork_templates.get_paperwork_template_by_id(template_id)
    return inspect_registered_template(template)


def inspect_trade_record_sheet_template() -> (
    agent_schemas.TransactionPaperworkTemplateInspection
):
    return inspect_registered_template(
        paperwork_templates.get_trade_record_sheet_template()
    )


def _parse_positive_int(value: str | None) -> int | None:
    if value is None:
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None

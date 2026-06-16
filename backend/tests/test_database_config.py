from pathlib import Path

from app import database


def test_database_url_prefers_explicit_database_url():
    assert (
        database._resolve_database_url({"DATABASE_URL": "sqlite:///custom.db"})
        == "sqlite:///custom.db"
    )


def test_database_url_uses_configured_data_dir():
    assert (
        database._resolve_database_url({"SKC_DATA_DIR": "/tmp/skc-data"})
        == "sqlite:////tmp/skc-data/sql_app.db"
    )


def test_database_url_prefers_local_ai_crm_data_dir_when_present():
    def fake_exists(path: Path) -> bool:
        return str(path).endswith("SKC Agent OS/backend")

    resolved = database._resolve_database_url({}, path_exists=fake_exists)

    assert resolved.endswith("/SKC Agent OS/backend/sql_app.db")
    assert resolved.startswith("sqlite:///")


def test_database_url_falls_back_to_process_db_when_no_persistent_dir_exists():
    assert database._resolve_database_url({}, path_exists=lambda _path: False) == "sqlite:///sql_app.db"

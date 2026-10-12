# Caviardage des journaux (S8) : ils sont exportables et joints aux rapports de bug.
import logging

from services import secrets_store


def _format(record_msg: str, *args, exc: BaseException | None = None) -> str:
    record = logging.LogRecord("t", logging.ERROR, __file__, 1, record_msg, args, None)
    if exc is not None:
        record.exc_info = (type(exc), exc, exc.__traceback__)
    return secrets_store.RedactingFormatter("%(message)s").format(record)


def test_known_secret_never_reaches_a_log_line(monkeypatch):
    monkeypatch.setattr(secrets_store, "_known_secrets", set())
    secrets_store.register_secret("nonce-abcdef123456")
    line = _format("ouverture de http://127.0.0.1:8756/?lt=%s", "nonce-abcdef123456")
    assert "nonce-abcdef123456" not in line
    assert secrets_store.REDACTED in line


def test_home_directory_becomes_a_tilde(monkeypatch):
    """Le chemin du dossier personnel porte le nom de la session."""
    monkeypatch.setattr(secrets_store, "_HOME", "/Users/prenom")
    line = _format("Import impossible : %s", "/Users/prenom/Documents/cours.pdf")
    assert line == "Import impossible : ~/Documents/cours.pdf"


def test_traceback_is_redacted_too(monkeypatch):
    """Un filtre ne voit que le message : la trace, qui cite des chemins et
    parfois le secret lui-même, passerait en clair."""
    monkeypatch.setattr(secrets_store, "_HOME", "/Users/prenom")
    monkeypatch.setattr(secrets_store, "_known_secrets", {"jeton-secret-0001"})
    try:
        raise OSError("lecture de /Users/prenom/notes.pdf avec jeton-secret-0001")
    except OSError as exc:
        line = _format("échec", exc=exc)
    assert "/Users/prenom" not in line
    assert "jeton-secret-0001" not in line
    assert "~/notes.pdf" in line


def test_a_root_home_is_left_alone(monkeypatch):
    monkeypatch.setattr(secrets_store, "_HOME", "/")
    assert _format("chemin %s", "/etc/hosts") == "chemin /etc/hosts"

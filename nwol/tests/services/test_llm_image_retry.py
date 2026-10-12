# Un appel avec image qui échoue est rejoué sans image — et le journal dit
# pourquoi. Il écrivait « Ollama a refusé les images » même quand Ollama avait
# interrompu un modèle qui répétait le même texte en boucle.
import logging

from llm import ollama_client

REPEAT = 'Ollama HTTP 500: {"error":"prediction aborted, token repeat limit reached"}'


def test_reason_names_the_real_cause():
    assert "répéter" in ollama_client._image_retry_reason(RuntimeError(REPEAT))
    overflow = RuntimeError('Ollama HTTP 400: {"error":"exceed_context_size_error"}')
    assert "contexte" in ollama_client._image_retry_reason(overflow)
    assert "HTTP 502" in ollama_client._image_retry_reason(RuntimeError("Ollama HTTP 502: bad gateway"))


def test_repeat_limit_with_an_image_is_retried_without_it(monkeypatch, caplog):
    calls: list[int] = []

    def fake_call(prompt, model, images=None, options=None, format_json=True, task=""):
        calls.append(len(images or []))
        if images:
            raise RuntimeError(REPEAT)
        return '{"ok": true}'

    monkeypatch.setattr(ollama_client, "_load_ollama_images", lambda paths: ["image-en-base64"])
    monkeypatch.setattr(ollama_client, "_call_ollama", fake_call)

    with caplog.at_level(logging.WARNING, logger="LLM"):
        result = ollama_client._generate_json(
            "question", "prompt", lambda raw: {"ok": True}, model="m", image_paths=["page.png"]
        )

    assert result == {"ok": True}
    assert calls == [1, 0]
    assert "répéter" in caplog.text
    assert "refusé" not in caplog.text

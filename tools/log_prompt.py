"""Hook UserPromptSubmit do Claude Code: acrescenta cada prompt a ia_log/prompts.md.

Exigência do enunciado (7.2.3.a): log dos prompts utilizados.
Recebe JSON no stdin com os campos "prompt" e "session_id". Nunca bloqueia o prompt.
"""
import json
import os
import sys
from datetime import datetime
from pathlib import Path


def main() -> None:
    try:
        dados = json.load(sys.stdin)
    except Exception:
        return
    prompt = (dados.get("prompt") or "").strip()
    if not prompt:
        return
    raiz = Path(os.environ.get("CLAUDE_PROJECT_DIR") or Path(__file__).resolve().parent.parent)
    log = raiz / "ia_log" / "prompts.md"
    log.parent.mkdir(parents=True, exist_ok=True)
    novo = not log.exists()
    with log.open("a", encoding="utf-8") as f:
        if novo:
            f.write("# Log de prompts (gerado automaticamente pelo hook)\n\n")
        quando = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        sessao = (dados.get("session_id") or "")[:8]
        f.write(f"## {quando} · sessão {sessao}\n\n{prompt}\n\n---\n\n")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass  # o log nunca pode impedir o uso do Claude Code
    sys.exit(0)

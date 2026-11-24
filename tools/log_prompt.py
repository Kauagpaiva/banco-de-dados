"""Hook UserPromptSubmit do Claude Code: acrescenta cada prompt a ia_log/prompts/<autor>.md.

Exigência do enunciado (7.2.3.a): log dos prompts utilizados.
Um arquivo por integrante (evita conflito de merge). Autor = variável BANCADA_AUTOR ou,
na falta dela, `git config user.name`. Recebe JSON no stdin com "prompt" e "session_id".
Nunca bloqueia o prompt.
"""
import json
import os
import re
import subprocess
import sys
import unicodedata
from datetime import datetime
from pathlib import Path


def _slug(texto: str) -> str:
    sem_acento = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", sem_acento.lower()).strip("-") or "desconhecido"


def _autor(raiz: Path) -> str:
    nome = os.environ.get("BANCADA_AUTOR")
    if not nome:
        try:
            nome = subprocess.run(["git", "config", "user.name"], cwd=raiz, capture_output=True,
                                  text=True, timeout=5).stdout.strip()
        except Exception:
            nome = ""
    return _slug(nome or "desconhecido")


def _branch(raiz: Path) -> str:
    try:
        return subprocess.run(["git", "branch", "--show-current"], cwd=raiz, capture_output=True,
                              text=True, timeout=5).stdout.strip()
    except Exception:
        return ""


def main() -> None:
    try:
        dados = json.load(sys.stdin)
    except Exception:
        return
    prompt = (dados.get("prompt") or "").strip()
    if not prompt:
        return
    raiz = Path(os.environ.get("CLAUDE_PROJECT_DIR") or Path(__file__).resolve().parent.parent)
    autor = _autor(raiz)
    log = raiz / "ia_log" / "prompts" / f"{autor}.md"
    log.parent.mkdir(parents=True, exist_ok=True)
    novo = not log.exists()
    with log.open("a", encoding="utf-8") as f:
        if novo:
            f.write(f"# Log de prompts — {autor} (gerado automaticamente pelo hook)\n\n")
        quando = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        sessao = (dados.get("session_id") or "")[:8]
        f.write(f"## {quando} · branch {_branch(raiz)} · sessão {sessao}\n\n{prompt}\n\n---\n\n")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass  # o log nunca pode impedir o uso do Claude Code
    sys.exit(0)

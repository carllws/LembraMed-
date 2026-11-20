"""Notificação push via ntfy (https://ntfy.sh) — sem dependências extras.

Cada usuário informa o seu próprio tópico na aba "Perfil" da tela.
Quem souber o nome do tópico consegue ler as mensagens, por isso o app sugere
nomes aleatórios e o push leva só nome e dosagem do remédio.
"""
import json
import os
import urllib.request

SERVIDOR = os.environ.get("NTFY_SERVIDOR", "https://ntfy.sh")


def enviar(topico, titulo, mensagem, prioridade=4):
    """Envia o push (JSON, aceita acentos). True se deu certo; False se não há
    tópico ou se falhou (o agendador tenta de novo no próximo ciclo)."""
    if not topico:
        return False
    corpo = json.dumps({
        "topic": topico,
        "title": titulo,
        "message": mensagem,
        "priority": prioridade,
        "tags": ["pill", "alarm_clock"],
    }).encode("utf-8")
    req = urllib.request.Request(
        SERVIDOR, data=corpo, method="POST",
        headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return 200 <= resp.status < 300
    except Exception as e:
        print("Falha ao enviar push:", e)
        return False

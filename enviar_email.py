"""Envio de e-mail (recuperação de senha) via SMTP, configurado por variáveis de ambiente.

SMTP_HOST, SMTP_PORT (587), SMTP_USUARIO, SMTP_SENHA, SMTP_DE.
Sem SMTP_HOST (uso local), o link é só impresso no console do servidor.
"""
import os
import smtplib
from email.message import EmailMessage


def enviar(destino, assunto, texto):
    host = os.environ.get("SMTP_HOST")
    if not host:
        print(f"[e-mail não configurado] Para: {destino}\n{assunto}\n{texto}")
        return False
    msg = EmailMessage()
    msg["From"] = os.environ.get("SMTP_DE", os.environ.get("SMTP_USUARIO", "lembramed@localhost"))
    msg["To"], msg["Subject"] = destino, assunto
    msg.set_content(texto)
    try:
        with smtplib.SMTP(host, int(os.environ.get("SMTP_PORT", "587")), timeout=15) as srv:
            srv.starttls()
            if os.environ.get("SMTP_USUARIO"):
                srv.login(os.environ["SMTP_USUARIO"], os.environ.get("SMTP_SENHA", ""))
            srv.send_message(msg)
        return True
    except Exception as e:
        print("Falha ao enviar e-mail:", e)
        return False

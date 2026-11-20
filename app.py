"""API (Flask) + agendador em segundo plano do LembraMed!.

Rodar:  python app.py      (http://127.0.0.1:5000)
"""
import os
import secrets
import threading
import time
from datetime import datetime, timedelta
from functools import wraps
from pathlib import Path

from markupsafe import escape
from flask import Flask, g, jsonify, request, send_from_directory, session

import db
import enviar_email
import notificacao
import servico as s

INTERVALO_AGENDADOR_S = 30
MAX_FALHAS_LOGIN = 5
BLOQUEIO_LOGIN_S = 60


def avisar_pendentes(conn, enviar=notificacao.enviar, agora=None):
    """Envia o push de cada alarme que precisa de aviso, para o tópico de cada usuário.
    Só marca como avisado se o envio funcionou; se falhar, tenta de novo no próximo ciclo."""
    for a in s.avisos_a_enviar(conn, agora):
        dose = f" — {a['dosagem']}" if a["dosagem"] else ""
        if enviar(a["ntfy_topico"], "LembraMed! 💊 Hora do remédio", f"{a['nome']}{dose} ({a['hora']})"):
            s.marcar_avisado(conn, a["id"], agora)
    for a in s.avisos_estoque(conn):
        if enviar(a["ntfy_topico"], "LembraMed! 📦 Estoque baixo",
                  f"Restam {a['estoque']} de {a['nome']}. Hora de repor."):
            s.marcar_estoque_avisado(conn, a["id"])
    for a in s.avisos_cuidador(conn, agora):
        dose = f" — {a['dosagem']}" if a["dosagem"] else ""
        if enviar(a["cuidador_topico"], "LembraMed! ⚠️ Dose perdida",
                  f"{a['usuario']} não confirmou {a['nome']}{dose} das {a['hora']}.", 5):
            s.marcar_cuidador_avisado(conn, a["id"], agora)


def _loop_agendador(caminho_db, parar):
    """Verifica a cada 30 s se algum horário chegou, gera o alarme e manda o push."""
    while not parar.is_set():
        try:
            with db.conectar(caminho_db) as conn:
                s.gerar_alarmes(conn)
                avisar_pendentes(conn)
        except Exception as e:  # o agendador nunca deve morrer
            print("Erro no agendador:", e)
        parar.wait(INTERVALO_AGENDADOR_S)


class LimitadorLogin:
    """Bloqueia por 60 s depois de 5 tentativas erradas (por e-mail + IP)."""

    def __init__(self, agora=time.time):
        self._agora = agora
        self._falhas = {}
        self._lock = threading.Lock()

    def segundos_bloqueado(self, chave):
        with self._lock:
            n, ate = self._falhas.get(chave, (0, 0))
            return max(0, int(ate - self._agora()) + 1) if ate > self._agora() else 0

    def falhou(self, chave):
        with self._lock:
            n, ate = self._falhas.get(chave, (0, 0))
            n += 1
            if n >= MAX_FALHAS_LOGIN:
                n, ate = 0, self._agora() + BLOQUEIO_LOGIN_S
            self._falhas[chave] = (n, ate)

    def acertou(self, chave):
        with self._lock:
            self._falhas.pop(chave, None)


def _chave_secreta(caminho_db):
    """Chave que assina o cookie de sessão: variável de ambiente ou arquivo .segredo."""
    if os.environ.get("SECRET_KEY"):
        return os.environ["SECRET_KEY"]
    arq = Path(caminho_db).with_name(".segredo")
    if not arq.exists():
        arq.write_text(secrets.token_hex(32))
    return arq.read_text().strip()


def create_app(caminho_db=None, iniciar_agendador=True, enviar=notificacao.enviar):
    caminho_db = caminho_db or db.DB_PADRAO
    db.iniciar(caminho_db)
    app = Flask(__name__)
    app.json.ensure_ascii = False
    app.secret_key = _chave_secreta(caminho_db)
    app.config.update(SESSION_COOKIE_SAMESITE="Lax", SESSION_COOKIE_HTTPONLY=True,
                      PERMANENT_SESSION_LIFETIME=timedelta(days=14))
    if os.environ.get("COOKIE_SECURE") == "1" or os.environ.get("BASE_URL", "").startswith("https://"):
        app.config["SESSION_COOKIE_SECURE"] = True      # cookie só trafega por HTTPS
    if os.environ.get("TRUST_PROXY") == "1":            # atrás do proxy do serviço de hospedagem
        from werkzeug.middleware.proxy_fix import ProxyFix
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1)
    limitador = LimitadorLogin()

    def com_conexao(fn):
        with db.conectar(caminho_db) as conn:
            return fn(conn)

    def login_obrigatorio(fn):
        @wraps(fn)
        def interno(*args, **kwargs):
            uid = session.get("usuario_id")
            if uid:
                try:
                    g.usuario = com_conexao(lambda c: s.obter_usuario(c, uid))
                except s.NaoEncontrado:
                    session.clear()
                    uid = None
            if not uid:
                raise s.ErroAutenticacao("Faça login para continuar.")
            return fn(g.usuario["id"], *args, **kwargs)
        return interno

    @app.errorhandler(s.ErroValidacao)
    def _validacao(e):
        return jsonify(erro=str(e)), 400

    @app.errorhandler(s.ErroAutenticacao)
    def _autenticacao(e):
        return jsonify(erro=str(e)), 401

    @app.errorhandler(s.NaoEncontrado)
    def _nao_encontrado(e):
        return jsonify(erro=str(e)), 404

    @app.errorhandler(s.ErroConflito)
    def _conflito(e):
        return jsonify(erro=str(e)), 409

    def _entrar(usuario):
        session.clear()
        session.permanent = True
        session["usuario_id"] = usuario["id"]

    # ---------- página ----------
    @app.get("/")
    def pagina_inicial():
        resp = send_from_directory(Path(__file__).parent / "static", "index.html")
        resp.headers["Cache-Control"] = "no-store"
        return resp

    # ---------- PWA ----------
    @app.get("/sw.js")
    def service_worker():
        resp = send_from_directory(Path(__file__).parent / "static", "sw.js", mimetype="application/javascript")
        resp.headers["Cache-Control"] = "no-cache"
        resp.headers["Service-Worker-Allowed"] = "/"
        return resp

    @app.get("/manifest.webmanifest")
    def manifesto():
        return send_from_directory(Path(__file__).parent / "static", "manifest.webmanifest",
                                   mimetype="application/manifest+json")

    # ---------- conta ----------
    @app.post("/api/cadastro")
    def cadastro():
        d = request.get_json(silent=True) or {}
        u = com_conexao(lambda c: s.cadastrar_usuario(c, d.get("nome"), d.get("email"), d.get("senha")))
        _entrar(u)
        return jsonify(u), 201

    @app.post("/api/login")
    def login():
        d = request.get_json(silent=True) or {}
        chave = ((d.get("email") or "").strip().lower(), request.remote_addr)
        espera = limitador.segundos_bloqueado(chave)
        if espera:
            return jsonify(erro=f"Muitas tentativas. Tente de novo em {espera} segundos."), 429
        try:
            u = com_conexao(lambda c: s.autenticar(c, d.get("email"), d.get("senha")))
        except s.ErroAutenticacao:
            limitador.falhou(chave)
            raise
        limitador.acertou(chave)
        _entrar(u)
        return jsonify(u)

    @app.post("/api/logout")
    def logout():
        session.clear()
        return "", 204

    @app.get("/api/eu")
    @login_obrigatorio
    def eu(uid):
        return jsonify(g.usuario)

    @app.put("/api/eu")
    @login_obrigatorio
    def atualizar_eu(uid):
        d = request.get_json(silent=True) or {}
        return jsonify(com_conexao(lambda c: s.definir_topico(c, uid, d.get("ntfy_topico"))))

    @app.put("/api/eu/som")
    @login_obrigatorio
    def atualizar_som(uid):
        d = request.get_json(silent=True) or {}
        return jsonify(com_conexao(lambda c: s.definir_prefs_som(c, uid, d)))

    @app.put("/api/eu/cuidador")
    @login_obrigatorio
    def atualizar_cuidador(uid):
        d = request.get_json(silent=True) or {}
        return jsonify(com_conexao(lambda c: s.definir_cuidador(c, uid, d.get("cuidador_topico"))))

    @app.put("/api/medicamentos/<int:mid>/estoque")
    @login_obrigatorio
    def atualizar_estoque(uid, mid):
        d = request.get_json(silent=True) or {}
        com_conexao(lambda c: s.definir_estoque(c, uid, mid, d.get("estoque"), d.get("aviso", 5)))
        return "", 204

    def _endereco_do_app():
        """Endereço público do app para montar links de e-mail.

        Vem da variável BASE_URL (ex.: https://lembramed.exemplo.com). O cabeçalho Host da
        requisição pode ser forjado por quem faz o pedido, então só é aceito em localhost.
        """
        base = os.environ.get("BASE_URL", "").strip().rstrip("/")
        if base:
            return base
        if request.host.split(":")[0] in ("localhost", "127.0.0.1", "[::1]"):
            return request.host_url.rstrip("/")
        return None

    @app.post("/api/esqueci-senha")
    def esqueci_senha():
        d = request.get_json(silent=True) or {}
        chave = ("reset", (d.get("email") or "").strip().lower(), request.remote_addr)
        if limitador.segundos_bloqueado(chave):
            return jsonify(erro="Muitas tentativas. Aguarde um minuto."), 429
        limitador.falhou(chave)  # conta cada pedido; 5 pedidos seguidos bloqueiam por 60 s
        r = com_conexao(lambda c: s.criar_token_reset(c, d.get("email")))
        if r:
            u, token = r
            base = _endereco_do_app()
            if base:
                link = base + "/#redefinir=" + token
                enviar_email.enviar(u["email"], "LembraMed! — redefinir senha",
                                    f"Olá, {u['nome']}!\n\nPara criar uma nova senha, abra:\n{link}\n\n"
                                    f"O link vale por {s.RESET_VALIDADE_MIN} minutos. "
                                    "Se não foi você, ignore este e-mail.")
            else:
                print("BASE_URL não definida: e-mail de redefinição NÃO enviado "
                      "(o endereço da requisição não é confiável).")
        # resposta igual com ou sem conta, para não revelar quais e-mails existem
        return jsonify(ok=True, mensagem="Se o e-mail existir, enviamos o link para redefinir a senha.")

    @app.post("/api/redefinir-senha")
    def redefinir_senha():
        d = request.get_json(silent=True) or {}
        com_conexao(lambda c: s.redefinir_senha(c, d.get("token"), d.get("senha")))
        return jsonify(ok=True)

    @app.get("/api/historico/imprimir")
    @login_obrigatorio
    def historico_imprimir(uid):
        dias = max(1, min(request.args.get("dias", 30, type=int), 365))
        linhas = com_conexao(lambda c: s.historico(c, uid, dias))
        nomes = {"tomado": "Tomado", "perdido": "Perdido", "pendente": "Pendente"}
        corpo = "".join(
            f"<tr><td>{escape(r['data_prevista'])}</td><td>{escape(r['hora'])}</td>"
            f"<td>{escape(r['nome'])} {escape(r['dosagem'] or '')}</td><td>{nomes.get(r['status'], '')}</td></tr>"
            for r in linhas)
        tomadas = sum(r["status"] == "tomado" for r in linhas)
        html = (f"<!doctype html><meta charset=utf-8><title>Histórico LembraMed!</title>"
                "<style>body{font:14px sans-serif;margin:24px}table{border-collapse:collapse;width:100%}"
                "td,th{border:1px solid #999;padding:4px 8px;text-align:left}</style>"
                f"<h1>Histórico de remédios — {escape(g.usuario['nome'])}</h1>"
                f"<p>Últimos {dias} dias · {tomadas} tomadas de {len(linhas)} doses.</p>"
                f"<table><tr><th>Data</th><th>Hora</th><th>Remédio</th><th>Situação</th></tr>{corpo}</table>"
                "<p><small>Ferramenta de lembrete; não substitui orientação médica. "
                "Use Imprimir → Salvar como PDF.</small></p><script>window.print()</script>")
        resp = app.response_class(html, mimetype="text/html")
        resp.headers["Cache-Control"] = "no-store"
        return resp

    @app.post("/api/eu/teste-push")
    @login_obrigatorio
    def teste_push(uid):
        topico = g.usuario["ntfy_topico"]
        if not topico:
            raise s.ErroValidacao("Salve um tópico antes de testar.")
        if not enviar(topico, "Teste do LembraMed! 💊", "Se você viu isto, o push está funcionando!"):
            return jsonify(erro="Não consegui enviar. Verifique sua internet e o nome do tópico."), 502
        return jsonify(ok=True)

    # ---------- remédios ----------
    @app.get("/medicamentos")
    @login_obrigatorio
    def listar(uid):
        return jsonify(com_conexao(lambda c: s.listar_medicamentos(c, uid)))

    def _guardar_estoque(uid, mid, d):
        if d.get("estoque") not in (None, ""):
            com_conexao(lambda c: s.definir_estoque(c, uid, mid, d.get("estoque"), d.get("estoque_aviso", 5)))

    @app.post("/medicamentos")
    @login_obrigatorio
    def criar(uid):
        d = request.get_json(silent=True) or {}
        horarios = d.get("horarios", [])
        dias = d.get("dias_semana", "0123456")

        if d.get("intervalo_horas"):  # cronograma "a cada X horas"
            mid = com_conexao(lambda c: s.criar_cronograma_intervalo(
                c, uid, d.get("nome"), d.get("dosagem"), d.get("observacoes"),
                d.get("intervalo_horas"), d.get("primeira_dose"), d.get("dias")))
            _guardar_estoque(uid, mid, d)
            return jsonify(id=mid), 201

        def f(c):
            mid = s.criar_medicamento(c, uid, d.get("nome"), d.get("dosagem"), d.get("observacoes"),
                                      d.get("data_inicio"), d.get("data_fim"))
            for hr in horarios:
                s.adicionar_horario(c, uid, mid, hr, dias)
            return mid
        mid = com_conexao(f)
        _guardar_estoque(uid, mid, d)
        return jsonify(id=mid), 201

    @app.delete("/medicamentos/<int:mid>")
    @login_obrigatorio
    def remover(uid, mid):
        com_conexao(lambda c: s.desativar_medicamento(c, uid, mid))
        return "", 204

    @app.post("/medicamentos/<int:mid>/horarios")
    @login_obrigatorio
    def novo_horario(uid, mid):
        d = request.get_json(silent=True) or {}
        hid = com_conexao(lambda c: s.adicionar_horario(
            c, uid, mid, d.get("hora"), d.get("dias_semana", "0123456")))
        return jsonify(id=hid), 201

    @app.delete("/horarios/<int:hid>")
    @login_obrigatorio
    def remover_hor(uid, hid):
        com_conexao(lambda c: s.remover_horario(c, uid, hid))
        return "", 204

    @app.get("/api/dashboard")
    @login_obrigatorio
    def dashboard(uid):
        return jsonify(com_conexao(lambda c: s.dashboard(c, uid)))

    # ---------- alarmes ----------
    @app.get("/alarmes/pendentes")
    @login_obrigatorio
    def pendentes(uid):
        def f(c):
            s.gerar_alarmes(c)  # não depende só do intervalo do agendador
            return s.alarmes_pendentes(c, uid)
        return jsonify(com_conexao(f))

    @app.post("/registros/<int:rid>/tomado")
    @login_obrigatorio
    def tomado(uid, rid):
        com_conexao(lambda c: s.marcar_tomado(c, uid, rid))
        return jsonify(ok=True)

    @app.post("/registros/<int:rid>/adiar")
    @login_obrigatorio
    def adiar(uid, rid):
        d = request.get_json(silent=True) or {}
        ate = com_conexao(lambda c: s.adiar(c, uid, rid, d.get("minutos", 10)))
        return jsonify(adiado_ate=ate)

    @app.get("/historico")
    @login_obrigatorio
    def hist(uid):
        dias = max(1, min(request.args.get("dias", 30, type=int), 365))
        return jsonify(com_conexao(lambda c: s.historico(c, uid, dias)))

    if iniciar_agendador:
        parar = threading.Event()
        threading.Thread(target=_loop_agendador, args=(caminho_db, parar), daemon=True).start()
        app.config["parar_agendador"] = parar
    return app


if __name__ == "__main__":
    import os
    host = os.environ.get("HOST", "127.0.0.1")
    porta = int(os.environ.get("PORT", "5000"))
    try:
        from waitress import serve  # servidor de produção
        serve(create_app(), host=host, port=porta)
    except ImportError:
        create_app().run(host=host, port=porta, debug=False)

"""Regras de negócio: usuários, cadastro de remédios, alarmes, confirmação e histórico.

Toda função que mexe em dados de alguém recebe `usuario_id` e só enxerga o que
pertence a esse usuário.
"""
import hashlib
import json
import re
import secrets
import sqlite3
from datetime import date, datetime, timedelta

from werkzeug.security import check_password_hash, generate_password_hash

TOLERANCIA_MIN = 120    # alarmes mais atrasados que isso já nascem como "perdido"
REPETIR_AVISO_MIN = 10  # repete a notificação até você confirmar
MAX_DOSES = 2000        # limite de doses de um cronograma por intervalo
_HASH = "pbkdf2:sha256"
_HORA_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_TOPICO_RE = re.compile(r"^[A-Za-z0-9_-]{6,64}$")
_HASH_FALSO = generate_password_hash("senha-falsa", method=_HASH)


class ErroValidacao(ValueError):
    pass


class NaoEncontrado(LookupError):
    pass


class ErroAutenticacao(Exception):
    pass


class ErroConflito(Exception):
    pass


# ---------- usuários ----------
def _publico(u):
    try:
        prefs = json.loads(u["prefs_som"]) if u["prefs_som"] else {}
    except (ValueError, TypeError):
        prefs = {}
    return {"id": u["id"], "nome": u["nome"], "email": u["email"],
            "ntfy_topico": u["ntfy_topico"], "prefs_som": prefs,
            "cuidador_topico": u["cuidador_topico"]}


def cadastrar_usuario(conn, nome, email, senha):
    nome = (nome or "").strip()
    email = (email or "").strip().lower()
    senha = senha or ""
    if not nome:
        raise ErroValidacao("Informe seu nome.")
    if len(nome) > 80:
        raise ErroValidacao("O nome é muito longo.")
    if not _EMAIL_RE.match(email) or len(email) > 120:
        raise ErroValidacao("Informe um e-mail válido.")
    if len(senha) < 8:
        raise ErroValidacao("A senha precisa ter pelo menos 8 caracteres.")
    if len(senha) > 128:
        raise ErroValidacao("A senha é muito longa (máximo 128 caracteres).")
    try:
        with conn:
            primeiro = conn.execute("SELECT COUNT(*) FROM usuarios").fetchone()[0] == 0
            cur = conn.execute(
                "INSERT INTO usuarios (nome, email, senha_hash) VALUES (?, ?, ?)",
                (nome, email, generate_password_hash(senha, method=_HASH)))
            if primeiro:  # adota remédios criados antes de existir login
                conn.execute("UPDATE medicamentos SET usuario_id = ? WHERE usuario_id IS NULL",
                             (cur.lastrowid,))
    except sqlite3.IntegrityError:
        raise ErroConflito("Já existe uma conta com esse e-mail.")
    return obter_usuario(conn, cur.lastrowid)


def autenticar(conn, email, senha):
    email = (email or "").strip().lower()
    u = conn.execute("SELECT * FROM usuarios WHERE email = ?", (email,)).fetchone()
    # roda a verificação mesmo se o e-mail não existe (tempo parecido nos dois casos)
    ok = check_password_hash(u["senha_hash"] if u else _HASH_FALSO, senha or "")
    if not u or not ok:
        raise ErroAutenticacao("E-mail ou senha incorretos.")
    return _publico(u)


def obter_usuario(conn, usuario_id):
    u = conn.execute("SELECT * FROM usuarios WHERE id = ?", (usuario_id,)).fetchone()
    if not u:
        raise NaoEncontrado("Usuário não encontrado.")
    return _publico(u)


def definir_topico(conn, usuario_id, topico):
    topico = (topico or "").strip() or None  # vazio = desligar o push
    if topico and not _TOPICO_RE.match(topico):
        raise ErroValidacao("O tópico deve ter de 6 a 64 caracteres: letras, números, - ou _.")
    with conn:
        conn.execute("UPDATE usuarios SET ntfy_topico = ? WHERE id = ?", (topico, usuario_id))
    return obter_usuario(conn, usuario_id)


def definir_prefs_som(conn, usuario_id, prefs):
    """Guarda na conta as escolhas de som (valem em qualquer aparelho)."""
    if not isinstance(prefs, dict):
        raise ErroValidacao("Preferências inválidas.")
    ok = {}
    for k, v in prefs.items():
        if not isinstance(k, str) or len(k) > 40 or not isinstance(v, (str, int, float, bool)):
            raise ErroValidacao("Preferências inválidas.")
        ok[k] = v
    txt = json.dumps(ok, ensure_ascii=False)
    if len(txt) > 2000:
        raise ErroValidacao("Preferências grandes demais.")
    with conn:
        conn.execute("UPDATE usuarios SET prefs_som = ? WHERE id = ?", (txt, usuario_id))
    return obter_usuario(conn, usuario_id)


def definir_cuidador(conn, usuario_id, topico):
    topico = (topico or "").strip() or None  # vazio = desligar
    if topico and not _TOPICO_RE.match(topico):
        raise ErroValidacao("O tópico deve ter de 6 a 64 caracteres: letras, números, - ou _.")
    with conn:
        conn.execute("UPDATE usuarios SET cuidador_topico = ? WHERE id = ?", (topico, usuario_id))
    return obter_usuario(conn, usuario_id)


# ---------- recuperação de senha ----------
RESET_VALIDADE_MIN = 30


def _hash_token(token):
    return hashlib.sha256(token.encode()).hexdigest()


def criar_token_reset(conn, email, agora=None):
    """Devolve (usuario, token) ou None se o e-mail não existe (quem chama responde igual nos dois casos)."""
    agora = agora or datetime.now()
    u = conn.execute("SELECT * FROM usuarios WHERE email = ?", ((email or "").strip().lower(),)).fetchone()
    if not u:
        return None
    token = secrets.token_urlsafe(32)
    with conn:
        conn.execute("UPDATE reset_senha SET usado = 1 WHERE usuario_id = ?", (u["id"],))
        conn.execute("INSERT INTO reset_senha (usuario_id, token_hash, expira_em) VALUES (?, ?, ?)",
                     (u["id"], _hash_token(token),
                      (agora + timedelta(minutes=RESET_VALIDADE_MIN)).isoformat(timespec="seconds")))
    return _publico(u), token


def redefinir_senha(conn, token, nova_senha, agora=None):
    agora = agora or datetime.now()
    nova_senha = nova_senha or ""
    if len(nova_senha) < 8:
        raise ErroValidacao("A senha precisa ter pelo menos 8 caracteres.")
    if len(nova_senha) > 128:
        raise ErroValidacao("A senha é muito longa (máximo 128 caracteres).")
    r = conn.execute("SELECT * FROM reset_senha WHERE token_hash = ?", (_hash_token(token or ""),)).fetchone()
    if not r or r["usado"] or r["expira_em"] < agora.isoformat(timespec="seconds"):
        raise ErroValidacao("Link inválido ou expirado. Peça um novo.")
    with conn:
        conn.execute("UPDATE usuarios SET senha_hash = ? WHERE id = ?",
                     (generate_password_hash(nova_senha, method=_HASH), r["usuario_id"]))
        conn.execute("UPDATE reset_senha SET usado = 1 WHERE usuario_id = ?", (r["usuario_id"],))


# ---------- estoque ----------
def definir_estoque(conn, usuario_id, med_id, estoque, aviso=5):
    try:
        estoque = None if estoque in (None, "") else int(estoque)
        aviso = int(aviso)
    except (TypeError, ValueError):
        raise ErroValidacao("Estoque inválido.")
    if (estoque is not None and not 0 <= estoque <= 100000) or not 0 <= aviso <= 1000:
        raise ErroValidacao("Estoque inválido.")
    with conn:
        cur = conn.execute(
            "UPDATE medicamentos SET estoque = ?, estoque_aviso = ?, estoque_avisado = 0 "
            "WHERE id = ? AND usuario_id = ?", (estoque, aviso, med_id, usuario_id))
    if cur.rowcount == 0:
        raise NaoEncontrado("Remédio não encontrado.")


def avisos_estoque(conn):
    rows = conn.execute(
        """SELECT m.id, m.nome, m.estoque, u.ntfy_topico FROM medicamentos m
             JOIN usuarios u ON u.id = m.usuario_id
            WHERE m.ativo = 1 AND m.estoque IS NOT NULL AND m.estoque <= m.estoque_aviso
              AND m.estoque_avisado = 0 AND u.ntfy_topico IS NOT NULL""").fetchall()
    return [dict(r) for r in rows]


def marcar_estoque_avisado(conn, med_id):
    with conn:
        conn.execute("UPDATE medicamentos SET estoque_avisado = 1 WHERE id = ?", (med_id,))


# ---------- cuidador ----------
def avisos_cuidador(conn, agora=None):
    """Doses perdidas (de ontem em diante) cujo cuidador ainda não foi avisado."""
    agora = agora or datetime.now()
    desde = (agora.date() - timedelta(days=1)).isoformat()
    rows = conn.execute(
        """SELECT r.id, u.nome AS usuario, u.cuidador_topico, m.nome, m.dosagem, h.hora
             FROM registros r
             JOIN horarios h ON h.id = r.horario_id
             JOIN medicamentos m ON m.id = h.medicamento_id
             JOIN usuarios u ON u.id = m.usuario_id
            WHERE r.status = 'perdido' AND r.aviso_cuidador IS NULL
              AND u.cuidador_topico IS NOT NULL AND r.data_prevista >= ?""", (desde,)).fetchall()
    return [dict(r) for r in rows]


def marcar_cuidador_avisado(conn, registro_id, agora=None):
    agora = agora or datetime.now()
    with conn:
        conn.execute("UPDATE registros SET aviso_cuidador = ? WHERE id = ?",
                     (agora.isoformat(timespec="seconds"), registro_id))


# ---------- cadastro de remédios ----------
def _parse_data(valor, campo):
    if valor in (None, ""):
        return None
    try:
        return date.fromisoformat(valor)
    except (TypeError, ValueError):
        raise ErroValidacao(f"{campo} inválida. Use o formato AAAA-MM-DD.")


def criar_medicamento(conn, usuario_id, nome, dosagem=None, observacoes=None,
                      data_inicio=None, data_fim=None, agora=None):
    """Cria o remédio. Sem data_fim = uso contínuo; com data_fim e sem data_inicio,
    o tratamento começa hoje."""
    nome = (nome or "").strip()
    if not nome:
        raise ErroValidacao("O nome do medicamento é obrigatório.")
    ini = _parse_data(data_inicio, "A data de início")
    fim = _parse_data(data_fim, "A data final")
    if fim and not ini:
        ini = (agora or datetime.now()).date()
    if ini and fim and fim < ini:
        raise ErroValidacao("A data final não pode ser antes da data de início.")
    if ini and fim and (fim - ini).days > 730:
        raise ErroValidacao("O tratamento pode ter no máximo 2 anos.")
    with conn:
        cur = conn.execute(
            "INSERT INTO medicamentos (usuario_id, nome, dosagem, observacoes, data_inicio, data_fim) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (usuario_id, nome, dosagem, observacoes,
             ini.isoformat() if ini else None, fim.isoformat() if fim else None))
    return cur.lastrowid


def _inserir_dose(conn, med_id, previsto):
    """Cada dose de um cronograma por intervalo vira um horário de dia único."""
    conn.execute(
        "INSERT INTO horarios (medicamento_id, hora, dias_semana, data_unica, criado_em) "
        "VALUES (?, ?, '0123456', ?, ?)",
        (med_id, previsto.strftime("%H:%M"), previsto.date().isoformat(),
         previsto.isoformat(timespec="seconds")))


def _estender(conn, med_id, prim, x, agora):
    """Garante as doses de um cronograma contínuo até 72 h à frente."""
    horizonte = agora + timedelta(hours=72)
    ultimo = conn.execute(
        "SELECT MAX(data_unica || 'T' || hora) FROM horarios WHERE medicamento_id = ?",
        (med_id,)).fetchone()[0]
    k = 0 if not ultimo else round(
        (datetime.fromisoformat(ultimo + ":00") - prim).total_seconds() / 3600 / x) + 1
    while prim + timedelta(hours=x * k) <= horizonte:
        _inserir_dose(conn, med_id, prim + timedelta(hours=x * k))
        k += 1


def calcular_doses(primeira_dose, intervalo_horas, quantidade):
    """Calcula os horários: a primeira dose e as seguintes, de X em X horas."""
    return [primeira_dose + timedelta(hours=intervalo_horas * k) for k in range(quantidade)]


def criar_cronograma_intervalo(conn, usuario_id, nome, dosagem=None, observacoes=None,
                               intervalo_horas=None, primeira_dose=None, dias=None, agora=None):
    """Cria um cronograma "a cada X horas" (X de 1 a 12). Sem `dias` = uso contínuo."""
    agora = agora or datetime.now()
    nome = (nome or "").strip()
    if not nome:
        raise ErroValidacao("O nome do medicamento é obrigatório.")
    try:
        x = int(intervalo_horas)
    except (TypeError, ValueError):
        raise ErroValidacao("Informe o intervalo em horas (de 1 a 12).")
    if not 1 <= x <= 12:
        raise ErroValidacao("O intervalo deve ser de 1 a 12 horas.")
    try:
        prim = datetime.fromisoformat(primeira_dose).replace(second=0, microsecond=0)
    except (TypeError, ValueError):
        raise ErroValidacao("Informe a data e a hora da primeira dose.")
    if prim < agora - timedelta(minutes=30):
        raise ErroValidacao("A primeira dose não pode estar no passado. "
                            "Se você já tomou, informe o horário da próxima.")
    if prim > agora + timedelta(days=30):
        raise ErroValidacao("A primeira dose deve ser nos próximos 30 dias.")
    total = None
    if dias not in (None, ""):
        try:
            n = int(dias)
        except (TypeError, ValueError):
            raise ErroValidacao("Informe a duração em dias.")
        if not 1 <= n <= 365:
            raise ErroValidacao("A duração deve ser de 1 a 365 dias.")
        total = -(-n * 24 // x)  # arredonda para cima: doses que cabem em n dias
        if total > MAX_DOSES:
            raise ErroValidacao(f"Esse cronograma teria {total} doses (máximo {MAX_DOSES}). "
                                "Reduza a duração ou aumente o intervalo.")
    ultima = calcular_doses(prim, x, total)[-1] if total else None
    with conn:
        cur = conn.execute(
            "INSERT INTO medicamentos (usuario_id, nome, dosagem, observacoes, data_inicio, data_fim, "
            "intervalo_horas, primeira_dose) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (usuario_id, nome, dosagem, observacoes, prim.date().isoformat(),
             ultima.date().isoformat() if ultima else None, x, prim.isoformat(timespec="seconds")))
        mid = cur.lastrowid
        if total:
            for previsto in calcular_doses(prim, x, total):
                _inserir_dose(conn, mid, previsto)
        else:
            _estender(conn, mid, prim, x, agora)
    return mid


def estender_cronogramas(conn, agora=None):
    """Mantém as próximas 72 h de doses dos cronogramas contínuos por intervalo."""
    agora = agora or datetime.now()
    for m in conn.execute(
        "SELECT id, intervalo_horas, primeira_dose FROM medicamentos "
        "WHERE ativo = 1 AND intervalo_horas IS NOT NULL AND data_fim IS NULL").fetchall():
        with conn:
            _estender(conn, m["id"], datetime.fromisoformat(m["primeira_dose"]), m["intervalo_horas"], agora)


def listar_medicamentos(conn, usuario_id):
    meds = [dict(m) for m in conn.execute(
        "SELECT id, nome, dosagem, observacoes, data_inicio, data_fim, intervalo_horas, primeira_dose, "
        "estoque, estoque_aviso "
        "FROM medicamentos WHERE ativo = 1 AND usuario_id = ? ORDER BY nome", (usuario_id,))]
    for m in meds:
        m["horarios"] = [dict(h) for h in conn.execute(
            "SELECT id, hora, dias_semana FROM horarios "
            "WHERE medicamento_id = ? AND ativo = 1 AND data_unica IS NULL ORDER BY hora", (m["id"],))]
    return meds


def desativar_medicamento(conn, usuario_id, med_id):
    with conn:
        cur = conn.execute(
            "UPDATE medicamentos SET ativo = 0 WHERE id = ? AND usuario_id = ? AND ativo = 1",
            (med_id, usuario_id))
    if cur.rowcount == 0:
        raise NaoEncontrado("Medicamento não encontrado.")


def adicionar_horario(conn, usuario_id, med_id, hora, dias_semana="0123456", agora=None):
    if not _HORA_RE.match(hora or ""):
        raise ErroValidacao("Hora inválida. Use o formato HH:MM (ex.: 08:30).")
    dias_semana = "".join(sorted(set(dias_semana or "")))
    if not dias_semana or any(d not in "0123456" for d in dias_semana):
        raise ErroValidacao("dias_semana deve conter dígitos de 0 (segunda) a 6 (domingo).")
    existe = conn.execute(
        "SELECT 1 FROM medicamentos WHERE id = ? AND usuario_id = ? AND ativo = 1",
        (med_id, usuario_id)).fetchone()
    if not existe:
        raise NaoEncontrado("Medicamento não encontrado.")
    with conn:
        cur = conn.execute(
            "INSERT INTO horarios (medicamento_id, hora, dias_semana, criado_em) VALUES (?, ?, ?, ?)",
            (med_id, hora, dias_semana, (agora or datetime.now()).isoformat(timespec="seconds")))
    return cur.lastrowid


def remover_horario(conn, usuario_id, horario_id):
    with conn:
        cur = conn.execute(
            """UPDATE horarios SET ativo = 0
                WHERE id = ? AND ativo = 1
                  AND medicamento_id IN (SELECT id FROM medicamentos WHERE usuario_id = ?)""",
            (horario_id, usuario_id))
    if cur.rowcount == 0:
        raise NaoEncontrado("Horário não encontrado.")


# ---------- alarmes ----------
def expirar_alarmes(conn, agora=None):
    """Alarmes pendentes que passaram da tolerância (e não estão adiados) viram 'perdido'."""
    agora = agora or datetime.now()
    for r in conn.execute(
        """SELECT r.id, r.data_prevista, r.adiado_ate, h.hora
             FROM registros r JOIN horarios h ON h.id = r.horario_id
            WHERE r.status = 'pendente'""").fetchall():
        if r["adiado_ate"] and r["adiado_ate"] > agora.isoformat(timespec="seconds"):
            continue
        previsto = datetime.fromisoformat(f"{r['data_prevista']}T{r['hora']}:00")
        if (agora - previsto).total_seconds() / 60 > TOLERANCIA_MIN:
            with conn:
                conn.execute("UPDATE registros SET status = 'perdido' WHERE id = ?", (r["id"],))


def gerar_alarmes(conn, agora=None):
    """Cria o registro do dia para cada horário que já passou (de todos os usuários).
    Idempotente: rodar várias vezes não duplica (UNIQUE horario_id + data)."""
    agora = agora or datetime.now()
    expirar_alarmes(conn, agora)
    estender_cronogramas(conn, agora)
    hoje = agora.date().isoformat()
    dia = str(agora.weekday())
    novos = []
    linhas = conn.execute(
        """SELECT h.id, h.hora, h.dias_semana, h.criado_em, h.data_unica, m.data_inicio, m.data_fim
             FROM horarios h JOIN medicamentos m ON m.id = h.medicamento_id
            WHERE m.ativo = 1 AND h.ativo = 1 AND m.usuario_id IS NOT NULL"""
    ).fetchall()
    for h in linhas:
        if h["data_unica"]:
            if h["data_unica"] != hoje:
                continue  # dose por intervalo vale só no próprio dia
        elif dia not in h["dias_semana"]:
            continue
        if h["data_inicio"] and hoje < h["data_inicio"]:
            continue  # tratamento ainda não começou
        if h["data_fim"] and hoje > h["data_fim"]:
            continue  # tratamento terminou
        previsto = datetime.fromisoformat(f"{hoje}T{h['hora']}:00")
        if previsto > agora:
            continue
        if h["criado_em"] and previsto < datetime.fromisoformat(h["criado_em"]):
            continue  # horário criado depois da hora: não conta como dose perdida
        atraso_min = (agora - previsto).total_seconds() / 60
        status = "perdido" if atraso_min > TOLERANCIA_MIN else "pendente"
        with conn:
            cur = conn.execute(
                "INSERT OR IGNORE INTO registros (horario_id, data_prevista, status) "
                "VALUES (?, ?, ?)", (h["id"], hoje, status))
        if cur.rowcount:
            novos.append(cur.lastrowid)
    return novos


def alarmes_pendentes(conn, usuario_id, agora=None):
    """Alarmes do usuário que devem estar tocando agora (pendentes e não adiados)."""
    agora = agora or datetime.now()
    rows = conn.execute(
        """SELECT r.id, m.nome, m.dosagem, m.observacoes, h.hora, r.data_prevista
             FROM registros r
             JOIN horarios h ON h.id = r.horario_id
             JOIN medicamentos m ON m.id = h.medicamento_id
            WHERE m.usuario_id = ? AND r.status = 'pendente' AND m.ativo = 1 AND h.ativo = 1
              AND (r.adiado_ate IS NULL OR r.adiado_ate <= ?)
         ORDER BY h.hora""",
        (usuario_id, agora.isoformat(timespec="seconds")),
    ).fetchall()
    return [dict(r) for r in rows]


def _registro_pendente(conn, usuario_id, registro_id):
    r = conn.execute(
        """SELECT r.* FROM registros r
             JOIN horarios h ON h.id = r.horario_id
             JOIN medicamentos m ON m.id = h.medicamento_id
            WHERE r.id = ? AND m.usuario_id = ?""", (registro_id, usuario_id)).fetchone()
    if not r:
        raise NaoEncontrado("Registro não encontrado.")
    if r["status"] != "pendente":
        raise ErroValidacao(f"Este alarme já está '{r['status']}'.")
    return r


def marcar_tomado(conn, usuario_id, registro_id, agora=None):
    agora = agora or datetime.now()
    _registro_pendente(conn, usuario_id, registro_id)
    with conn:
        conn.execute(
            "UPDATE registros SET status = 'tomado', registrado_em = ?, adiado_ate = NULL "
            "WHERE id = ?", (agora.isoformat(timespec="seconds"), registro_id))
        conn.execute(  # baixa de 1 no estoque (se o remédio controla estoque)
            """UPDATE medicamentos SET estoque = MAX(estoque - 1, 0)
                WHERE estoque IS NOT NULL AND id = (
                    SELECT h.medicamento_id FROM registros r
                      JOIN horarios h ON h.id = r.horario_id WHERE r.id = ?)""", (registro_id,))


def adiar(conn, usuario_id, registro_id, minutos=10, agora=None):
    agora = agora or datetime.now()
    try:
        minutos = int(minutos)
    except (TypeError, ValueError):
        raise ErroValidacao("Minutos inválidos.")
    if not 1 <= minutos <= 120:
        raise ErroValidacao("O adiamento deve ser de 1 a 120 minutos.")
    _registro_pendente(conn, usuario_id, registro_id)
    ate = (agora + timedelta(minutes=minutos)).isoformat(timespec="seconds")
    with conn:
        # ultimo_aviso = NULL faz o push chegar de novo assim que o adiamento acabar
        conn.execute("UPDATE registros SET adiado_ate = ?, ultimo_aviso = NULL WHERE id = ?",
                     (ate, registro_id))
    return ate


def historico(conn, usuario_id, dias=30, hoje=None):
    hoje = hoje or datetime.now().date()
    desde = (hoje - timedelta(days=dias)).isoformat()
    rows = conn.execute(
        """SELECT r.id, r.data_prevista, h.hora, m.nome, m.dosagem, r.status, r.registrado_em
             FROM registros r
             JOIN horarios h ON h.id = r.horario_id
             JOIN medicamentos m ON m.id = h.medicamento_id
            WHERE m.usuario_id = ? AND r.data_prevista >= ?
         ORDER BY r.data_prevista DESC, h.hora DESC""", (usuario_id, desde)).fetchall()
    return [dict(r) for r in rows]


# ---------- dashboard de cronogramas ----------
def _doses_previstas(conn, usuario_id, d0, n_dias, agora):
    """Doses planejadas pelos horários ativos (respeitando dias da semana e período)."""
    rows = conn.execute(
        """SELECT h.id AS horario_id, h.hora, h.dias_semana, h.criado_em, h.data_unica,
                  m.id AS med_id, m.nome, m.dosagem, m.data_inicio, m.data_fim
             FROM horarios h JOIN medicamentos m ON m.id = h.medicamento_id
            WHERE m.usuario_id = ? AND m.ativo = 1 AND h.ativo = 1""", (usuario_id,)).fetchall()
    out = []
    for r in rows:
        for i in range(n_dias):
            d = d0 + timedelta(days=i)
            iso = d.isoformat()
            if r["data_unica"]:
                if r["data_unica"] != iso:
                    continue
            elif str(d.weekday()) not in r["dias_semana"]:
                continue
            if (r["data_inicio"] and iso < r["data_inicio"]) or (r["data_fim"] and iso > r["data_fim"]):
                continue
            previsto = datetime.fromisoformat(f"{iso}T{r['hora']}:00")
            if previsto > agora:
                status = "futuro"
            else:
                if r["criado_em"] and previsto < datetime.fromisoformat(r["criado_em"]):
                    continue
                status = "perdido" if (agora - previsto).total_seconds() / 60 > TOLERANCIA_MIN else "pendente"
            out.append({"horario_id": r["horario_id"], "data": iso, "hora": r["hora"],
                        "med_id": r["med_id"], "nome": r["nome"], "dosagem": r["dosagem"],
                        "status": status, "previsto": previsto})
    return out


def dashboard(conn, usuario_id, agora=None):
    """Tudo que o painel de cronogramas mostra: semana (seg–dom), adesão,
    tratamentos com progresso e a próxima dose."""
    agora = agora or datetime.now()
    hoje = agora.date()
    seg = hoje - timedelta(days=hoje.weekday())
    datas = [(seg + timedelta(days=i)).isoformat() for i in range(7)]

    doses = {}
    for r in conn.execute(
        """SELECT r.horario_id, r.data_prevista, r.status, h.hora, m.id AS med_id, m.nome, m.dosagem
             FROM registros r
             JOIN horarios h ON h.id = r.horario_id
             JOIN medicamentos m ON m.id = h.medicamento_id
            WHERE m.usuario_id = ? AND r.data_prevista BETWEEN ? AND ?
              AND ((m.ativo = 1 AND h.ativo = 1) OR r.status IN ('tomado', 'perdido'))""",
        (usuario_id, datas[0], datas[-1])):
        doses[(r["horario_id"], r["data_prevista"])] = {
            "data": r["data_prevista"], "hora": r["hora"], "med_id": r["med_id"],
            "nome": r["nome"], "dosagem": r["dosagem"], "status": r["status"]}
    for p in _doses_previstas(conn, usuario_id, seg, 7, agora):
        chave = (p["horario_id"], p["data"])
        if chave not in doses:
            doses[chave] = {k: p[k] for k in ("data", "hora", "med_id", "nome", "dosagem", "status")}
    lista = sorted(doses.values(), key=lambda d: (d["data"], d["hora"], d["nome"]))

    esperadas = [d for d in lista if d["status"] != "futuro"]
    tomadas = [d for d in esperadas if d["status"] == "tomado"]
    adesao = {"tomadas": len(tomadas), "esperadas": len(esperadas),
              "pct": round(100 * len(tomadas) / len(esperadas)) if esperadas else None}

    futuras = sorted((p for p in _doses_previstas(conn, usuario_id, hoje, 15, agora) if p["status"] == "futuro"),
                     key=lambda p: p["previsto"])
    proximas = {}
    for p in futuras:
        proximas.setdefault(p["med_id"], [])
        if len(proximas[p["med_id"]]) < 4:
            proximas[p["med_id"]].append({"data": p["data"], "hora": p["hora"]})

    tratamentos = []
    for m in conn.execute(
        "SELECT id, nome, dosagem, observacoes, data_inicio, data_fim, intervalo_horas, primeira_dose "
        "FROM medicamentos WHERE usuario_id = ? AND ativo = 1 ORDER BY nome", (usuario_id,)):
        ini = date.fromisoformat(m["data_inicio"]) if m["data_inicio"] else None
        fim = date.fromisoformat(m["data_fim"]) if m["data_fim"] else None
        t = {"med_id": m["id"], "nome": m["nome"], "dosagem": m["dosagem"],
             "observacoes": m["observacoes"], "data_inicio": m["data_inicio"], "data_fim": m["data_fim"],
             "continuo": fim is None, "total_dias": None, "dia_atual": None,
             "concluido": bool(fim and hoje > fim), "aguardando": bool(ini and hoje < ini),
             "intervalo_horas": m["intervalo_horas"], "primeira_dose": m["primeira_dose"],
             "doses_total": None, "proximas": proximas.get(m["id"], []),
             "doses_tomadas": conn.execute(
                 """SELECT COUNT(*) FROM registros r JOIN horarios h ON h.id = r.horario_id
                     WHERE h.medicamento_id = ? AND r.status = 'tomado'""", (m["id"],)).fetchone()[0]}
        if m["intervalo_horas"] and fim:
            t["doses_total"] = conn.execute(
                "SELECT COUNT(*) FROM horarios WHERE medicamento_id = ?", (m["id"],)).fetchone()[0]
        if ini and fim:
            t["total_dias"] = (fim - ini).days + 1
            t["dia_atual"] = min(max((hoje - ini).days + 1, 0), t["total_dias"])
        t["horarios"] = [dict(h) for h in conn.execute(
            "SELECT id, hora, dias_semana FROM horarios WHERE medicamento_id = ? AND ativo = 1 "
            "AND data_unica IS NULL ORDER BY hora", (m["id"],))]
        tratamentos.append(t)

    proxima = None
    if futuras:
        p = futuras[0]
        proxima = {"nome": p["nome"], "dosagem": p["dosagem"], "hora": p["hora"], "data": p["data"],
                   "quando": p["previsto"].isoformat(timespec="seconds")}
    return {"hoje": hoje.isoformat(), "semana_datas": datas, "doses": lista, "adesao": adesao,
            "tratamentos": tratamentos, "proxima": proxima}


# ---------- notificações push ----------
def avisos_a_enviar(conn, agora=None):
    """Alarmes pendentes (de todos os usuários com push configurado) que precisam de
    (nova) notificação: nunca avisados, adiamento terminado ou aviso há > REPETIR_AVISO_MIN."""
    agora = agora or datetime.now()
    limite = (agora - timedelta(minutes=REPETIR_AVISO_MIN)).isoformat(timespec="seconds")
    rows = conn.execute(
        """SELECT r.id, u.ntfy_topico, m.nome, m.dosagem, m.observacoes, h.hora
             FROM registros r
             JOIN horarios h ON h.id = r.horario_id
             JOIN medicamentos m ON m.id = h.medicamento_id
             JOIN usuarios u ON u.id = m.usuario_id
            WHERE r.status = 'pendente' AND m.ativo = 1 AND h.ativo = 1
              AND u.ntfy_topico IS NOT NULL
              AND (r.adiado_ate IS NULL OR r.adiado_ate <= ?)
              AND (r.ultimo_aviso IS NULL OR r.ultimo_aviso <= ?)
         ORDER BY h.hora""",
        (agora.isoformat(timespec="seconds"), limite),
    ).fetchall()
    return [dict(r) for r in rows]


def marcar_avisado(conn, registro_id, agora=None):
    agora = agora or datetime.now()
    with conn:
        conn.execute("UPDATE registros SET ultimo_aviso = ? WHERE id = ?",
                     (agora.isoformat(timespec="seconds"), registro_id))

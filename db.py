"""Camada de banco de dados (SQLite) do LembraMed!."""
import os
import sqlite3
from pathlib import Path

# Em produção, DB_PATH aponta para o disco persistente (ex.: /data/lembramed.db).
DB_PADRAO = Path(os.environ.get("DB_PATH") or Path(__file__).parent / "despertador.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS usuarios (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    nome        TEXT NOT NULL,
    email       TEXT NOT NULL UNIQUE,            -- sempre em minúsculas
    senha_hash  TEXT NOT NULL,                   -- nunca guardamos a senha em si
    ntfy_topico TEXT,                            -- tópico do push de cada usuário
    criado_em   TEXT NOT NULL DEFAULT (datetime('now')),
    prefs_som        TEXT,                       -- JSON com as preferências de som da conta
    cuidador_topico  TEXT                        -- tópico ntfy de quem acompanha (familiar/cuidador)
);

CREATE TABLE IF NOT EXISTS reset_senha (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    usuario_id  INTEGER NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
    token_hash  TEXT NOT NULL UNIQUE,            -- só o hash do token é guardado
    expira_em   TEXT NOT NULL,
    usado       INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS medicamentos (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    usuario_id  INTEGER REFERENCES usuarios(id) ON DELETE CASCADE,
    nome        TEXT NOT NULL,
    dosagem     TEXT,
    observacoes TEXT,
    data_inicio TEXT,                            -- "AAAA-MM-DD" (início do tratamento)
    data_fim    TEXT,                            -- "AAAA-MM-DD"; NULL = uso contínuo
    intervalo_horas INTEGER,                     -- cronograma "a cada X horas" (1 a 12)
    primeira_dose   TEXT,                        -- ISO "AAAA-MM-DDTHH:MM:SS" da 1ª dose
    ativo       INTEGER NOT NULL DEFAULT 1,
    estoque         INTEGER,                     -- comprimidos restantes (NULL = não controla)
    estoque_aviso   INTEGER NOT NULL DEFAULT 5,  -- avisa quando chegar a este valor
    estoque_avisado INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS horarios (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    medicamento_id INTEGER NOT NULL REFERENCES medicamentos(id) ON DELETE CASCADE,
    hora           TEXT NOT NULL,                   -- "HH:MM"
    dias_semana    TEXT NOT NULL DEFAULT '0123456', -- 0 = segunda ... 6 = domingo
    ativo          INTEGER NOT NULL DEFAULT 1,      -- 0 = removido (mantém o histórico)
    criado_em      TEXT,                            -- doses anteriores a isso não contam como perdidas
    data_unica     TEXT                             -- se preenchido, vale só nesse dia (dose por intervalo)
);

CREATE TABLE IF NOT EXISTS registros (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    horario_id     INTEGER NOT NULL REFERENCES horarios(id) ON DELETE CASCADE,
    data_prevista  TEXT NOT NULL,                -- "AAAA-MM-DD"
    status         TEXT NOT NULL DEFAULT 'pendente'
                   CHECK (status IN ('pendente', 'tomado', 'perdido')),
    adiado_ate     TEXT,                         -- ISO datetime, se o alarme foi adiado
    registrado_em  TEXT,                         -- quando foi marcado como tomado
    ultimo_aviso   TEXT,                         -- última notificação push enviada
    aviso_cuidador TEXT,                         -- quando o cuidador foi avisado da dose perdida
    UNIQUE (horario_id, data_prevista)           -- um alarme por horário por dia
);
"""


def conectar(caminho=None):
    conn = sqlite3.connect(str(caminho or DB_PADRAO))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 5000")   # espera até 5 s se o banco estiver ocupado
    return conn


def _colunas(conn, tabela):
    return [c["name"] for c in conn.execute(f"PRAGMA table_info({tabela})")]


def iniciar(caminho=None):
    with conectar(caminho) as conn:
        conn.execute("PRAGMA journal_mode = WAL")  # leituras não travam as escritas do agendador
        conn.executescript(SCHEMA)
        # migrações leves para bancos criados em versões anteriores
        if "ultimo_aviso" not in _colunas(conn, "registros"):
            conn.execute("ALTER TABLE registros ADD COLUMN ultimo_aviso TEXT")
        if "ativo" not in _colunas(conn, "horarios"):
            conn.execute("ALTER TABLE horarios ADD COLUMN ativo INTEGER NOT NULL DEFAULT 1")
        if "usuario_id" not in _colunas(conn, "medicamentos"):
            # remédios antigos ficam "sem dono" e são adotados pelo 1º usuário cadastrado
            conn.execute("ALTER TABLE medicamentos ADD COLUMN usuario_id INTEGER "
                         "REFERENCES usuarios(id) ON DELETE CASCADE")
        if "data_inicio" not in _colunas(conn, "medicamentos"):
            conn.execute("ALTER TABLE medicamentos ADD COLUMN data_inicio TEXT")
            conn.execute("ALTER TABLE medicamentos ADD COLUMN data_fim TEXT")
        if "criado_em" not in _colunas(conn, "horarios"):
            conn.execute("ALTER TABLE horarios ADD COLUMN criado_em TEXT")
        if "intervalo_horas" not in _colunas(conn, "medicamentos"):
            conn.execute("ALTER TABLE medicamentos ADD COLUMN intervalo_horas INTEGER")
            conn.execute("ALTER TABLE medicamentos ADD COLUMN primeira_dose TEXT")
        if "data_unica" not in _colunas(conn, "horarios"):
            conn.execute("ALTER TABLE horarios ADD COLUMN data_unica TEXT")
        for tabela, col, ddl in [
            ("usuarios", "prefs_som", "TEXT"), ("usuarios", "cuidador_topico", "TEXT"),
            ("medicamentos", "estoque", "INTEGER"),
            ("medicamentos", "estoque_aviso", "INTEGER NOT NULL DEFAULT 5"),
            ("medicamentos", "estoque_avisado", "INTEGER NOT NULL DEFAULT 0"),
            ("registros", "aviso_cuidador", "TEXT"),
        ]:
            if col not in _colunas(conn, tabela):
                conn.execute(f"ALTER TABLE {tabela} ADD COLUMN {col} {ddl}")

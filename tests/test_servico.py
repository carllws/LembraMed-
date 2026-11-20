import os, sys, tempfile, unittest
from datetime import datetime, timedelta
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import db, servico as s
from app import create_app, avisar_pendentes, LimitadorLogin

SEG_0805 = datetime(2026, 11, 9, 8, 5)  # segunda-feira
ANTES = datetime(2026, 11, 1)  # horários de teste são criados antes das doses simuladas


class BaseBanco(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        db.iniciar(self.tmp.name)
        self.conn = db.conectar(self.tmp.name)
        self.ana = s.cadastrar_usuario(self.conn, "Ana", "ana@exemplo.com", "senha1234")["id"]
        self.bia = s.cadastrar_usuario(self.conn, "Bia", "bia@exemplo.com", "senha5678")["id"]
        self.mid = s.criar_medicamento(self.conn, self.ana, "Exemplo", "1 comprimido")
        s.adicionar_horario(self.conn, self.ana, self.mid, "08:00", agora=ANTES)

    def tearDown(self):
        self.conn.close()
        os.unlink(self.tmp.name)


class TestUsuarios(BaseBanco):
    def test_senha_nao_fica_guardada_em_texto(self):
        h = self.conn.execute("SELECT senha_hash FROM usuarios WHERE id = ?", (self.ana,)).fetchone()[0]
        self.assertNotIn("senha1234", h)

    def test_login_ok_e_erros(self):
        self.assertEqual(s.autenticar(self.conn, " ANA@exemplo.com ", "senha1234")["nome"], "Ana")
        with self.assertRaises(s.ErroAutenticacao):
            s.autenticar(self.conn, "ana@exemplo.com", "errada")
        with self.assertRaises(s.ErroAutenticacao):
            s.autenticar(self.conn, "naoexiste@exemplo.com", "senha1234")

    def test_cadastro_valida(self):
        for args in [("", "x@y.com", "senha1234"), ("X", "invalido", "senha1234"),
                     ("X", "x@y.com", "curta")]:
            with self.assertRaises(s.ErroValidacao):
                s.cadastrar_usuario(self.conn, *args)
        with self.assertRaises(s.ErroConflito):
            s.cadastrar_usuario(self.conn, "Outra Ana", "ANA@exemplo.com", "senha1234")

    def test_topico(self):
        self.assertEqual(s.definir_topico(self.conn, self.ana, "remedio-ana-123")["ntfy_topico"], "remedio-ana-123")
        self.assertIsNone(s.definir_topico(self.conn, self.ana, "")["ntfy_topico"])
        with self.assertRaises(s.ErroValidacao):
            s.definir_topico(self.conn, self.ana, "tem espaço!")

    def test_isolamento_entre_usuarios(self):
        self.assertEqual(s.listar_medicamentos(self.conn, self.bia), [])
        with self.assertRaises(s.NaoEncontrado):
            s.desativar_medicamento(self.conn, self.bia, self.mid)
        with self.assertRaises(s.NaoEncontrado):
            s.adicionar_horario(self.conn, self.bia, self.mid, "10:00")
        s.gerar_alarmes(self.conn, SEG_0805)
        self.assertEqual(s.alarmes_pendentes(self.conn, self.bia, SEG_0805), [])
        rid = s.alarmes_pendentes(self.conn, self.ana, SEG_0805)[0]["id"]
        with self.assertRaises(s.NaoEncontrado):
            s.marcar_tomado(self.conn, self.bia, rid, SEG_0805)
        with self.assertRaises(s.NaoEncontrado):
            s.adiar(self.conn, self.bia, rid, 5, SEG_0805)
        self.assertEqual(s.historico(self.conn, self.bia, hoje=SEG_0805.date()), [])

    def test_primeiro_usuario_adota_remedios_antigos(self):
        tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False); tmp.close()
        try:
            db.iniciar(tmp.name)
            c = db.conectar(tmp.name)
            c.execute("INSERT INTO medicamentos (nome) VALUES ('Antigo')"); c.commit()
            uid = s.cadastrar_usuario(c, "Ana", "a@b.co", "senha1234")["id"]
            self.assertEqual(s.listar_medicamentos(c, uid)[0]["nome"], "Antigo")
            c.close()
        finally:
            os.unlink(tmp.name)


class TestAlarmes(BaseBanco):
    def test_nao_dispara_antes_da_hora(self):
        self.assertEqual(s.gerar_alarmes(self.conn, datetime(2026, 11, 9, 7, 59)), [])

    def test_dispara_e_e_idempotente(self):
        self.assertEqual(len(s.gerar_alarmes(self.conn, SEG_0805)), 1)
        self.assertEqual(s.gerar_alarmes(self.conn, SEG_0805), [])
        self.assertEqual(len(s.alarmes_pendentes(self.conn, self.ana, SEG_0805)), 1)

    def test_respeita_dias_da_semana(self):
        s.adicionar_horario(self.conn, self.ana, self.mid, "09:00", "5", agora=ANTES)  # só sábado
        agora = datetime(2026, 11, 9, 9, 30)
        s.gerar_alarmes(self.conn, agora)
        horas = [a["hora"] for a in s.alarmes_pendentes(self.conn, self.ana, agora)]
        self.assertNotIn("09:00", horas)

    def test_atraso_grande_vira_perdido(self):
        agora = datetime(2026, 11, 9, 18, 0)
        s.gerar_alarmes(self.conn, agora)
        self.assertEqual(s.alarmes_pendentes(self.conn, self.ana, agora), [])
        self.assertEqual(s.historico(self.conn, self.ana, hoje=agora.date())[0]["status"], "perdido")

    def test_alarme_nao_atendido_vira_perdido_depois_da_tolerancia(self):
        s.gerar_alarmes(self.conn, SEG_0805)
        self.assertEqual(len(s.alarmes_pendentes(self.conn, self.ana, SEG_0805)), 1)
        s.gerar_alarmes(self.conn, datetime(2026, 11, 9, 10, 30))  # 2h30 depois
        self.assertEqual(s.alarmes_pendentes(self.conn, self.ana, datetime(2026, 11, 9, 10, 30)), [])
        self.assertEqual(s.historico(self.conn, self.ana, hoje=SEG_0805.date())[0]["status"], "perdido")

    def test_alarme_adiado_nao_expira_enquanto_adiado(self):
        s.gerar_alarmes(self.conn, SEG_0805)
        rid = s.alarmes_pendentes(self.conn, self.ana, SEG_0805)[0]["id"]
        s.adiar(self.conn, self.ana, rid, 120, datetime(2026, 11, 9, 9, 50))  # adiado até 11:50
        s.gerar_alarmes(self.conn, datetime(2026, 11, 9, 11, 0))
        self.assertEqual(len(s.alarmes_pendentes(self.conn, self.ana, datetime(2026, 11, 9, 11, 55))), 1)

    def test_adiar_e_reaparecer(self):
        s.gerar_alarmes(self.conn, SEG_0805)
        rid = s.alarmes_pendentes(self.conn, self.ana, SEG_0805)[0]["id"]
        s.adiar(self.conn, self.ana, rid, 10, SEG_0805)
        self.assertEqual(s.alarmes_pendentes(self.conn, self.ana, datetime(2026, 11, 9, 8, 10)), [])
        self.assertEqual(len(s.alarmes_pendentes(self.conn, self.ana, datetime(2026, 11, 9, 8, 16))), 1)

    def test_marcar_tomado_e_nao_repetir(self):
        s.gerar_alarmes(self.conn, SEG_0805)
        rid = s.alarmes_pendentes(self.conn, self.ana, SEG_0805)[0]["id"]
        s.marcar_tomado(self.conn, self.ana, rid, SEG_0805)
        self.assertEqual(s.alarmes_pendentes(self.conn, self.ana, SEG_0805), [])
        with self.assertRaises(s.ErroValidacao):
            s.marcar_tomado(self.conn, self.ana, rid, SEG_0805)

    def test_remover_horario_mantem_historico(self):
        s.gerar_alarmes(self.conn, SEG_0805)
        hid = s.listar_medicamentos(self.conn, self.ana)[0]["horarios"][0]["id"]
        s.remover_horario(self.conn, self.ana, hid)
        self.assertEqual(s.alarmes_pendentes(self.conn, self.ana, SEG_0805), [])
        self.assertEqual(len(s.historico(self.conn, self.ana, hoje=SEG_0805.date())), 1)

    def test_historico_padrao_cobre_30_dias(self):
        s.gerar_alarmes(self.conn, datetime(2026, 11, 5, 8, 30))   # registro de 25 dias antes
        hoje = datetime(2026, 11, 30).date()
        self.assertEqual(len(s.historico(self.conn, self.ana, hoje=hoje)), 1)          # padrão = 30 dias
        self.assertEqual(len(s.historico(self.conn, self.ana, dias=7, hoje=hoje)), 0)  # 7 dias não alcança
        self.assertEqual(len(s.historico(self.conn, self.ana, dias=30, hoje=datetime(2026, 12, 10).date())), 0)

    def test_validacoes(self):
        with self.assertRaises(s.ErroValidacao):
            s.criar_medicamento(self.conn, self.ana, "  ")
        with self.assertRaises(s.ErroValidacao):
            s.adicionar_horario(self.conn, self.ana, self.mid, "25:99")


class TestCronograma(BaseBanco):
    def test_periodo_validacoes_e_inicio_padrao(self):
        mid = s.criar_medicamento(self.conn, self.ana, "Antibiótico", data_fim="2026-11-15", agora=SEG_0805)
        m = [x for x in s.listar_medicamentos(self.conn, self.ana) if x["id"] == mid][0]
        self.assertEqual((m["data_inicio"], m["data_fim"]), ("2026-11-09", "2026-11-15"))
        with self.assertRaises(s.ErroValidacao):
            s.criar_medicamento(self.conn, self.ana, "X", data_inicio="2026-11-10", data_fim="2026-11-09")
        with self.assertRaises(s.ErroValidacao):
            s.criar_medicamento(self.conn, self.ana, "X", data_inicio="10/11/2026")
        with self.assertRaises(s.ErroValidacao):
            s.criar_medicamento(self.conn, self.ana, "X", data_inicio="2026-01-01", data_fim="2029-01-01")

    def test_alarmes_so_dentro_do_periodo(self):
        mid = s.criar_medicamento(self.conn, self.ana, "Curto", data_inicio="2026-11-10", data_fim="2026-11-11")
        s.adicionar_horario(self.conn, self.ana, mid, "07:00", agora=ANTES)
        antes = lambda d: [a["nome"] for a in s.alarmes_pendentes(self.conn, self.ana, d)]
        for dia, esperado in [(9, False), (10, True), (11, True), (12, False)]:
            agora = datetime(2026, 11, dia, 7, 30)
            s.gerar_alarmes(self.conn, agora)
            self.assertEqual("Curto" in antes(agora), esperado, dia)

    def test_horario_criado_depois_da_hora_nao_vira_perdido(self):
        mid = s.criar_medicamento(self.conn, self.ana, "Novo")
        s.adicionar_horario(self.conn, self.ana, mid, "08:00", agora=datetime(2026, 11, 9, 15, 0))
        s.gerar_alarmes(self.conn, datetime(2026, 11, 9, 15, 5))
        self.assertNotIn("Novo", [h["nome"] for h in s.historico(self.conn, self.ana, hoje=SEG_0805.date())])

    def test_dashboard_semana_adesao_e_proxima(self):
        s.gerar_alarmes(self.conn, SEG_0805)
        rid = s.alarmes_pendentes(self.conn, self.ana, SEG_0805)[0]["id"]
        s.marcar_tomado(self.conn, self.ana, rid, SEG_0805)
        d = s.dashboard(self.conn, self.ana, SEG_0805)
        self.assertEqual(d["semana_datas"][0], "2026-11-09")
        self.assertEqual(len(d["semana_datas"]), 7)
        self.assertEqual([x["status"] for x in d["doses"]], ["tomado"] + ["futuro"] * 6)
        self.assertEqual(d["adesao"], {"tomadas": 1, "esperadas": 1, "pct": 100})
        self.assertEqual(d["proxima"]["data"], "2026-11-10")
        self.assertTrue(d["tratamentos"][0]["continuo"])

    def test_dashboard_tratamento_com_progresso_e_conclusao(self):
        mid = s.criar_medicamento(self.conn, self.ana, "Curto", data_inicio="2026-11-09", data_fim="2026-11-11")
        s.adicionar_horario(self.conn, self.ana, mid, "09:00", agora=ANTES)
        t = [x for x in s.dashboard(self.conn, self.ana, SEG_0805)["tratamentos"] if x["nome"] == "Curto"][0]
        self.assertEqual((t["dia_atual"], t["total_dias"], t["concluido"]), (1, 3, False))
        doses = [x for x in s.dashboard(self.conn, self.ana, SEG_0805)["doses"] if x["nome"] == "Curto"]
        self.assertEqual(len(doses), 3)  # só os 3 dias do tratamento
        t = [x for x in s.dashboard(self.conn, self.ana, datetime(2026, 11, 12, 8, 0))["tratamentos"] if x["nome"] == "Curto"][0]
        self.assertTrue(t["concluido"])

    def test_dias_da_semana_no_dashboard(self):
        mid = s.criar_medicamento(self.conn, self.bia, "Sábados")
        s.adicionar_horario(self.conn, self.bia, mid, "10:00", "5", agora=ANTES)
        doses = s.dashboard(self.conn, self.bia, SEG_0805)["doses"]
        self.assertEqual([x["data"] for x in doses], ["2026-11-14"])

    def test_dashboard_isolado_por_usuario(self):
        d = s.dashboard(self.conn, self.bia, SEG_0805)
        self.assertEqual((d["doses"], d["tratamentos"], d["proxima"]), ([], [], None))


class TestIntervalo(BaseBanco):
    AGORA = datetime(2026, 11, 9, 18, 30)

    def doses(self, mid):
        return [(r["data_unica"], r["hora"]) for r in self.conn.execute(
            "SELECT data_unica, hora FROM horarios WHERE medicamento_id = ? ORDER BY data_unica, hora", (mid,))]

    def test_calcular_doses_de_6_em_6_horas(self):
        horas = [d.strftime("%d %H:%M") for d in s.calcular_doses(datetime(2026, 11, 9, 18, 30), 6, 5)]
        self.assertEqual(horas, ["09 18:30", "10 00:30", "10 06:30", "10 12:30", "10 18:30"])

    def test_dipirona_6_em_6_por_3_dias_tem_12_doses(self):
        mid = s.criar_cronograma_intervalo(self.conn, self.ana, "Dipirona", "1 comprimido", None,
                                           6, "2026-11-09T18:30", 3, self.AGORA)
        d = self.doses(mid)
        self.assertEqual(len(d), 12)
        self.assertEqual(d[0], ("2026-11-09", "18:30"))
        self.assertEqual(d[-1], ("2026-11-12", "12:30"))
        m = [x for x in s.listar_medicamentos(self.conn, self.ana) if x["id"] == mid][0]
        self.assertEqual((m["data_inicio"], m["data_fim"], m["intervalo_horas"], m["horarios"]),
                         ("2026-11-09", "2026-11-12", 6, []))  # doses não viram "horários fixos"

    def test_intervalo_que_nao_divide_24_nao_repete_o_mesmo_horario(self):
        mid = s.criar_cronograma_intervalo(self.conn, self.ana, "X", None, None, 5, "2026-11-09T18:30", 1, self.AGORA)
        self.assertEqual(self.doses(mid), [("2026-11-09", "18:30"), ("2026-11-09", "23:30"),
                         ("2026-11-10", "04:30"), ("2026-11-10", "09:30"), ("2026-11-10", "14:30")])

    def test_todos_os_intervalos_de_1_a_12(self):
        for x in range(1, 13):
            mid = s.criar_cronograma_intervalo(self.conn, self.ana, f"M{x}", None, None, x, "2026-11-09T18:30", 1, self.AGORA)
            self.assertEqual(len(self.doses(mid)), -(-24 // x), x)

    def test_validacoes(self):
        casos = [dict(intervalo_horas=0), dict(intervalo_horas=13), dict(intervalo_horas="abc"),
                 dict(primeira_dose="2026-11-09T10:00"),      # passado
                 dict(primeira_dose="ontem"), dict(dias=0), dict(dias=400),
                 dict(intervalo_horas=1, dias=365)]            # 8760 doses > limite
        for extra in casos:
            args = dict(intervalo_horas=6, primeira_dose="2026-11-09T18:30", dias=2)
            args.update(extra)
            with self.assertRaises(s.ErroValidacao, msg=str(extra)):
                s.criar_cronograma_intervalo(self.conn, self.ana, "X", None, None, agora=self.AGORA, **args)

    def test_alarmes_nos_horarios_calculados(self):
        s.criar_cronograma_intervalo(self.conn, self.ana, "Dipirona", None, None, 6, "2026-11-09T18:30", 1, self.AGORA)
        s.gerar_alarmes(self.conn, datetime(2026, 11, 9, 18, 31))
        self.assertEqual([a["hora"] for a in s.alarmes_pendentes(self.conn, self.ana, datetime(2026, 11, 9, 18, 31))], ["18:30"])
        s.gerar_alarmes(self.conn, datetime(2026, 11, 10, 0, 31))
        horas = [a["hora"] for a in s.alarmes_pendentes(self.conn, self.ana, datetime(2026, 11, 10, 0, 31))]
        self.assertIn("00:30", horas)
        self.assertNotIn("18:30", horas)  # a de ontem já expirou (perdida)

    def test_primeira_dose_agora_dispara_na_hora(self):
        agora = datetime(2026, 11, 9, 18, 30, 40)
        s.criar_cronograma_intervalo(self.conn, self.ana, "Agora", None, None, 8, "2026-11-09T18:30", 1, agora)
        s.gerar_alarmes(self.conn, agora)
        self.assertEqual([a["nome"] for a in s.alarmes_pendentes(self.conn, self.ana, agora)], ["Agora"])

    def test_continuo_mantem_72h_a_frente(self):
        mid = s.criar_cronograma_intervalo(self.conn, self.ana, "Cont", None, None, 6, "2026-11-09T18:30", None, self.AGORA)
        self.assertEqual(self.doses(mid)[-1], ("2026-11-12", "18:30"))  # até agora + 72h
        s.gerar_alarmes(self.conn, datetime(2026, 11, 12, 20, 0))       # dias depois
        self.assertEqual(self.doses(mid)[-1], ("2026-11-15", "18:30"))
        self.assertEqual(len(self.doses(mid)), len(set(self.doses(mid))))  # sem duplicadas

    def test_dashboard_mostra_progresso_por_doses(self):
        mid = s.criar_cronograma_intervalo(self.conn, self.ana, "Dipirona", None, None, 6, "2026-11-09T18:30", 1, self.AGORA)
        s.gerar_alarmes(self.conn, datetime(2026, 11, 9, 18, 31))
        rid = s.alarmes_pendentes(self.conn, self.ana, datetime(2026, 11, 9, 18, 31))[0]["id"]
        s.marcar_tomado(self.conn, self.ana, rid, datetime(2026, 11, 9, 18, 35))
        t = [x for x in s.dashboard(self.conn, self.ana, datetime(2026, 11, 9, 18, 40))["tratamentos"] if x["nome"] == "Dipirona"][0]
        self.assertEqual((t["intervalo_horas"], t["doses_total"], t["doses_tomadas"]), (6, 4, 1))
        self.assertEqual(t["proximas"][0], {"data": "2026-11-10", "hora": "00:30"})

    def test_isolamento(self):
        mid = s.criar_cronograma_intervalo(self.conn, self.ana, "Dipirona", None, None, 6, "2026-11-09T18:30", 1, self.AGORA)
        self.assertEqual(s.dashboard(self.conn, self.bia, self.AGORA)["tratamentos"], [])
        with self.assertRaises(s.NaoEncontrado):
            s.desativar_medicamento(self.conn, self.bia, mid)


class TestPush(BaseBanco):
    def setUp(self):
        super().setUp()
        s.definir_topico(self.conn, self.ana, "remedio-ana-123")
        self.enviados = []
        self.ok = lambda topico, t, m: self.enviados.append((topico, m)) or True

    def ciclo(self, agora, enviar=None):
        s.gerar_alarmes(self.conn, agora)
        avisar_pendentes(self.conn, enviar or self.ok, agora)

    def test_avisa_uma_vez_e_repete_depois_de_10_min(self):
        self.ciclo(datetime(2026, 11, 9, 8, 0))
        self.ciclo(datetime(2026, 11, 9, 8, 5))
        self.assertEqual(len(self.enviados), 1)
        self.assertEqual(self.enviados[0][0], "remedio-ana-123")
        self.ciclo(datetime(2026, 11, 9, 8, 11))
        self.assertEqual(len(self.enviados), 2)

    def test_sem_topico_nao_envia(self):
        s.definir_topico(self.conn, self.ana, "")
        self.ciclo(datetime(2026, 11, 9, 8, 0))
        self.assertEqual(self.enviados, [])

    def test_para_de_avisar_quando_tomado(self):
        self.ciclo(datetime(2026, 11, 9, 8, 0))
        rid = s.alarmes_pendentes(self.conn, self.ana, datetime(2026, 11, 9, 8, 0))[0]["id"]
        s.marcar_tomado(self.conn, self.ana, rid, datetime(2026, 11, 9, 8, 1))
        self.ciclo(datetime(2026, 11, 9, 8, 30))
        self.assertEqual(len(self.enviados), 1)

    def test_adiar_reavisa_so_quando_o_adiamento_acaba(self):
        self.ciclo(datetime(2026, 11, 9, 8, 0))
        rid = s.alarmes_pendentes(self.conn, self.ana, datetime(2026, 11, 9, 8, 0))[0]["id"]
        s.adiar(self.conn, self.ana, rid, 5, datetime(2026, 11, 9, 8, 1))
        self.ciclo(datetime(2026, 11, 9, 8, 3))
        self.assertEqual(len(self.enviados), 1)
        self.ciclo(datetime(2026, 11, 9, 8, 7))
        self.assertEqual(len(self.enviados), 2)

    def test_falha_no_envio_tenta_de_novo(self):
        self.ciclo(datetime(2026, 11, 9, 8, 0), enviar=lambda *a: False)
        self.ciclo(datetime(2026, 11, 9, 8, 1))
        self.assertEqual(len(self.enviados), 1)


class TestLimitador(unittest.TestCase):
    def test_bloqueia_e_libera(self):
        t = [1000.0]
        lim = LimitadorLogin(agora=lambda: t[0])
        for _ in range(5):
            lim.falhou("k")
        self.assertGreater(lim.segundos_bloqueado("k"), 0)
        t[0] += 61
        self.assertEqual(lim.segundos_bloqueado("k"), 0)


class TestAPI(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.enviados = []
        self.app = create_app(os.path.join(self.dir.name, "t.db"), iniciar_agendador=False,
                              enviar=lambda *a: self.enviados.append(a) or True)

    def tearDown(self):
        self.dir.cleanup()

    def cadastrar(self, nome, email):
        c = self.app.test_client()
        r = c.post("/api/cadastro", json={"nome": nome, "email": email, "senha": "senha1234"})
        self.assertEqual(r.status_code, 201)
        return c

    def test_exige_login(self):
        c = self.app.test_client()
        for url in ["/medicamentos", "/historico", "/alarmes/pendentes", "/api/eu"]:
            self.assertEqual(c.get(url).status_code, 401, url)
        self.assertEqual(c.post("/medicamentos", json={"nome": "x"}).status_code, 401)

    def test_pagina_e_login_logout(self):
        c = self.app.test_client()
        self.assertEqual(c.get("/").status_code, 200)
        self.cadastrar("Ana", "ana@x.com")
        c = self.app.test_client()
        self.assertEqual(c.post("/api/login", json={"email": "ana@x.com", "senha": "errada"}).status_code, 401)
        self.assertEqual(c.post("/api/login", json={"email": "ana@x.com", "senha": "senha1234"}).status_code, 200)
        self.assertEqual(c.get("/api/eu").get_json()["nome"], "Ana")
        self.assertNotIn("senha", str(c.get("/api/eu").get_json()))
        c.post("/api/logout")
        self.assertEqual(c.get("/api/eu").status_code, 401)

    def test_cadastro_duplicado_e_invalido(self):
        self.cadastrar("Ana", "ana@x.com")
        c = self.app.test_client()
        self.assertEqual(c.post("/api/cadastro", json={"nome": "A", "email": "ANA@x.com", "senha": "senha1234"}).status_code, 409)
        self.assertEqual(c.post("/api/cadastro", json={"nome": "A", "email": "a@x.com", "senha": "1"}).status_code, 400)

    def test_bloqueio_apos_5_falhas(self):
        self.cadastrar("Ana", "ana@x.com")
        c = self.app.test_client()
        for _ in range(5):
            c.post("/api/login", json={"email": "ana@x.com", "senha": "errada"})
        r = c.post("/api/login", json={"email": "ana@x.com", "senha": "senha1234"})
        self.assertEqual(r.status_code, 429)

    def test_fluxo_e_isolamento(self):
        ana, bia = self.cadastrar("Ana", "ana@x.com"), self.cadastrar("Bia", "bia@x.com")
        antes = datetime.now() - timedelta(minutes=1)
        if antes.date() != datetime.now().date():
            self.skipTest("virada de dia")
        r = ana.post("/medicamentos", json={"nome": "Teste", "horarios": [antes.strftime("%H:%M")]})
        self.assertEqual(r.status_code, 201)
        import sqlite3
        with sqlite3.connect(os.path.join(self.dir.name, "t.db")) as raw:
            raw.execute("UPDATE horarios SET criado_em = '2020-01-01T00:00:00'")
        pend = ana.get("/alarmes/pendentes").get_json()
        self.assertEqual(len(pend), 1)
        # Bia não enxerga nem mexe nas coisas da Ana
        self.assertEqual(bia.get("/medicamentos").get_json(), [])
        self.assertEqual(bia.get("/alarmes/pendentes").get_json(), [])
        self.assertEqual(bia.post(f"/registros/{pend[0]['id']}/tomado").status_code, 404)
        mid = ana.get("/medicamentos").get_json()[0]["id"]
        self.assertEqual(bia.delete(f"/medicamentos/{mid}").status_code, 404)
        # Ana confirma, vê o histórico e remove um horário sem perder o histórico
        self.assertEqual(ana.post(f"/registros/{pend[0]['id']}/tomado").status_code, 200)
        hid = ana.get("/medicamentos").get_json()[0]["horarios"][0]["id"]
        self.assertEqual(ana.delete(f"/horarios/{hid}").status_code, 204)
        self.assertEqual(ana.delete(f"/horarios/{hid}").status_code, 404)
        self.assertEqual(ana.get("/historico").get_json()[0]["status"], "tomado")
        self.assertEqual(ana.post("/medicamentos", json={}).status_code, 400)

    def test_perfil_e_teste_push(self):
        c = self.cadastrar("Ana", "ana@x.com")
        self.assertEqual(c.post("/api/eu/teste-push").status_code, 400)  # sem tópico
        self.assertEqual(c.put("/api/eu", json={"ntfy_topico": "ruim!"}).status_code, 400)
        self.assertEqual(c.put("/api/eu", json={"ntfy_topico": "remedio-ana-123"}).status_code, 200)
        self.assertEqual(c.post("/api/eu/teste-push").status_code, 200)
        self.assertEqual(self.enviados[0][0], "remedio-ana-123")

    def test_dashboard_api(self):
        c = self.cadastrar("Ana", "ana@x.com")
        r = c.post("/medicamentos", json={"nome": "Curto", "horarios": ["08:00", "20:00"],
                                          "data_inicio": "2026-11-09", "data_fim": "2026-11-11"})
        self.assertEqual(r.status_code, 201)
        d = c.get("/api/dashboard").get_json()
        self.assertEqual(d["tratamentos"][0]["total_dias"], 3)
        self.assertEqual(len(d["semana_datas"]), 7)
        self.assertEqual(c.post("/medicamentos", json={"nome": "X", "horarios": ["08:00"], "data_fim": "ontem"}).status_code, 400)
        self.assertEqual(self.app.test_client().get("/api/dashboard").status_code, 401)
        self.assertEqual(c.get("/historico?dias=999999").status_code, 200)  # limite máximo é aplicado

    def test_api_cronograma_por_intervalo(self):
        c = self.cadastrar("Ana", "ana@x.com")
        agora = datetime.now().replace(second=0, microsecond=0)
        r = c.post("/medicamentos", json={"nome": "Dipirona", "intervalo_horas": 6,
                                          "primeira_dose": agora.isoformat(timespec="minutes"), "dias": 2})
        self.assertEqual(r.status_code, 201)
        t = c.get("/api/dashboard").get_json()["tratamentos"][0]
        self.assertEqual((t["intervalo_horas"], t["doses_total"]), (6, 8))
        self.assertEqual(len(c.get("/alarmes/pendentes").get_json()), 1)  # 1ª dose, agora
        r = c.post("/medicamentos", json={"nome": "X", "intervalo_horas": 20, "primeira_dose": agora.isoformat()})
        self.assertEqual(r.status_code, 400)


if __name__ == "__main__":
    unittest.main()

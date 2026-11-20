import os, sys, tempfile, unittest
from datetime import datetime, timedelta
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import db, servico as s
from app import create_app, avisar_pendentes

AGORA = datetime(2026, 11, 16, 8, 0)


class Extras(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False); self.tmp.close()
        db.iniciar(self.tmp.name)
        self.conn = db.conectar(self.tmp.name)
        self.ana = s.cadastrar_usuario(self.conn, "Ana", "ana@exemplo.com", "senha1234")["id"]
        self.mid = s.criar_medicamento(self.conn, self.ana, "Exemplo", "1 comprimido")
        self.hid = s.adicionar_horario(self.conn, self.ana, self.mid, "08:00", agora=AGORA - timedelta(days=1))

    def tearDown(self):
        self.conn.close(); os.unlink(self.tmp.name)

    def test_prefs_som_na_conta(self):
        u = s.definir_prefs_som(self.conn, self.ana, {"tipo": "sino", "volume": 70})
        self.assertEqual(u["prefs_som"]["tipo"], "sino")
        with self.assertRaises(s.ErroValidacao):
            s.definir_prefs_som(self.conn, self.ana, ["x"])

    def test_reset_de_senha(self):
        self.assertIsNone(s.criar_token_reset(self.conn, "naoexiste@x.com"))
        _, tok = s.criar_token_reset(self.conn, "ana@exemplo.com", AGORA)
        with self.assertRaises(s.ErroValidacao):
            s.redefinir_senha(self.conn, tok, "curta", AGORA)
        with self.assertRaises(s.ErroValidacao):  # expirado
            s.redefinir_senha(self.conn, tok, "novasenha99", AGORA + timedelta(hours=1))
        s.redefinir_senha(self.conn, tok, "novasenha99", AGORA + timedelta(minutes=5))
        s.autenticar(self.conn, "ana@exemplo.com", "novasenha99")
        with self.assertRaises(s.ErroValidacao):  # token só vale uma vez
            s.redefinir_senha(self.conn, tok, "outrasenha99", AGORA + timedelta(minutes=6))

    def test_estoque_baixa_e_avisa(self):
        s.definir_topico(self.conn, self.ana, "topico-ana-123")
        s.definir_estoque(self.conn, self.ana, self.mid, 3, 2)
        s.gerar_alarmes(self.conn, AGORA)
        rid = s.alarmes_pendentes(self.conn, self.ana, AGORA)[0]["id"]
        s.marcar_tomado(self.conn, self.ana, rid, AGORA)
        self.assertEqual(s.listar_medicamentos(self.conn, self.ana)[0]["estoque"], 2)
        enviados = []
        avisar_pendentes(self.conn, lambda t, ti, m, p=4: enviados.append((t, ti)) or True, AGORA)
        self.assertTrue(any("Estoque" in ti for _, ti in enviados))
        enviados.clear()
        avisar_pendentes(self.conn, lambda t, ti, m, p=4: enviados.append((t, ti)) or True, AGORA)
        self.assertFalse(any("Estoque" in ti for _, ti in enviados))  # avisa uma vez só

    def test_estoque_de_outro_usuario(self):
        bia = s.cadastrar_usuario(self.conn, "Bia", "bia@exemplo.com", "senha5678")["id"]
        with self.assertRaises(s.NaoEncontrado):
            s.definir_estoque(self.conn, bia, self.mid, 5)

    def test_cuidador_recebe_dose_perdida(self):
        s.definir_cuidador(self.conn, self.ana, "cuidador-123")
        depois = AGORA + timedelta(hours=3)
        s.gerar_alarmes(self.conn, AGORA); s.expirar_alarmes(self.conn, depois)
        enviados = []
        avisar_pendentes(self.conn, lambda t, ti, m, p=4: enviados.append((t, ti)) or True, depois)
        self.assertIn(("cuidador-123", "LembraMed! ⚠️ Dose perdida"), enviados)
        enviados.clear()
        avisar_pendentes(self.conn, lambda t, ti, m, p=4: enviados.append((t, ti)) or True, depois)
        self.assertEqual(enviados, [])

    def test_cadastrar_com_estoque_pela_api(self):
        c = create_app(self.tmp.name, iniciar_agendador=False).test_client()
        c.post("/api/login", json={"email": "ana@exemplo.com", "senha": "senha1234"})
        r = c.post("/medicamentos", json={"nome": "Dipirona", "horarios": ["08:00"], "estoque": 20, "estoque_aviso": 4})
        self.assertEqual(r.status_code, 201)
        m = [x for x in c.get("/medicamentos").get_json() if x["nome"] == "Dipirona"][0]
        self.assertEqual((m["estoque"], m["estoque_aviso"]), (20, 4))
        c.put(f"/api/medicamentos/{m['id']}/estoque", json={"estoque": 35, "aviso": 6})
        m = [x for x in c.get("/medicamentos").get_json() if x["nome"] == "Dipirona"][0]
        self.assertEqual((m["estoque"], m["estoque_aviso"]), (35, 6))

    def test_link_de_senha_nao_usa_host_forjado(self):
        import enviar_email
        enviados = []
        original = enviar_email.enviar
        enviar_email.enviar = lambda d, a, txt: enviados.append(txt) or True
        antigo = os.environ.pop("BASE_URL", None)
        try:
            c = create_app(self.tmp.name, iniciar_agendador=False).test_client()
            corpo = {"email": "ana@exemplo.com"}
            self.assertEqual(c.post("/api/esqueci-senha", json=corpo,
                                    headers={"Host": "site-falso.exemplo"}).status_code, 200)
            self.assertEqual(enviados, [])                       # sem BASE_URL e host estranho: não envia
            os.environ["BASE_URL"] = "https://lembramed.exemplo.com/"
            c.post("/api/esqueci-senha", json={"email": "ana@exemplo.com"}, headers={"Host": "site-falso.exemplo"})
            self.assertIn("https://lembramed.exemplo.com/#redefinir=", enviados[0])
            self.assertNotIn("site-falso", enviados[0])          # nunca usa o Host da requisição
        finally:
            enviar_email.enviar = original
            os.environ.pop("BASE_URL", None)
            if antigo: os.environ["BASE_URL"] = antigo

    def test_producao_cookie_secure_wal_e_icones(self):
        os.environ["COOKIE_SECURE"] = "1"
        try:
            c = create_app(self.tmp.name, iniciar_agendador=False).test_client()
            r = c.post("/api/login", json={"email": "ana@exemplo.com", "senha": "senha1234"},
                       base_url="https://lembramed.exemplo.com")
            self.assertIn("Secure", r.headers.get("Set-Cookie", ""))
        finally:
            os.environ.pop("COOKIE_SECURE", None)
        self.assertEqual(self.conn.execute("PRAGMA journal_mode").fetchone()[0], "wal")
        for icone in ("icone-192.png", "icone-512.png", "icone-maskable-512.png"):
            self.assertEqual(c.get("/static/" + icone).status_code, 200)
        self.assertIn("icone-512.png", c.get("/manifest.webmanifest").get_data(as_text=True))

    def test_api_pwa_e_impressao(self):
        app = create_app(self.tmp.name, iniciar_agendador=False)
        c = app.test_client()
        self.assertIn("aba-estoque", c.get("/").get_data(as_text=True))
        self.assertEqual(c.get("/manifest.webmanifest").status_code, 200)
        self.assertEqual(c.get("/sw.js").status_code, 200)
        self.assertEqual(c.get("/api/historico/imprimir").status_code, 401)
        c.post("/api/login", json={"email": "ana@exemplo.com", "senha": "senha1234"})
        r = c.get("/api/historico/imprimir")
        self.assertEqual(r.status_code, 200); self.assertIn("Histórico", r.get_data(as_text=True))
        r = c.post("/api/esqueci-senha", json={"email": "naoexiste@x.com"})
        self.assertEqual(r.status_code, 200)


if __name__ == "__main__":
    unittest.main()

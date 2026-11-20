"""Teste de tela com Playwright (pip install playwright && playwright install chromium).
Se não estiver instalado, é ignorado."""
import os, sys, tempfile, threading, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
try:
    from playwright.sync_api import sync_playwright
except ImportError:
    sync_playwright = None

from werkzeug.serving import make_server
from app import create_app


@unittest.skipIf(sync_playwright is None, "Playwright não instalado")
class Tela(unittest.TestCase):
    def test_cadastro_e_perfil(self):
        tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False); tmp.close()
        srv = make_server("127.0.0.1", 0, create_app(tmp.name, iniciar_agendador=False))
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        try:
            with sync_playwright() as p:
                b = p.chromium.launch(); pg = b.new_page()
                pg.goto(f"http://127.0.0.1:{srv.server_port}/")
                self.assertIn("LembraMed", pg.title())
                self.assertTrue(pg.locator("#form-login").is_visible())
                self.assertTrue(pg.get_by_text("Esqueci minha senha").is_visible())
                b.close()
        finally:
            srv.shutdown(); os.unlink(tmp.name)


@unittest.skipIf(sync_playwright is None, "Playwright não instalado")
class Voz(unittest.TestCase):
    def test_fala_remedio_e_dosagem(self):
        tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False); tmp.close()
        srv = make_server("127.0.0.1", 0, create_app(tmp.name, iniciar_agendador=False))
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        try:
            with sync_playwright() as p:
                b = p.chromium.launch(); pg = b.new_page()
                pg.goto(f"http://127.0.0.1:{srv.server_port}/")
                texto = pg.evaluate("""() => {
                    let dito = null;
                    window.SpeechSynthesisUtterance = function (t) { this.text = t; };
                    Object.defineProperty(window, 'speechSynthesis', { configurable: true, value: {
                        cancel() {}, getVoices() { return []; }, speak(u) { dito = u; } } });
                    somCfg.voz = true;
                    falar(textoDoAlarme([{ nome: 'Dipirona', dosagem: '1 comprimido' }]));
                    return dito.text; }""")
                self.assertEqual(texto, "Hora do remédio. Tome Dipirona, 1 comprimido.")
                b.close()
        finally:
            srv.shutdown(); os.unlink(tmp.name)


if __name__ == "__main__":
    unittest.main()

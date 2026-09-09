import unittest
from unittest.mock import patch

from casehunter.discovery.case_builder import build_case
from casehunter.discovery.collector import fetch_public_text, html_links, html_table_rows, html_to_text
from casehunter.discovery.detector import detect_problems
from casehunter.discovery.extractor import extract_amounts_clp, extract_safis
from casehunter.discovery.ley_lobby import enrich_candidate, scan_ley_lobby_listing


class FakeHeaders:
    def get_content_type(self): return "text/html"
    def get_content_charset(self): return "utf-8"


class FakeResponse:
    headers = FakeHeaders()
    def __init__(self, body: bytes, url): self.body, self.url = body, url
    def read(self, *args): return self.body
    def geturl(self): return self.url
    def __enter__(self): return self
    def __exit__(self, exc_type, exc, tb): return False


def page_html(rows, pages=(1, 2)):
    nav = "".join(f'<a href="?page={p}">{p}</a>' for p in pages)
    return f"<html><body>{nav}<table>{rows}</table></body></html>".encode()


def row(date, aid, matter, detail):
    return f'<tr><td>{date}</td><td>{aid}</td><td>{matter}</td><td><a href="{detail}">Ver Detalle</a></td></tr>'


def detail_html(aid, date, safi, company):
    return f'''<html><body>
    <table><tr><td>Identificador</td><td>{aid}</td></tr><tr><td>Fecha</td><td>{date}</td></tr></table>
    <table><tr><th>Nombre completo</th><th>Calidad</th><th>Trabaja para</th><th>Representa a</th></tr>
      <tr><td>Carlos Garrido</td><td>Gestor de intereses</td><td>SMI Ingenieros</td><td>{company}</td></tr></table>
    <p>N° CONTRATO SAFI {safi} APRUEBA LIQUIDACION DE CONTRATO, DEVOLUCION DE GARANTIA Y RETENCIONES.</p>
    <p>Se requiere saber estado de la resolución de liquidación. Pago pendiente $100.000.000.</p>
    </body></html>'''.encode()


class DiscoveryTests(unittest.TestCase):
    def test_extract_single_safi(self):
        self.assertEqual(extract_safis("Contrato SAFI 385256 pendiente."), ["385256"])

    def test_extract_dotted_and_plural_safis(self):
        self.assertEqual(extract_safis("SAFI 137.601. SAFIs 283.586 y 321.609."), ["137601", "283586", "321609"])

    def test_extract_hyphenated_safi_list(self):
        self.assertEqual(extract_safis("SAFI: 385256-385254-389843-389836."), ["385256", "385254", "389843", "389836"])

    def test_extract_normal_amount(self):
        self.assertEqual(extract_amounts_clp("Monto $42.000.000."), [42000000])

    def test_extract_amount_in_millions(self):
        self.assertIn(1700000000, extract_amounts_clp("Pago aproximado 1.700 millones."))

    def test_detect_core_signals(self):
        types = {x["type"] for x in detect_problems("devolución de retenciones pendiente de aprobación pago pendiente")}
        self.assertTrue({"RETENTION_PENDING", "INTERNAL_APPROVAL_PENDING", "PAYMENT_PENDING"}.issubset(types))

    def test_build_high_confidence_case(self):
        result = build_case("SAFI 385256 devolución de retenciones en revisión $42.000.000")
        self.assertEqual(result["confidence"]["label"], "HIGH")

    def test_html_to_text_removes_script(self):
        text = html_to_text("<h1>SAFI 385256</h1><script>ignore</script><p>$42.000.000</p>")
        self.assertIn("SAFI 385256", text)
        self.assertNotIn("ignore", text)

    def test_table_rows_preserve_empty_cells(self):
        rows = html_table_rows("<table><tr><td>Fabiana</td><td>Gestor de intereses</td><td></td><td>DUFFCO SPA</td></tr></table>", "https://a.test")
        self.assertEqual(rows[0]["cells"], ["Fabiana", "Gestor de intereses", "", "DUFFCO SPA"])

    def test_table_rows_extract_links(self):
        rows = html_table_rows("<table><tr><td>A</td><td><a href='/x'>B</a></td></tr></table>", "https://a.test/base")
        self.assertEqual(rows[0]["links"], ["https://a.test/x"])

    def test_links_are_absolute(self):
        links = html_links('<a href="?page=2">2</a>', "https://a.test/list")
        self.assertIn("https://a.test/list?page=2", links)

    @patch("casehunter.discovery.collector.urlopen")
    def test_public_collector(self, mocked):
        mocked.return_value = FakeResponse(b"<html><body>SAFI 385256 pago pendiente $42.000.000</body></html>", "https://public.example/case")
        collected = fetch_public_text("https://public.example/case")
        self.assertEqual(build_case(collected["text"])["safis"], ["385256"])

    @patch("casehunter.discovery.ley_lobby.fetch_public_document")
    def test_detail_enrichment(self, mocked):
        html = detail_html("AM002AW2052621", "2026-01-21", "319.892", "CARLOS GARRIDO INGENIEROS Y CIA LTDA").decode()
        mocked.return_value = {"source_url":"https://www.leylobby.gob.cl/detail", "raw_html":html, "text":html_to_text(html), "content_type":"text/html"}
        candidate = {"audience_id":"AM002AW2052621", "date":"2026-01-21", "detail_url":"https://www.leylobby.gob.cl/detail", "source_url":"x", "safis":[], "amounts_clp":[], "problems":[], "confidence":{"score":0,"label":"LOW"}, "represented_entities":[], "works_for":[], "raw_text":"pago pendiente"}
        enriched = enrich_candidate(candidate)
        self.assertIn("319892", enriched["safis"])
        self.assertEqual(enriched["represented_entities"], ["CARLOS GARRIDO INGENIEROS Y CIA LTDA"])

    @patch("casehunter.discovery.ley_lobby.fetch_public_document")
    def test_multi_page_scan(self, mocked):
        base = "https://www.leylobby.gob.cl/instituciones/AM002/cargos-pasivos/642196/audiencias"
        p1 = page_html(row("2026-08-12", "AM002AW2275919", "saldos pendientes de pagos, devolución de retenciones", "/instituciones/AM002/audiencias/2026/1/100"))
        p2 = page_html(row("2025-01-29", "AM002AW1739462", "no ha salido ningún pago; devolver retenciones", "/instituciones/AM002/audiencias/2025/1/200"), pages=(1,2))
        docs = {
            base: {"source_url":base,"raw_html":p1.decode(),"text":html_to_text(p1.decode()),"content_type":"text/html"},
            base+"?page=2": {"source_url":base+"?page=2","raw_html":p2.decode(),"text":html_to_text(p2.decode()),"content_type":"text/html"},
        }
        mocked.side_effect = lambda url, timeout=20: docs[url]
        result = scan_ley_lobby_listing(base, enrich=False)
        self.assertEqual(result["pages_scanned"], 2)
        self.assertEqual(result["candidate_count"], 2)

    def test_current_modification_and_adjustment_wording(self):
        text = "Modificaciones pendientes. SAFI 410.834. Pendiente Tramitacion Ajuste Final en revision DGOP."
        types = {p["type"] for p in detect_problems(text)}
        self.assertIn("CONTRACT_MODIFICATION_PENDING", types)
        self.assertIn("FINAL_ADJUSTMENT_PENDING", types)

    def test_real_source_fixture_2026(self):
        text = """2026-01-21 AM002AW2052621 N° CONTRATO SAFI 319.892 APRUEBA LIQUIDACION DE CONTRATO, DEVOLUCION DE GARANTIA Y RETENCIONES. Se requiere saber estado de la resolución de liquidación. N° CONTRATO SAFI 386.866. Estado de tramitación del convenio que permite el pago de los trabajos ejecutados, al igual que la orden de páguese."""
        case = build_case(text)
        self.assertEqual(case["safis"], ["319892", "386866"])
        types = {p["type"] for p in case["problems"]}
        self.assertTrue({"LIQUIDATION_PENDING", "GUARANTEE_PENDING", "RETENTION_PENDING", "PAYMENT_PENDING"}.issubset(types))

    def test_real_source_amount_fixture(self):
        text = "SAFI 396.993. Falta la aprobación de la modificación de obras cuyo monto es de $1.656.931.779; lo que no permite cobrar $3.411.223.851."
        self.assertEqual(build_case(text)["amounts_clp"], [1656931779, 3411223851])

    def test_real_case_valko_2026(self):
        text = """2026-05-26 AM010AW2183902 Constructora Valko S.A. Devolución de retenciones en Contrato Reposición Ruta 181CH sector Curacautín Malalcahuello Código Safi 278.592. Se informa que se están resolviendo temas administrativos para este proceso. Devolución de fondos retenidos y tramitaciones para destrabar la devolución de montos retenidos."""
        case = build_case(text)
        self.assertEqual(case["safis"], ["278592"])
        types = {p["type"] for p in case["problems"]}
        self.assertIn("RETENTION_PENDING", types)

    def test_real_case_rincor_2026(self):
        text = """2026-07-07 AO022AW2231798 Solicitud de pago de retenciones contractuales adeudadas a Constructora Rincor contrato Conservación Posta de Salud Rural San Enrique, Santo Domingo, ingresado sin respuesta a la fecha y estado de pago ingresado con fecha 22 de enero de 2026, sin claridad en su fecha de pago. Se busca abordar la restitución de las retenciones."""
        case = build_case(text)
        types = {p["type"] for p in case["problems"]}
        self.assertIn("RETENTION_PENDING", types)
        self.assertIn("PAYMENT_PENDING", types)

    def test_real_case_cyd_2026(self):
        text = """2026-06-04 AM010AW2190376 Presentación empresa CyD Ingeniería Limitada. Empresa presenta Contratos adjudicados, que se encuentran terminados y consultan estado de Liquidación de Contrato. Se entrega información de Contratos que se encuentran en Liquidación que pertenecen a Empresa CyD."""
        case = build_case(text)
        types = {p["type"] for p in case["problems"]}
        self.assertIn("LIQUIDATION_PENDING", types)

    def test_real_case_prevcons_2026(self):
        text = """2026-02-27 AM007AW2093457 PREVCONS SPA. Solicitar orientación administrativa respecto del flujo de tramitación asociado a contratos DOH con el objeto de comprender los hitos, unidades intervinientes y canales formales de seguimiento, así como las vías institucionales disponibles para requerir información y trazabilidad del proceso conforme a derecho. Se solicita audiencia con carácter prioritario atendida la naturaleza temporal del cierre administrativo de las obras."""
        case = build_case(text)
        types = {p["type"] for p in case["problems"]}
        self.assertIn("LIQUIDATION_PENDING", types)


if __name__ == "__main__": unittest.main()

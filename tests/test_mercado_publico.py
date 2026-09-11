import os
import unittest
from datetime import date
from unittest.mock import patch

from casehunter.mercado_publico import (
    lookup_provider,
    order_to_candidate,
    purchase_order_by_code,
    scan_purchase_orders_for_rut,
)


class MercadoPublicoTests(unittest.TestCase):
    @patch("casehunter.mercado_publico._get_json")
    def test_lookup_provider(self, mocked):
        mocked.return_value = {"ListaEmpresas": [{"CodigoEmpresa": 17793, "NombreEmpresa": "Proveedor Demo SpA"}]}
        provider = lookup_provider("70.017.820-k", ticket="ticket")
        self.assertEqual(provider["provider_code"], "17793")
        self.assertEqual(provider["name"], "Proveedor Demo SpA")

    @patch("casehunter.mercado_publico._get_json")
    def test_purchase_order_lookup_by_code(self, mocked):
        mocked.return_value = {"Listado": [{"Codigo": "2097-241-SE26", "CodigoEstado": 6, "Estado": "Aceptada"}]}
        order = purchase_order_by_code("2097-241-SE26", ticket="ticket")
        self.assertEqual(order["Codigo"], "2097-241-SE26")
        requested_url = mocked.call_args.args[0]
        self.assertIn("codigo=2097-241-SE26", requested_url)
        self.assertIn("ticket=ticket", requested_url)

    def test_pending_reception_becomes_case(self):
        order = {
            "Codigo":"2097-1-SE26", "Nombre":"Servicio", "CodigoEstado":13, "Estado":"Pendiente de Recepcionar",
            "TipoMoneda":"CLP", "Total":42000000,
            "Comprador":{"NombreOrganismo":"SERVICIO PÚBLICO"},
            "Fechas":{"FechaCreacion":"2026-09-01T10:00:00"},
        }
        candidate = order_to_candidate(order, "Proveedor Demo SpA", date(2026,9,1))
        self.assertEqual(candidate["problems"][0]["type"], "RECEPTION_PENDING")
        self.assertEqual(candidate["amounts_clp"], [42000000])
        self.assertEqual(candidate["agency"], "SERVICIO PÚBLICO")

    def test_accepted_order_is_not_case(self):
        order = {"Codigo":"X", "CodigoEstado":6, "Estado":"Aceptada"}
        self.assertIsNone(order_to_candidate(order, "Proveedor", date.today()))

    @patch("casehunter.mercado_publico.purchase_orders_by_provider_date")
    @patch("casehunter.mercado_publico.lookup_provider")
    def test_rut_scan_deduplicates_orders(self, provider, orders):
        provider.return_value = {"provider_code":"17793", "name":"Proveedor Demo SpA"}
        item = {"Codigo":"OC-1", "CodigoEstado":13, "Estado":"Pendiente de Recepcionar", "TipoMoneda":"CLP", "Total":1000, "Comprador":{}}
        orders.return_value = [item]
        result = scan_purchase_orders_for_rut("70.017.820-k", "2026-09-01", "2026-09-02", ticket="ticket")
        self.assertEqual(result["candidate_count"], 1)
        self.assertEqual(result["pages_scanned"], 2)

    def test_ticket_is_required(self):
        previous = os.environ.pop("MERCADO_PUBLICO_TICKET", None)
        try:
            with self.assertRaises(ValueError): lookup_provider("70.017.820-k")
        finally:
            if previous is not None: os.environ["MERCADO_PUBLICO_TICKET"] = previous

    def test_max_range_enforced(self):
        with self.assertRaises(ValueError):
            scan_purchase_orders_for_rut("70.017.820-k", "2026-01-01", "2026-04-01", ticket="ticket")


if __name__ == "__main__": unittest.main()

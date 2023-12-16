# Copyright (C) 2022 Dorin Hongu <dhongu(@)gmail(.)com
# Copyright (C) 2022 NextERP Romania
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).

import json
import logging

from odoo import api, fields, models
from odoo.tools.safe_eval import safe_eval

_logger = logging.getLogger(__name__)


class ResCompany(models.Model):
    _inherit = "res.company"

    l10n_ro_edi_residence = fields.Integer(string="Period of Residence", default=5)
    l10n_ro_edi_cius_embed_pdf = fields.Boolean(
        string="Embed PDF in CIUS", default=False
    )
    l10n_ro_download_einvoices = fields.Boolean(
        string="Download e-invoices from ANAF", default=False
    )

    def _l10n_ro_get_anaf_efactura_messages(self):
        company_messages = []
        anaf_config = self.l10n_ro_account_anaf_sync_id
        if not anaf_config:
            _logger.warning("No ANAF configuration for company %s", self.name)
            return company_messages
        if not anaf_config.access_token:
            _logger.warning("No access token for company %s", self.name)
            return company_messages
        # We set a parameter to define the number of days to fetch messages from ANAF
        # default 60 days as long as the invoices are available on ANAF
        config_obj = self.env["ir.config_parameter"].sudo()
        param = config_obj.search([("key", "=", "efactura_download_limit_days")])
        if not param:
            config_obj.set_param("efactura_download_limit_days", "60")
        no_days = safe_eval(config_obj.get_param("efactura_download_limit_days"))
        params = {
            "zile": no_days,
            "cif": self.partner_id.l10n_ro_vat_number,
        }
        content, status_code = anaf_config._l10n_ro_einvoice_call(
            "/listaMesajeFactura", params, method="GET"
        )
        if status_code == 200:
            doc = json.loads(content.decode("utf-8"))
            company_messages = list(
                filter(
                    lambda m: m.get("cif") == self.partner_id.l10n_ro_vat_number
                    and m.get("tip") == "FACTURA PRIMITA",
                    doc.get("mesaje") or [],
                )
            )
        return company_messages

    @api.model
    def _l10n_ro_create_anaf_efactura(self):
        # method to be used in cron job to auto download e-invoices from ANAF
        ro_companies = self.search([]).filtered(
            lambda c: c.country_id.code == "RO"
            and c.l10n_ro_account_anaf_sync_id
            and c.l10n_ro_download_einvoices
        )
        new_invoices = self.env["account.move"]
        for company in ro_companies:
            move_obj = self.env["account.move"].with_company(company)
            company_messages = company._l10n_ro_get_anaf_efactura_messages()
            for message in company_messages:
                invoice = move_obj.search(
                    [("l10n_ro_edi_download", "=", message.get("id"))]
                )
                if not invoice:
                    new_invoice = move_obj.with_context(
                        default_move_type="in_invoice"
                    ).create(
                        {
                            "l10n_ro_edi_download": message.get("id"),
                            "l10n_ro_edi_transaction": message.get("id_solicitare"),
                        }
                    )
                    new_invoice.l10n_ro_download_zip_anaf(
                        company.l10n_ro_account_anaf_sync_id
                    )
                    new_invoices += new_invoice

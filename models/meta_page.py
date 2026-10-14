import logging

import requests

from odoo import fields, models

_logger = logging.getLogger(__name__)


class OtmMetaPage(models.Model):
    _name = 'otm.meta.page'
    _description = 'Meta Facebook Page'
    _order = 'name'

    config_id = fields.Many2one('otm.meta.config', required=True, ondelete='cascade', index=True)
    name = fields.Char(string='Page Name', required=True)
    page_id = fields.Char(string='Page ID', required=True, index=True)
    page_access_token = fields.Char(
        string='Page Token', groups='custom_leads_19.group_super_admin,custom_leads_19.group_lead_manager')
    subscribed = fields.Boolean(string='Subscribed to leadgen', readonly=True)

    _page_uniq = models.Constraint('unique(config_id, page_id)', 'This Page is already added.')

    def action_subscribe(self):
        """Subscribe the app to this Page's leadgen events."""
        for page in self:
            token = page.sudo().page_access_token
            if not token:
                continue
            try:
                resp = requests.post(
                    'https://graph.facebook.com/%s/%s/subscribed_apps' % (page.config_id.graph_version, page.page_id),
                    data={'subscribed_fields': 'leadgen', 'access_token': token}, timeout=15)
                page.subscribed = bool(resp.status_code == 200 and resp.json().get('success'))
                if not page.subscribed:
                    _logger.warning("Meta subscribe failed for page %s: %s", page.page_id, resp.text)
            except Exception:
                _logger.exception("Meta subscribe failed for page %s", page.page_id)

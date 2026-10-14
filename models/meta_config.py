import logging
import secrets

from odoo import api, fields, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class OtmMetaConfig(models.Model):
    _name = 'otm.meta.config'
    _description = 'Meta Lead Ads Configuration'

    name = fields.Char(required=True, default='Meta Lead Ads')
    active = fields.Boolean(default=True)
    company_id = fields.Many2one('res.company', string='Company', required=True,
                                 default=lambda self: self.env.company)
    verify_token = fields.Char(
        string='Verify Token', required=True, copy=False,
        default=lambda self: secrets.token_urlsafe(16),
        help='Paste this same value in Meta App Dashboard > Webhooks > Verify Token.')
    page_access_token = fields.Char(
        string='Page Access Token', groups='custom_leads_19.group_super_admin,custom_leads_19.group_lead_manager',
        help='Long-lived Page access token with leads_retrieval, pages_show_list, '
             'pages_manage_ads and pages_read_engagement permissions.')
    app_secret = fields.Char(
        string='App Secret',
        groups='custom_leads_19.group_super_admin,custom_leads_19.group_lead_manager',
        help='Optional but recommended. When set, every webhook call is rejected unless '
             'its X-Hub-Signature-256 header matches.')
    graph_version = fields.Char(string='Graph API Version', default='v21.0', required=True)
    source_name = fields.Char(string='Lead Source Name', default='Meta', required=True,
                              help='Every Meta lead is filed under this Lead Source.')
    create_campaign = fields.Boolean(
        string='Create Source Campaign', default=True,
        help='Create a Source Campaign (named after the Meta campaign) under the Meta source.')
    webhook_url = fields.Char(string='Callback URL', compute='_compute_webhook_url')
    log_count = fields.Integer(compute='_compute_log_count')

    _company_uniq = models.Constraint('unique(company_id)', 'Only one Meta configuration per company.')

    @api.depends('company_id')
    def _compute_webhook_url(self):
        base = self.env['ir.config_parameter'].sudo().get_param('web.base.url') or ''
        for rec in self:
            rec.webhook_url = '%s/otm/meta/webhook' % base.rstrip('/')

    def _compute_log_count(self):
        for rec in self:
            rec.log_count = self.env['otm.meta.lead.log'].sudo().search_count(
                [('company_id', '=', rec.company_id.id)])

    def action_regenerate_token(self):
        for rec in self:
            rec.verify_token = secrets.token_urlsafe(16)

    def action_open_logs(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Meta Leads Log'),
            'res_model': 'otm.meta.lead.log',
            'view_mode': 'list,form',
            'domain': [('company_id', '=', self.company_id.id)],
        }

    def action_test_token(self):
        """Call Graph /me to confirm the Page access token works."""
        import requests
        self.ensure_one()
        if not self.page_access_token:
            raise UserError(_('Enter the Page Access Token first.'))
        try:
            resp = requests.get(
                'https://graph.facebook.com/%s/me' % self.graph_version,
                params={'access_token': self.page_access_token, 'fields': 'id,name'}, timeout=15)
            data = resp.json()
        except Exception as e:
            raise UserError(_('Could not reach Meta Graph API: %s') % e)
        if resp.status_code != 200:
            raise UserError(_('Meta rejected the token: %s') % (data.get('error', {}).get('message') or resp.text))
        return {
            'type': 'ir.actions.client', 'tag': 'display_notification',
            'params': {'title': _('Token OK'), 'type': 'success', 'sticky': False,
                       'message': _('Connected as: %s') % data.get('name')},
        }

    # ── Source / campaign resolution ───────────────────────────────────────
    def _get_source(self):
        self.ensure_one()
        Source = self.env['leads.sources'].sudo()
        source = Source.search([('name', '=ilike', self.source_name)], limit=1)
        if not source:
            source = Source.create({
                'name': self.source_name, 'digital_lead': True,
                'source': 'inbound_source'})
        return source

    def _get_campaign(self, source, campaign_name):
        self.ensure_one()
        if not self.create_campaign or not campaign_name:
            return self.env['lead.source.campaign']
        Campaign = self.env['lead.source.campaign'].sudo().with_context(active_test=False)
        campaign = Campaign.search([
            ('lead_source_id', '=', source.id), ('name', '=ilike', campaign_name)], limit=1)
        if not campaign:
            campaign = Campaign.create({'name': campaign_name, 'lead_source_id': source.id})
        elif not campaign.active:
            campaign.active = True
        return campaign

import json
import logging
import re

import requests

from odoo import api, fields, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class OtmMetaLeadLog(models.Model):
    _name = 'otm.meta.lead.log'
    _description = 'Meta Lead Ads Log'
    _order = 'id desc'
    _rec_name = 'leadgen_id'

    leadgen_id = fields.Char(string='Meta Lead ID', required=True, index=True, readonly=True)
    company_id = fields.Many2one('res.company', required=True, index=True,
                                 default=lambda self: self.env.company)
    state = fields.Selection([
        ('pending', 'Pending'), ('created', 'Lead Created'),
        ('duplicate', 'Duplicate'), ('failed', 'Failed')],
        default='pending', required=True, index=True)
    name = fields.Char(string='Name', readonly=True)
    phone = fields.Char(string='Phone', readonly=True)
    email = fields.Char(string='Email', readonly=True)
    campaign_name = fields.Char(string='Meta Campaign', readonly=True)
    adset_name = fields.Char(string='Ad Set', readonly=True)
    ad_name = fields.Char(string='Ad', readonly=True)
    form_name = fields.Char(string='Form', readonly=True)
    page_id = fields.Char(readonly=True)
    form_id = fields.Char(readonly=True)
    lead_id = fields.Many2one('leads.logic', string='Lead', readonly=True, ondelete='set null')
    error = fields.Text(readonly=True)
    payload = fields.Text(string='Webhook Payload', readonly=True)
    lead_data = fields.Text(string='Graph Lead Data', readonly=True)

    _leadgen_uniq = models.Constraint('unique(leadgen_id, company_id)', 'This Meta lead was already received.')

    # ── Entry point from controller ─────────────────────────────────────────
    @api.model
    def _ingest(self, config, value):
        """value = the 'value' dict of a leadgen change."""
        leadgen_id = str(value.get('leadgen_id') or '')
        if not leadgen_id:
            return self.browse()
        log = self.sudo().search([('leadgen_id', '=', leadgen_id), ('company_id', '=', config.company_id.id)], limit=1)
        if log and log.state in ('created', 'duplicate'):
            return log  # Meta retried an already handled lead
        if not log:
            log = self.sudo().create({
                'leadgen_id': leadgen_id, 'company_id': config.company_id.id,
                'page_id': value.get('page_id'), 'form_id': value.get('form_id'),
                'payload': json.dumps(value)})
        log._process(config)
        return log

    # ── Processing ──────────────────────────────────────────────────────────
    def _process(self, config):
        for log in self:
            try:
                with self.env.cr.savepoint():
                    log._process_one(config)
            except Exception as e:
                _logger.exception("Meta lead %s failed", log.leadgen_id)
                log.write({'state': 'failed', 'error': str(e)})

    def _graph_get(self, config, path, params=None):
        params = dict(params or {}, access_token=config.sudo().page_access_token)
        resp = requests.get(
            'https://graph.facebook.com/%s/%s' % (config.graph_version, path),
            params=params, timeout=15)
        data = resp.json()
        if resp.status_code != 200:
            raise UserError(_('Graph API error: %s') % (data.get('error', {}).get('message') or resp.text))
        return data

    @staticmethod
    def _parse_fields(field_data):
        name = first = last = ''
        email = phone = False
        for f in field_data or []:
            key = (f.get('name') or '').lower()
            vals = f.get('values') or []
            val = (vals[0] if vals else '') or ''
            if key in ('full_name', 'name'):
                name = val
            elif key == 'first_name':
                first = val
            elif key == 'last_name':
                last = val
            elif 'email' in key:
                email = val
            elif 'phone' in key or 'mobile' in key or 'whatsapp' in key:
                phone = phone or val
        name = name or ('%s %s' % (first, last)).strip()
        return name, phone, email

    def _process_one(self, config):
        self.ensure_one()
        if not config.sudo().page_access_token:
            raise UserError(_('Page Access Token is not configured.'))
        data = self._graph_get(config, self.leadgen_id, {
            'fields': 'id,created_time,ad_id,ad_name,adset_id,adset_name,campaign_id,'
                      'campaign_name,form_id,field_data'})
        name, phone, email = self._parse_fields(data.get('field_data'))
        form_id = data.get('form_id') or self.form_id
        form_name = False
        if form_id:
            try:
                form_name = self._graph_get(config, form_id, {'fields': 'name'}).get('name')
            except Exception:
                _logger.warning("Meta: could not read form name for %s", form_id)

        campaign_name = data.get('campaign_name')
        ad_name = data.get('ad_name')
        self.write({
            'name': name or False, 'phone': phone, 'email': email,
            'campaign_name': campaign_name, 'adset_name': data.get('adset_name'),
            'ad_name': ad_name, 'form_name': form_name,
            'lead_data': json.dumps(data), 'error': False})

        if not phone:
            raise UserError(_('The Meta form did not collect a phone number, so no lead can be created.'))
        phone = re.sub(r'[\s\-()]', '', phone)

        Lead = self.env['leads.logic'].sudo()
        tail = re.sub(r'\D', '', phone)[-10:]
        existing = Lead.search([('phone_number', 'like', '%' + tail)], limit=1) if tail else Lead
        if existing:
            existing.message_post(body=_(
                'Re-enquiry received from Meta Lead Ads (campaign: %(c)s, form: %(f)s).',
                c=campaign_name or '-', f=form_name or '-'))
            self.write({'state': 'duplicate', 'lead_id': existing.id})
            return

        source = config._get_source()
        campaign = config._get_campaign(source, campaign_name or form_name or 'Meta Ads')
        vals = {
            'name': name or 'Meta Lead',
            'phone_number': phone,
            'email_address': email or False,
            'leads_source': source.id,
            'digital_lead': True,
            'meta_leadgen_id': self.leadgen_id,
            'meta_form_name': form_name,
            'meta_ad_name': ad_name,
        }
        if campaign:
            vals['source_campaign_id'] = campaign.id
        lead = Lead.create(vals)
        self.write({'state': 'created', 'lead_id': lead.id})

    def action_retry(self):
        for log in self:
            config = self.env['otm.meta.config'].sudo().search(
                [('company_id', '=', log.company_id.id)], limit=1)
            if not config:
                raise UserError(_('No Meta configuration for this company.'))
            log._process(config)

    def action_open_lead(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_window', 'res_model': 'leads.logic',
                'res_id': self.lead_id.id, 'view_mode': 'form'}

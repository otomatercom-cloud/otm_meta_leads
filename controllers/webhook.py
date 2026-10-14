import hashlib
import hmac
import json
import logging

from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)


class OtmMetaWebhook(http.Controller):

    def _config(self):
        return request.env['otm.meta.config'].sudo().search([], limit=1)

    @http.route('/otm/meta/webhook', type='http', auth='public', csrf=False, methods=['GET', 'POST'])
    def webhook(self, **kw):
        if request.httprequest.method == 'GET':
            token = kw.get('hub.verify_token')
            configs = request.env['otm.meta.config'].sudo().search([('verify_token', '=', token or '__none__')], limit=1)
            if kw.get('hub.mode') == 'subscribe' and configs:
                return request.make_response(kw.get('hub.challenge') or '', status=200)
            return request.make_response('Forbidden', status=403)

        raw = request.httprequest.get_data()
        try:
            data = json.loads(raw.decode() or '{}')
        except Exception:
            return request.make_response('Bad Request', status=400)

        Config = request.env['otm.meta.config'].sudo()
        configs = Config.search([])
        if not configs:
            return request.make_response('Not configured', status=200)

        signature = request.httprequest.headers.get('X-Hub-Signature-256', '')
        config = False
        for cfg in configs:
            secret = cfg.app_secret
            if not secret:
                config = cfg
                break
            expected = 'sha256=' + hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
            if hmac.compare_digest(expected, signature):
                config = cfg
                break
        if not config:
            _logger.warning("Meta webhook: invalid signature")
            return request.make_response('Invalid signature', status=403)

        Log = request.env['otm.meta.lead.log'].with_company(config.company_id)
        try:
            if data.get('object') == 'page':
                for entry in data.get('entry', []):
                    for change in entry.get('changes', []):
                        if change.get('field') == 'leadgen':
                            Log._ingest(config, change.get('value') or {})
        except Exception:
            _logger.exception("Meta webhook processing failed")
            request.env.cr.rollback()
        # Always 200: failures are stored in the log and can be retried from the UI.
        return request.make_response('OK', status=200)

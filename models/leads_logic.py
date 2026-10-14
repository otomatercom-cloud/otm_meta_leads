from odoo import fields, models


class LeadsLogic(models.Model):
    _inherit = 'leads.logic'

    meta_leadgen_id = fields.Char(string='Meta Lead ID', index=True, copy=False, readonly=True)
    meta_form_name = fields.Char(string='Meta Form', copy=False, readonly=True)
    meta_ad_name = fields.Char(string='Meta Ad', copy=False, readonly=True)

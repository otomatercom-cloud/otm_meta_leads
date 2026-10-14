{
    'name': 'Otomater Meta Lead Ads',
    'version': '19.0.1.0.0',
    'summary': 'Facebook/Instagram Lead Ads → Leads (Source "Meta", Source Campaign = Meta campaign)',
    'description': """
Receives Meta (Facebook / Instagram) Lead Ads through the Graph API webhook and
creates leads in custom_leads_19 (leads.logic):
  * Lead Source  = "Meta"
  * Source Campaign = the Meta campaign name (auto-created under the Meta source)
  * Duplicate phone check, full receive log, one-click retry for failed leads.
""",
    'author': 'Otomater',
    'website': 'https://www.otomater.com',
    'category': 'Sales/CRM',
    'license': 'OPL-1',
    'depends': ['custom_leads_19'],
    'data': [
        'security/ir.model.access.csv',
        'data/meta_data.xml',
        'views/meta_lead_log_views.xml',
        'views/meta_config_views.xml',
    ],
    'installable': True,
    'application': False,
}

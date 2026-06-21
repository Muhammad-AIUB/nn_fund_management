# -*- coding: utf-8 -*-
{
    'name': 'NN Fund Management',
    'version': '17.0.1.0.0',
    'summary': 'Manage incoming funds, allocations, requisitions, bills and '
               'transfers with GM/MD approval and strict balance control.',
    'description': "Custom fund management module for NN Services & "
                   "Engineering Ltd. See README.md for full documentation.",
    'author': 'Muhammad AIUB',
    'category': 'Accounting/Finance',
    'license': 'LGPL-3',
    'depends': ['base', 'mail'],
    'data': [
        'security/security_groups.xml',
        'security/ir.model.access.csv',
        'security/record_rules.xml',
        'data/sequences.xml',
        'data/expense_head_data.xml',
        'data/approval_rule_data.xml',
        'data/mail_alias_data.xml',
        'wizard/approval_wizard_views.xml',
        'views/approval_rule_views.xml',
        'views/fund_account_views.xml',
        'views/incoming_fund_views.xml',
        'views/bank_email_views.xml',
        'views/project_views.xml',
        'views/expense_head_views.xml',
        'views/fund_allocation_views.xml',
        'views/fund_requisition_views.xml',
        'views/bill_views.xml',
        'views/fund_transfer_views.xml',
        'views/approval_history_views.xml',
        'views/fund_dashboard_views.xml',
        'views/menus.xml',
        'views/res_config_settings_views.xml',
    ],
    'demo': [
        'demo/demo_data.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'nn_fund_management/static/src/scss/form_buttons.scss',
        ],
    },
    'application': True,
    'installable': True,
    'post_init_hook': 'post_init_hook',
}

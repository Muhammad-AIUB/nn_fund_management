# -*- coding: utf-8 -*-
{
    'name': 'NN Fund Management',
    'version': '17.0.1.0.0',
    'summary': 'Manage incoming funds, allocations, requisitions, bills and '
               'transfers with GM/MD approval and strict balance control.',
    'description': """
NN Fund Management
==================
Custom module for NN Services & Engineering Ltd. to manage the full lifecycle
of company funds:

* Fund accounts and incoming funds
* Project and expense-head allocations
* Fund requisitions and bills
* Transfers between projects / expense heads
* GM and MD approval workflow
* Available / held / assigned / spent balance tracking
* Approval and audit history

The system guarantees that the same money cannot be allocated, transferred or
spent more than once.
""",
    'author': 'Muhammad AIUB',
    'category': 'Accounting/Finance',
    'license': 'LGPL-3',
    'depends': ['base', 'mail'],
    'data': [
        'security/security_groups.xml',
        'security/ir.model.access.csv',
        'data/sequences.xml',
        'data/expense_head_data.xml',
        'wizard/approval_wizard_views.xml',
        'views/fund_account_views.xml',
        'views/incoming_fund_views.xml',
        'views/project_views.xml',
        'views/expense_head_views.xml',
        'views/approval_history_views.xml',
        'views/menus.xml',
    ],
    'application': True,
    'installable': True,
}

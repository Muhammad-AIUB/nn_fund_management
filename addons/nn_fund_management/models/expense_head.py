# -*- coding: utf-8 -*-
from odoo import fields, models


class ExpenseHead(models.Model):
    """An expense category (office rent, salary, utilities, ...) that funds can
    be allocated to. Shares the same balance logic as projects."""
    _name = 'nn.expense.head'
    _description = 'Expense Head'
    _inherit = ['nn.fund.target.mixin', 'mail.thread']
    _order = 'name'

    name = fields.Char(string='Expense Head', required=True, tracking=True)
    code = fields.Char(string='Code', copy=False)
    description = fields.Text()
    active = fields.Boolean(default=True)

    _sql_constraints = [
        ('unique_expense_head_code', 'unique(code, company_id)',
         'Expense head code must be unique per company.'),
    ]

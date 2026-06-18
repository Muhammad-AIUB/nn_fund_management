# -*- coding: utf-8 -*-
from odoo import api, fields, models


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

    allocation_ids = fields.One2many(
        'nn.fund.allocation', 'expense_head_id', string='Allocations')
    requisition_ids = fields.One2many(
        'nn.fund.requisition', 'expense_head_id', string='Requisitions')
    transfer_out_ids = fields.One2many(
        'nn.fund.transfer', 'source_expense_id', string='Outgoing Transfers')
    transfer_in_ids = fields.One2many(
        'nn.fund.transfer', 'dest_expense_id', string='Incoming Transfers')

    _sql_constraints = [
        ('unique_expense_head_code', 'unique(code, company_id)',
         'Expense head code must be unique per company.'),
    ]

    @api.depends('allocation_ids.amount', 'allocation_ids.state',
                 'requisition_ids.amount', 'requisition_ids.state',
                 'requisition_ids.remaining_billable',
                 'requisition_ids.billed_amount',
                 'transfer_out_ids.amount', 'transfer_out_ids.state',
                 'transfer_in_ids.amount', 'transfer_in_ids.state')
    def _compute_fund_balances(self):
        return super()._compute_fund_balances()

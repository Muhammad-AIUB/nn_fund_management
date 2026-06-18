# -*- coding: utf-8 -*-
from odoo import api, fields, models


class Project(models.Model):
    """A project that funds can be allocated to, requisitioned from and
    transferred between. Balances come from the shared fund-target mixin."""
    _name = 'nn.project'
    _description = 'Fund Project'
    _inherit = ['nn.fund.target.mixin', 'mail.thread']
    _order = 'name'

    name = fields.Char(string='Project Name', required=True, tracking=True)
    code = fields.Char(string='Code', copy=False)
    manager_id = fields.Many2one('res.users', string='Project Manager')
    partner_id = fields.Many2one('res.partner', string='Client')
    date_start = fields.Date(string='Start Date')
    date_end = fields.Date(string='End Date')
    description = fields.Text()
    active = fields.Boolean(default=True)
    state = fields.Selection(
        selection=[('open', 'Open'), ('closed', 'Closed')],
        string='Status', default='open', tracking=True)

    allocation_ids = fields.One2many(
        'nn.fund.allocation', 'project_id', string='Allocations')

    _sql_constraints = [
        ('unique_project_code', 'unique(code, company_id)',
         'Project code must be unique per company.'),
    ]

    @api.depends('allocation_ids.amount', 'allocation_ids.state')
    def _compute_fund_balances(self):
        return super()._compute_fund_balances()

    def _get_balance_components(self):
        res = super()._get_balance_components()
        approved = self.allocation_ids.filtered(lambda a: a.state == 'approved')
        res['total_allocated'] = sum(approved.mapped('amount'))
        return res

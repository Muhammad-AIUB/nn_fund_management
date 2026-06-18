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
    requisition_ids = fields.One2many(
        'nn.fund.requisition', 'project_id', string='Requisitions')
    transfer_out_ids = fields.One2many(
        'nn.fund.transfer', 'source_project_id', string='Outgoing Transfers')
    transfer_in_ids = fields.One2many(
        'nn.fund.transfer', 'dest_project_id', string='Incoming Transfers')

    _sql_constraints = [
        ('unique_project_code', 'unique(code, company_id)',
         'Project code must be unique per company.'),
    ]

    @api.depends('allocation_ids.amount', 'allocation_ids.state',
                 'requisition_ids.amount', 'requisition_ids.state',
                 'requisition_ids.remaining_billable',
                 'requisition_ids.billed_amount',
                 'transfer_out_ids.amount', 'transfer_out_ids.state',
                 'transfer_in_ids.amount', 'transfer_in_ids.state')
    def _compute_fund_balances(self):
        return super()._compute_fund_balances()

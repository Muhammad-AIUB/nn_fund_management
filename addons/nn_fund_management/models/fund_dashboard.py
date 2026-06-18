# -*- coding: utf-8 -*-
from odoo import api, fields, models


class FundDashboard(models.TransientModel):
    """Lightweight, read-only overview of the whole fund position.

    A transient model whose fields are computed live from the underlying
    records each time the dashboard is opened, so the figures are always current
    without storing any duplicate state.
    """
    _name = 'nn.fund.dashboard'
    _description = 'Fund Management Dashboard'

    currency_id = fields.Many2one(
        'res.currency', default=lambda self: self.env.company.currency_id)

    total_received = fields.Monetary(compute='_compute_kpis')
    unassigned_balance = fields.Monetary(compute='_compute_kpis')
    held_amount = fields.Monetary(compute='_compute_kpis')
    assigned_amount = fields.Monetary(compute='_compute_kpis')
    spent_amount = fields.Monetary(compute='_compute_kpis')
    pending_approval_count = fields.Integer(compute='_compute_kpis')

    project_ids = fields.Many2many('nn.project', compute='_compute_lists')
    expense_head_ids = fields.Many2many(
        'nn.expense.head', compute='_compute_lists')
    pending_allocation_ids = fields.Many2many(
        'nn.fund.allocation', compute='_compute_lists')
    pending_requisition_ids = fields.Many2many(
        'nn.fund.requisition', compute='_compute_lists')
    pending_transfer_ids = fields.Many2many(
        'nn.fund.transfer', compute='_compute_lists')
    recent_history_ids = fields.Many2many(
        'nn.approval.history', compute='_compute_lists')

    def _compute_kpis(self):
        accounts = self.env['nn.fund.account'].search([])
        projects = self.env['nn.project'].search([])
        expenses = self.env['nn.expense.head'].search([])
        pending = sum(
            self.env[model].search_count([('state', '=', 'submitted')])
            for model in ('nn.fund.allocation', 'nn.fund.requisition',
                          'nn.fund.transfer'))
        for rec in self:
            rec.total_received = sum(accounts.mapped('total_received'))
            rec.unassigned_balance = sum(accounts.mapped('available_balance'))
            rec.held_amount = sum(accounts.mapped('on_hold_amount'))
            rec.assigned_amount = sum(accounts.mapped('assigned_amount'))
            rec.spent_amount = (sum(projects.mapped('total_spent'))
                                + sum(expenses.mapped('total_spent')))
            rec.pending_approval_count = pending

    def _compute_lists(self):
        projects = self.env['nn.project'].search([], limit=80)
        expenses = self.env['nn.expense.head'].search([], limit=80)
        alloc = self.env['nn.fund.allocation'].search(
            [('state', '=', 'submitted')])
        req = self.env['nn.fund.requisition'].search(
            [('state', '=', 'submitted')])
        trf = self.env['nn.fund.transfer'].search(
            [('state', '=', 'submitted')])
        recent_limit = int(self.env['ir.config_parameter'].sudo().get_param(
            'nn_fund_management.dashboard_recent_limit', 20))
        history = self.env['nn.approval.history'].search(
            [], limit=recent_limit)
        for rec in self:
            rec.project_ids = projects
            rec.expense_head_ids = expenses
            rec.pending_allocation_ids = alloc
            rec.pending_requisition_ids = req
            rec.pending_transfer_ids = trf
            rec.recent_history_ids = history

    @api.model
    def action_open_dashboard(self):
        """Open a fresh dashboard record (one per click)."""
        return {
            'type': 'ir.actions.act_window',
            'name': 'Fund Dashboard',
            'res_model': 'nn.fund.dashboard',
            'view_mode': 'form',
            'target': 'current',
            'res_id': self.create({}).id,
        }

# -*- coding: utf-8 -*-
from odoo import fields, models


class ApprovalHistory(models.Model):
    """Immutable log of every workflow action on a fund document.

    One row is written for each create / submit / approve / reject / cancel /
    close action across allocations, requisitions and transfers. The link to the
    source document is generic (``res_model`` + ``res_id``) so a single model
    serves all document types and satisfies the audit-history requirement
    (creator, approver, previous/new status, date, comment, amount, related
    account / project / expense head, reference document).

    Records are written through ``sudo()`` by the approval mixin and are not
    user-deletable, so the trail cannot be tampered with.
    """
    _name = 'nn.approval.history'
    _description = 'Approval / Audit History'
    _order = 'action_date desc, id desc'

    res_model = fields.Char(string='Document Model', required=True, index=True)
    res_id = fields.Integer(string='Document ID', required=True, index=True)
    document_ref = fields.Char(string='Document')

    action = fields.Selection(
        selection=[
            ('create', 'Created'),
            ('submit', 'Submitted'),
            ('approve', 'Approved (step)'),
            ('gm_approve', 'GM Approved'),
            ('md_approve', 'MD Approved'),
            ('reject', 'Rejected'),
            ('cancel', 'Cancelled'),
            ('close', 'Closed'),
            ('reset', 'Reset to Draft'),
            ('post', 'Bill Posted'),
            ('reverse', 'Bill Reversed'),
        ], string='Action', required=True)
    approval_level = fields.Selection(
        selection=[('gm', 'General Manager'), ('md', 'Managing Director')],
        string='Approval Level')
    step_label = fields.Char(string='Approval Step')

    user_id = fields.Many2one(
        'res.users', string='Done By', required=True,
        default=lambda self: self.env.user)
    action_date = fields.Datetime(
        string='Date', required=True, default=fields.Datetime.now)

    from_state = fields.Char(string='Previous Status')
    to_state = fields.Char(string='New Status')
    comment = fields.Text(string='Comment')

    amount = fields.Monetary(string='Amount')
    currency_id = fields.Many2one('res.currency', string='Currency')

    fund_account_id = fields.Many2one('nn.fund.account', string='Fund Account')
    project_id = fields.Many2one('nn.project', string='Project')
    expense_head_id = fields.Many2one('nn.expense.head', string='Expense Head')

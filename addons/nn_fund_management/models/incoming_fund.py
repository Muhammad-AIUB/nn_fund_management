# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import AccessError, ValidationError


class IncomingFund(models.Model):
    """Money received into a fund account.

    A record starts in ``draft``. Confirming it (a finance-only action) makes
    the amount count towards the account's unassigned balance. The same
    transaction reference can never be reused inside one fund account, enforced
    by a database-level unique constraint so it holds even under concurrency.
    """
    _name = 'nn.incoming.fund'
    _description = 'Incoming Fund'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'date desc, id desc'

    name = fields.Char(
        string='Reference', default='New', copy=False, readonly=True, index=True)
    fund_account_id = fields.Many2one(
        'nn.fund.account', string='Fund Account', required=True,
        tracking=True, ondelete='restrict')
    date = fields.Date(
        string='Date', required=True, tracking=True,
        default=fields.Date.context_today)
    amount = fields.Monetary(string='Amount', required=True, tracking=True)
    currency_id = fields.Many2one(
        'res.currency', related='fund_account_id.currency_id',
        store=True, readonly=True)
    company_id = fields.Many2one(
        'res.company', string='Company', required=True,
        default=lambda self: self.env.company)

    transaction_reference = fields.Char(
        string='Transaction Reference', required=True, tracking=True)
    source = fields.Char(string='Sender / Source')
    description = fields.Text(string='Description')
    attachment_ids = fields.Many2many('ir.attachment', string='Attachments')

    state = fields.Selection(
        selection=[
            ('draft', 'Draft'),
            ('pending_verification', 'Pending Verification'),
            ('confirmed', 'Confirmed'),
            ('cancelled', 'Cancelled'),
        ], string='Status', default='draft', required=True, tracking=True)
    source_email_id = fields.Many2one(
        'nn.bank.email', string='Source Bank Email', readonly=True, copy=False)

    _sql_constraints = [
        ('unique_txn_ref_per_account',
         'unique(fund_account_id, transaction_reference)',
         'This transaction reference is already used in the selected fund '
         'account. References must be unique per fund account.'),
    ]

    @api.constrains('amount')
    def _check_amount_positive(self):
        for rec in self:
            if rec.amount <= 0:
                raise ValidationError(_("The amount must be greater than zero."))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = self.env['ir.sequence'].sudo().next_by_code(
                    'nn.incoming.fund') or 'New'
        return super().create(vals_list)

    def _ensure_finance_user(self):
        """Confirming incoming funds is a finance-only action (server side)."""
        if not self.env.user.has_group(
                'nn_fund_management.group_finance_user'):
            raise AccessError(_(
                "Only Finance users can confirm incoming funds."))

    def action_confirm(self):
        self._ensure_finance_user()
        for rec in self:
            if rec.state not in ('draft', 'pending_verification'):
                raise ValidationError(_(
                    "Only draft or pending-verification incoming funds can be "
                    "confirmed."))
            rec.state = 'confirmed'

    def action_cancel(self):
        for rec in self:
            rec.state = 'cancelled'

    def action_set_to_draft(self):
        for rec in self:
            if rec.state == 'cancelled':
                rec.state = 'draft'

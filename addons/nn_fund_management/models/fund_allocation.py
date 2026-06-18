# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError


class FundAllocation(models.Model):
    """Assigns unassigned funds from a fund account to a project or expense head.

    Money effect (all realised through computed balances, never direct writes):

    * submitted / gm_approved  -> amount is **on hold** on the fund account
      (removed from the unassigned/available balance, reserved).
    * approved                 -> amount becomes **assigned** on the account and
      **allocated** to the chosen project / expense head.
    * rejected / cancelled     -> hold is released, amount returns to unassigned.

    Because the balances are derived from the document's state, approving twice
    (or any repeated action) can never move the money twice.
    """
    _name = 'nn.fund.allocation'
    _description = 'Fund Allocation Request'
    _inherit = ['nn.approval.mixin', 'mail.thread', 'mail.activity.mixin']
    _order = 'request_date desc, id desc'

    name = fields.Char(string='Request Number', default='New', copy=False,
                       readonly=True, index=True)
    fund_account_id = fields.Many2one(
        'nn.fund.account', string='Fund Account', required=True,
        tracking=True, ondelete='restrict')
    currency_id = fields.Many2one(
        related='fund_account_id.currency_id', store=True, readonly=True)
    company_id = fields.Many2one(
        'res.company', string='Company', required=True,
        default=lambda self: self.env.company)

    target_type = fields.Selection(
        selection=[('project', 'Project'), ('expense_head', 'Expense Head')],
        string='Allocate To', required=True, default='project', tracking=True)
    project_id = fields.Many2one('nn.project', string='Project',
                                 tracking=True, ondelete='restrict')
    expense_head_id = fields.Many2one('nn.expense.head', string='Expense Head',
                                      tracking=True, ondelete='restrict')

    amount = fields.Monetary(string='Amount', required=True, tracking=True)
    purpose = fields.Text(string='Purpose')
    attachment_ids = fields.Many2many('ir.attachment', string='Attachments')

    # Convenience: available balance of the source, shown on the form.
    account_available = fields.Monetary(
        related='fund_account_id.available_balance', readonly=True,
        string='Account Available')

    _sql_constraints = [
        ('check_amount_positive', 'CHECK(amount > 0)',
         'The allocation amount must be greater than zero.'),
    ]

    # ------------------------------------------------------------------
    # Constraints
    # ------------------------------------------------------------------
    @api.constrains('target_type', 'project_id', 'expense_head_id')
    def _check_single_target(self):
        for rec in self:
            if rec.target_type == 'project':
                if not rec.project_id:
                    raise ValidationError(_("Please select a project."))
                if rec.expense_head_id:
                    raise ValidationError(_(
                        "An allocation must use either a project or an expense "
                        "head, not both."))
            else:
                if not rec.expense_head_id:
                    raise ValidationError(_("Please select an expense head."))
                if rec.project_id:
                    raise ValidationError(_(
                        "An allocation must use either a project or an expense "
                        "head, not both."))

    @api.onchange('target_type')
    def _onchange_target_type(self):
        if self.target_type == 'project':
            self.expense_head_id = False
        else:
            self.project_id = False

    # ------------------------------------------------------------------
    # Approval hooks
    # ------------------------------------------------------------------
    def _check_can_submit(self):
        """Block submission if it would overdraw the account's unassigned
        balance. Server-side guarantee against double-allocation."""
        self.ensure_one()
        available = self.fund_account_id.available_balance
        if self.amount > available:
            raise UserError(_(
                "Requested amount (%(req)s) exceeds the available unassigned "
                "balance of %(acc)s (%(avail)s).",
                req=self.amount, acc=self.fund_account_id.display_name,
                avail=available))

    def _approval_log_extra(self):
        self.ensure_one()
        return {
            'fund_account_id': self.fund_account_id.id,
            'project_id': self.project_id.id,
            'expense_head_id': self.expense_head_id.id,
        }

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = self.env['ir.sequence'].sudo().next_by_code(
                    'nn.fund.allocation') or 'New'
        records = super().create(vals_list)
        for rec in records:
            rec._log_approval('create', from_state=False, to_state='draft')
        return records

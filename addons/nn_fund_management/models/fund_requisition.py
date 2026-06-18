# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError


class FundRequisition(models.Model):
    """Requests funds from a project or expense head, to be drawn down by bills.

    Money effect on the target (all via computed balances):

    * submitted / gm_approved -> amount is **requisition hold** on the target
      (reserved, cannot be requisitioned or transferred again).
    * approved                -> the remaining billable amount is reserved as
      **approved-but-unspent**, waiting for bills to draw it down.
    * rejected / cancelled    -> the hold is released to the available balance.
    * closed                  -> any unbilled remainder is released; billed
      amounts already count as spent (through the bills).
    """
    _name = 'nn.fund.requisition'
    _description = 'Fund Requisition'
    _inherit = ['nn.approval.mixin', 'mail.thread', 'mail.activity.mixin']
    _order = 'request_date desc, id desc'

    name = fields.Char(string='Requisition Number', default='New', copy=False,
                       readonly=True, index=True)
    company_id = fields.Many2one(
        'res.company', string='Company', required=True,
        default=lambda self: self.env.company)
    currency_id = fields.Many2one(
        'res.currency', default=lambda self: self.env.company.currency_id,
        readonly=True)

    target_type = fields.Selection(
        selection=[('project', 'Project'), ('expense_head', 'Expense Head')],
        string='Requisition From', required=True, default='project',
        tracking=True)
    project_id = fields.Many2one('nn.project', string='Project',
                                 tracking=True, ondelete='restrict')
    expense_head_id = fields.Many2one('nn.expense.head', string='Expense Head',
                                      tracking=True, ondelete='restrict')

    amount = fields.Monetary(string='Requested Amount', required=True,
                             tracking=True)
    purpose = fields.Text(string='Purpose')
    required_date = fields.Date(string='Required Date')
    attachment_ids = fields.Many2many('ir.attachment', string='Attachments')

    target_available = fields.Monetary(
        string='Available at Source', compute='_compute_target_available')

    billed_amount = fields.Monetary(
        string='Billed Amount', compute='_compute_billing', store=True)
    remaining_billable = fields.Monetary(
        string='Remaining Billable', compute='_compute_billing', store=True,
        help="Approved amount still available to bill against.")

    # 'closed' extends the shared approval states.
    state = fields.Selection(
        selection_add=[('closed', 'Closed')],
        ondelete={'closed': 'set default'})

    _sql_constraints = [
        ('check_amount_positive', 'CHECK(amount > 0)',
         'The requested amount must be greater than zero.'),
    ]

    # ------------------------------------------------------------------
    # Computes
    # ------------------------------------------------------------------
    @api.depends('target_type', 'project_id', 'expense_head_id',
                 'project_id.available_fund',
                 'expense_head_id.available_fund')
    def _compute_target_available(self):
        for rec in self:
            target = rec._get_target()
            rec.target_available = target.available_fund if target else 0.0

    def _get_billed_amount(self):
        """Total posted (non-reversed) bills against this requisition.
        Returns 0 until the bill model is added; overridden there."""
        self.ensure_one()
        return 0.0

    @api.depends('amount', 'state')
    def _compute_billing(self):
        for rec in self:
            billed = rec._get_billed_amount()
            rec.billed_amount = billed
            if rec.state in ('approved', 'closed'):
                rec.remaining_billable = max(rec.amount - billed, 0.0)
            else:
                rec.remaining_billable = 0.0

    # ------------------------------------------------------------------
    # Helpers / constraints
    # ------------------------------------------------------------------
    def _get_target(self):
        self.ensure_one()
        return (self.project_id if self.target_type == 'project'
                else self.expense_head_id)

    @api.constrains('target_type', 'project_id', 'expense_head_id')
    def _check_single_target(self):
        for rec in self:
            if rec.target_type == 'project':
                if not rec.project_id:
                    raise ValidationError(_("Please select a project."))
                if rec.expense_head_id:
                    raise ValidationError(_(
                        "Use either a project or an expense head, not both."))
            else:
                if not rec.expense_head_id:
                    raise ValidationError(_("Please select an expense head."))
                if rec.project_id:
                    raise ValidationError(_(
                        "Use either a project or an expense head, not both."))

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
        self.ensure_one()
        available = self.target_available
        if self.amount > available:
            raise UserError(_(
                "Requested amount (%(req)s) exceeds the available balance of "
                "%(tgt)s (%(avail)s).",
                req=self.amount, tgt=self._get_target().display_name,
                avail=available))

    def _approval_log_extra(self):
        self.ensure_one()
        return {
            'project_id': self.project_id.id,
            'expense_head_id': self.expense_head_id.id,
        }

    # ------------------------------------------------------------------
    # Close
    # ------------------------------------------------------------------
    def action_close(self):
        for rec in self:
            if rec.state != 'approved':
                raise UserError(_(
                    "Only approved requisitions can be closed."))
            from_state = rec.state
            rec.state = 'closed'
            rec._log_approval('close', from_state=from_state, to_state='closed')
        return True

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = self.env['ir.sequence'].next_by_code(
                    'nn.fund.requisition') or 'New'
        records = super().create(vals_list)
        for rec in records:
            rec._log_approval('create', from_state=False, to_state='draft')
        return records

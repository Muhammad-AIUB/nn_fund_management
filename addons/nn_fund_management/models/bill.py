# -*- coding: utf-8 -*-
import logging

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)


class Bill(models.Model):
    """A bill drawn against an approved fund requisition.

    Enforced rules (server side):

    * The requisition must be **approved** to be billed.
    * The bill's target must match the requisition's target - Project A can
      never bill Project B's requisition, nor one expense head another's.
    * A bill can never exceed the requisition's **remaining billable** amount;
      several partial bills are allowed but their total can't exceed the
      approved amount.
    * Posting marks the amount as spent and reduces the remaining billable;
      cancelling a posted bill returns that amount - it never creates new funds
      (the requisition's billed amount is simply recomputed from posted bills).
    """
    _name = 'nn.bill'
    _description = 'Bill'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'bill_date desc, id desc'

    name = fields.Char(string='Bill Number', default='New', copy=False,
                       readonly=True, index=True)
    company_id = fields.Many2one(
        'res.company', string='Company', required=True,
        default=lambda self: self.env.company)
    currency_id = fields.Many2one(
        'res.currency', default=lambda self: self.env.company.currency_id,
        readonly=True)

    requisition_id = fields.Many2one(
        'nn.fund.requisition', string='Requisition', required=True,
        tracking=True, ondelete='restrict',
        domain="[('state', '=', 'approved')]")
    target_type = fields.Selection(
        selection=[('project', 'Project'), ('expense_head', 'Expense Head')],
        string='Type', readonly=True)
    project_id = fields.Many2one('nn.project', string='Project', readonly=True)
    expense_head_id = fields.Many2one('nn.expense.head', string='Expense Head',
                                      readonly=True)

    amount = fields.Monetary(string='Bill Amount', required=True, tracking=True)
    bill_date = fields.Date(string='Bill Date', required=True,
                            default=fields.Date.context_today)
    partner_id = fields.Many2one('res.partner', string='Vendor')
    reference = fields.Char(string='Vendor Reference')
    description = fields.Text(string='Description')
    attachment_ids = fields.Many2many('ir.attachment', string='Attachments')

    requisition_remaining = fields.Monetary(
        related='requisition_id.remaining_billable', readonly=True,
        string='Remaining Billable')

    state = fields.Selection(
        selection=[
            ('draft', 'Draft'),
            ('posted', 'Posted'),
            ('cancelled', 'Cancelled'),
        ], string='Status', default='draft', required=True, tracking=True,
        copy=False)

    _sql_constraints = [
        ('check_amount_positive', 'CHECK(amount > 0)',
         'The bill amount must be greater than zero.'),
    ]

    # ------------------------------------------------------------------
    # Onchange / constraints
    # ------------------------------------------------------------------
    @api.onchange('requisition_id')
    def _onchange_requisition_id(self):
        """Copy the target from the requisition so it cannot be mismatched."""
        req = self.requisition_id
        self.target_type = req.target_type
        self.project_id = req.project_id
        self.expense_head_id = req.expense_head_id

    @api.constrains('requisition_id', 'target_type', 'project_id',
                    'expense_head_id')
    def _check_target_matches_requisition(self):
        for rec in self:
            req = rec.requisition_id
            if not req:
                continue
            if (rec.target_type != req.target_type
                    or rec.project_id != req.project_id
                    or rec.expense_head_id != req.expense_head_id):
                raise ValidationError(_(
                    "A bill must use the same project / expense head as its "
                    "requisition (%s).", req.display_name))

    # ------------------------------------------------------------------
    # History
    # ------------------------------------------------------------------
    def _log_history(self, action, from_state, to_state):
        self.ensure_one()
        self.env['nn.approval.history'].sudo().create({
            'res_model': self._name,
            'res_id': self.id,
            'document_ref': self.display_name,
            'action': action,
            'from_state': from_state,
            'to_state': to_state,
            'amount': self.amount,
            'currency_id': self.currency_id.id,
            'project_id': self.project_id.id,
            'expense_head_id': self.expense_head_id.id,
        })

    # ------------------------------------------------------------------
    # Workflow
    # ------------------------------------------------------------------
    def action_post(self):
        for rec in self:
            if rec.state != 'draft':
                raise UserError(_("Only draft bills can be posted."))
            req = rec.requisition_id
            if req.state != 'approved':
                raise UserError(_(
                    "Bills can only be posted against an approved requisition."))
            rec._check_target_matches_requisition()
            if rec.amount > req.remaining_billable:
                raise UserError(_(
                    "Bill amount (%(amt)s) exceeds the requisition's remaining "
                    "billable amount (%(rem)s).",
                    amt=rec.amount, rem=req.remaining_billable))
            rec.state = 'posted'
            rec._log_history('post', 'draft', 'posted')
            rec._notify_requisition_usage()
        return True

    def _notify_requisition_usage(self):
        """Warn on the requisition when it is almost (>=90%) or fully used.
        Best-effort: never let a notification block posting a bill."""
        self.ensure_one()
        req = self.requisition_id
        if not req.amount:
            return
        used_ratio = (req.amount - req.remaining_billable) / req.amount
        try:
            if req.remaining_billable <= 0:
                req.message_post(body=_(
                    "Requisition %s is now fully billed.", req.display_name),
                    subtype_xmlid='mail.mt_note')
            elif used_ratio >= 0.9:
                req.message_post(body=_(
                    "Requisition %(doc)s is almost fully used "
                    "(remaining billable: %(rem)s).",
                    doc=req.display_name, rem=req.remaining_billable),
                    subtype_xmlid='mail.mt_note')
        except Exception:  # noqa: BLE001 - notifications are best-effort
            _logger.warning("Could not post usage notice on %s",
                            req.display_name)

    def action_cancel(self):
        for rec in self:
            if rec.state == 'cancelled':
                continue
            from_state = rec.state
            rec.state = 'cancelled'
            # 'reverse' for a posted bill (returns funds), plain cancel for draft
            rec._log_history(
                'reverse' if from_state == 'posted' else 'cancel',
                from_state, 'cancelled')
        return True

    def action_reset_to_draft(self):
        for rec in self:
            if rec.state != 'cancelled':
                raise UserError(_("Only cancelled bills can be reset."))
            rec.state = 'draft'
        return True

    @api.ondelete(at_uninstall=False)
    def _prevent_delete_posted(self):
        for rec in self:
            if rec.state == 'posted':
                raise UserError(_(
                    "You cannot delete a posted bill. Cancel it first."))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = self.env['ir.sequence'].sudo().next_by_code(
                    'nn.bill') or 'New'
        return super().create(vals_list)

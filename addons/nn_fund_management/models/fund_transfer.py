# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError


class FundTransfer(models.Model):
    """Moves funds between two targets (project <-> project, project <-> expense
    head, in any combination).

    Money effect (via computed balances):

    * submitted / gm_approved -> amount is **transfer hold** on the source
      (removed from its available balance; cannot be spent, requisitioned or
      transferred again).
    * approved                -> amount is added to the destination
      (**incoming transfer**) and confirmed as an **outgoing transfer** on the
      source.
    * rejected / cancelled    -> the hold is released back to the source.
    """
    _name = 'nn.fund.transfer'
    _description = 'Fund Transfer'
    _inherit = ['nn.approval.mixin', 'mail.thread', 'mail.activity.mixin']
    _order = 'request_date desc, id desc'

    name = fields.Char(string='Transfer Number', default='New', copy=False,
                       readonly=True, index=True)
    company_id = fields.Many2one(
        'res.company', string='Company', required=True,
        default=lambda self: self.env.company)
    currency_id = fields.Many2one(
        'res.currency', default=lambda self: self.env.company.currency_id,
        readonly=True)

    # Source
    source_type = fields.Selection(
        selection=[('project', 'Project'), ('expense_head', 'Expense Head')],
        string='Source Type', required=True, default='project', tracking=True)
    source_project_id = fields.Many2one('nn.project', string='Source Project',
                                        ondelete='restrict')
    source_expense_id = fields.Many2one('nn.expense.head',
                                        string='Source Expense Head',
                                        ondelete='restrict')

    # Destination
    dest_type = fields.Selection(
        selection=[('project', 'Project'), ('expense_head', 'Expense Head')],
        string='Destination Type', required=True, default='project',
        tracking=True)
    dest_project_id = fields.Many2one('nn.project', string='Destination Project',
                                      ondelete='restrict')
    dest_expense_id = fields.Many2one('nn.expense.head',
                                      string='Destination Expense Head',
                                      ondelete='restrict')

    amount = fields.Monetary(string='Amount', required=True, tracking=True)
    reason = fields.Text(string='Reason')
    attachment_ids = fields.Many2many('ir.attachment', string='Attachments')

    source_available = fields.Monetary(
        string='Source Available', compute='_compute_source_available')
    source_display = fields.Char(string='Source',
                                 compute='_compute_displays', store=True)
    dest_display = fields.Char(string='Destination',
                               compute='_compute_displays', store=True)

    _sql_constraints = [
        ('check_amount_positive', 'CHECK(amount > 0)',
         'The transfer amount must be greater than zero.'),
    ]

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _get_source(self):
        self.ensure_one()
        return (self.source_project_id if self.source_type == 'project'
                else self.source_expense_id)

    def _get_dest(self):
        self.ensure_one()
        return (self.dest_project_id if self.dest_type == 'project'
                else self.dest_expense_id)

    @api.depends('source_type', 'source_project_id', 'source_expense_id',
                 'dest_type', 'dest_project_id', 'dest_expense_id')
    def _compute_displays(self):
        for rec in self:
            src = rec._get_source()
            dst = rec._get_dest()
            rec.source_display = src.display_name if src else ''
            rec.dest_display = dst.display_name if dst else ''

    @api.depends('source_type', 'source_project_id', 'source_expense_id',
                 'source_project_id.available_fund',
                 'source_expense_id.available_fund')
    def _compute_source_available(self):
        for rec in self:
            src = rec._get_source()
            rec.source_available = src.available_fund if src else 0.0

    # ------------------------------------------------------------------
    # Onchange / constraints
    # ------------------------------------------------------------------
    @api.onchange('source_type')
    def _onchange_source_type(self):
        if self.source_type == 'project':
            self.source_expense_id = False
        else:
            self.source_project_id = False

    @api.onchange('dest_type')
    def _onchange_dest_type(self):
        if self.dest_type == 'project':
            self.dest_expense_id = False
        else:
            self.dest_project_id = False

    @api.constrains('source_type', 'source_project_id', 'source_expense_id',
                    'dest_type', 'dest_project_id', 'dest_expense_id')
    def _check_source_dest(self):
        for rec in self:
            src = rec._get_source()
            dst = rec._get_dest()
            if not src:
                raise ValidationError(_("Please select a source."))
            if not dst:
                raise ValidationError(_("Please select a destination."))
            # Disallow both type-specific fields being filled.
            if rec.source_project_id and rec.source_expense_id:
                raise ValidationError(_(
                    "The source must be a single project or expense head."))
            if rec.dest_project_id and rec.dest_expense_id:
                raise ValidationError(_(
                    "The destination must be a single project or expense head."))
            # Source and destination cannot be the same record.
            if src._name == dst._name and src.id == dst.id:
                raise ValidationError(_(
                    "The source and destination cannot be the same."))

    def _locked_after_draft_fields(self):
        return {'amount', 'source_type', 'source_project_id',
                'source_expense_id', 'dest_type', 'dest_project_id',
                'dest_expense_id'}

    def _approval_match_context(self):
        """Match approval rules against the transfer's source target."""
        self.ensure_one()
        src = self._get_source()
        return {
            'project': src if src and src._name == 'nn.project'
            else self.env['nn.project'],
            'expense': src if src and src._name == 'nn.expense.head'
            else self.env['nn.expense.head'],
        }

    # ------------------------------------------------------------------
    # Approval hooks
    # ------------------------------------------------------------------
    def _check_can_submit(self):
        self.ensure_one()
        available = self.source_available
        if self.amount > available:
            raise UserError(_(
                "Transfer amount (%(amt)s) exceeds the source's available "
                "balance (%(avail)s).",
                amt=self.amount, avail=available))

    def _approval_log_extra(self):
        self.ensure_one()
        src = self._get_source()
        return {
            'project_id': src.id if src._name == 'nn.project' else False,
            'expense_head_id': (src.id if src._name == 'nn.expense.head'
                                else False),
        }

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = self.env['ir.sequence'].sudo().next_by_code(
                    'nn.fund.transfer') or 'New'
        records = super().create(vals_list)
        for rec in records:
            rec._log_approval('create', from_state=False, to_state='draft')
        return records

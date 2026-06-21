# -*- coding: utf-8 -*-
import logging

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.tools import float_compare

_logger = logging.getLogger(__name__)


class FundAccount(models.Model):
    """A bank, cash or other financial account that holds company funds.

    The account exposes four headline balances, all computed (never edited by
    hand) so that the figures always reconcile with the underlying documents:

    * ``total_received``    - sum of confirmed incoming funds
    * ``assigned_amount``   - funds approved into projects / expense heads
    * ``on_hold_amount``    - funds reserved by pending allocation requests
    * ``available_balance`` - unassigned balance still free to allocate

    Only ``total_received`` is wired up in this step; ``assigned`` and
    ``on_hold`` are extended once the allocation model exists.
    """
    _name = 'nn.fund.account'
    _description = 'Fund Account'
    _order = 'name'

    name = fields.Char(string='Account Name', required=True)
    code = fields.Char(string='Reference')
    account_type = fields.Selection(
        selection=[('bank', 'Bank'), ('cash', 'Cash'), ('other', 'Other')],
        string='Account Type', default='bank', required=True)
    bank_name = fields.Char()
    account_number = fields.Char()
    active = fields.Boolean(default=True)

    company_id = fields.Many2one(
        'res.company', string='Company', required=True,
        default=lambda self: self.env.company)
    currency_id = fields.Many2one(
        'res.currency', related='company_id.currency_id',
        store=True, readonly=True)

    incoming_fund_ids = fields.One2many(
        'nn.incoming.fund', 'fund_account_id', string='Incoming Funds')
    allocation_ids = fields.One2many(
        'nn.fund.allocation', 'fund_account_id', string='Allocations')

    incoming_fund_count = fields.Integer(compute='_compute_counts')
    allocation_count = fields.Integer(compute='_compute_counts')

    def _compute_counts(self):
        for acc in self:
            acc.incoming_fund_count = len(acc.incoming_fund_ids)
            acc.allocation_count = len(acc.allocation_ids)

    def action_view_incoming_funds(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Incoming Funds'),
            'res_model': 'nn.incoming.fund',
            'view_mode': 'tree,form',
            'domain': [('fund_account_id', '=', self.id)],
            'context': {'default_fund_account_id': self.id},
        }

    def action_view_allocations(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Allocations'),
            'res_model': 'nn.fund.allocation',
            'view_mode': 'tree,form',
            'domain': [('fund_account_id', '=', self.id)],
            'context': {'default_fund_account_id': self.id},
        }

    total_received = fields.Monetary(
        compute='_compute_balances', store=True,
        help="Sum of all confirmed incoming funds.")
    assigned_amount = fields.Monetary(
        compute='_compute_balances', store=True,
        help="Funds approved into projects or expense heads.")
    on_hold_amount = fields.Monetary(
        compute='_compute_balances', store=True,
        help="Funds reserved by pending allocation requests.")
    available_balance = fields.Monetary(
        compute='_compute_balances', store=True,
        help="Unassigned balance still free to allocate "
             "(received - assigned - on hold).")

    # States in which an allocation reserves money on the account but has not
    # yet been finalised into an assignment.
    _ALLOCATION_HOLD_STATES = ('submitted',)

    @api.depends('incoming_fund_ids.amount', 'incoming_fund_ids.state',
                 'allocation_ids.amount', 'allocation_ids.state')
    def _compute_balances(self):
        for account in self:
            confirmed = account.incoming_fund_ids.filtered(
                lambda f: f.state == 'confirmed')
            on_hold = account.allocation_ids.filtered(
                lambda a: a.state in self._ALLOCATION_HOLD_STATES)
            assigned = account.allocation_ids.filtered(
                lambda a: a.state == 'approved')

            account.total_received = sum(confirmed.mapped('amount'))
            account.on_hold_amount = sum(on_hold.mapped('amount'))
            account.assigned_amount = sum(assigned.mapped('amount'))
            account.available_balance = (
                account.total_received
                - account.assigned_amount
                - account.on_hold_amount
            )

    _PROTECTED_BALANCE_FIELDS = (
        'total_received', 'available_balance', 'on_hold_amount',
        'assigned_amount')

    def write(self, vals):
        forbidden = set(self._PROTECTED_BALANCE_FIELDS).intersection(vals)
        if forbidden:
            raise UserError(_(
                "Balance fields are calculated automatically and cannot be "
                "edited manually: %s", ', '.join(sorted(forbidden))))
        return super().write(vals)

    @api.model
    def _nn_load_demo_data(self):
        """Build the spec's §13 sample scenario as demo data, so the module
        shows a live, fully-populated system immediately after install. Runs the
        real workflow (so balances, approval history and the dashboard all
        populate). Best-effort: a glitch here must never break installation."""
        try:
            admin = self.env.ref('base.user_admin', raise_if_not_found=False)
            group = self.env.ref('nn_fund_management.group_fund_admin',
                                 raise_if_not_found=False)
            if not admin or not group:
                return
            admin.sudo().write({'groups_id': [(4, group.id)]})
            env = self.env(user=admin.id)
            icp = env['ir.config_parameter'].sudo()
            previous = icp.get_param('nn_fund_management.allow_self_approval')
            # Temporarily allow self-approval so the single demo user can drive
            # the whole approval chain; restored to the secure default after.
            icp.set_param('nn_fund_management.allow_self_approval', 'True')

            acc = env['nn.fund.account'].create({
                'name': 'NN Operating Account', 'account_type': 'bank',
                'bank_name': 'Demo Bank', 'account_number': '0099001122'})
            proj_a = env['nn.project'].create({'name': 'Skyline Tower'})
            proj_b = env['nn.project'].create({'name': 'Riverside Park'})

            inflow = env['nn.incoming.fund'].create({
                'fund_account_id': acc.id, 'amount': 1000000,
                'transaction_reference': 'DEMO-INFLOW-001',
                'source': 'Head Office', 'description': 'Quarterly funding'})
            inflow.action_confirm()

            alloc = env['nn.fund.allocation'].create({
                'fund_account_id': acc.id, 'target_type': 'project',
                'project_id': proj_a.id, 'amount': 600000,
                'purpose': 'Phase 1 construction'})
            alloc.action_submit()
            alloc.approve('Approved by GM')
            alloc.approve('Approved by MD')

            # A second request left pending, so the dashboard shows work to do.
            pending = env['nn.fund.allocation'].create({
                'fund_account_id': acc.id, 'target_type': 'project',
                'project_id': proj_b.id, 'amount': 120000,
                'purpose': 'Landscaping budget (awaiting approval)'})
            pending.action_submit()

            transfer = env['nn.fund.transfer'].create({
                'source_type': 'project', 'source_project_id': proj_a.id,
                'dest_type': 'project', 'dest_project_id': proj_b.id,
                'amount': 200000, 'reason': 'Re-balance project budgets'})
            transfer.action_submit()
            transfer.approve('GM')
            transfer.approve('MD')

            req = env['nn.fund.requisition'].create({
                'target_type': 'project', 'project_id': proj_b.id,
                'amount': 150000, 'purpose': 'Vendor payments'})
            req.action_submit()
            req.approve('GM')
            req.approve('MD')

            bill = env['nn.bill'].create({
                'requisition_id': req.id, 'amount': 100000,
                'target_type': 'project', 'project_id': proj_b.id,
                'reference': 'INV-2025-0142'})
            bill.action_post()

            icp.set_param('nn_fund_management.allow_self_approval',
                          previous or 'False')
            _logger.info("NN Fund Management demo scenario loaded.")
        except Exception:  # noqa: BLE001 - demo data must never block install
            _logger.exception(
                "NN Fund Management demo data could not be loaded")
        return True

    @api.constrains('available_balance')
    def _check_no_negative_balance(self):
        """Safety net: the unassigned balance must never go negative."""
        for account in self:
            rounding = account.currency_id.rounding or 0.01
            if float_compare(account.available_balance, 0.0,
                             precision_rounding=rounding) < 0:
                raise ValidationError(_(
                    "This operation would make the available balance of "
                    "'%(name)s' negative (%(val)s), which is not allowed.",
                    name=account.display_name, val=account.available_balance))

# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.tools import float_compare


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

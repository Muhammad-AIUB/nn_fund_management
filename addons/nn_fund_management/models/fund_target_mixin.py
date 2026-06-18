# -*- coding: utf-8 -*-
from odoo import api, fields, models


class FundTargetMixin(models.AbstractModel):
    """Shared balance logic for anything funds can be allocated to.

    Both :class:`nn.project` and :class:`nn.expense.head` are "fund targets":
    money is allocated to them, held against requisitions/transfers, spent via
    bills, and moved between them. To avoid duplicating the balance maths in two
    places, the fields and their compute method live here and both models simply
    inherit this mixin.

    Every balance is computed and stored - users never edit them by hand. The
    contributing documents (allocations, requisitions, transfers, bills) are
    added in later steps; until then each component computes to zero, so the
    headline ``available_fund`` already behaves correctly.
    """
    _name = 'nn.fund.target.mixin'
    _description = 'Fund Target Balance Mixin'

    currency_id = fields.Many2one(
        'res.currency', string='Currency',
        default=lambda self: self.env.company.currency_id, readonly=True)
    company_id = fields.Many2one(
        'res.company', string='Company', required=True,
        default=lambda self: self.env.company)

    total_allocated = fields.Monetary(
        compute='_compute_fund_balances', store=True,
        help="Total funds approved into this target.")
    incoming_transfer = fields.Monetary(
        compute='_compute_fund_balances', store=True,
        help="Approved transfers received from other targets.")
    outgoing_transfer = fields.Monetary(
        compute='_compute_fund_balances', store=True,
        help="Approved transfers sent to other targets.")
    requisition_hold = fields.Monetary(
        compute='_compute_fund_balances', store=True,
        help="Amount reserved by pending/approved requisitions not yet billed.")
    transfer_hold = fields.Monetary(
        compute='_compute_fund_balances', store=True,
        help="Amount reserved by pending outgoing transfers.")
    approved_unspent = fields.Monetary(
        compute='_compute_fund_balances', store=True,
        help="Approved requisition amount still available to bill against.")
    total_spent = fields.Monetary(
        compute='_compute_fund_balances', store=True,
        help="Amount spent through posted bills.")
    available_fund = fields.Monetary(
        compute='_compute_fund_balances', store=True,
        help="Funds free to requisition or transfer "
             "(allocated + incoming - outgoing - holds - spent).")

    def _get_balance_components(self):
        """Return the raw amounts that make up the balances for one record.

        Projects and expense heads share the exact same contributing documents
        (and use identical relation field names: ``allocation_ids``,
        ``requisition_ids`` ...), so the maths lives here once. Each relation is
        read only if it has been declared yet, which lets the module grow step
        by step without breaking earlier steps.
        """
        self.ensure_one()
        c = {
            'total_allocated': 0.0,
            'incoming_transfer': 0.0,
            'outgoing_transfer': 0.0,
            'requisition_hold': 0.0,
            'transfer_hold': 0.0,
            'approved_unspent': 0.0,
            'total_spent': 0.0,
        }

        if 'allocation_ids' in self._fields:
            approved_alloc = self.allocation_ids.filtered(
                lambda a: a.state == 'approved')
            c['total_allocated'] = sum(approved_alloc.mapped('amount'))

        if 'requisition_ids' in self._fields:
            pending_req = self.requisition_ids.filtered(
                lambda r: r.state in ('submitted', 'gm_approved'))
            approved_req = self.requisition_ids.filtered(
                lambda r: r.state == 'approved')
            c['requisition_hold'] = sum(pending_req.mapped('amount'))
            c['approved_unspent'] = sum(
                approved_req.mapped('remaining_billable'))
            # Spent = total posted-bill amount across the target's requisitions.
            c['total_spent'] = sum(self.requisition_ids.mapped('billed_amount'))

        return c

    def _compute_fund_balances(self):
        for rec in self:
            c = rec._get_balance_components()
            rec.total_allocated = c['total_allocated']
            rec.incoming_transfer = c['incoming_transfer']
            rec.outgoing_transfer = c['outgoing_transfer']
            rec.requisition_hold = c['requisition_hold']
            rec.transfer_hold = c['transfer_hold']
            rec.approved_unspent = c['approved_unspent']
            rec.total_spent = c['total_spent']
            rec.available_fund = (
                c['total_allocated']
                + c['incoming_transfer']
                - c['outgoing_transfer']
                - c['requisition_hold']
                - c['transfer_hold']
                - c['approved_unspent']
                - c['total_spent']
            )

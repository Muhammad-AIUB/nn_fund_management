# -*- coding: utf-8 -*-
import logging

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError

_logger = logging.getLogger(__name__)


class ApprovalMixin(models.AbstractModel):
    """Reusable two-level (GM -> MD) approval workflow.

    Allocations, requisitions and transfers all share the exact same approval
    rules, so the workflow lives here once:

    * State machine: draft -> submitted -> gm_approved -> approved,
      plus rejected / cancelled (requisition adds 'closed').
    * GM must approve before MD; MD cannot act first (enforced by the state).
    * Only a user in the level's approver group may approve/reject at that level
      (server side, not just hidden buttons).
    * A user cannot approve their own request unless self-approval is explicitly
      enabled via the ``nn_fund_management.allow_self_approval`` config option.
    * Every transition writes an immutable audit-history row.
    * Transitions are guarded by the current state, so clicking a button twice
      can never create a duplicate fund movement.

    The actual money effect is realised by the balance compute methods, which
    read document state - never by direct balance writes - so it is inherently
    idempotent. Concrete models plug their own validation/effects into the
    ``_on_*`` hooks below.
    """
    _name = 'nn.approval.mixin'
    _description = 'Two-level Approval Mixin'

    state = fields.Selection(
        selection=[
            ('draft', 'Draft'),
            ('submitted', 'Submitted'),
            ('gm_approved', 'GM Approved'),
            ('approved', 'Approved'),
            ('rejected', 'Rejected'),
            ('cancelled', 'Cancelled'),
        ], string='Status', default='draft', required=True,
        tracking=True, copy=False)

    requested_by_id = fields.Many2one(
        'res.users', string='Requested By', copy=False,
        default=lambda self: self.env.user, tracking=True)
    request_date = fields.Date(
        string='Request Date', default=fields.Date.context_today, copy=False)

    gm_user_id = fields.Many2one('res.users', string='GM Approver',
                                 readonly=True, copy=False)
    gm_date = fields.Datetime(string='GM Approval Date', readonly=True,
                              copy=False)
    md_user_id = fields.Many2one('res.users', string='MD Approver',
                                 readonly=True, copy=False)
    md_date = fields.Datetime(string='MD Approval Date', readonly=True,
                              copy=False)

    approval_history_ids = fields.One2many(
        'nn.approval.history', compute='_compute_approval_history_ids',
        string='Approval History')

    # ------------------------------------------------------------------
    # History
    # ------------------------------------------------------------------
    def _compute_approval_history_ids(self):
        History = self.env['nn.approval.history']
        for rec in self:
            rec_id = rec.id if isinstance(rec.id, int) else rec._origin.id
            rec.approval_history_ids = History.search([
                ('res_model', '=', rec._name),
                ('res_id', '=', rec_id),
            ]) if rec_id else History

    def _approval_log_extra(self):
        """Hook: extra columns (fund account / project / expense head) for the
        audit row. Overridden by concrete models."""
        self.ensure_one()
        return {}

    def _log_approval(self, action, approval_level=False,
                      from_state=False, to_state=False, comment=False):
        self.ensure_one()
        vals = {
            'res_model': self._name,
            'res_id': self.id,
            'document_ref': self.display_name,
            'action': action,
            'approval_level': approval_level,
            'from_state': from_state,
            'to_state': to_state,
            'comment': comment,
            'amount': self.amount if 'amount' in self._fields else 0.0,
            'currency_id': self.currency_id.id
            if 'currency_id' in self._fields and self.currency_id else False,
        }
        vals.update(self._approval_log_extra())
        return self.env['nn.approval.history'].sudo().create(vals)

    # ------------------------------------------------------------------
    # Permission helpers
    # ------------------------------------------------------------------
    def _approver_group(self, level):
        return ('nn_fund_management.group_gm_approver' if level == 'gm'
                else 'nn_fund_management.group_md_approver')

    def _check_approver(self, level):
        if not self.env.user.has_group(self._approver_group(level)):
            raise AccessError(_(
                "Only a %s approver can take this action.",
                'GM' if level == 'gm' else 'MD'))

    def _check_not_self_approval(self):
        allow = self.env['ir.config_parameter'].sudo().get_param(
            'nn_fund_management.allow_self_approval') in ('True', 'true', '1')
        if not allow and self.requested_by_id == self.env.user:
            raise UserError(_(
                "You cannot approve your own request. Ask another approver, or "
                "enable self-approval in the module settings."))

    # ------------------------------------------------------------------
    # Activities & notifications
    # ------------------------------------------------------------------
    def _schedule_approver_activities(self, level):
        """Schedule a To-Do activity for every user who can approve at the
        given level, so the request shows up in their activity inbox.

        Notifications are best-effort: a mail misconfiguration must never block
        the financial workflow, so failures are logged, not raised."""
        self.ensure_one()
        if not hasattr(self, 'activity_schedule'):
            return
        group = self.env.ref(self._approver_group(level),
                             raise_if_not_found=False)
        if not group:
            return
        summary = _("%(level)s approval required: %(doc)s",
                    level='GM' if level == 'gm' else 'MD',
                    doc=self.display_name)
        for user in group.users:
            try:
                self.activity_schedule(
                    'mail.mail_activity_data_todo',
                    user_id=user.id, summary=summary)
            except Exception:  # noqa: BLE001 - notifications are best-effort
                _logger.warning(
                    "Could not schedule approval activity for %s on %s",
                    user.login, self.display_name)

    def _clear_approval_activities(self):
        if hasattr(self, 'activity_unlink'):
            self.activity_unlink(['mail.mail_activity_data_todo'])

    def _notify_requester(self, body):
        """Notify the requester via the document chatter (best-effort).

        The requester is subscribed as a follower and a note is logged, so the
        update appears on the document without depending on an outgoing mail
        server."""
        self.ensure_one()
        if not hasattr(self, 'message_post'):
            return
        try:
            partner = self.requested_by_id.partner_id
            if partner:
                self.message_subscribe(partner_ids=partner.ids)
            self.message_post(body=body, subtype_xmlid='mail.mt_note')
        except Exception:  # noqa: BLE001 - notifications are best-effort
            _logger.warning("Could not notify requester on %s",
                            self.display_name)

    # ------------------------------------------------------------------
    # Hooks for concrete models (default: no-op)
    # ------------------------------------------------------------------
    def _check_can_submit(self):
        """Validate availability before placing a hold. Override to raise."""
        return True

    def _on_submit(self):
        return True

    def _on_final_approve(self):
        return True

    def _on_reject(self):
        return True

    def _on_cancel(self):
        return True

    # ------------------------------------------------------------------
    # Workflow transitions
    # ------------------------------------------------------------------
    def action_submit(self):
        for rec in self:
            if rec.state != 'draft':
                raise UserError(_("Only draft requests can be submitted."))
            rec._check_can_submit()
            rec.state = 'submitted'
            rec._log_approval('submit', from_state='draft',
                              to_state='submitted')
            rec._schedule_approver_activities('gm')
            rec._on_submit()
        return True

    def approve(self, comment=False):
        self.ensure_one()
        if self.state == 'submitted':
            self._check_approver('gm')
            self._check_not_self_approval()
            self.write({
                'state': 'gm_approved',
                'gm_user_id': self.env.user.id,
                'gm_date': fields.Datetime.now(),
            })
            self._log_approval('gm_approve', 'gm', 'submitted',
                               'gm_approved', comment)
            self._clear_approval_activities()
            self._schedule_approver_activities('md')
        elif self.state == 'gm_approved':
            self._check_approver('md')
            self._check_not_self_approval()
            self.write({
                'state': 'approved',
                'md_user_id': self.env.user.id,
                'md_date': fields.Datetime.now(),
            })
            self._log_approval('md_approve', 'md', 'gm_approved',
                               'approved', comment)
            self._clear_approval_activities()
            self._notify_requester(
                _("Your request %s has been fully approved.",
                  self.display_name))
            self._on_final_approve()
        else:
            raise UserError(_("This request is not awaiting approval."))
        return True

    def reject(self, comment=False):
        self.ensure_one()
        if self.state not in ('submitted', 'gm_approved'):
            raise UserError(_("Only a pending request can be rejected."))
        if not comment:
            raise UserError(_("A reason is required to reject a request."))
        level = 'gm' if self.state == 'submitted' else 'md'
        self._check_approver(level)
        self._check_not_self_approval()
        from_state = self.state
        self.state = 'rejected'
        self._log_approval('reject', level, from_state, 'rejected', comment)
        self._clear_approval_activities()
        self._notify_requester(
            _("Your request %(doc)s was rejected. Reason: %(reason)s",
              doc=self.display_name, reason=comment))
        self._on_reject()
        return True

    def action_cancel(self):
        for rec in self:
            if rec.state == 'cancelled':
                continue
            if rec.state == 'approved' and not self.env.user.has_group(
                    'nn_fund_management.group_fund_admin'):
                raise AccessError(_(
                    "Only a Fund Administrator can cancel an approved request."))
            from_state = rec.state
            rec.state = 'cancelled'
            rec._log_approval('cancel', from_state=from_state,
                              to_state='cancelled')
            rec._clear_approval_activities()
            rec._on_cancel()
        return True

    def action_reset_to_draft(self):
        for rec in self:
            if rec.state not in ('rejected', 'cancelled'):
                raise UserError(_(
                    "Only rejected or cancelled requests can be reset."))
            from_state = rec.state
            rec.state = 'draft'
            rec._log_approval('reset', from_state=from_state, to_state='draft')
        return True

    # ------------------------------------------------------------------
    # Wizard launchers (capture an optional/required comment)
    # ------------------------------------------------------------------
    def _open_decision_wizard(self, mode):
        self.ensure_one()
        return {
            'name': _('Approve') if mode == 'approve' else _('Reject'),
            'type': 'ir.actions.act_window',
            'res_model': 'nn.approval.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': dict(self.env.context,
                            active_model=self._name,
                            active_id=self.id,
                            default_mode=mode),
        }

    def action_approve_wizard(self):
        return self._open_decision_wizard('approve')

    def action_reject_wizard(self):
        return self._open_decision_wizard('reject')

    # ------------------------------------------------------------------
    # Protect confirmed documents from deletion
    # ------------------------------------------------------------------
    @api.ondelete(at_uninstall=False)
    def _prevent_delete_active_documents(self):
        for rec in self:
            if rec.state not in ('draft', 'cancelled', 'rejected'):
                raise UserError(_(
                    "You cannot delete a request that is submitted or "
                    "approved. Cancel it first."))

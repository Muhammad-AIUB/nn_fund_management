# -*- coding: utf-8 -*-
import logging

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError

_logger = logging.getLogger(__name__)


class ApprovalMixin(models.AbstractModel):
    """Reusable, rule-driven multi-step approval workflow.

    Allocations, requisitions and transfers share the same approval engine, so
    it lives here once:

    * State machine: draft -> submitted -> approved, plus rejected / cancelled
      (requisition adds 'closed'). The document stays ``submitted`` while it
      walks through the approval steps and only becomes ``approved`` after the
      last step.
    * The required steps come from a configurable :class:`nn.approval.rule`
      (matched by request type, amount and company at submission time and then
      frozen on the document). Each step is a security group, so approvers are
      configurable and never hardcoded. The default rule reproduces GM -> MD.
    * Only a member of the current step's group may approve/reject it (server
      side, not just hidden buttons). Steps are processed strictly in order.
    * A user cannot approve their own request unless self-approval is enabled
      via the ``nn_fund_management.allow_self_approval`` config option.
    * Every transition writes an immutable audit-history row.
    * Transitions are guarded by the current state and step pointer, so clicking
      a button twice can never create a duplicate fund movement.

    The actual money effect is realised by the balance compute methods, which
    read document state - never by direct balance writes - so it is inherently
    idempotent. Concrete models plug their own validation/effects into the
    ``_on_*`` hooks below.
    """
    _name = 'nn.approval.mixin'
    _description = 'Approval Workflow Mixin'
    _inherit = ['nn.chat.mixin']

    _REQUEST_TYPE_BY_MODEL = {
        'nn.fund.allocation': 'allocation',
        'nn.fund.requisition': 'requisition',
        'nn.fund.transfer': 'transfer',
    }

    state = fields.Selection(
        selection=[
            ('draft', 'Draft'),
            ('submitted', 'Submitted'),
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

    approval_rule_id = fields.Many2one(
        'nn.approval.rule', string='Approval Rule', readonly=True, copy=False)
    approval_step = fields.Integer(
        string='Next Step Index', default=0, readonly=True, copy=False,
        help="Index of the next approval step to be completed.")
    next_approver_group_id = fields.Many2one(
        'res.groups', string='Pending Approval From',
        compute='_compute_approval_progress')
    approval_progress = fields.Char(
        string='Approval Progress', compute='_compute_approval_progress')

    approval_history_ids = fields.One2many(
        'nn.approval.history', compute='_compute_approval_history_ids',
        string='Approval History')

    # ------------------------------------------------------------------
    # Rule resolution & steps
    # ------------------------------------------------------------------
    def _get_request_type(self):
        return self._REQUEST_TYPE_BY_MODEL.get(self._name, 'any')

    def _chat_member_partners(self):
        """Discussion members = requester + everyone who can approve it,
        taken from the applicable rule (resolved live while still in draft)."""
        partners = super()._chat_member_partners()
        rule = self.approval_rule_id or self._resolve_approval_rule()
        for step in rule.step_ids:
            partners |= self._step_approver_users(step).mapped('partner_id')
        return partners

    def _approval_match_context(self):
        """Project / expense head used to match rules. Overridden by models
        whose target is not a plain ``project_id`` / ``expense_head_id``."""
        self.ensure_one()
        return {
            'project': (self.project_id if 'project_id' in self._fields
                        else self.env['nn.project']),
            'expense': (self.expense_head_id if 'expense_head_id' in self._fields
                        else self.env['nn.expense.head']),
        }

    def _resolve_approval_rule(self):
        """Return the most specific active rule (with steps) that matches."""
        self.ensure_one()
        rtype = self._get_request_type()
        amount = self.amount if 'amount' in self._fields else 0.0
        company = (self.company_id if 'company_id' in self._fields
                   else self.env.company)
        ctx = self._approval_match_context()
        rules = self.env['nn.approval.rule'].search(
            [('active', '=', True)], order='sequence, amount_min, id')
        for rule in rules:
            if rule.step_ids and rule._matches(
                    rtype, amount, company,
                    ctx.get('project'), ctx.get('expense')):
                return rule
        return self.env['nn.approval.rule']

    def _step_approver_users(self, step):
        """Users allowed to act on a step: the specific user, else the group."""
        return step.user_id if step.user_id else step.group_id.users

    def _ordered_steps(self):
        self.ensure_one()
        return self.approval_rule_id.step_ids.sorted(
            lambda s: (s.sequence, s.id))

    def _current_step(self):
        self.ensure_one()
        steps = self._ordered_steps()
        if 0 <= self.approval_step < len(steps):
            return steps[self.approval_step]
        return self.env['nn.approval.rule.step']

    @api.depends('state', 'approval_rule_id', 'approval_step')
    def _compute_approval_progress(self):
        for rec in self:
            total = len(rec._ordered_steps()) if rec.approval_rule_id else 0
            if rec.state == 'submitted':
                step = rec._current_step()
                rec.next_approver_group_id = step.group_id if step else False
                rec.approval_progress = _(
                    "%(done)s of %(total)s steps approved",
                    done=rec.approval_step, total=total)
            elif rec.state == 'approved':
                rec.next_approver_group_id = False
                rec.approval_progress = _("Fully approved")
            else:
                rec.next_approver_group_id = False
                rec.approval_progress = ''

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

    def _log_approval(self, action, approval_level=False, from_state=False,
                      to_state=False, comment=False, step_label=False):
        self.ensure_one()
        vals = {
            'res_model': self._name,
            'res_id': self.id,
            'document_ref': self.display_name,
            'action': action,
            'approval_level': approval_level,
            'step_label': step_label,
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
    def _check_step_approver(self, step):
        if step.user_id:
            if self.env.user != step.user_id:
                raise AccessError(_(
                    "Only %s can approve this step.", step.user_id.name))
        elif step.group_id not in self.env.user.groups_id:
            raise AccessError(_(
                "Only a member of '%s' can approve this step.",
                step.group_id.full_name))

    def _check_not_self_approval(self):
        allow = self.env['ir.config_parameter'].sudo().get_param(
            'nn_fund_management.allow_self_approval') in ('True', 'true', '1')
        if not allow and self.requested_by_id == self.env.user:
            raise UserError(_(
                "You cannot approve your own request. Ask another approver, or "
                "enable self-approval in the module settings."))

    # ------------------------------------------------------------------
    # Activities & notifications (best-effort)
    # ------------------------------------------------------------------
    def _schedule_activities_for_users(self, users):
        self.ensure_one()
        if not hasattr(self, 'activity_schedule') or not users:
            return
        summary = _("Approval required: %s", self.display_name)
        for user in users:
            try:
                self.activity_schedule(
                    'mail.mail_activity_data_todo',
                    user_id=user.id, summary=summary)
            except Exception:  # noqa: BLE001 - notifications are best-effort
                _logger.warning(
                    "Could not schedule approval activity for %s on %s",
                    user.login, self.display_name)

    def _schedule_step_activities(self):
        step = self._current_step()
        if step:
            self._schedule_activities_for_users(self._step_approver_users(step))

    def _clear_approval_activities(self):
        if hasattr(self, 'activity_unlink'):
            self.activity_unlink(['mail.mail_activity_data_todo'])

    def _notify_requester(self, body):
        """Notify the requester via the document chatter (best-effort)."""
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
    def _lock_balance_source(self):
        """Lock the row whose balance gates this request, so two users
        submitting at the same time are serialised and the same money can't be
        reserved twice (prevents the check-then-reserve race). Overridden by
        concrete models. Default: no lock."""
        return True

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
            # Lock the balance source first, then validate availability, so
            # concurrent submissions can't both pass the same check.
            rec._lock_balance_source()
            rec._check_can_submit()
            rule = rec._resolve_approval_rule()
            if not rule:
                raise UserError(_(
                    "No approval rule is configured for this request. "
                    "Please configure one under Fund Management > "
                    "Configuration > Approval Rules."))
            rec.approval_rule_id = rule
            rec.approval_step = 0
            rec.state = 'submitted'
            rec._log_approval('submit', from_state='draft',
                              to_state='submitted')
            rec._schedule_step_activities()
            rec._on_submit()
        return True

    def approve(self, comment=False):
        self.ensure_one()
        if self.state != 'submitted':
            raise UserError(_("This request is not awaiting approval."))
        step = self._current_step()
        if not step:
            raise UserError(_("No approval step is configured."))
        self._check_step_approver(step)
        self._check_not_self_approval()

        self.approval_step += 1
        is_final = self.approval_step >= len(self._ordered_steps())
        self._log_approval(
            'approve', from_state='submitted',
            to_state='approved' if is_final else 'submitted',
            comment=comment, step_label=step.name)

        self._clear_approval_activities()
        if is_final:
            self.state = 'approved'
            self._notify_requester(
                _("Your request %s has been fully approved.",
                  self.display_name))
            self._on_final_approve()
        else:
            self._schedule_step_activities()
        return True

    def reject(self, comment=False):
        self.ensure_one()
        if self.state != 'submitted':
            raise UserError(_("Only a pending request can be rejected."))
        if not comment:
            raise UserError(_("A reason is required to reject a request."))
        step = self._current_step()
        if step:
            self._check_step_approver(step)
        self._check_not_self_approval()
        self.state = 'rejected'
        self._log_approval(
            'reject', from_state='submitted', to_state='rejected',
            comment=comment, step_label=step.name if step else False)
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
            rec.write({
                'state': 'draft',
                'approval_rule_id': False,
                'approval_step': 0,
            })
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
    # Protect submitted/approved documents from edits & deletion
    # ------------------------------------------------------------------
    def _locked_after_draft_fields(self):
        """Financial fields that must not change once the request leaves draft.
        Overridden by concrete models."""
        return set()

    def write(self, vals):
        locked = self._locked_after_draft_fields()
        changed = locked.intersection(vals)
        if changed:
            for rec in self:
                if rec.state != 'draft':
                    raise UserError(_(
                        "You cannot change %(fields)s once the request has been "
                        "submitted (status: %(state)s). Reset it to draft "
                        "first.",
                        fields=', '.join(sorted(changed)),
                        state=rec.state))
        return super().write(vals)

    @api.ondelete(at_uninstall=False)
    def _prevent_delete_active_documents(self):
        for rec in self:
            if rec.state not in ('draft', 'cancelled', 'rejected'):
                raise UserError(_(
                    "You cannot delete a request that is submitted or "
                    "approved. Cancel it first."))

# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class ApprovalRule(models.Model):
    """Configurable approval policy.

    A rule matches a document by request type, amount range and (optionally)
    company, and defines the **ordered list of approval steps** that document
    must pass. Steps are security groups, so approvers are configurable and not
    hardcoded. Example policies:

    * Up to 50,000      -> GM
    * 50,001 - 200,000  -> GM, Finance
    * Above 200,000     -> GM, Finance, MD

    When a request is submitted, the most specific active matching rule (lowest
    ``sequence``) is captured on the document, so later rule edits never change
    an in-flight approval.
    """
    _name = 'nn.approval.rule'
    _description = 'Approval Rule'
    _order = 'sequence, amount_min, id'

    name = fields.Char(required=True)
    active = fields.Boolean(default=True)
    sequence = fields.Integer(
        default=10, help="Lower values are evaluated first (more specific "
        "rules should have a lower sequence).")

    request_type = fields.Selection(
        selection=[
            ('any', 'Any'),
            ('allocation', 'Fund Allocation'),
            ('requisition', 'Fund Requisition'),
            ('transfer', 'Fund Transfer'),
        ], string='Request Type', required=True, default='any')

    company_id = fields.Many2one(
        'res.company', string='Company',
        help="Leave empty to apply to all companies.")

    amount_min = fields.Monetary(string='Amount From', default=0.0)
    amount_max = fields.Monetary(
        string='Amount To', default=0.0,
        help="Upper bound (inclusive). 0 means no upper limit.")
    currency_id = fields.Many2one(
        'res.currency', default=lambda self: self.env.company.currency_id)

    project_id = fields.Many2one(
        'nn.project', string='Project',
        help="Limit this rule to a specific project. Leave empty for any.")
    expense_head_id = fields.Many2one(
        'nn.expense.head', string='Expense Head',
        help="Limit this rule to a specific expense head. Empty for any.")

    step_ids = fields.One2many(
        'nn.approval.rule.step', 'rule_id', string='Approval Steps',
        copy=True)
    step_count = fields.Integer(compute='_compute_step_count')

    @api.depends('step_ids')
    def _compute_step_count(self):
        for rule in self:
            rule.step_count = len(rule.step_ids)

    @api.constrains('amount_min', 'amount_max')
    def _check_amounts(self):
        for rule in self:
            if rule.amount_max and rule.amount_max < rule.amount_min:
                raise ValidationError(_(
                    "'Amount To' must be greater than or equal to "
                    "'Amount From'."))

    def _matches(self, request_type, amount, company, project=None,
                 expense=None):
        """Return True if this rule applies to the given document."""
        self.ensure_one()
        if self.request_type not in ('any', request_type):
            return False
        if self.company_id and company and self.company_id != company:
            return False
        if amount < self.amount_min:
            return False
        if self.amount_max and amount > self.amount_max:
            return False
        if self.project_id and self.project_id != project:
            return False
        if self.expense_head_id and self.expense_head_id != expense:
            return False
        return True


class ApprovalRuleStep(models.Model):
    """One ordered approval step of a rule: a security group that must approve."""
    _name = 'nn.approval.rule.step'
    _description = 'Approval Rule Step'
    _order = 'sequence, id'

    rule_id = fields.Many2one('nn.approval.rule', required=True,
                              ondelete='cascade')
    sequence = fields.Integer(default=10)
    name = fields.Char(string='Step Label', required=True)
    group_id = fields.Many2one(
        'res.groups', string='Approver Group', required=True,
        help="A user in this group must approve this step.")
    user_id = fields.Many2one(
        'res.users', string='Specific Approver',
        help="If set, only this exact user may approve this step (must still "
             "be a member of the group). Leave empty to allow any group "
             "member.")

    @api.constrains('user_id', 'group_id')
    def _check_user_in_group(self):
        for step in self:
            if step.user_id and step.group_id not in step.user_id.groups_id:
                raise ValidationError(_(
                    "%(user)s must belong to the group '%(group)s' to be its "
                    "approver.", user=step.user_id.name,
                    group=step.group_id.full_name))

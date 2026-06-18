# -*- coding: utf-8 -*-
from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    nn_allow_self_approval = fields.Boolean(
        string="Allow Self-Approval",
        config_parameter='nn_fund_management.allow_self_approval',
        help="If enabled, an approver may approve a request they created "
             "themselves. Disabled by default for segregation of duties.")

    nn_requisition_alert_threshold = fields.Float(
        string="Requisition Usage Alert (%)",
        config_parameter='nn_fund_management.requisition_alert_threshold',
        default=90.0,
        help="When a requisition reaches this percentage of its approved "
             "amount, an 'almost fully used' notice is posted.")

    nn_bank_default_account_id = fields.Many2one(
        'nn.fund.account', string="Default Bank-Email Account",
        config_parameter='nn_fund_management.bank_default_account_id',
        help="Fund account used for funds parsed from bank emails when the "
             "account number cannot be matched. If empty, unmatched emails "
             "are flagged instead of guessing an account.")

    nn_dashboard_recent_limit = fields.Integer(
        string="Dashboard Recent Movements",
        config_parameter='nn_fund_management.dashboard_recent_limit',
        default=20,
        help="How many recent movements to show on the dashboard.")

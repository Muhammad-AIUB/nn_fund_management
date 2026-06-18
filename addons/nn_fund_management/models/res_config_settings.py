# -*- coding: utf-8 -*-
from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    nn_allow_self_approval = fields.Boolean(
        string="Allow Self-Approval",
        config_parameter='nn_fund_management.allow_self_approval',
        help="If enabled, an approver may approve a request they created "
             "themselves. Disabled by default for segregation of duties.")

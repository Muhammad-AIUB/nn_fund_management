# -*- coding: utf-8 -*-
from odoo import _, fields, models
from odoo.exceptions import UserError


class ApprovalWizard(models.TransientModel):
    """Small dialog that captures the approver's comment before applying an
    approve or reject decision to the document in context. A reason is mandatory
    when rejecting."""
    _name = 'nn.approval.wizard'
    _description = 'Approval Decision'

    mode = fields.Selection(
        selection=[('approve', 'Approve'), ('reject', 'Reject')],
        string='Decision', required=True)
    comment = fields.Text(string='Comment')

    def action_confirm(self):
        self.ensure_one()
        model = self.env.context.get('active_model')
        res_id = self.env.context.get('active_id')
        if not model or not res_id:
            raise UserError(_("No document to act on."))
        record = self.env[model].browse(res_id)
        if self.mode == 'approve':
            record.approve(self.comment)
        else:
            record.reject(self.comment)
        return {'type': 'ir.actions.act_window_close'}

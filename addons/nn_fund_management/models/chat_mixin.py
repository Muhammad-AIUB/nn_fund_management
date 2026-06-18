# -*- coding: utf-8 -*-
from odoo import _, fields, models


class FundChatMixin(models.AbstractModel):
    """Gives a record a real-time discussion channel.

    Rather than re-inventing messaging, this reuses Odoo's native **Discuss**
    (`discuss.channel`), which is websocket-backed, so messages are delivered
    live. A private *group* channel is created lazily the first time someone
    opens the discussion, and the relevant people are added as members.
    """
    _name = 'nn.chat.mixin'
    _description = 'Fund Discussion Channel Mixin'

    channel_id = fields.Many2one(
        'discuss.channel', string='Discussion Channel',
        copy=False, readonly=True)

    def _chat_channel_name(self):
        self.ensure_one()
        return _("Discussion: %s", self.display_name)

    def _chat_member_partners(self):
        """Partners who belong in the discussion. Extended by sub-models."""
        self.ensure_one()
        partners = self.env.user.partner_id
        if 'requested_by_id' in self._fields and self.requested_by_id:
            partners |= self.requested_by_id.partner_id
        return partners

    def action_open_chat(self):
        """Create (once) and open the record's Discuss channel."""
        self.ensure_one()
        channel = self.channel_id
        if not channel:
            channel = self.env['discuss.channel'].create({
                'name': self._chat_channel_name(),
                'channel_type': 'group',
            })
            self.channel_id = channel.id
        partners = self._chat_member_partners()
        if partners:
            channel.add_members(partner_ids=partners.ids)
        return {
            'type': 'ir.actions.client',
            'tag': 'mail.action_discuss',
            'name': self._chat_channel_name(),
            'context': {'active_id': channel.id},
        }

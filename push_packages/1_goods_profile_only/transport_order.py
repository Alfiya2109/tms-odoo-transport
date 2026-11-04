import base64
import json
from collections import defaultdict
from datetime import datetime, time, timedelta, date
from dateutil.relativedelta import relativedelta
from odoo import api, fields, models, Command, _
from odoo.exceptions import ValidationError, UserError
from odoo.tools import config
import pytz
import requests
import logging
from . import price_list_registry as R
_logger = logging.getLogger(__name__)


def _get_routing_api_token():
    """Read routing API credentials from odoo.conf and return a Basic auth header."""
    token = config.get('tms_routing_api_token', '')
    if not token:
        return None
    encoded = base64.b64encode(token.encode('utf-8')).decode('utf-8')
    return f'Basic {encoded}'

class TransportOrder(models.Model):
    _name = 'transport.order'
    _inherit = ['mail.thread', 'soft.delete.mixin', 'tms.custom.field.mixin', 'gdpr.anonymize.mixin', 'portal.mixin']
    _description = 'Transport order'
    _rec_name = 'number'

    _GDPR_FIELDS = {
        # Sender
        'sender_name': 'anonymize_char', 'sender_street': 'anonymize_char',
        'sender_street_2': 'clear', 'sender_city': 'anonymize_char',
        'sender_zip': 'clear', 'sender_latitude': 'zero', 'sender_longitude': 'zero',
        'sender_phone': 'clear', 'sender_mobile': 'clear', 'sender_email': 'clear',
        # Receiver
        'receiver_name': 'anonymize_char', 'receiver_street': 'anonymize_char',
        'receiver_street_2': 'clear', 'receiver_city': 'anonymize_char',
        'receiver_zip': 'clear', 'receiver_latitude': 'zero', 'receiver_longitude': 'zero',
        'receiver_phone': 'clear', 'receiver_mobile': 'clear', 'receiver_email': 'clear',
        # Notification
        'notification_email': 'clear', 'notification_phone': 'clear',
        'receiver_notification_email': 'clear', 'receiver_notification_phone': 'clear',
    }

    # Tier 1: Locked after draft — require cancellation to change
    _LOCKED_FIELDS = {
        'customer_id', 'company_id', 'transport_order_type_id',
        'goods_profile_id', 'freight_service_id', 'origin',
    }

    # Tier 2: Editable after draft but changes are logged as amendments
    _CONTROLLED_FIELDS = {
        'sender_address_id', 'sender_name', 'sender_street', 'sender_street_2',
        'sender_city', 'sender_state_id', 'sender_zip', 'sender_country_id',
        'sender_latitude', 'sender_longitude', 'sender_phone', 'sender_mobile', 'sender_email',
        'receiver_address_id', 'receiver_name', 'receiver_street', 'receiver_street_2',
        'receiver_city', 'receiver_state_id', 'receiver_zip', 'receiver_country_id',
        'receiver_latitude', 'receiver_longitude', 'receiver_phone', 'receiver_mobile', 'receiver_email',
        'pick_up_date', 'pick_up_time_window', 'pick_up_time_from', 'pick_up_time_to',
        'delivery_date', 'delivery_time_window', 'delivery_time_from', 'delivery_time_to',
        'requirement_ids',
        'require_pickup_signature', 'require_pickup_photo',
        'require_pickup_assignment_scanning', 'require_pickup_goods_scanning',
        'require_delivery_signature', 'require_delivery_photo',
        'require_delivery_assignment_scanning', 'require_delivery_goods_scanning',
        'driving_distance_km', 'driving_distance_miles', 'manual_distance',
        'order_contact_id',
        'sender_contact_person', 'sender_contact_phone', 'sender_access_instructions',
        'receiver_contact_person', 'receiver_contact_phone', 'receiver_access_instructions',
        'incoterm_id', 'incoterm_location',
        'declared_goods_value', 'declared_goods_value_currency_id',
        'estimated_pickup_duration', 'estimated_delivery_duration',
        'notify_receiver_on_delivery', 'receiver_notification_email', 'receiver_notification_phone',
        'notify_receiver_on_dispatch',
    }

    def init(self):
        """Create partial index for fast recurring-order duplicate checks."""
        self.env.cr.execute("""
            CREATE INDEX IF NOT EXISTS idx_transport_order_recurrence_key
            ON transport_order (source_template_id, recurrence_target_date, recurrence_time_slot_id)
            WHERE source_template_id IS NOT NULL
        """)

    def _default_midnight(self):
        user_tz = self.env.user.tz or 'UTC'
        local = pytz.timezone(user_tz)
        now = datetime.now(local)
        midnight = datetime.combine(now.date(), time.min)

        # Adjust midnight to UTC
        midnight_utc = midnight - local.utcoffset(midnight)
        return midnight_utc

    number = fields.Char(string="Order number", required=True, tracking=True, default="New")
    priority = fields.Selection([
        ('0', 'Normal'),
        ('1', 'High'),
        ('2', 'Urgent'),
        ('3', 'Express'),
    ], string='Priority', default='0', tracking=True, index=True)
    company_id = fields.Many2one('res.company', string="Company", required=True, tracking=True, default=lambda self: self.env.user.company_id)
    last_updated_at = fields.Datetime(string="Last Updated", index=True, help="Deep update timestamp")
    selected_company_id = fields.Integer(string="Company ID", default=lambda self: self.company_id.id, store=False)
    selected_company_latitude = fields.Float(string="Company latitude", default=lambda self: self.company_id.partner_id.country_id.latitude, digits=(16, 5), store=False)
    selected_company_longitude = fields.Float(string="Company longitude", default=lambda self: self.company_id.partner_id.country_id.longitude, digits=(16, 5), store=False)
    active = fields.Boolean('Active', default=True, tracking=True)
    customer_id = fields.Many2one('res.partner', string='Customer', tracking=True, domain="[('id', 'in', customer_ids)]", ondelete="restrict")
    order_contact_id = fields.Many2one(
        'res.partner', string='Order Contact',
        domain="[('id', 'child_of', customer_id), ('is_company', '=', False)]",
        tracking=True,
        help="The specific person at the customer who placed the order."
    )
    transport_order_type_id = fields.Many2one('transport.order.type', string='Order type', domain="[('company_ids', 'in', company_id)]", ondelete="restrict")
    goods_profile_id = fields.Many2one(
        'goods.profile', string="Goods Profile",
        domain="[('company_ids', 'in', company_id)]",
        tracking=True,
        help="Controls which fields are visible and required on goods lines.",
    )
    # Related profile booleans for inline child views (parent.gp_show_*)
    gp_show_package_id = fields.Boolean(related='goods_profile_id.show_package_id', store=False)
    gp_show_goods_label = fields.Boolean(related='goods_profile_id.show_goods_label', store=False)
    gp_show_description = fields.Boolean(related='goods_profile_id.show_description', store=False)
    gp_show_quantity = fields.Boolean(related='goods_profile_id.show_quantity', store=False)
    gp_show_package_type = fields.Boolean(related='goods_profile_id.show_package_type', store=False)
    gp_show_dimensions = fields.Boolean(related='goods_profile_id.show_dimensions', store=False)
    gp_show_stacking = fields.Boolean(related='goods_profile_id.show_stacking', store=False)
    gp_show_volume = fields.Boolean(related='goods_profile_id.show_volume', store=False)
    gp_show_ldm = fields.Boolean(related='goods_profile_id.show_ldm', store=False)
    gp_show_gross_weight = fields.Boolean(related='goods_profile_id.show_gross_weight', store=False)
    gp_show_volumetric_weight = fields.Boolean(related='goods_profile_id.show_volumetric_weight', store=False)
    gp_show_billable_weight = fields.Boolean(related='goods_profile_id.show_billable_weight', store=False)
    gp_show_adr = fields.Boolean(related='goods_profile_id.show_adr', store=False)
    gp_show_container = fields.Boolean(related='goods_profile_id.show_container', store=False)
    gp_show_liquid = fields.Boolean(related='goods_profile_id.show_liquid', store=False)
    gp_show_temperature = fields.Boolean(related='goods_profile_id.show_temperature', store=False)
    gp_show_material_type = fields.Boolean(related='goods_profile_id.show_material_type', store=False)

    require_delivery_signature = fields.Boolean(string="Require Delivery Signature", default=False, tracking=True)
    require_delivery_photo = fields.Boolean(string="Require Delivery Photo", default=False, tracking=True)
    require_delivery_assignment_scanning = fields.Boolean(string="Require Delivery Assignment Scanning", default=False, tracking=True)
    require_delivery_goods_scanning = fields.Boolean(string="Require Delivery Goods Scanning", default=False, tracking=True)
    require_pickup_signature = fields.Boolean(string="Require Pickup Signature", default=False, tracking=True)
    require_pickup_photo = fields.Boolean(string="Require Pickup Photo", default=False, tracking=True)
    require_pickup_assignment_scanning = fields.Boolean(string="Require Pickup Assignment Scanning", default=False, tracking=True)
    require_pickup_goods_scanning = fields.Boolean(string="Require Pickup Goods Scanning", default=False, tracking=True)

    require_work_time_reporting = fields.Boolean(
        string="Require Work Time Reporting",
        default=False,
        tracking=True,
        help=(
            "When enabled, the driver is asked in the mobile app to confirm "
            "or correct a suggested work shift time (derived from pickup and "
            "delivery timestamps) on assignments derived from this order. "
            "Cascades from order type; cascades to road assignments."
        ),
    )

    require_material_reporting = fields.Boolean(
        string="Require Material Reporting",
        default=False,
        tracking=True,
        help=(
            "When enabled, the driver is asked to report actual delivered/"
            "picked-up quantity per goods line on assignments derived from "
            "this order. Cascades from order type; cascades to road "
            "assignments."
        ),
    )

    # ── Notification Preferences (copied from customer onchange, overridable per order) ──
    notification_email = fields.Char("Notification Email",
        help="Email address(es) for notifications. Comma-separate multiple addresses. Defaults from customer contact.")
    notification_phone = fields.Char("Notification Phone",
        help="Phone number(s) for SMS notifications. Comma-separate multiple numbers. Defaults from customer contact.")
    email_order_confirmed = fields.Boolean("Email: Order Confirmed", default=True)
    email_pickup_completed = fields.Boolean("Email: Pickup Completed", default=True)
    email_delivery_completed = fields.Boolean("Email: Delivery Completed", default=True)
    email_deviation_reported = fields.Boolean("Email: Deviation Reported", default=True)
    sms_order_confirmed = fields.Boolean("SMS: Order Confirmed", default=False)
    sms_pickup_completed = fields.Boolean("SMS: Pickup Completed", default=False)
    sms_delivery_completed = fields.Boolean("SMS: Delivery Completed", default=False)
    sms_deviation_reported = fields.Boolean("SMS: Deviation Reported", default=False)

    # ── Receiver Notifications (target the actual person receiving the goods) ──
    notify_receiver_on_delivery = fields.Boolean("Notify Receiver on Delivery", default=False,
        help="If checked, a separate notification will be sent to the receiver when delivery is completed.")
    notify_receiver_on_dispatch = fields.Boolean("Notify Receiver on Dispatch", default=False,
        help="If checked, a separate notification will be sent to the receiver when the delivery is on its way.")
    notify_receiver_via_email = fields.Boolean("Notify Receiver via Email", default=True,
        help="If checked, receiver notifications are sent by email when an "
             "event toggle (delivery/dispatch) fires.")
    notify_receiver_via_sms = fields.Boolean("Notify Receiver via SMS", default=False,
        help="If checked, receiver notifications are sent by SMS when an "
             "event toggle (delivery/dispatch) fires.")
    receiver_notification_email = fields.Char("Receiver Notification Email",
        help="Email address for the receiver. Defaults from receiver address.")
    receiver_notification_phone = fields.Char("Receiver Notification Phone",
        help="Phone number for receiver SMS. Defaults from receiver address.")

    notification_log_ids = fields.One2many(
        'transport.notification.log', 'transport_order_id',
        string="Notification Log",
    )

    # Template Logic
    template_id = fields.Many2one('transport.order.template', string="Order Template")

    # Custom Fields placeholders
    custom_bool_1 = fields.Boolean("Custom Boolean 1", tracking=True)
    custom_bool_2 = fields.Boolean("Custom Boolean 2", tracking=True)
    custom_bool_3 = fields.Boolean("Custom Boolean 3", tracking=True)
    custom_char_1 = fields.Char("Custom Char 1", tracking=True)
    custom_char_2 = fields.Char("Custom Char 2", tracking=True)
    custom_char_3 = fields.Char("Custom Char 3", tracking=True)
    custom_char_4 = fields.Char("Custom Char 4", tracking=True)
    custom_char_5 = fields.Char("Custom Char 5", tracking=True)
    custom_int_1 = fields.Integer("Custom Integer 1", tracking=True)
    custom_int_2 = fields.Integer("Custom Integer 2", tracking=True)
    custom_int_3 = fields.Integer("Custom Integer 3", tracking=True)
    custom_float_1 = fields.Float("Custom Float 1", tracking=True)
    custom_float_2 = fields.Float("Custom Float 2", tracking=True)
    custom_float_3 = fields.Float("Custom Float 3", tracking=True)
    custom_select_1 = fields.Many2one('custom.transport.options.1', string="Custom Select 1", tracking=True, domain="[('model_key', 'in', ['TO', 'TORA'])]")
    custom_select_2 = fields.Many2one('custom.transport.options.2', string="Custom Select 2", tracking=True, domain="[('model_key', 'in', ['TO', 'TORA'])]")
    custom_select_3 = fields.Many2one('custom.transport.options.3', string="Custom Select 3", tracking=True, domain="[('model_key', 'in', ['TO', 'TORA'])]")
    custom_select_4 = fields.Many2one('custom.transport.options.4', string="Custom Select 4", tracking=True, domain="[('model_key', 'in', ['TO', 'TORA'])]")
    custom_select_5 = fields.Many2one('custom.transport.options.5', string="Custom Select 5", tracking=True, domain="[('model_key', 'in', ['TO', 'TORA'])]")

    # TORA Custom Fields
    custom_tora_bool_1 = fields.Boolean("TORA Custom Boolean 1", tracking=True)
    custom_tora_bool_2 = fields.Boolean("TORA Custom Boolean 2", tracking=True)
    custom_tora_bool_3 = fields.Boolean("TORA Custom Boolean 3", tracking=True)
    custom_tora_char_1 = fields.Char("TORA Custom Char 1", tracking=True)
    custom_tora_char_2 = fields.Char("TORA Custom Char 2", tracking=True)
    custom_tora_char_3 = fields.Char("TORA Custom Char 3", tracking=True)
    custom_tora_char_4 = fields.Char("TORA Custom Char 4", tracking=True)
    custom_tora_char_5 = fields.Char("TORA Custom Char 5", tracking=True)
    custom_tora_int_1 = fields.Integer("TORA Custom Integer 1", tracking=True)
    custom_tora_int_2 = fields.Integer("TORA Custom Integer 2", tracking=True)
    custom_tora_int_3 = fields.Integer("TORA Custom Integer 3", tracking=True)
    custom_tora_float_1 = fields.Float("TORA Custom Float 1", tracking=True)
    custom_tora_float_2 = fields.Float("TORA Custom Float 2", tracking=True)
    custom_tora_float_3 = fields.Float("TORA Custom Float 3", tracking=True)
    custom_tora_select_1 = fields.Many2one('custom.transport.options.1', string="TORA Custom Select 1", tracking=True, domain="[('model_key', '=', 'TORA')]")
    custom_tora_select_2 = fields.Many2one('custom.transport.options.2', string="TORA Custom Select 2", tracking=True, domain="[('model_key', '=', 'TORA')]")
    custom_tora_select_3 = fields.Many2one('custom.transport.options.3', string="TORA Custom Select 3", tracking=True, domain="[('model_key', '=', 'TORA')]")
    custom_tora_select_4 = fields.Many2one('custom.transport.options.4', string="TORA Custom Select 4", tracking=True, domain="[('model_key', '=', 'TORA')]")
    custom_tora_select_5 = fields.Many2one('custom.transport.options.5', string="TORA Custom Select 5", tracking=True, domain="[('model_key', '=', 'TORA')]")

    # ── Recurring Order Back-links ──────────────────────────────────────
    source_template_id = fields.Many2one(
        'transport.order.template',
        string="Source Template",
        readonly=True,
        index=True,
        help="The recurring template that auto-generated this order.",
    )
    auto_generated = fields.Boolean(
        string="Auto-generated",
        readonly=True,
        default=False,
    )
    recurrence_target_date = fields.Date(
        string="Recurrence Date",
        readonly=True,
        help="The target recurrence date this order was generated for.",
    )
    recurrence_time_slot_id = fields.Many2one(
        'transport.order.template.time.slot',
        string="Time Slot",
        readonly=True,
        ondelete='set null',
    )

    @api.onchange('template_id')
    def _on_change_template_id(self):
        if self.template_id:
            self.apply_template_values(self.template_id)

    def apply_template_values(self, template):
        vals = {}
        # Simple Fields
        if template.company_id: vals['company_id'] = template.company_id.id
        if template.customer_id: vals['customer_id'] = template.customer_id.id
        if template.transport_order_type_id: vals['transport_order_type_id'] = template.transport_order_type_id.id
        if template.freight_service_id: vals['freight_service_id'] = template.freight_service_id.id
        if template.internal_details: vals['internal_details'] = template.internal_details
        if template.external_details: vals['external_details'] = template.external_details
        if template.invoicing_instructions: vals['invoicing_instructions'] = template.invoicing_instructions
        if template.invoice_reference: vals['invoice_reference'] = template.invoice_reference
        if template.pick_up_details: vals['pick_up_details'] = template.pick_up_details
        if template.delivery_details: vals['delivery_details'] = template.delivery_details
        
        # Addresses
        for prefix in ['sender', 'receiver']:
            for field in ['address_id', 'name', 'street', 'street_2', 'city', 'state_id', 'zip', 'country_id', 
                          'latitude', 'longitude', 'phone', 'mobile', 'email']:
                fn = f"{prefix}_{field}"
                val = getattr(template, fn)
                if val:
                    if hasattr(val, 'id'): # Many2one
                        vals[fn] = val.id
                    else:
                        vals[fn] = val
        
        # Price Zones — lookup based on template addresses
        for prefix in ['sender', 'receiver']:
            zip_val = vals.get(f'{prefix}_zip') or getattr(self, f'{prefix}_zip', False)
            country_val = vals.get(f'{prefix}_country_id')
            if not country_val:
                country_field = getattr(self, f'{prefix}_country_id', False)
                country_val = country_field.id if country_field else False
            if zip_val and country_val:
                zone_id = self._get_price_zone_for_address(zip_val, country_val)
                if zone_id:
                    vals[f'{prefix}_price_zone_id'] = zone_id

        # Time Logic
        # If template has specific time, we combine it with the Order's existing date or Today
        if template.pick_up_time:
            base_date = self.pick_up_date or fields.Date.context_today(self)
            hours = int(template.pick_up_time)
            minutes = int((template.pick_up_time * 60) % 60)
            # Use False for second/microsecond
            try:
                dt = datetime.combine(base_date, time(hours, minutes))
                # Adjust for timezone? Float time in template often implies local time or business time.
                # DateTime fields in Odoo are UTC.
                # Ideally we should convert "User's preferred 14:00" to UTC.
                # For now simplify: User enters 14.5 (14:30). We treat it as server standard. 
                # Improving: If user tz is set, convert.
                vals['pick_up_time_from'] = dt
                vals['pick_up_time_window'] = False # Disable window if specific time is set
            except Exception:
                pass

        if template.delivery_time:
            # For delivery, default to pick_up_date or today
            base_date = self.delivery_date or self.pick_up_date or fields.Date.context_today(self)
            hours = int(template.delivery_time)
            minutes = int((template.delivery_time * 60) % 60)
            try:
                dt = datetime.combine(base_date, time(hours, minutes))
                vals['delivery_time_from'] = dt
                vals['delivery_time_window'] = False
            except Exception:
                pass

        # Update main record vals
        if vals:
             self.update(vals)

        # Goods Lines (One2many)
        # We need to create goods lines. Since this is onchange, we use Command.clear/create
        # OR just append. Request implies "register all fields". 
        # Safest is to append if we want to avoid data loss, or replace if we treat valid template as source of truth.
        # Let's replace if lines are empty, append if not? Or just append. 
        # "Insert into the form".
        
        lines = []
        # Clear existing? 
        # lines.append(Command.clear()) 
        
        for t_line in template.goods_line_ids:
            line_vals = {
                'goods_label': t_line.goods_label,
                'description': t_line.description,
                'quantity': t_line.quantity,
                'package_type_id': t_line.package_type_id.id,
                'length': t_line.length,
                'width': t_line.width,
                'height': t_line.height,
                'volume_compute_method': t_line.volume_compute_method,
                'volume_manual': t_line.volume_manual,
                'ldm_compute_method': t_line.ldm_compute_method,
                'ldm_manual': t_line.ldm_manual,
                'gross_weight': t_line.gross_weight,
                'stackable': t_line.stackable,
                'stacking_factor': t_line.stacking_factor,
            }
            lines.append(Command.create(line_vals))
            
        if lines:
            self.update({'goods_line_ids': lines})

    def action_save_as_template(self):
        self.ensure_one()
        return {
            'name': _('Save as Template'),
            'type': 'ir.actions.act_window',
            'res_model': 'transport.order.template.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_name': f"Template from {self.number}"}
        }

    def action_update_template(self):
        self.ensure_one()
        if not self.template_id:
            return
            
        # Update Template Logic (Reverse of apply)
        t = self.template_id
        vals = {
            'company_id': self.company_id.id,
            'customer_id': self.customer_id.id,
            'transport_order_type_id': self.transport_order_type_id.id,
            'freight_service_id': self.freight_service_id.id,
            'internal_details': self.internal_details,
            'external_details': self.external_details,
            'invoicing_instructions': self.invoicing_instructions,
            'invoice_reference': self.invoice_reference,
            'pick_up_details': self.pick_up_details,
            'delivery_details': self.delivery_details,
        }
        
        # Times
        if self.pick_up_time_from:
             vals['pick_up_time'] = self.pick_up_time_from.hour + self.pick_up_time_from.minute / 60.0
        if self.delivery_time_from:
             vals['delivery_time'] = self.delivery_time_from.hour + self.delivery_time_from.minute / 60.0
             
        # Addresses (Loop same fields)
        for prefix in ['sender', 'receiver']:
            for field in ['address_id', 'name', 'street', 'street_2', 'city', 'state_id', 'zip', 'country_id', 
                          'latitude', 'longitude', 'phone', 'mobile', 'email']:
                val = getattr(self, f"{prefix}_{field}")
                if hasattr(val, 'id'):
                     vals[f"{prefix}_{field}"] = val.id
                else:
                     vals[f"{prefix}_{field}"] = val
        
        t.write(vals)
        
        # Lines: Replace all template lines with current order lines
        t.goods_line_ids.unlink()
        for line in self.goods_line_ids:
            self.env['transport.order.template.line'].create({
                'template_id': t.id,
                'goods_label': line.goods_label,
                'description': line.description,
                'quantity': line.quantity,
                'package_type_id': line.package_type_id.id,
                'length': line.length,
                'width': line.width,
                'height': line.height,
                'volume_compute_method': line.volume_compute_method,
                'volume_manual': line.volume_manual,
                'ldm_compute_method': line.ldm_compute_method,
                'ldm_manual': line.ldm_manual,
                'gross_weight': line.gross_weight,
                'stackable': line.stackable,
                'stacking_factor': line.stacking_factor,
            })
            
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Success'),
                'message': _('Template updated successfully!'),
                'type': 'success',
                'sticky': False,
            }
        }

    @api.onchange('transport_order_type_id')
    def _onchange_transport_order_type_id(self):
        if self.transport_order_type_id:
            self.require_delivery_signature = self.transport_order_type_id.require_delivery_signature
            self.require_delivery_photo = self.transport_order_type_id.require_delivery_photo
            self.require_delivery_assignment_scanning = self.transport_order_type_id.require_delivery_assignment_scanning
            self.require_delivery_goods_scanning = self.transport_order_type_id.require_delivery_goods_scanning

            self.require_pickup_signature = self.transport_order_type_id.require_pickup_signature
            self.require_pickup_photo = self.transport_order_type_id.require_pickup_photo
            self.require_pickup_assignment_scanning = self.transport_order_type_id.require_pickup_assignment_scanning
            self.require_pickup_goods_scanning = self.transport_order_type_id.require_pickup_goods_scanning

            self.require_work_time_reporting = self.transport_order_type_id.require_work_time_reporting
            self.require_material_reporting = self.transport_order_type_id.require_material_reporting

            # Auto-set goods profile from order type (overridable)
            if self.transport_order_type_id.goods_profile_id:
                self.goods_profile_id = self.transport_order_type_id.goods_profile_id

            # Copy default requirements from order type
            if self.transport_order_type_id.requirement_ids:
                self.requirement_ids = [Command.set(self.transport_order_type_id.requirement_ids.ids)]
            
            self.estimated_pickup_duration = self.transport_order_type_id.default_pickup_duration
            self.estimated_delivery_duration = self.transport_order_type_id.default_delivery_duration

    @api.onchange('goods_profile_id')
    def _onchange_goods_profile_id(self):
        """Clear goods-line data that belongs to categories the new profile hides."""
        profile = self.goods_profile_id
        if not profile or not self.goods_line_ids:
            return

        # Map profile flags → goods.line fields to clear
        category_fields = {
            'show_container': {
                'label': _("Container"),
                'fields': {'container_type_id': False, 'container_number': False,
                           'container_seal_number': False, 'container_tare_weight': 0},
            },
            'show_temperature': {
                'label': _("Temperature"),
                'fields': {'temperature_min': 0, 'temperature_max': 0},
            },
            'show_material_type': {
                'label': _("Material Type"),
                'fields': {'material_type_id': False, 'waste_code': False},
            },
            'show_liquid': {
                'label': _("Liquid/Bulk"),
                'fields': {'volume_liters': 0, 'liquid_density': 0,
                           'liquid_product_name': False},
            },
            'show_adr': {
                'label': _("ADR / Dangerous Goods"),
                'fields': {'is_dangerous_goods': False, 'adr_substance_id': False,
                           'adr_description': False, 'net_explosive_mass': 0,
                           'adr_limited_quantity': False, 'environmentally_hazardous': False},
            },
        }

        cleared_categories = []
        for flag, cat in category_fields.items():
            if getattr(profile, flag, True):
                continue  # Profile shows this category — skip
            # Check if any goods line has data in these fields
            has_data = False
            for line in self.goods_line_ids:
                for fname, empty_val in cat['fields'].items():
                    val = getattr(line, fname, empty_val)
                    if empty_val is False and val:
                        has_data = True
                        break
                    if isinstance(empty_val, (int, float)) and val:
                        has_data = True
                        break
                if has_data:
                    break
            if not has_data:
                continue
            # Clear the fields on all goods lines
            for line in self.goods_line_ids:
                for fname, empty_val in cat['fields'].items():
                    setattr(line, fname, empty_val)
            cleared_categories.append(cat['label'])

        if cleared_categories:
            return {
                'warning': {
                    'title': _("Goods data cleared"),
                    'message': _(
                        "The new goods profile does not support the following categories. "
                        "Data in these fields has been cleared from all goods lines:\n\n• %s\n\n"
                        "If this was unintentional, discard your changes."
                    ) % "\n• ".join(cleared_categories),
                }
            }

    order_reference = fields.Char(string='Order reference', tracking=True)
    project_code = fields.Char(string='Project code', tracking=True)
    trailer_width_m = fields.Float(string='Trailer Width (m)', default=0.0, tracking=True, help="Override global trailer width for this order's LDM calculation.")
    freight_service_id = fields.Many2one('freight.service', string='Freight service', domain="[('company_ids', 'in', company_id)]", ondelete="restrict")
    internal_details = fields.Text(string='Internal details', tracking=True)
    external_details = fields.Text(string='External details', tracking=True)
    invoicing_instructions = fields.Text(string="Invoicing Instructions", tracking=True)
    invoice_reference = fields.Char(string="Invoice Reference", tracking=True, help="Reference to be printed on the Invoice")
    pick_up_date = fields.Date(string='Pick up date', tracking=True, default=fields.Date.context_today )
    pick_up_time_window = fields.Boolean(string='Pick up time window', tracking=True, default=False)
    pick_up_time_from = fields.Datetime(string='Pick up time from', tracking=True)
    pick_up_time_to = fields.Datetime(string='Pick up time to', tracking=True)
    pick_up_details = fields.Text(string='Pick up details', tracking=True)
    delivery_date = fields.Date(string='Delivery date', tracking=True)
    delivery_time_window = fields.Boolean(string='Delivery time window', tracking=True, default=False)
    delivery_time_from = fields.Datetime(string='Delivery time from', tracking=True)
    delivery_time_to = fields.Datetime(string='Delivery time to', tracking=True)
    delivery_details = fields.Text(string='Delivery details', tracking=True)
    start_time = fields.Datetime(compute='_compute_start_time', string="Start time", store=True)
    end_time = fields.Datetime(compute='_compute_end_time', string="End time", store=True)
    waybill_number = fields.Char(string="Waybill number", tracking=True)
    estimatedTimeOfDelivery = fields.Datetime(string="ETA", tracking=True)

    tracking_url = fields.Char(string="Tracking URL", compute="_compute_tracking_url", store=False)

    def _compute_tracking_url(self):
        base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url')
        for rec in self:
            if rec.state in ('confirmed', 'planned', 'started', 'done', 'closed'):
                if not rec.access_token:
                    rec._portal_ensure_token()
                rec.tracking_url = f"{base_url}/track/{rec.id}?access_token={rec.access_token}"
            else:
                rec.tracking_url = False

    state = fields.Selection([
        ('draft', 'Draft'),
        ('confirmed', 'Confirmed'),
        ('planned', 'Planned'),
        ('started', 'Started'),
        ('done', 'Done'),
        ('closed', 'Closed'),
        ('cancelled', 'Cancelled'),
    ], string="State", tracking=True, compute='_compute_transport_order_state',
       inverse='_inverse_state', store=True, readonly=False, default="draft")
    cancel_reason = fields.Text(string="Cancellation Reason", tracking=True, readonly=True)
    commercial_state = fields.Selection([
        ('unpriced', 'Unpriced'),
        ('priced', 'Priced'),
        ('approved', 'Approved'),
        ('invoiced', 'Invoiced'),
    ], string="Billing Status", compute='_compute_commercial_state',
       store=True, readonly=True, default='unpriced')

    can_settle_commercial = fields.Boolean(
        compute='_compute_can_settle_commercial',
    )

    prices_approved = fields.Boolean(
        string="Prices Approved", default=False, tracking=True,
        help="Indicates that the revenue prices have been reviewed and approved for invoicing.",
    )

    prices_stale = fields.Boolean(
        string="Prices Outdated", default=False,
        help="Set to True when price-affecting fields change after prices were generated.",
    )

    shipping_legs_stale = fields.Boolean(
        string="Shipping Legs Outdated", default=False,
        help="Set to True when routing-affecting fields change after assignments were generated.",
    )

    has_stale_data = fields.Boolean(
        compute='_compute_has_stale_data', store=True,
        string="Has Stale Data",
    )

    evidence_status = fields.Selection([
        ('not_required', 'Not Required'),
        ('complete', 'Complete'),
        ('partial', 'Partial'),
        ('missing', 'Missing'),
    ], string="Reporting Status", compute='_compute_evidence_status',
       readonly=True, default='not_required')

    has_deviation = fields.Boolean(
        string="Has Deviation",
        compute='_compute_has_deviation',
        readonly=True,
    )
    deviation_ids = fields.Many2many(
        'road.assignment.deviation',
        string='Deviations',
        compute='_compute_deviation_ids',
    )

    # Fields that, when changed, mean existing prices may be outdated
    _PRICE_AFFECTING_FIELDS = {
        'customer_id', 'company_id', 'freight_service_id', 'transport_order_type_id',
        'sender_address_id', 'receiver_address_id',
        'sender_zip', 'receiver_zip', 'sender_country_id', 'receiver_country_id',
        'driving_distance_km', 'total_billable_weight',
        'total_gross_weight', 'total_volume', 'total_ldm',
    }

    # Quantity-source fields per price_type (registry-derived). When any of
    # these change on the order, contract-linked lines get re-priced.
    _QUANTITY_SOURCE_FIELDS = {
        cfg['quantity_source']
        for cfg in R.PRICE_TYPES.values()
        if cfg.get('quantity_source')
    }

    # Fields that, when changed, mean existing shipping legs / assignments may be outdated
    _SHIPPING_LEG_AFFECTING_FIELDS = {
        # Routing-critical (determines which legs/districts are used)
        'company_id', 'transport_order_type_id',
        'total_billable_weight',
        # Addresses (copied to assignments + used for district lookup)
        'sender_address_id', 'sender_name', 'sender_street', 'sender_street_2',
        'sender_zip', 'sender_city', 'sender_state_id', 'sender_country_id',
        'sender_latitude', 'sender_longitude',
        'sender_phone', 'sender_mobile', 'sender_email',
        'receiver_address_id', 'receiver_name', 'receiver_street', 'receiver_street_2',
        'receiver_zip', 'receiver_city', 'receiver_state_id', 'receiver_country_id',
        'receiver_latitude', 'receiver_longitude',
        'receiver_phone', 'receiver_mobile', 'receiver_email',
        # Details & requirements (copied to assignments)
        'pick_up_details', 'delivery_details',
        'require_pickup_signature', 'require_pickup_photo',
        'require_pickup_assignment_scanning', 'require_pickup_goods_scanning',
        'require_delivery_signature', 'require_delivery_photo',
        'require_delivery_assignment_scanning', 'require_delivery_goods_scanning',
        # Times (used to calculate planned pickup/delivery on assignments)
        'pick_up_date', 'pick_up_time_from',
        # Time windows (copied to assignments)
        'pick_up_time_window', 'pick_up_time_to',
        'delivery_time_window', 'delivery_time_from', 'delivery_time_to',
        'estimated_pickup_duration', 'estimated_delivery_duration',
    }

    @api.depends('transport_order_line_ids', 'invoice_id', 'invoice_id.state', 'prices_approved')
    def _compute_commercial_state(self):
        for order in self:
            try:
                if order.invoice_id and order.invoice_id.state == 'posted':
                    order.commercial_state = 'invoiced'
                elif order.transport_order_line_ids and order.prices_approved:
                    order.commercial_state = 'approved'
                elif order.transport_order_line_ids:
                    order.commercial_state = 'priced'
                else:
                    order.commercial_state = 'unpriced'
            except Exception:
                order.commercial_state = 'unpriced'

    @api.depends_context('uid')
    def _compute_can_settle_commercial(self):
        result = self.env.user.has_group(
            'transport_management.group_commercial_settlement_user'
        )
        for rec in self:
            rec.can_settle_commercial = result

    def action_approve_prices(self):
        self.write({'prices_approved': True})

    def action_unapprove_prices(self):
        self.write({'prices_approved': False})

    @api.depends('prices_stale', 'shipping_legs_stale')
    def _compute_has_stale_data(self):
        for order in self:
            order.has_stale_data = order.prices_stale or order.shipping_legs_stale

    @api.depends(
        'road_assignment_ids.require_pickup_signature',
        'road_assignment_ids.require_pickup_photo',
        'road_assignment_ids.require_pickup_assignment_scanning',
        'road_assignment_ids.require_pickup_goods_scanning',
        'road_assignment_ids.require_delivery_signature',
        'road_assignment_ids.require_delivery_photo',
        'road_assignment_ids.require_delivery_assignment_scanning',
        'road_assignment_ids.require_delivery_goods_scanning',
        'road_assignment_ids.pickup_signature',
        'road_assignment_ids.pickup_photo',
        'road_assignment_ids.pickup_photo_ids',
        'road_assignment_ids.pickup_scan_payload_json',
        'road_assignment_ids.delivery_signature',
        'road_assignment_ids.delivery_photo',
        'road_assignment_ids.delivery_photo_ids',
        'road_assignment_ids.delivery_scan_payload_json',
    )
    def _compute_evidence_status(self):
        for order in self:
            assignments = order.road_assignment_ids
            if not assignments:
                order.evidence_status = 'not_required'
                continue

            statuses = set()
            for assignment in assignments:
                statuses.add(assignment.evidence_status)

            if 'missing' in statuses:
                order.evidence_status = 'missing'
            elif 'partial' in statuses:
                order.evidence_status = 'partial'
            elif statuses == {'complete'}:
                order.evidence_status = 'complete'
            elif 'complete' in statuses and 'not_required' in statuses:
                order.evidence_status = 'complete'
            else:
                order.evidence_status = 'not_required'

    @api.depends('road_assignment_ids.has_deviation')
    def _compute_has_deviation(self):
        for order in self:
            order.has_deviation = any(a.has_deviation for a in order.road_assignment_ids)

    work_start_time = fields.Datetime(
        string='Work Shift Start',
        compute='_compute_work_shift_totals', store=True,
        help="Earliest work_start_time across all linked road assignments.")
    work_end_time = fields.Datetime(
        string='Work Shift End',
        compute='_compute_work_shift_totals', store=True,
        help="Latest work_end_time across all linked road assignments.")
    total_work_duration_hours = fields.Float(
        string='Total Work Duration (h)',
        compute='_compute_work_shift_totals', store=True, digits=(16, 2),
        help="Sum of work_duration_hours across all linked road assignments. "
             "Used as basis for hourly billing.")

    @api.depends(
        'road_assignment_ids.work_start_time',
        'road_assignment_ids.work_end_time',
        'road_assignment_ids.work_duration_hours',
    )
    def _compute_work_shift_totals(self):
        for order in self:
            assignments = order.road_assignment_ids
            starts = assignments.mapped('work_start_time')
            ends = assignments.mapped('work_end_time')
            order.work_start_time = min(starts) if starts else False
            order.work_end_time = max(ends) if ends else False
            order.total_work_duration_hours = sum(assignments.mapped('work_duration_hours'))

    @api.depends('road_assignment_ids.deviation_ids')
    def _compute_deviation_ids(self):
        for order in self:
            order.deviation_ids = order.road_assignment_ids.mapped('deviation_ids')

    origin = fields.Selection([
        ('internal', 'Internal'),
        ('portal', 'Portal'),
        ('integration', 'Integration'),
    ], string="Origin", default='internal', tracking=True)
    sender_address = fields.Char(compute='_compute_sender_address', string="Sender Address (Display)", store=False)
    sender_address_id = fields.Many2one('res.partner', string='Sender address', tracking=True, domain="[('id', 'in', customer_delivery_address_ids)]")
    sender_name = fields.Char(string='Sender Name', tracking=True, store=True)
    sender_street = fields.Char(string='Sender Street', tracking=True, store=True)
    sender_street_2 = fields.Char(string='Sender Street 2', tracking=True, store=True)
    sender_city = fields.Char(string='Sender City', tracking=True, store=True)
    sender_state_id = fields.Many2one('res.country.state', string='Sender State', tracking=True, store=True)
    sender_zip = fields.Char(string='Sender ZIP', tracking=True, store=True)
    sender_country_id = fields.Many2one('res.country', string='Sender Country', tracking=True, store=True, default=lambda self: self.env.company.country_id)
    sender_country_state_required = fields.Boolean(string='Sender State Required', related='sender_country_id.state_required')
    sender_latitude = fields.Float(string='Sender latitude', digits=(16, 5), store=True)
    sender_longitude = fields.Float(string='Sender longitude', digits=(16, 5), store=True)
    sender_geo_coordinates = fields.Char(string="Sender geo coordinates", compute='_compute_sender_geo_coordinates')
    sender_phone = fields.Char(string='Sender Phone', tracking=True, store=True)
    sender_mobile = fields.Char(string='Sender Mobile', tracking=True, store=True)
    sender_email = fields.Char(string='Sender Email', tracking=True, store=True)
    sender_contact_person = fields.Char(string='Sender Contact Person', tracking=True, help="Specific contact person at the pickup location for this order.")
    sender_contact_phone = fields.Char(string='Sender Contact Phone', tracking=True, help="Phone number for the pickup contact person.")
    sender_access_instructions = fields.Text(string='Sender Access Instructions', tracking=True, help="Specific instructions for accessing the pickup location (overrides address-level instructions).")
    sender_price_zone_id = fields.Many2one(
        'transport.price.zone', string="Sender Zone", tracking=True,
        help="Auto-set from sender address via district lookup. Can be overridden.")
    receiver_address = fields.Char(compute='_compute_receiver_address', string="Receiver Address (Display)", store=False)
    receiver_address_id = fields.Many2one('res.partner', string='Receiver address', domain="[('id', 'in', customer_delivery_address_ids)]", tracking=True, required=False)
    receiver_name = fields.Char(string='Receiver Name', tracking=True, store=True)
    receiver_street = fields.Char(string='Receiver Street', tracking=True, store=True)
    receiver_street_2 = fields.Char(string='Receiver Street 2', tracking=True, store=True)
    receiver_city = fields.Char(string='Receiver City', tracking=True, store=True)
    receiver_state_id = fields.Many2one('res.country.state', string='Receiver State', tracking=True, store=True)
    receiver_zip = fields.Char(string='Receiver ZIP', tracking=True, store=True)
    receiver_country_id = fields.Many2one('res.country', string='Receiver Country', tracking=True, store=True, default=lambda self: self.env.company.country_id)
    receiver_country_state_required = fields.Boolean(string='Receiver State Required', related='receiver_country_id.state_required')
    receiver_latitude = fields.Float(string='Receiver latitude', digits=(16, 5), store=True)
    receiver_longitude = fields.Float(string='Receiver longitude', digits=(16, 5), store=True)
    receiver_geo_coordinates = fields.Char(string="Receiver geo coordinates", compute='_compute_receiver_geo_coordinates')
    receiver_phone = fields.Char(string='Receiver Phone', tracking=True, store=True)
    receiver_mobile = fields.Char(string='Receiver Mobile', tracking=True, store=True)
    receiver_email = fields.Char(string='Receiver Email', tracking=True, store=True)
    receiver_contact_person = fields.Char(string='Receiver Contact Person', tracking=True, help="Specific contact person at the delivery location for this order.")
    receiver_contact_phone = fields.Char(string='Receiver Contact Phone', tracking=True, help="Phone number for the delivery contact person.")
    receiver_access_instructions = fields.Text(string='Receiver Access Instructions', tracking=True, help="Specific instructions for accessing the delivery location (overrides address-level instructions).")
    receiver_price_zone_id = fields.Many2one(
        'transport.price.zone', string="Receiver Zone", tracking=True,
        help="Auto-set from receiver address via district lookup. Can be overridden.")
    manual_distance = fields.Boolean(string='Manual distance', tracking=True, default=False, store=True)
    driving_distance_km = fields.Float(string='Driving distance (km)', digits=(16, 5), tracking=True, store=True)
    driving_distance_miles = fields.Float(string='Driving distance (miles)', digits=(16, 5), tracking=True, store=True)
    distance_unit = fields.Selection([('km', 'Kilometers'),('miles', 'Miles')], string="Distance Unit", default=lambda self: self.env.user.distance_unit or 'km', required=True, store=False)
    goods_line_ids = fields.One2many('goods.line','transport_order_id', string="Goods lines")
    road_assignment_ids = fields.One2many('road.assignment','transport_order_id', string="Assignments")
    document_ids = fields.One2many('transport.document', 'transport_order_id', string='Documents')
    document_count = fields.Integer(compute='_compute_document_count', string='Document Count')
    transport_order_line_ids = fields.One2many('transport.order.line','transport_order_id', string="Transport Order Lines")
    transport_order_line_ids_parents_only = fields.One2many('transport.order.line','transport_order_id',string="Financial Line",domain=[('parent_line_id', '=', False)])
    customer_ids = fields.Many2many('res.partner', string='Customers', compute='_compute_customer_ids')
    customer_delivery_address_ids = fields.Many2many('res.partner', compute='_compute_customer_delivery_address_ids')
    customer_customer_delivery_address_ids = fields.Many2many('res.partner', compute='_compute_customer_customer_delivery_address_ids')
    total_gross_weight = fields.Float(string="Total gross weight", compute='_compute_total_gross_weight', store=True, tracking=True)
    total_billable_weight = fields.Float(string="Total billable weight", compute='_compute_total_billable_weight', store=True, tracking=True)
    total_volumetric_weight = fields.Float(string="Total volumetric weight", compute='_compute_total_volumetric_weight', store=True, tracking=True)

    total_volume = fields.Float(string="Total Volume", compute='_compute_total_volume', store=True, tracking=True)
    total_ldm = fields.Float(string="Total LDM", compute='_compute_total_ldm', store=True, tracking=True)
    goods_description = fields.Char(string="Goods", compute='_compute_goods_description', store=True)
    goods_full_summary = fields.Text(string="Goods Full Summary", compute='_compute_goods_full_summary', store=True, tracking=True)
    order_lines_summary = fields.Text(string="Order Lines Summary", compute='_compute_order_lines_summary', store=True, tracking=True)
    assignments_summary = fields.Text(string="Assignments Summary", compute='_compute_assignments_summary', store=True, tracking=True)
    events_summary = fields.Text(string="Events Summary", compute='_compute_events_summary', store=True, tracking=True)

    requirement_ids = fields.Many2many('transport.requirement', string="Requirements")
    incoterm_id = fields.Many2one('account.incoterms', string='Incoterm', tracking=True)
    incoterm_location = fields.Char(string='Incoterm Location', tracking=True, help="Delivery place associated with the incoterm")
    
    declared_goods_value = fields.Monetary(string="Declared Goods Value", currency_field='declared_goods_value_currency_id', tracking=True)
    declared_goods_value_currency_id = fields.Many2one('res.currency', string="Declared Goods Value Currency", default=lambda self: self.env.company.currency_id)

    # ── French freight documents (lettre de voiture nationale) ──
    # The commissionnaire de transport (freight forwarder) is a distinct legal
    # party from the carrier under French law and is a mandatory mention when
    # the transport is arranged through one.
    commissionnaire_id = fields.Many2one(
        'res.partner', string="Commissionnaire de transport", tracking=True,
        help="Freight forwarder arranging the transport, when distinct from the "
             "carrier. Mandatory mention on the French lettre de voiture when applicable.")
    # Sommes à encaisser / contre-remboursement — cash to collect on delivery.
    cod_amount = fields.Monetary(
        string="Contre-remboursement", currency_field='cod_currency_id', tracking=True,
        help="Amount to collect on delivery (sommes à encaisser).")
    cod_currency_id = fields.Many2one(
        'res.currency', string="COD Currency",
        default=lambda self: self.env.company.currency_id)

    estimated_pickup_duration = fields.Integer(string='Estimated Pickup Duration (min)', tracking=True)
    estimated_delivery_duration = fields.Integer(string='Estimated Delivery Duration (min)', tracking=True)

    def _update_requirement_tag(self, auto_field_name, is_active):
        """ Updates requirement_ids based on a flag and the requirement's auto_field """
        # Only proceed if we are in a proper environment (not during some basic model loading)
        if not self.env.registry.ready:
            return

        tag = self.env['transport.requirement'].search([('auto_field', '=', auto_field_name)], limit=1)
        if not tag:
            return
        
        # We use Command to be safe with Odoo's ORM within writes/updates
        # But here we are often in a compute loop, checking specific IDs is safer
        
        current_ids = self.requirement_ids.ids
        if is_active:
             if tag.id not in current_ids:
                 self.requirement_ids = [Command.link(tag.id)]
        else:
             if tag.id in current_ids:
                 self.requirement_ids = [Command.unlink(tag.id)]

    bulky_goods = fields.Boolean(
        string="Bulky Goods",
        compute='_compute_bulky_goods',
        store=True,
        tracking=True
    )

    @api.depends('goods_line_ids', 'goods_line_ids.gross_weight', 'goods_line_ids.length', 
                 'goods_line_ids.width', 'goods_line_ids.height')
    def _compute_bulky_goods(self):
        for order in self:
            is_bulky = False
            for line in order.goods_line_ids:
                weight = line.gross_weight or 0.0
                
                # Check if the line matches any bulky goods criteria
                # The logic is consistent with goods.line implementation
                domain = [
                    ('company_ids', 'in', order.company_id.id),
                    ('gross_weight_from', '<=', weight),
                    ('gross_weight_to', '>', weight),
                    ('length_from', '<=', line.length),
                    ('length_to', '>', line.length),
                    ('width_from', '<=', line.width),
                    ('width_to', '>', line.width),
                    ('height_from', '<=', line.height),
                    ('height_to', '>', line.height)
                ]
                
                # If we find at least one matching criteria, the order contains bulky goods
                if self.env['bulky.goods.criteria'].search_count(domain, limit=1):
                    is_bulky = True
                    break
            
            order.bulky_goods = is_bulky
            order._update_requirement_tag('bulky_goods', is_bulky)

    has_dangerous_goods = fields.Boolean(
        string="Has Dangerous Goods",
        compute='_compute_has_dangerous_goods',
        store=True,
        tracking=True
    )
    hazmat_emergency_phone = fields.Char(
        string="Hazmat Emergency Phone", tracking=True,
        help="24-hour emergency response telephone number printed on the US "
             "Bill of Lading for hazardous materials. Prefilled from the company; "
             "leave empty to fall back to the company default on the printout.")

    @api.onchange('company_id')
    def _onchange_company_hazmat_phone(self):
        """Prefill the emergency phone from the company (UI convenience). The
        BOL also falls back to the company value, so an empty field is fine."""
        if not self.hazmat_emergency_phone and self.company_id.hazmat_emergency_phone:
            self.hazmat_emergency_phone = self.company_id.hazmat_emergency_phone

    assignment_count = fields.Integer(compute='_compute_assignment_count', string="Assignment Count")
    goods_line_count = fields.Integer(compute='_compute_goods_line_count', string="Goods Line Count")

    @api.depends('road_assignment_ids')
    def _compute_assignment_count(self):
        for order in self:
            order.assignment_count = len(order.road_assignment_ids)

    @api.depends('goods_line_ids')
    def _compute_goods_line_count(self):
        for order in self:
            order.goods_line_count = len(order.goods_line_ids)

    @api.depends('document_ids')
    def _compute_document_count(self):
        for order in self:
            order.document_count = len(order.document_ids)

    def action_view_assignments(self):
        self.ensure_one()
        return {
            'name': _('Assignments'),
            'type': 'ir.actions.act_window',
            'res_model': 'road.assignment',
            'view_mode': 'list,form',
            'domain': [('transport_order_id', '=', self.id)],
            'context': {'default_transport_order_id': self.id},
        }

    def action_view_goods(self):
        self.ensure_one()
        return {
            'name': _('Goods Lines'),
            'type': 'ir.actions.act_window',
            'res_model': 'goods.line',
            'view_mode': 'list,form',
            'domain': [('transport_order_id', '=', self.id)],
            'context': {'default_transport_order_id': self.id},
        }

    def action_view_financial_lines(self):
        self.ensure_one()
        return {
            'name': _('Financial Lines'),
            'type': 'ir.actions.act_window',
            'res_model': 'transport.order.line',
            'view_mode': 'list,form',
            'domain': [('transport_order_id', '=', self.id)],
            'context': {'default_transport_order_id': self.id},
        }

    @api.depends('goods_line_ids', 'goods_line_ids.is_dangerous_goods')
    def _compute_has_dangerous_goods(self):
        for order in self:
            val = any(line.is_dangerous_goods for line in order.goods_line_ids)
            order.has_dangerous_goods = val
            order._update_requirement_tag('has_dangerous_goods', val)

    def get_adr_lines(self):
        """Returns dangerous goods lines sorted by ADR Class then UN Number."""
        lines = self.goods_line_ids.filtered(lambda l: l.is_dangerous_goods)
        return lines.sorted(key=lambda l: (l.adr_class or '', l.un_number or ''))

    has_temperature_requirement = fields.Boolean(
        string="Temperature Controlled",
        compute='_compute_has_temperature_requirement',
        store=True,
        tracking=True,
    )

    @api.depends('goods_line_ids.temperature_min', 'goods_line_ids.temperature_max')
    def _compute_has_temperature_requirement(self):
        for order in self:
            val = any(
                (line.temperature_min or 0) != 0 or (line.temperature_max or 0) != 0
                for line in order.goods_line_ids
            )
            order.has_temperature_requirement = val
            order._update_requirement_tag('has_temperature_requirement', val)

    order_currency_id = fields.Many2one(
        related='company_id.currency_id',
        string="Order Currency",
        store=True
    )
    system_currency_id = fields.Many2one(
        'res.currency', 
        string="System Currency", 
        compute='_compute_order_totals',
        store=True,
        help="The system-wide commercial currency from configuration."
    )
    total_system_currency = fields.Monetary(
        string="Total System Currency",
        compute='_compute_order_totals',
        store=True,
        currency_field='system_currency_id',
        help="Total price of all sales and cost lines, converted to the system's commercial currency."
    )
    total_product_currency = fields.Monetary(
        string="Total Order Currency",
        compute='_compute_order_totals',
        store=True,
        currency_field='order_currency_id',
        help="Total price of all sales and cost lines, converted to this order's company currency."
    )
    total_order_revenue = fields.Monetary(
        string="Total Order Revenue",
        compute='_compute_revenue_totals',
        store=True,
        currency_field='order_currency_id',
        help="Total revenue calculated ONLY from transport order lines (excludes assignment costs)."
    )
    total_system_revenue = fields.Monetary(
        string="Total System Revenue",
        compute='_compute_revenue_totals',
        store=True,
        currency_field='system_currency_id',
        help="Total system revenue calculated ONLY from transport order lines (excludes assignment costs)."
    )

    total_order_cost = fields.Monetary(
        string="Total Order Cost",
        compute='_compute_margin_totals',
        store=True,
        currency_field='order_currency_id',
        help="Total cost calculated from all road assignments."
    )
    total_system_cost = fields.Monetary(
        string="Total System Cost",
        compute='_compute_margin_totals',
        store=True,
        currency_field='system_currency_id',
        help="Total cost calculated from all road assignments."
    )
    margin = fields.Monetary(
        string="Margin",
        compute='_compute_margin_totals',
        store=True,
        currency_field='order_currency_id',
        help="Revenue - Cost (in Order Currency)"
    )
    margin_percent = fields.Float(
        string="Margin %",
        compute='_compute_margin_totals',
        store=True,
        aggregator="avg",
        help="(Revenue - Cost) / Revenue * 100"
    )

    @api.depends('total_order_revenue', 'total_system_revenue', 
                 'road_assignment_ids.total_system_cost', 
                 'company_id.currency_id', 'pick_up_date')
    def _compute_margin_totals(self):
        """
        Calculates total cost from assignments and derives the margin.
        """
        # Get system currency once
        config_param = self.env['ir.config_parameter'].sudo().get_param('transport_management.commercial_currency_id')
        system_currency = None
        if config_param:
            try:
                system_currency = self.env['res.currency'].browse(int(config_param))
            except ValueError:
                system_currency = None
        if not system_currency:
             system_currency = self.env.company.currency_id or self.env.ref('base.USD', raise_if_not_found=False)

        for order in self:
            # 1. Calculate Total System Cost (sum of assignments)
            t_system_cost = sum(a.total_system_cost for a in order.road_assignment_ids)
            order.total_system_cost = t_system_cost

            # 2. Calculate Total Order Cost (convert System Cost -> Order Currency)
            # Use pick_up_date or today for conversion
            conversion_date = order.pick_up_date or fields.Date.context_today(order)
            order_currency = order.company_id.currency_id

            if system_currency and order_currency and system_currency != order_currency:
                t_order_cost = system_currency._convert(
                    t_system_cost,
                    order_currency,
                    order.company_id,
                    conversion_date
                )
            else:
                 t_order_cost = t_system_cost

            order.total_order_cost = t_order_cost
            
            # 3. Calculate Margin
            order.margin = order.total_order_revenue - order.total_order_cost
            
            # 4. Calculate Margin % (Ratio)
            if order.total_order_revenue:
                order.margin_percent = order.margin / order.total_order_revenue
            else:
                order.margin_percent = 0.0

    margin_color = fields.Selection([
        ('red', 'Red'),
        ('yellow', 'Yellow'),
        ('green', 'Green')
    ], string="Margin Color", compute='_compute_margin_color', store=False)

    @api.depends('margin_percent')
    def _compute_margin_color(self):
        ICPSudo = self.env['ir.config_parameter'].sudo()
        # Default 0.0 and 15.0 if not set
        red_thresh = float(ICPSudo.get_param('transport_management.margin_threshold_red', 0.0))
        yellow_thresh = float(ICPSudo.get_param('transport_management.margin_threshold_yellow', 15.0))

        for order in self:
            # margin_percent is a ratio (0.25 = 25%)
            # Thresholds are in percentage (25.0 = 25%)
            mp_val = order.margin_percent * 100.0
            if mp_val < red_thresh:
                order.margin_color = 'red'
            elif mp_val <= yellow_thresh:
                order.margin_color = 'yellow'
            else:
                order.margin_color = 'green'

    def action_open_address_import_wizard(self):
        self.ensure_one()
        field_to_update = self.env.context.get('field_to_update')
        
        wizard = self.env['address.import.wizard'].create({
            'target_model': 'transport.order',
            'transport_order_id': self.id,
            'field_to_update': field_to_update,
        })
        
        return {
            'name': _('Import Address'),
            'type': 'ir.actions.act_window',
            'res_model': 'address.import.wizard',
            'res_id': wizard.id,
            'view_mode': 'form',
            'target': 'new',
        }

    def action_save_sender_to_address_book(self):
        self.ensure_one()
        if self.sender_address_id:
            return

        vals = {
            'name': self.sender_name or _('New Address'),
            'street': self.sender_street,
            'street2': self.sender_street_2,
            'city': self.sender_city,
            'zip': self.sender_zip,
            'state_id': self.sender_state_id.id,
            'country_id': self.sender_country_id.id,
            'phone': self.sender_phone,
            'mobile': self.sender_mobile,
            'email': self.sender_email,
            'type': 'other',
            'parent_id': self.customer_id.id if self.customer_id else False
        }
        partner = self.env['res.partner'].create(vals)
        self.sender_address_id = partner.id

    def action_save_receiver_to_address_book(self):
        self.ensure_one()
        if self.receiver_address_id:
            return

        vals = {
            'name': self.receiver_name or _('New Address'),
            'street': self.receiver_street,
            'street2': self.receiver_street_2,
            'city': self.receiver_city,
            'zip': self.receiver_zip,
            'state_id': self.receiver_state_id.id,
            'country_id': self.receiver_country_id.id,
            'phone': self.receiver_phone,
            'mobile': self.receiver_mobile,
            'email': self.receiver_email,
            'type': 'delivery',
            'parent_id': self.customer_id.id if self.customer_id else False
        }
        partner = self.env['res.partner'].create(vals)
        self.receiver_address_id = partner.id
    
    @api.depends('company_id.currency_id', 'pick_up_date',
                 'transport_order_line_ids.price', 'transport_order_line_ids.currency_id')
    def _compute_revenue_totals(self):
        """
        Calculates the total revenue (Transport Order Lines ONLY) in both system 
        and company currency, ignoring road assignment costs.
        """
        # Get the system currency once
        config_param = self.env['ir.config_parameter'].sudo().get_param('transport_management.commercial_currency_id')
        system_currency = None
        if config_param:
            try:
                system_currency = self.env['res.currency'].browse(int(config_param))
            except ValueError:
                system_currency = None
        
        # Fallback if not configured or param is invalid
        if not system_currency:
            system_currency = self.env.company.currency_id or self.env.ref('base.USD', raise_if_not_found=False)

        for order in self:
            company_currency = order.company_id.currency_id
            
            total_system_val = 0.0
            total_company_val = 0.0
            
            # Use today's date for conversion if no order date is set
            conversion_date = order.pick_up_date or fields.Date.context_today(order)

            # Sum Transport Order Lines ONLY
            for line in order.transport_order_line_ids:
                if line.currency_id and line.price and company_currency:
                    # Convert to System Currency
                    total_system_val += line.currency_id._convert(
                        line.price,
                        system_currency,
                        order.company_id,
                        conversion_date
                    )
                    # Convert to Company Currency
                    total_company_val += line.currency_id._convert(
                        line.price,
                        company_currency,
                        order.company_id,
                        conversion_date
                    )
            
            order.total_system_revenue = total_system_val
            order.total_order_revenue = total_company_val

    waybill_number = fields.Char(string='Waybill Number', tracking=True)
    event_ids = fields.One2many(
        'assignment.event',
        'transport_order_id',
        string='Assignment Events',
        copy=False
    )

    is_this_week = fields.Boolean(
        string="Is This Week",
        compute='_compute_week_flags',
        store=True
    )
    is_next_week = fields.Boolean(
        string="Is Next Week",
        compute='_compute_week_flags',
        store=True
    )
    is_previous_week = fields.Boolean(
        string="Is Previous Week",
        compute='_compute_week_flags',
        store=True
    )
    direct_invoice_id = fields.Many2one(
        'account.move',
        string="Direct Invoice",
        readonly=True,
        index=True,
        help="Invoice created directly from this Transport Order (without Sales Order)."
    )

    invoice_id = fields.Many2one(
        'account.move',
        string="Invoice",
        compute='_compute_invoice_id',
        store=True,
        readonly=True,
        help="The Invoice linked to this Transport Order (via Sales Order or directly)."
    )

    @api.depends(
        'sales_order_id.invoice_ids', 'sales_order_id.invoice_ids.state',
        'direct_invoice_id', 'direct_invoice_id.state',
    )
    def _compute_invoice_id(self):
        for order in self:
            so = order.sudo().sales_order_id
            if so and so.invoice_ids:
                # Path A: TO created from a Sales Order — invoice via SO
                invoices = so.invoice_ids.filtered(
                    lambda inv: inv.move_type == 'out_invoice'
                ).sorted(lambda inv: inv.id, reverse=True)
                order.invoice_id = invoices[0] if invoices else False
            elif order.direct_invoice_id:
                # Path B: standalone TO — invoice created directly
                order.invoice_id = order.direct_invoice_id
            else:
                order.invoice_id = False
    def action_create_and_post_invoice(self):
        """
        Creates and posts invoices for selected Transport Orders.
        - SO-linked TOs: invoiced via the Sales Order (existing flow).
        - Standalone TOs: invoiced directly (account.move created from TO lines).
        """
        so_linked = self.filtered(lambda o: o.sudo().sales_order_id)
        standalone = self - so_linked

        if so_linked:
            so_linked._action_create_and_post_invoice_via_so()
        if standalone:
            standalone.action_create_invoice_direct()

    def _action_create_and_post_invoice_via_so(self):
        """Invoice via Sales Order (for TOs created from a SO)."""
        for order in self:
            so = order.sudo().sales_order_id
            if not so:
                continue

            if so.state in ['draft', 'sent']:
                so.action_confirm()

            if so.invoice_status == 'to invoice':
                invoices = so._create_invoices()
                for invoice in invoices:
                    if order.incoterm_id:
                        invoice.invoice_incoterm_id = order.incoterm_id.id
                    if order.incoterm_location:
                        invoice.incoterm_location = order.incoterm_location
                    if invoice.state == 'draft':
                        invoice.action_post()

    # ── Direct invoicing (standalone TOs, no SO) ──────────────────────

    def _prepare_invoice_vals(self):
        """Build account.move vals for a single standalone transport order."""
        self.ensure_one()
        partner = self.customer_id
        invoice_partner = self.order_contact_id or partner

        fiscal_position = self.env['account.fiscal.position']._get_fiscal_position(partner)
        payment_term = partner.property_payment_term_id

        return {
            'move_type': 'out_invoice',
            'partner_id': invoice_partner.id,
            'company_id': self.company_id.id,
            'currency_id': self.order_currency_id.id,
            'invoice_origin': self.number,
            'ref': self.invoice_reference or self.number,
            'fiscal_position_id': fiscal_position.id if fiscal_position else False,
            'invoice_payment_term_id': payment_term.id if payment_term else False,
            'invoice_incoterm_id': self.incoterm_id.id if self.incoterm_id else False,
            'incoterm_location': self.incoterm_location or False,
            'invoice_line_ids': self._prepare_invoice_line_vals(),
        }

    def _prepare_invoice_line_vals(self):
        """Build account.move.line vals from transport.order.line records.
        Creates a separate invoice line for each parent and child line."""
        self.ensure_one()
        line_vals = []
        for line in self.transport_order_line_ids:
            if not line.product_id:
                continue
            # Skip child lines here — they are handled via their parent
            if line.parent_line_id:
                continue

            # Parent line
            line_vals.append(self._prepare_single_invoice_line(line))

            # Child (add-on) lines as separate invoice lines
            for child in line.child_line_ids:
                if child.product_id:
                    line_vals.append(self._prepare_single_invoice_line(child))

        return line_vals

    def _prepare_single_invoice_line(self, to_line):
        """Build a single account.move.line Command.create from a transport.order.line."""
        account = to_line.product_id._get_product_accounts()['income']
        taxes = to_line.product_id.taxes_id.filtered(
            lambda t: t.company_id == self.company_id
        )
        return Command.create({
            'product_id': to_line.product_id.id,
            'name': to_line.product_id.display_name,
            'quantity': to_line.quantity,
            'price_unit': to_line.price_per_unit,
            'account_id': account.id,
            'tax_ids': [Command.set(taxes.ids)],
        })

    def action_create_invoice_direct(self):
        """Create and post account.move directly for standalone TOs (no SO)."""
        if not self.env.user.has_group('transport_management.group_commercial_settlement_user'):
            raise UserError(_("Only users with the Commercial Settlement role can create invoices."))

        AccountMove = self.env['account.move'].sudo()

        for order in self:
            if order.sales_order_id:
                continue  # SO-linked: handled by SO flow
            if order.direct_invoice_id:
                continue  # already invoiced directly
            if not order.customer_id or not order.transport_order_line_ids:
                continue

            vals = order._prepare_invoice_vals()
            invoice = AccountMove.create(vals)
            invoice.action_post()

            order.direct_invoice_id = invoice.id
            order.message_post(body=_("Invoice %s created and posted.", invoice.name))

    def action_create_consolidated_invoices_direct(self):
        """Create consolidated invoices for standalone TOs, grouped by
        customer + currency + payment terms."""
        if not self.env.user.has_group('transport_management.group_commercial_settlement_user'):
            raise UserError(_("Only users with the Commercial Settlement role can create invoices."))

        standalone = self.filtered(
            lambda o: not o.sales_order_id
                      and not o.direct_invoice_id
                      and o.customer_id
                      and o.transport_order_line_ids
        )
        if not standalone:
            raise ValidationError(_("No standalone orders ready to invoice."))

        # Group by (invoice_partner, currency, payment_term)
        groups = defaultdict(lambda: self.env['transport.order'])
        for order in standalone:
            invoice_partner = order.order_contact_id or order.customer_id
            currency = order.order_currency_id
            payment_term = order.customer_id.property_payment_term_id
            key = (invoice_partner.id, currency.id, payment_term.id if payment_term else 0)
            groups[key] |= order

        AccountMove = self.env['account.move'].sudo()
        invoices = self.env['account.move']

        for (partner_id, currency_id, pt_id), orders in groups.items():
            partner = self.env['res.partner'].browse(partner_id)
            fiscal_position = self.env['account.fiscal.position']._get_fiscal_position(
                orders[0].customer_id
            )

            all_line_vals = []
            origins = []
            for order in orders:
                all_line_vals.extend(order._prepare_invoice_line_vals())
                origins.append(order.number)

            vals = {
                'move_type': 'out_invoice',
                'partner_id': partner_id,
                'company_id': orders[0].company_id.id,
                'currency_id': currency_id,
                'invoice_origin': ', '.join(origins),
                'fiscal_position_id': fiscal_position.id if fiscal_position else False,
                'invoice_payment_term_id': pt_id or False,
                'invoice_line_ids': all_line_vals,
            }
            invoice = AccountMove.create(vals)
            invoice.action_post()
            invoices |= invoice

            for order in orders:
                order.direct_invoice_id = invoice.id
                order.message_post(body=_("Consolidated invoice %s created.", invoice.name))

        return {
            'name': _('Consolidated Invoices'),
            'type': 'ir.actions.act_window',
            'res_model': 'account.move',
            'view_mode': 'list,form',
            'domain': [('id', 'in', invoices.ids)],
            'context': {'create': False},
        }
            
    sales_order_id = fields.Many2one(
        'sale.order',
        string="Sales Order",
        readonly=True,
        tracking=True,
        index=True,
        help="Set when this Transport Order was created from a Sales Order. "
             "When set, invoicing flows through the Sales Order."
    )
    def action_create_consolidated_invoices(self):
        """
        Creates consolidated invoices for selected Transport Orders.
        - SO-linked TOs: consolidated via Sales Order (existing Odoo logic).
        - Standalone TOs: consolidated directly from TO lines.
        """
        so_linked = self.filtered(lambda o: o.sudo().sales_order_id)
        standalone = self - so_linked

        all_invoices = self.env['account.move']

        if so_linked:
            result = so_linked._action_create_consolidated_invoices_via_so()
            if result and result.get('domain'):
                all_invoices |= self.env['account.move'].search(result['domain'])

        if standalone:
            result = standalone.action_create_consolidated_invoices_direct()
            if result and result.get('domain'):
                all_invoices |= self.env['account.move'].search(result['domain'])

        if not all_invoices:
            raise ValidationError(_("No orders were ready to be invoiced."))

        return {
            'name': _('Consolidated Invoices'),
            'type': 'ir.actions.act_window',
            'res_model': 'account.move',
            'view_mode': 'list,form',
            'domain': [('id', 'in', all_invoices.ids)],
            'context': {'create': False},
        }

    def _action_create_consolidated_invoices_via_so(self):
        """Consolidated invoicing via Sales Orders (for SO-linked TOs)."""
        sale_orders = self.sudo().mapped('sales_order_id')
        if not sale_orders:
            return None

        draft_sos = sale_orders.filtered(lambda so: so.state in ['draft', 'sent'])
        if draft_sos:
            draft_sos.action_confirm()

        invoiceable_orders = sale_orders.filtered(lambda so: so.invoice_status == 'to invoice')
        if not invoiceable_orders:
            return None

        invoices = invoiceable_orders._create_invoices()
        if invoices:
            invoices.action_post()

        return {
            'domain': [('id', 'in', invoices.ids)],
        }
    @api.depends('pick_up_date')
    def _compute_week_flags(self):
        """
        Computes boolean flags to check if the record's pickup date
        is in the current week, previous week, or the next week.
        """
        today = date.today()
        # Assumes week starts on Monday (weekday=0)
        start_of_this_week = today - relativedelta(days=today.weekday())
        end_of_this_week = start_of_this_week + relativedelta(days=6)
        start_of_next_week = start_of_this_week + relativedelta(weeks=1)
        end_of_next_week = end_of_this_week + relativedelta(weeks=1)
        start_of_prev_week = start_of_this_week - relativedelta(weeks=1)
        end_of_prev_week = start_of_this_week - relativedelta(days=1)

        for record in self:
            record.is_this_week = False
            record.is_next_week = False
            record.is_previous_week = False
            if record.pick_up_date:
                pickup_date = record.pick_up_date
                if start_of_this_week <= pickup_date <= end_of_this_week:
                    record.is_this_week = True
                elif start_of_next_week <= pickup_date <= end_of_next_week:
                    record.is_next_week = True
                elif start_of_prev_week <= pickup_date <= end_of_prev_week:
                    record.is_previous_week = True

    def update_state_from_assignments(self):
        """
        Update the transport order's state based on the states of its related road assignments.
        The state is set to the highest-priority state among all assignments.
        """
        STATE_HIERARCHY = {
            'draft': 0,
            'confirmed': 1,
            'started': 2,
            'done': 3,
            'cancelled': 4,
        }
        # Get all assignment states
        assignment_states = [assign.state for assign in self.road_assignment_ids if assign.state]
        if not assignment_states:
            return
        # Find the highest-priority state
        highest_state = max(assignment_states, key=lambda s: STATE_HIERARCHY.get(s, 0))
        # Only upgrade, never downgrade
        current_state_level = STATE_HIERARCHY.get(self.state, 0)
        new_state_level = STATE_HIERARCHY.get(highest_state, 0)
        if new_state_level > current_state_level:
            self.state = highest_state


    @api.depends('create_date')
    def _compute_today_date(self):
        for record in self:
            record.today_date = fields.Date.context_today(self)

    @api.onchange('company_id')
    def _onchange_company_id(self):
        if self.company_id:
            self.selected_company_id = self.company_id.id
            self.selected_company_latitude = self.company_id.partner_id.country_id.latitude
            self.selected_company_longitude = self.company_id.partner_id.country_id.longitude

    def copy(self, default=None):
        default = dict(default or {})
        default.setdefault('state', 'draft')
        default.setdefault('number', 'New')
        default.setdefault('pick_up_date', fields.Date.context_today(self))
        default.setdefault('waybill_number', False)
        default.setdefault('invoice_reference', False)
        default.setdefault('road_assignment_ids', [Command.clear()])
        default.setdefault('transport_order_line_ids', [Command.clear()])

        # Build goods lines explicitly so goods_event_ids are excluded
        if 'goods_line_ids' not in default:
            goods_cmds = []
            for line in self.goods_line_ids:
                vals = line.copy_data()[0]
                if vals:
                    vals.pop('goods_event_ids', None)
                    goods_cmds.append(Command.create(vals))
            default['goods_line_ids'] = goods_cmds

        return super().copy(default)

    @api.model_create_multi
    def create(self, vals_list):

        for vals in vals_list:
            vals['last_updated_at'] = fields.Datetime.now()
            if vals.get('state') != 'draft':
                if not vals.get('number') or vals['number'] == 'New':
                    seq_id = self.env['ir.config_parameter'].sudo().get_param('transport_management.transport_order_sequence_id')
                    if seq_id:
                        vals['number'] = self.env['ir.sequence'].sudo().browse(int(seq_id)).next_by_id()
                    else:
                        vals['number'] = self.env['ir.sequence'].sudo().next_by_code('transport.order')

            if vals.get('pick_up_time_window'):
                vals['pick_up_date'] = None
            else:
                vals['pick_up_time_from'] = None
                vals['pick_up_time_to'] = None

            if vals.get('delivery_time_window'):
                vals['delivery_date'] = None
            else:
                vals['delivery_time_from'] = None
                vals['delivery_time_to'] = None

            # Auto-set price zones if not explicitly provided
            for prefix in ['sender', 'receiver']:
                zone_field = f'{prefix}_price_zone_id'
                if not vals.get(zone_field):
                    zip_code = vals.get(f'{prefix}_zip')
                    country_id = vals.get(f'{prefix}_country_id')
                    company_id = vals.get('company_id', self.env.company.id)
                    if zip_code and country_id:
                        district = self.env['transport.district'].sudo().get_matching_district(
                            company_id, zip_code, country_id)
                        if district and district.price_zone_id:
                            vals[zone_field] = district.price_zone_id.id

        orders = super().create(vals_list)

        for order in orders:
            criteria = order._find_matching_planning_criteria()
            is_direct = criteria and criteria.planning_type == 'direct'
            if order.transport_order_type_id.auto_plan_assignments or is_direct:
                try:
                    order.sudo().generate_assignments()
                except ValidationError:
                    pass  # Silently skip — address data not yet complete

        # Auto-generate transport order lines if enabled
        # Uses sudo() so portal users (who lack create on transport.order.line)
        # can still trigger automatic line generation when submitting orders.
        # Reuses the same full-featured method as the "Regenerate" button so
        # that parent/child structures, dedup and price calculation are
        # identical regardless of whether lines are auto-generated or
        # manually regenerated.
        icp = self.env['ir.config_parameter'].sudo()
        auto_gen = icp.get_param('transport_management.auto_generate_transport_order_lines')
        if auto_gen is False or str(auto_gen).lower() == 'true':
            for order in orders:
                try:
                    order.sudo().with_context(skip_approval_reset=True).generate_transport_order_lines()
                except Exception:
                    _logger.warning(
                        "Auto-generation of transport order lines failed for order %s",
                        order.id, exc_info=True,
                    )

        return orders

    def write(self, vals):
        # 1. Handle time window blanking (Applied to the whole batch)
        if 'pick_up_time_window' in vals:
            if vals.get('pick_up_time_window'):
                vals['pick_up_date'] = None
            else:
                vals['pick_up_time_from'] = None
                vals['pick_up_time_to'] = None

        if 'delivery_time_window' in vals:
            if vals.get('delivery_time_window'):
                vals['delivery_date'] = None
            else:
                vals['delivery_time_from'] = None
                vals['delivery_time_to'] = None

        # 2. Sequence Number Logic (Multi-record safe)
        # We only check this if 'number' is NOT in vals (to avoid recursion)
        if 'number' not in vals:
            # Find records that are moving to (or are in) a non-draft state but still have 'New' number
            for rec in self:
                effective_state = vals.get('state') or rec.state
                
                if effective_state != 'draft' and (rec.number == 'New' or not rec.number):
                    # Assign a new number
                    seq_id = self.env['ir.config_parameter'].sudo().get_param('transport_management.transport_order_sequence_id')
                    if seq_id:
                        new_no = self.env['ir.sequence'].sudo().browse(int(seq_id)).next_by_id()
                    else:
                        new_no = self.env['ir.sequence'].sudo().next_by_code('transport.order')
                    # Write immediately to this specific record
                    # We pass 'number' in vals so the recursive call skips this block
                    rec.write({'number': new_no})

        # 3. Tiered field locking
        if not self.env.context.get('skip_field_locking'):
            changed = set(vals)
            locked_changed = self._LOCKED_FIELDS & changed
            if locked_changed:
                locked_orders = self.filtered(lambda o: o.state not in ('draft', 'confirmed'))
                if locked_orders:
                    labels = sorted(self._fields[f].string for f in locked_changed if f in self._fields)
                    raise UserError(_(
                        "Cannot modify %(fields)s on planned/started/done orders. "
                        "Cancel the order and create a new one to change these fields.",
                        fields=', '.join(labels)
                    ))

        # 4. Auto-update price zones when zip/country changes
        for prefix in ['sender', 'receiver']:
            zip_key = f'{prefix}_zip'
            country_key = f'{prefix}_country_id'
            zone_key = f'{prefix}_price_zone_id'
            if (zip_key in vals or country_key in vals) and zone_key not in vals:
                for rec in self:
                    zip_code = vals.get(zip_key, rec[zip_key])
                    country = vals.get(country_key) or (rec[country_key].id if rec[country_key] else False)
                    company = vals.get('company_id', rec.company_id.id)
                    if zip_code and country:
                        district = self.env['transport.district'].get_matching_district(
                            company, zip_code, country)
                        zone_id = district.price_zone_id.id if district and district.price_zone_id else False
                        vals[zone_key] = zone_id

        # 5. Perform the actual Write
        if not self.env.context.get('skip_last_updated'):
            vals['last_updated_at'] = fields.Datetime.now()
        res = super(TransportOrder, self.with_context(skip_last_updated=True)).write(vals)

        # 5. Amendment logging for controlled fields changed after draft
        if not self.env.context.get('skip_field_locking'):
            controlled_changed = self._CONTROLLED_FIELDS & set(vals)
            if controlled_changed:
                for order in self.filtered(lambda o: o.state != 'draft'):
                    order._log_amendment(controlled_changed)

        # 6. Stale-price / stale-shipping-legs detection
        if not self.env.context.get('skip_stale_check'):
            changed = set(vals)

            # If any price-affecting field changed and we already have price lines → mark stale
            if self._PRICE_AFFECTING_FIELDS & changed:
                stale_orders = self.filtered(
                    lambda o: o.commercial_state in ('priced', 'approved') and not o.prices_stale
                )
                if stale_orders:
                    stale_orders.with_context(skip_stale_check=True).write({
                        'prices_stale': True,
                        'prices_approved': False,
                    })

            # If any quantity-source field changed → re-price contract-linked lines
            # so quantity follows the new value automatically (skips approved).
            if self._QUANTITY_SOURCE_FIELDS & changed:
                refreshable = self.filtered(
                    lambda o: not o.prices_approved and o.transport_order_line_ids
                )
                if refreshable:
                    refreshable.with_context(skip_stale_check=True)._auto_refresh_contract_prices()

            # If any shipping-leg-affecting field changed and we have assignments → mark stale
            if self._SHIPPING_LEG_AFFECTING_FIELDS & changed:
                stale_orders = self.filtered(
                    lambda o: o.road_assignment_ids and not o.shipping_legs_stale
                )
                if stale_orders:
                    stale_orders.with_context(skip_stale_check=True).write({'shipping_legs_stale': True})

        # 5. Propagate requirement changes to assignments
        #    When requirements are added on the order, add them to all assignments.
        #    Assignments may have extra requirements beyond the order's, but must
        #    always include all order-level requirements.
        if 'requirement_ids' in vals:
            for order in self:
                order_req_ids = set(order.requirement_ids.ids)
                for assignment in order.road_assignment_ids:
                    assignment_req_ids = set(assignment.requirement_ids.ids)
                    if not order_req_ids <= assignment_req_ids:
                        # Union: keep assignment extras + add any new order requirements
                        merged = list(assignment_req_ids | order_req_ids)
                        assignment.requirement_ids = [Command.set(merged)]

        # 6. Handle Coordinate Updates (Existing logic)
        coordinate_fields = ['sender_latitude', 'sender_longitude', 'receiver_latitude', 'receiver_longitude']
        if any(field in vals for field in coordinate_fields):
            _logger.info("Coordinate change detected, fetching new distance.")
            for order in self:
                if not order.manual_distance:
                    order.fetch_distance()

        # 6. Auto Plan Assignments
        # Check if any relevant field for planning changed
        # skip_auto_plan: used by address import wizard to avoid heavy side
        # effects that can interfere with the form reload (tab switching bug).
        if not self.env.context.get('skip_auto_plan'):
            planning_fields = [
                'company_id', 'transport_order_type_id',
                'goods_line_ids',
                'sender_address_id', 'sender_zip', 'sender_country_id',
                'receiver_address_id', 'receiver_zip', 'receiver_country_id',
                'start_time', 'pick_up_date', 'pick_up_time_from',
                'pick_up_details', 'delivery_details',
                'sender_street', 'sender_street_2', 'sender_city',
                'receiver_street', 'receiver_street_2', 'receiver_city',
                'estimated_pickup_duration', 'estimated_delivery_duration'
            ]

            if any(field in vals for field in planning_fields):
                for order in self:
                    criteria = order._find_matching_planning_criteria()
                    is_direct = criteria and criteria.planning_type == 'direct'
                    if order.transport_order_type_id.auto_plan_assignments or is_direct:
                        # Only auto-plan if no assignments are planned or beyond
                        # (to avoid overwriting assignments already on a transport load)
                        has_planned = any(
                            a.state in ('planned', 'in_progress', 'completed', 'closed')
                            for a in order.road_assignment_ids
                        )
                        if not has_planned:
                            try:
                                order.generate_assignments()
                            except ValidationError:
                                pass  # Silently skip — address data not yet complete
                        else:
                            order._auto_plan_blocked_warning()

        return res

    def _auto_plan_blocked_warning(self):
        """Send a bus notification when auto-plan cannot run because
        one or more assignments are already planned."""
        self.ensure_one()
        self.env['bus.bus']._sendone(
            self.env.user.partner_id,
            'simple_notification',
            {
                'type': 'warning',
                'title': _("Auto-planering blockerad"),
                'message': _(
                    "Ändringen är registrerad. Uppdragen genereras automatiskt, "
                    "men kunde inte genomföras då ett eller flera uppdrag redan "
                    "är planerade. Denna åtgärd måste hanteras manuellt."
                ),
                'sticky': True,
            },
        )

    def _log_amendment(self, changed_fields):
        """Post an amendment note in the chatter when controlled fields change after draft."""
        labels = sorted(self._fields[f].string for f in changed_fields if f in self._fields)
        body = _("Order amended after confirmation. Changed fields:\n%s") % '\n'.join("• %s" % l for l in labels)
        self.message_post(body=body, message_type='notification', subtype_xmlid='mail.mt_note')

    def action_confirm(self):
        for rec in self:
            if rec.state == "draft":
                errors = []
                
                if not rec.goods_line_ids:
                    errors.append(_("At least one goods line is required."))
                
                missing_sender = []
                if not rec.sender_name: missing_sender.append(_("Name"))
                if not rec.sender_city: missing_sender.append(_("City"))
                if not rec.sender_country_id: missing_sender.append(_("Country"))
                if missing_sender:
                    errors.append(_("Sender address is missing: %s" % ", ".join(missing_sender)))
                        
                missing_receiver = []
                if not rec.receiver_name: missing_receiver.append(_("Name"))
                if not rec.receiver_city: missing_receiver.append(_("City"))
                if not rec.receiver_country_id: missing_receiver.append(_("Country"))
                if missing_receiver:
                    errors.append(_("Receiver address is missing: %s" % ", ".join(missing_receiver)))
                
                if not rec.pick_up_date and not rec.pick_up_time_from:
                    errors.append(_("Pick-up date or Pick-up time is required."))
                
                if rec.transport_order_type_id and rec.transport_order_type_id.mandatory_field_ids:
                    for field in rec.transport_order_type_id.mandatory_field_ids:
                        field_val = rec[field.name]
                        # Handle basic truthiness (empty strings, empty relational fields, False, etc)
                        if not field_val:
                            errors.append(_("The field '%s' is mandatory for this order type.") % field.field_description)
                        
                if errors:
                    raise ValidationError(_("Cannot confirm order %(order_num)s because validation failed:\n\n%(errors)s", 
                                            order_num=rec.number, 
                                            errors="\n".join("• %s" % e for e in errors)))

                rec.state = "confirmed"
                rec._portal_ensure_token()
                self.env['transport.notification.service'].notify_order_confirmed(rec)

    def action_done(self):
        self.ensure_one()
        event_type = self.env['transport.event.type'].search([('code', '=', 70)], limit=1)

        # Smart default: pick the best assignment for delivery completion
        # Prefer DE/DI assignments, prioritised by state
        assignment_ids = self.road_assignment_ids.ids
        best_assignment = False
        if assignment_ids:
            active = self.road_assignment_ids.filtered(lambda a: a.state not in ('done', 'error', 'cancelled'))
            # 1) DE/DI that are in progress
            candidates = active.filtered(lambda a: a.transport_type_id.code in ('DE', 'DI'))
            # 2) any type in progress
            if not candidates:
                candidates = active
            if candidates:
                for pref_state in ('started', 'planned', 'confirmed', 'draft'):
                    match = candidates.filtered(lambda a: a.state == pref_state)
                    if match:
                        best_assignment = match[0]
                        break
                if not best_assignment:
                    best_assignment = candidates[0]

        ctx = {
            'default_transport_order_id': self.id,
            'default_event_type_id': event_type.id if event_type else False,
            'default_note': _('Use this modal to register a delivered event to complete the order.'),
            'domain_transport_assignment_id': [('id', 'in', assignment_ids)],
        }
        if best_assignment:
            ctx['default_transport_assignment_id'] = best_assignment.id

        return {
            'name': _('Register Delivered Event'),
            'type': 'ir.actions.act_window',
            'res_model': 'assignment.event',
            'view_mode': 'form',
            'target': 'new',
            'context': ctx,
        }

    def action_set_to_draft(self):
        for rec in self:
            rec.state = 'draft'

    @api.model
    def _touch_orders_class(self, ids):
        if not ids:
            return
        # Using raw SQL to avoid recursion or interfering with regular writes
        self.env.cr.execute(
            "UPDATE transport_order SET last_updated_at = %s WHERE id IN %s",
            (fields.Datetime.now(), tuple(ids))
        )


    def action_cancel(self):
        for rec in self:
            rec.state = "cancelled"

    @api.model
    def get_dashboard_config(self):
        params = self.env['ir.config_parameter'].sudo()
        return {
            'allocated_free': float(params.get_param(
                'transport_management.allocated_load_factor_free_threshold', 75.0)),
            'allocated_full': float(params.get_param(
                'transport_management.allocated_load_factor_full_threshold', 95.0)),
            'peak_free': float(params.get_param(
                'transport_management.peak_load_factor_free_threshold', 80.0)),
            'peak_full': float(params.get_param(
                'transport_management.peak_load_factor_full_threshold', 100.0)),
        }

    @api.model
    def delete_old_draft_orders(self):
        cutoff_date = fields.Datetime.now() - timedelta(hours=24)
        old_draft_orders = self.search([('state', '=', 'draft'), ('create_date', '<', cutoff_date)])
        count = len(old_draft_orders)
        old_draft_orders.unlink()
        
        # Set message for isotrax logging
        import threading
        thread = threading.current_thread()
        if hasattr(thread, 'isotrax_job_message'):
            thread.isotrax_job_message = f"{count} old draft orders deleted"
        return count

    @api.onchange('order_contact_id')
    def _onchange_order_contact_id(self):
        if self.order_contact_id and self.customer_id:
            # Check that the contact belongs to the customer (is a child of customer_id)
            if self.order_contact_id.id != self.customer_id.id and \
               self.order_contact_id.parent_id.id != self.customer_id.id:
                self.order_contact_id = False
                return {
                    'warning': {
                        'title': _('Invalid Contact'),
                        'message': _('The selected contact does not belong to the customer. It has been cleared.'),
                    }
                }

    @api.onchange('customer_id')
    def _onchange_customer_id(self):
        self.order_contact_id = False
        
        if self.customer_id and not self.sender_country_id:
            self.sender_country_id = self.customer_id.country_id
        if self.customer_id and not self.receiver_country_id:
            self.receiver_country_id = self.customer_id.country_id
        if self.customer_id:
            # Find the transport.customer linked to this partner to get the default ref
            transport_customer = self.env['transport.customer'].search([
                ('partner_id', '=', self.customer_id.id)
            ], limit=1)
            
            if transport_customer:
                if transport_customer.invoice_reference:
                    self.invoice_reference = transport_customer.invoice_reference
                # Copy notification preferences from customer
                self.email_order_confirmed = transport_customer.email_order_confirmed
                self.email_pickup_completed = transport_customer.email_pickup_completed
                self.email_delivery_completed = transport_customer.email_delivery_completed
                self.email_deviation_reported = transport_customer.email_deviation_reported
                self.sms_order_confirmed = transport_customer.sms_order_confirmed
                self.sms_pickup_completed = transport_customer.sms_pickup_completed
                self.sms_delivery_completed = transport_customer.sms_delivery_completed
                self.sms_deviation_reported = transport_customer.sms_deviation_reported
            # Default notification contact from transport.customer, fallback to res.partner
            if transport_customer:
                self.notification_email = transport_customer.notification_email or transport_customer.partner_id.email or ''
                self.notification_phone = transport_customer.notification_phone or transport_customer.partner_id.mobile or transport_customer.partner_id.phone or ''
            else:
                self.notification_email = self.customer_id.email or ''
                self.notification_phone = self.customer_id.mobile or self.customer_id.phone or ''

    def _get_price_zone_for_address(self, zip_code, country_id, latitude=None, longitude=None):
        """Resolve the price zone for an address.

        Precedence:
          1. A price zone with its OWN polygon that contains the point wins
             (explicit pricing geography, independent of operations).
          2. Otherwise fall back to district matching (polygon district, then
             ZIP prefix) and use that district's price zone.
        """
        if not country_id:
            return False
        if not zip_code and not (latitude and longitude):
            return False
        # 1. Direct price-zone geofence (own geography takes precedence).
        if latitude and longitude:
            zone = self.env['transport.price.zone'].get_matching_zone(
                self.company_id.id, latitude, longitude)
            if zone:
                return zone.id
        # 2. District → district.price_zone_id (polygon district, then ZIP).
        district = self.env['transport.district'].get_matching_district(
            self.company_id.id, zip_code,
            country_id.id if hasattr(country_id, 'id') else country_id,
            latitude=latitude, longitude=longitude,
        )
        return district.price_zone_id.id if district and district.price_zone_id else False

    @api.onchange('sender_address_id')
    def _onchange_sender_address_id(self):
        if self.sender_address_id:
            self.sender_name = self.sender_address_id.name
            self.sender_street = self.sender_address_id.street
            self.sender_street_2 = self.sender_address_id.street2
            self.sender_zip = self.sender_address_id.zip
            self.sender_city = self.sender_address_id.city
            self.sender_state_id = self.sender_address_id.state_id
            self.sender_country_id = self.sender_address_id.country_id
            self.sender_latitude = self.sender_address_id.partner_latitude
            self.sender_longitude = self.sender_address_id.partner_longitude
            self.sender_phone = self.sender_address_id.phone
            self.sender_mobile = self.sender_address_id.mobile
            self.sender_email = self.sender_address_id.email
            self.sender_contact_person = self.sender_address_id.name
            self.sender_contact_phone = self.sender_address_id.phone or self.sender_address_id.mobile
            self.sender_access_instructions = self.sender_address_id.access_instructions or (self.sender_address_id.parent_id.access_instructions if self.sender_address_id.parent_id else False)
            self.sender_price_zone_id = self._get_price_zone_for_address(
                self.sender_zip, self.sender_country_id,
                self.sender_latitude, self.sender_longitude)
            #self.fetch_distance()
            self._increment_address_usage(self.sender_address_id)

    @api.onchange('receiver_address_id')
    def _onchange_receiver_address_id(self):
        if self.receiver_address_id:
            self.receiver_name = self.receiver_address_id.name
            self.receiver_street = self.receiver_address_id.street
            self.receiver_street_2 = self.receiver_address_id.street2
            self.receiver_city = self.receiver_address_id.city
            self.receiver_state_id = self.receiver_address_id.state_id.id
            self.receiver_zip = self.receiver_address_id.zip
            self.receiver_country_id = self.receiver_address_id.country_id.id
            self.receiver_latitude = self.receiver_address_id.partner_latitude
            self.receiver_longitude = self.receiver_address_id.partner_longitude
            self.receiver_phone = self.receiver_address_id.phone
            self.receiver_mobile = self.receiver_address_id.mobile
            self.receiver_email = self.receiver_address_id.email

            self.receiver_contact_person = self.receiver_address_id.name
            self.receiver_contact_phone = self.receiver_address_id.phone or self.receiver_address_id.mobile
            self.receiver_access_instructions = self.receiver_address_id.access_instructions or (self.receiver_address_id.parent_id.access_instructions if self.receiver_address_id.parent_id else False)
            self.receiver_price_zone_id = self._get_price_zone_for_address(
                self.receiver_zip, self.receiver_country_id,
                self.receiver_latitude, self.receiver_longitude)
            #self.fetch_distance()
            self._increment_address_usage(self.receiver_address_id)

    @api.onchange('notify_receiver_via_email', 'notify_receiver_via_sms')
    def _onchange_receiver_notify_channels(self):
        """When a channel is toggled on, default the corresponding notification
        field from the receiver contact info if it is empty. Avoids the office
        having to remember to fill it in after enabling the channel."""
        if self.notify_receiver_via_email and not self.receiver_notification_email:
            self.receiver_notification_email = self.receiver_email
        if self.notify_receiver_via_sms and not self.receiver_notification_phone:
            self.receiver_notification_phone = self.receiver_mobile or self.receiver_phone

    @api.onchange('receiver_email', 'receiver_phone', 'receiver_mobile')
    def _onchange_receiver_contact_for_notifications(self):
        """Default the receiver notification email/phone from the receiver
        contact fields. Works both for partner-selected addresses (where the
        receiver_* fields are populated from the partner record) and for
        manually-entered addresses.

        Phone preference: mobile beats phone. When mobile is filled in later,
        the notification phone is upgraded from phone → mobile. Manual office
        overrides (a value that doesn't match either receiver_phone or
        receiver_mobile) are preserved untouched."""
        if not self.receiver_notification_email and self.receiver_email:
            self.receiver_notification_email = self.receiver_email

        preferred_phone = self.receiver_mobile or self.receiver_phone
        current = self.receiver_notification_phone
        # Auto-fill when empty, or when the current value matches one of the
        # receiver contact fields (i.e. previously auto-filled). Leave manual
        # overrides alone.
        if not current or current in (self.receiver_phone, self.receiver_mobile):
            self.receiver_notification_phone = preferred_phone

    @api.onchange('sender_zip', 'sender_country_id')
    def _onchange_sender_zip_country(self):
        if self.sender_zip and self.sender_country_id:
            self.sender_price_zone_id = self._get_price_zone_for_address(
                self.sender_zip, self.sender_country_id)

    @api.onchange('receiver_zip', 'receiver_country_id')
    def _onchange_receiver_zip_country(self):
        if self.receiver_zip and self.receiver_country_id:
            self.receiver_price_zone_id = self._get_price_zone_for_address(
                self.receiver_zip, self.receiver_country_id)

    @api.depends('company_id')
    def _compute_customer_ids(self):
        for record in self:

            customers = []

            if record.company_id:
                transport_customers = self.env['transport.customer'].sudo().search([
                    ('company_ids', 'in', record.company_id.id)
                ])

                for customer in transport_customers:
                    if customer.partner_id:
                        customers.append(customer.partner_id.id)

            record.customer_ids = [(6, 0, customers)]

    @api.depends('customer_id')
    def _compute_customer_delivery_address_ids(self):
        for order in self:
            if order.customer_id:
                # Only partners that are genuine addresses — exclude invoice
                # contacts and any partner that is linked to a user account
                # (internal users, portal users, template users, IsaBot, etc.)
                addresses = self.env['res.partner'].search([
                    ('type', '!=', 'invoice'),
                    ('user_ids', '=', False),
                ])
                order.customer_delivery_address_ids = addresses
            else:
                order.customer_delivery_address_ids = []

    @api.onchange('pick_up_time_window')
    def _onchange_pick_up_time_window(self):

        if self.pick_up_time_window == True:
            self.pick_up_date = None

        else:
            self.pick_up_time_from = None
            self.pick_up_time_to = None

    @api.onchange('delivery_time_window')
    def _onchange_delivery_time_window(self):

        if self.delivery_time_window:
            self.delivery_date = None
        else:
            self.delivery_time_from = None
            self.delivery_time_to = None

    @api.onchange('sender_latitude', 'sender_longitude', 'receiver_latitude', 'receiver_longitude')
    def _onchange_coordinates(self):
        self.fetch_distance()

    @api.onchange('manual_distance')
    def _onchange_manual_distance(self):
        self.fetch_distance()

    @api.onchange('driving_distance_km')
    def _onchange_driving_distance_km(self):
        self.driving_distance_miles = self.driving_distance_km*0.621371

    @api.onchange('driving_distance_miles')
    def _onchange_driving_distance_miles(self):
        self.driving_distance_km = self.driving_distance_miles/0.621371

    @api.depends('goods_line_ids.gross_weight')
    def _compute_total_gross_weight(self):
        for order in self:
            total_weight = sum(line.gross_weight for line in order.goods_line_ids)
            order.total_gross_weight = total_weight

    @api.depends('goods_line_ids.billable_weight')
    def _compute_total_billable_weight(self):
        for order in self:
            total_weight = sum(line.billable_weight for line in order.goods_line_ids)
            order.total_billable_weight = total_weight

    @api.depends('goods_line_ids.volumetric_weight')
    def _compute_total_volumetric_weight(self):
        for order in self:
            total_weight = sum(line.volumetric_weight for line in order.goods_line_ids)
            order.total_volumetric_weight = total_weight

    @api.depends('goods_line_ids.volume_m3')
    def _compute_total_volume(self):
        for order in self:
            total_volume = sum(line.volume_m3 for line in order.goods_line_ids)
            order.total_volume = total_volume

    @api.depends('goods_line_ids.ldm')
    def _compute_total_ldm(self):
        for order in self:
            order.total_ldm = sum(line.ldm for line in order.goods_line_ids)

    @api.depends('goods_line_ids.quantity', 'goods_line_ids.package_type_id',
                 'goods_line_ids.container_type_id',
                 'goods_line_ids.is_dangerous_goods', 'goods_line_ids.stackable',
                 'total_billable_weight', 'total_volume', 'total_ldm')
    def _compute_goods_description(self):
        """Compute a canonical one-line goods description, e.g. '1 PLL, 3 PKT · 300 kg · 2.50 m³'."""
        for order in self:
            if not order.goods_line_ids:
                order.goods_description = False
                continue
            # Aggregate packages by type code, containers by container type code
            pkgs = {}
            cnts = {}
            for line in order.goods_line_ids:
                if line.container_type_id:
                    ct_code = line.container_type_id.code
                    cnts[ct_code] = cnts.get(ct_code, 0) + (line.quantity or 1)
                else:
                    code = line.package_type_id.code if line.package_type_id else 'pkg'
                    pkgs[code] = pkgs.get(code, 0) + (line.quantity or 1)
            parts = []
            if pkgs:
                parts.append(", ".join(f"{int(qty)} {code}" for code, qty in sorted(pkgs.items())))
            if cnts:
                parts.append(", ".join(f"{int(qty)} {code}" for code, qty in sorted(cnts.items())))
            if order.total_billable_weight:
                w = order.total_billable_weight
                parts.append(f"{w:.0f} kg" if w == int(w) else f"{w:.1f} kg")
            if order.total_volume:
                parts.append(f"{order.total_volume:.2f} m³")
            if order.total_ldm:
                parts.append(f"{order.total_ldm:.2f} ldm")
            # Flags
            if any(line.is_dangerous_goods for line in order.goods_line_ids):
                parts.append("ADR")
            if any(not line.stackable for line in order.goods_line_ids):
                parts.append("Non-stackable")
            order.goods_description = " · ".join(parts)

    @api.depends(
        'goods_line_ids.package_id', 'goods_line_ids.goods_label', 'goods_line_ids.description',
        'goods_line_ids.quantity', 'goods_line_ids.package_type_id',
        'goods_line_ids.length', 'goods_line_ids.width', 'goods_line_ids.height',
        'goods_line_ids.gross_weight', 'goods_line_ids.volume_m3', 'goods_line_ids.ldm',
        'goods_line_ids.stackable', 'goods_line_ids.stacking_factor',
        'goods_line_ids.volume_compute_method', 'goods_line_ids.ldm_compute_method',
        'goods_line_ids.is_dangerous_goods', 'goods_line_ids.un_number', 'goods_line_ids.adr_class',
        'goods_line_ids.container_type_id', 'goods_line_ids.container_number',
        'goods_line_ids.temperature_min', 'goods_line_ids.temperature_max',
        'goods_line_ids.material_type_id',
    )
    def _compute_goods_full_summary(self):
        """Full multi-line summary of all goods lines for tracking on transport order."""
        for order in self:
            if not order.goods_line_ids:
                order.goods_full_summary = False
                continue
            lines = []
            for i, gl in enumerate(order.goods_line_ids, 1):
                parts = [f"#{i}"]
                if gl.quantity and gl.package_type_id:
                    parts.append(f"{gl.quantity} {gl.package_type_id.code}")
                elif gl.quantity:
                    parts.append(f"{gl.quantity} st")
                if gl.goods_label:
                    parts.append(gl.goods_label)
                if gl.description:
                    parts.append(gl.description)
                if gl.gross_weight:
                    parts.append(f"{gl.gross_weight:.1f} kg")
                if gl.volume_m3:
                    parts.append(f"{gl.volume_m3:.2f} m³")
                if gl.ldm:
                    parts.append(f"{gl.ldm:.2f} ldm")
                if gl.length or gl.width or gl.height:
                    parts.append(f"{gl.length or 0}x{gl.width or 0}x{gl.height or 0} m")
                if not gl.stackable:
                    parts.append("Non-stackable")
                if gl.is_dangerous_goods:
                    adr = "ADR"
                    if gl.un_number:
                        adr += f" UN{gl.un_number}"
                    if gl.adr_class:
                        adr += f" Cl.{gl.adr_class}"
                    parts.append(adr)
                if gl.container_type_id:
                    ct = gl.container_type_id.code
                    if gl.container_number:
                        ct += f" ({gl.container_number})"
                    parts.append(ct)
                if gl.temperature_min or gl.temperature_max:
                    parts.append(f"{gl.temperature_min or '?'}–{gl.temperature_max or '?'} °C")
                if gl.material_type_id:
                    parts.append(gl.material_type_id.name)
                if gl.package_id:
                    parts.append(f"ID:{gl.package_id}")
                lines.append(" · ".join(parts))
            order.goods_full_summary = "\n".join(lines)

    @api.depends(
        'transport_order_line_ids.product_id',
        'transport_order_line_ids.quantity',
        'transport_order_line_ids.price_per_unit',
        'transport_order_line_ids.price',
        'transport_order_line_ids.currency_id',
    )
    def _compute_order_lines_summary(self):
        """Full summary of all order lines for tracking on transport order."""
        for order in self:
            if not order.transport_order_line_ids:
                order.order_lines_summary = False
                continue
            lines = []
            for ol in order.transport_order_line_ids.filtered(lambda l: not l.parent_line_id):
                product = ol.product_id.display_name or '?'
                currency = ol.currency_id.name or ''
                line = f"{product}: {ol.quantity} x {ol.price_per_unit:.2f} = {ol.price:.2f} {currency}"
                lines.append(line)
                for child in ol.child_line_ids:
                    cp = child.product_id.display_name or '?'
                    cc = child.currency_id.name or ''
                    lines.append(f"  ↳ {cp}: {child.price:.2f} {cc}")
            order.order_lines_summary = "\n".join(lines)

    @api.depends(
        'road_assignment_ids.number',
        'road_assignment_ids.state',
        'road_assignment_ids.type',
        'road_assignment_ids.transport_carrier_id',
        'road_assignment_ids.carrier_reference',
        'road_assignment_ids.planned_pick_up_time',
        'road_assignment_ids.planned_delivery_time',
        'road_assignment_ids.sender_name',
        'road_assignment_ids.sender_city',
        'road_assignment_ids.receiver_name',
        'road_assignment_ids.receiver_city',
        'road_assignment_ids.driving_distance_km',
        'road_assignment_ids.transport_line_id',
        'road_assignment_ids.total_assignment_cost',
        'road_assignment_ids.assignment_currency_id',
        'road_assignment_ids.cost_state',
    )
    def _compute_assignments_summary(self):
        """Full summary of all assignments for tracking on transport order."""
        state_labels = dict(self.env['road.assignment']._fields['state'].selection)
        cost_state_labels = dict(self.env['road.assignment']._fields['cost_state'].selection)
        for order in self:
            if not order.road_assignment_ids:
                order.assignments_summary = False
                continue
            lines = []
            for ra in order.road_assignment_ids:
                parts = [ra.number or '?']
                state_label = state_labels.get(ra.state, ra.state or '?')
                parts.append(f"[{state_label}]")
                if ra.type:
                    parts.append(ra.type)
                if ra.transport_line_id:
                    parts.append(f"Line:{ra.transport_line_id.display_name}")
                if ra.transport_carrier_id:
                    parts.append(ra.transport_carrier_id.display_name)
                if ra.carrier_reference:
                    parts.append(f"Ref:{ra.carrier_reference}")
                route_parts = []
                if ra.sender_name or ra.sender_city:
                    route_parts.append(ra.sender_city or ra.sender_name or '')
                if ra.receiver_name or ra.receiver_city:
                    route_parts.append(ra.receiver_city or ra.receiver_name or '')
                if route_parts:
                    parts.append(" → ".join(route_parts))
                if ra.driving_distance_km:
                    parts.append(f"{ra.driving_distance_km:.0f} km")
                time_parts = []
                if ra.planned_pick_up_time:
                    time_parts.append(f"PU:{ra.planned_pick_up_time.strftime('%Y-%m-%d %H:%M')}")
                if ra.planned_delivery_time:
                    time_parts.append(f"DEL:{ra.planned_delivery_time.strftime('%Y-%m-%d %H:%M')}")
                if time_parts:
                    parts.append(" ".join(time_parts))
                # Cost summary
                cost_currency = ra.assignment_currency_id.name or ''
                cost_label = cost_state_labels.get(ra.cost_state, ra.cost_state or '')
                if ra.total_assignment_cost:
                    parts.append(f"Cost:{ra.total_assignment_cost:.2f} {cost_currency}".strip())
                if cost_label:
                    parts.append(f"({cost_label})")
                lines.append(" · ".join(parts))
            order.assignments_summary = "\n".join(lines)

    @api.depends(
        'event_ids',
        'event_ids.event_time',
        'event_ids.event_type_id',
        'event_ids.place',
        'event_ids.country_id',
        'event_ids.transport_assignment_id',
        'event_ids.is_deviation',
        'event_ids.root_cause',
        'event_ids.severity',
        'event_ids.event_source',
        'event_ids.user',
        'event_ids.note',
        'road_assignment_ids.event_ids',
        'road_assignment_ids.event_ids.event_time',
        'road_assignment_ids.event_ids.event_type_id',
        'road_assignment_ids.event_ids.place',
        'road_assignment_ids.event_ids.is_deviation',
        'road_assignment_ids.event_ids.root_cause',
        'road_assignment_ids.event_ids.severity',
    )
    def _compute_events_summary(self):
        """Full chronological summary of all assignment events for tracking on the transport order.

        Aggregates events from:
          * order.event_ids (events linked directly to the order), and
          * road_assignment_ids.event_ids (events linked to any assignment on the order).
        Duplicates are filtered; the list is chronological (oldest → newest).
        """
        for order in self:
            # Collect unique events from both sources
            event_set = order.event_ids | order.road_assignment_ids.mapped('event_ids')
            if not event_set:
                order.events_summary = False
                continue
            # Sort chronologically by event_time (newest first, like a log).
            # Events with missing event_time are placed last.
            events_sorted = event_set.sorted(
                key=lambda e: (
                    e.event_time is False,  # False sorts before True → rows with time first
                    -(e.event_time.timestamp() if e.event_time else 0),
                )
            )
            lines = []
            for ev in events_sorted:
                parts = []
                if ev.event_time:
                    parts.append(ev.event_time.strftime('%Y-%m-%d %H:%M'))
                else:
                    parts.append('?')
                # Event type (name + code if available)
                if ev.event_type_id:
                    et_label = ev.event_type_id.name or ''
                    if getattr(ev.event_type_id, 'code', False):
                        et_label = f"{ev.event_type_id.code} - {et_label}".strip(' -')
                    parts.append(f"[{et_label}]")
                # Assignment link
                if ev.transport_assignment_id:
                    parts.append(f"RA:{ev.transport_assignment_id.number or ev.transport_assignment_id.id}")
                # Place
                place_parts = []
                if ev.place:
                    place_parts.append(ev.place)
                if ev.country_id:
                    place_parts.append(ev.country_id.code or ev.country_id.name or '')
                if place_parts:
                    parts.append(", ".join(p for p in place_parts if p))
                # Deviation info
                if ev.is_deviation:
                    dev_parts = ["DEVIATION"]
                    if ev.severity:
                        dev_parts.append(ev.severity)
                    if ev.root_cause:
                        dev_parts.append(ev.root_cause)
                    parts.append("/".join(dev_parts))
                # Source & user
                if ev.event_source:
                    parts.append(f"src:{ev.event_source}")
                if ev.user:
                    parts.append(f"by:{ev.user}")
                # Note (truncated)
                if ev.note:
                    note = ev.note.strip().replace('\n', ' ')
                    if len(note) > 80:
                        note = note[:77] + '...'
                    parts.append(f"\"{note}\"")
                lines.append(" · ".join(parts))
            order.events_summary = "\n".join(lines)

    @api.depends('company_id.currency_id', 'pick_up_date',
                 'transport_order_line_ids.price', 'transport_order_line_ids.currency_id',
                 'road_assignment_ids.road_assignment_line_ids.price', 'road_assignment_ids.road_assignment_line_ids.currency_id')
    def _compute_order_totals(self):
        """
        Calculates the total price in both the system's commercial currency
        and the order's company currency.
        """
        # Get the system currency once
        config_param = self.env['ir.config_parameter'].sudo().get_param('transport_management.commercial_currency_id')
        system_currency = None
        if config_param:
            try:
                system_currency = self.env['res.currency'].browse(int(config_param))
            except ValueError:
                system_currency = None
        
        # Fallback if not configured or param is invalid
        if not system_currency:
            system_currency = self.env.company.currency_id or self.env.ref('base.USD', raise_if_not_found=False)

        for order in self:
            order.system_currency_id = system_currency.id
            company_currency = order.company_id.currency_id
            
            total_system_val = 0.0
            total_company_val = 0.0
            
            # Use today's date for conversion if no order date is set
            conversion_date = order.pick_up_date or fields.Date.context_today(order)

            # 1. Sum Transport Order Lines
            for line in order.transport_order_line_ids:
                if line.currency_id and line.price and company_currency:
                    # Convert to System Currency
                    total_system_val += line.currency_id._convert(
                        line.price,
                        system_currency,
                        order.company_id,
                        conversion_date
                    )
                    # Convert to Company Currency
                    total_company_val += line.currency_id._convert(
                        line.price,
                        company_currency,
                        order.company_id,
                        conversion_date
                    )
            
            # 2. Sum Road Assignment Lines
            for assignment in order.road_assignment_ids:
                for cost_line in assignment.road_assignment_line_ids:
                    if cost_line.currency_id and cost_line.price and company_currency:
                        # Convert to System Currency
                        total_system_val += cost_line.currency_id._convert(
                            cost_line.price,
                            system_currency,
                            order.company_id,
                            conversion_date
                        )
                        # Convert to Company Currency
                        total_company_val += cost_line.currency_id._convert(
                            cost_line.price,
                            company_currency,
                            order.company_id,
                            conversion_date
                        )
            
            order.total_system_currency = total_system_val
            order.total_product_currency = total_company_val

    @api.constrains('delivery_time_from', 'delivery_time_to')
    def _check_delivery_time(self):
        for record in self:
            if record.delivery_time_from:
                if not record.delivery_time_to:
                    raise ValidationError("Delivery time to is required when delivery time from is set.")
                if record.delivery_time_to < record.delivery_time_from:
                    raise ValidationError("Delivery time to cannot be earlier than delivery time from.")
            if record.delivery_time_to:
                if not record.delivery_time_from:
                    raise ValidationError("Delivery time from is required when delivery time to is set.")

    @api.constrains('pick_up_time_from', 'pick_up_time_to')
    def _check_pick_up_time(self):
        for record in self:
            if record.pick_up_time_from:
                if not record.pick_up_time_to:
                    raise ValidationError("Pick up time to is required when pick up time from is set.")
                if record.pick_up_time_to < record.pick_up_time_from:
                    raise ValidationError("Pick up time to cannot be earlier than pick up time from.")
            if record.pick_up_time_to:
                if not record.pick_up_time_from:
                    raise ValidationError("Pick up time from is required when pick up time to is set.")

    @api.constrains('start_time', 'end_time')
    def _check_times(self):
        for record in self:

            if record.start_time and record.end_time:
                if record.start_time > record.end_time:
                    raise ValidationError("The specified pick up and delivery times are invalid. Delivery cannot be made before pick up.")

    @api.depends('pick_up_date', 'pick_up_time_from')
    def _compute_start_time(self):
        for rec in self:
            rec.start_time = None
            start_time = None

            if rec.pick_up_date:
                start_time = datetime.combine(rec.pick_up_date, time.min)
            if rec.pick_up_time_from:
                start_time = rec.pick_up_time_from

            rec.start_time = start_time or fields.Datetime.now()

    @api.depends('delivery_date', 'delivery_time_to')
    def _compute_end_time(self):
        for rec in self:
            rec.end_time = None
            end_time = None

            if rec.delivery_date:
                end_time = datetime.combine(rec.delivery_date, time.min)
            if rec.delivery_time_to:
                end_time = rec.delivery_time_to

            rec.end_time = end_time or fields.Datetime.now()

    @api.depends('sender_latitude', 'sender_longitude')
    def _compute_sender_geo_coordinates(self):
        for rec in self:
            rec.sender_geo_coordinates = ''
            geo_coordinates = ''

            if rec.sender_latitude and rec.sender_longitude:
                geo_coordinates = f"{rec.sender_latitude}" + ',' + f"{rec.sender_longitude}"

            rec.sender_geo_coordinates = geo_coordinates

    @api.depends('receiver_latitude', 'receiver_longitude')
    def _compute_receiver_geo_coordinates(self):
        for rec in self:
            rec.receiver_geo_coordinates = ''
            geo_coordinates = ''

            if rec.receiver_latitude and rec.receiver_longitude:
                geo_coordinates = f"{rec.receiver_latitude}" + ',' + f"{rec.receiver_longitude}"

            rec.receiver_geo_coordinates = geo_coordinates

    @api.model
    def _compute_sender_address(self):

        for rec in self:

            rec.sender_address = ''
            name = rec.sender_name or ''
            if rec.sender_street:
                if name:
                    name += ', ' + rec.sender_street
                else:
                    name += rec.sender_street
            if rec.sender_city:
                if name:
                    name += ', ' + rec.sender_city
                else:
                    name += rec.sender_city
            if rec.sender_country_id:
                if name:
                    name += ', ' + rec.sender_country_id.code
                else:
                    name += rec.sender_country_id.code

            rec.sender_address = name

    @api.model
    def _compute_receiver_address(self):

        for rec in self:
            rec.receiver_address = ''
            name = rec.receiver_name or ''

            if rec.receiver_street:
                if name:
                    name += ', ' + rec.receiver_street
                else:
                    name += rec.receiver_street
            if rec.receiver_city:
                if name:
                    name += ', ' + rec.receiver_city
                else:
                    name += rec.receiver_city
            if rec.receiver_country_id:
                if name:
                    name += ', ' + rec.receiver_country_id.code
                else:
                    name += rec.receiver_country_id.code

            rec.receiver_address = name


    def generate_waybill_number(self):
        for rec in self:

            if not rec.company_id:
                raise ValidationError("Please select a company.")

            # Call method in waybill.number.series model
            new_waybill_number = self.env['waybill.number'].get_new_waybill_number(rec.company_id.id)

            # Assign generated waybill number
            rec.waybill_number = new_waybill_number

    def _geocode_address(self, direction):
        self.ensure_one()
        geo_obj = self.env['base.geocoder']
        street = self[f'{direction}_street']
        zip_code = self[f'{direction}_zip']
        city = self[f'{direction}_city']
        state = self[f'{direction}_state_id'].with_context(lang='en_US').name
        country = self[f'{direction}_country_id'].with_context(lang='en_US').name
        address_id = self[f'{direction}_address_id']
        label = _('Sender') if direction == 'sender' else _('Receiver')

        search = geo_obj.geo_query_address(street=street, zip=zip_code, city=city, state=state, country=country)
        result = geo_obj.geo_find(search, force_country=country)
        if result is None:
            search = geo_obj.geo_query_address(city=city, state=state, country=country)
            result = geo_obj.geo_find(search, force_country=country)

        if result:
            self.write({
                f'{direction}_latitude': result[0],
                f'{direction}_longitude': result[1],
            })
            self.fetch_distance()

            if address_id:
                old_lat = address_id.partner_latitude
                old_lng = address_id.partner_longitude
                coords_missing = not old_lat and not old_lng
                coords_differ = coords_missing or (
                    round(old_lat, 5) != round(result[0], 5)
                    or round(old_lng, 5) != round(result[1], 5)
                )
                if coords_differ:
                    wizard = self.env['tms.geocode.save.wizard'].create({
                        'address_id': address_id.id,
                        'old_latitude': old_lat or 0.0,
                        'old_longitude': old_lng or 0.0,
                        'new_latitude': result[0],
                        'new_longitude': result[1],
                    })
                    return {
                        'name': _('Save Coordinates?'),
                        'type': 'ir.actions.act_window',
                        'res_model': 'tms.geocode.save.wizard',
                        'res_id': wizard.id,
                        'view_mode': 'form',
                        'target': 'new',
                    }

            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Success'),
                    'message': _('%s address found at %s, %s', label, str(result[0]), str(result[1])),
                    'type': 'success',
                    'sticky': False,
                    'next': {'type': 'ir.actions.client', 'tag': 'soft_reload'},
                },
            }
        else:
            self.write({
                f'{direction}_latitude': None,
                f'{direction}_longitude': None,
                'driving_distance_km': 0,
                'driving_distance_miles': 0,
            })
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Geocoding Failed'),
                    'message': _('Could not find coordinates for the %s address. Please check the address details.', label.lower()),
                    'type': 'danger',
                    'sticky': False,
                    'next': {'type': 'ir.actions.client', 'tag': 'soft_reload'},
                },
            }

    def geo_code_sender_address(self):
        return self._geocode_address('sender')

    def geo_code_receiver_address(self):
        return self._geocode_address('receiver')

    def fetch_distance(self):
        API_TOKEN = _get_routing_api_token()
        API_URL = 'https://routing.editsolutions.com/distances'

        # Batch all records that need distance calculation
        recs_to_fetch = []
        for rec in self:
            if rec.manual_distance:
                continue
            s_lat = rec.sender_latitude
            s_lon = rec.sender_longitude
            r_lat = rec.receiver_latitude
            r_lon = rec.receiver_longitude
            if s_lat and s_lon and r_lat and r_lon:
                recs_to_fetch.append((rec, s_lat, s_lon, r_lat, r_lon))
            else:
                rec.driving_distance_km = 0
                rec.driving_distance_miles = 0

        if not recs_to_fetch:
            return

        pairs = [
            {'from_lat': s_lat, 'from_lon': s_lon, 'to_lat': r_lat, 'to_lon': r_lon}
            for _rec, s_lat, s_lon, r_lat, r_lon in recs_to_fetch
        ]

        distances = None

        # Primary: use cached routing API
        if API_TOKEN:
            headers = {'Content-Type': 'application/json', 'Authorization': API_TOKEN}
            try:
                payload = json.dumps({"pairs": pairs})
                response = requests.post(API_URL, headers=headers, data=payload, timeout=30)
                response.raise_for_status()
                response_data = response.json()
                if response_data.get('status') == 'Success' and response_data.get('data'):
                    distances = response_data['data'].get('distances', [])
            except Exception as e:
                _logger.warning("Routing distances API unavailable (%s), falling back to OSRM", str(e))

        # Fallback to OSRM if the routing service failed or is not configured
        if distances is None:
            distances = []
            for _rec, s_lat, s_lon, r_lat, r_lon in recs_to_fetch:
                try:
                    url = (f"https://router.project-osrm.org/route/v1/driving/"
                           f"{s_lon},{s_lat};{r_lon},{r_lat}")
                    resp = requests.get(url, timeout=10)
                    distances.append(resp.json()['routes'][0]['legs'][0]['distance'])
                except Exception:
                    distances.append(None)

        for i, (rec, *_) in enumerate(recs_to_fetch):
            dist = distances[i] if i < len(distances) else None
            if dist is not None:
                rec.driving_distance_km = dist / 1000
                rec.driving_distance_miles = dist * 0.621371 / 1000
            else:
                rec.driving_distance_km = 0
                rec.driving_distance_miles = 0

    def _check_can_regenerate_assignments(self):
        """Ensure no assignments are planned/started/done before regeneration.

        Draft and confirmed assignments are safe to regenerate — they have
        not yet been dispatched to a vehicle.  Only 'planned' and later
        states block regeneration.
        """
        allowed_states = ('draft', 'confirmed', 'cancelled')
        for rec in self:
            blocking = rec.road_assignment_ids.filtered(
                lambda a: a.state not in allowed_states
            )
            if not blocking:
                continue

            # Split into internally planned vs dispatched/active
            internally_planned = blocking.filtered(
                lambda a: a.state == 'planned' and a.transport_load_id
            )
            dispatched_or_active = blocking - internally_planned

            parts = []
            if internally_planned:
                parts.append(_(
                    "%(numbers)s: unplan from transport load(s) first.",
                    numbers=', '.join(internally_planned.mapped('number'))
                ))
            if dispatched_or_active:
                parts.append(_(
                    "%(numbers)s: cancel before regenerating.",
                    numbers=', '.join(dispatched_or_active.mapped('number'))
                ))

            raise UserError(_(
                "Cannot regenerate shipping legs for order %(order)s.\n\n%(details)s",
                order=rec.number,
                details='\n'.join(parts),
            ))

    def _find_matching_planning_criteria(self):
        """Find the first matching assignment planning criteria row.

        Iterates through the order type's criteria rows and matches
        on all dimensions that are enabled via the apc_* toggles.
        Same pattern as price list row matching in purchase_transport_pricing.py.
        """
        self.ensure_one()
        order_type = self.transport_order_type_id
        if not order_type:
            return None

        for row in order_type.assignment_planning_criteria_ids:
            if order_type.apc_billable_weight_interval:
                if not (row.billable_weight_from <= self.total_billable_weight < row.billable_weight_to):
                    continue

            if order_type.apc_volume_interval:
                if not (row.volume_from <= self.total_volume < row.volume_to):
                    continue

            if order_type.apc_ldm_interval:
                if not (row.ldm_from <= self.total_ldm < row.ldm_to):
                    continue

            if order_type.apc_gross_weight_interval:
                if not (row.gross_weight_from <= self.total_gross_weight < row.gross_weight_to):
                    continue

            if order_type.apc_distance_interval:
                if not (row.driving_distance_km >= row.distance_from and (row.distance_to == 0 or self.driving_distance_km < row.distance_to)):
                    continue

            if order_type.apc_sender_zip_prefix:
                if not self.sender_zip or not self.sender_zip.startswith(row.sender_zip_prefix or ''):
                    continue

            if order_type.apc_sender_country:
                if row.sender_country_id != self.sender_country_id:
                    continue

            if order_type.apc_receiver_zip_prefix:
                if not self.receiver_zip or not self.receiver_zip.startswith(row.receiver_zip_prefix or ''):
                    continue

            if order_type.apc_receiver_country:
                if row.receiver_country_id != self.receiver_country_id:
                    continue

            if order_type.apc_customer:
                if row.customer_id != self.customer_id:
                    continue

            if order_type.apc_company:
                if row.company_id != self.company_id:
                    continue

            if order_type.apc_sender_price_zone:
                if row.sender_price_zone_id != self.sender_price_zone_id:
                    continue

            if order_type.apc_receiver_price_zone:
                if row.receiver_price_zone_id != self.receiver_price_zone_id:
                    continue

            if order_type.apc_freight_service:
                if row.freight_service_id != self.freight_service_id:
                    continue

            if order_type.apc_adr:
                if row.adr != self.has_dangerous_goods:
                    continue

            if order_type.apc_bulky_goods:
                if row.bulky_goods != self.bulky_goods:
                    continue

            if order_type.apc_requirements:
                # All row requirements must be present on the order
                if not (set(row.requirement_ids.ids) <= set(self.requirement_ids.ids)):
                    continue

            return row  # First matching row

        return None

    def generate_assignments(self):
        for rec in self:
            if not rec.company_id:
                raise ValidationError("Please select a company.")

            if not rec.transport_order_type_id:
                raise ValidationError("Please select a transport order type.")

            # Reset stale flag — we are (re)generating assignments now
            if rec.shipping_legs_stale:
                rec.shipping_legs_stale = False

            assignment_planning_criteria = rec._find_matching_planning_criteria()

            if assignment_planning_criteria:
                if assignment_planning_criteria.planning_type:
                    if assignment_planning_criteria.planning_type == "direct":

                        if not rec.sender_zip or not rec.sender_country_id:
                            raise ValidationError("Sender zip code and country is required")

                        # Archive draft/confirmed assignments; keep cancelled ones
                        if rec.road_assignment_ids:
                            rec._check_can_regenerate_assignments()
                            to_remove = rec.road_assignment_ids.filtered(
                                lambda a: a.state in ('draft', 'confirmed') 
                            )
                            to_remove.write({'active': False, 'state': 'cancelled'})

                        district_from = self.env['transport.district'].get_matching_district(rec.company_id.id, rec.sender_zip,rec.sender_country_id.id)

                        if not district_from:
                            raise ValidationError(_(
                                "No transport district matches sender zip '%(zip)s' in "
                                "%(country)s. Please configure a district with a matching "
                                "zip prefix before generating assignments."
                            ) % {
                                'zip': rec.sender_zip,
                                'country': rec.sender_country_id.name or '',
                            })

                        note = ""

                        if rec.pick_up_details:
                            note += f"{rec.pick_up_details}"

                        if rec.delivery_details:
                            if note:
                                note += f"\n{rec.delivery_details}"
                            else:
                                note += f"{rec.delivery_details}"

                        assignments = [{
                            'transport_order_id': rec.id,
                            'transport_carrier_id': district_from.transport_carrier_id.id,
                            'transport_type_id': self.env['transport.type'].search([('code', '=', 'DI')], limit=1).id,
                            'sender_address_id': rec.sender_address_id.id,
                            'sender_name': rec.sender_name,
                            'sender_street': rec.sender_street,
                            'sender_street_2': rec.sender_street_2,
                            'sender_zip': rec.sender_zip,
                            'sender_city': rec.sender_city,
                            'sender_state_id': rec.sender_state_id.id,
                            'sender_country_id': rec.sender_country_id.id,
                            'sender_longitude': rec.sender_longitude,
                            'sender_latitude': rec.sender_latitude,
                            'sender_phone': rec.sender_phone,
                            'sender_mobile': rec.sender_mobile,
                            'sender_email': rec.sender_email,
                            'receiver_address_id': rec.receiver_address_id.id,
                            'receiver_name': rec.receiver_name,
                            'receiver_street': rec.receiver_street,
                            'receiver_street_2': rec.receiver_street_2,
                            'receiver_zip': rec.receiver_zip,
                            'receiver_city': rec.receiver_city,
                            'receiver_state_id': rec.receiver_state_id.id,
                            'receiver_country_id': rec.receiver_country_id.id,
                            'receiver_longitude': rec.receiver_longitude,
                            'receiver_latitude': rec.receiver_latitude,
                            'receiver_phone': rec.receiver_phone,
                            'receiver_mobile': rec.receiver_mobile,
                            'receiver_email': rec.receiver_email,
                            'note': note,
                            'pick_up_details': rec.pick_up_details,
                            'delivery_details': rec.delivery_details,
                            'state': 'draft',
                            # DI (Direct) gets both pickup and delivery evidence requirements
                            'require_pickup_signature': rec.require_pickup_signature,
                            'require_pickup_photo': rec.require_pickup_photo,
                            'require_pickup_assignment_scanning': rec.require_pickup_assignment_scanning,
                            'require_pickup_goods_scanning': rec.require_pickup_goods_scanning,
                            'require_delivery_signature': rec.require_delivery_signature,
                            'require_delivery_photo': rec.require_delivery_photo,
                            'require_delivery_assignment_scanning': rec.require_delivery_assignment_scanning,
                            'require_delivery_goods_scanning': rec.require_delivery_goods_scanning,
                            'requirement_ids': [Command.set(rec.requirement_ids.ids)],
                            # DI (Direct) gets both pickup and delivery time windows
                            'pick_up_time_window': rec.pick_up_time_window,
                            'pick_up_time_from': rec.pick_up_time_from,
                            'pick_up_time_to': rec.pick_up_time_to,
                            'delivery_time_window': rec.delivery_time_window,
                            'delivery_time_from': rec.delivery_time_from,
                            'delivery_time_to': rec.delivery_time_to,
                            'estimated_pickup_duration': rec.estimated_pickup_duration,
                            'estimated_delivery_duration': rec.estimated_delivery_duration,
                        }]

                        # Calculate times
                        for assignment in assignments:
                            assignment['planned_pick_up_time'] = rec.start_time
                            assignment['planned_delivery_time'] = rec.start_time + timedelta(hours=8)

                        created = self.env['road.assignment']
                        for assignment in assignments:
                            created |= self.env['road.assignment'].with_company(rec.company_id).with_context(skip_auto_cost_lines=True).create(assignment)
                        created.fetch_distance()
                        created.generate_road_assignment_lines()

                    elif assignment_planning_criteria.planning_type == "shipping_legs":

                        if not rec.sender_zip or not rec.sender_country_id:
                            raise ValidationError("Sender zip code and country is required")

                        if not rec.receiver_zip or not rec.receiver_country_id:
                            raise ValidationError("Receiver zip code and country is required")

                        district_from = self.env['transport.district'].get_matching_district(rec.company_id.id, rec.sender_zip, rec.sender_country_id.id)
                        district_to = self.env['transport.district'].get_matching_district(rec.company_id.id, rec.receiver_zip, rec.receiver_country_id.id)

                        if district_from and district_to:

                            # Archive draft/confirmed assignments; keep cancelled ones
                            if rec.road_assignment_ids:
                                rec._check_can_regenerate_assignments()
                                to_remove = rec.road_assignment_ids.filtered(
                                    lambda a: a.state in ('draft', 'confirmed') 
                                )
                                to_remove.write({'active': False, 'state': 'cancelled'})

                            # Set addresses
                            if(rec.sender_address_id):
                                pick_up_assignment_address_from_id = rec.sender_address_id.id
                            else:
                                pick_up_assignment_address_from_id = None

                            if district_from.transport_hub_id and district_from.transport_hub_id.partner_id:
                                pick_up_assignment_address_to_id = district_from.transport_hub_id.partner_id.id
                                pick_up_assignment_to_name = district_from.transport_hub_id.name
                                pick_up_assignment_to_street = district_from.transport_hub_id.street
                                pick_up_assignment_to_street_2 = district_from.transport_hub_id.street_2
                                pick_up_assignment_to_zip = district_from.transport_hub_id.zip
                                pick_up_assignment_to_city = district_from.transport_hub_id.city
                                pick_up_assignment_to_state_id = district_from.transport_hub_id.state_id
                                pick_up_assignment_to_country_id = district_from.transport_hub_id.country_id
                                pick_up_assignment_to_longitude = district_from.transport_hub_id.longitude
                                pick_up_assignment_to_latitude = district_from.transport_hub_id.latitude
                                pick_up_assignment_to_phone = ''
                                pick_up_assignment_to_mobile = ''
                                pick_up_assignment_to_email = ''
                            else:
                                pick_up_assignment_address_to_id = None

                            if district_to.transport_hub_id and district_to.transport_hub_id.partner_id:
                                delivery_assignment_address_from_id = district_to.transport_hub_id.partner_id.id
                                delivery_assignment_from_name = district_to.transport_hub_id.name
                                delivery_assignment_from_street = district_to.transport_hub_id.street
                                delivery_assignment_from_street_2 = district_to.transport_hub_id.street_2
                                delivery_assignment_from_zip = district_to.transport_hub_id.zip
                                delivery_assignment_from_city = district_to.transport_hub_id.city
                                delivery_assignment_from_state_id = district_to.transport_hub_id.state_id
                                delivery_assignment_from_country_id = district_to.transport_hub_id.country_id
                                delivery_assignment_from_longitude = district_to.transport_hub_id.longitude
                                delivery_assignment_from_latitude = district_to.transport_hub_id.latitude
                                delivery_assignment_from_phone = ''
                                delivery_assignment_from_mobile = ''
                                delivery_assignment_from_email = ''
                            else:
                                delivery_assignment_address_from_id = None
                                delivery_assignment_from_name = ''
                                delivery_assignment_from_street = ''
                                delivery_assignment_from_street_2 = ''
                                delivery_assignment_from_zip = ''
                                delivery_assignment_from_city = ''
                                delivery_assignment_from_state_id = None
                                delivery_assignment_from_country_id = None
                                delivery_assignment_from_longitude = None
                                delivery_assignment_from_latitude = None
                                delivery_assignment_from_phone = ''
                                delivery_assignment_from_mobile = ''
                                delivery_assignment_from_email = ''

                            if(rec.receiver_address_id):
                                delivery_assignment_address_to_id = rec.receiver_address_id.id
                            else:
                                delivery_assignment_address_to_id = None

                            # Create pick up and distribution
                            assignments = [{
                                #'number': self.env['ir.sequence'].next_by_code('road.assignment'),
                                'transport_order_id': rec.id,
                                'transport_carrier_id': district_from.transport_carrier_id.id,
                                'transport_type_id': self.env['transport.type'].search([('code', '=', 'PU')], limit=1).id,
                                'sender_address_id': pick_up_assignment_address_from_id,
                                'sender_name': rec.sender_name,
                                'sender_street': rec.sender_street,
                                'sender_street_2': rec.sender_street_2,
                                'sender_zip': rec.sender_zip,
                                'sender_city': rec.sender_city,
                                'sender_state_id': rec.sender_state_id.id,
                                'sender_country_id': rec.sender_country_id.id,
                                'sender_longitude': rec.sender_longitude,
                                'sender_latitude': rec.sender_latitude,
                                'sender_phone': rec.sender_phone,
                                'sender_mobile': rec.sender_mobile,
                                'sender_email': rec.sender_email,
                                'receiver_address_id': pick_up_assignment_address_to_id,
                                'receiver_name': pick_up_assignment_to_name,
                                'receiver_street': pick_up_assignment_to_street,
                                'receiver_street_2': pick_up_assignment_to_street_2,
                                'receiver_zip': pick_up_assignment_to_zip,
                                'receiver_city': pick_up_assignment_to_city,
                                'receiver_state_id': pick_up_assignment_to_state_id.id,
                                'receiver_country_id': pick_up_assignment_to_country_id.id,
                                'receiver_longitude': pick_up_assignment_to_longitude,
                                'receiver_latitude': pick_up_assignment_to_latitude,
                                'receiver_phone': pick_up_assignment_to_phone,
                                'receiver_mobile': pick_up_assignment_to_mobile,
                                'receiver_email': pick_up_assignment_to_email,
                                'note': rec.pick_up_details,
                                'pick_up_details': rec.pick_up_details,
                                'state': 'draft',
                                # PU gets pickup evidence requirements only
                                'require_pickup_signature': rec.require_pickup_signature,
                                'require_pickup_photo': rec.require_pickup_photo,
                                'require_pickup_assignment_scanning': rec.require_pickup_assignment_scanning,
                                'require_pickup_goods_scanning': rec.require_pickup_goods_scanning,
                                'requirement_ids': [Command.set(rec.requirement_ids.ids)],
                                # PU gets pickup time windows only
                                'pick_up_time_window': rec.pick_up_time_window,
                                'pick_up_time_from': rec.pick_up_time_from,
                                'pick_up_time_to': rec.pick_up_time_to,
                                'estimated_pickup_duration': rec.estimated_pickup_duration,
                                'estimated_delivery_duration': 0,
                            }]

                            assignments.append({
                                #'number': self.env['ir.sequence'].next_by_code('road.assignment'),
                                'transport_order_id': rec.id,
                                'transport_type_id': self.env['transport.type'].search([('code', '=', 'DE')], limit=1).id,
                                'transport_carrier_id': district_to.transport_carrier_id.id,
                                'sender_address_id': delivery_assignment_address_from_id,
                                'sender_name': delivery_assignment_from_name,
                                'sender_street': delivery_assignment_from_street,
                                'sender_street_2': delivery_assignment_from_street_2,
                                'sender_zip': delivery_assignment_from_zip,
                                'sender_city': delivery_assignment_from_city,
                                'sender_state_id': delivery_assignment_from_state_id.id,
                                'sender_country_id': delivery_assignment_from_country_id.id,
                                'sender_longitude': delivery_assignment_from_longitude,
                                'sender_latitude': delivery_assignment_from_latitude,
                                'sender_phone': delivery_assignment_from_phone,
                                'sender_mobile': delivery_assignment_from_mobile,
                                'sender_email': delivery_assignment_from_email,
                                'receiver_address_id': delivery_assignment_address_to_id,
                                'receiver_name': rec.receiver_name,
                                'receiver_street': rec.receiver_street,
                                'receiver_street_2': rec.receiver_street_2,
                                'receiver_zip': rec.receiver_zip,
                                'receiver_city': rec.receiver_city,
                                'receiver_state_id': rec.receiver_state_id.id,
                                'receiver_country_id': rec.receiver_country_id.id,
                                'receiver_longitude': rec.receiver_longitude,
                                'receiver_latitude': rec.receiver_latitude,
                                'receiver_phone': rec.receiver_phone,
                                'receiver_mobile': rec.receiver_mobile,
                                'receiver_email': rec.receiver_email,
                                'note': rec.delivery_details,
                                'delivery_details': rec.delivery_details,
                                'state': 'draft',
                                # DE gets delivery evidence requirements only
                                'require_delivery_signature': rec.require_delivery_signature,
                                'require_delivery_photo': rec.require_delivery_photo,
                                'require_delivery_assignment_scanning': rec.require_delivery_assignment_scanning,
                                'require_delivery_goods_scanning': rec.require_delivery_goods_scanning,
                                'requirement_ids': [Command.set(rec.requirement_ids.ids)],
                                # DE gets delivery time windows only
                                'delivery_time_window': rec.delivery_time_window,
                                'delivery_time_from': rec.delivery_time_from,
                                'delivery_time_to': rec.delivery_time_to,
                                'estimated_pickup_duration': 0,
                                'estimated_delivery_duration': rec.estimated_delivery_duration,
                            })

                            shipping_legs = self.env['shipping.leg.template'].get_shipping_legs(rec.company_id.id, district_from.transport_hub_id.id, district_to.transport_hub_id.id)

                            for shipping_leg in shipping_legs:

                                if shipping_leg.transport_line_id:

                                    transport_line = shipping_leg.transport_line_id
                                    transport_hub_from = transport_line.transport_hub_from_id
                                    transport_hub_to = transport_line.transport_hub_to_id

                                    if transport_hub_from:
                                        sender_address_id = transport_hub_from.partner_id.id
                                        sender_name = transport_hub_from.name
                                        sender_street = transport_hub_from.street
                                        sender_street_2 = transport_hub_from.street_2
                                        sender_zip = transport_hub_from.zip
                                        sender_city = transport_hub_from.city
                                        sender_state_id = transport_hub_from.state_id.id
                                        sender_country_id = transport_hub_from.country_id.id
                                        sender_latitude = transport_hub_from.latitude
                                        sender_longitude = transport_hub_from.longitude
                                        sender_phone = ''
                                        sender_mobile = ''
                                        sender_email = ''
                                    else:
                                        sender_address_id = None
                                        sender_name = ''
                                        sender_street = ''
                                        sender_street_2 = ''
                                        sender_zip = ''
                                        sender_city = ''
                                        sender_state_id = None
                                        sender_country_id = None
                                        sender_latitude = None
                                        sender_longitude = None
                                        sender_phone = ''
                                        sender_mobile = ''
                                        sender_email = ''

                                    if transport_hub_to:
                                        receiver_address_id = transport_hub_to.partner_id.id
                                        receiver_name = transport_hub_to.name
                                        receiver_street = transport_hub_to.street
                                        receiver_street_2 = transport_hub_to.street_2
                                        receiver_zip = transport_hub_to.zip
                                        receiver_city = transport_hub_to.city
                                        receiver_state_id = transport_hub_to.state_id.id
                                        receiver_country_id = transport_hub_to.country_id.id
                                        receiver_latitude = transport_hub_to.latitude
                                        receiver_longitude = transport_hub_to.longitude
                                        receiver_phone = ''
                                        receiver_mobile = ''
                                        receiver_email = ''
                                    else:
                                        receiver_address_id = None
                                        receiver_name = ''
                                        receiver_street = ''
                                        receiver_street_2 = ''
                                        receiver_zip = ''
                                        receiver_city = ''
                                        receiver_state_id = None
                                        receiver_country_id = None
                                        receiver_latitude = None
                                        receiver_longitude = None
                                        receiver_phone = ''
                                        receiver_mobile = ''
                                        receiver_email = ''

                                    assignments.insert(len(assignments)-1,{

                                        'transport_order_id': rec.id,
                                        'transport_type_id': self.env['transport.type'].search([('code', '=', 'LI')], limit=1).id,
                                        'transport_line_id': transport_line.id,
                                        'transport_carrier_id': transport_line.transport_carrier_id.id,
                                        'sender_address_id': sender_address_id,
                                        'sender_name': sender_name,
                                        'sender_street': sender_street,
                                        'sender_street_2': sender_street_2,
                                        'sender_zip': sender_zip,
                                        'sender_city': sender_city,
                                        'sender_state_id': sender_state_id,
                                        'sender_country_id': sender_country_id,
                                        'sender_latitude': sender_latitude,
                                        'sender_longitude': sender_longitude,
                                        'sender_phone': sender_phone,
                                        'sender_mobile': sender_mobile,
                                        'sender_email': sender_email,
                                        'receiver_address_id': receiver_address_id,
                                        'receiver_name': receiver_name,
                                        'receiver_street': receiver_street,
                                        'receiver_street_2': receiver_street_2,
                                        'receiver_zip': receiver_zip,
                                        'receiver_city': receiver_city,
                                        'receiver_state_id': receiver_state_id,
                                        'receiver_country_id': receiver_country_id,
                                        'receiver_latitude': receiver_latitude,
                                        'receiver_longitude': receiver_longitude,
                                        'receiver_phone': receiver_phone,
                                        'receiver_mobile': receiver_mobile,
                                        'receiver_email': receiver_email,
                                        'note': '',
                                        'state': 'draft',
                                        'requirement_ids': [Command.set(rec.requirement_ids.ids)],
                                        'estimated_pickup_duration': 0,
                                        'estimated_delivery_duration': 0,
                                    })

                            # Calculate times
                            current_time = rec.start_time

                            for assignment in assignments:

                                transport_type = self.env['transport.type'].browse(assignment['transport_type_id'])

                                if transport_type.code == 'PU':
                                    if district_from:
                                        current_time = self._get_next_available_time(current_time, district_from, rec.company_id)
                                        assignment['planned_pick_up_time'] = current_time
                                        assignment['planned_delivery_time'] = current_time + timedelta(
                                            hours=self._get_duration_for_day(current_time, district_from))
                                        current_time = assignment['planned_delivery_time']
                                elif transport_type.code == 'DE':
                                    if district_to:
                                        current_time = self._get_next_available_time(current_time, district_to, rec.company_id)
                                        assignment['planned_pick_up_time'] = current_time
                                        assignment['planned_delivery_time'] = current_time + timedelta(
                                            hours=self._get_duration_for_day(current_time, district_to))
                                        current_time = assignment['planned_delivery_time']
                                elif transport_type.code == 'LI':
                                    line = self.env['transport.line'].search([('id', '=', assignment['transport_line_id'])],
                                                                             limit=1)
                                    if line:
                                        current_time = self._get_next_available_time(current_time, line, rec.company_id)
                                        assignment['planned_pick_up_time'] = current_time
                                        assignment['planned_delivery_time'] = current_time + timedelta(
                                            hours=self._get_duration_for_day(current_time, line))
                                        current_time = assignment['planned_delivery_time']

                            created = self.env['road.assignment']
                            for assignment in assignments:
                                created |= self.env['road.assignment'].with_company(rec.company_id).with_context(skip_auto_cost_lines=True).create(assignment)
                            created.fetch_distance()
                            created.generate_road_assignment_lines()
                        else:
                            raise ValidationError(
                                "No matching districts found for the given sender and receiver zip codes and countries.")
                else:
                    _logger.warning("No planning type defined for transport order %s", rec.number)
            else:
                _logger.warning("No assignment planning criteria found for billable weight %s on order %s", rec.total_billable_weight, rec.number)


    def _get_next_available_time(self, current_time, obj, company_id):
        day_of_week = current_time.weekday()
        max_date = current_time + timedelta(days=14)  # Sätt en gräns på två veckor framåt

        while current_time <= max_date:

            # Check if current date is a holiday
            if current_time and company_id:
                holiday = self.env['holiday'].search([('company_ids', 'in', company_id.id),('date', '=', current_time.date())], limit=1)

                if holiday:
                    if obj.traffic_on_holidays:
                        start_time = current_time.replace(hour=int(obj.start_time_holidays), minute=round((obj.start_time_holidays % 1) * 60), second=0, microsecond=0)
                        if current_time <= start_time:
                            return start_time
                else:
                    if day_of_week == 0 and obj.traffic_on_mondays:
                        start_time = current_time.replace(hour=int(obj.start_time_mondays), minute=round((obj.start_time_mondays % 1) * 60), second=0, microsecond=0)
                        if current_time <= start_time:
                            return start_time
                    elif day_of_week == 1 and obj.traffic_on_tuesdays:
                        start_time = current_time.replace(hour=int(obj.start_time_tuesdays), minute=round((obj.start_time_tuesdays % 1) * 60), second=0, microsecond=0)
                        if current_time <= start_time:
                            return start_time
                    elif day_of_week == 2 and obj.traffic_on_wednesdays:
                        start_time = current_time.replace(hour=int(obj.start_time_wednesdays), minute=round((obj.start_time_wednesdays % 1) * 60), second=0, microsecond=0)
                        if current_time <= start_time:
                            return start_time
                    elif day_of_week == 3 and obj.traffic_on_thursdays:
                        start_time = current_time.replace(hour=int(obj.start_time_thursdays), minute=round((obj.start_time_thursdays % 1) * 60), second=0, microsecond=0)
                        if current_time <= start_time:
                            return start_time
                    elif day_of_week == 4 and obj.traffic_on_fridays:
                        start_time = current_time.replace(hour=int(obj.start_time_fridays), minute=round((obj.start_time_fridays % 1) * 60), second=0, microsecond=0)
                        if current_time <= start_time:
                            return start_time
                    elif day_of_week == 5 and obj.traffic_on_saturdays:
                        start_time = current_time.replace(hour=int(obj.start_time_saturdays), minute=round((obj.start_time_saturdays % 1) * 60), second=0, microsecond=0)
                        if current_time <= start_time:
                            return start_time
                    elif day_of_week == 6 and obj.traffic_on_sundays:
                        start_time = current_time.replace(hour=int(obj.start_time_sundays), minute=round((obj.start_time_sundays % 1) * 60), second=0, microsecond=0)
                        if current_time <= start_time:
                            return start_time

                current_time = (current_time + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
                day_of_week = (day_of_week + 1) % 7

        raise ValueError("Ingen giltig starttid hittades inom två veckor.")

    def _get_duration_for_day(self, current_time, obj):
        day_of_week = current_time.weekday()
        if day_of_week == 0:
            return obj.mondays_duration
        elif day_of_week == 1:
            return obj.tuesdays_duration
        elif day_of_week == 2:
            return obj.wednesdays_duration
        elif day_of_week == 3:
            return obj.thursdays_duration
        elif day_of_week == 4:
            return obj.fridays_duration
        elif day_of_week == 5:
            return obj.saturdays_duration
        elif day_of_week == 6:
            return obj.sundays_duration
        return 0

    def _increment_address_usage(self, address_id):
        for order in self:
            if address_id and order.customer_id:
                usage_record = self.env['transport.address.usage'].search([
                    ('customer_id', '=', order.customer_id.id),
                    ('address_id', '=', address_id.id)
                ], limit=1)
                if usage_record:
                    usage_record.usage_count += 1
                else:
                    self.env['transport.address.usage'].create({
                        'customer_id': order.customer_id.id,
                        'address_id': address_id.id,
                        'usage_count': 1
                    })
    def _get_fallback_price_from_product(self, product_id, transport_order):
        """
        Creates a price line dict using the product's lst_price (Sales Price)
        as a fallback when no contract price is found.
        """
        _logger.info(f"Using fallback sales price for product {product_id} on order {transport_order.number}")
        
        product = self.env['product.product'].browse(product_id)
        if not product:
            return []
        sales_price = product.lst_price
        currency_id = transport_order.company_id.currency_id.id
        parent_vals = {
            'transport_order_id': transport_order.id,
            'product_id': product_id,
            'quantity': 1,
            'price_per_unit': sales_price,
            'price': sales_price,
            'currency_id': currency_id,
            'sales_transport_contract_id': False,
            'sales_transport_price_list_id': False,
            'breakpoint_calculation': False,
            'manually_added': False,
        }
        return [parent_vals]

    @staticmethod
    def _goods_line_source_overrides(goods_line):
        """Build pricing source_overrides from a goods.line so the pricing
        service uses this row's intervals/dimensions instead of order totals.
        Used by both generate_transport_order_lines and the auto-refresh hook
        to keep per-goods-line behavior consistent."""
        if not goods_line:
            return {}
        return {
            'total_billable_weight': goods_line.billable_weight,
            'total_volume': goods_line.volume_m3,
            'total_ldm': goods_line.ldm,
            'total_gross_weight': goods_line.gross_weight,
            'container_type_id': goods_line.container_type_id,
            'material_type_id': goods_line.material_type_id,
            'package_type_id': goods_line.package_type_id,
            'nmfc_class_id': goods_line.nmfc_class_id,
            'has_dangerous_goods': goods_line.is_dangerous_goods,
        }

    def _auto_refresh_contract_prices(self):
        """Re-run pricing on every contract-linked parent line. Called from
        write() when a quantity_source field changes (weight, distance, etc.).
        Approved orders are left untouched. Lines linked to a goods_line use
        that row's values as source_overrides; other lines use order totals."""
        Pricing = self.env['sales.transport.pricing']
        Line = self.env['transport.order.line']
        for order in self:
            if order.prices_approved:
                continue
            parent_lines = order.transport_order_line_ids.filtered(
                lambda l: not l.parent_line_id and l.sales_transport_contract_id and l.product_id
            )
            for line in parent_lines:
                source_overrides = self._goods_line_source_overrides(line.goods_line_id) or None
                price_lines_vals_list = Pricing.calculate_price_for_product(
                    line.product_id.id, order.id,
                    source_overrides=source_overrides,
                )
                if not price_lines_vals_list:
                    continue
                line.child_line_ids.with_context(skip_approval_reset=True).unlink()
                parent_vals = price_lines_vals_list[0]
                parent_vals.pop('transport_order_id', None)
                parent_vals.pop('product_id', None)
                line.with_context(skip_approval_reset=True).write(parent_vals)
                if len(price_lines_vals_list) > 1:
                    child_lines_to_create = []
                    for child_vals in price_lines_vals_list[1:]:
                        child_vals['parent_line_id'] = line.id
                        child_vals['manually_added'] = False
                        child_lines_to_create.append(child_vals)
                    Line.with_context(skip_approval_reset=True).create(child_lines_to_create)

    def action_dismiss_prices_stale(self):
        for order in self:
            order.prices_stale = False
            order.message_post(
                body="Stale prices warning dismissed — prices accepted as-is.",
                message_type='comment',
                subtype_xmlid='mail.mt_note',
            )

    def action_dismiss_shipping_legs_stale(self):
        for order in self:
            order.shipping_legs_stale = False
            order.message_post(
                body="Stale assignments warning dismissed — assignments accepted as-is.",
                message_type='comment',
                subtype_xmlid='mail.mt_note',
            )

    def generate_transport_order_lines(self):
        for rec in self:
            _logger.info("Starting generation of transport order lines for order %s", rec.number)
            
            # --- Delete old lines ---
            transport_order_lines_to_delete = self.env['transport.order.line'].search([
                ('transport_order_id', '=', rec.id),
                ('manually_added', '=', False)
            ])
            if transport_order_lines_to_delete:
                _logger.info("Deleting %d old auto-generated lines", len(transport_order_lines_to_delete))
                transport_order_lines_to_delete.with_context(skip_approval_reset=True).unlink()
            else:
                _logger.info("No old auto-generated lines to delete")

            engine_lines = self.env['transport.order.line.engine'].sudo().generate_transport_order_lines(rec)
            _logger.info("Generated %d engine lines", len(engine_lines))

            parent_line_map = {}  # Stores {dedup_key: {'vals': {}, 'child_vals': []}}
            all_child_product_ids = set()

            # --- Pass 1: Collect and Map All Lines ---
            _logger.info("Starting Pass 1: Collecting and mapping lines")
            for engine_line in engine_lines:
                product_id = engine_line["product_id"]
                _logger.debug("Processing product_id %s", product_id)

                # Per-goods-line pricing: pull intervals + dimensions from the
                # goods.line so each row gets its own quantity/material match.
                goods_line_id = engine_line.get('goods_line_id')
                goods_line = self.env['goods.line'].browse(goods_line_id) if goods_line_id else False
                source_overrides = self._goods_line_source_overrides(goods_line)

                # Composite dedup key: product + goods-line (so two goods rows
                # with the same material still produce two revenue lines).
                dedup_key = (
                    product_id,
                    goods_line_id or False,
                )

                if dedup_key in parent_line_map:
                    _logger.debug("Dedup key %s already mapped, skipping", dedup_key)
                    continue

                price_lines_vals_list = self.env['sales.transport.pricing'].sudo().calculate_price_for_product(
                    product_id, rec.id,
                    source_overrides=source_overrides or None,
                )

                # --- THIS IS THE MODIFICATION ---
                if not price_lines_vals_list:
                    _logger.warning("No price lines found for product %s. Using fallback product price.", product_id)
                    # Get the fallback price instead of skipping
                    price_lines_vals_list = self._get_fallback_price_from_product(product_id, rec)
                    # If fallback also fails (e.g., product deleted), then skip
                    if not price_lines_vals_list:
                        continue
                # --- END OF MODIFICATION ---

                parent_vals = price_lines_vals_list[0]
                child_vals_list = price_lines_vals_list[1:]

                # Persist the goods-line link on the revenue line so the
                # auto-refresh hook can later rebuild source_overrides.
                if goods_line_id:
                    parent_vals['goods_line_id'] = goods_line_id

                _logger.debug("Found %d child lines for product %s", len(child_vals_list), product_id)
                parent_line_map[dedup_key] = {'vals': parent_vals, 'child_vals': child_vals_list}

                for child_vals in child_vals_list:
                    if 'product_id' in child_vals:
                        all_child_product_ids.add(child_vals['product_id'])

            # --- Pass 2: Create True Parent Lines ---
            _logger.info("Starting Pass 2: Creating parent lines")
            true_parent_records = {}
            child_lines_to_create_vals_list = []

            for dedup_key, data in parent_line_map.items():
                product_id = data['vals']['product_id']
                if product_id in all_child_product_ids:
                    _logger.debug("Product %s is a child product, skipping as parent", product_id)
                    continue

                _logger.debug("Creating parent line for product %s (key %s)", product_id, dedup_key)
                # Ensure transport_order_id is set
                data['vals']['transport_order_id'] = rec.id
                parent_record = self.env['transport.order.line'].with_context(skip_approval_reset=True).create(data['vals'])
                true_parent_records[dedup_key] = parent_record

            # --- Pass 3: Gather and Create All Child Lines ---
            _logger.info("Starting Pass 3: Creating child lines")
            for dedup_key, parent_record in true_parent_records.items():
                child_vals_list = parent_line_map[dedup_key]['child_vals']
                _logger.debug("Processing %d children for parent key %s", len(child_vals_list), dedup_key)
                
                for child_vals in child_vals_list:
                    child_vals['parent_line_id'] = parent_record.id
                    child_vals['transport_order_id'] = rec.id # Also set order ID
                    child_lines_to_create_vals_list.append(child_vals)

            if child_lines_to_create_vals_list:
                _logger.info("Creating %d child lines", len(child_lines_to_create_vals_list))
                self.env['transport.order.line'].with_context(skip_approval_reset=True).create(child_lines_to_create_vals_list)
            else:
                _logger.info("No child lines to create")

            # Reset stale flag and approval after (re)generating prices
            vals_to_reset = {}
            if rec.prices_stale:
                vals_to_reset['prices_stale'] = False
            if rec.prices_approved:
                vals_to_reset['prices_approved'] = False
            if vals_to_reset:
                rec.write(vals_to_reset)

            _logger.info("Finished generating transport order lines for order %s", rec.number)

    @api.depends('road_assignment_ids.state', 'road_assignment_ids.transport_type_id')
    def _compute_transport_order_state(self):
        """
        Computes the state of the transport order based on the states and types
        of its linked road assignments. This logic can upgrade or downgrade the status.
        """
        for order in self:
            # Rule 0: Final states are permanent and are not re-computed.
            if order.state in ('cancelled', 'closed'):
                continue

            # If there are no assignments, its state is controlled manually (e.g., Draft -> Confirmed).
            if not order.road_assignment_ids:
                order.state = order.state or 'draft'
                continue

            assignments = order.road_assignment_ids
            assignment_states = set(assignments.mapped('state'))

            # --- REVISED LOGIC ---

            # If ALL assignments are cancelled, keep current state and require manual handling.
            if all(s == 'cancelled' for s in assignment_states):
                order.state = order.state or 'confirmed'
                continue

            # Start with the most basic state and check for conditions to upgrade it.
            new_state = 'confirmed'

            # Rule for 'Planned': If ANY non-cancelled assignment is planned or beyond, the order is at least 'planned'.
            if any(s in ['planned', 'started', 'done', 'closed'] for s in assignment_states):
                new_state = 'planned'

            # Rule for 'Started': If ANY assignment has been started (or is done), the order is at least 'started'.
            if any(s in ['started', 'done', 'closed'] for s in assignment_states):
                new_state = 'started'

            # Rule for 'Done' (this overrides 'started' if conditions are met):
            # Condition 1: A final 'Direct' or 'Delivery' assignment is 'done' or 'closed'.
            is_final_leg_done = any(
                a.transport_type_id.name in ['Direct', 'Delivery'] and a.state in ('done', 'closed')
                for a in assignments if a.transport_type_id
            )
            # Condition 2: ALL assignments are in a finished state ('done', 'closed', or 'cancelled').
            all_legs_finished = all(s in ['done', 'closed', 'cancelled'] for s in assignment_states)

            if is_final_leg_done or all_legs_finished:
                new_state = 'done'

            # Rule for 'Closed': ALL non-cancelled assignments must be 'closed'.
            all_closed = all(
                s in ['closed', 'cancelled'] for s in assignment_states
            ) and any(s == 'closed' for s in assignment_states)
            if all_closed:
                new_state = 'closed'

            # Generate sequence number when leaving draft for the first time
            if new_state != 'draft' and (order.number == 'New' or not order.number):
                seq_id = self.env['ir.config_parameter'].sudo().get_param('transport_management.transport_order_sequence_id')
                if seq_id:
                    order.number = self.env['ir.sequence'].sudo().browse(int(seq_id)).next_by_id()
                else:
                    order.number = self.env['ir.sequence'].sudo().next_by_code('transport.order')

            # Set the final computed state
            order.state = new_state
        

    ALLOWED_STATE_TRANSITIONS = {
        'draft': {'confirmed', 'cancelled'},
        'confirmed': {'draft', 'planned', 'cancelled'},
        'planned': {'confirmed', 'started', 'done', 'cancelled'},
        'started': {'done', 'cancelled'},
        'done': {'closed'},
        'closed': {'done'},  # Reopen
        'cancelled': {'draft'},
    }

    def _inverse_state(self):
        """Validate manual state changes (via buttons) against allowed transitions."""
        for order in self:
            old_state = order._origin.state if order._origin else 'draft'
            new_state = order.state
            if old_state == new_state:
                continue
            allowed = self.ALLOWED_STATE_TRANSITIONS.get(old_state, set())
            if new_state not in allowed:
                raise ValidationError(
                    _("Cannot change order status from '%(old)s' to '%(new)s'.",
                      old=old_state, new=new_state)
                )

    def _cron_archive_old_orders(self):
        """
        Archives transport orders and their assignments older than the configured period.
        Also archives any old assignments independently.
        """
        archiving_period = self.env['ir.config_parameter'].sudo().get_param('transport_management.archiving_period')
        count = 0

        if archiving_period:
            cutoff_date = fields.Datetime.now() - relativedelta(months=int(archiving_period))

            # PART 1: Archive old Transport Orders and their related Assignments
            orders_to_archive = self.search([
                ('start_time', '<', cutoff_date),
                ('active', '=', True)
            ])

            if orders_to_archive:
                count = len(orders_to_archive)
                # Archive the orders
                orders_to_archive.write({'active': False})

                # Archive their related assignments
                assignments_of_archived_orders = self.env['road.assignment'].search([
                    ('transport_order_id', 'in', orders_to_archive.ids)
                ])
                if assignments_of_archived_orders:
                    assignments_of_archived_orders.write({'active': False})

            # PART 2: Independently archive any other old Road Assignments
            other_assignments_to_archive = self.env['road.assignment'].search([
                ('planned_pick_up_time', '<', cutoff_date),
                ('active', '=', True)
            ])

            if other_assignments_to_archive:
                other_assignments_to_archive.write({'active': False})

        # Set message for isotrax logging
        import threading
        thread = threading.current_thread()
        if hasattr(thread, 'isotrax_job_message'):
            thread.isotrax_job_message = f"{count} transport orders archived"
        return count
    def _action_print_waybill(self, report_action_xml_id):
        """
        This method ALWAYS opens the language selection wizard for the selected records.
        """
        if not self:
            return

        return {
            'type': 'ir.actions.act_window',
            'name': 'Choose Report Language',
            'res_model': 'waybill.report.language.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'active_ids': self.ids,
                'active_model': self._name,
                'report_action_xml_id': report_action_xml_id,
            }
        }

    def action_print_cmr_waybill(self):
        # 2. ADD YOUR DEBUG MESSAGES HERE
        return self._action_print_waybill('transport_management.action_cmr_waybill')

    def action_print_sis_waybill(self):
        return {
            'type': 'ir.actions.act_window',
            'name': 'Choose Report Language',
            'res_model': 'sis.waybill.report.language.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'active_ids': self.ids,
                'active_model': self._name,
                'report_action_xml_id': 'transport_management.action_sis_waybill',
            }
        }
    def get_translated_term(self, term):
        """
        This helper method allows QWeb to get a translation for a specific
        term by calling it on a recordset with a modified context.
        """
        return _(term)
    def _action_open_map_wizard(self, latitude, longitude, name, title, location_type):
        """Helper method to open the map wizard."""
        self.ensure_one()
        if not latitude or not longitude:
            raise ValidationError(_("Coordinates are not available for this address."))

        return {
            'type': 'ir.actions.act_window',
            'name': title,
            'res_model': 'map.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_latitude': latitude,
                'default_longitude': longitude,
                'default_name': name,
                'default_location_type': location_type,
                'active_model': self._name,
                'active_id': self.id,
            }
        }

    def action_open_sender_map(self):
        """Opens the map wizard for the sender's location."""
        return self._action_open_map_wizard(
            self.sender_latitude, 
            self.sender_longitude, 
            self.sender_name,
            _('Sender Location'),
            'sender'
        )

    def action_open_receiver_map(self):
        """Opens the map wizard for the receiver's location."""
        return self._action_open_map_wizard(
            self.receiver_latitude, 
            self.receiver_longitude, 
            self.receiver_name,
            _('Receiver Location'),
            'receiver'
        )

    def action_generate_waybill_number(self):
        """Generate a new waybill number from the active number series."""
        self.ensure_one()
        if not self.company_id:
            raise ValidationError(_('Company has to be defined in order to generate a new waybill number.'))
        new_number = self.env['waybill.number'].sudo().get_new_waybill_number(self.company_id.id)
        self.waybill_number = new_number

    def action_open_customer(self):
        """Opens the customer's partner form."""
        self.ensure_one()
        if not self.customer_id:
            return
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'res.partner',
            'res_id': self.customer_id.id,
            'view_mode': 'form',
            'target': 'current',
        }

    def action_open_transport_customer(self):
        """Open the transport.customer record linked to this order's customer."""
        self.ensure_one()
        if not self.customer_id:
            return
        customer = self.env['transport.customer'].search([
            ('partner_id', '=', self.customer_id.id),
        ], limit=1)
        if not customer:
            raise UserError(_(
                "No transport customer record found for %s.",
                self.customer_id.name,
            ))
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'transport.customer',
            'res_id': customer.id,
            'view_mode': 'form',
            'view_id': self.env.ref(
                'transport_management.view_transport_customer_form'
            ).id,
        }

    def action_confirm_my_draft_assignments(self):
        """
        Finds all 'draft' road assignments related to this transport order
        that were created by the current user, and confirms them.
        """
        # Ensure we only act on the current user's assignments
        user_id = self.env.user.id

        for order in self:
            # Search for the specific assignments to confirm
            assignments_to_confirm = self.env['road.assignment'].search([
                ('transport_order_id', '=', order.id),
                ('state', '=', 'draft'),
                ('create_uid', '=', user_id)
            ])

            if assignments_to_confirm:
                assignments_to_confirm.action_confirm()
                return True

    # ── Consignment Reference Layer Fields ──
    consignment_origin_address_id = fields.Many2one('res.partner', string='Consignment origin address')
    consignment_origin_name = fields.Char(string='Consignment origin name')
    consignment_origin_street = fields.Char(string='Consignment origin street')
    consignment_origin_street_2 = fields.Char(string='Consignment origin street 2')
    consignment_origin_city = fields.Char(string='Consignment origin city')
    consignment_origin_state_id = fields.Many2one('res.country.state', string='Consignment origin state')
    consignment_origin_zip = fields.Char(string='Consignment origin zip')
    consignment_origin_country_id = fields.Many2one('res.country', string='Consignment origin country')
    consignment_origin_latitude = fields.Float(string='Consignment origin latitude', digits=(16, 5))
    consignment_origin_longitude = fields.Float(string='Consignment origin longitude', digits=(16, 5))

    consignment_destination_address_id = fields.Many2one('res.partner', string='Consignment destination address')
    consignment_destination_name = fields.Char(string='Consignment destination name')
    consignment_destination_street = fields.Char(string='Consignment destination street')
    consignment_destination_street_2 = fields.Char(string='Consignment destination street 2')
    consignment_destination_city = fields.Char(string='Consignment destination city')
    consignment_destination_state_id = fields.Many2one('res.country.state', string='Consignment destination state')
    consignment_destination_zip = fields.Char(string='Consignment destination zip')
    consignment_destination_country_id = fields.Many2one('res.country', string='Consignment destination country')
    consignment_destination_latitude = fields.Float(string='Consignment destination latitude', digits=(16, 5))
    consignment_destination_longitude = fields.Float(string='Consignment destination longitude', digits=(16, 5))

    consignment_sender_id = fields.Many2one('res.partner', string='Original sender')
    consignment_consignee_id = fields.Many2one('res.partner', string='Final consignee')

    consignment_waybill_number = fields.Char(string='Master waybill number')
    ordering_carrier_id = fields.Many2one('res.partner', string='Ordering carrier')
    is_successive_carriage = fields.Boolean(string='Successive carriage', default=False)
    
    driver_notes = fields.Text(string='Driver notes')
    own_fleet = fields.Boolean(string='Own fleet', default=False)
    created_via_booking_new = fields.Boolean(string='Created via new booking UI', default=False)

    @api.onchange('consignment_origin_address_id')
    def _onchange_consignment_origin_address_id(self):
        if self.consignment_origin_address_id:
            self.consignment_origin_name = self.consignment_origin_address_id.name
            self.consignment_origin_street = self.consignment_origin_address_id.street
            self.consignment_origin_street_2 = self.consignment_origin_address_id.street2
            self.consignment_origin_city = self.consignment_origin_address_id.city
            self.consignment_origin_state_id = self.consignment_origin_address_id.state_id.id
            self.consignment_origin_zip = self.consignment_origin_address_id.zip
            self.consignment_origin_country_id = self.consignment_origin_address_id.country_id.id
            self.consignment_origin_latitude = self.consignment_origin_address_id.partner_latitude
            self.consignment_origin_longitude = self.consignment_origin_address_id.partner_longitude

    @api.onchange('consignment_destination_address_id')
    def _onchange_consignment_destination_address_id(self):
        if self.consignment_destination_address_id:
            self.consignment_destination_name = self.consignment_destination_address_id.name
            self.consignment_destination_street = self.consignment_destination_address_id.street
            self.consignment_destination_street_2 = self.consignment_destination_address_id.street2
            self.consignment_destination_city = self.consignment_destination_address_id.city
            self.consignment_destination_state_id = self.consignment_destination_address_id.state_id.id
            self.consignment_destination_zip = self.consignment_destination_address_id.zip
            self.consignment_destination_country_id = self.consignment_destination_address_id.country_id.id
            self.consignment_destination_latitude = self.consignment_destination_address_id.partner_latitude
            self.consignment_destination_longitude = self.consignment_destination_address_id.partner_longitude

    @api.onchange('receiver_address_id', 'receiver_name', 'receiver_street', 'receiver_street_2', 'receiver_city', 'receiver_state_id', 'receiver_zip', 'receiver_country_id', 'receiver_latitude', 'receiver_longitude')
    def _onchange_receiver_for_consignment(self):
        if not self.consignment_destination_address_id:
            self.consignment_destination_address_id = self.receiver_address_id
        if not self.consignment_destination_name:
            self.consignment_destination_name = self.receiver_name
        if not self.consignment_destination_street:
            self.consignment_destination_street = self.receiver_street
        if not self.consignment_destination_street_2:
            self.consignment_destination_street_2 = self.receiver_street_2
        if not self.consignment_destination_city:
            self.consignment_destination_city = self.receiver_city
        if not self.consignment_destination_state_id:
            self.consignment_destination_state_id = self.receiver_state_id
        if not self.consignment_destination_zip:
            self.consignment_destination_zip = self.receiver_zip
        if not self.consignment_destination_country_id:
            self.consignment_destination_country_id = self.receiver_country_id
        if not self.consignment_destination_latitude:
            self.consignment_destination_latitude = self.receiver_latitude
        if not self.consignment_destination_longitude:
            self.consignment_destination_longitude = self.receiver_longitude

    def _prepare_booking_order_vals(self, payload):
        def _m2o(val):
            return int(val) if val else False

        vals = {
            'customer_id': _m2o(payload.get('customer_id')),
            'order_contact_id': _m2o(payload.get('order_contact_id')),
            'order_reference': payload.get('order_reference'),
            'project_code': payload.get('project_code'),
            'transport_order_type_id': _m2o(payload.get('transport_order_type_id')),
            'freight_service_id': _m2o(payload.get('freight_service_id')),
            'goods_profile_id': _m2o(payload.get('goods_profile_id')),
            'company_id': _m2o(payload.get('company_id')) or self.env.company.id,
            'created_via_booking_new': True,
            
            'sender_address_id': _m2o(payload.get('sender_address_id')),
            'sender_name': payload.get('sender_name'),
            'sender_street': payload.get('sender_street'),
            'sender_street_2': payload.get('sender_street_2'),
            'sender_city': payload.get('sender_city'),
            'sender_state_id': _m2o(payload.get('sender_state_id')),
            'sender_zip': payload.get('sender_zip'),
            'sender_country_id': _m2o(payload.get('sender_country_id')),
            'sender_latitude': float(payload.get('sender_latitude') or 0.0),
            'sender_longitude': float(payload.get('sender_longitude') or 0.0),
            'sender_phone': payload.get('sender_phone'),
            'sender_mobile': payload.get('sender_mobile'),
            'sender_email': payload.get('sender_email'),
            'sender_contact_person': payload.get('sender_contact_person'),
            'sender_contact_phone': payload.get('sender_contact_phone'),
            'sender_access_instructions': payload.get('sender_access_instructions'),
            'sender_price_zone_id': _m2o(payload.get('sender_price_zone_id')),
            
            'receiver_address_id': _m2o(payload.get('receiver_address_id')),
            'receiver_name': payload.get('receiver_name'),
            'receiver_street': payload.get('receiver_street'),
            'receiver_street_2': payload.get('receiver_street_2'),
            'receiver_city': payload.get('receiver_city'),
            'receiver_state_id': _m2o(payload.get('receiver_state_id')),
            'receiver_zip': payload.get('receiver_zip'),
            'receiver_country_id': _m2o(payload.get('receiver_country_id')),
            'receiver_latitude': float(payload.get('receiver_latitude') or 0.0),
            'receiver_longitude': float(payload.get('receiver_longitude') or 0.0),
            'receiver_phone': payload.get('receiver_phone'),
            'receiver_mobile': payload.get('receiver_mobile'),
            'receiver_email': payload.get('receiver_email'),
            'receiver_contact_person': payload.get('receiver_contact_person'),
            'receiver_contact_phone': payload.get('receiver_contact_phone'),
            'receiver_access_instructions': payload.get('receiver_access_instructions'),
            'receiver_price_zone_id': _m2o(payload.get('receiver_price_zone_id')),
            
            'consignment_origin_address_id': _m2o(payload.get('consignment_origin_address_id')),
            'consignment_origin_name': payload.get('consignment_origin_name'),
            'consignment_origin_street': payload.get('consignment_origin_street'),
            'consignment_origin_street_2': payload.get('consignment_origin_street_2'),
            'consignment_origin_city': payload.get('consignment_origin_city'),
            'consignment_origin_state_id': _m2o(payload.get('consignment_origin_state_id')),
            'consignment_origin_zip': payload.get('consignment_origin_zip'),
            'consignment_origin_country_id': _m2o(payload.get('consignment_origin_country_id')),
            'consignment_origin_latitude': float(payload.get('consignment_origin_latitude') or 0.0),
            'consignment_origin_longitude': float(payload.get('consignment_origin_longitude') or 0.0),
            
            'consignment_destination_address_id': _m2o(payload.get('consignment_destination_address_id')),
            'consignment_destination_name': payload.get('consignment_destination_name'),
            'consignment_destination_street': payload.get('consignment_destination_street'),
            'consignment_destination_street_2': payload.get('consignment_destination_street_2'),
            'consignment_destination_city': payload.get('consignment_destination_city'),
            'consignment_destination_state_id': _m2o(payload.get('consignment_destination_state_id')),
            'consignment_destination_zip': payload.get('consignment_destination_zip'),
            'consignment_destination_country_id': _m2o(payload.get('consignment_destination_country_id')),
            'consignment_destination_latitude': float(payload.get('consignment_destination_latitude') or 0.0),
            'consignment_destination_longitude': float(payload.get('consignment_destination_longitude') or 0.0),
            
            'consignment_sender_id': _m2o(payload.get('consignment_sender_id')),
            'consignment_consignee_id': _m2o(payload.get('consignment_consignee_id')),
            'consignment_waybill_number': payload.get('consignment_waybill_number'),
            'waybill_number': payload.get('consignment_waybill_number'),
            'ordering_carrier_id': _m2o(payload.get('ordering_carrier_id')),
            'is_successive_carriage': bool(payload.get('is_successive_carriage')),
            
            'pick_up_date': payload.get('pick_up_date'),
            'pick_up_time_window': payload.get('pick_up_time_window'),
            'pick_up_time_from': payload.get('pick_up_time_from') or None,
            'pick_up_time_to': payload.get('pick_up_time_to') or None,
            'delivery_date': payload.get('delivery_date'),
            'delivery_time_window': payload.get('delivery_time_window'),
            'delivery_time_from': payload.get('delivery_time_from') or None,
            'delivery_time_to': payload.get('delivery_time_to') or None,
            'estimatedTimeOfDelivery': payload.get('estimatedTimeOfDelivery') or None,
            'estimated_pickup_duration': int(payload.get('estimated_pickup_duration') or 0),
            'estimated_delivery_duration': int(payload.get('estimated_delivery_duration') or 0),
            'priority': payload.get('priority') or '0',
            'incoterm_id': _m2o(payload.get('incoterm_id')),
            'incoterm_location': payload.get('incoterm_location'),
            
            'driver_notes': payload.get('driver_notes'),
            'internal_details': payload.get('internal_details'),
            'external_details': payload.get('external_details'),
            'invoicing_instructions': payload.get('invoicing_instructions'),
            'invoice_reference': payload.get('invoice_reference'),
            
            'require_delivery_photo': bool(payload.get('require_delivery_photo')),
            'require_delivery_signature': bool(payload.get('require_delivery_signature')),
            'requirement_ids': [(6, 0, [int(rid) for rid in payload.get('requirement_ids', [])])],

            'commissionnaire_id': _m2o(payload.get('commissionnaire_id')),
            'cod_amount': float(payload.get('cod_amount') or 0.0),
            'cod_currency_id': _m2o(payload.get('cod_currency_id')),
            'hazmat_emergency_phone': payload.get('hazmat_emergency_phone'),
        }
        return vals

    def _prepare_booking_goods_line_vals(self, g, order):
        def _m2o(val):
            return int(val) if val else False
            
        def _cm_to_m(val):
            return float(val or 0.0) / 100.0

        def _temp(val):
            if val is None or val == '':
                return False
            try:
                return float(val)
            except (TypeError, ValueError):
                return False

        vals = {
            'transport_order_id': order.id,
            'package_id': g.get('package_id'),
            'goods_label': g.get('goods_label'),
            'description': g.get('description'),
            'quantity': int(g.get('quantity') or 1),
            'package_type_id': _m2o(g.get('package_type_id')),
            'length': _cm_to_m(g.get('length')),
            'width': _cm_to_m(g.get('width')),
            'height': _cm_to_m(g.get('height')),
            'volume_compute_method': g.get('volume_compute_method') or 'manual',
            'volume_manual': float(g.get('volume_manual') or 0.0),
            'ldm_compute_method': g.get('ldm_compute_method') or 'manual',
            'ldm_manual': float(g.get('ldm_manual') or 0.0),
            'stackable': bool(g.get('stackable', True) if g.get('stackable') is not None else True),
            'stacking_factor': float(g.get('stacking_factor') or 1.0),
            'gross_weight': float(g.get('gross_weight') or 0.0),
            'hs_code': g.get('hs_code'),
            
            'is_dangerous_goods': bool(g.get('is_dangerous_goods')),
            'adr_substance_id': _m2o(g.get('adr_substance_id')),
            'adr_description': g.get('adr_description'),
            'net_explosive_mass': float(g.get('net_explosive_mass') or 0.0),
            'adr_limited_quantity': bool(g.get('adr_limited_quantity')),
            'environmentally_hazardous': bool(g.get('environmentally_hazardous')),
            
            'temperature_min': _temp(g.get('temperature_min')),
            'temperature_max': _temp(g.get('temperature_max')),

            'material_type_id': _m2o(g.get('material_type_id')),
            'waste_code': g.get('waste_code'),
            'container_type_id': _m2o(g.get('container_type_id')),
            'container_number': g.get('container_number'),
            'container_seal_number': g.get('container_seal_number'),
            'container_tare_weight': float(g.get('container_tare_weight') or 0.0),
            
            'volume_liters': float(g.get('volume_liters') or 0.0),
            'liquid_density': float(g.get('liquid_density') or 0.0),
            'liquid_product_name': g.get('liquid_product_name'),
            
            'nmfc_class_manual': bool(g.get('nmfc_class_manual')),
            'nmfc_class_id': _m2o(g.get('nmfc_class_id')),
        }
        return vals

    def _get_default_product_id(self):
        product = self.env.ref('transport_management.product_freight_service', raise_if_not_found=False)
        if product:
            return product.id
        fallback = self.env['product.product'].search([], limit=1)
        return fallback.id if fallback else False

    @api.model
    def create_from_booking(self, payload):
        order_vals = self._prepare_booking_order_vals(payload)
        order = self.create(order_vals)
        
        goods_vals_list = []
        for g in payload.get('goods_lines', []):
            g_vals = self._prepare_booking_goods_line_vals(g, order)
            goods_vals_list.append(g_vals)
        if goods_vals_list:
            self.env['goods.line'].create(goods_vals_list)
            
        self.env.flush_all()
        order._compute_total_gross_weight()
        order._compute_total_billable_weight()
        order._compute_total_volume()
        order._compute_total_ldm()
        # Clear any auto-generated lines created by self.create() to match the UI charges list
        order.transport_order_line_ids.unlink()
        
        charge_vals_list = []
        for c in payload.get('charges', []):
            product_id = int(c.get('product_id') or 0)
            if not product_id:
                product_id = self._get_default_product_id()
            if product_id:
                charge_vals_list.append({
                    'transport_order_id': order.id,
                    'product_id': product_id,
                    'price_type': c.get('price_type') or 'price_per_order',
                    'quantity': float(c.get('quantity') or 0.0),
                    'price_per_unit': float(c.get('price_per_unit') or 0.0),
                    'manually_added': bool(c.get('manually_added', True)),
                })
        if charge_vals_list:
            self.env['transport.order.line'].create(charge_vals_list)
            
        if payload.get('planning_type'):
            order.generate_assignments()
            
        if order.driver_notes and order.road_assignment_ids:
            order.road_assignment_ids.write({'driver_notes': order.driver_notes})
            
        return order.id

    @api.model
    def write_from_booking(self, order_id, payload):
        order = self.browse(order_id)
        order_vals = self._prepare_booking_order_vals(payload)
        order.write(order_vals)
        
        order.goods_line_ids.unlink()
        goods_vals_list = []
        for g in payload.get('goods_lines', []):
            g_vals = self._prepare_booking_goods_line_vals(g, order)
            goods_vals_list.append(g_vals)
        if goods_vals_list:
            self.env['goods.line'].create(goods_vals_list)
            
        self.env.flush_all()
        order._compute_total_gross_weight()
        order._compute_total_billable_weight()
        order._compute_total_volume()
        order._compute_total_ldm()
        # Clear all existing lines to match the UI charges list
        order.transport_order_line_ids.unlink()
        
        charge_vals_list = []
        for c in payload.get('charges', []):
            product_id = int(c.get('product_id') or 0)
            if not product_id:
                product_id = self._get_default_product_id()
            if product_id:
                charge_vals_list.append({
                    'transport_order_id': order.id,
                    'product_id': product_id,
                    'price_type': c.get('price_type') or 'price_per_order',
                    'quantity': float(c.get('quantity') or 0.0),
                    'price_per_unit': float(c.get('price_per_unit') or 0.0),
                    'manually_added': bool(c.get('manually_added', True)),
                })
        if charge_vals_list:
            self.env['transport.order.line'].create(charge_vals_list)
            
        if payload.get('planning_type'):
            order.generate_assignments()
            
        if order.driver_notes and order.road_assignment_ids:
            order.road_assignment_ids.write({'driver_notes': order.driver_notes})
            
        return order.id

    @api.model
    def preview_booking(self, payload):
        self.env.cr.execute('SAVEPOINT booking_preview')
        try:
            order_vals = self._prepare_booking_order_vals(payload)
            order = self.create(order_vals)
            
            goods_vals_list = []
            for g in payload.get('goods_lines', []):
                goods_vals_list.append(self._prepare_booking_goods_line_vals(g, order))
            if goods_vals_list:
                self.env['goods.line'].create(goods_vals_list)
                
            self.env.flush_all()
            order._compute_total_gross_weight()
            order._compute_total_billable_weight()
            order._compute_total_volume()
            order._compute_total_ldm()
            
            order.generate_transport_order_lines()
            order.generate_assignments()
            
            totals = {
                'total_gross_weight': order.total_gross_weight,
                'total_billable_weight': order.total_billable_weight,
                'total_volume': order.total_volume,
                'total_ldm': order.total_ldm,
            }
            
            charges = []
            for line in order.transport_order_line_ids_parents_only:
                charges.append({
                    'product_id': line.product_id.id,
                    'product_name': line.product_id.name,
                    'price_type': line.price_type,
                    'quantity': line.quantity,
                    'price_per_unit': line.price_per_unit,
                    'price': line.price,
                    'manually_added': line.manually_added,
                })
                
            legs = []
            for idx, leg in enumerate(order.road_assignment_ids):
                legs.append({
                    'sequence': idx + 1,
                    'type': leg.transport_type_id.code if leg.transport_type_id else 'DI',
                    'from': leg.sender_city or leg.sender_name or '',
                    'to': leg.receiver_city or leg.receiver_name or '',
                    'cost': leg.total_order_cost or 0.0,
                    'carrier': leg.transport_carrier_id.name if leg.transport_carrier_id else 'Own fleet',
                })
                
            margin = {
                'revenue': order.total_order_revenue,
                'cost': order.total_order_cost,
                'margin': order.margin,
                'margin_percent': (order.margin_percent * 100.0) if order.margin_percent else 0.0,
            }
            
            return {
                'success': True,
                'totals': totals,
                'charges': charges,
                'legs': legs,
                'margin': margin,
            }
        except Exception as e:
            self.env.cr.execute('ROLLBACK TO SAVEPOINT booking_preview')
            _logger.exception("Error in preview_booking")
            return {
                'success': False,
                'error': str(e),
            }
        finally:
            try:
                self.env.cr.execute('ROLLBACK TO SAVEPOINT booking_preview')
            except Exception:
                pass



from datetime import timedelta
from markupsafe import Markup, escape
from odoo import api, fields, models, _, Command
from odoo.exceptions import ValidationError, UserError
from odoo.tools import config
import json
import requests
import logging
_logger = logging.getLogger(__name__)


def _get_routing_api_token():
    """Read routing API credentials from odoo.conf and return a Basic auth header.

    Expects ``tms_routing_api_token = username:password`` in odoo.conf.
    Returns ``Basic <base64>`` suitable for the Authorization header.
    """
    token = config.get('tms_routing_api_token', '')
    if not token:
        raise UserError(_(
            "The routing API token is not configured. "
            "Add 'tms_routing_api_token = username:password' to your odoo.conf file."
        ))
    import base64
    encoded = base64.b64encode(token.encode('utf-8')).decode('utf-8')
    return f'Basic {encoded}'

class RoadAssignment(models.Model):
    _name = 'road.assignment'
    _inherit = ['mail.thread', 'soft.delete.mixin', 'tms.custom.field.mixin', 'gdpr.anonymize.mixin']
    _description = 'Road transport assignment'
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
        # Proof of service
        'pickup_signee_name': 'anonymize_char', 'pickup_signature': 'clear_binary',
        'delivery_signee_name': 'anonymize_char', 'delivery_signature': 'clear_binary',
    }

    # Tier 1: Locked after draft — require cancellation to change
    _LOCKED_FIELDS = {
        'transport_carrier_id', 'transport_type_id', 'transport_line_id',
    }

    # Tier 2: Editable after draft but changes are logged as amendments
    _CONTROLLED_FIELDS = {
        'sender_address_id', 'sender_name', 'sender_street', 'sender_street_2',
        'sender_city', 'sender_state_id', 'sender_zip', 'sender_country_id',
        'sender_latitude', 'sender_longitude', 'sender_phone', 'sender_mobile', 'sender_email',
        'sender_contact_person', 'sender_contact_phone', 'sender_access_instructions',
        'receiver_address_id', 'receiver_name', 'receiver_street', 'receiver_street_2',
        'receiver_city', 'receiver_state_id', 'receiver_zip', 'receiver_country_id',
        'receiver_latitude', 'receiver_longitude', 'receiver_phone', 'receiver_mobile', 'receiver_email',
        'receiver_contact_person', 'receiver_contact_phone', 'receiver_access_instructions',
        'planned_pick_up_time', 'planned_delivery_time',
        'pick_up_time_window', 'pick_up_time_from', 'pick_up_time_to',
        'delivery_time_window', 'delivery_time_from', 'delivery_time_to',
        'requirement_ids',
        'require_pickup_signature', 'require_pickup_photo',
        'require_pickup_assignment_scanning', 'require_pickup_goods_scanning',
        'require_delivery_signature', 'require_delivery_photo',
        'require_delivery_assignment_scanning', 'require_delivery_goods_scanning',
        'transport_load_id',
        'estimated_pickup_duration', 'estimated_delivery_duration',
    }

    # Tier 3: Changes that trigger push notification to driver on started loads
    _PUSH_NOTIFY_FIELDS = {
        'state', 'planned_pick_up_time', 'planned_delivery_time',
        'sender_name', 'sender_street', 'sender_city',
        'receiver_name', 'receiver_street', 'receiver_city',
    }

    number = fields.Char(string="Number", required=True, tracking=True, default="New", copy=False)
    last_updated_at = fields.Datetime(string="Last Updated", index=True, help="Deep update timestamp")

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
    custom_select_1 = fields.Many2one('custom.transport.options.1', string="Custom Select 1", tracking=True, domain="[('model_key', 'in', ['RA', 'TORA'])]")
    custom_select_2 = fields.Many2one('custom.transport.options.2', string="Custom Select 2", tracking=True, domain="[('model_key', 'in', ['RA', 'TORA'])]")
    custom_select_3 = fields.Many2one('custom.transport.options.3', string="Custom Select 3", tracking=True, domain="[('model_key', 'in', ['RA', 'TORA'])]")
    custom_select_4 = fields.Many2one('custom.transport.options.4', string="Custom Select 4", tracking=True, domain="[('model_key', 'in', ['RA', 'TORA'])]")
    custom_select_5 = fields.Many2one('custom.transport.options.5', string="Custom Select 5", tracking=True, domain="[('model_key', 'in', ['RA', 'TORA'])]")

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

    transport_order_id = fields.Many2one('transport.order', string="Transport order")
    priority = fields.Selection(related='transport_order_id.priority', store=True, readonly=True)
    waybill_number = fields.Char(related='transport_order_id.waybill_number', string='Waybill Number', store=True)
    pick_up_details = fields.Text(string='Pick up details', tracking=True)
    delivery_details = fields.Text(string='Delivery details', tracking=True)
    driver_notes = fields.Text(string='Internal — Driver Notes', tracking=True)
    goods_line_ids = fields.One2many(related='transport_order_id.goods_line_ids', string="Goods Lines", readonly=True)
    total_billable_weight = fields.Float(related='transport_order_id.total_billable_weight', string="Total Billable Weight", store=True)
    total_gross_weight = fields.Float(related='transport_order_id.total_gross_weight', string="Total Gross Weight", store=True)
    total_volume = fields.Float(related='transport_order_id.total_volume', string="Total Volume", store=True)
    total_ldm = fields.Float(related='transport_order_id.total_ldm', string="Total LDM", store=True)
    goods_description = fields.Char(related='transport_order_id.goods_description', string="Goods", store=True)
    declared_goods_value = fields.Monetary(related='transport_order_id.declared_goods_value', string="Declared Goods Value", readonly=True, currency_field='declared_goods_value_currency_id')
    declared_goods_value_currency_id = fields.Many2one(related='transport_order_id.declared_goods_value_currency_id', string="Declared Goods Value Currency", readonly=True)

    # ── Goods profile visibility flags (for inline list column_invisible) ──
    goods_profile_id = fields.Many2one(related='transport_order_id.goods_profile_id', store=False)
    gp_show_package_id = fields.Boolean(related='transport_order_id.gp_show_package_id', store=False)
    gp_show_goods_label = fields.Boolean(related='transport_order_id.gp_show_goods_label', store=False)
    gp_show_description = fields.Boolean(related='transport_order_id.gp_show_description', store=False)
    gp_show_dimensions = fields.Boolean(related='transport_order_id.gp_show_dimensions', store=False)
    gp_show_volume = fields.Boolean(related='transport_order_id.gp_show_volume', store=False)
    gp_show_ldm = fields.Boolean(related='transport_order_id.gp_show_ldm', store=False)
    gp_show_gross_weight = fields.Boolean(related='transport_order_id.gp_show_gross_weight', store=False)
    gp_show_volumetric_weight = fields.Boolean(related='transport_order_id.gp_show_volumetric_weight', store=False)
    gp_show_billable_weight = fields.Boolean(related='transport_order_id.gp_show_billable_weight', store=False)
    gp_show_adr = fields.Boolean(related='transport_order_id.gp_show_adr', store=False)
    gp_show_container = fields.Boolean(related='transport_order_id.gp_show_container', store=False)
    gp_show_temperature = fields.Boolean(related='transport_order_id.gp_show_temperature', store=False)
    gp_show_material_type = fields.Boolean(related='transport_order_id.gp_show_material_type', store=False)

    bulky_goods = fields.Boolean(related='transport_order_id.bulky_goods', store=True, string="Bulky Goods")
    has_dangerous_goods = fields.Boolean(related='transport_order_id.has_dangerous_goods', store=True, string="Has Dangerous Goods")

    goods_summary_html = fields.Html(
        string="Goods Summary",
        compute='_compute_goods_summary_html',
        sanitize=False,
    )
    transport_carrier = fields.Char(compute='_compute_transport_carrier', store=False, string="Carrier")
    transport_carrier_id = fields.Many2one('res.partner', string="Transport carrier", tracking=True, domain="[('id', 'in', transport_carrier_ids)]")
    carrier_id = fields.Many2one(
        'transport.carrier', string="Carrier Record",
        compute='_compute_carrier_id', inverse='_inverse_carrier_id',
        domain="[('company_ids', 'in', company_id)]",
    )
    transport_type_id = fields.Many2one('transport.type', string="Transport type", tracking=True)

    transport_line_id = fields.Many2one('transport.line', string="Transport line", tracking=True)
    type = fields.Char(compute='_compute_type', string="Type")
    planned_pick_up_time = fields.Datetime(string='Planned pick up time', tracking=True)
    planned_delivery_time = fields.Datetime(string='Planned delivery time', tracking=True)

    # ── Week flags (for quick search filters) ──
    is_this_week = fields.Boolean(string="Is This Week", compute='_compute_week_flags', store=True)
    is_next_week = fields.Boolean(string="Is Next Week", compute='_compute_week_flags', store=True)
    is_previous_week = fields.Boolean(string="Is Previous Week", compute='_compute_week_flags', store=True)

    @api.depends('planned_pick_up_time')
    def _compute_week_flags(self):
        today = fields.Date.context_today(self)
        start_of_this_week = today - timedelta(days=today.weekday())
        end_of_this_week = start_of_this_week + timedelta(days=6)
        start_of_next_week = start_of_this_week + timedelta(days=7)
        end_of_next_week = start_of_next_week + timedelta(days=6)
        start_of_prev_week = start_of_this_week - timedelta(days=7)
        end_of_prev_week = start_of_this_week - timedelta(days=1)
        for record in self:
            record.is_this_week = False
            record.is_next_week = False
            record.is_previous_week = False
            if record.planned_pick_up_time:
                pickup_date = record.planned_pick_up_time.date()
                if start_of_this_week <= pickup_date <= end_of_this_week:
                    record.is_this_week = True
                elif start_of_next_week <= pickup_date <= end_of_next_week:
                    record.is_next_week = True
                elif start_of_prev_week <= pickup_date <= end_of_prev_week:
                    record.is_previous_week = True

    # ── Carrier type (for search filters) ──
    carrier_type = fields.Selection(
        [('internal', 'Internal'),
         ('external_planned', 'External - Planned'),
         ('external_unplanned', 'External - Self-managed')],
        string="Carrier Type",
        compute='_compute_carrier_type', store=True,
    )

    carrier_allow_recall = fields.Boolean(
        string="Carrier Allows Recall",
        compute='_compute_carrier_allow_recall',
    )

    # ── US carrier identifiers (bridged from transport.carrier for BOL/EDI/search) ──
    carrier_scac = fields.Char(
        string="Carrier SCAC", compute='_compute_carrier_us_identifiers', store=True,
        help="SCAC of the assigned carrier. Bridged from the carrier record for Bill of Lading and X12 EDI.")
    carrier_mc_number = fields.Char(
        string="Carrier MC Number", compute='_compute_carrier_us_identifiers', store=True)
    carrier_usdot_number = fields.Char(
        string="Carrier USDOT Number", compute='_compute_carrier_us_identifiers', store=True)

    # ── US Bill of Lading (per carrier leg) ──
    bol_number = fields.Char(
        string="BOL Number", tracking=True,
        help="Bill of Lading number for this carrier leg. Falls back to the assignment number on the printout when empty.")
    pro_number = fields.Char(
        string="PRO Number", tracking=True,
        help="Carrier's progressive (PRO) tracking number for this leg.")
    freight_charge_terms = fields.Selection([
        ('prepaid', 'Prepaid'),
        ('collect', 'Collect'),
        ('third_party', 'Third Party'),
    ], string="Freight Charge Terms", default='prepaid', tracking=True,
        help="Who pays the freight charges on this leg's Bill of Lading.")
    bill_to_partner_id = fields.Many2one(
        'res.partner', string="Bill To (3rd Party)", tracking=True,
        help="Third-party payer of freight charges. Shown on the BOL when terms are 'Third Party'.")
    bol_special_instructions = fields.Text(
        string="BOL Special Instructions", tracking=True,
        help="Free-text instructions printed in the Special Instructions box of the Bill of Lading.")

    def action_print_bol(self):
        """Print the US Bill of Lading for this carrier leg."""
        return self.env.ref('transport_management.action_bill_of_lading').report_action(self)

    @api.depends('transport_carrier_id')
    def _compute_carrier_us_identifiers(self):
        Carrier = self.env['transport.carrier'].sudo()
        partner_ids = self.mapped('transport_carrier_id').ids
        carriers = Carrier.search([('partner_id', 'in', partner_ids)]) if partner_ids else Carrier
        partner_map = {c.partner_id.id: c for c in carriers}
        for rec in self:
            carrier = partner_map.get(rec.transport_carrier_id.id)
            rec.carrier_scac = carrier.scac_code if carrier else False
            rec.carrier_mc_number = carrier.mc_number if carrier else False
            rec.carrier_usdot_number = carrier.usdot_number if carrier else False

    @api.depends('transport_carrier_id')
    def _compute_carrier_type(self):
        Carrier = self.env['transport.carrier'].sudo()
        # Batch lookup: find all carriers for the partner IDs in one query
        partner_ids = self.mapped('transport_carrier_id').ids
        carriers = Carrier.search([('partner_id', 'in', partner_ids)]) if partner_ids else Carrier
        partner_to_type = {c.partner_id.id: c.carrier_type for c in carriers}
        for rec in self:
            rec.carrier_type = partner_to_type.get(rec.transport_carrier_id.id, False)

    @api.depends('transport_carrier_id')
    def _compute_carrier_allow_recall(self):
        Carrier = self.env['transport.carrier'].sudo()
        partner_ids = self.mapped('transport_carrier_id').ids
        carriers = Carrier.search([('partner_id', 'in', partner_ids)]) if partner_ids else Carrier
        partner_map = {c.partner_id.id: c for c in carriers}
        for rec in self:
            carrier = partner_map.get(rec.transport_carrier_id.id)
            rec.carrier_allow_recall = (
                carrier.allow_recall if carrier else False
            )

    # ── Time Window Fields (copied from transport.order at generation, editable) ──
    pick_up_time_window = fields.Boolean(string='Pick up time window', tracking=True, default=False)
    pick_up_time_from = fields.Datetime(string='Pick up time from', tracking=True)
    pick_up_time_to = fields.Datetime(string='Pick up time to', tracking=True)
    delivery_time_window = fields.Boolean(string='Delivery time window', tracking=True, default=False)
    delivery_time_from = fields.Datetime(string='Delivery time from', tracking=True)
    delivery_time_to = fields.Datetime(string='Delivery time to', tracking=True)

    estimated_pickup_duration = fields.Integer(string='Estimated Pickup Duration (min)', default=0, tracking=True)
    estimated_delivery_duration = fields.Integer(string='Estimated Delivery Duration (min)', default=0, tracking=True)

    # ── Actual Times (set from events, readonly) ──
    actual_pickup_time = fields.Datetime(string='Actual Pickup Time', readonly=True, tracking=True,
        help="Set automatically from event code 10 (Picked up at sender).")
    actual_delivery_time = fields.Datetime(string='Actual Delivery Time', readonly=True, tracking=True,
        help="Set automatically from event code 70 (Delivered to receiver).")

    # ── Work Shift Times ──
    work_start_time = fields.Datetime(string='Work Shift Start', readonly=True, tracking=True,
        help="Set automatically from event code 80 (Work shift started). "
             "Marks when the driver began working on this assignment (e.g. "
             "leaving the terminal), independent of pickup/delivery times.")
    work_end_time = fields.Datetime(string='Work Shift End', readonly=True, tracking=True,
        help="Set automatically from event code 81 (Work shift ended). "
             "Marks when the driver finished working on this assignment "
             "(e.g. returning to the terminal).")
    work_duration_hours = fields.Float(string='Work Duration (h)',
        compute='_compute_work_duration_hours',
        inverse='_inverse_work_duration_hours',
        store=True, readonly=False, digits=(16, 2),
        help="Auto-computed from work_start_time and work_end_time. May be "
             "edited manually by the office (e.g. when the driver forgot to "
             "stamp). Manual edits stick until start/end times change again, "
             "at which point auto-compute takes over.")

    # ── Time Window Deviation Indicators ──
    pick_up_time_window_deviated = fields.Boolean(string='Pickup Window Deviated',
        compute='_compute_time_window_deviation', store=True,
        help="True when the pickup time window on this assignment differs from the transport order.")
    delivery_time_window_deviated = fields.Boolean(string='Delivery Window Deviated',
        compute='_compute_time_window_deviation', store=True,
        help="True when the delivery time window on this assignment differs from the transport order.")

    # ── Helper field for view conditional visibility ──
    transport_type_code = fields.Char(related='transport_type_id.code', string="Transport Type Code", store=False)

    sender_address = fields.Char(string="Sender", compute='_compute_sender_address')
    sender_address_id = fields.Many2one('res.partner', string='Sender address', domain="[('id', 'in', assignment_address_ids)]", tracking=True)
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
    sender_contact_person = fields.Char(string='Sender Contact Person', tracking=True, help="Specific contact person at the pickup location for this assignment.")
    sender_contact_phone = fields.Char(string='Sender Contact Phone', tracking=True, help="Phone number for the pickup contact person.")
    sender_access_instructions = fields.Text(string='Sender Access Instructions', tracking=True, help="Specific instructions for accessing the pickup location.")
    receiver_address = fields.Char(string='Receiver',  compute='_compute_receiver_address')
    receiver_address_id = fields.Many2one('res.partner', string='Receiver address', domain="[('id', 'in', assignment_address_ids)]", tracking=True, required=False)
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
    receiver_contact_person = fields.Char(string='Receiver Contact Person', tracking=True, help="Specific contact person at the delivery location for this assignment.")
    receiver_contact_phone = fields.Char(string='Receiver Contact Phone', tracking=True, help="Phone number for the delivery contact person.")
    receiver_access_instructions = fields.Text(string='Receiver Access Instructions', tracking=True, help="Specific instructions for accessing the delivery location.")
    note = fields.Text(string="Note", tracking=True)
    manual_distance = fields.Boolean(string='Manual distance', tracking=True, default=False, store=True)
    driving_distance_km = fields.Float(string='Driving distance (km)', tracking=True, store=True)
    driving_distance_miles = fields.Float(string='Driving distance (miles)', tracking=True, store=True)
    distance_unit = fields.Selection([('km', 'Kilometers'),('miles', 'Miles')], string="Distance Unit", default=lambda self: self.env.user.distance_unit or 'km', required=True, store=False)
    state = fields.Selection([
        ('draft', 'Draft'),
        ('confirmed', 'Confirmed'),
        ('planned', 'Planned'),
        ('started', 'Started'),
        ('done', 'Done'),
        ('error', 'Error'),
        ('closed', 'Closed'),
        ('cancelled', 'Cancelled'),
    ], string="State", tracking=True, default="draft")
    closed_date = fields.Datetime(string="Closed Date", readonly=True, tracking=True)
    pre_close_state = fields.Selection([
        ('done', 'Done'), ('error', 'Error'),
    ], string="State Before Close", readonly=True,
       help="The state before the assignment was closed, used for reopening.")
    cancel_reason = fields.Text(string="Cancellation Reason", tracking=True, readonly=True)
    # ── Documents ──
    document_ids = fields.One2many('transport.document', 'road_assignment_id', string='Documents')
    document_count = fields.Integer(compute='_compute_document_count', string='Document Count')

    # ── Deviations ──
    deviation_ids = fields.One2many(
        'road.assignment.deviation', 'assignment_id',
        string='Deviations',
    )
    pick_up_deviation_ids = fields.One2many(
        'road.assignment.deviation', 'assignment_id',
        string='Pick-up Deviations',
        domain=[('phase', '=', 'pickup')],
    )
    delivery_deviation_ids = fields.One2many(
        'road.assignment.deviation', 'assignment_id',
        string='Delivery Deviations',
        domain=[('phase', '=', 'delivery')],
    )

    has_pick_up_deviation = fields.Boolean(
        string="Has Pick-up Deviation",
        compute='_compute_deviation_flags', store=True,
    )
    has_delivery_deviation = fields.Boolean(
        string="Has Delivery Deviation",
        compute='_compute_deviation_flags', store=True,
    )
    has_deviation = fields.Boolean(
        string="Has Deviation",
        compute='_compute_deviation_flags', store=True,
    )
    deviation_badge_html = fields.Html(
        string="Deviations (Badge)",
        compute='_compute_deviation_badge_html',
        sanitize=False,
    )
    deviation_count = fields.Integer(
        string="Deviation Count",
        compute='_compute_deviation_flags', store=True,
    )
    deviation_root_cause = fields.Selection([
        ('traffic', 'Traffic'),
        ('customer_not_available', 'Customer Not Available'),
        ('wrong_address', 'Wrong Address'),
        ('damaged_goods', 'Damaged Goods'),
        ('missing_goods', 'Missing Goods'),
        ('vehicle_breakdown', 'Vehicle Breakdown'),
        ('weather', 'Weather'),
        ('other', 'Other'),
    ], string='Deviation Root Cause', compute='_compute_deviation_aggregates', store=True)

    deviation_severity = fields.Selection([
        ('minor', 'Minor'),
        ('major', 'Major'),
        ('critical', 'Critical'),
    ], string='Deviation Severity', compute='_compute_deviation_aggregates', store=True)

    event_count = fields.Integer(
        string="Event Count",
        compute='_compute_event_count',
    )

    @api.depends('event_ids')
    def _compute_event_count(self):
        for rec in self:
            rec.event_count = len(rec.event_ids)
    # Legacy — no longer written to; kept for analytics/reports backward compat
    pick_up_deviation_description = fields.Text(string="Pick-up Deviation Description")
    delivery_deviation_description = fields.Text(string="Delivery Deviation Description")

    @api.depends('document_ids')
    def _compute_document_count(self):
        for rec in self:
            rec.document_count = len(rec.document_ids)

    @api.depends('deviation_ids', 'deviation_ids.phase', 'deviation_ids.event_type_id', 'deviation_ids.severity', 'deviation_ids.root_cause')
    def _compute_deviation_flags(self):
        for rec in self:
            pu = rec.deviation_ids.filtered(lambda d: d.phase == 'pickup')
            dl = rec.deviation_ids.filtered(lambda d: d.phase == 'delivery')
            rec.has_pick_up_deviation = bool(pu)
            rec.has_delivery_deviation = bool(dl)
            rec.has_deviation = bool(pu) or bool(dl)
            rec.deviation_count = len(rec.deviation_ids)

    @api.depends('deviation_ids.root_cause', 'deviation_ids.severity')
    def _compute_deviation_aggregates(self):
        for rec in self:
            deviations = rec.deviation_ids
            if not deviations:
                rec.deviation_root_cause = False
                rec.deviation_severity = False
                continue

            # Pick the "worst" deviation: critical > major > minor.
            # If multiple of same severity, biggest ID/latest time.
            def severity_rank(sev):
                return {'critical': 1, 'major': 2, 'minor': 3}.get(sev, 4)

            sorted_deviations = deviations.sorted(
                key=lambda d: (severity_rank(d.severity), -(d.id or 0)),
                reverse=False
            )
            main_deviation = sorted_deviations[0]
            rec.deviation_severity = main_deviation.severity
            rec.deviation_root_cause = main_deviation.root_cause

    @api.depends('deviation_ids', 'deviation_ids.phase', 'deviation_ids.event_type_id')
    def _compute_deviation_badge_html(self):
        for rec in self:
            # Build HTML badges
            badges = []
            for dev in rec.deviation_ids:
                phase_label = _("Pick-up") if dev.phase == 'pickup' else _("Delivery")
                type_name = dev.event_type_id.name or _("Deviation")
                badges.append(
                    '<span class="badge text-bg-danger me-1">'
                    '<i class="fa fa-exclamation-triangle me-1"></i>'
                    '%s — %s</span>' % (type_name, phase_label)
                )
            rec.deviation_badge_html = ''.join(badges) if badges else False

    @api.depends('total_gross_weight', 'total_billable_weight', 'total_volume',
                 'total_ldm', 'goods_description')
    def _compute_goods_summary_html(self):
        def _fmt(val, unit):
            """Format a number: drop decimals if .0, otherwise 2 decimals."""
            if not val:
                return None
            return f"{val:,.0f} {unit}" if val == int(val) else f"{val:,.2f} {unit}"

        for rec in self:
            parts = []
            gross = _fmt(rec.total_gross_weight, 'kg')
            if gross:
                parts.append(f'<i class="fa fa-balance-scale" style="width:14px;text-align:center;"></i> {escape(gross)}')
            billable = _fmt(rec.total_billable_weight, 'kg')
            if billable:
                parts.append(f'<i class="fa fa-calculator" style="width:14px;text-align:center;"></i> {escape(billable)}')
            vol = _fmt(rec.total_volume, 'm³')
            if vol:
                parts.append(f'<i class="fa fa-cube" style="width:14px;text-align:center;"></i> {escape(vol)}')
            ldm = _fmt(rec.total_ldm, 'ldm')
            if ldm:
                parts.append(f'<i class="fa fa-arrows-h" style="width:14px;text-align:center;"></i> {escape(ldm)}')

            if not parts:
                rec.goods_summary_html = False
                continue

            sep = ' <span style="color:#adb5bd;margin:0 6px;">·</span> '
            html = (
                f'<div style="display:flex;align-items:center;gap:6px;'
                f'font-size:12px;font-weight:500;color:#6c757d;padding:8px 0;">'
                f'{sep.join(parts)}'
                f'</div>'
            )
            rec.goods_summary_html = Markup(html)

    @api.depends(
        'pick_up_time_window', 'pick_up_time_from', 'pick_up_time_to',
        'delivery_time_window', 'delivery_time_from', 'delivery_time_to',
        'transport_order_id.pick_up_time_window',
        'transport_order_id.pick_up_time_from',
        'transport_order_id.pick_up_time_to',
        'transport_order_id.delivery_time_window',
        'transport_order_id.delivery_time_from',
        'transport_order_id.delivery_time_to',
        'transport_type_id',
    )
    def _compute_time_window_deviation(self):
        for rec in self:
            rec.pick_up_time_window_deviated = False
            rec.delivery_time_window_deviated = False

            if not rec.transport_order_id or not rec.transport_type_id:
                continue

            code = rec.transport_type_id.code

            # Pickup deviation check (DI and PU have pickup windows)
            if code in ('DI', 'PU'):
                order = rec.transport_order_id
                if (rec.pick_up_time_window != order.pick_up_time_window
                        or rec.pick_up_time_from != order.pick_up_time_from
                        or rec.pick_up_time_to != order.pick_up_time_to):
                    rec.pick_up_time_window_deviated = True

            # Delivery deviation check (DI and DE have delivery windows)
            if code in ('DI', 'DE'):
                order = rec.transport_order_id
                if (rec.delivery_time_window != order.delivery_time_window
                        or rec.delivery_time_from != order.delivery_time_from
                        or rec.delivery_time_to != order.delivery_time_to):
                    rec.delivery_time_window_deviated = True

    @api.depends('odometer_start', 'odometer_end')
    def _compute_odometer_distance(self):
        for rec in self:
            if rec.odometer_start and rec.odometer_end and rec.odometer_end >= rec.odometer_start:
                rec.odometer_distance = rec.odometer_end - rec.odometer_start
            else:
                rec.odometer_distance = 0

    @api.depends('work_start_time', 'work_end_time')
    def _compute_work_duration_hours(self):
        for rec in self:
            if rec.work_start_time and rec.work_end_time and rec.work_end_time > rec.work_start_time:
                delta = rec.work_end_time - rec.work_start_time
                rec.work_duration_hours = delta.total_seconds() / 3600.0
            # Else: leave the value alone — preserves a manually entered
            # duration when one of the timestamps is missing.

    def _inverse_work_duration_hours(self):
        """Allow manual edits of work_duration_hours by office. The value
        is stored as-is; no propagation back to start/end times."""
        return

    event_ids = fields.One2many(
        'assignment.event',
        'transport_assignment_id',
        string='Assignment Events',
        copy=False
    )
    duplicate_event_count = fields.Integer(
        string='Duplicate Events',
        compute='_compute_duplicate_event_count',
    )
    assignment_address_ids = fields.Many2many('res.partner', compute='_compute_assignment_address_ids')
    transport_carrier_ids = fields.Many2many('res.partner', compute='_compute_transport_carrier_ids')
    transport_load_id = fields.Many2one('transport.load', string='Transport Load')
    transport_load_summary = fields.Char(string="Load Info", compute='_compute_transport_load_summary')

    @api.depends('transport_load_id', 'transport_load_id.vehicle_id', 'transport_load_id.driver_id')
    def _compute_transport_load_summary(self):
        for rec in self:
            if rec.transport_load_id:
                vehicle = rec.transport_load_id.vehicle_id.display_name or 'No Vehicle'
                driver = rec.transport_load_id.driver_id.display_name or 'No Driver'
                rec.transport_load_summary = f"{vehicle} | {driver}"
            else:
                rec.transport_load_summary = False
    sender_address_sequence = fields.Integer(string="Sender Stop Sequence", default=0)
    receiver_address_sequence = fields.Integer(string="Receiver Stop Sequence", default=0)

    company_id = fields.Many2one(
        'res.company',
        string='Company',
        related='transport_order_id.company_id',
        store=True,
        readonly=True
    )
    active = fields.Boolean('Active', default=True, tracking=True)
    road_assignment_line_ids = fields.One2many(
        'road.assignment.line', 
        'road_assignment_id', 
        string="Assignment Cost Lines",
        domain=[('parent_line_id', '=', False)]
    )
    system_currency_id = fields.Many2one(
        'res.currency',
        string="System Currency",
        compute='_compute_cost_totals',
        store=True
    )
    total_system_cost = fields.Monetary(
        string="Total System Cost",
        compute='_compute_cost_totals',
        store=True,
        currency_field='system_currency_id'
    )
    assignment_currency_id = fields.Many2one(
        'res.currency',
        string="Assignment Currency",
        default=lambda self: self.env.company.currency_id,
        required=True
    )
    total_assignment_cost = fields.Monetary(
        string="Total Assignment Cost",
        compute='_compute_cost_totals',
        store=True,
        currency_field='assignment_currency_id'
    )

    # ── Cost in Order Currency (for clear comparison in Transport Order) ──
    order_currency_id = fields.Many2one(
        related='transport_order_id.company_id.currency_id',
        string="Order Currency",
        readonly=True
    )
    total_order_cost = fields.Monetary(
        string="Cost (Order Currency)",
        compute='_compute_cost_totals',
        store=True,
        currency_field='order_currency_id',
        help="Total cost converted to the Transport Order's currency."
    )

    purchase_order_id = fields.Many2one(
        'purchase.order',
        string="Purchase Order",
        readonly=True,
        tracking=True,
        help="The Purchase Order created for settling this Road Assignment."
    )
    vendor_bill_id = fields.Many2one(
        'account.move',
        string="Vendor Bill",
        compute='_compute_vendor_bill_id',
        store=True,
        readonly=True,
    )
    cost_state = fields.Selection(
        [('unpriced', 'Unpriced'),
         ('priced', 'Priced'),
         ('approved', 'Approved'),
         ('po_created', 'PO Created'),
         ('billed', 'Billed')],
        string="Cost State",
        compute='_compute_cost_state',
        store=True,
    )
    can_settle_commercial = fields.Boolean(
        compute='_compute_can_settle_commercial',
    )

    costs_approved = fields.Boolean(
        string="Costs Approved", default=False, tracking=True,
        help="Indicates that the cost lines have been reviewed and approved for settlement.",
    )
    is_self_invoice = fields.Boolean(
        related='transport_carrier_id.is_self_invoice',
        readonly=True,
    )
    carrier_reference = fields.Char(string="Carrier Reference", tracking=True)

    # CO2 emissions
    co2_emissions_kg = fields.Float(
        string='CO\u2082 Emissions (kg)',
        compute='_compute_co2_emissions',
        store=True,
        help="Estimated CO\u2082 emissions: distance / 100 * fuel consumption * emission factor",
    )

    @api.depends('driving_distance_km', 'transport_load_id.vehicle_id.avg_fuel_consumption',
                 'transport_load_id.vehicle_id.co2_emission_factor')
    def _compute_co2_emissions(self):
        for rec in self:
            vehicle = rec.transport_load_id.vehicle_id if rec.transport_load_id else False
            if vehicle and rec.driving_distance_km and vehicle.avg_fuel_consumption and vehicle.co2_emission_factor:
                rec.co2_emissions_kg = (
                    rec.driving_distance_km / 100.0
                    * vehicle.avg_fuel_consumption
                    * vehicle.co2_emission_factor
                )
            else:
                rec.co2_emissions_kg = 0.0

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
            "delivery timestamps). Defaults from "
            "transport_order.require_work_time_reporting."
        ),
    )

    assignment_started_at = fields.Datetime(
        string="Assignment Started At",
        readonly=True,
        tracking=True,
        help="Timestamp when the assignment was started by the driver. "
             "Set automatically when an event matching the transport type's "
             "configured start event is recorded (regardless of which "
             "specific event code that is per type).",
    )
    assignment_completed_at = fields.Datetime(
        string="Assignment Completed At",
        readonly=True,
        tracking=True,
        help="Timestamp when the assignment was completed by the driver. "
             "Set automatically when an event matching the transport type's "
             "configured complete event is recorded.",
    )

    odometer_start = fields.Float(
        string="Odometer Start (km)",
        tracking=True,
        help="Vehicle odometer reading at the start of this assignment's "
             "work shift. Set from event code 80 payload {'odometer': X}.",
    )
    odometer_end = fields.Float(
        string="Odometer End (km)",
        tracking=True,
        help="Vehicle odometer reading at the end of this assignment's "
             "work shift. Set from event code 81 payload {'odometer': X}.",
    )
    odometer_distance = fields.Float(
        string="Odometer Distance (km)",
        compute='_compute_odometer_distance',
        store=True,
    )

    require_material_reporting = fields.Boolean(
        string="Require Material Reporting",
        default=False,
        tracking=True,
        help=(
            "When enabled, the driver is asked to report actual delivered/"
            "picked-up quantity per goods line. Defaults from "
            "transport_order.require_material_reporting."
        ),
    )

    requirement_ids = fields.Many2many('transport.requirement', string="Requirements")
    inherited_requirement_ids = fields.Many2many(
        'transport.requirement', 
        compute='_compute_inherited_requirements', 
        string="Inherited Requirements",
        help="Requirements inherited from the Transport Order"
    )

    @api.depends('transport_order_id', 'transport_order_id.requirement_ids')
    def _compute_inherited_requirements(self):
        for rec in self:
            if rec.transport_order_id:
                rec.inherited_requirement_ids = rec.transport_order_id.requirement_ids
            else:
                rec.inherited_requirement_ids = False

    @api.constrains('requirement_ids')
    def _check_inherited_requirements(self):
        for rec in self:
            if not rec.inherited_requirement_ids:
                continue
            missing = rec.inherited_requirement_ids - rec.requirement_ids
            if missing:
                raise ValidationError(_("You cannot remove requirements inherited from the Transport Order: %s") % ", ".join(missing.mapped('name')))

    @api.constrains('transport_load_id')
    def _check_carrier_match(self):
        for rec in self:
            if not rec.transport_load_id:
                continue
            # Block external unplanned carriers from transport loads
            carrier_rec = rec._get_carrier_record()
            if carrier_rec and carrier_rec.carrier_type == 'external_unplanned':
                raise ValidationError(
                    _("Cannot add assignment '%s' to a transport load — "
                      "carrier '%s' is external unplanned and should not be planned on loads.")
                    % (rec.number, rec.transport_carrier_id.name)
                )
            # Carrier mismatch check
            if rec.transport_load_id.carrier_id and rec.transport_carrier_id:
                if rec.transport_carrier_id != rec.transport_load_id.carrier_id.partner_id:
                    raise ValidationError(
                        _("Carrier mismatch: assignment carrier '%s' does not match load carrier '%s'.")
                        % (rec.transport_carrier_id.name, rec.transport_load_id.carrier_id.name))

    @api.onchange('transport_order_id')
    def _onchange_transport_order_requirements_load(self):
        if self.transport_order_id and self.transport_order_id.requirement_ids:
            current = set(self.requirement_ids.ids)
            new_reqs = set(self.transport_order_id.requirement_ids.ids)
            self.requirement_ids = [Command.set(list(current | new_reqs))]


    # == Pick Up Proof ==
    pickup_photo_ids = fields.Many2many(
        'ir.attachment', 
        'road_assignment_pickup_photo_rel', 
        'assignment_id', 
        'attachment_id', 
        string='Pick Up Photos',
        help="Photos collected during pick up."
    )
    pickup_signature = fields.Binary(string='Pick Up Signature', attachment=True)
    pickup_signee_name = fields.Char(string='Pick Up Signee Name')
    pickup_scan_payload_json = fields.Text(string="Pick Up Scan Metadata")
    pickup_photo = fields.Binary(string='Pick Up Photo Upload', attachment=True)

    # == Delivery Proof ==
    delivery_photo_ids = fields.Many2many(
        'ir.attachment', 
        'road_assignment_delivery_photo_rel', 
        'assignment_id', 
        'attachment_id', 
        string='Delivery Photos',
        help="Photos collected during delivery."
    )
    delivery_signature = fields.Binary(string='Delivery Signature', attachment=True)
    delivery_signee_name = fields.Char(string='Delivery Signee Name')
    delivery_scan_payload_json = fields.Text(string="Delivery Scan Metadata")
    delivery_photo = fields.Binary(string='Delivery Photo Upload', attachment=True)

    # == Reporting Status (computed, not stored for real-time UI updates) ==
    pickup_evidence_satisfied = fields.Boolean(
        string="Pickup Reporting Satisfied",
        compute='_compute_evidence_status',
        help="True when all required pickup reporting has been provided."
    )
    delivery_evidence_satisfied = fields.Boolean(
        string="Delivery Reporting Satisfied",
        compute='_compute_evidence_status',
        help="True when all required delivery reporting has been provided."
    )
    evidence_status = fields.Selection([
        ('not_required', 'Not Required'),
        ('complete', 'Complete'),
        ('partial', 'Partial'),
        ('missing', 'Missing'),
    ], string="Reporting Status", compute='_compute_evidence_status',
        search='_search_evidence_status',
        help="Overall reporting requirements status.")
    evidence_status_badge = fields.Char(
        string="Reporting Badge",
        compute='_compute_evidence_status',
    )
    evidence_badge_class = fields.Char(
        string="Reporting Badge Class",
        compute='_compute_evidence_status',
    )

    @api.depends(
        'require_pickup_signature', 'require_pickup_photo',
        'require_pickup_assignment_scanning', 'require_pickup_goods_scanning',
        'require_delivery_signature', 'require_delivery_photo',
        'require_delivery_assignment_scanning', 'require_delivery_goods_scanning',
        'pickup_signature', 'pickup_photo', 'pickup_photo_ids', 'pickup_scan_payload_json',
        'delivery_signature', 'delivery_photo', 'delivery_photo_ids', 'delivery_scan_payload_json',
    )
    def _compute_evidence_status(self):
        GoodsEvent = self.env['goods.event'].sudo()
        for rec in self:
            # -- Pickup checks --
            pickup_checks = []
            if rec.require_pickup_signature:
                pickup_checks.append(bool(rec.pickup_signature))
            if rec.require_pickup_photo:
                pickup_checks.append(bool(rec.pickup_photo) or bool(rec.pickup_photo_ids))
            if rec.require_pickup_assignment_scanning:
                pickup_checks.append(bool(rec.pickup_scan_payload_json))
            if rec.require_pickup_goods_scanning:
                pickup_checks.append(rec._goods_scanning_satisfied(GoodsEvent, 'pickup'))

            rec.pickup_evidence_satisfied = all(pickup_checks) if pickup_checks else True

            # -- Delivery checks --
            delivery_checks = []
            if rec.require_delivery_signature:
                delivery_checks.append(bool(rec.delivery_signature))
            if rec.require_delivery_photo:
                delivery_checks.append(bool(rec.delivery_photo) or bool(rec.delivery_photo_ids))
            if rec.require_delivery_assignment_scanning:
                delivery_checks.append(bool(rec.delivery_scan_payload_json))
            if rec.require_delivery_goods_scanning:
                delivery_checks.append(rec._goods_scanning_satisfied(GoodsEvent, 'delivery'))

            rec.delivery_evidence_satisfied = all(delivery_checks) if delivery_checks else True

            # -- Overall status --
            all_checks = pickup_checks + delivery_checks
            if not all_checks:
                rec.evidence_status = 'not_required'
                rec.evidence_status_badge = ''
                rec.evidence_badge_class = ''
            elif all(all_checks):
                rec.evidence_status = 'complete'
                rec.evidence_status_badge = 'OK'
                rec.evidence_badge_class = 'text-bg-success'
            elif any(all_checks):
                rec.evidence_status = 'partial'
                rec.evidence_status_badge = '!'
                rec.evidence_badge_class = 'text-bg-warning'
            else:
                rec.evidence_status = 'missing'
                rec.evidence_status_badge = 'X'
                rec.evidence_badge_class = 'text-bg-danger'

    def _goods_scanning_satisfied(self, GoodsEvent, phase):
        """Check if all goods lines with a package_id have been scanned for the given phase."""
        self.ensure_one()
        package_ids = [gl.package_id for gl in self.goods_line_ids if gl.package_id]
        if not package_ids:
            return False
        # Resolve event type codes from configuration: event types mapped to
        # PU (pickup) or DE (delivery) assignment types via state_map_ids.
        StateMap = self.env['transport.event.type.state.map'].sudo()
        if phase == 'pickup':
            type_codes = ['PU', 'DI']
        else:
            type_codes = ['DE', 'DI']
        mapped_event_type_ids = StateMap.search([
            ('assignment_type_id.code', 'in', type_codes),
        ]).mapped('event_type_id').ids
        if not mapped_event_type_ids:
            return False
        for pkg_id in package_ids:
            count = GoodsEvent.search_count([
                ('road_assignment_id', '=', self.id),
                ('package_id', '=', pkg_id),
                ('scan_payload_json', '!=', False),
                ('event_type_id', 'in', mapped_event_type_ids),
            ])
            if count == 0:
                return False
        return True

    def _search_evidence_status(self, operator, value):
        """Custom search for the non-stored evidence_status field.
        Builds a domain on the underlying stored requirement + proof fields."""
        if operator not in ('=', '!=', 'in', 'not in'):
            return [('id', '=', False)]

        # Normalize to a set of target statuses
        if operator in ('=', '!='):
            targets = {value}
            negate = operator == '!='
        else:
            targets = set(value) if isinstance(value, (list, tuple)) else {value}
            negate = operator == 'not in'

        # Domain for "not_required": no require_* fields are True
        no_req = [
            ('require_pickup_signature', '=', False),
            ('require_pickup_photo', '=', False),
            ('require_pickup_assignment_scanning', '=', False),
            ('require_pickup_goods_scanning', '=', False),
            ('require_delivery_signature', '=', False),
            ('require_delivery_photo', '=', False),
            ('require_delivery_assignment_scanning', '=', False),
            ('require_delivery_goods_scanning', '=', False),
        ]

        # For 'missing', 'partial', 'complete' we need to search records that
        # have at least one requirement, then compute in Python.
        has_req = ['|', '|', '|', '|', '|', '|', '|',
            ('require_pickup_signature', '=', True),
            ('require_pickup_photo', '=', True),
            ('require_pickup_assignment_scanning', '=', True),
            ('require_pickup_goods_scanning', '=', True),
            ('require_delivery_signature', '=', True),
            ('require_delivery_photo', '=', True),
            ('require_delivery_assignment_scanning', '=', True),
            ('require_delivery_goods_scanning', '=', True),
        ]

        matching_ids = []

        if 'not_required' in targets:
            matching_ids += self.search(no_req).ids

        # For the other statuses, fetch records with requirements and filter
        check_statuses = targets - {'not_required'}
        if check_statuses:
            recs_with_req = self.search(has_req)
            for rec in recs_with_req:
                if rec.evidence_status in check_statuses:
                    matching_ids.append(rec.id)

        if negate:
            return [('id', 'not in', matching_ids)]
        return [('id', 'in', matching_ids)]

    def _update_proof_of_service(self, event):
        """
        Updates the proof fields on the assignment based on the event data.
        Call this when a relevant event (Pick Up or Delivery) is processed.
        """
        self.ensure_one()
        if not event or not event.event_type_id:
            return

        code = event.event_type_id.code

        # Pick Up Event (Code 10)
        if code == 10: 
            vals = {}
            if event.photo_ids:
                vals['pickup_photo_ids'] = [(6, 0, event.photo_ids.ids)]
            if event.signature:
                vals['pickup_signature'] = event.signature
            if event.signee_name:
                vals['pickup_signee_name'] = event.signee_name
            if event.scan_payload_json:
                vals['pickup_scan_payload_json'] = event.scan_payload_json
            if event.photo:
                vals['pickup_photo'] = event.photo
            
            if vals:
                self.write(vals)

        # Delivered Event (Code 70)
        elif code == 70:
            vals = {}
            if event.photo_ids:
                vals['delivery_photo_ids'] = [(6, 0, event.photo_ids.ids)]
            if event.signature:
                vals['delivery_signature'] = event.signature
            if event.signee_name:
                vals['delivery_signee_name'] = event.signee_name
            if event.scan_payload_json:
                vals['delivery_scan_payload_json'] = event.scan_payload_json
            if event.photo:
                vals['delivery_photo'] = event.photo
            
            if vals:
                self.write(vals)

    @staticmethod
    def _parse_event_payload(event):
        """Safely decode assignment_event.scan_payload_json. Returns {} on
        missing/invalid input so handlers can fall through gracefully."""
        import json
        if not event or not event.scan_payload_json:
            return {}
        try:
            data = json.loads(event.scan_payload_json)
        except (ValueError, TypeError):
            return {}
        return data if isinstance(data, dict) else {}

    @staticmethod
    def _extract_hours_from_event(event):
        """Read driver-reported hours from the dedicated reported_hours
        field. Falls back to legacy scan_payload_json {"hours": X} for
        events created before reported_hours existed. Returns None if no
        value is available."""
        if event.reported_hours:
            return float(event.reported_hours)
        # Legacy fallback for events stored before the dedicated field.
        if event.scan_payload_json:
            import json
            try:
                data = json.loads(event.scan_payload_json)
                if isinstance(data, dict) and 'hours' in data:
                    return float(data.get('hours'))
            except (ValueError, TypeError):
                pass
        return None

    def _apply_hour_log(self, event):
        """Code 82: write driver-reported hours to work_duration_hours.
        Hours come from event.reported_hours. Last write wins; uses the
        manual-edit path so the value sticks until work_start_time/
        work_end_time change again."""
        self.ensure_one()
        hours = self._extract_hours_from_event(event)
        if hours is None:
            _logger.warning(
                "Hour log event %s on assignment %s missing reported_hours",
                event.id, self.number,
            )
            return
        if hours < 0:
            return
        self.write({'work_duration_hours': hours})

    def _apply_material_reported(self, event):
        """Code 83: stamp goods.line.reported_at on a goods.line belonging to
        this assignment's transport order. Payload must include
        {goods_line_id}. The actual quantity is read from the goods line's
        existing weight fields — this event only marks the line as reported."""
        self.ensure_one()
        payload = self._parse_event_payload(event)
        try:
            goods_line_id = int(payload.get('goods_line_id') or 0)
        except (TypeError, ValueError):
            _logger.warning(
                "Material reported event %s on assignment %s missing/invalid goods_line_id",
                event.id, self.number,
            )
            return
        if not goods_line_id:
            return
        goods_line = self.env['goods.line'].browse(goods_line_id).exists()
        if not goods_line:
            return
        # Scope check: only stamp goods lines on the same transport order as
        # this assignment.
        order_ids = self.transport_order_id.ids if self.transport_order_id else []
        if goods_line.transport_order_id.id not in order_ids:
            _logger.warning(
                "Material reported event %s tried to stamp goods.line %s outside assignment %s scope",
                event.id, goods_line_id, self.number,
            )
            return
        goods_line.write({'reported_at': event.event_time})

    def _update_actual_times(self, event):
        """
        Updates actual pickup/delivery, work-shift times, and driver-reported
        quantities based on event codes. Called from
        assignment_event._update_assignment_status().
        - Event code 10 (Picked up at sender) → actual_pickup_time
        - Event code 70 (Delivered to receiver) → actual_delivery_time
        - Event code 80 (Work shift started) → work_start_time
        - Event code 81 (Work shift ended) → work_end_time
        - Event code 82 (Hour log) → work_duration_hours (from payload)
        - Event code 83 (Material reported) → goods.line.reported_at
        """
        self.ensure_one()
        if not event or not event.event_type_id:
            return

        code = event.event_type_id.code
        vals = {}

        # Generic start/complete time tracking — matches whatever event
        # codes are configured on this transport type.
        tt = self.transport_type_id
        if tt and tt.assignment_start_event_type_id and code == tt.assignment_start_event_type_id.code:
            vals['assignment_started_at'] = event.event_time
        if tt and tt.assignment_complete_event_type_id and code == tt.assignment_complete_event_type_id.code:
            vals['assignment_completed_at'] = event.event_time

        if code == 10:
            vals['actual_pickup_time'] = event.event_time
        elif code == 70:
            vals['actual_delivery_time'] = event.event_time
        elif code == 80:
            vals['work_start_time'] = event.event_time
            odometer = self._read_payload_odometer(event)
            if odometer is not None:
                vals['odometer_start'] = odometer
        elif code == 81:
            vals['work_end_time'] = event.event_time
            odometer = self._read_payload_odometer(event)
            if odometer is not None:
                vals['odometer_end'] = odometer
        elif code == 82:
            self._apply_hour_log(event)
            return
        elif code == 83:
            self._apply_material_reported(event)
            return

        if vals:
            self.write(vals)

    def _read_payload_odometer(self, event):
        """Extract optional 'odometer' float from an assignment event's
        scan_payload_json. Returns None if missing/invalid."""
        payload = self._parse_event_payload(event)
        raw = payload.get('odometer')
        if raw is None:
            return None
        try:
            value = float(raw)
        except (TypeError, ValueError):
            return None
        return value if value >= 0 else None

    def _recompute_proof_of_service(self):
        """
        Recomputes all proof-of-service fields from the remaining events.
        Called after event deletion to ensure proof fields reflect current state.
        """
        self.ensure_one()
        events = self.env['assignment.event'].search([
            ('transport_assignment_id', '=', self.id),
        ], order='event_time asc')

        # Reset all proof fields and actual times first
        vals = {
            'pickup_photo_ids': [(5, 0, 0)],
            'pickup_signature': False,
            'pickup_signee_name': False,
            'pickup_scan_payload_json': False,
            'pickup_photo': False,
            'delivery_photo_ids': [(5, 0, 0)],
            'delivery_signature': False,
            'delivery_signee_name': False,
            'delivery_scan_payload_json': False,
            'delivery_photo': False,
            'actual_pickup_time': False,
            'actual_delivery_time': False,
            'work_start_time': False,
            'work_end_time': False,
            'work_duration_hours': 0.0,
            'odometer_start': 0.0,
            'odometer_end': 0.0,
            'assignment_started_at': False,
            'assignment_completed_at': False,
        }

        # Re-apply from remaining events (latest wins for scalar fields)
        tt = self.transport_type_id
        start_code = tt.assignment_start_event_type_id.code if tt and tt.assignment_start_event_type_id else None
        complete_code = tt.assignment_complete_event_type_id.code if tt and tt.assignment_complete_event_type_id else None

        for event in events:
            if not event.event_type_id:
                continue
            code = event.event_type_id.code

            # Generic assignment start/complete tracking — earliest start &
            # latest complete win (so deleting some history is safe).
            if start_code is not None and code == start_code:
                if not vals.get('assignment_started_at') or event.event_time < vals['assignment_started_at']:
                    vals['assignment_started_at'] = event.event_time
            if complete_code is not None and code == complete_code:
                if not vals.get('assignment_completed_at') or event.event_time > vals['assignment_completed_at']:
                    vals['assignment_completed_at'] = event.event_time

            if code == 10:
                if event.photo_ids:
                    vals['pickup_photo_ids'] = [(6, 0, event.photo_ids.ids)]
                if event.signature:
                    vals['pickup_signature'] = event.signature
                if event.signee_name:
                    vals['pickup_signee_name'] = event.signee_name
                if event.scan_payload_json:
                    vals['pickup_scan_payload_json'] = event.scan_payload_json
                if event.photo:
                    vals['pickup_photo'] = event.photo
                vals['actual_pickup_time'] = event.event_time

            elif code == 70:
                if event.photo_ids:
                    vals['delivery_photo_ids'] = [(6, 0, event.photo_ids.ids)]
                if event.signature:
                    vals['delivery_signature'] = event.signature
                if event.signee_name:
                    vals['delivery_signee_name'] = event.signee_name
                if event.scan_payload_json:
                    vals['delivery_scan_payload_json'] = event.scan_payload_json
                if event.photo:
                    vals['delivery_photo'] = event.photo
                vals['actual_delivery_time'] = event.event_time

            elif code == 80:
                vals['work_start_time'] = event.event_time
                odo = self._read_payload_odometer(event)
                if odo is not None:
                    vals['odometer_start'] = odo

            elif code == 81:
                vals['work_end_time'] = event.event_time
                odo = self._read_payload_odometer(event)
                if odo is not None:
                    vals['odometer_end'] = odo

            elif code == 82:
                hours = self._extract_hours_from_event(event)
                if hours is not None and hours >= 0:
                    vals['work_duration_hours'] = hours

        self.write(vals)

    @api.onchange('transport_order_id', 'transport_type_id')
    def _onchange_transport_requirements(self):
        if self.transport_order_id and self.transport_type_id:
            # DI = Direct, DE = Delivery
            if self.transport_type_id.code in ['DI', 'DE']:
                self.require_delivery_signature = self.transport_order_id.require_delivery_signature
                self.require_delivery_photo = self.transport_order_id.require_delivery_photo
                self.require_delivery_assignment_scanning = self.transport_order_id.require_delivery_assignment_scanning
                self.require_delivery_goods_scanning = self.transport_order_id.require_delivery_goods_scanning

            if self.transport_type_id.code in ['DI', 'PU']:
                self.require_pickup_signature = self.transport_order_id.require_pickup_signature
                self.require_pickup_photo = self.transport_order_id.require_pickup_photo
                self.require_pickup_assignment_scanning = self.transport_order_id.require_pickup_assignment_scanning
                self.require_pickup_goods_scanning = self.transport_order_id.require_pickup_goods_scanning

            self.require_work_time_reporting = self.transport_order_id.require_work_time_reporting
            self.require_material_reporting = self.transport_order_id.require_material_reporting

    @api.onchange('transport_order_id', 'transport_type_id')
    def _onchange_transport_details(self):
        if not self.transport_order_id or not self.transport_type_id:
            return

        type_code = self.transport_type_id.code

        if type_code == 'PU':
            self.pick_up_details = self.transport_order_id.pick_up_details
            self.delivery_details = False
        
        elif type_code == 'DE':
            self.pick_up_details = False
            self.delivery_details = self.transport_order_id.delivery_details
        
        elif type_code == 'DI':
            self.pick_up_details = self.transport_order_id.pick_up_details
            self.delivery_details = self.transport_order_id.delivery_details
    @api.onchange('carrier_id')
    def _onchange_carrier_id_ref(self):
        """Populate carrier reference when carrier is selected."""
        if self.carrier_id and self.carrier_id.reference:
            self.carrier_reference = self.carrier_id.reference
        else:
            self.carrier_reference = False

    @api.depends('road_assignment_line_ids.price', 'road_assignment_line_ids.child_line_ids.price', 'road_assignment_line_ids.currency_id', 'company_id')
    def _compute_cost_totals(self):
        """
        Calculates the total cost of the assignment in both the assignment's currency
        and the system-wide commercial currency.
        """
        # 1. Get System Currency
        config_param = self.env['ir.config_parameter'].sudo().get_param('transport_management.commercial_currency_id')
        system_currency = None
        if config_param:
            try:
                system_currency = self.env['res.currency'].browse(int(config_param))
            except ValueError:
                system_currency = None
        
        # Fallback to company currency or USD
        if not system_currency:
            system_currency = self.env.company.currency_id or self.env.ref('base.USD', raise_if_not_found=False)

        for rec in self:
            rec.system_currency_id = system_currency.id
            # Default assignment currency to company currency if not set (or you can make this a field user selects)
            rec_currency = rec.assignment_currency_id or rec.company_id.currency_id
            
            # If the assignment is cancelled, we treat the cost as 0.0
            if rec.state == 'cancelled':
                rec.total_system_cost = 0.0
                rec.total_assignment_cost = 0.0
                continue

            total_system = 0.0
            total_assign = 0.0
            
            # Use planned date or today for conversion
            conversion_date = rec.planned_pick_up_time.date() if rec.planned_pick_up_time else fields.Date.context_today(rec)

            for line in rec.road_assignment_line_ids:
                # Use total_price (base + child surcharges like DMT)
                # instead of just the base price.
                line_total = line.total_price
                if line_total and line.currency_id:
                    # Convert to System Currency
                    total_system += line.currency_id._convert(
                        line_total,
                        system_currency,
                        rec.company_id,
                        conversion_date
                    )
                    # Convert to Assignment Currency
                    total_assign += line.currency_id._convert(
                        line_total,
                        rec_currency,
                        rec.company_id,
                        conversion_date
                    )

            rec.total_system_cost = total_system
            rec.total_assignment_cost = total_assign

            # Convert System Cost -> Order Currency
            # We use the system cost as the base truth for inter-currency conversion
            order_cur = rec.transport_order_id.company_id.currency_id
            if order_cur and system_currency and order_cur != system_currency:
                rec.total_order_cost = system_currency._convert(
                        total_system,
                        order_cur,
                        rec.company_id,
                        conversion_date
                    )
            else:
                rec.total_order_cost = total_system
            rec.total_assignment_cost = total_assign

    def action_open_purchase_order(self):
        self.ensure_one()
        if not self.purchase_order_id:
            # If no PO exists, treating this as a request to create one
            return self.action_create_purchase_order()
            
        return {
            'name': _('Purchase Order'),
            'type': 'ir.actions.act_window',
            'res_model': 'purchase.order',
            'view_mode': 'form',
            'res_id': self.purchase_order_id.id,
            'target': 'current',
        }

    def action_open_transport_load(self):
        self.ensure_one()
        if not self.transport_load_id:
            return
            
        return {
            'name': _('Transport Load'),
            'type': 'ir.actions.act_window',
            'res_model': 'transport.load',
            'view_mode': 'form',
            'res_id': self.transport_load_id.id,
            'target': 'current',
        }

    def action_view_cost_lines(self):
        self.ensure_one()
        return {
            'name': _('Cost Lines'),
            'type': 'ir.actions.act_window',
            'res_model': 'road.assignment.line',
            'view_mode': 'list,form',
            'domain': [('road_assignment_id', '=', self.id)],
            'context': {'default_road_assignment_id': self.id},
        }

    def action_view_goods(self):
        self.ensure_one()
        return {
            'name': _('Goods Lines'),
            'type': 'ir.actions.act_window',
            'res_model': 'goods.line',
            'view_mode': 'list,form',
            'domain': [('transport_order_id', '=', self.transport_order_id.id)],
            # Note: Goods lines are on the order, not directly on assignment in model structure usually, 
            # but here they are related. 
            # Reviewing model: goods_line_ids is related='transport_order_id.goods_line_ids'
            # So we show all goods lines of the order?
            # Or filtering by assignment? Assignment usually covers the whole order or parts.
            # Request says "Show the parent order's total_billable_weight". 
            # "Clicking opens/scrolls to the Goods tab" -> Opening order's goods lines seems correct.
        }

    def action_view_events(self):
        self.ensure_one()
        return {
            'name': _('Events'),
            'type': 'ir.actions.act_window',
            'res_model': 'assignment.event',
            'view_mode': 'list,form',
            'domain': [('transport_assignment_id', '=', self.id)],
            'context': {'default_transport_assignment_id': self.id},
        }

    def generate_road_assignment_lines(self):
        """
        Generates road assignment lines using the line engine.
        This will delete old non-manual lines and create new ones
        based on the parent/child pricing logic.
        """
        for rec in self:
            _logger.info("Starting generation of road assignment lines for assignment %s", rec.number)
            
            # --- Delete old lines ---
            lines_to_delete = self.env['road.assignment.line'].search([
                ('road_assignment_id', '=', rec.id),
                ('manually_added', '=', False)
            ])
            if lines_to_delete:
                _logger.info("Deleting %d old auto-generated cost lines", len(lines_to_delete))
                lines_to_delete.unlink()
            else:
                _logger.info("No old auto-generated cost lines to delete")
    
            # --- Generate new line values from engine ---
            # This gets the *products* that should be on the assignment
            engine_lines_vals_list = self.env['road.assignment.line.engine'].generate_road_assignment_lines(rec)
            _logger.info("Engine found %d potential lines", len(engine_lines_vals_list))
    
            parent_line_map = {}  # Stores {dedup_key: {'vals': {}, 'child_vals': []}}
            all_child_product_ids = set()

            # --- Pass 1: Collect and Map All Lines ---
            _logger.info("Starting Pass 1: Collecting and mapping lines")
            for engine_line_vals in engine_lines_vals_list:
                product_id = engine_line_vals.get("product_id")
                if not product_id:
                    continue

                _logger.debug("Processing product_id %s", product_id)

                # Build source overrides from goods-line-level dimensions
                source_overrides = {}
                for dim_key in ('container_type_id', 'material_type_id', 'package_type_id', 'nmfc_class_id'):
                    if dim_key in engine_line_vals:
                        source_overrides[dim_key] = engine_line_vals[dim_key]

                # Composite dedup key: product + goods-line dimensions
                dedup_key = (
                    product_id,
                    engine_line_vals.get('container_type_id', False),
                    engine_line_vals.get('material_type_id', False),
                    engine_line_vals.get('package_type_id', False),
                    engine_line_vals.get('nmfc_class_id', False),
                )

                if dedup_key in parent_line_map:
                    _logger.debug("Dedup key %s already mapped, skipping", dedup_key)
                    continue

                try:
                    price_lines_vals_list = self.env['purchase.transport.pricing'].calculate_price_for_product(
                        product_id, rec.id,
                        source_overrides=source_overrides or None,
                    )
                except (KeyError, AttributeError) as e:
                    _logger.error(
                        "Pricing model 'purchase.transport.pricing' or method 'calculate_price_for_product' "
                        "not found. You must create this to use the new logic. Error: %s", e
                    )
                    raise ValidationError(
                        "The purchase transport pricing service is not configured. "
                        "(Model 'purchase.transport.pricing' or method 'calculate_price_for_product' is missing)."
                    )

                if not price_lines_vals_list:
                    _logger.warning("No purchase price lines found for product %s", product_id)
                    continue

                parent_vals = price_lines_vals_list[0]
                child_vals_list = price_lines_vals_list[1:]

                # Apply quantity from engine line if provided
                engine_quantity = engine_line_vals.get('quantity')
                if engine_quantity is not None:
                    parent_vals['quantity'] = engine_quantity

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
                # Ensure the road_assignment_id is set
                data['vals']['road_assignment_id'] = rec.id
                data['vals']['manually_added'] = False # Ensure it's flagged as auto-generated
                parent_record = self.env['road.assignment.line'].create(data['vals'])
                true_parent_records[dedup_key] = parent_record

            # --- Pass 3: Gather and Create All Child Lines ---
            _logger.info("Starting Pass 3: Creating child lines")
            for dedup_key, parent_record in true_parent_records.items():
                child_vals_list = parent_line_map[dedup_key]['child_vals']
                _logger.debug("Processing %d children for parent key %s", len(child_vals_list), dedup_key)
                
                for child_vals in child_vals_list:
                    child_vals['parent_line_id'] = parent_record.id
                    child_vals['road_assignment_id'] = rec.id # Also set assignment ID
                    child_vals['manually_added'] = False
                    child_lines_to_create_vals_list.append(child_vals)
    
            if child_lines_to_create_vals_list:
                _logger.info("Creating %d child lines", len(child_lines_to_create_vals_list))
                self.env['road.assignment.line'].create(child_lines_to_create_vals_list)
            else:
                _logger.info("No child lines to create")
    
            _logger.info("Finished generating road assignment lines for assignment %s", rec.number)
        return True

    def action_create_purchase_order(self):
        """
        Creates a 1-1 Purchase Order for each selected Road Assignment.
        Now includes CHILD lines (add-ons).
        """
        if not self.env.user.has_group('transport_management.group_commercial_settlement_user'):
            raise UserError(_("Only users with the Commercial Settlement role can create Purchase Orders or Vendor Bills."))
        assignments_to_process = self.filtered(lambda ra: not ra.purchase_order_id)
        
        if not assignments_to_process:
            return

        PurchaseOrder = self.env['purchase.order']
        
        inherit_param = self.env['ir.config_parameter'].sudo().get_param('transport_management.inherit_purchase_order_number_from_road_assignment')
        if inherit_param is False or inherit_param is None:
            should_inherit = False
        else:
            should_inherit = (str(inherit_param).lower() == 'true')

        for assignment in assignments_to_process:
            if not assignment.transport_carrier_id:
                continue

            po_lines_vals = []
            
            # LOOP THROUGH PARENTS
            for line in assignment.road_assignment_line_ids:
                if not line.product_id:
                    continue

                # 1. Add the PARENT Line
                po_lines_vals.append(Command.create({
                    'product_id': line.product_id.id,
                    'name': line.product_id.display_name, # Use product name, not the full description tree
                    'product_qty': line.quantity,
                    'price_unit': line.price_per_unit,
                }))

                # 2. Add the CHILD Lines (The Fix)
                for child in line.child_line_ids:   
                    po_lines_vals.append(Command.create({
                        'product_id': child.product_id.id,
                        'name': child.product_id.display_name, # Or child.description
                        'product_qty': child.quantity,
                        'price_unit': child.price_per_unit,
                    }))

            if not po_lines_vals:
                continue

            # Create Purchase Order
            vals = {
                'partner_id': assignment.transport_carrier_id.id,
                'company_id': assignment.company_id.id,
                'origin': assignment.number,
                'currency_id': assignment.assignment_currency_id.id,
                'date_order': fields.Datetime.now(),
                'order_line': po_lines_vals,
                'partner_ref': assignment.carrier_reference,
            }
            
            if should_inherit and assignment.number and assignment.number != 'New':
                vals['name'] = assignment.number
            else:
                seq_id = self.env['ir.config_parameter'].sudo().get_param('isotrax.purchase_order_sequence_id')
                if seq_id:
                    vals['name'] = self.env['ir.sequence'].sudo().browse(int(seq_id)).next_by_id()

            new_po = PurchaseOrder.create(vals)
            assignment.purchase_order_id = new_po.id
            new_po.button_confirm()
            
            assignment.message_post(body=f"Purchase Order {new_po.name} created.")

    @api.depends('purchase_order_id.invoice_ids')
    def _compute_vendor_bill_id(self):
        for assignment in self:
            if assignment.purchase_order_id:
                bills = assignment.purchase_order_id.invoice_ids.filtered(
                    lambda inv: inv.move_type == 'in_invoice'
                ).sorted(lambda inv: inv.id, reverse=True)
                assignment.vendor_bill_id = bills[0] if bills else False
            else:
                assignment.vendor_bill_id = False

    @api.depends('road_assignment_line_ids', 'purchase_order_id', 'vendor_bill_id', 'costs_approved')
    def _compute_cost_state(self):
        for assignment in self:
            if assignment.vendor_bill_id:
                assignment.cost_state = 'billed'
            elif assignment.purchase_order_id:
                assignment.cost_state = 'po_created'
            elif assignment.road_assignment_line_ids and assignment.costs_approved:
                assignment.cost_state = 'approved'
            elif assignment.road_assignment_line_ids:
                assignment.cost_state = 'priced'
            else:
                assignment.cost_state = 'unpriced'

    @api.depends_context('uid')
    def _compute_can_settle_commercial(self):
        result = self.env.user.has_group(
            'transport_management.group_commercial_settlement_user'
        )
        for rec in self:
            rec.can_settle_commercial = result

    def action_approve_costs(self):
        self.write({'costs_approved': True})

    def action_unapprove_costs(self):
        self.write({'costs_approved': False})

    def action_regenerate_prices(self):
        """
        Regenerates prices for assignments that haven't yet had a PO created.
        Resets approval so the new prices must be approved again.
        """
        for rec in self:
            if rec.purchase_order_id:
                raise ValidationError(
                    _("Cannot regenerate prices for assignment %s because a purchase order already exists.", rec.number)
                )
        self.generate_road_assignment_lines()
        self.write({'costs_approved': False})

    def action_create_vendor_bills(self):
        """
        Creates vendor bills (self-billing invoices) for selected Road Assignments
        whose transport carrier has is_self_invoice=True.
        1. Filters to self-invoice carriers only.
        2. Creates Purchase Orders if missing.
        3. Creates vendor bills from the POs.
        4. Posts the bills.
        """
        self_invoice_assignments = self.filtered(
            lambda ra: ra.transport_carrier_id and ra.transport_carrier_id.is_self_invoice
        )
        if not self_invoice_assignments:
            raise ValidationError(_("No selected assignments have a carrier marked for self-billing."))

        # Ensure POs exist
        self_invoice_assignments.action_create_purchase_order()

        # Collect POs that are ready to invoice
        purchase_orders = self_invoice_assignments.mapped('purchase_order_id')
        invoiceable_pos = purchase_orders.filtered(lambda po: po.invoice_status == 'to invoice')

        if not invoiceable_pos:
            raise ValidationError(_("No purchase orders are ready to be invoiced (they may already be invoiced)."))

        # Create vendor bills via standard Odoo method
        invoiceable_pos.action_create_invoice()

        # Collect the newly created bills
        bills = self.env['account.move']
        for po in invoiceable_pos:
            bills |= po.invoice_ids.filtered(lambda inv: inv.state == 'draft' and inv.move_type == 'in_invoice')

        # Set bill date and post; subscribe the vendor so they see them in portal
        if bills:
            bills.filtered(lambda b: not b.invoice_date).write({
                'invoice_date': fields.Date.context_today(self),
            })
            bills.action_post()
            for bill in bills:
                if bill.partner_id:
                    bill.message_subscribe(partner_ids=[bill.partner_id.commercial_partner_id.id])

        return {
            'name': _('Self-billing Invoices'),
            'type': 'ir.actions.act_window',
            'res_model': 'account.move',
            'view_mode': 'list,form',
            'domain': [('id', 'in', bills.ids)],
            'context': {'create': False},
        }

    def assign_to_new_load(self, new_load_id=None):
        """
        Assigns this assignment to a new transport load, handling the
        regeneration of stops for both the old and new loads.
        Can also be used to unassign by passing no new_load_id.
        Returns a dict with optional 'carrier_auto_assigned' key if the
        load's carrier was auto-set from the assignment.
        """
        result = {}
        for assignment in self:
            old_load = assignment.transport_load_id
            new_load = self.env['transport.load'].browse(new_load_id) if new_load_id else None

            # If the assignment is not changing, do nothing.
            if old_load == new_load:
                continue

            # Validate carrier match before assigning (skip if assignment
            # has no carrier — it will be set automatically by the load).
            if (new_load and new_load.carrier_id
                    and assignment.transport_carrier_id
                    and assignment.transport_carrier_id != new_load.carrier_id.partner_id):
                raise ValidationError(
                    _("Cannot assign to load: carrier mismatch. "
                      "Assignment carrier: %s, Load carrier: %s")
                    % (assignment.transport_carrier_id.name, new_load.carrier_id.name))

            # Case 1: Un-assigning the assignment from its load
            if not new_load:
                assignment.write({
                    'transport_load_id': False,
                    'sender_address_sequence': 0,
                    'receiver_address_sequence': 0,
                })
            # Case 2: Assigning to a new load (which also handles the write)
            else:
                # This existing method correctly calculates sequences and adds the assignment.
                # We call it to reuse the logic.
                add_result = new_load.action_add_assignments_from_selection([assignment.id])
                if add_result.get('carrier_auto_assigned'):
                    result['carrier_auto_assigned'] = add_result['carrier_auto_assigned']
                    result['load_number'] = new_load.number

            # Finally, regenerate the stops for the old load, if it existed.
            if old_load:
                old_load._generate_transport_stops()
        return result

    # ... all your other existing methods ...
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            vals['last_updated_at'] = fields.Datetime.now()
            if vals.get('state') != 'draft':
                if not vals.get('number') or vals['number'] == 'New':
                    seq_id = self.env['ir.config_parameter'].sudo().get_param('transport_management.road_assignment_sequence_id')
                    if seq_id:
                        vals['number'] = self.env['ir.sequence'].sudo().browse(int(seq_id)).next_by_id()
                    else:
                        vals['number'] = self.env['ir.sequence'].next_by_code('road.assignment') or 'New'
        recs = super().create(vals_list)
        recs.env['transport.load']._touch_loads_class(recs.mapped('transport_load_id').ids)
        recs.env['transport.order']._touch_orders_class(recs.mapped('transport_order_id').ids)

        # Auto-generate road assignment lines if enabled.
        # Skip when 'skip_auto_cost_lines' context is set — callers like
        # generate_assignments() need to fetch distances first so the
        # pricing engine can match the correct price row.
        if not self.env.context.get('skip_auto_cost_lines'):
            icp = self.env['ir.config_parameter'].sudo()
            auto_gen = icp.get_param('transport_management.auto_generate_road_assignment_lines')
            if auto_gen is False or str(auto_gen).lower() == 'true':
                engine = self.env['road.assignment.line.engine']
                for rec in recs:
                    lines_vals = engine.generate_road_assignment_lines(rec)
                    if lines_vals:
                        created_lines = self.env['road.assignment.line'].create(lines_vals)
                        for line in created_lines:
                            try:
                                line.get_price_from_contract()
                            except Exception:
                                pass

        return recs


    def unlink(self):
        # force_unlink is the soft-delete mixin's contract for a deliberate
        # permanent purge (retention cron, manager 'permanent delete'). In that
        # case the dispatch guard — which protects against accidental user
        # deletion of active assignments — must be bypassed, otherwise
        # soft-deleted records can never be purged.
        if not self.env.context.get('force_unlink'):
            non_deletable = self.filtered(lambda a: a.state not in ('draft', 'confirmed', 'cancelled') or a.state == 'closed')
            if non_deletable:
                raise UserError(_(
                    "Cannot delete assignment(s) %(numbers)s — they are already "
                    "dispatched or in progress. Cancel them first, then create "
                    "new assignments.",
                    numbers=', '.join(non_deletable.mapped('number')),
                ))
        load_ids = self.mapped('transport_load_id').ids
        order_ids = self.mapped('transport_order_id').ids
        res = super().unlink()
        if load_ids:
            self.env['transport.load']._touch_loads_class(load_ids)
        if order_ids:
            self.env['transport.order']._touch_orders_class(order_ids)
        return res

    def action_delete_from_order(self):
        """Delete assignment via button — respects same rules as unlink."""
        self.ensure_one()
        self.unlink()
        return {'type': 'ir.actions.act_window_close'}

    def action_confirm(self):
        for rec in self:
            if rec.state == "draft":
                if rec.number == 'New' or not rec.number:
                    seq_id = self.env['ir.config_parameter'].sudo().get_param('transport_management.road_assignment_sequence_id')
                    if seq_id:
                        rec.number = self.env['ir.sequence'].sudo().browse(int(seq_id)).next_by_id()
                    else:
                        rec.number = self.env['ir.sequence'].next_by_code('road.assignment') or 'New'
                rec._apply_bol_number_policy()
                rec.state = "confirmed"

    def _apply_bol_number_policy(self):
        """Populate bol_number on confirm according to the order type's policy.

        Runs only when bol_number is empty, so a manually-entered value always
        wins. 'none' leaves it empty — the BOL printout then falls back to the
        assignment number. Called after the assignment number is assigned so the
        'reuse' policy has a value to copy.
        """
        self.ensure_one()
        if self.bol_number:
            return
        order_type = self.transport_order_id.transport_order_type_id
        source = order_type.bol_number_source if order_type else 'none'
        if source == 'sequence':
            self.bol_number = self.env['ir.sequence'].next_by_code('transport.bol.number') or False
        elif source == 'reuse':
            self.bol_number = self.number or False

    def action_dispatch(self):
        """Explicit dispatch: confirmed → planned. Notifies carrier."""
        for rec in self:
            if rec.state != 'confirmed':
                raise UserError(
                    _("Cannot dispatch assignment '%s' — it must be in Confirmed state.") % rec.number
                )
            if not rec.transport_carrier_id:
                raise UserError(
                    _("Cannot dispatch assignment '%s' — a carrier must be assigned first.") % rec.number
                )
            rec.state = 'planned'
            self.env['transport.notification.service'].notify_assignment_dispatched(rec)

    def action_mass_dispatch(self):
        """Mass dispatch from list view. Only dispatches external carriers."""
        to_dispatch = self.filtered(
            lambda r: r.state == 'confirmed'
            and r.transport_carrier_id
            and r.carrier_type in ('external_planned', 'external_unplanned')
        )
        skipped_internal = self.filtered(
            lambda r: r.state == 'confirmed'
            and r.transport_carrier_id
            and r.carrier_type == 'internal'
        )
        skipped_other = self - to_dispatch - skipped_internal

        for rec in to_dispatch:
            rec.state = 'planned'
            self.env['transport.notification.service'].notify_assignment_dispatched(rec)

        # Build notification
        parts = []
        if to_dispatch:
            parts.append(_("%d assignment(s) dispatched.") % len(to_dispatch))
        if skipped_internal:
            parts.append(
                _("%d skipped — internally planned carriers are dispatched via transport loads.")
                % len(skipped_internal)
            )
        if skipped_other:
            parts.append(
                _("%d skipped — not in confirmed state or missing carrier.")
                % len(skipped_other)
            )

        msg_type = 'success' if to_dispatch and not skipped_internal else 'warning'
        if not to_dispatch and not skipped_internal:
            msg_type = 'warning'

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Dispatch'),
                'message': ' '.join(parts) or _('No assignments to dispatch.'),
                'type': msg_type,
                'sticky': bool(skipped_internal or skipped_other),
            },
        }

    def action_undispatch(self):
        """Recall a dispatched assignment: planned → confirmed.

        Only applicable to external unplanned carriers with allow_recall
        enabled. Sends a recall notification to the carrier.
        """
        for rec in self:
            if rec.state != 'planned':
                raise UserError(
                    _("Cannot recall assignment '%s' — it must be in Planned state.") % rec.number
                )
            carrier_rec = rec._get_carrier_record()
            if not carrier_rec or carrier_rec.carrier_type != 'external_unplanned':
                raise UserError(
                    _("Cannot recall assignment '%s' — recall is only available for external unplanned carriers.")
                    % rec.number
                )
            if not carrier_rec.allow_recall:
                raise UserError(
                    _("Cannot recall assignment '%s' — recall is not allowed for carrier '%s'.")
                    % (rec.number, rec.transport_carrier_id.name)
                )
            rec.state = 'confirmed'
            self.env['transport.notification.service'].notify_assignment_recalled(rec)

    def _get_carrier_record(self):
        """Look up the transport.carrier record for this assignment's carrier partner."""
        self.ensure_one()
        if not self.transport_carrier_id:
            return self.env['transport.carrier']
        return self.env['transport.carrier'].sudo().search(
            [('partner_id', '=', self.transport_carrier_id.id)], limit=1
        )

    def action_cancel(self):
        for rec in self:
            if rec.state in ('done', 'closed', 'cancelled'):
                raise UserError(
                    _("Cannot cancel assignment '%s' — it is already %s.") % (rec.number, rec.state)
                )
            rec.write({'state': 'cancelled'})

    def action_close(self):
        """Manually close a done/error assignment, locking further edits."""
        for rec in self:
            if rec.state not in ('done', 'error'):
                raise UserError(
                    _("Cannot close assignment '%s' — it must be in Done or Error state.")
                    % rec.number
                )
            rec.write({
                'pre_close_state': rec.state,
                'state': 'closed',
                'closed_date': fields.Datetime.now(),
            })

    def action_reopen(self):
        """Reopen a closed assignment (manager only). Restores the previous state.

        Controlled by the ``allow_reopen_closed`` system parameter — when
        disabled, no one can reopen closed assignments.
        """
        allow_reopen = self.env['ir.config_parameter'].sudo().get_param(
            'transport_management.allow_reopen_closed', 'False'
        ) == 'True'
        if not allow_reopen:
            raise UserError(_(
                "Reopening closed assignments is disabled. "
                "An administrator can enable this in Transport Management → Settings."
            ))
        for rec in self:
            if rec.state not in ('closed', 'done'):
                raise UserError(
                    _("Cannot reopen assignment '%s' — it must be in Done or Closed state.") % rec.number
                )
            if rec.state == 'closed':
                restore_state = rec.pre_close_state or 'done'
            else:
                restore_state = 'confirmed'
            rec.write({
                'state': restore_state,
                'closed_date': False,
                'pre_close_state': False,
            })

    def _compute_type(self):
        for rec in self:
            rec.type = ''

            if rec.transport_type_id:
                rec.type += f"{rec.transport_type_id.short_name}"
            if rec.transport_line_id:
                if rec.type != '':
                    rec.type += ' - ' + f"{rec.transport_line_id.code}"
                else:
                    rec.type += f"{rec.transport_line_id.code}"

    def _compute_duplicate_event_count(self):
        counts = self.env['assignment.event'].with_context(include_duplicates=True).read_group(
            [('transport_assignment_id', 'in', self.ids), ('is_duplicate', '=', True)],
            ['transport_assignment_id'],
            ['transport_assignment_id'],
        )
        count_map = {c['transport_assignment_id'][0]: c['transport_assignment_id_count'] for c in counts}
        for rec in self:
            rec.duplicate_event_count = count_map.get(rec.id, 0)

    def action_add_event(self):
        """Open event form as a dialog for immediate save."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _("Add Event"),
            'res_model': 'assignment.event',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_transport_assignment_id': self.id,
                'default_transport_order_id': self.transport_order_id.id,
                'default_waybill_number': self.transport_order_id.waybill_number,
                'default_event_source': 'manual',
            },
        }

    def action_view_duplicate_events(self):
        self.ensure_one()
        dup_list = self.env.ref('transport_management.view_assignment_event_duplicate_list')
        dup_form = self.env.ref('transport_management.view_assignment_event_duplicate_form')
        return {
            'type': 'ir.actions.act_window',
            'name': _("Duplicate Events — %s") % self.display_name,
            'res_model': 'assignment.event',
            'view_mode': 'list,form',
            'views': [(dup_list.id, 'list'), (dup_form.id, 'form')],
            'domain': [('transport_assignment_id', '=', self.id), ('is_duplicate', '=', True)],
            'context': {'include_duplicates': True},
        }

    def _compute_assignment_address_ids(self):
        for record in self:
            addresses = []
            if record.transport_order_id:
                if record.transport_order_id.sender_address_id:
                    addresses.append(record.transport_order_id.sender_address_id.id)
                if record.transport_order_id.receiver_address_id:
                    addresses.append(record.transport_order_id.receiver_address_id.id)

                transport_hubs = self.env['transport.hub'].search([
                    ('company_ids', 'in', record.transport_order_id.company_id.id)
                ])

                for hub in transport_hubs:
                    if hub.partner_id:
                        addresses.append(hub.partner_id.id)

            record.assignment_address_ids = [(6, 0, addresses)]

    def _compute_transport_carrier_ids(self):
        for record in self:

            carriers = []

            if record.transport_order_id:
                transport_carriers = self.env['transport.carrier'].sudo().search([
                    ('company_ids', 'in', record.transport_order_id.company_id.id)
                ])

                for carrier in transport_carriers:
                    if carrier.partner_id:
                        carriers.append(carrier.partner_id.id)

            record.transport_carrier_ids = [(6, 0, carriers)]


    def _compute_sender_address(self):
        for rec in self:
            address = ''

            if rec.sender_name:
                address = rec.sender_name or ''

            if rec.sender_street:
                if address:
                    address += ', ' + (rec.sender_street or '')
                else:
                    address += rec.sender_street or ''

            if rec.sender_city:
                if address:
                    address += ', ' + (rec.sender_city or '')
                else:
                    address += rec.sender_city or ''

            if rec.sender_country_id:
                if address:
                    address += ', ' + (rec.sender_country_id.name or '')
                else:
                    address += rec.sender_country_id.name or ''

            rec.sender_address = address

    def action_open_address_import_wizard(self):
        self.ensure_one()
        field_to_update = self.env.context.get('field_to_update')
        
        wizard = self.env['address.import.wizard'].create({
            'target_model': 'road.assignment',
            'road_assignment_id': self.id,
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
            # For assignment, maybe link to carrier if not linked to an order?
            # Or just standalone. 
            'parent_id': False 
        }
        partner = self.env['res.partner'].create(vals)
        self.sender_address_id = partner.id
        
        # Link to Carrier Address Book
        if self.transport_carrier_id:
             carrier = self.env['transport.carrier'].search([
                 ('partner_id', '=', self.transport_carrier_id.id)
             ], limit=1)
             if carrier:
                 carrier.write({'address_book_ids': [(4, partner.id)]})

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
            'parent_id': False
        }
        partner = self.env['res.partner'].create(vals)
        self.receiver_address_id = partner.id

        # Link to Carrier Address Book
        if self.transport_carrier_id:
             carrier = self.env['transport.carrier'].search([
                 ('partner_id', '=', self.transport_carrier_id.id)
             ], limit=1)
             if carrier:
                 carrier.write({'address_book_ids': [(4, partner.id)]})

    def _compute_receiver_address(self):
        for rec in self:
            address = ''

            if rec.receiver_name:
                address = rec.receiver_name or ''

            if rec.receiver_street:
                if address:
                    address += ', ' + (rec.receiver_street or '')
                else:
                    address += rec.receiver_street or ''

            if rec.receiver_city:
                if address:
                    address += ', ' + (rec.receiver_city or '')
                else:
                    address += rec.receiver_city or ''

            if rec.receiver_country_id:
                if address:
                    address += ', ' + (rec.receiver_country_id.name or '')
                else:
                    address += rec.receiver_country_id.name or ''

            rec.receiver_address = address

    def _increment_address_usage(self, address_id):
        """
        Increments usage count for an address for the carrier.
        """
        for rec in self:
            if not address_id or not rec.transport_carrier_id:
                continue
                
            # Use the carrier's partner_id as the 'customer_id' for usage tracking context
            partner = rec.transport_carrier_id
            
            usage_record = self.env['transport.address.usage'].search([
                ('customer_id', '=', partner.id),
                ('address_id', '=', address_id.id)
            ], limit=1)
            
            if usage_record:
                usage_record.usage_count += 1
            else:
                self.env['transport.address.usage'].create({
                    'customer_id': partner.id,
                    'address_id': address_id.id,
                    'usage_count': 1
                })

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
            self.fetch_distance()

    @api.onchange('receiver_address_id')
    def _onchange_receiver_address_id(self):
        if self.receiver_address_id:
            self.receiver_name = self.receiver_address_id.name
            self.receiver_street = self.receiver_address_id.street
            self.receiver_street_2 = self.receiver_address_id.street2
            self.receiver_zip = self.receiver_address_id.zip
            self.receiver_city = self.receiver_address_id.city
            self.receiver_state_id = self.receiver_address_id.state_id
            self.receiver_country_id = self.receiver_address_id.country_id
            self.receiver_latitude = self.receiver_address_id.partner_latitude
            self.receiver_longitude = self.receiver_address_id.partner_longitude
            self.receiver_phone = self.receiver_address_id.phone
            self.receiver_mobile = self.receiver_address_id.mobile
            self.receiver_email = self.receiver_address_id.email
            self.receiver_contact_person = self.receiver_address_id.name
            self.receiver_contact_phone = self.receiver_address_id.phone or self.receiver_address_id.mobile
            self.receiver_access_instructions = self.receiver_address_id.access_instructions or (self.receiver_address_id.parent_id.access_instructions if self.receiver_address_id.parent_id else False)
            self.fetch_distance()

    # Fields on road.assignment that should sync to transport.stop PU/DO stops
    _SENDER_STOP_FIELDS = {
        'sender_name', 'sender_street', 'sender_street_2', 'sender_city',
        'sender_state_id', 'sender_zip', 'sender_country_id',
        'sender_latitude', 'sender_longitude',
        'sender_phone', 'sender_mobile', 'sender_email',
        'sender_contact_person', 'sender_contact_phone', 'sender_access_instructions',
        'sender_address_id',
    }
    _RECEIVER_STOP_FIELDS = {
        'receiver_name', 'receiver_street', 'receiver_street_2', 'receiver_city',
        'receiver_state_id', 'receiver_zip', 'receiver_country_id',
        'receiver_latitude', 'receiver_longitude',
        'receiver_phone', 'receiver_mobile', 'receiver_email',
        'receiver_contact_person', 'receiver_contact_phone', 'receiver_access_instructions',
        'receiver_address_id',
    }

    def write(self, vals):
        # Closed-state lock: block ALL changes on closed assignments
        if not self.env.context.get('skip_closed_check'):
            closed_recs = self.filtered(lambda a: a.state == 'closed')
            if closed_recs:
                # Only allow state change (for reopen) and last_updated_at
                allowed_on_closed = {'state', 'pre_close_state', 'closed_date', 'last_updated_at'}
                disallowed = set(vals) - allowed_on_closed
                if disallowed:
                    raise UserError(_(
                        "Cannot modify closed assignment(s) %(numbers)s. "
                        "Reopen the assignment first.",
                        numbers=', '.join(closed_recs.mapped('number')),
                    ))

        # Tiered field locking
        if not self.env.context.get('skip_field_locking'):
            changed = set(vals)
            locked_changed = self._LOCKED_FIELDS & changed
            if locked_changed:
                locked_recs = self.filtered(lambda a: a.state not in ('draft', 'confirmed'))
                if locked_recs:
                    labels = sorted(self._fields[f].string for f in locked_changed if f in self._fields)
                    raise UserError(_(
                        "Cannot modify %(fields)s on planned/started/done assignments. "
                        "Cancel the assignment and create a new one to change these fields.",
                        fields=', '.join(labels)
                    ))

        # Capture old loads BEFORE write if transport_load_id is changing.
        # Skip if caller already provides sequences (e.g. action_add_assignments_from_selection)
        # or if context flag is set (internal sequence update from this method).
        old_loads = None
        needs_load_stop_sync = (
            'transport_load_id' in vals
            and 'sender_address_sequence' not in vals
            and not self.env.context.get('skip_load_stop_sync')
        )
        if needs_load_stop_sync:
            old_loads = {rec.id: rec.transport_load_id for rec in self}

        # For deep update, capture unconditionally ALL old loads before write
        all_old_load_ids = set(self.mapped('transport_load_id').ids)

        res = super().write(vals)

        # Generate sequence number when state is not draft and number is missing
        for rec in self:
            if rec.state != 'draft' and (rec.number in ('New', False) or not rec.number):
                seq_id = self.env['ir.config_parameter'].sudo().get_param('transport_management.road_assignment_sequence_id')
                if seq_id:
                    rec.number = self.env['ir.sequence'].sudo().browse(int(seq_id)).next_by_id()
                else:
                    rec.number = self.env['ir.sequence'].next_by_code('road.assignment') or 'New'

        # Amendment logging for controlled fields changed after draft
        if not self.env.context.get('skip_field_locking'):
            controlled_changed = self._CONTROLLED_FIELDS & set(vals)
            if controlled_changed:
                for assignment in self.filtered(lambda a: a.state != 'draft'):
                    assignment._log_amendment(controlled_changed)

        # Push notification to driver for changes on started loads
        push_changed = self._PUSH_NOTIFY_FIELDS & set(vals)
        if push_changed:
            push_svc = self.env['transport.push.notification.service']
            notified_loads = set()
            for assignment in self:
                load = assignment.transport_load_id
                if (load and load.load_status == 'started'
                        and load.id not in notified_loads):
                    notified_loads.add(load.id)
                    push_svc.notify_driver_assignment_changed(
                        load, push_changed, assignment=assignment)

        # Handle coordinate changes (existing logic)
        coordinate_fields = ['sender_latitude', 'sender_longitude', 'receiver_latitude', 'receiver_longitude']
        if any(field in vals for field in coordinate_fields):
            for order in self:
                if not order.manual_distance:
                    order.fetch_distance()

        # Handle transport_load_id changes — assign sequences + regenerate stops
        if needs_load_stop_sync and old_loads is not None:
            new_load_id = vals['transport_load_id']
            affected_old_loads = self.env['transport.load']

            for rec in self:
                old_load = old_loads.get(rec.id)
                if old_load:
                    affected_old_loads |= old_load

            if new_load_id:
                new_load = self.env['transport.load'].browse(new_load_id)
                # Re-sequence ALL assignments in PU/DO paired order:
                # A1:PU, A1:DO, A2:PU, A2:DO, ...
                # Existing keep their relative order; new ones appended.
                new_recs = self.filtered(lambda r: r.transport_load_id.id == new_load_id)
                existing = new_load.transport_assignment_ids - new_recs
                ordered = existing.sorted(lambda a: a.sender_address_sequence or 0)
                all_ordered = ordered + new_recs

                seq = 10
                for rec in all_ordered:
                    rec.with_context(skip_load_stop_sync=True).write({
                        'sender_address_sequence': seq,
                        'receiver_address_sequence': seq + 10,
                    })
                    seq += 20

                new_load._generate_transport_stops()
            else:
                # Un-assigning: reset sequences
                self.with_context(skip_load_stop_sync=True).write({
                    'sender_address_sequence': 0,
                    'receiver_address_sequence': 0,
                })

            # Regenerate stops for old loads that lost assignments
            for old_load in affected_old_loads:
                if old_load.exists():
                    old_load._generate_transport_stops()

            # Auto-dispatch / un-dispatch for internal & external_planned carriers
            if not self.env.context.get('skip_auto_dispatch'):
                if new_load_id:
                    for rec in self.filtered(lambda a: a.state == 'confirmed'):
                        carrier_rec = rec._get_carrier_record()
                        if carrier_rec and carrier_rec.carrier_type in ('internal', 'external_planned'):
                            rec.with_context(skip_auto_dispatch=True).write({'state': 'planned'})
                else:
                    for rec in self.filtered(lambda a: a.state == 'planned'):
                        carrier_rec = rec._get_carrier_record()
                        if carrier_rec and carrier_rec.carrier_type in ('internal', 'external_planned'):
                            rec.with_context(skip_auto_dispatch=True).write({'state': 'confirmed'})

        # ------------------------------------------------------------------
        # Sync address/contact changes to linked transport stops
        # (non-destructive: updates existing stops, preserves sequence/state)
        # ------------------------------------------------------------------
        sender_changed = any(f in vals for f in self._SENDER_STOP_FIELDS)
        receiver_changed = any(f in vals for f in self._RECEIVER_STOP_FIELDS)

        if (sender_changed or receiver_changed) and not self.env.context.get('skip_stop_data_sync'):
            # Regenerate stops entirely so grouping is re-evaluated
            # (consecutive stops with the same address get merged)
            affected_loads = self.mapped('transport_load_id').filtered(lambda l: l.exists())
            for load in affected_loads:
                load._generate_transport_stops()

            # Flag affected loads as potentially needing re-optimization
            loads_to_flag = affected_loads.filtered(lambda l: not l.route_stale)
            if loads_to_flag:
                loads_to_flag.write({'route_stale': True})

        # Deep update transport.load and transport.order timestamps
        all_new_load_ids = set(self.mapped('transport_load_id').ids)
        if all_old_load_ids or all_new_load_ids:
            self.env['transport.load']._touch_loads_class(list(all_old_load_ids | all_new_load_ids))
        
        self.env['transport.order']._touch_orders_class(self.mapped('transport_order_id').ids)

        # Deep update own last_updated_at
        if not self.env.context.get('skip_last_updated'):
            now = fields.Datetime.now()
            super(RoadAssignment, self.with_context(skip_last_updated=True)).write({'last_updated_at': now})

        return res

    @api.model
    def _touch_assignments_class(self, ids):
        if not ids:
            return
        # Using raw SQL to avoid recursion or interfering with regular writes
        self.env.cr.execute(
            "UPDATE road_assignment SET last_updated_at = %s WHERE id IN %s",
            (fields.Datetime.now(), tuple(set(ids)))
        )

    def _log_amendment(self, changed_fields):
        """Post an amendment note in the chatter when controlled fields change after draft."""
        labels = sorted(self._fields[f].string for f in changed_fields if f in self._fields)
        body = _("Assignment amended after confirmation. Changed fields:\n%s") % '\n'.join("• %s" % l for l in labels)
        self.message_post(body=body, message_type='notification', subtype_xmlid='mail.mt_note')

    @api.onchange('sender_latitude', 'sender_longitude', 'receiver_latitude', 'receiver_longitude')
    def _onchange_sender_coordinates(self):
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
        headers = {'Content-Type': 'application/json', 'Authorization': API_TOKEN}

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
        try:
            payload = json.dumps({"pairs": pairs})
            response = requests.post(API_URL, headers=headers, data=payload, timeout=30)
            response.raise_for_status()
            response_data = response.json()
            if response_data.get('status') == 'Success' and response_data.get('data'):
                distances = response_data['data'].get('distances', [])
        except Exception as e:
            _logger.warning("Routing distances API unavailable (%s), falling back to OSRM", str(e))

        # Fallback to OSRM if the routing service failed
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

    @api.depends('transport_carrier_id')
    def _compute_transport_carrier(self):
        for rec in self:
            rec.transport_carrier = ''

            if rec.transport_carrier_id and rec.transport_carrier_id.name:
                rec.transport_carrier = rec.transport_carrier_id.name

    @api.depends('transport_carrier_id')
    def _compute_carrier_id(self):
        Carrier = self.env['transport.carrier'].sudo()
        for rec in self:
            if rec.transport_carrier_id:
                rec.carrier_id = Carrier.search(
                    [('partner_id', '=', rec.transport_carrier_id.id)], limit=1
                )
            else:
                rec.carrier_id = False

    def _inverse_carrier_id(self):
        for rec in self:
            rec.transport_carrier_id = rec.carrier_id.partner_id if rec.carrier_id else False

    def _compute_state_from_events(self):
        """
        Recomputes the state, execution states, and proof-of-service of an
        assignment based on its remaining events.  Typically called after one
        or more events are deleted.

        The method:
        1. Recomputes proof-of-service fields from remaining events
        2. Cleans up orphaned deviations
        3. Resets execution states to not_started
        4. Replays all remaining events in chronological order to rebuild
           both the assignment state and all execution states
        5. Explicitly recomputes transport.stop states from executions
        """
        for assignment in self:
            # Skip closed/cancelled assignments — they are locked.
            if assignment.state in ('closed', 'cancelled'):
                continue

            # Invalidate ORM cache to ensure we see the current DB state
            assignment.invalidate_recordset(['event_ids'])

            # Recompute proof-of-service fields from remaining events
            assignment._recompute_proof_of_service()

            # Clean up orphaned deviations (linked to deleted events)
            orphaned_devs = assignment.deviation_ids.filtered(
                lambda d: d.event_id and not d.event_id.exists()
            )
            if orphaned_devs:
                orphaned_devs.with_context(force_unlink=True).unlink()

            old_state = assignment.state

            # Reset execution states for this assignment's stop executions.
            # Returns the affected stops so we can explicitly recompute them.
            affected_stops = assignment._reset_execution_states()

            # If there are no more events, reset to the appropriate base state.
            if not assignment.event_ids:
                if assignment.state not in ('draft', 'confirmed', 'cancelled'):
                    assignment.state = 'planned' if assignment.transport_load_id else 'confirmed'
                _logger.info(
                    "State recomputed for %s: %s → %s (no events remaining)",
                    assignment.number, old_state, assignment.state,
                )
                # Force-flush execution writes and recompute stop states
                self._flush_and_recompute_stops(affected_stops)
                if assignment.transport_order_id:
                    assignment.transport_order_id._compute_transport_order_state()
                continue

            # Reset assignment state to base level before replaying events
            assignment.state = 'planned' if assignment.transport_load_id else 'confirmed'

            # Replay ALL remaining events in chronological order to rebuild
            # both assignment state and execution states.
            remaining_events = self.env['assignment.event'].search([
                ('transport_assignment_id', '=', assignment.id)
            ], order='event_time asc, id asc')

            for event in remaining_events:
                event._apply_state_and_executions(assignment)

            _logger.info(
                "State recomputed for %s: %s → %s (%d events replayed)",
                assignment.number, old_state, assignment.state,
                len(remaining_events),
            )

            # Force-flush execution writes and recompute stop states
            self._flush_and_recompute_stops(affected_stops)

            # Recompute parent transport order state
            if assignment.transport_order_id:
                assignment.transport_order_id._compute_transport_order_state()

    def _flush_and_recompute_stops(self, stops):
        """Flush pending ORM writes and explicitly recompute stop states.

        After resetting/replaying execution states, the ORM's deferred
        recomputation of ``transport.stop.state`` (a stored computed field)
        may not fire reliably within the same transaction.  This helper
        ensures the stop states are always in sync with their executions.
        """
        if not stops:
            return
        # Flush all pending writes so execution state values are in DB
        self.env.flush_all()
        # Invalidate cached execution_ids on stops to force re-read from DB
        stops.invalidate_recordset(['execution_ids', 'state'])
        # Explicitly trigger the stored compute method
        stops._compute_state_from_executions()
        _logger.info(
            "Recomputed state for %d stop(s): %s",
            len(stops),
            {s.display_name: s.state for s in stops},
        )

    def _reset_execution_states(self):
        """Reset all stop execution states for this assignment to not_started.

        Returns:
            recordset of transport.stop records whose executions were reset
            (so callers can explicitly recompute stop states afterwards).
        """
        all_affected_stops = self.env['transport.stop']
        if not self:
            return all_affected_stops
        Execution = self.env['transport.stop.execution']
        for assignment in self:
            if not assignment.transport_load_id:
                continue
            executions = Execution.search([
                ('assignment_id', '=', assignment.id),
                ('stop_id.transport_load_id', '=', assignment.transport_load_id.id),
            ])
            if executions:
                stops = executions.mapped('stop_id')
                all_affected_stops |= stops
                old_states = {ex.id: ex.state for ex in executions}
                executions.write({'state': 'not_started'})
                _logger.info(
                    "Reset %d execution(s) to not_started for %s "
                    "(stops: %s, previous states: %s)",
                    len(executions), assignment.number,
                    stops.mapped('display_name'),
                    old_states,
                )
        return all_affected_stops

    # ── Cron: Auto-close assignments ────────────────────────────────────

    @api.model
    def _cron_close_assignments(self):
        """Close assignments that meet the configured criteria.

        Criteria (either triggers closing):
        1. Time-based: X days after done/error (actual_delivery_time or write_date)
        2. Cost settlement-based: PO or vendor bill created on the assignment
        """
        ICP = self.env['ir.config_parameter'].sudo()
        close_days = int(ICP.get_param(
            'transport_management.close_after_days', '30'))
        close_on_settlement = (
            ICP.get_param('transport_management.close_on_settlement', 'True') == 'True'
        )

        if not close_days and not close_on_settlement:
            return  # Nothing configured

        candidates = self.search([('state', 'in', ('done', 'error'))])
        to_close = self.env['road.assignment']
        now = fields.Datetime.now()

        for ra in candidates:
            # Criterion 1: Time-based
            if close_days:
                ref_time = ra.actual_delivery_time or ra.write_date
                if ref_time:
                    cutoff = now - timedelta(days=close_days)
                    if ref_time <= cutoff:
                        to_close |= ra
                        continue

            # Criterion 2: Cost settlement-based
            if close_on_settlement:
                cost_settled = ra.cost_state in ('po_created', 'billed')
                if cost_settled:
                    to_close |= ra

        if to_close:
            _logger.info(
                "Auto-closing %d assignment(s): %s",
                len(to_close), ', '.join(to_close.mapped('number')),
            )
            for ra in to_close:
                ra.with_context(skip_closed_check=True).write({
                    'pre_close_state': ra.state,
                    'state': 'closed',
                    'closed_date': now,
                })

    @api.model
    def _compute_display_name(self):
        for assignment in self:
            assignment.display_name = f"{assignment.number} - {assignment.type}"

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
            'sender_assignment'
        )

    def action_open_receiver_map(self):
        """Opens the map wizard for the receiver's location."""
        return self._action_open_map_wizard(
            self.receiver_latitude,
            self.receiver_longitude,
            self.receiver_name,
            _('Receiver Location'),
            'receiver_assignment'
        )
    @api.onchange('transport_order_id')
    def _onchange_transport_order_id_generate_lines(self):
        """
        Automatically generates cost lines when the Transport Order
        is first selected on a new Road Assignment.
        """
        # We only want this to run on a NEW, unsaved record.
        # `self.id._origin` is the check for a saved record.
        # If the record is saved, the user must use the "Generate" button.
        if self._origin:
            return

        # If no transport order is selected, clear any existing lines
        if not self.transport_order_id:
            self.road_assignment_line_ids = [(5, 0, 0)]
            return

        _logger.info("Onchange: Running line engine for new Road Assignment.")
        
        # This is the same logic your button runs.
        # Our new robust engine code can handle 'self' (a virtual record).
        engine_lines_vals = self.env['road.assignment.line.engine'].generate_road_assignment_lines(self)
        _logger.info(f"Onchange: Generated {len(engine_lines_vals)} engine line values")

        # Command to delete all existing lines in memory
        commands = [(5, 0, 0)]

        # Add all the new engine lines
        for vals in engine_lines_vals:
            commands.append((0, 0, vals))
        
        # Set the cost lines on the form
        self.road_assignment_line_ids = commands
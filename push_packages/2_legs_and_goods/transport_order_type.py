from odoo import api, fields, models

# Fields on transport.order that may be selected as "mandatory before confirm".
# Excludes: computed fields, system fields, booleans, One2many/Many2many relations,
# non-stored fields, and fields that are already validated by action_confirm().
_MANDATORY_FIELD_CANDIDATES = [
    # Core identity
    'customer_id', 'freight_service_id', 'order_reference', 'project_code',
    'waybill_number',
    # Sender address
    'sender_address_id', 'sender_name', 'sender_street', 'sender_street_2',
    'sender_city', 'sender_state_id', 'sender_zip', 'sender_country_id',
    'sender_phone', 'sender_mobile', 'sender_email', 'sender_price_zone_id',
    # Receiver address
    'receiver_address_id', 'receiver_name', 'receiver_street', 'receiver_street_2',
    'receiver_city', 'receiver_state_id', 'receiver_zip', 'receiver_country_id',
    'receiver_phone', 'receiver_mobile', 'receiver_email', 'receiver_price_zone_id',
    # Scheduling
    'pick_up_date', 'pick_up_time_from', 'pick_up_time_to',
    'delivery_date', 'delivery_time_from', 'delivery_time_to',
    # Details
    'pick_up_details', 'delivery_details', 'internal_details', 'external_details',
    'invoicing_instructions', 'invoice_reference',
    # Notification
    'notification_email', 'notification_phone',
    # Distance
    'driving_distance_km', 'driving_distance_miles',
    # Requirements
    'requirement_ids',
    # Custom fields (TO)
    'custom_char_1', 'custom_char_2', 'custom_char_3', 'custom_char_4', 'custom_char_5',
    'custom_int_1', 'custom_int_2', 'custom_int_3',
    'custom_float_1', 'custom_float_2', 'custom_float_3',
    'custom_select_1', 'custom_select_2', 'custom_select_3', 'custom_select_4', 'custom_select_5',
    # Custom fields (TORA)
    'custom_tora_char_1', 'custom_tora_char_2', 'custom_tora_char_3', 'custom_tora_char_4', 'custom_tora_char_5',
    'custom_tora_int_1', 'custom_tora_int_2', 'custom_tora_int_3',
    'custom_tora_float_1', 'custom_tora_float_2', 'custom_tora_float_3',
    'custom_tora_select_1', 'custom_tora_select_2', 'custom_tora_select_3', 'custom_tora_select_4', 'custom_tora_select_5',
]


class TransportOrderType(models.Model):
    _name = 'transport.order.type'
    _inherit = ['mail.thread', 'soft.delete.mixin']
    _description = 'Order Type'

    code = fields.Char(string="Code", required=True, tracking=True)
    name = fields.Char(string="Name", required=True, tracking=True, translate=True)
    default_pickup_duration = fields.Integer(string='Default Pickup Duration (min)', default=30)
    default_delivery_duration = fields.Integer(string='Default Delivery Duration (min)', default=30)
    bol_number_source = fields.Selection([
        ('none', 'Manual / fallback to assignment number'),
        ('sequence', 'Generate from BOL number series'),
        ('reuse', 'Reuse the assignment number'),
    ], string="BOL Number Source", default='none', tracking=True,
        help="How the Bill of Lading number is set when an assignment is confirmed, "
             "for orders of this type. The BOL number always stays editable, and an "
             "already-entered value is never overwritten.")
    company_ids = fields.Many2many('res.company', string='Company', required=False, default=lambda self: [(6, 0, self.env.user.company_ids.ids)])
    assignment_planning_criteria_ids = fields.One2many('assignment.planning.criteria', 'transport_order_type_id', string="Assignment Planning Criteria")

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
            "delivery timestamps). The driver's confirmation creates events "
            "80 (Work shift started) and 81 (Work shift ended) which set "
            "work_start_time and work_end_time on the road assignment."
        ),
    )

    require_material_reporting = fields.Boolean(
        string="Require Material Reporting",
        default=False,
        tracking=True,
        help=(
            "When enabled, the driver is asked in the mobile app to report "
            "actual delivered/picked-up quantity per goods line. The driver's "
            "input creates event 83 (Material reported) which writes "
            "goods.line.reported_quantity."
        ),
    )

    auto_plan_assignments = fields.Boolean(string="Auto Plan Assignments", default=False, tracking=True)
    default_planning_type = fields.Selection([
        ('direct', 'Direct'),
        ('hub', 'Hub-based')
    ], string="Default Leg Planning Type", default='direct', tracking=True)

    mandatory_field_ids = fields.Many2many(
        'ir.model.fields',
        string="Mandatory Fields",
        domain="[('model', '=', 'transport.order'), ('name', 'in', %s)]" % str(_MANDATORY_FIELD_CANDIDATES),
        help="Select fields that must be filled before confirming an order of this type."
    )

    goods_profile_id = fields.Many2one(
        'goods.profile', string="Goods Profile",
        help="Default goods profile for orders of this type. Controls which fields are visible on goods lines.",
    )

    requirement_ids = fields.Many2many(
        'transport.requirement', string="Default Requirements",
        help="Requirements automatically added to orders of this type.",
    )

    # ── Assignment Planning Criteria Configuration ──────────────────
    # Boolean toggles controlling which dimensions are active in the
    # criteria table (same pattern as price list configuration).
    apc_billable_weight_interval = fields.Boolean(string="Billable Weight Interval", tracking=True)
    apc_volume_interval = fields.Boolean(string="Volume Interval", tracking=True)
    apc_ldm_interval = fields.Boolean(string="LDM Interval", tracking=True)
    apc_gross_weight_interval = fields.Boolean(string="Gross Weight Interval", tracking=True)
    apc_distance_interval = fields.Boolean(string="Distance Interval", tracking=True)
    apc_sender_zip_prefix = fields.Boolean(string="Sender Zip Prefix", tracking=True)
    apc_sender_country = fields.Boolean(string="Sender Country", tracking=True)
    apc_receiver_zip_prefix = fields.Boolean(string="Receiver Zip Prefix", tracking=True)
    apc_receiver_country = fields.Boolean(string="Receiver Country", tracking=True)
    apc_customer = fields.Boolean(string="Customer", tracking=True)
    apc_company = fields.Boolean(string="APC Company", tracking=True)
    apc_sender_price_zone = fields.Boolean(string="Sender Price Zone", tracking=True)
    apc_receiver_price_zone = fields.Boolean(string="Receiver Price Zone", tracking=True)
    apc_freight_service = fields.Boolean(string="Freight Service", tracking=True)
    apc_adr = fields.Boolean(string="ADR / Dangerous Goods", tracking=True)
    apc_bulky_goods = fields.Boolean(string="Bulky Goods", tracking=True)
    apc_requirements = fields.Boolean(string="Requirements", tracking=True)

    _sql_constraints = [
        ('code_unique', 'unique(code)', 'The code must be unique!')
    ]
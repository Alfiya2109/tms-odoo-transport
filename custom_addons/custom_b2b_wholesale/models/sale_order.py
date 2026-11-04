from odoo import models, fields, api

class SaleOrder(models.Model):
    _inherit = 'sale.order'

    # Add custom PO Number to the sales order header
    x_po_number = fields.Char(string='PO Number', copy=False)


class SaleOrderLine(models.Model):
    _inherit = 'sale.order.line'

    # Custom columns for the Sales Order Line grid
    x_line_sequence = fields.Integer(string='Item No.', compute='_compute_line_sequence')
    x_product_sku = fields.Char(string='Item Number', related='product_id.default_code', readonly=True, store=True)
    x_case_price = fields.Float(string='Case Price', compute='_compute_packing_and_prices', store=True)
    x_unit_price = fields.Float(string='Unit Price', compute='_compute_packing_and_prices', store=True)

    @api.depends('order_id.order_line')
    def _compute_line_sequence(self):
        for order in self.mapped('order_id'):
            for index, line in enumerate(order.order_line):
                line.x_line_sequence = index + 1

    @api.depends('product_id', 'product_uom', 'price_unit', 'product_packaging_id')
    def _compute_packing_and_prices(self):
        for line in self:
            if not line.product_id:
                line.x_case_price = 0.0
                line.x_unit_price = 0.0
                continue

            # 1. Fetch Packing structure info from standard Odoo packaging
            pkg = line.product_packaging_id
            if pkg:
                pkg_qty = pkg.qty or 1.0
            else:
                # Fallback to the first available packaging on the product template
                packagings = line.product_id.packaging_ids
                if packagings:
                    pkg_qty = packagings[0].qty or 1.0
                else:
                    pkg_qty = 1.0

            # 2. Case Price and Unit Price logic
            # Unit Price is standard Odoo line price_unit
            line.x_unit_price = line.price_unit

            # Case Price is Unit Price multiplied by package qty
            line.x_case_price = line.price_unit * pkg_qty

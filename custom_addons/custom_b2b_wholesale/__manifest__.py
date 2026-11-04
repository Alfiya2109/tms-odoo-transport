{
    'name': 'B2B Wholesale Customizations (Curated Flavours)',
    'version': '1.0',
    'category': 'Sales',
    'summary': 'Custom Sales Grid, UoM Pricing, and Layout optimizations for Curated Flavours Inc.',
    'description': """
This module implements the custom requirements for Curated Flavours Inc.
- Custom PO Number in Sales Orders & Invoices.
- Custom columns in Sales Order Lines (Case Price, Unit Price, Packing).
- Automatic price calculation during UoM switching.
- Tax columns hidden from Sales Views.
    """,
    'author': 'Antigravity AI / Developer',
    'depends': ['sale', 'account', 'stock'],
    'data': [
        'views/sale_order_views.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'custom_b2b_wholesale/static/src/css/custom_style.css',
        ],
    },
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
}
